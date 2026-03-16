import os

from fastapi import FastAPI, HTTPException, Query
from models import (
    LocationCheckRequest,
    LocationCheckResponse,
    HazardZonesLoadRequest,
    LoadResultResponse,
)
from geofence_service import geofence_service

app = FastAPI(title="Louisiana Weather Geofence API")

@app.on_event("startup")
def startup_event():
    print("Starting geofence service...")
    # DISABLED FOR MANUAL TESTING
    # geofence_service.update_geofences()
    # geofence_service.update_wpc_polygons()
    print("Automatic updates disabled. Use manual testing in Python IDE.")

@app.get("/health")
def health():
    return {"status": "running"}

@app.get("/geofences")
def get_geofences():
    return geofence_service.get_geofences()

@app.post("/check-location", response_model=LocationCheckResponse)
def check_location(request: LocationCheckRequest):
    inside, event, severity = geofence_service.check_location(
        request.user_lat,
        request.user_lon
    )

    return LocationCheckResponse(
        inside=inside,
        event=event,
        severity=severity
    )

# ---------------------------------------------------------------------------
# Hazard-zone loader endpoints
# ---------------------------------------------------------------------------

@app.post("/hazard-zones/load", response_model=LoadResultResponse)
def load_hazard_zones(request: HazardZonesLoadRequest):
    """
    Load ML-predicted or developer-provided hazard zones (GeoJSON polygons)
    directly into the in-memory cache.

    - **replace** (default ``true``): when true the cache is replaced; when
      false the zones are appended to existing entries.
    - **hazard_zones**: list of zone objects with ``event``, optional
      ``severity``, and a GeoJSON ``geometry`` (Polygon or MultiPolygon).
    """
    try:
        zones = [z.model_dump() for z in request.hazard_zones]
        loaded = geofence_service.load_hazard_zones(zones, replace_cache=request.replace)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return LoadResultResponse(
        loaded=loaded,
        cache_size=geofence_service.count(),
        replaced=request.replace,
        source="hazard_zones",
    )


@app.post("/hazard-zones/load-demo", response_model=LoadResultResponse)
def load_hazard_zones_demo():
    """
    Load built-in sample hazard zones from ``fixtures/sample_hazard_zones.json``
    into the in-memory cache (replaces existing entries).

    Useful for testing without live NWS/WPC API access.
    """
    # Resolve fixture path relative to this file so it works regardless of cwd
    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "sample_hazard_zones.json")
    if not os.path.exists(fixture_path):
        raise HTTPException(status_code=500, detail="Demo fixture file not found.")

    try:
        loaded = geofence_service.load_hazard_zones_from_file(fixture_path, replace_cache=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return LoadResultResponse(
        loaded=loaded,
        cache_size=geofence_service.count(),
        replaced=True,
        source="demo_fixture",
    )


# ---------------------------------------------------------------------------
# Upstream API loader endpoints (NWS + WPC)
# ---------------------------------------------------------------------------

@app.post("/geofences/load/nws", response_model=LoadResultResponse)
def load_nws(replace: bool = Query(default=True, description="Replace cache (true) or append (false)")):
    """
    Trigger a live fetch of current NWS alerts into the in-memory cache.

    NWS ``update_geofences()`` always replaces the cache internally; the
    ``replace`` query parameter is accepted for API consistency but the
    underlying NWS loader always performs a full replacement.
    """
    try:
        geofence_service.update_geofences()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"NWS load failed: {exc}")

    cache_size = geofence_service.count()
    return LoadResultResponse(
        loaded=cache_size,
        cache_size=cache_size,
        replaced=True,
        source="nws",
    )


@app.post("/geofences/load/wpc", response_model=LoadResultResponse)
def load_wpc(
    day: int = Query(default=1, ge=1, le=5, description="WPC ERO outlook day (1–5)"),
    replace: bool = Query(default=True, description="Replace cache (true) or append (false)"),
):
    """
    Download and load the WPC Excessive Rainfall Outlook KMZ for the given day.

    - **day** (1–5, default 1): outlook day to fetch.
    - **replace** (default ``true``): replace or append to existing cache.
    """
    try:
        loaded = geofence_service.load_wpc_kmz(day=day, replace_cache=replace)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"WPC load failed: {exc}")

    return LoadResultResponse(
        loaded=loaded,
        cache_size=geofence_service.count(),
        replaced=replace,
        source=f"wpc_day{day}",
    )

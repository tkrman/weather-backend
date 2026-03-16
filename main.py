import json
import os
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from models import (
    LocationCheckRequest,
    LocationCheckResponse,
    LoadHazardZonesRequest,
    LoadHazardZonesResponse,
)
from geofence_service import geofence_service

app = FastAPI(title="Louisiana Weather Geofence API")

_FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
_SAMPLE_HAZARD_ZONES_PATH = os.path.join(_FIXTURES_DIR, "sample_hazard_zones.json")


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


@app.post("/geofences/load", response_model=LoadHazardZonesResponse)
def load_hazard_zones(request: LoadHazardZonesRequest):
    """
    Load hazard-zone polygons directly into the in-memory cache.

    Intended for:
      - ML pipeline POSTing predicted hazard zones after each inference run.
      - Developers testing without live NWS/WPC API access.

    Set ``replace`` to ``true`` (default) to swap out the cache entirely, or
    ``false`` to append to the existing cache.
    """
    zones = [zone.model_dump() for zone in request.hazard_zones]
    loaded = geofence_service.load_hazard_zones(zones, replace=request.replace)
    action = "replaced" if request.replace else "appended"
    return LoadHazardZonesResponse(
        loaded=loaded,
        replaced=request.replace,
        message=f"Successfully {action} cache with {loaded} hazard zone(s).",
    )


@app.post("/geofences/load-demo", response_model=LoadHazardZonesResponse)
def load_demo_hazard_zones():
    """
    Load the built-in sample hazard zones from ``fixtures/sample_hazard_zones.json``
    into the in-memory cache.

    Useful for developers testing without live NWS/WPC API access.
    """
    try:
        with open(_SAMPLE_HAZARD_ZONES_PATH, "r") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="Sample hazard zones fixture file not found.")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to parse fixture file: {exc}")

    replace = data.get("replace", True)
    zones = data.get("hazard_zones", [])
    loaded = geofence_service.load_hazard_zones(zones, replace=replace)
    action = "replaced" if replace else "appended"
    return LoadHazardZonesResponse(
        loaded=loaded,
        replaced=replace,
        message=f"Demo data loaded: {action} cache with {loaded} hazard zone(s).",
    )


@app.post("/geofences/load-nws", response_model=LoadHazardZonesResponse)
def load_nws_hazard_zones():
    """
    Fetch current NWS alerts from the configured ``NWS_ALERTS_URL`` and load
    polygonal alerts into the in-memory cache, replacing any existing data.
    """
    geofence_service.update_geofences()
    after = geofence_service.count()
    return LoadHazardZonesResponse(
        loaded=after,
        replaced=True,
        message=f"NWS alerts loaded: replaced cache with {after} hazard zone(s).",
    )


@app.post("/geofences/load-wpc", response_model=LoadHazardZonesResponse)
def load_wpc_hazard_zones(
    day: int = Query(default=1, ge=1, le=5, description="WPC ERO outlook day (1–5)"),
    replace: bool = Query(default=True, description="Replace cache (true) or append (false)"),
):
    """
    Download the latest WPC Excessive Rainfall Outlook KMZ for the given day
    (1–5, default 1) and load the polygons into the in-memory cache.
    """
    loaded = geofence_service.load_wpc_kmz(day=day, replace_cache=replace)
    if loaded == 0:
        raise HTTPException(
            status_code=502,
            detail=f"WPC Day {day} KMZ returned 0 polygons. "
                   "The outlook may not be available yet; try a different day.",
        )
    action = "replaced" if replace else "appended"
    return LoadHazardZonesResponse(
        loaded=loaded,
        replaced=replace,
        message=f"WPC Day {day} ERO loaded: {action} cache with {loaded} hazard zone(s).",
    )

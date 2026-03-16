from fastapi import FastAPI, HTTPException
from models import (
    LocationCheckRequest,
    LocationCheckResponse,
    LoadHazardZonesRequest,
    LoadFromApiRequest,
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

@app.post("/geofences/load-hazard-zones")
def load_hazard_zones(request: LoadHazardZonesRequest):
    """
    Load hazard-zone polygons directly into the in-memory cache.

    Intended for the ML pipeline (after each inference run) and for
    developers testing without live NWS/WPC API access.
    """
    zones = [zone.model_dump() for zone in request.hazard_zones]
    loaded = geofence_service.load_hazard_zones(zones, replace=request.replace)
    return {"loaded": loaded, "replace": request.replace}

@app.post("/geofences/load-demo")
def load_demo():
    """
    Load the built-in sample hazard zones (fixtures/sample_hazard_zones.json)
    into the in-memory cache. Replaces any existing cached polygons.
    """
    loaded = geofence_service.load_demo_data(replace=True)
    return {"loaded": loaded, "source": "demo"}

@app.post("/geofences/load-from-api")
def load_from_api(request: LoadFromApiRequest):
    """
    Trigger loading of live hazard-zone data from NWS or WPC APIs.

    - source="nws"  → current NWS active alerts (polygon features only)
    - source="wpc"  → WPC Excessive Rainfall Outlook KMZ for `wpc_day` (1..5)
    """
    source = request.source.lower()

    if source == "nws":
        geofence_service.update_geofences()
        loaded = geofence_service.count()
        return {"loaded": loaded, "source": "nws", "replace": request.replace}

    if source == "wpc":
        if request.wpc_day not in (1, 2, 3, 4, 5):
            raise HTTPException(status_code=422, detail="wpc_day must be between 1 and 5")
        loaded = geofence_service.load_wpc_kmz(day=request.wpc_day, replace_cache=request.replace)
        return {"loaded": loaded, "source": "wpc", "wpc_day": request.wpc_day, "replace": request.replace}

    raise HTTPException(status_code=422, detail="source must be 'nws' or 'wpc'")

from fastapi import FastAPI
from models import LocationCheckRequest, LocationCheckResponse
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

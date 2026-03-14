import datetime
import json
import logging
import pathlib

from fastapi import Depends, FastAPI, HTTPException
from shapely.geometry import shape
from sqlalchemy.orm import Session

from database import UserDevice, get_db, init_db
from geofence_service import geofence_service
from models import (
    DeviceRegistrationRequest,
    DeviceRegistrationResponse,
    GeofenceIngestRequest,
    GeofenceIngestResponse,
    HazardNotificationResponse,
    LocationCheckRequest,
    LocationCheckResponse,
    LocationUpdateRequest,
    LocationUpdateResponse,
    NotificationResultItem,
)
from notification_service import send_hazard_notifications_batch

logger = logging.getLogger(__name__)

app = FastAPI(title="Louisiana Weather Geofence API")

# Path to the bundled sample-data fixture (used by /geofences/load-demo)
_FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures"
_SAMPLE_HAZARD_ZONES_FILE = _FIXTURES_DIR / "sample_hazard_zones.json"


@app.on_event("startup")
def startup_event():
    print("Starting geofence service...")
    init_db()
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


@app.get("/geofences/count")
def get_geofences_count():
    """Return the number of hazard-zone polygons currently loaded in the cache."""
    return {"count": geofence_service.count()}


@app.post("/geofences/load", response_model=GeofenceIngestResponse, status_code=200)
def load_geofences(request: GeofenceIngestRequest):
    """
    Load hazard-zone polygons directly into the in-memory cache.

    **Primary use-cases:**
    - The ML pipeline POSTs its predicted hazard zones here after each inference run.
    - Developers testing without live NWS/WPC API access can POST sample GeoJSON
      polygons (or use ``POST /geofences/load-demo`` for the built-in sample data).

    Payload shape (mirrors ``fixtures/sample_hazard_zones.json``)::

        {
          "replace": true,
          "hazard_zones": [
            {
              "event": "Tornado Warning",
              "severity": "Extreme",
              "geometry": {
                "type": "Polygon",
                "coordinates": [[[-91.25, 30.35], [-90.95, 30.35], ...]]
              }
            }
          ]
        }
    """
    polygons = []
    skipped = 0
    for zone in request.hazard_zones:
        try:
            shp = shape(zone.geometry)
            if shp.is_empty:
                raise ValueError("geometry is empty (no coordinates)")
        except Exception as exc:
            logger.warning("Skipping zone '%s' — invalid geometry: %s", zone.event, exc)
            skipped += 1
            continue
        polygons.append(
            {
                "event": zone.event,
                "severity": zone.severity,
                "geometry": zone.geometry,
                "polygon": shp,
            }
        )

    if request.replace:
        geofence_service.set_polygons(polygons)
    else:
        with geofence_service.lock:
            geofence_service.cached_polygons.extend(polygons)

    total = geofence_service.count()
    logger.info(
        "Geofence ingest: loaded=%d skipped=%d replace=%s total_cached=%d",
        len(polygons), skipped, request.replace, total,
    )

    return GeofenceIngestResponse(
        loaded=len(polygons),
        total_cached=total,
        replaced=request.replace,
        message=(
            f"Loaded {len(polygons)} hazard zone(s)"
            + (f" ({skipped} skipped due to invalid geometry)" if skipped else "")
            + f". Cache now holds {total} zone(s)."
        ),
    )


@app.post("/geofences/load-demo", response_model=GeofenceIngestResponse, status_code=200)
def load_demo_geofences():
    """
    Load the built-in sample Louisiana hazard zones for offline testing.

    Replaces the current cache with four representative zones (Tornado Warning,
    Flash Flood Warning, Excessive Rainfall Outlook, Severe Thunderstorm Warning)
    spread across Louisiana.  No live APIs, database, or ML pipeline required.

    After calling this endpoint you can immediately test:
    - ``GET  /geofences``                         — list the loaded zones
    - ``POST /check-location``                    — check a coordinate against them
    - ``POST /users/register``                    — register a test device
    - ``PUT  /users/{id}/location``               — move device into/out of a zone
    - ``POST /notifications/send-hazard-alerts``  — trigger (mock) FCM alerts
    """
    try:
        raw = json.loads(_SAMPLE_HAZARD_ZONES_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not read sample fixture: {exc}") from exc

    ingest = GeofenceIngestRequest(hazard_zones=raw["hazard_zones"], replace=True)
    return load_geofences(ingest)


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
# Device / user registration
# ---------------------------------------------------------------------------

@app.post("/users/register", response_model=DeviceRegistrationResponse, status_code=201)
def register_device(request: DeviceRegistrationRequest, db: Session = Depends(get_db)):
    """
    Register (or re-register) a user's device with its FCM token and current
    GPS location.  If the token already exists the record is updated in place.
    """
    existing: UserDevice | None = (
        db.query(UserDevice)
        .filter(UserDevice.device_token == request.device_token)
        .first()
    )

    if existing:
        existing.last_lat = request.lat
        existing.last_lon = request.lon
        existing.updated_at = datetime.datetime.now(datetime.timezone.utc)
        db.commit()
        db.refresh(existing)
        return DeviceRegistrationResponse(
            user_id=existing.id,
            device_token=existing.device_token,
            lat=existing.last_lat,
            lon=existing.last_lon,
            message="Device updated",
        )

    user = UserDevice(
        device_token=request.device_token,
        last_lat=request.lat,
        last_lon=request.lon,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return DeviceRegistrationResponse(
        user_id=user.id,
        device_token=user.device_token,
        lat=user.last_lat,
        lon=user.last_lon,
        message="Device registered",
    )


@app.put("/users/{user_id}/location", response_model=LocationUpdateResponse)
def update_location(
    user_id: int,
    request: LocationUpdateRequest,
    db: Session = Depends(get_db),
):
    """
    Update a user's last known location and return whether they are currently
    inside a hazard zone.
    """
    user: UserDevice | None = db.query(UserDevice).filter(UserDevice.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.last_lat = request.lat
    user.last_lon = request.lon
    user.updated_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()
    db.refresh(user)

    inside, event, severity = geofence_service.check_location(request.lat, request.lon)

    return LocationUpdateResponse(
        user_id=user.id,
        lat=request.lat,
        lon=request.lon,
        inside_hazard=inside,
        event=event,
        severity=severity,
    )


# ---------------------------------------------------------------------------
# Hazard-zone notifications
# ---------------------------------------------------------------------------

@app.post("/notifications/send-hazard-alerts", response_model=HazardNotificationResponse)
def send_hazard_alerts(db: Session = Depends(get_db)):
    """
    Check every registered user's last known location against the cached
    hazard-zone geofences and send FCM push notifications to those inside
    a hazard zone.

    Returns a summary of how many notifications were sent and their outcomes.
    """
    users = db.query(UserDevice).all()

    tokens_to_notify = []
    for user in users:
        if user.last_lat is None or user.last_lon is None:
            continue
        inside, event, severity = geofence_service.check_location(
            user.last_lat, user.last_lon
        )
        if inside:
            tokens_to_notify.append(
                {
                    "token": user.device_token,
                    "event": event or "Weather Alert",
                    "severity": severity or "Unknown",
                }
            )

    result = send_hazard_notifications_batch(tokens_to_notify)

    notification_items = [
        NotificationResultItem(
            token_preview=r["token_preview"],
            success=r["success"],
            error=r.get("error"),
        )
        for r in result.get("results", [])
    ]

    return HazardNotificationResponse(
        notified_users=len(tokens_to_notify),
        success_count=result["success_count"],
        failure_count=result["failure_count"],
        firebase_configured=result["firebase_configured"],
        results=notification_items,
    )

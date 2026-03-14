import datetime
import logging

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.orm import Session

from database import UserDevice, get_db, init_db
from geofence_service import geofence_service
from models import (
    DeviceRegistrationRequest,
    DeviceRegistrationResponse,
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

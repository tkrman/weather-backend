from pydantic import BaseModel, Field
from typing import Any, List


class LocationCheckRequest(BaseModel):
    user_lat: float
    user_lon: float


class LocationCheckResponse(BaseModel):
    inside: bool
    event: str | None = None
    severity: str | None = None


class GeofenceResponse(BaseModel):
    event: str
    severity: str
    geometry: Any


# ---------------------------------------------------------------------------
# Device / user registration
# ---------------------------------------------------------------------------

class DeviceRegistrationRequest(BaseModel):
    device_token: str = Field(..., description="Firebase Cloud Messaging (FCM) device token")
    lat: float = Field(..., description="Initial latitude of the device")
    lon: float = Field(..., description="Initial longitude of the device")


class DeviceRegistrationResponse(BaseModel):
    user_id: int
    device_token: str
    lat: float | None = None
    lon: float | None = None
    message: str


# ---------------------------------------------------------------------------
# Location update
# ---------------------------------------------------------------------------

class LocationUpdateRequest(BaseModel):
    lat: float
    lon: float


class LocationUpdateResponse(BaseModel):
    user_id: int
    lat: float
    lon: float
    inside_hazard: bool
    event: str | None = None
    severity: str | None = None


# ---------------------------------------------------------------------------
# Hazard notifications
# ---------------------------------------------------------------------------

class NotificationResultItem(BaseModel):
    token_preview: str
    success: bool
    error: str | None = None


class HazardNotificationResponse(BaseModel):
    notified_users: int
    success_count: int
    failure_count: int
    firebase_configured: bool
    results: List[NotificationResultItem] = []

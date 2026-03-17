from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, Field


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
    effective: str | None = Field(
        None,
        description="ISO 8601 datetime when the alert became effective (NWS alerts only)",
    )
    onset: str | None = Field(
        None,
        description="ISO 8601 datetime when the hazard event is expected to begin (NWS alerts only)",
    )
    expires: str | None = Field(
        None,
        description="ISO 8601 datetime when the alert expires (NWS alerts only)",
    )


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


# ---------------------------------------------------------------------------
# Geofence ingest (ML pipeline / manual test data)
# ---------------------------------------------------------------------------

class HazardZoneItem(BaseModel):
    """A single hazard zone as produced by the ML pipeline or posted manually for testing."""
    event: str = Field(..., description="Alert type, e.g. 'Tornado Warning'")
    severity: str = Field(..., description="Severity level, e.g. 'Extreme', 'SLGT'")
    geometry: Dict[str, Any] = Field(
        ...,
        description="GeoJSON geometry object with 'type' and 'coordinates' keys",
    )


class GeofenceIngestRequest(BaseModel):
    """
    Payload accepted by POST /geofences/load.

    The ML pipeline (or a developer testing manually) sends this to replace or
    extend the in-memory hazard-zone cache without needing live NWS/WPC API access.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "replace": True,
                "hazard_zones": [
                    {
                        "event": "Tornado Warning",
                        "severity": "Extreme",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [-91.25, 30.35],
                                    [-90.95, 30.35],
                                    [-90.95, 30.55],
                                    [-91.25, 30.55],
                                    [-91.25, 30.35],
                                ]
                            ],
                        },
                    }
                ],
            }
        }
    )

    hazard_zones: List[HazardZoneItem] = Field(
        ..., description="List of hazard zones to load into the cache"
    )
    replace: bool = Field(
        True,
        description="If true (default), the current cache is replaced. If false, zones are appended.",
    )


class GeofenceIngestResponse(BaseModel):
    loaded: int
    total_cached: int
    replaced: bool
    message: str
    fetched_at: str = Field(
        ...,
        description="ISO 8601 UTC datetime when this ingest request was processed",
    )

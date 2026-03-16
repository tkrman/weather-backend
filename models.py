from pydantic import BaseModel
from typing import Any, List, Optional


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
# Hazard-zone loader models
# ---------------------------------------------------------------------------

class HazardZoneIn(BaseModel):
    """A single hazard zone entry supplied by an ML pipeline or developer."""
    event: str
    severity: Optional[str] = None
    geometry: Any  # Expected: GeoJSON Polygon or MultiPolygon dict


class HazardZonesLoadRequest(BaseModel):
    """Request body for POST /hazard-zones/load."""
    replace: bool = True
    hazard_zones: List[HazardZoneIn]


class LoadResultResponse(BaseModel):
    """Response returned by all hazard-zone and geofence loader endpoints."""
    loaded: int
    cache_size: int
    replaced: bool
    source: Optional[str] = None

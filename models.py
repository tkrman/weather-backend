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


class HazardZoneItem(BaseModel):
    event: str
    severity: Optional[str] = None
    geometry: Any


class LoadHazardZonesRequest(BaseModel):
    replace: bool = True
    hazard_zones: List[HazardZoneItem]


class LoadHazardZonesResponse(BaseModel):
    loaded: int
    replaced: bool
    message: str

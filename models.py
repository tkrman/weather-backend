from pydantic import BaseModel
from typing import Any, Dict, List, Optional


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


class HazardZone(BaseModel):
    event: str
    severity: Optional[str] = None
    geometry: Dict[str, Any]


class LoadHazardZonesRequest(BaseModel):
    hazard_zones: List[HazardZone]
    replace: bool = True


class LoadFromApiRequest(BaseModel):
    source: str = "nws"          # "nws" | "wpc"
    wpc_day: int = 1             # 1..5, only used when source="wpc"
    replace: bool = True

from pydantic import BaseModel
from typing import Any


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

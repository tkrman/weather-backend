from pydantic import BaseModel
from typing import Any, Optional


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


class LLMSummarizeRequest(BaseModel):
    lat: float
    lon: float


class LLMSummarizeResponse(BaseModel):
    inside: bool
    event: Optional[str] = None
    severity: Optional[str] = None
    summary: str

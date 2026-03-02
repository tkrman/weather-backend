# geofence_service.py
from __future__ import annotations

import io
import threading
import zipfile
from typing import Any, Dict, List, Optional, Tuple

import requests
from shapely.geometry import Point, shape, Polygon, MultiPolygon
from shapely.geometry.base import BaseGeometry
from fastkml import kml

from config import NWS_ALERTS_URL, REFRESH_INTERVAL_SECONDS, USER_AGENT


DEFAULT_TIMEOUT = 15  # seconds

# WPC ERO KMZ template (Day 1..5). You primarily use Day 1..3.
WPC_ERO_KMZ_URL_TEMPLATE = (
    "https://www.wpc.ncep.noaa.gov/kml/ero/Day_{day}_Excessive_Rainfall_Outlook.kmz"
)


class GeofenceService:
    """
    Service for fetching, caching, and querying weather geofences.

    Supported sources:
      • NWS Alerts (current or historical window) — polygon features only
      • WPC Excessive Rainfall Outlook (Day 1..5) via KMZ/KML

    Cache layout:
      cached_polygons: List[{
          "event": str,                 # e.g., Tornado Warning, Excessive Rainfall Outlook
          "severity": Optional[str],    # e.g., Severe/Extreme or MRGL/SLGT/MDT/HIGH
          "geometry": Dict[str, Any],   # GeoJSON geometry
          "polygon": shapely geometry   # shapely Polygon/MultiPolygon
      }]
    """

    def __init__(self) -> None:
        self.cached_polygons: List[Dict[str, Any]] = []
        self.lock = threading.Lock()

    # ------------------------------------------------------------------
    # Internal HTTP helper
    # ------------------------------------------------------------------
    def _http_get_json(self, url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        headers = {"User-Agent": USER_AGENT}
        resp = requests.get(url, headers=headers, params=params, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # NWS (current) alerts loader  — polygon-only
    # ------------------------------------------------------------------
    def fetch_alerts(self) -> Dict[str, Any]:
        """Fetch the configured NWS alerts JSON from NWS_ALERTS_URL."""
        return self._http_get_json(NWS_ALERTS_URL)

    def update_geofences(self) -> None:
        """
        Load *current* alerts from NWS_ALERTS_URL into cache, keeping only polygonal alerts.
        (Auto-refresh scheduling remains disabled for manual testing.)
        """
        try:
            data = self.fetch_alerts()
            polygons: List[Dict[str, Any]] = []

            for feature in data.get("features", []):
                geometry = feature.get("geometry")
                props = feature.get("properties", {}) or {}

                if not geometry:
                    # Many alerts are geocode-only (county/zone) with no geometry; skip them
                    continue

                gtype = geometry.get("type")
                if gtype not in ("Polygon", "MultiPolygon"):
                    continue

                try:
                    shp: BaseGeometry = shape(geometry)
                except Exception as exc:
                    print(f"[WARN] Failed to parse geometry into Shapely shape: {exc}")
                    continue

                polygons.append(
                    {
                        "event": props.get("event"),
                        "severity": props.get("severity"),
                        "geometry": geometry,
                        "polygon": shp,
                    }
                )

            with self.lock:
                self.cached_polygons = polygons

            print(f"[INFO] Updated {len(polygons)} geofences from NWS current alerts.")

        except Exception as e:
            print(f"[ERROR] update_geofences failed: {e}")

        # Manual mode by design
        # threading.Timer(REFRESH_INTERVAL_SECONDS, self.update_geofences).start()

    # ------------------------------------------------------------------
    # NWS historical alerts loader — polygon-only
    # ------------------------------------------------------------------
    def load_historical_alerts(
        self, start_iso: str, end_iso: str, area: Optional[str] = None, limit: int = 500
    ) -> None:
        """
        Load NWS alerts issued between start_iso and end_iso (ISO8601 UTC).
        Optionally filter by 2-letter state 'area' (e.g., 'LA'); use None for nationwide.
        Only polygonal alerts are kept. Replaces the current cache.

        This follows the alerts API pagination via 'pagination.next' cursor.
        """
        try:
            url = "https://api.weather.gov/alerts"
            params: Dict[str, Any] = {"start": start_iso, "end": end_iso, "limit": str(limit)}
            if area:
                params["area"] = area

            polygons: List[Dict[str, Any]] = []
            cursor: Optional[str] = None

            while True:
                q = dict(params)
                if cursor:
                    q["cursor"] = cursor

                data = self._http_get_json(url, params=q)

                for feature in data.get("features", []):
                    geometry = feature.get("geometry")
                    props = feature.get("properties", {}) or {}
                    if not geometry:
                        continue

                    gtype = geometry.get("type")
                    if gtype not in ("Polygon", "MultiPolygon"):
                        continue

                    try:
                        shp: BaseGeometry = shape(geometry)
                    except Exception as exc:
                        print(f"[WARN] Failed to parse historical geometry: {exc}")
                        continue

                    polygons.append(
                        {
                            "event": props.get("event"),
                            "severity": props.get("severity"),
                            "geometry": geometry,
                            "polygon": shp,
                        }
                    )

                cursor = (data.get("pagination") or {}).get("next")
                if not cursor:
                    break

            with self.lock:
                self.cached_polygons = polygons

            print(
                f"[INFO] [Historical] Loaded {len(polygons)} alert polygons from "
                f"{start_iso} to {end_iso} (area={area or 'ALL'})."
            )

        except Exception as e:
            print(f"[ERROR] load_historical_alerts failed: {e}")

    # ------------------------------------------------------------------
    # WPC ERO (KMZ/KML) helpers & loaders
    # ------------------------------------------------------------------
    @staticmethod
    def _standardize_ero_category(name: Optional[str]) -> str:
        """
        Normalize WPC ERO category from placemark name.
        Expected: MRGL, SLGT, MDT, HIGH; but sometimes spelled out.
        """
        if not name:
            return "UNKNOWN"
        u = name.strip().upper()
        if "MRGL" in u or "MARGINAL" in u:
            return "MRGL"
        if "SLGT" in u or "SLIGHT" in u:
            return "SLGT"
        if "MDT" in u or "MODERATE" in u:
            return "MDT"
        if "HIGH" in u:
            return "HIGH"
        return u

    def _parse_wpc_kmz_bytes(self, kmz_bytes: bytes, day: int) -> List[Dict[str, Any]]:
        """
        Parse a WPC ERO KMZ payload into our cached_polygons record list.
        Returns a list of objects shaped like cached_polygons entries:
          { "event", "severity", "geometry", "polygon" }
        """
        # 1) Extract KML bytes
        try:
            with zipfile.ZipFile(io.BytesIO(kmz_bytes), "r") as zf:
                kml_name = "doc.kml"
                if kml_name not in zf.namelist():
                    # Fallback to first *.kml present
                    kml_candidates = [n for n in zf.namelist() if n.lower().endswith(".kml")]
                    if not kml_candidates:
                        raise RuntimeError("KMZ has no KML file inside.")
                    kml_name = kml_candidates[0]
                kml_bytes = zf.read(kml_name)
        except Exception as e:
            raise RuntimeError(f"Failed to extract KML from KMZ: {e}") from e

        # 2) Parse KML -> Shapely via fastkml
        try:
            doc = kml.KML()
            doc.from_string(kml_bytes)
        except Exception as e:
            raise RuntimeError(f"Failed to parse KML: {e}") from e

        # 3) Robust iterator (supports fastkml where .features is a method OR a list)
        def _iter_features(obj):
            """
            Yield nested features for both fastkml styles:
            - .features is a callable (older style)
            - .features is a list-like property (newer style)
            """
            children = None
            if hasattr(obj, "features"):
                children = obj.features
                if callable(children):
                    children = children()
            if children:
                for f in children:
                    yield f
                    yield from _iter_features(f)

        polygons: List[Dict[str, Any]] = []

        # 4) Collect placemarks that actually have polygon geometry
        for node in _iter_features(doc):
            if not hasattr(node, "geometry"):
                continue
            geom = getattr(node, "geometry", None)
            if geom is None:
                continue

            shp = geom  # fastkml already returns a Shapely geometry
            if isinstance(shp, Polygon):
                shp = MultiPolygon([shp])

            severity = self._standardize_ero_category(getattr(node, "name", None))
            polygons.append(
                {
                    "event": "Excessive Rainfall Outlook",
                    "severity": severity,               # MRGL / SLGT / MDT / HIGH / UNKNOWN
                    "geometry": shp.__geo_interface__,  # GeoJSON geometry for /geofences
                    "polygon": shp,                     # shapely MultiPolygon
                }
            )

        return polygons

    def load_wpc_kmz(self, day: int, replace_cache: bool = False) -> int:
        """
        Download the latest WPC ERO Day-N KMZ (1..5), parse polygons, and load them.
        Args:
            day: 1..5 (common use: 1..3)
            replace_cache: if True, replaces cache; else appends
        Returns:
            Number of polygons loaded.
        """
        if day not in (1, 2, 3, 4, 5):
            raise ValueError("day must be one of {1,2,3,4,5}")

        url = WPC_ERO_KMZ_URL_TEMPLATE.format(day=day)
        try:
            headers = {"User-Agent": USER_AGENT}
            resp = requests.get(url, headers=headers, timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
            polygons = self._parse_wpc_kmz_bytes(resp.content, day=day)
        except Exception as e:
            print(f"[ERROR] load_wpc_kmz(Day {day}) failed: {e}")
            return 0

        with self.lock:
            if replace_cache:
                self.cached_polygons = polygons
            else:
                self.cached_polygons.extend(polygons)

        print(f"[INFO] WPC Day {day} KMZ → {len(polygons)} polygons loaded.")
        return len(polygons)

    def load_wpc_kmz_by_url(self, url: str, day: int, replace_cache: bool = False) -> int:
        """
        Download a KMZ from an arbitrary URL, parse polygons, and load them.
        Useful for dated or alternate hosting paths.
        """
        try:
            headers = {"User-Agent": USER_AGENT}
            resp = requests.get(url, headers=headers, timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
            polygons = self._parse_wpc_kmz_bytes(resp.content, day=day)
        except Exception as e:
            print(f"[ERROR] load_wpc_kmz_by_url failed: {e}")
            return 0

        with self.lock:
            if replace_cache:
                self.cached_polygons = polygons
            else:
                self.cached_polygons.extend(polygons)

        print(f"[INFO] WPC KMZ ({url}) → {len(polygons)} polygons loaded.")
        return len(polygons)

    def load_wpc_kmz_from_file(self, path: str, day: int, replace_cache: bool = False) -> int:
        """
        Load WPC ERO polygons from a local KMZ file path (offline / reproducible tests).
        """
        try:
            with open(path, "rb") as f:
                kmz_bytes = f.read()
            polygons = self._parse_wpc_kmz_bytes(kmz_bytes=kmz_bytes, day=day)
        except Exception as e:
            print(f"[ERROR] load_wpc_kmz_from_file failed: {e}")
            return 0

        with self.lock:
            if replace_cache:
                self.cached_polygons = polygons
            else:
                self.cached_polygons.extend(polygons)

        print(f"[INFO] WPC KMZ (local: {path}) → {len(polygons)} polygons loaded.")
        return len(polygons)

    # ------------------------------------------------------------------
    # Back-compat shim: previous 'update_wpc_polygons' method name
    # ------------------------------------------------------------------
    def update_wpc_polygons(self, day: int = 1) -> None:
        """
        Backward-compatible wrapper that loads WPC ERO polygons for a given day (KMZ).
        Defaults to Day 1 to mirror the old behavior name.
        """
        loaded = self.load_wpc_kmz(day=day, replace_cache=False)
        if loaded == 0:
            print("[WARN] update_wpc_polygons() loaded 0 polygons. "
                  "If you expected data, verify the KMZ availability or try another day.")

    # ------------------------------------------------------------------
    # Accessors, utilities, and geofence check
    # ------------------------------------------------------------------
    def get_geofences(self) -> List[Dict[str, Any]]:
        """
        Return a public-safe view of cached polygons (no shapely object).
        """
        with self.lock:
            return [
                {
                    "event": p.get("event"),
                    "severity": p.get("severity"),
                    "geometry": p.get("geometry"),
                }
                for p in self.cached_polygons
            ]

    def count(self) -> int:
        """Return number of cached polygons."""
        with self.lock:
            return len(self.cached_polygons)

    def set_polygons(self, polygons: List[Dict[str, Any]]) -> None:
        """Replace cache (useful for tests)."""
        with self.lock:
            self.cached_polygons = polygons

    def check_location(
        self,
        lat: float,
        lon: float,
        count_boundary_as_inside: bool = False
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Check if a (lat, lon) point is inside ANY cached polygon.

        Args:
            lat: Latitude in decimal degrees.
            lon: Longitude in decimal degrees.
            count_boundary_as_inside: If True, treats boundary points as inside (touches).

        Returns:
            (inside, event, severity) for the first matching polygon; else (False, None, None).
        """
        point = Point(lon, lat)
        with self.lock:
            for p in self.cached_polygons:
                poly: BaseGeometry = p["polygon"]
                if poly.contains(point) or (count_boundary_as_inside and poly.touches(point)):
                    return True, p.get("event"), p.get("severity")
        return False, None, None


# Singleton instance
geofence_service = GeofenceService()

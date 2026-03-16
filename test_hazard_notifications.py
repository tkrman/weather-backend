"""
test_hazard_notifications.py - Unit tests for device registration, location
updates, and hazard-zone push-notification endpoints.

External I/O (FCM, NWS API) is mocked so the tests run offline.
"""
from __future__ import annotations

import os
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Use an in-memory SQLite database for tests so the file system is untouched.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

# Import after env var is set so config.py picks up the test URL.
import database as db_module  # noqa: E402
from database import Base, UserDevice, get_db  # noqa: E402
from main import app  # noqa: E402

# ---------------------------------------------------------------------------
# One shared in-memory engine for all tests
# ---------------------------------------------------------------------------

TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,  # share one connection so the in-memory DB persists
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=TEST_ENGINE)


def _override_get_db() -> Generator:
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client(monkeypatch) -> TestClient:
    """
    Provides a TestClient wired to the in-memory test engine.

    monkeypatch replaces the module-level ``engine`` in database.py so that
    ``init_db()`` (called at startup) creates tables in TEST_ENGINE rather
    than in a separate :memory: connection.
    """
    monkeypatch.setattr(db_module, "engine", TEST_ENGINE)
    monkeypatch.setattr(db_module, "SessionLocal", TestSession)

    # Create all tables before the app starts (and clean up after).
    Base.metadata.create_all(bind=TEST_ENGINE)

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()

    Base.metadata.drop_all(bind=TEST_ENGINE)


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

def test_health(client: TestClient):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "running"}


# ---------------------------------------------------------------------------
# /users/register
# ---------------------------------------------------------------------------

def test_register_new_device(client: TestClient):
    payload = {"device_token": "fcm_token_abc", "lat": 30.2, "lon": -92.0}
    resp = client.post("/users/register", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["device_token"] == "fcm_token_abc"
    assert data["lat"] == pytest.approx(30.2)
    assert data["lon"] == pytest.approx(-92.0)
    assert "user_id" in data
    assert data["message"] == "Device registered"


def test_register_existing_device_updates_location(client: TestClient):
    """Re-registering the same token with new coords should update the record."""
    payload = {"device_token": "fcm_token_xyz", "lat": 29.9, "lon": -90.0}
    resp1 = client.post("/users/register", json=payload)
    assert resp1.status_code == 201
    user_id_first = resp1.json()["user_id"]

    # Same token, different location
    payload2 = {"device_token": "fcm_token_xyz", "lat": 31.0, "lon": -91.5}
    resp2 = client.post("/users/register", json=payload2)
    assert resp2.status_code == 201
    data2 = resp2.json()
    assert data2["user_id"] == user_id_first  # same record
    assert data2["lat"] == pytest.approx(31.0)
    assert data2["message"] == "Device updated"


# ---------------------------------------------------------------------------
# /users/{user_id}/location
# ---------------------------------------------------------------------------

def test_update_location_inside_hazard(client: TestClient):
    """When a user's updated location falls inside a geofence they should get
    inside_hazard=True back."""
    # Register a device first
    reg = client.post(
        "/users/register",
        json={"device_token": "tok1", "lat": 0.0, "lon": 0.0},
    )
    user_id = reg.json()["user_id"]

    # Inject a test geofence around New Orleans area
    from shapely.geometry import Polygon as ShapelyPolygon
    from geofence_service import geofence_service

    poly = ShapelyPolygon(
        [(-92.1, 30.1), (-91.9, 30.1), (-91.9, 30.3), (-92.1, 30.3), (-92.1, 30.1)]
    )
    geofence_service.set_polygons(
        [{"event": "Tornado Warning", "severity": "Extreme", "geometry": {}, "polygon": poly}]
    )

    # Move device into the geofence
    resp = client.put(f"/users/{user_id}/location", json={"lat": 30.2, "lon": -92.0})
    assert resp.status_code == 200
    data = resp.json()
    assert data["inside_hazard"] is True
    assert data["event"] == "Tornado Warning"
    assert data["severity"] == "Extreme"

    geofence_service.set_polygons([])


def test_update_location_outside_hazard(client: TestClient):
    reg = client.post(
        "/users/register",
        json={"device_token": "tok2", "lat": 0.0, "lon": 0.0},
    )
    user_id = reg.json()["user_id"]

    resp = client.put(f"/users/{user_id}/location", json={"lat": 10.0, "lon": 10.0})
    assert resp.status_code == 200
    assert resp.json()["inside_hazard"] is False


def test_update_location_user_not_found(client: TestClient):
    resp = client.put("/users/99999/location", json={"lat": 30.0, "lon": -90.0})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /notifications/send-hazard-alerts
# ---------------------------------------------------------------------------

def test_send_hazard_alerts_no_users(client: TestClient):
    """With no registered users the endpoint should return zeros."""
    resp = client.post("/notifications/send-hazard-alerts")
    assert resp.status_code == 200
    data = resp.json()
    assert data["notified_users"] == 0
    assert data["success_count"] == 0


def test_send_hazard_alerts_firebase_not_configured(client: TestClient):
    """When Firebase is not configured notifications fail gracefully."""
    from shapely.geometry import Polygon as ShapelyPolygon
    from geofence_service import geofence_service

    poly = ShapelyPolygon(
        [(-92.1, 30.1), (-91.9, 30.1), (-91.9, 30.3), (-92.1, 30.3), (-92.1, 30.1)]
    )
    geofence_service.set_polygons(
        [{"event": "Flash Flood Warning", "severity": "Moderate", "geometry": {}, "polygon": poly}]
    )

    # Register a user inside the hazard zone
    client.post("/users/register", json={"device_token": "tok_flood", "lat": 30.2, "lon": -92.0})

    resp = client.post("/notifications/send-hazard-alerts")
    assert resp.status_code == 200
    data = resp.json()
    assert data["notified_users"] == 1           # 1 user in zone
    assert data["firebase_configured"] is False  # credentials not set
    assert data["failure_count"] == 1

    geofence_service.set_polygons([])


def test_send_hazard_alerts_firebase_success(client: TestClient):
    """When Firebase is available notifications should be sent successfully."""
    import notification_service
    from shapely.geometry import Polygon as ShapelyPolygon
    from geofence_service import geofence_service

    poly = ShapelyPolygon(
        [(-92.1, 30.1), (-91.9, 30.1), (-91.9, 30.3), (-92.1, 30.3), (-92.1, 30.1)]
    )
    geofence_service.set_polygons(
        [{"event": "Tornado Warning", "severity": "Extreme", "geometry": {}, "polygon": poly}]
    )
    client.post("/users/register", json={"device_token": "tok_ok", "lat": 30.2, "lon": -92.0})

    # Mock the Firebase send_each call to simulate a successful send
    mock_send_response = MagicMock()
    mock_send_response.success = True
    mock_send_response.exception = None

    mock_batch_response = MagicMock()
    mock_batch_response.responses = [mock_send_response]

    # Reset Firebase init state so our patches take effect
    notification_service._firebase_initialized = False
    notification_service._firebase_available = False

    with (
        patch.object(notification_service, "FIREBASE_CREDENTIALS_PATH", "/fake/creds.json"),
        patch("firebase_admin._apps", {"[DEFAULT]": MagicMock()}),
        patch("firebase_admin.initialize_app"),
        patch("firebase_admin.credentials.Certificate"),
        patch("firebase_admin.messaging.send_each", return_value=mock_batch_response),
    ):
        resp = client.post("/notifications/send-hazard-alerts")

    assert resp.status_code == 200
    data = resp.json()
    assert data["notified_users"] == 1
    assert data["firebase_configured"] is True
    assert data["success_count"] == 1
    assert data["failure_count"] == 0

    geofence_service.set_polygons([])


# ---------------------------------------------------------------------------
# notification_service unit tests
# ---------------------------------------------------------------------------

def test_send_batch_empty_list():
    from notification_service import send_hazard_notifications_batch

    result = send_hazard_notifications_batch([])
    assert result["success_count"] == 0
    assert result["failure_count"] == 0
    assert result["results"] == []


def test_send_batch_firebase_not_configured():
    import notification_service

    original_path = notification_service.FIREBASE_CREDENTIALS_PATH
    original_init = notification_service._firebase_initialized
    original_avail = notification_service._firebase_available
    try:
        notification_service.FIREBASE_CREDENTIALS_PATH = ""
        notification_service._firebase_initialized = False
        notification_service._firebase_available = False

        result = notification_service.send_hazard_notifications_batch(
            [{"token": "fcm_token_flood_test", "event": "Flood", "severity": "Moderate"}]
        )
        assert result["firebase_configured"] is False
        assert result["failure_count"] == 1
        assert result["success_count"] == 0
    finally:
        notification_service.FIREBASE_CREDENTIALS_PATH = original_path
        notification_service._firebase_initialized = original_init
        notification_service._firebase_available = original_avail


# ---------------------------------------------------------------------------
# /geofences/count
# ---------------------------------------------------------------------------

def test_geofences_count_empty(client: TestClient):
    from geofence_service import geofence_service
    geofence_service.set_polygons([])
    resp = client.get("/geofences/count")
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


def test_geofences_count_after_load(client: TestClient):
    from shapely.geometry import Polygon as ShapelyPolygon
    from geofence_service import geofence_service

    poly = ShapelyPolygon([(-92.1, 30.1), (-91.9, 30.1), (-91.9, 30.3), (-92.1, 30.3), (-92.1, 30.1)])
    geofence_service.set_polygons([
        {"event": "A", "severity": "High", "geometry": {}, "polygon": poly},
        {"event": "B", "severity": "Low", "geometry": {}, "polygon": poly},
    ])
    resp = client.get("/geofences/count")
    assert resp.json()["count"] == 2
    geofence_service.set_polygons([])


# ---------------------------------------------------------------------------
# POST /geofences/load  (ML pipeline ingest / manual test data)
# ---------------------------------------------------------------------------

_SAMPLE_ZONE = {
    "event": "Tornado Warning",
    "severity": "Extreme",
    "geometry": {
        "type": "Polygon",
        "coordinates": [
            [[-91.25, 30.35], [-90.95, 30.35], [-90.95, 30.55], [-91.25, 30.55], [-91.25, 30.35]]
        ],
    },
}


def test_load_geofences_replace(client: TestClient):
    from geofence_service import geofence_service
    # Pre-populate with one zone so we can verify it gets replaced
    from shapely.geometry import Polygon as ShapelyPolygon
    poly = ShapelyPolygon([(-92.1, 30.1), (-91.9, 30.1), (-91.9, 30.3), (-92.1, 30.3), (-92.1, 30.1)])
    geofence_service.set_polygons([{"event": "Old", "severity": "Low", "geometry": {}, "polygon": poly}])

    payload = {"hazard_zones": [_SAMPLE_ZONE], "replace": True}
    resp = client.post("/geofences/load", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["loaded"] == 1
    assert data["total_cached"] == 1
    assert data["replaced"] is True
    # Old zone should be gone
    zones = client.get("/geofences").json()
    assert len(zones) == 1
    assert zones[0]["event"] == "Tornado Warning"
    geofence_service.set_polygons([])


def test_load_geofences_append(client: TestClient):
    from geofence_service import geofence_service
    # Start with one zone
    payload1 = {"hazard_zones": [_SAMPLE_ZONE], "replace": True}
    client.post("/geofences/load", json=payload1)

    second_zone = {
        "event": "Flash Flood Warning",
        "severity": "Severe",
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [[-90.15, 29.85], [-89.85, 29.85], [-89.85, 30.05], [-90.15, 30.05], [-90.15, 29.85]]
            ],
        },
    }
    payload2 = {"hazard_zones": [second_zone], "replace": False}
    resp = client.post("/geofences/load", json=payload2)
    assert resp.status_code == 200
    data = resp.json()
    assert data["loaded"] == 1
    assert data["total_cached"] == 2
    assert data["replaced"] is False
    geofence_service.set_polygons([])


def test_load_geofences_invalid_geometry_is_skipped(client: TestClient):
    from geofence_service import geofence_service
    bad_zone = {
        "event": "Bad Zone",
        "severity": "Low",
        "geometry": {"type": "Polygon", "coordinates": []},  # invalid - no rings
    }
    payload = {"hazard_zones": [bad_zone, _SAMPLE_ZONE], "replace": True}
    resp = client.post("/geofences/load", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    # The bad zone is skipped; only the valid one is loaded
    assert data["loaded"] == 1
    assert data["total_cached"] == 1
    assert "skipped" in data["message"]
    geofence_service.set_polygons([])


def test_load_geofences_non_polygon_geometry_is_skipped(client: TestClient):
    """Geometries that are not Polygon or MultiPolygon are rejected as invalid."""
    from geofence_service import geofence_service
    point_zone = {
        "event": "Point Zone",
        "severity": "Low",
        "geometry": {"type": "Point", "coordinates": [-91.10, 30.45]},
    }
    payload = {"hazard_zones": [point_zone, _SAMPLE_ZONE], "replace": True}
    resp = client.post("/geofences/load", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    # The Point zone is skipped; only the Polygon zone is loaded
    assert data["loaded"] == 1
    assert data["total_cached"] == 1
    assert "skipped" in data["message"]
    geofence_service.set_polygons([])


def test_load_geofences_missing_geometry_type_is_skipped(client: TestClient):
    """A geometry dict with no 'type' key is rejected as invalid."""
    from geofence_service import geofence_service
    bad_zone = {
        "event": "No Type Zone",
        "severity": "Low",
        "geometry": {"coordinates": [[[-91.25, 30.35], [-90.95, 30.35], [-90.95, 30.55], [-91.25, 30.55], [-91.25, 30.35]]]},
    }
    payload = {"hazard_zones": [bad_zone, _SAMPLE_ZONE], "replace": True}
    resp = client.post("/geofences/load", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["loaded"] == 1
    assert data["total_cached"] == 1
    assert "skipped" in data["message"]
    geofence_service.set_polygons([])


def test_load_geofences_check_location_works(client: TestClient):
    """A point inside a loaded zone should be detected by /check-location."""
    payload = {"hazard_zones": [_SAMPLE_ZONE], "replace": True}
    client.post("/geofences/load", json=payload)

    # Point inside the tornado warning box
    resp = client.post("/check-location", json={"user_lat": 30.45, "user_lon": -91.10})
    assert resp.status_code == 200
    data = resp.json()
    assert data["inside"] is True
    assert data["event"] == "Tornado Warning"

    # Point outside
    resp2 = client.post("/check-location", json={"user_lat": 10.0, "user_lon": 10.0})
    assert resp2.json()["inside"] is False

    from geofence_service import geofence_service
    geofence_service.set_polygons([])


# ---------------------------------------------------------------------------
# POST /geofences/load-nws  (live NWS Alerts API ingest)
# ---------------------------------------------------------------------------

_MOCK_NWS_RESPONSE = {
    "features": [
        {
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [[-91.25, 30.35], [-90.95, 30.35], [-90.95, 30.55], [-91.25, 30.55], [-91.25, 30.35]]
                ],
            },
            "properties": {"event": "Tornado Warning", "severity": "Extreme"},
        },
        {
            # geocode-only alert — no geometry; should be skipped
            "geometry": None,
            "properties": {"event": "Winter Storm Watch", "severity": "Moderate"},
        },
        {
            "geometry": {"type": "Point", "coordinates": [-91.10, 30.45]},
            "properties": {"event": "Special Weather Statement", "severity": "Minor"},
        },
    ]
}


def test_load_nws_geofences_success(client: TestClient):
    """A mocked NWS response with one polygon, one no-geometry, one Point should
    load exactly 1 zone (the polygon) and skip 2."""
    from geofence_service import geofence_service

    with patch.object(geofence_service, "fetch_alerts", return_value=_MOCK_NWS_RESPONSE):
        resp = client.post("/geofences/load-nws")

    assert resp.status_code == 200
    data = resp.json()
    assert data["loaded"] == 1
    assert data["total_cached"] == 1
    assert data["replaced"] is True
    assert "2 skipped" in data["message"]

    zones = client.get("/geofences").json()
    assert len(zones) == 1
    assert zones[0]["event"] == "Tornado Warning"

    geofence_service.set_polygons([])


def test_load_nws_geofences_replaces_existing(client: TestClient):
    """POST /geofences/load-nws should replace any previously cached zones."""
    from shapely.geometry import Polygon as ShapelyPolygon
    from geofence_service import geofence_service

    poly = ShapelyPolygon([(-92.1, 30.1), (-91.9, 30.1), (-91.9, 30.3), (-92.1, 30.3), (-92.1, 30.1)])
    geofence_service.set_polygons([
        {"event": "Old Zone", "severity": "Low", "geometry": {}, "polygon": poly},
        {"event": "Another Old Zone", "severity": "Low", "geometry": {}, "polygon": poly},
    ])

    single_zone_response = {
        "features": [
            {
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [[-91.25, 30.35], [-90.95, 30.35], [-90.95, 30.55], [-91.25, 30.55], [-91.25, 30.35]]
                    ],
                },
                "properties": {"event": "Flash Flood Warning", "severity": "Severe"},
            }
        ]
    }
    with patch.object(geofence_service, "fetch_alerts", return_value=single_zone_response):
        resp = client.post("/geofences/load-nws")

    assert resp.status_code == 200
    data = resp.json()
    assert data["loaded"] == 1
    assert data["total_cached"] == 1   # old zones replaced

    geofence_service.set_polygons([])


def test_load_nws_geofences_api_error_returns_502(client: TestClient):
    """When the NWS API is unreachable the endpoint should return 502."""
    from geofence_service import geofence_service

    with patch.object(geofence_service, "fetch_alerts", side_effect=Exception("connection refused")):
        resp = client.post("/geofences/load-nws")

    assert resp.status_code == 502
    assert "NWS API" in resp.json()["detail"]


def test_load_nws_geofences_empty_features(client: TestClient):
    """An NWS response with no features should load 0 zones successfully."""
    from geofence_service import geofence_service

    with patch.object(geofence_service, "fetch_alerts", return_value={"features": []}):
        resp = client.post("/geofences/load-nws")

    assert resp.status_code == 200
    data = resp.json()
    assert data["loaded"] == 0
    assert data["total_cached"] == 0
    assert data["replaced"] is True


# ---------------------------------------------------------------------------
# POST /geofences/load-demo
# ---------------------------------------------------------------------------

def test_load_demo_geofences(client: TestClient):
    from geofence_service import geofence_service
    resp = client.post("/geofences/load-demo")
    assert resp.status_code == 200
    data = resp.json()
    # The fixture has 4 sample zones
    assert data["loaded"] == 4
    assert data["total_cached"] == 4
    assert data["replaced"] is True

    # Verify zones are queryable
    zones_resp = client.get("/geofences")
    assert len(zones_resp.json()) == 4
    event_names = {z["event"] for z in zones_resp.json()}
    assert "Tornado Warning" in event_names
    assert "Flash Flood Warning" in event_names

    geofence_service.set_polygons([])


def test_load_demo_then_check_location_inside(client: TestClient):
    """After loading demo data, a point inside a demo zone should be detected."""
    client.post("/geofences/load-demo")

    # Baton Rouge area - inside the Tornado Warning demo box
    resp = client.post("/check-location", json={"user_lat": 30.45, "user_lon": -91.10})
    assert resp.status_code == 200
    data = resp.json()
    assert data["inside"] is True
    assert data["event"] == "Tornado Warning"

    from geofence_service import geofence_service
    geofence_service.set_polygons([])

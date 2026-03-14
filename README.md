# Louisiana Weather Geofence API

FastAPI backend for geofence-based weather hazard alerting. Tracks registered
devices via GPS and sends Firebase Cloud Messaging (FCM) push notifications when
a device enters a hazard zone.

---

## Quick start — no database or ML pipeline required

The server uses **SQLite by default** (zero configuration — the file is created
automatically). The ML pipeline integration point (`POST /geofences/load`) also
works in "demo mode" via `POST /geofences/load-demo`, which loads four sample
Louisiana hazard zones with a single HTTP call.

### 1 — Install Python dependencies

```powershell
# Windows PowerShell
pip install -r requirements.txt
```

```bash
# macOS / Linux
pip install -r requirements.txt
```

### 2 — Start the server

```powershell
# Windows PowerShell
python -m uvicorn main:app --reload
```

```bash
# macOS / Linux
uvicorn main:app --reload
```

The server starts on **http://localhost:8000**.  
Interactive API docs: **http://localhost:8000/docs**

> Open http://localhost:8000/docs in your browser (Windows PowerShell does not
> have an `open` command — just paste the URL into any browser).

---

## Full offline test flow

### Windows PowerShell

```powershell
# 1. Start the server (SQLite DB is created automatically — no setup needed)
python -m uvicorn main:app --reload

# (Open a second PowerShell window for the steps below)

# 2. Load demo hazard zones (no NWS / WPC / ML pipeline needed)
Invoke-RestMethod -Method Post -Uri http://localhost:8000/geofences/load-demo

# 3. Register a test device
Invoke-RestMethod -Method Post -Uri http://localhost:8000/users/register `
    -ContentType "application/json" `
    -Body '{"device_token":"test-fcm-token","lat":30.45,"lon":-91.10}'

# 4. Move the device into a hazard zone (returns inside_hazard: true)
Invoke-RestMethod -Method Put -Uri http://localhost:8000/users/1/location `
    -ContentType "application/json" `
    -Body '{"lat":30.45,"lon":-91.10}'

# 5. Trigger notification scan (Firebase degrades gracefully when unconfigured)
Invoke-RestMethod -Method Post -Uri http://localhost:8000/notifications/send-hazard-alerts

# 6. Verify how many zones are loaded
Invoke-RestMethod -Uri http://localhost:8000/geofences/count

# 7. List all loaded zones
Invoke-RestMethod -Uri http://localhost:8000/geofences
```

> **Tip:** run `test_offline.ps1` to execute all of the above steps automatically.

### macOS / Linux (bash)

```bash
# 1. Start the server (SQLite DB is created automatically — no setup needed)
uvicorn main:app --reload

# (Open a second terminal for the steps below)

# 2. Load demo hazard zones
curl -X POST http://localhost:8000/geofences/load-demo

# 3. Register a test device
curl -X POST http://localhost:8000/users/register \
    -H "Content-Type: application/json" \
    -d '{"device_token":"test-fcm-token","lat":30.45,"lon":-91.10}'

# 4. Move the device into a hazard zone
curl -X PUT http://localhost:8000/users/1/location \
    -H "Content-Type: application/json" \
    -d '{"lat":30.45,"lon":-91.10}'

# 5. Trigger notification scan
curl -X POST http://localhost:8000/notifications/send-hazard-alerts

# 6. Verify zone count
curl http://localhost:8000/geofences/count

# 7. List all zones
curl http://localhost:8000/geofences
```

---

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/health` | Liveness check |
| `GET`  | `/geofences` | List all cached hazard zones |
| `GET`  | `/geofences/count` | Count cached hazard zones |
| `POST` | `/geofences/load` | **ML pipeline ingest** — POST GeoJSON hazard zones |
| `POST` | `/geofences/load-demo` | Load built-in sample zones for offline testing |
| `POST` | `/check-location` | Check if a lat/lon is inside any hazard zone |
| `POST` | `/users/register` | Register (or update) a device with its FCM token |
| `PUT`  | `/users/{id}/location` | Update device location; returns hazard status |
| `POST` | `/notifications/send-hazard-alerts` | Send FCM alerts to all devices in hazard zones |

---

## ML pipeline ingest format

The ML pipeline should `POST` to `/geofences/load` with this payload shape
(see `fixtures/sample_hazard_zones.json` for a full example):

```json
{
  "replace": true,
  "hazard_zones": [
    {
      "event": "Tornado Warning",
      "severity": "Extreme",
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[-91.25, 30.35], [-90.95, 30.35], [-90.95, 30.55], [-91.25, 30.55], [-91.25, 30.35]]]
      }
    }
  ]
}
```

Set `"replace": false` to append zones to the existing cache instead of replacing it.

---

## Configuration

| Environment variable | Default | Description |
|----------------------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./weather_app.db` | SQLAlchemy DB URL. Override for PostgreSQL etc. |
| `FIREBASE_CREDENTIALS_PATH` | *(empty)* | Path to Firebase service-account JSON. When unset, push notifications fail gracefully. |

---

## Running tests

```powershell
# Windows PowerShell
python -m pytest test_hazard_notifications.py -v
```

```bash
# macOS / Linux
pytest test_hazard_notifications.py -v
```

import os

NWS_ALERTS_URL = "https://api.weather.gov/alerts/active?area=LA"
REFRESH_INTERVAL_SECONDS = 300  # 5 minutes
USER_AGENT = "Louisiana-Weather-Geofence-App (your@email.com)"

# SQLAlchemy database URL.  Override with DATABASE_URL env var (e.g. postgresql://...)
DATABASE_URL: str = os.environ.get("DATABASE_URL", "sqlite:///./weather_app.db")

# Absolute path to a Firebase service-account JSON file.
# When unset, push notifications are gracefully disabled.
FIREBASE_CREDENTIALS_PATH: str = os.environ.get("FIREBASE_CREDENTIALS_PATH", "")

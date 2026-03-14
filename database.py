"""
database.py — SQLAlchemy engine, session factory, and ORM models.
"""
from __future__ import annotations

import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config import DATABASE_URL

# SQLite needs check_same_thread=False; other engines ignore unknown connect_args
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class UserDevice(Base):
    """
    Registered user device.

    Stores the FCM push token and the device's last known GPS location so
    the backend can decide which users are inside a hazard zone and send
    them targeted push notifications.
    """

    __tablename__ = "user_devices"

    id = Column(Integer, primary_key=True, index=True)
    device_token = Column(String, unique=True, nullable=False, index=True)
    last_lat = Column(Float, nullable=True)
    last_lon = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
    )


def get_db():
    """FastAPI dependency — yields a SQLAlchemy session and closes it on exit."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables (idempotent)."""
    Base.metadata.create_all(bind=engine)

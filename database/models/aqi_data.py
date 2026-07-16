"""SQLAlchemy ORM model for the existing aqi_data table."""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from database.connection import Base


class AQIData(Base):
    """Represents a proof-of-concept AQI data record in the database.

    Maps directly to the existing ``aqi_data`` table.
    """

    __tablename__ = "aqi_data"
    __table_args__ = (
        Index("ix_aqi_data_city_recorded_at", "city", "recorded_at"),
        Index("ix_aqi_data_location_name", "location_name"),
        Index("ix_aqi_data_lower_city_recorded_at", func.lower("city"), "recorded_at"),
        # Prevents duplicate ingestion records at the DB level.
        # IntegrityError on insert is caught in sync_service and treated as a
        # duplicate skip, so existing duplicate-cache logic is unaffected.
        UniqueConstraint("location_name", "recorded_at", name="uq_aqi_data_location_recorded_at"),
    )

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    location_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pm25: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pm10: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    no2: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    o3: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    co: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    so2: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    temperature: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    humidity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    wind_speed: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    wind_direction: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    precipitation: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pressure: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    recorded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.now()
    )
    aqi: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    aqi_category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    dominant_pollutant: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<AQIData(id={self.id}, city='{self.city}', "
            f"location_name='{self.location_name}', pm25={self.pm25}, aqi={self.aqi})>"
        )

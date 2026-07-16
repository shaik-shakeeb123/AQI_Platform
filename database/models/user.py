"""SQLAlchemy ORM model for the users table."""

from datetime import datetime
from typing import Optional, List

from sqlalchemy import Boolean, DateTime, Integer, String, func, CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database.connection import Base


class User(Base):
    """Represents a user account in the database.

    Maps to the ``users`` table, supporting authentication, profile preferences,
    health condition classification, and notification settings.
    """

    __tablename__ = "users"

    # Authentication
    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    email: Mapped[str] = mapped_column(
        String(100), unique=True, index=True, nullable=False
    )
    password_hash: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    provider: Mapped[str] = mapped_column(
        String(50), default="EMAIL", server_default="EMAIL"
    )
    provider_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    google_id: Mapped[Optional[str]] = mapped_column(
        String(255), unique=True, index=True, nullable=True
    )
    email_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )

    # Profile
    full_name: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )
    profile_picture: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True
    )
    city: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )
    age_group: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )
    outdoor_activity: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )

    # Health Conditions (JSONB array — e.g. ["ASTHMA", "ALLERGY"])
    health_conditions: Mapped[list] = mapped_column(
        JSONB, default=list, server_default="[]"
    )

    # Notification Preferences
    aqi_alerts_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    safe_window_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    daily_summary_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )

    # Metadata
    preferences_completed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    last_login: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "provider IN ('EMAIL', 'GOOGLE')",
            name="check_provider_valid"
        ),
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email='{self.email}', full_name='{self.full_name}')>"

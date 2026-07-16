"""Pydantic validation schemas for authentication."""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class NotificationsRequest(BaseModel):
    aqi_alerts: bool
    safe_window: bool
    daily_summary: bool


class UserProfileUpdate(BaseModel):
    """Schema for updating user profile fields."""

    full_name: Optional[str] = Field(default=None, max_length=100)
    city: Optional[str] = Field(default=None, max_length=100)
    age_group: Optional[str] = Field(default=None, max_length=50)
    outdoor_activity: Optional[str] = Field(default=None, max_length=50)
    health_conditions: Optional[List[str]] = None
    notifications: Optional[NotificationsRequest] = None


class GoogleLoginRequest(BaseModel):
    """Schema for Google OAuth login requests."""

    id_token: str





class NotificationsResponse(BaseModel):
    aqi_alerts: bool
    safe_window: bool
    daily_summary: bool


class UserResponse(BaseModel):
    """Schema for mapping user data in API responses."""

    id: Optional[int] = None
    email: str
    full_name: Optional[str] = None
    city: Optional[str] = None
    google_id: Optional[str] = None
    profile_picture: Optional[str] = None
    last_login: Optional[datetime] = None
    preferences_completed: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    age_group: Optional[str] = None
    outdoor_activity: Optional[str] = None
    health_conditions: List[str] = []
    notifications: NotificationsResponse

    model_config = {
        "from_attributes": True
    }


class Token(BaseModel):
    """Schema representing the returned JWT access token."""

    access_token: str
    token_type: str = "bearer"


class UserRegisterRequest(BaseModel):
    """Schema for user registration requests."""
    email: str = Field(..., description="Unique email address")
    password: str = Field(..., description="Plain-text password")
    name: Optional[str] = Field(default=None, description="Full name")
    city: Optional[str] = Field(default=None, description="Home city")
    age_group: Optional[str] = Field(default=None, description="Age group")
    outdoor_activity: Optional[str] = Field(default=None, description="Outdoor activity level")
    health_conditions: Optional[List[str]] = Field(default=None, description="Health conditions list")
    notifications: Optional[NotificationsRequest] = None


class UserLoginRequest(BaseModel):
    """Schema for user login requests."""
    email: str = Field(..., description="Registered email address")
    password: str = Field(..., description="Plain-text password")

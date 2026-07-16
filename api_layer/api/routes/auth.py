"""Authentication and authorization API route handlers."""

import asyncio
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from database.connection import get_db
from api_layer.config import get_settings
from api_layer.security import (
    create_access_token,
    decode_access_token,
)
from database.models.user import User
from api_layer.api.schemas.auth import (
    Token,
    UserResponse,
    UserProfileUpdate,
    GoogleLoginRequest,
    UserRegisterRequest,
    UserLoginRequest,
)
from services.identity import get_identity_provider

router = APIRouter()

# Setup standard HTTP Bearer token extraction dependency
security_scheme = HTTPBearer()


async def get_current_user(
    auth: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: Session = Depends(get_db)
) -> User:
    """Dependency to extract user identity from JWT and load the database model.

    Requires a valid Bearer JWT in the Authorization header.
    """
    token = auth.credentials
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing user identity claim",
        )

    # Support resolving both legacy email-based sub claims and new stable numeric ID sub claims.
    # Wrapped in asyncio.to_thread because db.query() is synchronous SQLAlchemy
    # called from an async def — blocking the event loop otherwise.
    if sub.isdigit():
        user = await asyncio.to_thread(
            lambda: db.query(User).filter(User.id == int(sub)).first()
        )
    else:
        user = await asyncio.to_thread(
            lambda: db.query(User).filter(User.email == sub).first()
        )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user not found",
        )
    return user


@router.post(
    "/google-login",
    response_model=Token,
    summary="Sign in with Google",
    description=(
        "Verify a Google ID Token (JWT) obtained through Google Identity Services, "
        "find or create the user account, and return an internal JWT access token.\n\n"
        "**Token type expected:** Google OAuth 2.0 ID Token (JWT).\n\n"
        "**How to use from Swagger:** Obtain a Google ID Token from the Google Sign-In "
        "button on the frontend, then paste it here. The ID Token is a short-lived JWT "
        "issued by Google after successful OAuth consent."
    ),
    responses={
        400: {"description": "Malformed token (not a valid JWT structure)"},
        401: {"description": "Invalid Google ID token (expired, bad signature, or revoked)"},
        403: {"description": "Token audience mismatch (wrong Google Client ID)"},
        500: {"description": "Unexpected server error during token verification"},
    },
)
def google_login(payload: GoogleLoginRequest, db: Session = Depends(get_db)):
    """Verify Google ID Token, find/create user, update last login, and return JWT."""
    try:
        provider = get_identity_provider("google")
        claims = provider.verify_token(payload.id_token)
    except ValueError as e:
        # Malformed token or missing claims → 400
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except PermissionError as e:
        # Invalid signature, expired, or revoked token → 401
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )
    except ConnectionError as e:
        # Audience mismatch → 403
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        )
    except RuntimeError as e:
        # Unexpected failure → 500
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during Google token verification.",
        )

    google_id = claims["provider_id"]
    email = claims["email"]
    full_name = claims.get("name")
    profile_picture = claims.get("picture")

    # Query user by google_id or email
    user = db.query(User).filter(User.google_id == google_id).first()
    if not user:
        # Fallback lookup by email to support migration binding
        user = db.query(User).filter(User.email == email).first()
        if user:
            # Bind google_id to existing account
            user.google_id = google_id
            user.provider = "GOOGLE"
            if profile_picture:
                user.profile_picture = profile_picture
        else:
            # Create new user
            user = User(
                email=email,
                google_id=google_id,
                full_name=full_name,
                profile_picture=profile_picture,
                provider="GOOGLE",
                preferences_completed=False,
            )
            db.add(user)

    # Update last login time
    user.last_login = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)

    # Issue internally-scoped JWT containing the stable internal User ID
    token = create_access_token(data={"sub": str(user.id)})
    return {"access_token": token, "token_type": "bearer"}








@router.get(
    "/profile",
    response_model=UserResponse,
    summary="Get current user profile",
    description="Retrieve the authenticated user's profile details. Requires Bearer JWT.",
)
def get_profile(current_user: User = Depends(get_current_user)):
    """Retrieve current authenticated user's profile details."""
    return {
        "id": current_user.id,
        "email": current_user.email,
        "full_name": current_user.full_name,
        "city": current_user.city,
        "google_id": current_user.google_id,
        "profile_picture": current_user.profile_picture,
        "last_login": current_user.last_login,
        "preferences_completed": current_user.preferences_completed,
        "created_at": current_user.created_at,
        "updated_at": current_user.updated_at,
        "age_group": current_user.age_group,
        "outdoor_activity": current_user.outdoor_activity,
        "health_conditions": current_user.health_conditions or [],
        "notifications": {
            "aqi_alerts": current_user.aqi_alerts_enabled,
            "safe_window": current_user.safe_window_enabled,
            "daily_summary": current_user.daily_summary_enabled,
        }
    }


@router.put(
    "/profile",
    response_model=UserResponse,
    summary="Update current user profile",
    description="Update the authenticated user's profile fields. Requires Bearer JWT.",
)
def update_profile(
    payload: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update current user's profile fields in the database."""
    if payload.full_name is not None:
        current_user.full_name = payload.full_name
    if payload.city is not None:
        current_user.city = payload.city
    if payload.age_group is not None:
        current_user.age_group = payload.age_group
    if payload.outdoor_activity is not None:
        current_user.outdoor_activity = payload.outdoor_activity
    if payload.health_conditions is not None:
        current_user.health_conditions = payload.health_conditions
    if payload.notifications is not None:
        current_user.aqi_alerts_enabled = payload.notifications.aqi_alerts
        current_user.safe_window_enabled = payload.notifications.safe_window
        current_user.daily_summary_enabled = payload.notifications.daily_summary

    current_user.preferences_completed = True

    db.commit()
    db.refresh(current_user)

    return {
        "id": current_user.id,
        "email": current_user.email,
        "full_name": current_user.full_name,
        "city": current_user.city,
        "google_id": current_user.google_id,
        "profile_picture": current_user.profile_picture,
        "last_login": current_user.last_login,
        "preferences_completed": current_user.preferences_completed,
        "created_at": current_user.created_at,
        "updated_at": current_user.updated_at,
        "age_group": current_user.age_group,
        "outdoor_activity": current_user.outdoor_activity,
        "health_conditions": current_user.health_conditions or [],
        "notifications": {
            "aqi_alerts": current_user.aqi_alerts_enabled,
            "safe_window": current_user.safe_window_enabled,
            "daily_summary": current_user.daily_summary_enabled,
        }
    }


import hashlib
import hmac
import os

def hash_password(password: str) -> str:
    salt = os.urandom(16)
    pw_hash = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100000)
    return salt.hex() + "$" + pw_hash.hex()

def verify_password(password: str, hashed: str) -> bool:
    if not hashed or "$" not in hashed:
        return False
    salt_hex, hash_hex = hashed.split("$", 1)
    salt = bytes.fromhex(salt_hex)
    pw_hash = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100000)
    # Use constant-time comparison to prevent timing-oracle attacks.
    return hmac.compare_digest(pw_hash.hex(), hash_hex)


@router.post(
    "/register",
    response_model=Token,
    summary="Register a new user",
    description="Create a new user account with custom email and password.",
)
def register(payload: UserRegisterRequest, db: Session = Depends(get_db)):
    # Check if user already exists
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email address is already registered",
        )

    # Hash the password
    pw_hash = hash_password(payload.password)

    # Resolve notification preferences
    aqi_alerts = True
    safe_window = True
    daily_summary = True
    if payload.notifications is not None:
        aqi_alerts = payload.notifications.aqi_alerts
        safe_window = payload.notifications.safe_window
        daily_summary = payload.notifications.daily_summary

    # Determine if preferences completed (needs city, age_group, and outdoor_activity)
    has_prefs = bool(payload.city and payload.age_group and payload.outdoor_activity)

    # Create new user
    user = User(
        email=payload.email,
        password_hash=pw_hash,
        full_name=payload.name,
        city=payload.city,
        age_group=payload.age_group,
        outdoor_activity=payload.outdoor_activity,
        health_conditions=payload.health_conditions or [],
        aqi_alerts_enabled=aqi_alerts,
        safe_window_enabled=safe_window,
        daily_summary_enabled=daily_summary,
        preferences_completed=has_prefs,
        provider="EMAIL",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Return access token
    token = create_access_token(data={"sub": str(user.id)})
    return {"access_token": token, "token_type": "bearer"}


@router.post(
    "/login",
    response_model=Token,
    summary="Authenticate user credentials",
    description="Verify email and password credentials, and return a JWT access token.",
)
def login(payload: UserLoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not user.password_hash:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Update last login time
    user.last_login = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)

    # Return access token
    token = create_access_token(data={"sub": str(user.id)})
    return {"access_token": token, "token_type": "bearer"}

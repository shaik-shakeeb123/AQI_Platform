"""Shared API dependencies for dependency injection."""
from database.connection import get_db

# Re-export get_db for router convenience
__all__ = ["get_db"]

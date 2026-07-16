"""baseline schema

Revision ID: 0001
Revises: 
Create Date: 2026-07-16 01:02:29.813376

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: Create baseline tables."""
    # Create users table
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('email', sa.String(length=100), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=True),
        sa.Column('provider', sa.String(length=50), server_default='EMAIL', nullable=False),
        sa.Column('provider_id', sa.String(length=255), nullable=True),
        sa.Column('google_id', sa.String(length=255), nullable=True),
        sa.Column('email_verified', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('full_name', sa.String(length=100), nullable=True),
        sa.Column('profile_picture', sa.String(length=512), nullable=True),
        sa.Column('city', sa.String(length=100), nullable=True),
        sa.Column('age_group', sa.String(length=50), nullable=True),
        sa.Column('outdoor_activity', sa.String(length=50), nullable=True),
        sa.Column('health_conditions', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
        sa.Column('aqi_alerts_enabled', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('safe_window_enabled', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('daily_summary_enabled', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('preferences_completed', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('last_login', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("provider IN ('EMAIL', 'GOOGLE')", name='check_provider_valid'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_index(op.f('ix_users_google_id'), 'users', ['google_id'], unique=True)

    # Create aqi_data table
    op.create_table(
        'aqi_data',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('city', sa.String(length=100), nullable=True),
        sa.Column('location_name', sa.String(length=200), nullable=True),
        sa.Column('latitude', sa.Float(), nullable=True),
        sa.Column('longitude', sa.Float(), nullable=True),
        sa.Column('pm25', sa.Float(), nullable=True),
        sa.Column('pm10', sa.Float(), nullable=True),
        sa.Column('no2', sa.Float(), nullable=True),
        sa.Column('o3', sa.Float(), nullable=True),
        sa.Column('co', sa.Float(), nullable=True),
        sa.Column('so2', sa.Float(), nullable=True),
        sa.Column('temperature', sa.Float(), nullable=True),
        sa.Column('humidity', sa.Float(), nullable=True),
        sa.Column('wind_speed', sa.Float(), nullable=True),
        sa.Column('wind_direction', sa.Float(), nullable=True),
        sa.Column('precipitation', sa.Float(), nullable=True),
        sa.Column('pressure', sa.Float(), nullable=True),
        sa.Column('recorded_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('aqi', sa.Float(), nullable=True),
        sa.Column('aqi_category', sa.String(length=50), nullable=True),
        sa.Column('dominant_pollutant', sa.String(length=50), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    # The original expression index before the safe constraint migration replaced it
    op.execute("CREATE INDEX idx_aqi_data_lower_city_recorded_at ON aqi_data (lower(city), recorded_at)")


def downgrade() -> None:
    """Downgrade schema: Drop baseline tables."""
    op.drop_table('aqi_data')
    op.drop_table('users')

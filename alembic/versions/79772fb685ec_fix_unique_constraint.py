"""fix unique constraint

Revision ID: 79772fb685ec
Revises: 0005
Create Date: 2026-10-08 21:07:43.975874

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '79772fb685ec'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint('uq_aqi_data_location_recorded_at', 'aqi_data', type_='unique')
    op.create_unique_constraint('uq_aqi_data_city_location_recorded_at', 'aqi_data', ['city', 'location_name', 'recorded_at'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('uq_aqi_data_city_location_recorded_at', 'aqi_data', type_='unique')
    op.create_unique_constraint('uq_aqi_data_location_recorded_at', 'aqi_data', ['location_name', 'recorded_at'])

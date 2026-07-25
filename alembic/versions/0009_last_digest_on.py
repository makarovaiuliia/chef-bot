"""families.last_digest_on: дедупликация рассылок планировщика

Revision ID: 0009_last_digest_on
Revises: 0008_onboarding_attempts
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_last_digest_on"
down_revision: Union[str, Sequence[str], None] = "0008_onboarding_attempts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("families", sa.Column("last_digest_on", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("families", "last_digest_on")

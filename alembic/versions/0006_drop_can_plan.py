"""drop family_members.can_plan — права только через role=admin (спека §4)

Revision ID: 0006_drop_can_plan
Revises: 0005_multitenant
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_drop_can_plan"
down_revision: Union[str, Sequence[str], None] = "0005_multitenant"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("family_members") as b:
        b.drop_column("can_plan")


def downgrade() -> None:
    with op.batch_alter_table("family_members") as b:
        b.add_column(
            sa.Column("can_plan", sa.Boolean(), nullable=False, server_default=sa.false())
        )

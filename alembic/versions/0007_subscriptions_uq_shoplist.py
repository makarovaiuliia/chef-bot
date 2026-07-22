"""subscription requests, family sub_until, unique shopping list per menu

Revision ID: 0007_subscriptions_uq_shoplist
Revises: 0006_drop_can_plan
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_subscriptions_uq_shoplist"
down_revision: Union[str, Sequence[str], None] = "0006_drop_can_plan"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "subscription_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "family_id", sa.Integer(), sa.ForeignKey("families.id"),
            nullable=False, unique=True,
        ),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
    )
    op.add_column("families", sa.Column("sub_until", sa.Date(), nullable=True))
    with op.batch_alter_table("shopping_lists") as b:
        b.create_unique_constraint("uq_shopping_lists_menu_id", ["menu_id"])


def downgrade() -> None:
    with op.batch_alter_table("shopping_lists") as b:
        b.drop_constraint("uq_shopping_lists_menu_id", type_="unique")
    op.drop_column("families", "sub_until")
    op.drop_table("subscription_requests")

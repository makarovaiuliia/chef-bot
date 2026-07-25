"""onboarding attempts: суточный лимит генерации профиля до создания семьи

Revision ID: 0008_onboarding_attempts
Revises: 0007_subscriptions_uq_shoplist
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_onboarding_attempts"
down_revision: Union[str, Sequence[str], None] = "0007_subscriptions_uq_shoplist"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "onboarding_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_onboarding_attempts_telegram_user_id",
        "onboarding_attempts",
        ["telegram_user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_onboarding_attempts_telegram_user_id", table_name="onboarding_attempts"
    )
    op.drop_table("onboarding_attempts")

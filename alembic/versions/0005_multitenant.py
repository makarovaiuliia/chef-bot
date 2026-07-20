"""multitenant: family profile & settings, roles, llm_usage, store→string, breakfast

Revision ID: 0005_multitenant
Revises: 0004_conversations
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_multitenant"
down_revision: Union[str, Sequence[str], None] = "0004_conversations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    with op.batch_alter_table("families") as b:
        b.add_column(sa.Column("profile_md", sa.Text(), nullable=True))
        b.add_column(
            sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC")
        )
        b.add_column(
            sa.Column("digest_hour", sa.Integer(), nullable=False, server_default="9")
        )
        b.add_column(
            sa.Column(
                "digest_enabled", sa.Boolean(), nullable=False, server_default=sa.true()
            )
        )
        b.add_column(
            sa.Column(
                "plan_slots",
                sa.JSON(),
                nullable=False,
                server_default='["lunch", "dinner"]',
            )
        )
        b.add_column(sa.Column("invite_code", sa.String(32), nullable=True))
        b.create_unique_constraint("uq_families_invite_code", ["invite_code"])

    with op.batch_alter_table("family_members") as b:
        b.add_column(
            sa.Column(
                "role",
                sa.Enum("admin", "member", name="memberrole", native_enum=False, length=10),
                nullable=False,
                server_default="member",
            )
        )
        b.add_column(
            sa.Column("can_plan", sa.Boolean(), nullable=False, server_default=sa.false())
        )

    # первый участник каждой существующей семьи становится админом
    op.execute(
        "UPDATE family_members SET role = 'admin' WHERE id IN "
        "(SELECT MIN(id) FROM family_members GROUP BY family_id)"
    )

    # store: native enum → просто строка
    if bind.dialect.name == "postgresql":
        op.alter_column(
            "shopping_items",
            "store",
            type_=sa.String(100),
            postgresql_using="store::text",
            nullable=True,
            server_default=None,
        )
        op.execute("DROP TYPE IF EXISTS store")
        # breakfast в существующий native enum meal-слотов
        op.execute("ALTER TYPE mealslot ADD VALUE IF NOT EXISTS 'breakfast'")
    else:
        with op.batch_alter_table("shopping_items") as b:
            b.alter_column(
                "store",
                type_=sa.String(100),
                existing_type=sa.String(20),
                nullable=True,
                server_default=None,
            )
        # sqlite хранит enum как строку — breakfast не требует DDL

    op.create_table(
        "llm_usage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("family_id", sa.Integer(), sa.ForeignKey("families.id"), nullable=False),
        sa.Column("operation", sa.String(30), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
    )
    op.create_index("ix_llm_usage_family_op", "llm_usage", ["family_id", "operation"])


def downgrade() -> None:
    op.drop_index("ix_llm_usage_family_op")
    op.drop_table("llm_usage")
    with op.batch_alter_table("family_members") as b:
        b.drop_column("can_plan")
        b.drop_column("role")
    with op.batch_alter_table("families") as b:
        b.drop_constraint("uq_families_invite_code", type_="unique")
        b.drop_column("invite_code")
        b.drop_column("plan_slots")
        b.drop_column("digest_enabled")
        b.drop_column("digest_hour")
        b.drop_column("timezone")
        b.drop_column("profile_md")

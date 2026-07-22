import enum
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date as DateType
from datetime import datetime
from typing import Annotated

from sqlalchemy import (
    JSON,
    BigInteger,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import true as sa_true
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from config import get_settings


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all ORM models."""


CreatedAt = Annotated[
    datetime,
    mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False),
]


class MenuStatus(enum.StrEnum):
    draft = "draft"
    active = "active"
    archived = "archived"


class MealSlot(enum.StrEnum):
    breakfast = "breakfast"
    lunch = "lunch"
    dinner = "dinner"


class MemberRole(enum.StrEnum):
    admin = "admin"
    member = "member"


class ProteinKind(enum.StrEnum):
    chicken = "chicken"
    fish = "fish"
    seafood = "seafood"
    beef = "beef"
    pork = "pork"
    vegetarian = "vegetarian"
    mixed = "mixed"


class MessageRole(enum.StrEnum):
    user = "user"
    assistant = "assistant"
    tool = "tool"


class Family(Base):
    __tablename__ = "families"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str | None] = mapped_column(String(200))
    profile_md: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(
        String(64), default="UTC", server_default="UTC", nullable=False
    )
    digest_hour: Mapped[int] = mapped_column(
        Integer, default=9, server_default="9", nullable=False
    )
    digest_enabled: Mapped[bool] = mapped_column(
        default=True, server_default=sa_true(), nullable=False
    )
    plan_slots: Mapped[list[str]] = mapped_column(
        JSON, default=lambda: ["lunch", "dinner"], nullable=False
    )
    invite_code: Mapped[str | None] = mapped_column(String(32), unique=True)
    created_at: Mapped[CreatedAt]

    members: Mapped[list["FamilyMember"]] = relationship(
        back_populates="family", cascade="all, delete-orphan"
    )


class FamilyMember(Base):
    __tablename__ = "family_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("families.id"), nullable=False)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[MemberRole] = mapped_column(
        Enum(MemberRole, native_enum=False, length=10),
        default=MemberRole.member,
        server_default="member",
        nullable=False,
    )
    created_at: Mapped[CreatedAt]

    family: Mapped["Family"] = relationship(back_populates="members")


class Menu(Base):
    __tablename__ = "menus"

    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("families.id"), nullable=False)
    start_date: Mapped[DateType] = mapped_column(Date, nullable=False)
    days_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[MenuStatus] = mapped_column(
        Enum(MenuStatus), default=MenuStatus.draft, nullable=False
    )
    created_at: Mapped[CreatedAt]
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    meals: Mapped[list["Meal"]] = relationship(
        back_populates="menu", cascade="all, delete-orphan", order_by="Meal.date, Meal.slot"
    )


class Meal(Base):
    __tablename__ = "meals"

    id: Mapped[int] = mapped_column(primary_key=True)
    menu_id: Mapped[int] = mapped_column(ForeignKey("menus.id"), nullable=False)
    date: Mapped[DateType] = mapped_column(Date, nullable=False)
    slot: Mapped[MealSlot] = mapped_column(Enum(MealSlot), nullable=False)
    dish_name: Mapped[str] = mapped_column(Text, nullable=False)
    side_dishes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    protein_kind: Mapped[ProteinKind] = mapped_column(Enum(ProteinKind), nullable=False)

    menu: Mapped["Menu"] = relationship(back_populates="meals")
    recipe: Mapped["Recipe | None"] = relationship(
        back_populates="meal", uselist=False, cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("menu_id", "date", "slot", name="uq_meal_slot"),)


class Recipe(Base):
    __tablename__ = "recipes"

    id: Mapped[int] = mapped_column(primary_key=True)
    meal_id: Mapped[int] = mapped_column(
        ForeignKey("meals.id"), unique=True, nullable=False
    )
    content_md: Mapped[str] = mapped_column(Text, nullable=False)
    ingredients: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    prep_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    generated_at: Mapped[CreatedAt]

    meal: Mapped["Meal"] = relationship(back_populates="recipe")


class ShoppingList(Base):
    __tablename__ = "shopping_lists"

    id: Mapped[int] = mapped_column(primary_key=True)
    menu_id: Mapped[int] = mapped_column(ForeignKey("menus.id"), nullable=False)
    created_at: Mapped[CreatedAt]


class ShoppingItem(Base):
    __tablename__ = "shopping_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    shopping_list_id: Mapped[int | None] = mapped_column(
        ForeignKey("shopping_lists.id")
    )
    family_id: Mapped[int] = mapped_column(ForeignKey("families.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    store: Mapped[str | None] = mapped_column(String(100))
    bought: Mapped[bool] = mapped_column(default=False, nullable=False)
    bought_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[CreatedAt]


class LlmUsage(Base):
    """Учет LLM-операций per family: триал-лимиты считаются по этой таблице."""

    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("families.id"), nullable=False)
    operation: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # menu_gen|replace|recipe|profile|shopping
    tokens_in: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[CreatedAt]


class ClaudeConversation(Base):
    __tablename__ = "claude_conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("families.id"), nullable=False)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    role: Mapped[MessageRole] = mapped_column(Enum(MessageRole), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[CreatedAt]


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        url = get_settings().db_url
        kwargs: dict = {"echo": False}
        if url.startswith("postgresql"):
            # LLM-вызовы держат сессию весь хендлер (мидлварь) — запас пула
            kwargs.update(pool_size=10, max_overflow=20, pool_timeout=30, pool_pre_ping=True)
        _engine = create_async_engine(url, **kwargs)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            get_engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _sessionmaker


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Commits on success, rolls back on error."""
    sm = get_sessionmaker()
    async with sm() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

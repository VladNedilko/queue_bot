from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase): pass

class User(Base):
    __tablename__ = "users"
    telegram_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(128))
    display_name: Mapped[str] = mapped_column(String(256))
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

class Proxy(Base):
    __tablename__ = "proxies"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    chat_id: Mapped[int] = mapped_column(Integer)
    thread_id: Mapped[int] = mapped_column(Integer)
    max_users: Mapped[int] = mapped_column(Integer, default=3)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("chat_id", "thread_id", name="uq_proxy_topic"),)

class ProxySession(Base):
    __tablename__ = "proxy_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    proxy_id: Mapped[int] = mapped_column(ForeignKey("proxies.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.telegram_id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)
    ended_reason: Mapped[str | None] = mapped_column(String(40))

class SessionConfirmation(Base):
    __tablename__ = "session_confirmations"
    session_id: Mapped[int] = mapped_column(ForeignKey("proxy_sessions.id"), primary_key=True)
    last_confirmed_at: Mapped[datetime] = mapped_column(DateTime)
    requested_at: Mapped[datetime | None] = mapped_column(DateTime)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)

class QueueItem(Base):
    __tablename__ = "queue"
    id: Mapped[int] = mapped_column(primary_key=True)
    proxy_id: Mapped[int] = mapped_column(ForeignKey("proxies.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.telegram_id"), index=True)
    state: Mapped[str] = mapped_column(String(16), default="waiting") # waiting, offered
    queued_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    offer_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    __table_args__ = (UniqueConstraint("proxy_id", "user_id", name="uq_queue_user_proxy"),)

class BotMessage(Base):
    __tablename__ = "bot_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    proxy_id: Mapped[int] = mapped_column(ForeignKey("proxies.id"), unique=True)
    chat_id: Mapped[int] = mapped_column(Integer)
    message_id: Mapped[int] = mapped_column(Integer)

class Admin(Base):
    __tablename__ = "admins"
    telegram_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class Event(Base):
    __tablename__ = "session_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    proxy_id: Mapped[int] = mapped_column(ForeignKey("proxies.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255))

def make_session_factory(url: str):
    engine = create_async_engine(url, future=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


from datetime import datetime, timedelta, timezone
from sqlalchemy import select, text, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from .database import User, Proxy, ProxySession, QueueItem, Event, Setting

def now(): return datetime.now(timezone.utc).replace(tzinfo=None)
def user_name(user): return user.full_name or user.username or str(user.id)

class QueueService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], ttl: int): self.sessions, self.ttl = sessions, ttl
    async def _lock(self, s):
        # SQLite serializes writers; PostgreSQL deployment should replace with SELECT ... FOR UPDATE on Proxy.
        await s.execute(text("BEGIN IMMEDIATE"))
    async def upsert_user(self, s, tg):
        u = await s.get(User, tg.id)
        if u: u.username, u.display_name = tg.username, user_name(tg)
        else: s.add(User(telegram_id=tg.id, username=tg.username, display_name=user_name(tg)))
    async def get_proxy(self, proxy_id: int):
        async with self.sessions() as s: return await s.get(Proxy, proxy_id)
    async def join(self, proxy_id, tg):
        async with self.sessions() as s:
            await self._lock(s); await self.upsert_user(s, tg)
            p = await s.get(Proxy, proxy_id)
            if not p or not p.is_enabled: return "missing", None
            if p.is_closed: return "closed", None
            active = (await s.scalars(select(ProxySession).where(ProxySession.user_id == tg.id, ProxySession.ended_at.is_(None)))).all()
            setting = await s.get(Setting, "allow_multiple_proxies")
            if active and (not setting or setting.value != "true"):
                return ("same" if active[0].proxy_id == proxy_id else "other"), active[0].proxy_id
            item = await s.scalar(select(QueueItem).where(QueueItem.proxy_id == proxy_id, QueueItem.user_id == tg.id))
            if item and item.state == "waiting":
                pos = await s.scalar(select(func.count()).select_from(QueueItem).where(QueueItem.proxy_id == proxy_id, QueueItem.state == "waiting", QueueItem.queued_at <= item.queued_at))
                return "queued", pos
            count = await s.scalar(select(func.count()).select_from(ProxySession).where(ProxySession.proxy_id == proxy_id, ProxySession.ended_at.is_(None)))
            offers = await s.scalar(select(func.count()).select_from(QueueItem).where(QueueItem.proxy_id == proxy_id, QueueItem.state == "offered"))
            # An offered place is reserved: a later direct click must not steal it.
            can_activate = bool(item and item.state == "offered" and count < p.max_users)
            can_join_directly = not item and count + offers < p.max_users
            if can_activate or can_join_directly:
                if item: await s.delete(item)
                s.add(ProxySession(proxy_id=proxy_id, user_id=tg.id)); s.add(Event(proxy_id=proxy_id, user_id=tg.id, kind="joined")); await s.commit(); return "joined", count + 1
            s.add(QueueItem(proxy_id=proxy_id, user_id=tg.id)); s.add(Event(proxy_id=proxy_id, user_id=tg.id, kind="queued")); await s.commit()
            pos = await s.scalar(select(func.count()).select_from(QueueItem).where(QueueItem.proxy_id == proxy_id, QueueItem.state == "waiting"))
            return "queued", pos
    async def leave(self, proxy_id, tg_id):
        async with self.sessions() as s:
            await self._lock(s); p = await s.get(Proxy, proxy_id)
            session = await s.scalar(select(ProxySession).where(ProxySession.proxy_id == proxy_id, ProxySession.user_id == tg_id, ProxySession.ended_at.is_(None)))
            if not session: return False, None
            session.ended_at, session.ended_reason = now(), "user_left"; s.add(Event(proxy_id=proxy_id, user_id=tg_id, kind="left")); offered = await self._offer_next(s, p)
            await s.commit(); return True, offered
    async def _offer_next(self, s, p):
        q = await s.scalar(select(QueueItem).where(QueueItem.proxy_id == p.id, QueueItem.state == "waiting").order_by(QueueItem.queued_at).limit(1))
        if not q: return None
        q.state, q.offer_expires_at = "offered", now() + timedelta(seconds=self.ttl); s.add(Event(proxy_id=p.id, user_id=q.user_id, kind="offered")); return q.user_id
    async def expire_offers(self):
        notices=[]
        async with self.sessions() as s:
            await self._lock(s)
            expired=(await s.scalars(select(QueueItem).where(QueueItem.state=="offered", QueueItem.offer_expires_at < now()))).all()
            for q in expired:
                pid=q.proxy_id; await s.delete(q); s.add(Event(proxy_id=pid,user_id=q.user_id,kind="offer_expired")); p=await s.get(Proxy,pid); n=await self._offer_next(s,p)
                if n: notices.append((pid,n))
            await s.commit()
        return notices
    async def snapshot(self, proxy_id):
        async with self.sessions() as s:
            p=await s.get(Proxy,proxy_id)
            active=(await s.execute(select(User.display_name, User.username, ProxySession.started_at).join(ProxySession, User.telegram_id==ProxySession.user_id).where(ProxySession.proxy_id==proxy_id, ProxySession.ended_at.is_(None)).order_by(ProxySession.started_at))).all()
            queue=(await s.execute(select(User.display_name, User.username, QueueItem.queued_at, QueueItem.state).join(QueueItem, User.telegram_id==QueueItem.user_id).where(QueueItem.proxy_id==proxy_id).order_by(QueueItem.queued_at))).all()
            return p, active, queue
    async def reset_proxy(self, proxy_id: int):
        async with self.sessions() as s:
            await self._lock(s)
            sessions = (await s.scalars(select(ProxySession).where(ProxySession.proxy_id == proxy_id, ProxySession.ended_at.is_(None)))).all()
            for item in sessions: item.ended_at, item.ended_reason = now(), "admin_reset"
            for item in (await s.scalars(select(QueueItem).where(QueueItem.proxy_id == proxy_id))).all(): await s.delete(item)
            s.add(Event(proxy_id=proxy_id, user_id=None, kind="reset")); await s.commit()

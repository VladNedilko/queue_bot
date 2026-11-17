import asyncio, logging
from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramNetworkError
from .config import load_settings
from .database import Base, Admin, Setting, make_session_factory
from .services import QueueService
from .handlers import router, refresh, restore_proxy_cards
from .keyboards import offer_keyboard, confirmation_keyboard

async def offer_watcher(bot, service, sessions):
    while True:
        try:
            for pid,uid in await service.expire_offers():
                p=await service.get_proxy(pid)
                topic_url = await service.topic_link(pid)
                await bot.send_message(uid, f'🔔 {p.name}: место доступно. Подтверди вход в течение 1 часа.', reply_markup=offer_keyboard(pid, topic_url))
            notifications, changed = await service.process_session_confirmations()
            for kind, proxy_id, user_id, session_id in notifications:
                proxy = await service.get_proxy(proxy_id)
                if kind == "confirm":
                    await bot.send_message(
                        user_id,
                        f"⏰ Ты используешь {proxy.name} уже 3 часа. Подтверди в течение 10 минут: остаться или выйти.",
                        reply_markup=confirmation_keyboard(session_id),
                    )
                else:
                    topic_url = await service.topic_link(proxy_id)
                    await bot.send_message(user_id, f'🔔 {proxy.name}: место доступно. Подтверди вход в течение 1 часа.', reply_markup=offer_keyboard(proxy_id, topic_url))
            for proxy_id in changed:
                await refresh(bot, service, sessions, proxy_id)
        except Exception: logging.exception('offer watcher failed')
        await asyncio.sleep(15)
async def main():
    cfg=load_settings(); logging.basicConfig(level=cfg.log_level,format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    engine,sessions=make_session_factory(cfg.database_url)
    async with engine.begin() as c: await c.run_sync(Base.metadata.create_all) # for first local start; Alembic is used in deployment
    async with sessions() as s:
        for user_id in cfg.bootstrap_admin_ids:
            if not await s.get(Admin, user_id): s.add(Admin(telegram_id=user_id))
        setting = await s.get(Setting, "allow_multiple_proxies")
        if setting:
            setting.value = str(cfg.allow_multiple_proxies).lower()
        else:
            s.add(Setting(key="allow_multiple_proxies", value=str(cfg.allow_multiple_proxies).lower()))
        await s.commit()
    bot=Bot(cfg.token); dp=Dispatcher(); dp.include_router(router)
    service=QueueService(sessions, cfg.offer_ttl_seconds, cfg.session_confirmation_interval_seconds, cfg.session_confirmation_grace_seconds)
    await restore_proxy_cards(bot, service, sessions)
    task=asyncio.create_task(offer_watcher(bot,service,sessions))
    try:
        while True:
            try:
                await dp.start_polling(bot, service=service, sessions=sessions)
                break  # polling was deliberately stopped
            except TelegramNetworkError as error:
                logging.warning("Telegram API is unavailable (%s); retrying in 10 seconds", error)
                await asyncio.sleep(10)
    finally: task.cancel(); await bot.session.close(); await engine.dispose()
if __name__=='__main__': asyncio.run(main())

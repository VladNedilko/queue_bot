import asyncio, logging
from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramNetworkError
from .config import load_settings
from .database import Base, Admin, Setting, make_session_factory
from .services import QueueService
from .handlers import router

async def offer_watcher(bot, service, sessions):
    while True:
        try:
            for pid,uid in await service.expire_offers():
                p=await service.get_proxy(pid); from .keyboards import offer_keyboard
                await bot.send_message(uid,f'🔔 {p.name}: место доступно. Подтверди вход в течение 5 минут.',reply_markup=offer_keyboard(pid))
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
    bot=Bot(cfg.token); dp=Dispatcher(); dp.include_router(router); service=QueueService(sessions,cfg.offer_ttl_seconds)
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

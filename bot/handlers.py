import asyncio
import logging
import re
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select, func
from .database import Proxy, Admin, BotMessage
from .keyboards import proxy_keyboard, offer_keyboard

router = Router(); log = logging.getLogger(__name__)
def topic(message): return message.message_thread_id if message.is_topic_message else None
def visible_name(name: str, username: str | None) -> str:
    return f"{name} (@{username})" if username else name
async def is_admin(message, sessions):
    if not message.from_user: return False
    async with sessions() as s: return bool(await s.get(Admin, message.from_user.id))

@router.message(Command("start"))
async def start(message: Message, sessions):
    """Show the operational guide only to configured bot administrators."""
    if not await is_admin(message, sessions):
        return await message.answer("Бот управляет очередью в topics группы. Доступ к административным командам ограничен.")
    await message.answer(
        "👋 Панель администратора очереди\n\n"
        "/setup <название> [лимит] — зарегистрировать или обновить proxy в текущем topic.\n"
        "/status — загрузка всех proxy в группе.\n"
        "/users — активные пользователи proxy.\n"
        "/queues — очереди всех proxy.\n"
        "/reset <id> — завершить сессии и очистить очередь proxy.\n\n"
        "Команду /setup отправляйте внутри нужного forum topic."
    )
async def render(service, proxy_id):
    p,a,q=await service.snapshot(proxy_id); names='\n'.join(f"👤 {visible_name(n,u)}" for n,u,_ in a) or "—"
    status="🔒 Недоступен" if p.is_closed else (f"🔴 Занято {len(a)}/{p.max_users}" if len(a)>=p.max_users else f"🟢 Свободно {len(a)}/{p.max_users}")
    queue='\n'.join(f"{i}. {visible_name(n,u)}" for i,(n,u,_,_) in enumerate(q,1)) or "нет"
    return f"🖥 {p.name}\n\nСтатус: {status}\n\n{names}\n\n📋 Очередь: {len(q)} человек\n{queue}"
async def refresh(bot, service, sessions, proxy_id):
    async with sessions() as s: bm=await s.scalar(select(BotMessage).where(BotMessage.proxy_id==proxy_id))
    if bm:
        try:
            await bot.edit_message_text(
                text=await render(service, proxy_id),
                chat_id=bm.chat_id,
                message_id=bm.message_id,
                reply_markup=proxy_keyboard(proxy_id),
            )
        except Exception: log.exception("Could not refresh proxy card")

@router.message(Command("setup"))
async def setup(message: Message, service, sessions):
    if not await is_admin(message,sessions): return await message.answer("⛔ Эта команда доступна только администратору бота. Добавьте свой Telegram ID в ADMIN_IDS и перезапустите бота.")
    tid=topic(message)
    if not tid: return await message.answer("Используйте /setup <название> [лимит] внутри нужного forum topic.")
    args=(message.text or '').split(maxsplit=2); name=args[1] if len(args)>1 else f"Прокси #{tid}"; limit=int(args[2]) if len(args)>2 and args[2].isdigit() else 3
    async with sessions() as s:
        p=await s.scalar(select(Proxy).where(Proxy.chat_id==message.chat.id,Proxy.thread_id==tid))
        if not p: p=Proxy(name=name,chat_id=message.chat.id,thread_id=tid,max_users=limit);s.add(p);await s.flush()
        else: p.name,p.max_users=name,limit
        await s.commit(); pid=p.id
    card=await message.answer(await render(service,pid),reply_markup=proxy_keyboard(pid))
    async with sessions() as s:
        old=await s.scalar(select(BotMessage).where(BotMessage.proxy_id==pid))
        if old: old.chat_id,old.message_id=card.chat.id,card.message_id
        else: s.add(BotMessage(proxy_id=pid,chat_id=card.chat.id,message_id=card.message_id))
        await s.commit()
    await message.answer("Готово: topic зарегистрирован.")

def is_proxy_callback(cb: CallbackQuery) -> bool:
    """Use an explicit predicate: it accepts only our compact callback protocol."""
    return bool(cb.data and re.fullmatch(r"[jlq]:\d+", cb.data))

@router.callback_query(is_proxy_callback)
async def callback(cb: CallbackQuery, service, sessions):
    action,pid=cb.data.split(':'); pid=int(pid); p=await service.get_proxy(pid)
    if not p or cb.message.chat.id!=p.chat_id or cb.message.message_thread_id!=p.thread_id: return await cb.answer("Недействительная кнопка",show_alert=True)
    if action=='q':
        _,_,q=await service.snapshot(pid)
        text='📋 Очередь\n'+('\n'.join(f"{i}. {visible_name(n,u)} — {t:%H:%M}" for i,(n,u,t,_) in enumerate(q,1)) or 'Пусто')
        # This is visible only to the button presser and does not require a private chat.
        return await cb.answer(text[:197] + ('…' if len(text) > 197 else ''), show_alert=True)
    if action=='j':
        result,data=await service.join(pid,cb.from_user)
        messages={'queued':f'❌ {p.name} заполнен. Ты в очереди №{data}.','closed':f'🔒 {p.name} недоступен.','same':f'Ты уже используешь {p.name}.','other':'Сначала выйди из другого прокси.','missing':'Прокси недоступен.'}
        await cb.answer(messages[result], show_alert=True) if result in messages else await cb.answer()
        await refresh(cb.bot,service,sessions,pid); return
    ok,offer=await service.leave(pid,cb.from_user.id)
    await cb.answer() if ok else await cb.answer('Ты не используешь этот прокси.',show_alert=True)
    await refresh(cb.bot,service,sessions,pid)
    if offer:
        await cb.bot.send_message(offer,f'🔔 {p.name} освободился. Подтверди вход в течение 5 минут.',reply_markup=offer_keyboard(pid))

@router.message(Command("status"))
async def status(message: Message, service, sessions):
    if not await is_admin(message,sessions): return await message.answer("⛔ Нет прав администратора бота.")
    async with sessions() as s: ps=(await s.scalars(select(Proxy).where(Proxy.chat_id==message.chat.id,Proxy.is_enabled.is_(True)).order_by(Proxy.id))).all()
    rows=[]
    for p in ps:
        _,a,q=await service.snapshot(p.id); icon='🔒' if p.is_closed else ('🔴' if len(a)>=p.max_users else '🟢'); rows.append(f'{icon} {p.name} — {len(a)}/{p.max_users} — очередь {len(q)}')
    await message.answer('📊 СОСТОЯНИЕ ПРОКСИ\n\n'+'\n'.join(rows or ['Нет зарегистрированных прокси']))

@router.message(Command("users"))
async def users(message: Message, service, sessions):
    if not await is_admin(message,sessions): return await message.answer("⛔ Нет прав администратора бота.")
    async with sessions() as s: ps=(await s.scalars(select(Proxy).where(Proxy.chat_id==message.chat.id,Proxy.is_enabled.is_(True)))).all()
    lines=[]
    for p in ps:
        _, active, _ = await service.snapshot(p.id)
        lines.append(f'{p.id}. {p.name}: '+(', '.join(visible_name(n,u) for n,u,_ in active) or 'свободен'))
    await message.answer('👥 ПОЛЬЗОВАТЕЛИ\n\n'+'\n'.join(lines or ['Нет прокси']))

@router.message(Command("queues"))
async def queues(message: Message, service, sessions):
    if not await is_admin(message,sessions): return await message.answer("⛔ Нет прав администратора бота.")
    async with sessions() as s: ps=(await s.scalars(select(Proxy).where(Proxy.chat_id==message.chat.id,Proxy.is_enabled.is_(True)))).all()
    lines=[]
    for p in ps:
        _, _, q = await service.snapshot(p.id)
        lines.append(f'{p.id}. {p.name}: '+(', '.join(visible_name(n,u) for n,u,_,_ in q) or 'пусто'))
    await message.answer('📋 ОЧЕРЕДИ\n\n'+'\n'.join(lines or ['Нет прокси']))

@router.message(Command("reset"))
async def reset(message: Message, service, sessions):
    if not await is_admin(message,sessions): return await message.answer("⛔ Нет прав администратора бота.")
    parts=(message.text or '').split()
    if len(parts) != 2 or not parts[1].isdigit(): return await message.answer('Использование: /reset <внутренний_id_прокси>. Команда завершит сессии и очистит очередь.')
    p=await service.get_proxy(int(parts[1]))
    if not p or p.chat_id != message.chat.id: return await message.answer('Прокси не найден.')
    await service.reset_proxy(p.id); await refresh(message.bot,service,sessions,p.id)
    await message.answer(f'Состояние {p.name} сброшено.')

@router.message(Command("help"))
async def help_command(message: Message):
    await message.answer("Команды: /setup <название> [лимит] — только внутри topic; /status, /users, /queues; /reset <id>.")

@router.message(F.text.startswith("/"))
async def unknown_command(message: Message):
    await message.answer("Команда не распознана. Используйте /help. Для регистрации topic: /setup Прокси-1 3")

@router.callback_query()
async def unknown_callback(cb: CallbackQuery):
    log.warning("Unknown callback received: %r", cb.data)
    await cb.answer("Кнопка устарела. Выполните /setup в этом topic ещё раз.", show_alert=True)

@router.message(F.forum_topic_closed)
async def closed(message: Message, sessions):
    async with sessions() as s:
        p=await s.scalar(select(Proxy).where(Proxy.chat_id==message.chat.id,Proxy.thread_id==topic(message)))
        if p: p.is_closed=True; await s.commit()
@router.message(F.forum_topic_reopened)
async def reopened(message: Message, sessions):
    async with sessions() as s:
        p=await s.scalar(select(Proxy).where(Proxy.chat_id==message.chat.id,Proxy.thread_id==topic(message)))
        if p: p.is_closed=False; await s.commit()

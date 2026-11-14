from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

def proxy_keyboard(proxy_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🟢 ЗАЙТИ", callback_data=f"j:{proxy_id}"), InlineKeyboardButton(text="🚪 ВЫЙТИ", callback_data=f"l:{proxy_id}")], [InlineKeyboardButton(text="📋 ОЧЕРЕДЬ", callback_data=f"q:{proxy_id}")]])

def offer_keyboard(proxy_id: int, topic_url: str | None = None) -> InlineKeyboardMarkup:
    # A URL button opens the relevant forum topic. The user confirms the
    # reserved place with the normal button on the topic's persistent card.
    if topic_url:
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🟢 ЗАЙТИ", url=topic_url),
        ]])
    # A registered proxy always has a card/link. Keep a safe fallback for an
    # incomplete setup rather than leaving an unusable notification.
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🟢 ЗАЙТИ", callback_data=f"j:{proxy_id}"),
    ]])

def confirmation_keyboard(session_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ ОСТАТЬСЯ", callback_data=f"c:{session_id}:s"),
        InlineKeyboardButton(text="🚪 ВЫЙТИ", callback_data=f"c:{session_id}:l"),
    ]])


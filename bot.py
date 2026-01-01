cat > bot.py <<'PY'
import os
import re
import asyncio
import random
import logging
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile,
)
from aiogram.enums import ParseMode


# ================== LOGGING ==================
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
log = logging.getLogger("TarotBot")

# ================== ENV ==================
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "@supor_service").strip()

# 0 = лимит включён (как было), 1 = без лимита (только для теста)
TEST_MODE = os.getenv("TEST_MODE", "0").strip() == "1"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN пустой. Проверь .env рядом с bot.py")

# ================== PATHS ==================
BASE_DIR = Path(__file__).resolve().parent
CARDS_DIR = BASE_DIR / "cards"
DB_PATH = BASE_DIR / "usage.db"

CARD_EXT = {".jpg", ".jpeg", ".png", ".webp"}
BACK_NAMES = {"back", "backs", "cardback", "cardbacks", "рубашка", "shirt"}


def list_card_files() -> list[Path]:
    if not CARDS_DIR.exists():
        return []
    files = []
    for p in CARDS_DIR.iterdir():
        if p.is_file() and p.suffix.lower() in CARD_EXT:
            if p.stem.lower() in BACK_NAMES:
                continue
            files.append(p)
    return sorted(files)


# ================== LIMIT DB (1 раз в сутки на тему) ==================
def db_init():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS daily_usage (
            user_id INTEGER NOT NULL,
            topic TEXT NOT NULL,
            day TEXT NOT NULL,
            PRIMARY KEY (user_id, topic)
        )
    """)
    con.commit()
    con.close()


def today_key() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def can_use_today(user_id: int, topic: str) -> bool:
    if TEST_MODE:
        return True

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT day FROM daily_usage WHERE user_id=? AND topic=?", (user_id, topic))
    row = cur.fetchone()
    con.close()

    if not row:
        return True
    return row[0] != today_key()


def mark_used_today(user_id: int, topic: str):
    if TEST_MODE:
        return

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        INSERT INTO daily_usage(user_id, topic, day)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, topic) DO UPDATE SET day=excluded.day
    """, (user_id, topic, today_key()))
    con.commit()
    con.close()


def seconds_to_midnight() -> int:
    now = datetime.now()
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(0, int((tomorrow - now).total_seconds()))


# ================== UI ==================
BTN_LOVE = "💗 Любовь"
BTN_MONEY = "💼 Деньги/работа"
BTN_ADVICE = "🌙 Совет дня"
BTN_SUPPORT = "🛟 Техподдержка"

TOPIC_HEADER = {"love": "💗 Любовь", "money": "💼 Деньги/работа", "advice": "🌙 Совет дня"}
TOPIC_TITLE = {"love": "Любовь", "money": "Деньги/работа", "advice": "Совет дня"}


def panel_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_LOVE), KeyboardButton(text=BTN_MONEY)],
            [KeyboardButton(text=BTN_ADVICE)],
            [KeyboardButton(text=BTN_SUPPORT)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выбери тему 👇",
    )


def support_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✉️ Написать в поддержку",
                    url=f"https://t.me/{SUPPORT_USERNAME.lstrip('@')}",
                )
            ]
        ]
    )


# ================== START TEXT ==================
START_TEXT = (
    "✨ Приветствую тебя в мире знаков и подсказок.\n"
    "Выбери тему — и посмотри, что важно для тебя сейчас 🔮"
)

# ================== AUTO RU CARD NAME ==================
def _normalize_name(stem: str) -> str:
    s = stem.strip()
    s = re.sub(r"^\d+\s*[-_ ]\s*", "", s).strip()
    s = s.replace("_", " ").replace("-", " ")
    s = re.sub(r"\s+", " ", s).strip()

    # wheelOfFortune / theHighPriestess и т.п.
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


MAJORS_RU = {
    "The Fool": "Шут",
    "Fool": "Шут",
    "The Magician": "Маг",
    "Magician": "Маг",
    "The High Priestess": "Верховная Жрица",
    "High Priestess": "Верховная Жрица",
    "The Empress": "Императрица",
    "Empress": "Императрица",
    "The Emperor": "Император",
    "Emperor": "Император",
    "The Hierophant": "Иерофант",
    "Hierophant": "Иерофант",
    "The Lovers": "Влюблённые",
    "Lovers": "Влюблённые",
    "The Chariot": "Колесница",
    "Chariot": "Колесница",
    "Strength": "Сила",
    "The Hermit": "Отшельник",
    "Hermit": "Отшельник",
    "Wheel Of Fortune": "Колесо Фортуны",
    "Wheel of Fortune": "Колесо Фортуны",
    "WheelOfFortune": "Колесо Фортуны",
    "Justice": "Справедливость",
    "The Hanged Man": "Повешенный",
    "Hanged Man": "Повешенный",
    "Death": "Смерть",
    "Temperance": "Умеренность",
    "The Devil": "Дьявол",
    "Devil": "Дьявол",
    "The Tower": "Башня",
    "Tower": "Башня",
    "The Star": "Звезда",
    "Star": "Звезда",
    "The Moon": "Луна",
    "Moon": "Луна",
    "The Sun": "Солнце",
    "Sun": "Солнце",
    "Judgement": "Суд",
    "Judgment": "Суд",
    "The World": "Мир",
    "World": "Мир",
}

SUITS_RU = {
    "cups": "Кубков",
    "wands": "Жезлов",
    "swords": "Мечей",
    "pentacles": "Пентаклей",
}

RANKS_RU = {
    1: "Туз",
    2: "Двойка",
    3: "Тройка",
    4: "Четвёрка",
    5: "Пятёрка",
    6: "Шестёрка",
    7: "Семёрка",
    8: "Восьмёрка",
    9: "Девятка",
    10: "Десятка",
    11: "Паж",
    12: "Рыцарь",
    13: "Королева",
    14: "Король",
}

RANK_WORDS = {
    "ace": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "page": 11,
    "knight": 12,
    "queen": 13,
    "king": 14,
}


def card_ru_from_file(path: Path) -> str:
    raw = _normalize_name(path.stem)

    # Старшие (точное совпадение)
    if raw in MAJORS_RU:
        return MAJORS_RU[raw]

    # Старшие (игнор "The")
    if raw.startswith("The "):
        alt = raw[4:]
        if alt in MAJORS_RU:
            return MAJORS_RU[alt]
        if f"The {alt}" in MAJORS_RU:
            return MAJORS_RU[f"The {alt}"]

    # Младшие: Cups02 / 02Cups / Cups 02
    m = re.search(r"(cups|wands|swords|pentacles)\s*0?(\d{1,2})", raw, re.I)
    if not m:
        m = re.search(r"0?(\d{1,2})\s*(cups|wands|swords|pentacles)", raw, re.I)
        if m:
            num = int(m.group(1))
            suit = m.group(2).lower()
            if suit in SUITS_RU and num in RANKS_RU:
                return f"{RANKS_RU[num]} {SUITS_RU[suit]}"
    else:
        suit = m.group(1).lower()
        num = int(m.group(2))
        if suit in SUITS_RU and num in RANKS_RU:
            return f"{RANKS_RU[num]} {SUITS_RU[suit]}"

    # Младшие: "Two of Cups", "Queen of Swords"
    m2 = re.search(
        r"\b(ace|two|three|four|five|six|seven|eight|nine|ten|page|knight|queen|king)\b\s+of\s+\b(cups|wands|swords|pentacles)\b",
        raw,
        re.I,
    )
    if m2:
        rank_num = RANK_WORDS.get(m2.group(1).lower())
        suit = m2.group(2).lower()
        if rank_num in RANKS_RU and suit in SUITS_RU:
            return f"{RANKS_RU[rank_num]} {SUITS_RU[suit]}"

    return raw  # fallback


# ================== TEXT ENGINE (always different) ==================
INTRO = [
    "Смотри, что карта подсвечивает прямо сейчас.",
    "Это простая подсказка на сейчас — без лишнего шума.",
    "Карта показывает тенденцию, а не приговор.",
    "Сейчас важно увидеть главное и не усложнять.",
    "Это про то, где ты теряешь силы и как их вернуть.",
]

LINK = [
    "Если говорить по-честному,",
    "Самое важное тут то, что",
    "По ощущениям выходит так:",
    "Суть в том, что",
    "Ключевой момент такой:",
]

SOFT = [
    "Делай шаг спокойно, без спешки.",
    "Не решай на эмоциях — сначала выдохни.",
    "Смотри на факты и на поступки.",
    "Не тащи чужое на себе.",
    "Дай себе время, и картинка сложится.",
]

TOPIC_WORDS = {
    "love": {
        "focus": ["чувства", "взаимность", "разговор", "границы", "неясность", "тепло"],
        "risk": ["догадки", "обиды", "ревность", "молчание", "перетягивание каната"],
        "step": [
            "скажи одну честную фразу без намёков",
            "не соглашайся на полумеры",
            "спроси прямо, что между вами",
            "держи границы там, где тебе неприятно",
            "смотри на поступки, а не на слова",
        ],
    },
    "money": {
        "focus": ["деньги", "работа", "сроки", "договорённости", "рост", "стабильность"],
        "risk": ["спешка", "лишние траты", "распыление", "невыгодные условия", "перегруз"],
        "step": [
            "проверь цифры и условия",
            "закрой один хвост, который тянется давно",
            "сделай план на 3 шага",
            "выбери один приоритет и держись его",
            "убери лишнее и оставь главное",
        ],
    },
    "advice": {
        "focus": ["настроение", "ресурс", "пауза", "темп", "ясность", "внутренний баланс"],
        "risk": ["усталость", "перегруз", "раздражение", "суета", "импульсивность"],
        "step": [
            "сделай паузу на 10 минут без телефона",
            "закрой одно дело до конца",
            "убери одну мелочь вокруг себя",
            "выбери тишину вместо спора",
            "сделай один маленький, но точный шаг",
        ],
    },
}

MAJOR_HINTS = {
    "Шут": ["новый старт", "лёгкость", "шанс", "смелость попробовать"],
    "Маг": ["инициатива", "влияние", "ресурс", "умение договориться"],
    "Верховная Жрица": ["интуиция", "тайна", "внутренний голос", "пауза"],
    "Императрица": ["забота", "рост", "тепло", "притяжение"],
    "Император": ["границы", "порядок", "ответственность", "правила"],
    "Влюблённые": ["выбор", "взаимность", "союз", "притяжение"],
    "Колесо Фортуны": ["поворот", "смена цикла", "шанс", "случайность"],
    "Справедливость": ["баланс", "честность", "договор", "последствия"],
    "Смерть": ["закрытие этапа", "обновление", "смена сценария", "перерождение"],
    "Луна": ["туман", "сомнения", "страхи", "неясность"],
    "Солнце": ["ясность", "радость", "успех", "простота"],
}

def _minor_hint(card_ru: str) -> list[str]:
    parts = card_ru.split()
    if len(parts) < 2:
        return ["важный знак", "тенденция", "подсказка"]

    rank = parts[0].lower()
    suit = parts[1].lower()

    suit_h = {
        "кубков": ["чувства", "принятие", "тепло", "близость"],
        "мечей": ["мысли", "правда", "разговор", "напряжение"],
        "жезлов": ["движение", "желание", "энергия", "инициатива"],
        "пентаклей": ["деньги", "быт", "стабильность", "результат"],
    }.get(suit, ["сфера жизни", "практика", "реальность"])

    rank_h = {
        "туз": ["начало", "шанс", "первый шаг"],
        "двойка": ["выбор", "диалог", "баланс"],
        "тройка": ["рост", "поддержка", "развитие"],
        "четвёрка": ["пауза", "границы", "стабильность"],
        "пятёрка": ["напряжение", "урок", "неудобный момент"],
        "шестёрка": ["движение", "облегчение", "выход"],
        "семёрка": ["проверка", "ожидание", "стратегия"],
        "восьмёрка": ["ускорение", "прогресс", "практика"],
        "девятка": ["пик", "переживания", "почти итог"],
        "десятка": ["результат", "финал", "закрытие цикла"],
        "паж": ["весть", "интерес", "первый опыт"],
        "рыцарь": ["действие", "движение", "напор"],
        "королева": ["мудрость", "чувство меры", "влияние мягко"],
        "король": ["контроль", "ответственность", "позиция"],
    }.get(rank, ["тенденция", "намёк", "переход"])

    return rank_h + suit_h

def card_hints(card_ru: str) -> list[str]:
    if card_ru in MAJOR_HINTS:
        return MAJOR_HINTS[card_ru]
    return _minor_hint(card_ru)

def make_text(topic: str, card_ru: str) -> str:
    tw = TOPIC_WORDS[topic]
    focus = random.choice(tw["focus"])
    risk = random.choice(tw["risk"])
    step = random.choice(tw["step"])
    hints = card_hints(card_ru)

    h1, h2 = random.sample(hints, k=2) if len(hints) >= 2 else (hints[0], hints[0])

    desc_count = random.choice([3, 4])
    desc = []
    desc.append(f"{random.choice(INTRO)}")
    desc.append(f"Твоя карта — <b>{card_ru}</b>. {random.choice(LINK)} здесь про <b>{h1}</b> и <b>{h2}</b>.")
    desc.append(f"Это затрагивает <b>{focus}</b>, и лучше не уходить в <b>{risk}</b>.")
    if desc_count == 4:
        desc.append(random.choice(SOFT))

    out_count = random.choice([3, 4])
    out = []
    out.append("<b>Вывод:</b>")
    out.append(f"Сейчас самое полезное — <b>{step}</b>.")
    out.append("Один спокойный шаг даст больше ясности, чем попытка всё контролировать сразу.")
    if out_count == 4:
        out.append("Если внутри тревожно — сделай паузу и вернись к решению позже, на свежую голову.")

    return "\n".join(desc) + "\n\n" + "\n".join(out)


# ================== ROUTER ==================
router = Router()


@router.message(CommandStart())
async def start_cmd(message: Message):
    extra = "\n\n🧪 <b>Тест-режим:</b> лимитов нет, можешь нажимать сколько угодно." if TEST_MODE else \
            "\n\nЛимит: 1 раз в сутки на каждую тему."
    await message.answer(START_TEXT + extra, reply_markup=panel_menu(), parse_mode=ParseMode.HTML)


@router.message(F.text == BTN_SUPPORT)
async def support_msg(message: Message):
    await message.answer("Техподдержка 👇", reply_markup=support_inline())


@router.message(F.text == "/debug")
async def debug_msg(message: Message):
    files = list_card_files()
    await message.answer(
        "🔎 <b>DEBUG</b>\n"
        f"BASE_DIR: <code>{BASE_DIR}</code>\n"
        f"CARDS_DIR: <code>{CARDS_DIR}</code>\n"
        f"CARDS_DIR exists: <b>{CARDS_DIR.exists()}</b>\n"
        f"Cards found: <b>{len(files)}</b>\n"
        f"TEST_MODE: <b>{TEST_MODE}</b>",
        parse_mode=ParseMode.HTML
    )


@router.message(F.text.in_({BTN_LOVE, BTN_MONEY, BTN_ADVICE}))
async def reading_from_menu(message: Message, bot: Bot):
    topic = "love" if message.text == BTN_LOVE else "money" if message.text == BTN_MONEY else "advice"
    user_id = message.from_user.id

    # ЛИМИТ (как было)
    if not can_use_today(user_id, topic):
        sec = seconds_to_midnight()
        h = sec // 3600
        m = (sec % 3600) // 60
        await message.answer(
            f"⛔ На сегодня лимит по теме «{TOPIC_TITLE[topic]}» уже исчерпан.\n"
            f"Новый расклад будет доступен после 00:00.\n"
            f"До обновления примерно: {h}ч {m}м",
            reply_markup=panel_menu(),
        )
        return

    files = list_card_files()
    if len(files) < 1:
        await message.answer(
            "Я не вижу папку <b>cards</b> или в ней нет картинок.\n\n"
            f"Папка должна быть тут: <code>{CARDS_DIR}</code>\n"
            "И внутри должны лежать файлы .jpg/.png/.webp",
            parse_mode=ParseMode.HTML,
            reply_markup=panel_menu()
        )
        return

    # отмечаем использование
    mark_used_today(user_id, topic)

    picked = random.choice(files)
    card_ru = card_ru_from_file(picked)

    await message.answer(f"{TOPIC_HEADER[topic]}\nТяну карту… ✨", reply_markup=panel_menu())
    await asyncio.sleep(0.35)

    await bot.send_photo(
        chat_id=message.chat.id,
        photo=FSInputFile(picked),
        caption=f"🃏 Твоя карта: <b>{card_ru}</b>",
        parse_mode=ParseMode.HTML,
    )

    await asyncio.sleep(0.25)

    text = make_text(topic, card_ru)
    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=panel_menu())


# ================== MAIN ==================
async def main():
    db_init()
    bot = Bot(BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    found = len(list_card_files())
    log.info("✅ BOT STARTED | TEST_MODE=%s | cards=%s | BASE_DIR=%s", TEST_MODE, found, BASE_DIR)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

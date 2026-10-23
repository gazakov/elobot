import os
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

def _parse_int(var_name: str) -> Optional[int]:
    val = os.getenv(var_name)
    if val and val.strip().isdigit():
        return int(val.strip())
    return None

def _parse_int_list(var_name: str) -> list[int]:
    val = os.getenv(var_name, "").strip()
    if not val:
        return []
    res = []
    for part in val.split(","):
        p = part.strip()
        if p.isdigit():
            res.append(int(p))
    return res

# Discord токен и настройки
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
GUILD_ID = _parse_int("GUILD_ID")
GUILD_IDS = _parse_int_list("GUILD_IDS")
if GUILD_ID and GUILD_ID not in GUILD_IDS:
    GUILD_IDS.append(GUILD_ID)

RESP_ROLE_NAME = os.getenv("RESP_ROLE_NAME", "⋆ 1v1s Responsible").strip()
RESP_ROLE_ID = _parse_int("RESP_ROLE_ID") or 1371133559531634851

ADMIN_ROLE_NAME = os.getenv("ADMIN_ROLE_NAME", "Администратор").strip()
ADMIN_ROLE_ID = _parse_int("ADMIN_ROLE_ID")

# Роли Duck и Duck Evade для регламента вызовов GANGHUB
DUCK_ROLE_NAME = os.getenv("DUCK_ROLE_NAME", "Duck").strip()
DUCK_ROLE_ID = _parse_int("DUCK_ROLE_ID") or 1372618658253111326

DUCK_EVADE_ROLE_NAME = os.getenv("DUCK_EVADE_ROLE_NAME", "Duck Evade").strip()
DUCK_EVADE_ROLE_ID = _parse_int("DUCK_EVADE_ROLE_ID") or 1562573962972627056

# Пользователи с абсолютным иммунитетом к вызовам на дуэль (/challenge) и дакам
CHALLENGE_IMMUNITY_IDS = set(_parse_int_list("CHALLENGE_IMMUNITY_IDS"))
CHALLENGE_IMMUNITY_IDS.add(1404137813007532095)

# Канал для официальных логов даков
DUCK_CHANNEL_NAME = os.getenv("DUCK_CHANNEL_NAME", "ducks").strip()
DUCK_CHANNEL_ID = _parse_int("DUCK_CHANNEL_ID") or 1534056814117916702

# Размер штрафа ELO за Дак (отказ от дуэли или игнорирование вызова)
DUCK_ELO_PENALTY = int(os.getenv("DUCK_ELO_PENALTY", "25"))

# Канал и ветка для соревновательных дуэлей и вызовов Лиги
FIGHTS_INFO_CHANNEL_ID = _parse_int("FIGHTS_INFO_CHANNEL_ID") or 1562574681637257387
FIGHTS_CHANNEL_ID = FIGHTS_INFO_CHANNEL_ID
FIGHTS_THREAD_NAME = os.getenv("FIGHTS_THREAD_NAME", "бот").strip()

# Ограничения и кулдаун на создание вызовов (/challenge)
CHALLENGE_COOLDOWN_SECONDS = int(os.getenv("CHALLENGE_COOLDOWN_SECONDS", "600"))
MAX_PENDING_CHALLENGES_PER_USER = int(os.getenv("MAX_PENDING_CHALLENGES_PER_USER", "1"))

# Канал для публичной фиксации результатов матчей Лиги (1v1s-elos)
_res_ch_env = os.getenv("MATCH_RESULTS_CHANNEL_ID")
if _res_ch_env is not None and _res_ch_env.strip() == "0":
    MATCH_RESULTS_CHANNEL_ID = None
elif _res_ch_env and _res_ch_env.strip().isdigit():
    MATCH_RESULTS_CHANNEL_ID = int(_res_ch_env.strip())
else:
    MATCH_RESULTS_CHANNEL_ID = 1562552971961565247

MATCH_RESULTS_CHANNEL_NAME = os.getenv("MATCH_RESULTS_CHANNEL_NAME", "1v1s-elos").strip()

QUEUE_CHANNEL_ID = _parse_int("QUEUE_CHANNEL_ID")
_default_db = "elo_yba.sqlite" if os.path.exists("elo_yba.sqlite") and not os.path.exists("data/elo_yba.sqlite") else "data/elo_yba.sqlite"
DB_PATH = os.getenv("DB_PATH", _default_db).strip()
_default_backup = "backups" if DB_PATH == "elo_yba.sqlite" else "data/backups"
BACKUP_DIR = os.getenv("BACKUP_DIR", _default_backup).strip()
BACKUP_MAX_DAYS = int(os.getenv("BACKUP_MAX_DAYS", "30"))
BACKUP_MAX_FILES = int(os.getenv("BACKUP_MAX_FILES", "50"))
LOG_DIR = os.getenv("LOG_DIR", "logs").strip()
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").strip().upper()
BLOXLINK_API_KEY = os.getenv("BLOXLINK_API_KEY", "").strip() or None
ENABLE_MESSAGE_CONTENT = os.getenv("ENABLE_MESSAGE_CONTENT", "false").lower() == "true"
ENABLE_MEMBERS_INTENT = os.getenv("ENABLE_MEMBERS_INTENT", "false").lower() == "true"

# Параметры калибровки
# Игрок считается Unranked первые 5 матчей
MIN_GAMES_CALIBRATION = 5
MAX_RD_CALIBRATION = 220.0

# Ранговая система, адаптированная под закрытый пул сервера:
# 🟤 Unranked / Калибровка (первые 5–10 матчей)
# 🥉 Bronze (< 1300 ELO)
# 🥈 Silver (1300 – 1499 ELO)
# 🥇 Gold (1500 – 1699 ELO)
# 🔘 Platinum (1700 – 1849 ELO)
# 💎 Diamond (1850 – 1999 ELO)
# 🔮 Master (2000 – 2149 ELO)
# 👑 Grandmaster (2150+ ELO, требует ~75-80% винрейта)
# 🏆 Top 10 (уникальная роль для лучших игроков сезона)
RANKS = [
    {
        "name": "Bronze",
        "min_rating": 0,
        "max_rating": 1299,
        "badge": "🥉",
        "color": 0xCD7F32, # Бронзовый
    },
    {
        "name": "Silver",
        "min_rating": 1300,
        "max_rating": 1499,
        "badge": "🥈",
        "color": 0xC0C0C0, # Серебряный
    },
    {
        "name": "Gold",
        "min_rating": 1500,
        "max_rating": 1699,
        "badge": "🥇",
        "color": 0xFFD700, # Золотой
    },
    {
        "name": "Platinum",
        "min_rating": 1700,
        "max_rating": 1849,
        "badge": "🔘",
        "color": 0x3498DB, # Платиновый / Лазурный
    },
    {
        "name": "Diamond",
        "min_rating": 1850,
        "max_rating": 1999,
        "badge": "💎",
        "color": 0x00D2D3, # Алмазный / Бирюзовый
    },
    {
        "name": "Master",
        "min_rating": 2000,
        "max_rating": 2149,
        "badge": "🔮",
        "color": 0x9B59B6, # Фиолетовый
    },
    {
        "name": "Grandmaster",
        "min_rating": 2150,
        "max_rating": 99999,
        "badge": "👑",
        "color": 0xE74C3C, # Рубиновый / Красный
    },
]

SPECIAL_ROLES = {
    "CALIBRATION": {"name": "Unranked / Калибровка", "badge": "🟤", "color": 0x8B5A2B},
    "TOP_10": {"name": "Top 10", "badge": "🏆", "color": 0xF39C12},
    "TOP_1": {"name": "Чемпион (Top 1)", "badge": "👑", "color": 0xF1C40F},
}

# Кулдаун на смену страны (в днях)
COUNTRY_COOLDOWN_DAYS = int(os.getenv("COUNTRY_COOLDOWN_DAYS", "30"))

# Белый список стран (Европа и СНГ без мемных/тролльных вариантов вроде Узбекистана и Таджикистана)
COUNTRIES = {
    "RU": {"name_ru": "Россия", "name_en": "Russia", "flag": "🇷🇺", "aliases": ["рф", "рус", "рашка", "российская"]},
    "UA": {"name_ru": "Украина", "name_en": "Ukraine", "flag": "🇺🇦", "aliases": ["укр", "україна"]},
    "KZ": {"name_ru": "Казахстан", "name_en": "Kazakhstan", "flag": "🇰🇿", "aliases": ["каз", "қазақстан"]},
    "BY": {"name_ru": "Беларусь", "name_en": "Belarus", "flag": "🇧🇾", "aliases": ["рб", "белоруссия"]},
    "GE": {"name_ru": "Грузия", "name_en": "Georgia", "flag": "🇬🇪", "aliases": ["сакартвело"]},
    "AM": {"name_ru": "Армения", "name_en": "Armenia", "flag": "🇦🇲", "aliases": ["хайастан"]},
    "AZ": {"name_ru": "Азербайджан", "name_en": "Azerbaijan", "flag": "🇦🇿", "aliases": ["аз"]},
    "MD": {"name_ru": "Молдова", "name_en": "Moldova", "flag": "🇲🇩", "aliases": ["молдавия"]},
    "KG": {"name_ru": "Кыргызстан", "name_en": "Kyrgyzstan", "flag": "🇰🇬", "aliases": ["киргизия"]},
    "PL": {"name_ru": "Польша", "name_en": "Poland", "flag": "🇵🇱", "aliases": ["polska"]},
    "DE": {"name_ru": "Германия", "name_en": "Germany", "flag": "🇩🇪", "aliases": ["deutschland", "нем"]},
    "LV": {"name_ru": "Латвия", "name_en": "Latvia", "flag": "🇱🇻", "aliases": ["latvija"]},
    "LT": {"name_ru": "Литва", "name_en": "Lithuania", "flag": "🇱🇹", "aliases": ["lietuva"]},
    "EE": {"name_ru": "Эстония", "name_en": "Estonia", "flag": "🇪🇪", "aliases": ["eesti"]},
    "CZ": {"name_ru": "Чехия", "name_en": "Czech Republic", "flag": "🇨🇿", "aliases": ["cesko"]},
    "RS": {"name_ru": "Сербия", "name_en": "Serbia", "flag": "🇷🇸", "aliases": ["srbija"]},
    "BG": {"name_ru": "Болгария", "name_en": "Bulgaria", "flag": "🇧🇬", "aliases": ["българия"]},
    "RO": {"name_ru": "Румыния", "name_en": "Romania", "flag": "🇷🇴", "aliases": ["romania"]},
    "FI": {"name_ru": "Финляндия", "name_en": "Finland", "flag": "🇫🇮", "aliases": ["suomi"]},
    "SE": {"name_ru": "Швеция", "name_en": "Sweden", "flag": "🇸🇪", "aliases": ["sverige"]},
    "GB": {"name_ru": "Великобритания", "name_en": "United Kingdom", "flag": "🇬🇧", "aliases": ["uk", "англия", "британия", "england"]},
    "FR": {"name_ru": "Франция", "name_en": "France", "flag": "🇫🇷", "aliases": ["la france"]},
    "IT": {"name_ru": "Италия", "name_en": "Italy", "flag": "🇮🇹", "aliases": ["italia"]},
    "ES": {"name_ru": "Испания", "name_en": "Spain", "flag": "🇪🇸", "aliases": ["espana"]},
    "NL": {"name_ru": "Нидерланды", "name_en": "Netherlands", "flag": "🇳🇱", "aliases": ["голландия", "holland"]},
    "TR": {"name_ru": "Турция", "name_en": "Turkey", "flag": "🇹🇷", "aliases": ["turkiye"]},
    "IL": {"name_ru": "Израиль", "name_en": "Israel", "flag": "🇮🇱", "aliases": ["israel"]},
    "US": {"name_ru": "США", "name_en": "United States", "flag": "🇺🇸", "aliases": ["usa", "штаты", "америка"]},
}

def get_country_info(code: Optional[str]) -> Optional[dict]:
    if not code:
        return None
    return COUNTRIES.get(code.upper().strip())

def get_country_flag(code: Optional[str], with_space: bool = True) -> str:
    """Возвращает флаг-эмодзи страны (с пробелом по умолчанию для чистого форматирования) или пустую строку"""
    info = get_country_info(code)
    if not info:
        return ""
    return f"{info['flag']} " if with_space else info["flag"]


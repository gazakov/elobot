import urllib.request
import json
import time
from typing import Optional, Tuple, List, Dict, Any
import config
from database import Database
from logger import log

_user_cache: Dict[int, Tuple[Dict[str, Any], float]] = {}

def get_bloxlink_key(db: Optional[Database] = None) -> Optional[str]:
    """Возвращает API ключ Bloxlink из базы данных или переменных окружения"""
    if db:
        try:
            val = db.get_setting("bloxlink_api_key")
            if val and val.strip():
                return val.strip()
        except Exception:
            pass
    return config.BLOXLINK_API_KEY


def get_roblox_user_by_id(roblox_id: int) -> Optional[Dict[str, Any]]:
    """Получает информацию о пользователе Roblox по его ID с кэшированием"""
    now = time.time()
    if roblox_id in _user_cache:
        cached, ts = _user_cache[roblox_id]
        if now - ts < 3600.0:
            return cached

    try:
        url = f"https://users.roblox.com/v1/users/{roblox_id}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data and data.get("name"):
                _user_cache[roblox_id] = (data, now)
                return data
    except Exception:
        return None
    return None


def get_roblox_account_info(username_or_id: Any) -> Optional[Dict[str, Any]]:
    """Получает детальную информацию о Roblox аккаунте: ID, дату создания, возраст аккаунта"""
    from datetime import datetime, timezone

    user_info = None
    if isinstance(username_or_id, int) or (isinstance(username_or_id, str) and username_or_id.isdigit()):
        user_info = get_roblox_user_by_id(int(username_or_id))
    else:
        # Поиск по username
        clean_name = str(username_or_id).strip().lstrip("@")
        try:
            req = urllib.request.Request(
                "https://users.roblox.com/v1/usernames/users",
                data=json.dumps({"usernames": [clean_name]}).encode("utf-8"),
                headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=3.5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("data"):
                    user_id = data["data"][0]["id"]
                    user_info = get_roblox_user_by_id(user_id)
        except Exception:
            return None

    if not user_info:
        return None

    created_str = user_info.get("created", "")
    created_fmt = "—"
    days_old = 9999
    years_old = 0.0
    is_new = False

    if created_str:
        try:
            dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
            now_dt = datetime.now(timezone.utc)
            days_old = max(0, (now_dt - dt).days)
            years_old = round(days_old / 365.25, 1)
            created_fmt = dt.strftime("%d.%m.%Y")
            is_new = (days_old < 30)
        except Exception:
            pass

    return {
        "id": user_info["id"],
        "username": user_info["name"],
        "display_name": user_info.get("displayName") or user_info["name"],
        "created_date": created_fmt,
        "days_old": days_old,
        "years_old": years_old,
        "is_new": is_new,
        "profile_url": f"https://www.roblox.com/users/{user_info['id']}/profile"
    }


def resolve_discord_to_roblox(guild_id: int, user_id: int, api_key: str) -> Optional[Tuple[int, str]]:
    """
    Запрашивает у Bloxlink Server API Roblox ID пользователя и преобразует его в username.
    Поддерживает серверный эндпоинт, глобальный fallback, а также ключи robloxID, primaryAccount и resolved.
    Возвращает кортеж (roblox_id, roblox_username) или None.
    """
    if not api_key:
        return None

    guild_candidates = [guild_id] if guild_id else []
    if getattr(config, "GUILD_ID", None) and config.GUILD_ID not in guild_candidates:
        guild_candidates.append(config.GUILD_ID)

    for g_id in guild_candidates:
        if not g_id:
            continue
        try:
            url = f"https://api.blox.link/v4/public/guilds/{g_id}/discord-to-roblox/{user_id}"
            req = urllib.request.Request(
                url,
                headers={
                    "Authorization": api_key,
                    "User-Agent": "Mozilla/5.0"
                }
            )
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                if resp.status != 200:
                    continue
                data = json.loads(resp.read().decode("utf-8"))
                roblox_id_val = (
                    data.get("robloxID")
                    or data.get("primaryAccount")
                    or data.get("robloxId")
                    or (isinstance(data.get("resolved"), dict) and data["resolved"].get("robloxID"))
                )
                if not roblox_id_val and isinstance(data.get("accounts"), list) and data["accounts"]:
                    roblox_id_val = data["accounts"][0]

                if not roblox_id_val:
                    continue
                roblox_id = int(roblox_id_val)

            # Получаем точный @username из официального Roblox API
            user_info = get_roblox_user_by_id(roblox_id)
            if user_info and user_info.get("name"):
                return roblox_id, user_info["name"]
        except urllib.error.HTTPError as e:
            if e.code == 404:
                log.info(f"ℹ️ [Bloxlink] Пользователь {user_id} не верифицирован в guild {g_id} (404)")
            elif e.code in (401, 403):
                log.warning(f"⚠️ [Bloxlink] Ошибка {e.code} для guild {g_id}: проверьте API ключ и наличие бота Bloxlink на сервере.")
            else:
                log.warning(f"⚠️ [Bloxlink] Ошибка {e.code} при поиске user {user_id} в guild {g_id}: {e}")
        except Exception as e:
            log.warning(f"⚠️ [Bloxlink] Исключение при поиске user {user_id} в guild {g_id}: {e}")
            continue

    # Fallback: опрос глобального эндпоинта Bloxlink
    try:
        url = f"https://api.blox.link/v4/public/discord-to-roblox/{user_id}"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": api_key,
                "User-Agent": "Mozilla/5.0"
            }
        )
        with urllib.request.urlopen(req, timeout=4.0) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                roblox_id_val = (
                    data.get("robloxID")
                    or data.get("primaryAccount")
                    or data.get("robloxId")
                    or (isinstance(data.get("resolved"), dict) and data["resolved"].get("robloxID"))
                )
                if not roblox_id_val and isinstance(data.get("accounts"), list) and data["accounts"]:
                    roblox_id_val = data["accounts"][0]

                if roblox_id_val:
                    roblox_id = int(roblox_id_val)
                    user_info = get_roblox_user_by_id(roblox_id)
                    if user_info and user_info.get("name"):
                        return roblox_id, user_info["name"]
    except Exception:
        pass

    return None


def fetch_roblox_info_by_discord(guild_id: int, user_id: int, api_key: str) -> Optional[Dict[str, Any]]:
    """
    Получает полную информацию о Roblox-аккаунте по Discord ID через Bloxlink и Roblox API.
    Включает дату регистрации, количество дней, флаг <30 дней и профиль.
    """
    pair = resolve_discord_to_roblox(guild_id, user_id, api_key)
    if not pair:
        return None
    roblox_id, _ = pair
    return get_roblox_account_info(roblox_id)


def resolve_roblox_to_discord(guild_id: int, roblox_id: int, api_key: str) -> List[int]:
    """
    Обратный поиск Bloxlink: находит все Discord ID на сервере, связанные с данным Roblox ID.
    Критически важно для выявления твинков и подсадов (пассажиров).
    """
    if not api_key:
        return []

    guild_candidates = [guild_id] if guild_id else []
    if getattr(config, "GUILD_ID", None) and config.GUILD_ID not in guild_candidates:
        guild_candidates.append(config.GUILD_ID)

    for g_id in guild_candidates:
        if not g_id:
            continue
        try:
            url = f"https://api.blox.link/v4/public/guilds/{g_id}/roblox-to-discord/{roblox_id}"
            req = urllib.request.Request(
                url,
                headers={
                    "Authorization": api_key,
                    "User-Agent": "Mozilla/5.0"
                }
            )
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                if resp.status != 200:
                    continue
                data = json.loads(resp.read().decode("utf-8"))
                discord_ids = data.get("discordIDs", [])
                if discord_ids:
                    return [int(uid) for uid in discord_ids if str(uid).isdigit()]
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 404):
                continue
            log.warning(f"⚠️ [Bloxlink] Ошибка {e.code} при reverse-поиске roblox_id {roblox_id} в guild {g_id}: {e}")
        except Exception as e:
            log.warning(f"⚠️ [Bloxlink] Исключение при reverse-поиске roblox_id {roblox_id} в guild {g_id}: {e}")
            continue

    return []


def test_bloxlink_key(guild_id: int, api_key: str) -> Tuple[bool, str]:
    """Проверяет валидность ключа Bloxlink API для сервера"""
    if not api_key:
        return False, "Ключ не указан"

    try:
        # Тестовый запрос (даже если 404 - ключ верный, если 401/400 - неверный)
        url = f"https://api.blox.link/v4/public/guilds/{guild_id}/discord-to-roblox/123456789"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": api_key,
                "User-Agent": "Mozilla/5.0"
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=4.0):
                return True, "Ключ действителен"
        except urllib.error.HTTPError as e:
            if e.code == 404:
                # 404 означает, что авторизация успешна, но пользователь 123456789 не найден
                return True, "Ключ действителен и авторизован для данного сервера"
            elif e.code in (401, 403):
                return False, "Неверный API-ключ или нет прав доступа к серверу"
            elif e.code == 400:
                err_body = e.read().decode("utf-8", errors="ignore")
                return False, f"Ошибка запроса: {err_body}"
            else:
                return False, f"HTTP ошибка {e.code}"
    except Exception as e:
        return False, f"Ошибка соединения: {e}"

import asyncio
import re
import time
from datetime import datetime, timezone, timedelta
import discord
from discord import app_commands
from discord.ext import commands, tasks
from typing import Optional, Tuple, Dict, Any, Union
from urllib.parse import urlsplit
import config
import locales
import bloxlink
from bloxlink import fetch_roblox_info_by_discord
from database import Database
from ranks import get_rank_info, sync_user_roles
from logger import log

def check_is_resp_or_admin(member: Any, guild: Optional[discord.Guild] = None) -> bool:
    """Универсальная проверка прав: пользователь должен быть респом или администратором"""
    if not member or not hasattr(member, "roles"):
        return False

    if getattr(member, "guild_permissions", None) and member.guild_permissions.administrator:
        return True

    user_role_ids = {r.id for r in member.roles}
    user_role_names = {r.name for r in member.roles}

    # 1. Проверка по Snowflake ID (включая настроенные и известные ID ролей респов)
    valid_resp_ids = {1371133559531634851, 1562473046739263622}
    if config.RESP_ROLE_ID is not None:
        valid_resp_ids.add(config.RESP_ROLE_ID)

    if any(rid in user_role_ids for rid in valid_resp_ids):
        return True

    if config.ADMIN_ROLE_ID is not None and config.ADMIN_ROLE_ID in user_role_ids:
        return True

    # 2. Если RESP_ROLE_ID не задан в конфиге, разрешаем поиск по имени
    if config.RESP_ROLE_ID is None:
        if config.RESP_ROLE_NAME and config.RESP_ROLE_NAME in user_role_names:
            return True
        for r in member.roles:
            r_name_lower = r.name.lower()
            if (
                "1v1 elo responsible" in r_name_lower
                or "1v1s responsible" in r_name_lower
                or "1v1 responsible" in r_name_lower
                or "респонсибл" in r_name_lower
                or "респ" in r_name_lower
            ):
                return True

    if config.ADMIN_ROLE_ID is None and config.ADMIN_ROLE_NAME and config.ADMIN_ROLE_NAME in user_role_names:
        return True

    return False

def is_resp_or_admin(interaction: discord.Interaction) -> bool:
    """Проверка прав: пользователь должен быть респом или администратором"""
    if not interaction.guild or not hasattr(interaction.user, "roles"):
        return False
    return check_is_resp_or_admin(interaction.user, interaction.guild)


async def get_or_create_fights_channel(guild: discord.Guild, db: Optional[Database] = None) -> Optional[discord.abc.GuildChannel]:
    """
    Находит или создает официальный форум-канал Лиги для дуэлей (ForumChannel):
    1. Ищет целевой канал по настройке в БД ('fights_channel_id') или FIGHTS_INFO_CHANNEL_ID (1562574681637257387).
    2. Если не найден (например, на тестовом сервере):
       - Ищет существующий форум-канал по имени 'elo-1v1', 'файты-инфо', 'fights-info' или 'find-your-enemy'
       - Если нет — находит/создает категорию '🏆 GANGHUB LEAGUE'
       - Создает в ней ForumChannel 'файты-инфо'
       - При ошибке прав откатывается к TextChannel
    """
    if not guild:
        return None

    target_channel = None
    target_id = None

    if db:
        try:
            val = await asyncio.to_thread(db.get_setting, "fights_channel_id")
            if val and val.isdigit():
                target_id = int(val)
        except Exception:
            pass

    if not target_id:
        target_id = config.FIGHTS_INFO_CHANNEL_ID

    # 1. Проверяем по ID (основной сервер)
    if target_id:
        target_channel = guild.get_channel(target_id)
        if not target_channel:
            try:
                target_channel = await guild.fetch_channel(target_id)
            except Exception:
                target_channel = None

    # 2. Если канал по ID не найден (тестовый сервер)
    if not target_channel:
        # Проверяем форумы и текстовые каналы
        for ch in guild.channels:
            if isinstance(ch, (discord.ForumChannel, discord.TextChannel)) and (
                ch.name in ("файты-инфо", "fights-info", "find-your-enemy", "elo-1v1", "1v1-elo")
                or "elo-1v1" in ch.name.lower()
                or "fights" in ch.name.lower()
            ):
                target_channel = ch
                break

        if not target_channel:
            category_name = "🏆 GANGHUB LEAGUE"
            category = discord.utils.get(guild.categories, name=category_name)
            if not category:
                try:
                    category = await guild.create_category(
                        name=category_name,
                        reason="Категория Лиги GANGHUB для 1v1 дуэлей"
                    )
                except Exception as e:
                    log.warning(f"⚠️ Не удалось создать категорию {category_name}: {e}")
                    category = None

            # Пытаемся создать полноценный Форум-канал
            try:
                target_channel = await guild.create_forum(
                    name="файты-инфо",
                    category=category,
                    topic="Официальный соревновательный форум Лиги GANGHUB для 1v1 дуэлей",
                    reason="Создание форума дуэлей Лиги GANGHUB"
                )
            except Exception as e:
                log.warning(f"⚠️ Не удалось создать ForumChannel, создаем TextChannel: {e}")
                try:
                    target_channel = await guild.create_text_channel(
                        name="файты-инфо",
                        category=category,
                        topic="Официальный канал Лиги GANGHUB для 1v1 дуэлей",
                        reason="Создание резервного канала для Лиги"
                    )
                except Exception as ex:
                    log.error(f"❌ Не удалось создать канал дуэлей: {ex}")
                    target_channel = None

    return target_channel


def validate_proof_url(proof: Optional[str], lang: str = "ru") -> Tuple[bool, str]:
    """Строгая валидация URL доказательства для защиты от фишинга и Markdown Injection"""
    if not proof:
        return True, ""
    proof = proof.strip()
    if len(proof) > 256:
        return False, "❌ Invalid proof URL! Length exceeds 256 characters." if lang == "en" else "❌ Некорректная ссылка на пруф! Длина ссылки превышает 256 символов."

    # Защита от разрыва Markdown Embed [текст](ссылка) и управляющих символов
    forbidden_chars = {" ", "\r", "\n", "\t", ")", "(", "<", ">", '"', "[", "]"}
    if any(c in proof for c in forbidden_chars):
        return False, "❌ Invalid characters in URL! Link must not contain spaces, brackets or quotes." if lang == "en" else "❌ Некорректные символы в ссылке! Ссылка не должна содержать пробелов, скобок или кавычек."

    try:
        parsed = urlsplit(proof)
    except Exception:
        return False, "❌ Invalid URL syntax." if lang == "en" else "❌ Некорректный синтаксис URL адреса."

    if parsed.scheme not in ("https", "http"):
        return False, "❌ Link must start with http:// or https://." if lang == "en" else "❌ Ссылка должна начинаться с http:// или https://."

    if not parsed.netloc or not parsed.hostname:
        return False, "❌ Invalid domain name in URL." if lang == "en" else "❌ Некорректный адрес домена в ссылке."

    hostname = parsed.hostname.lower()
    suspicious_domains = ("grabify", "iplogger", "2no.co", "yip.su", "iplis.ru", "02ip.ru", "ezstat.ru")
    if any(dom in hostname for dom in suspicious_domains):
        return False, "❌ Prohibited domain detected (IP loggers and trackers are not allowed)!" if lang == "en" else "❌ Обнаружена запрещенная ссылка (IP-логгеры и трекеры запрещены)!"

    return True, ""


def get_resp_role(guild: Optional[discord.Guild]) -> Optional[discord.Role]:
    """Находит официальную роль Респонсиблов для пинга судей в матчах"""
    if not guild:
        return None
    for rid in (1562473046739263622, config.RESP_ROLE_ID):
        if not rid:
            continue
        role = guild.get_role(rid)
        if role:
            if hasattr(guild, "roles") and isinstance(guild.roles, list) and not guild.roles:
                role = None
            elif hasattr(guild, "roles") and isinstance(guild.roles, list) and guild.roles and role not in guild.roles:
                role = None
            if role:
                return role
    for r in guild.roles:
        r_name_lower = r.name.lower()
        if (
            "1v1 elo responsible" in r_name_lower
            or r.name == config.RESP_ROLE_NAME
            or "1v1s responsible" in r_name_lower
            or "gang responsible" in r_name_lower
            or "респонсибл" in r_name_lower
            or "респ" in r_name_lower
        ):
            return r
    return None


def get_duck_role(guild: Optional[discord.Guild]) -> Optional[discord.Role]:
    """Находит официальную роль Duck для автоматического наказания уклоняющихся"""
    if not guild:
        return None
    if config.DUCK_ROLE_ID:
        role = guild.get_role(config.DUCK_ROLE_ID)
        if role:
            return role
    for r in guild.roles:
        r_name_lower = r.name.lower()
        if (
            r.name == config.DUCK_ROLE_NAME
            or r_name_lower == "duck"
            or "дак" in r_name_lower
            or "🦆" in r.name
        ):
            return r
    return None


def has_duck_evade(member: Optional[discord.Member]) -> bool:
    """Проверяет наличие роли Duck Evade (иммунитет к роли Duck)"""
    if not member:
        return False
    if getattr(member, "id", None) in config.CHALLENGE_IMMUNITY_IDS:
        return True
    if not hasattr(member, "roles"):
        return False

    if config.DUCK_EVADE_ROLE_ID and any(r.id == config.DUCK_EVADE_ROLE_ID for r in member.roles):
        return True
    return any(
        r.name == config.DUCK_EVADE_ROLE_NAME
        or "duck evade" in r.name.lower()
        or "evade" in r.name.lower()
        for r in member.roles
    )


async def get_duck_channel(guild: Optional[discord.Guild], db: Database) -> Optional[discord.TextChannel]:
    """Находит официальный канал для публикации логов даков (Duck Logs)"""
    if not guild:
        return None

    # 1. Проверяем настройку в БД (/duck_channel set)
    channel_id_setting = await asyncio.to_thread(db.get_setting, "duck_channel_id")
    if channel_id_setting and channel_id_setting.isdigit():
        ch = guild.get_channel(int(channel_id_setting))
        if isinstance(ch, discord.TextChannel):
            return ch

    # 2. Проверяем Snowflake ID из config (.env)
    if config.DUCK_CHANNEL_ID:
        ch = guild.get_channel(config.DUCK_CHANNEL_ID)
        if isinstance(ch, discord.TextChannel):
            return ch

    # 3. Автоматический поиск текстового канала по названию среди каналов сервера
    for ch in guild.text_channels:
        name_lower = ch.name.lower()
        if (
            name_lower == config.DUCK_CHANNEL_NAME.lower()
            or "дак" in name_lower
            or "duck" in name_lower
            or "🦆" in ch.name
        ):
            return ch

    return None


async def get_match_results_channel(
    guild: Optional[discord.Guild],
    db: Optional[Database] = None,
    client: Optional[discord.Client] = None
) -> Optional[Union[discord.TextChannel, discord.Thread]]:
    """
    Находит официальный канал для публикации результатов матчей 1v1:
    1. Настройка в базе данных (ключ 'match_results_channel_id')
    2. config.MATCH_RESULTS_CHANNEL_ID (по умолчанию 1562552971961565247)
    3. Автоматический поиск текстового канала по ключевым названиям (1v1s-elos, match-results и т.д.)
    """
    target_id: Optional[int] = None
    if db:
        try:
            val = await asyncio.to_thread(db.get_setting, "match_results_channel_id")
            if val and val.isdigit():
                target_id = int(val)
        except Exception:
            pass

    if not target_id:
        target_id = getattr(config, "MATCH_RESULTS_CHANNEL_ID", None)

    # 1. Поиск по target_id в текущей гильдии
    if target_id and guild:
        ch = guild.get_channel(target_id)
        if not ch:
            try:
                ch = await guild.fetch_channel(target_id)
            except Exception:
                ch = None
        if ch and isinstance(ch, (discord.TextChannel, discord.Thread)):
            return ch

    # 2. Поиск по target_id через client
    if target_id and client:
        ch = client.get_channel(target_id)
        if not ch:
            try:
                ch = await client.fetch_channel(target_id)
            except Exception:
                ch = None
        if ch and isinstance(ch, (discord.TextChannel, discord.Thread)):
            if not guild or (hasattr(ch, "guild") and ch.guild and ch.guild.id == guild.id):
                return ch

    # 3. Автоматический поиск текстового канала по имени на сервере
    if guild:
        conf_name = getattr(config, "MATCH_RESULTS_CHANNEL_NAME", "1v1s-elos").lower()
        for ch in guild.text_channels:
            name_lower = ch.name.lower()
            if (
                name_lower == conf_name
                or "1v1s-elo" in name_lower
                or "1v1-elo" in name_lower
                or "1v1s_elo" in name_lower
                or "match-results" in name_lower
                or "результаты" in name_lower
            ):
                return ch

    return None


_CALL_REF_COOLDOWNS: Dict[int, float] = {}


class CallRefButton(discord.ui.Button):
    def __init__(self, challenger_id: Optional[int] = None, challenged_id: Optional[int] = None, lang: str = "ru"):
        super().__init__(
            label=locales.t("challenge_call_ref_btn", lang),
            style=discord.ButtonStyle.primary,
            emoji="📢",
            custom_id="btn_call_ref"
        )
        self.challenger_id = challenger_id
        self.challenged_id = challenged_id
        self.lang = lang

    async def callback(self, interaction: discord.Interaction):
        p1 = self.challenger_id
        p2 = self.challenged_id

        # При перезапуске бота восстанавливаем участников из текста сообщения ветки
        if (not p1 or not p2) and interaction.message:
            raw_text = (interaction.message.content or "")
            if interaction.message.embeds:
                raw_text += " " + (interaction.message.embeds[0].description or "")
            found = re.findall(r"<@!?(\d+)>", raw_text)
            if len(found) >= 2:
                p1, p2 = int(found[0]), int(found[1])

        if p1 and p2:
            if interaction.user.id not in (p1, p2) and not is_resp_or_admin(interaction):
                await interaction.response.send_message(
                    "🚫 **Доступ ограничен**\nТолько участники этой дуэли или администрация могут вызывать судейскую коллегию (Респов)!",
                    ephemeral=True
                )
                return

        # Защита от спама пингами Респонсиблов (кулдаун 90 секунд на ветку/канал)
        target_key = interaction.channel_id or (interaction.message.id if interaction.message else interaction.user.id)
        now = time.time()
        last_call = _CALL_REF_COOLDOWNS.get(target_key, 0.0)
        if now - last_call < 90.0:
            rem = int(90.0 - (now - last_call))
            wait_msg = (
                f"⏳ **Респонсиблы уже оповещены в эту ветку!**\nПовторный вызов будет доступен через `{rem}` сек."
                if self.lang == "ru"
                else f"⏳ **Referees have already been alerted!**\nYou can call referee again in `{rem}` sec."
            )
            await interaction.response.send_message(wait_msg, ephemeral=True)
            return

        _CALL_REF_COOLDOWNS[target_key] = now

        resp_role = get_resp_role(interaction.guild)
        role_mention = resp_role.mention if resp_role else "@1v1s Responsible"

        embed = discord.Embed(
            title=locales.t("challenge_ref_called_title", self.lang),
            description=locales.t(
                "challenge_ref_called_desc",
                self.lang,
                user=interaction.user.mention,
                role=role_mention
            ),
            color=discord.Color.orange()
        )
        embed.set_footer(text="GANGHUB League • Call Referee" if self.lang == "en" else "GANGHUB League • Вызов судьи")
        await interaction.response.send_message(content=role_mention, embed=embed)


class VipCrasherModal(discord.ui.Modal):
    def __init__(self, challenger_id: Optional[int], challenged_id: Optional[int], vip_info: str, lang: str = "ru"):
        title = "🚨 Помеха / Крашер на VIP" if lang == "ru" else "🚨 VIP Crasher Report"
        super().__init__(title=title[:45])
        self.challenger_id = challenger_id
        self.challenged_id = challenged_id
        self.vip_info = vip_info
        self.lang = lang

        self.crasher_name = discord.ui.TextInput(
            label="Никнейм нарушителя в Roblox" if lang == "ru" else "Roblox Nickname of the Crasher",
            placeholder="например: Player123" if lang == "ru" else "e.g. Player123",
            required=True,
            max_length=50
        )
        self.add_item(self.crasher_name)

        self.reason = discord.ui.TextInput(
            label="Описание помехи" if lang == "ru" else "Interference Details",
            placeholder="Мешает драться, срывает Bo3 сет, спамит атаками..." if lang == "ru" else "Griefing, hitting players, disrupting duel...",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=300
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        resp_role = get_resp_role(interaction.guild)
        role_mention = resp_role.mention if resp_role else "@1v1s Responsible"

        violator = self.crasher_name.value.strip()
        details = self.reason.value.strip() or ("Не указано" if self.lang == "ru" else "Not specified")
        vip_text = self.vip_info or ("Уточняется в ветке матча" if self.lang == "ru" else "Specified in match thread")

        if self.lang == "en":
            desc = (
                f"### 🚨 URGENT: VIP INTERFERENCE / CRASHER REPORT!\n"
                f"**Reported by:** {interaction.user.mention}\n"
                f"• **Roblox Violator:** `{violator}`\n"
                f"• **Details:** {details}\n"
                f"• **VIP Server:** {vip_text}\n\n"
                f"⚠️ **Action for Referees:** {role_mention} — join the server immediately and remove the crasher!"
            )
            title = "🚨 Official Referee Alert • VIP Crasher"
            footer = "GANGHUB Anti-Interference System"
        else:
            desc = (
                f"### 🚨 ВНИМАНИЕ РЕСПАМ: ПОМЕХА / КРАШЕР НА VIP!\n"
                f"**Пожаловался:** {interaction.user.mention}\n"
                f"• **Нарушитель в Roblox:** `{violator}`\n"
                f"• **Суть помехи:** {details}\n"
                f"• **Сервер дуэли:** {vip_text}\n\n"
                f"⚠️ **Респонсиблы {role_mention}:** срочно зайдите на VIP-сервер и удалите нарушителя!"
            )
            title = "🚨 Экстренный вызов судей • Крашер на VIP"
            footer = "GANGHUB League • Защита от помех"

        embed = discord.Embed(title=title, description=desc, color=discord.Color.red())
        embed.set_footer(text=footer)
        await interaction.response.send_message(content=f"{role_mention} {interaction.user.mention}", embed=embed)


class VipCrasherButton(discord.ui.Button):
    def __init__(self, challenger_id: Optional[int] = None, challenged_id: Optional[int] = None, vip_info: str = "", lang: str = "ru"):
        super().__init__(
            label="Помеха на VIP" if lang == "ru" else "VIP Crasher",
            style=discord.ButtonStyle.danger,
            emoji="🚨",
            custom_id="btn_vip_crasher"
        )
        self.challenger_id = challenger_id
        self.challenged_id = challenged_id
        self.vip_info = vip_info
        self.lang = lang

    async def callback(self, interaction: discord.Interaction):
        p1 = self.challenger_id
        p2 = self.challenged_id
        if (not p1 or not p2) and interaction.message:
            raw_text = (interaction.message.content or "")
            if interaction.message.embeds:
                raw_text += " " + (interaction.message.embeds[0].description or "")
            found = re.findall(r"<@!?(\d+)>", raw_text)
            if len(found) >= 2:
                p1, p2 = int(found[0]), int(found[1])

        if p1 and p2 and interaction.user.id not in (p1, p2) and not is_resp_or_admin(interaction):
            msg = "🚫 **Доступ ограничен**\nТолько участники этой дуэли могут отправлять экстренный репорт о помехе!" if self.lang == "ru" else "🚫 **Access Denied**\nOnly duel participants can report interference!"
            await interaction.response.send_message(msg, ephemeral=True)
            return

        modal = VipCrasherModal(p1, p2, self.vip_info, self.lang)
        await interaction.response.send_modal(modal)


class QuickReportChoiceView(discord.ui.View):
    def __init__(self, cog: Any, p1: discord.Member, p2: discord.Member, lang: str):
        super().__init__(timeout=60.0)
        self.cog = cog
        self.p1 = p1
        self.p2 = p2
        self.lang = lang

        btn_p1 = discord.ui.Button(
            label=f"Победил {p1.display_name[:14]}",
            style=discord.ButtonStyle.success,
            emoji="🏆"
        )
        btn_p1.callback = self._make_cb(winner=p1, loser=p2)
        self.add_item(btn_p1)

        btn_p2 = discord.ui.Button(
            label=f"Победил {p2.display_name[:14]}",
            style=discord.ButtonStyle.success,
            emoji="🏆"
        )
        btn_p2.callback = self._make_cb(winner=p2, loser=p1)
        self.add_item(btn_p2)

        btn_cancel = discord.ui.Button(
            label="Отмена" if lang == "ru" else "Cancel",
            style=discord.ButtonStyle.secondary,
            emoji="✖️"
        )
        async def on_cancel(interaction: discord.Interaction):
            await interaction.response.edit_message(content="❌ Внесение результата отменено." if lang == "ru" else "❌ Result reporting cancelled.", view=None)
        btn_cancel.callback = on_cancel
        self.add_item(btn_cancel)

    def _make_cb(self, winner: discord.Member, loser: discord.Member):
        async def cb(interaction: discord.Interaction):
            confirm_txt = f"⏳ Запись победы **{winner.display_name}**..." if self.lang == "ru" else f"⏳ Recording victory for **{winner.display_name}**..."
            await interaction.response.edit_message(content=confirm_txt, view=None)
            await self.cog._execute_report(
                interaction,
                winner=winner,
                loser=loser,
                proof=None,
                winner_build=None,
                loser_build=None
            )
        return cb


class QuickReportButton(discord.ui.Button):
    def __init__(self, challenger_id: Optional[int] = None, challenged_id: Optional[int] = None, lang: str = "ru"):
        super().__init__(
            label="Зафиксировать победу" if lang == "ru" else "Record Victory",
            style=discord.ButtonStyle.success,
            emoji="🏆",
            custom_id="btn_quick_report"
        )
        self.challenger_id = challenger_id
        self.challenged_id = challenged_id
        self.lang = lang

    async def callback(self, interaction: discord.Interaction):
        if not is_resp_or_admin(interaction):
            msg = (
                "🚫 **Доступ ограничен**\nФиксировать победу в дуэли могут только Респонсиблы (@1v1s Responsible) или Администраторы!"
                if self.lang == "ru"
                else "🚫 **Access Denied**\nOnly Referees (@1v1s Responsible) or Administrators can record duel results!"
            )
            await interaction.response.send_message(msg, ephemeral=True)
            return

        p1_id = self.challenger_id
        p2_id = self.challenged_id

        # 1. Поиск участников через SQLite по channel_id (ветке) или message_id
        cog = interaction.client.get_cog("MatchesCog")
        if (not p1_id or not p2_id) and cog and cog.db:
            ch_data = await asyncio.to_thread(cog.db.get_challenge_by_channel, interaction.channel_id)
            if not ch_data and interaction.message:
                ch_data = await asyncio.to_thread(cog.db.get_challenge_by_message, interaction.message.id)
            if ch_data:
                p1_id = ch_data.get("challenger_id")
                p2_id = ch_data.get("challenged_id")

        # 2. Фолбэк на mentions в сообщении
        if (not p1_id or not p2_id) and interaction.message:
            raw_text = (interaction.message.content or "")
            if interaction.message.embeds:
                raw_text += " " + (interaction.message.embeds[0].description or "")
            found = re.findall(r"<@!?(\d+)>", raw_text)
            if len(found) >= 2:
                p1_id, p2_id = int(found[0]), int(found[1])

        guild = interaction.guild
        if not guild or not p1_id or not p2_id:
            await interaction.response.send_message("❌ Не удалось определить участников матча.", ephemeral=True)
            return

        # Защита от конфликта интересов: бойцы НЕ могут судить свой собственный матч!
        if interaction.user.id in (p1_id, p2_id):
            msg = (
                "🚫 **Конфликт интересов**\nУчастники дуэли не могут сами подтверждать свою победу! Дождитесь решения Респонсибла (@1v1s Responsible) или вызовите судью кнопкой «📢 Вызов судьи»."
                if self.lang == "ru"
                else "🚫 **Conflict of Interest**\nDuel participants cannot judge their own match! Please wait for a Referee (@1v1s Responsible) or click «📢 Call Referee»."
            )
            await interaction.response.send_message(msg, ephemeral=True)
            return

        try:
            m1 = guild.get_member(p1_id) or await guild.fetch_member(p1_id)
            m2 = guild.get_member(p2_id) or await guild.fetch_member(p2_id)
        except Exception:
            m1, m2 = None, None

        if not m1 or not m2:
            await interaction.response.send_message("❌ Один из игроков дуэли не найден на сервере.", ephemeral=True)
            return

        if not cog:
            await interaction.response.send_message("❌ Ошибка: модуль матчей не загружен.", ephemeral=True)
            return

        view = QuickReportChoiceView(cog, m1, m2, self.lang)
        prompt_txt = (
            f"🏆 **Быстрое судейство дуэли**\n"
            f"⚠️ *Убедитесь, что победитель предоставил полный откат всех раундов (не клипы трупов)!*\n\n"
            f"Кто победил в бою между **{m1.display_name}** и **{m2.display_name}**?"
            if self.lang == "ru"
            else (
                f"🏆 **Quick Match Reporting**\n"
                f"⚠️ *Make sure the winner provided full video recordings of all rounds (no corpse clips)!*\n\n"
                f"Who won the duel between **{m1.display_name}** and **{m2.display_name}**?"
            )
        )
        await interaction.response.send_message(prompt_txt, view=view, ephemeral=True)


class CallRefView(discord.ui.View):
    def __init__(
        self,
        challenger_id: Optional[int] = None,
        challenged_id: Optional[int] = None,
        lang: str = "ru",
        vip_info: str = ""
    ):
        super().__init__(timeout=None)
        self.add_item(CallRefButton(challenger_id, challenged_id, lang))
        self.add_item(VipCrasherButton(challenger_id, challenged_id, vip_info, lang))
        self.add_item(QuickReportButton(challenger_id, challenged_id, lang))


class ChallengeView(discord.ui.View):
    def __init__(
        self,
        bot: Optional[commands.Bot] = None,
        db: Optional[Database] = None,
        challenger: Optional[discord.Member] = None,
        challenged: Optional[discord.Member] = None,
        lang: str = "ru",
        match_format: str = "T2 - Main vs Main",
        match_server: str = "Hesse (Германия)",
        challenge_id: Optional[int] = None
    ):
        super().__init__(timeout=None)
        self.bot = bot
        self.db = db
        self.challenger = challenger
        self.challenged = challenged
        self.lang = lang
        self.match_format = match_format
        self.match_server = match_server
        self.challenge_id = challenge_id
        self.message: Optional[discord.Message] = None

        # Устанавливаем локализованные лейблы кнопок
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                if item.custom_id == "challenge_btn_accept":
                    item.label = locales.t("challenge_accept_btn", lang)
                elif item.custom_id == "challenge_btn_decline":
                    item.label = locales.t("challenge_decline_btn", lang)
                elif item.custom_id == "challenge_btn_cancel":
                    item.label = locales.t("challenge_cancel_btn", lang)

    async def _resolve_challenge(self, interaction: discord.Interaction) -> Optional[Dict[str, Any]]:
        """
        Многоуровневый отказоустойчивый поиск вызова с авто-восстановлением:
        1. Поиск по message.id
        2. Поиск по self.challenge_id (если сохранен на View)
        3. Поиск по channel_id / thread_id (с приоритетом активных pending)
        4. Поиск по parent_id ветки (для форум-каналов)
        5. Поиск по участникам (self.challenger / self.challenged или парсинг меншенов из сообщения/эмбеда)
        6. Авто-восстановление: если запись в БД отсутствует (сбой SQLite при создании, очистка базы),
           но в Discord есть валидное сообщение вызова — автоматически создает запись в SQLite
           и привязывает ее, предотвращая ошибку «Данные устарели»!
        """
        if not self.db:
            return None

        msg = interaction.message
        ch = None

        # 1. Поиск по ID сообщения
        if msg:
            ch = await asyncio.to_thread(self.db.get_challenge_by_message, msg.id)
            if ch:
                return ch

        # 2. Поиск по ID вызова из View
        if self.challenge_id:
            ch = await asyncio.to_thread(self.db.get_challenge, self.challenge_id)
            if ch:
                if msg and ch.get("message_id") != msg.id:
                    await asyncio.to_thread(self.db.link_challenge_message, ch["id"], msg.id)
                    ch["message_id"] = msg.id
                return ch

        # 3. Поиск по ID канала или ветки (с приоритетом pending)
        if interaction.channel_id:
            ch = await asyncio.to_thread(self.db.get_challenge_by_channel, interaction.channel_id)
            if ch:
                if msg and ch.get("message_id") != msg.id:
                    await asyncio.to_thread(self.db.link_challenge_message, ch["id"], msg.id)
                    ch["message_id"] = msg.id
                return ch

        # 4. Если это ветка форума — проверяем родительский канал (parent_id)
        if interaction.channel and hasattr(interaction.channel, "parent_id") and interaction.channel.parent_id:
            ch = await asyncio.to_thread(self.db.get_challenge_by_channel, interaction.channel.parent_id)
            if ch:
                if msg and ch.get("message_id") != msg.id:
                    await asyncio.to_thread(self.db.link_challenge_message, ch["id"], msg.id, interaction.channel_id)
                    ch["message_id"] = msg.id
                    ch["channel_id"] = interaction.channel_id
                return ch

        # 5. Поиск по участникам дуэли
        p1_id = self.challenger.id if self.challenger else None
        p2_id = self.challenged.id if self.challenged else None

        # Если на View участники не сохранены (перезапуск бота), парсим их из сообщения/эмбеда
        if (not p1_id or not p2_id) and msg:
            raw_text = msg.content or ""
            if msg.embeds:
                for emb in msg.embeds:
                    raw_text += " " + (emb.title or "") + " " + (emb.description or "")
            found = re.findall(r"<@!?(\d+)>", raw_text)
            if len(found) >= 2:
                p1_id, p2_id = int(found[0]), int(found[1])

        if p1_id and p2_id:
            ch = await asyncio.to_thread(self.db.get_pending_challenge, p1_id, p2_id)
            if not ch:
                ch = await asyncio.to_thread(self.db.get_pending_challenge, p2_id, p1_id)
            if not ch:
                ch = await asyncio.to_thread(self.db.get_latest_challenge_for_players, p1_id, p2_id)

            if ch:
                if msg:
                    await asyncio.to_thread(self.db.link_challenge_message, ch["id"], msg.id, interaction.channel_id)
                    ch["message_id"] = msg.id
                    ch["channel_id"] = interaction.channel_id
                return ch

            # 6. Авто-восстановление: сообщение вызова реально существует в Discord, но в базе запись отсутствует
            if msg and msg.embeds:
                desc = msg.embeds[0].description or ""
                # Проверяем ключевые маркеры официального эмбеда дуэли Лиги
                if any(w in desc for w in ("ДУЭЛЬ 1v1", "DUEL CHALLENGE", "1v1")) and any(w in desc for w in ("Параметры дуэли", "Duel Settings")):
                    fmt_match = re.search(r"(?:Формат|Format):\s*[*`_]*([^\n*`_]+)", desc)
                    srv_match = re.search(r"(?:Сервер|Server):\s*[*`_]*([^\n*`_]+)", desc)
                    dead_match = re.search(r"<t:(\d+):[RrtTdD]>", desc)
                    init_match = re.search(r"(?:Инициатор|Initiator):[^\d<]*<@!?(\d+)>", desc)
                    opp_match = re.search(r"(?:Соперник|Opponent):[^\d<]*<@!?(\d+)>", desc)

                    challenger_id = int(init_match.group(1)) if init_match else p1_id
                    challenged_id = int(opp_match.group(1)) if opp_match else p2_id

                    parsed_fmt = fmt_match.group(1).strip() if fmt_match else self.match_format
                    parsed_srv = srv_match.group(1).strip() if srv_match else self.match_server

                    expires_dt = None
                    if dead_match:
                        try:
                            expires_dt = datetime.fromtimestamp(int(dead_match.group(1)), tz=timezone.utc)
                        except Exception:
                            expires_dt = None
                    if not expires_dt:
                        expires_dt = datetime.now(timezone.utc) + timedelta(hours=24)

                    log.warning(f"🛠️ [Авто-восстановление] Восстановление вызова: {challenger_id} -> {challenged_id} (msg: {msg.id})")
                    try:
                        new_cid = await asyncio.to_thread(
                            self.db.create_challenge,
                            guild_id=interaction.guild_id or 0,
                            channel_id=interaction.channel_id or 0,
                            message_id=msg.id,
                            challenger_id=challenger_id,
                            challenged_id=challenged_id,
                            format=parsed_fmt,
                            server=parsed_srv,
                            expires_at=expires_dt
                        )
                        self.challenge_id = new_cid
                        return await asyncio.to_thread(self.db.get_challenge, new_cid)
                    except Exception as ex:
                        log.error(f"❌ Ошибка авто-восстановления вызова: {ex}")

        return None

    @discord.ui.button(style=discord.ButtonStyle.green, emoji="⚔️", custom_id="challenge_btn_accept")
    async def btn_accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.db or not interaction.message:
            await interaction.response.send_message("❌ Invalid challenge context." if self.lang == "en" else "❌ Ошибка контекста вызова.", ephemeral=True)
            return

        # 1. Быстро получаем данные вызова с многоуровневым поиском и авто-восстановлением
        ch = await self._resolve_challenge(interaction)
        if not ch:
            await interaction.response.send_message("❌ Challenge data is outdated or not found." if self.lang == "en" else "❌ Данные этого вызова устарели или не найдены в базе.", ephemeral=True)
            return

        # 2. МГНОВЕННАЯ проверка авторизации: только вызванный игрок может нажать (отсекает чужих за 5 мс)
        if interaction.user.id != ch["challenged_id"]:
            if self.lang == "en":
                auth_msg = f"🚫 **Access Denied**\nYou are not a participant in this duel. The «Accept Challenge» button is only for <@{ch['challenged_id']}>."
            else:
                auth_msg = f"🚫 **Доступ ограничен**\nВы не являетесь участником этой дуэли. Кнопка «Принять вызов» доступна только для <@{ch['challenged_id']}>."
            await interaction.response.send_message(auth_msg, ephemeral=True)
            return

        # 3. Проверка статуса (защита от повторных нажатий)
        if ch.get("status") != "pending":
            await interaction.response.send_message("⚠️ This challenge has already ended (accepted, declined or expired)!" if self.lang == "en" else "⚠️ Этот вызов уже завершен (принят, отклонен или истек)!", ephemeral=True)
            return

        # 4. Мгновенно подтверждаем получение взаимодействия для Discord (исключает "Сбой взаимодействия")
        await interaction.response.defer()

        # Проверяем привязку Roblox у принимающего игрока
        challenged_user_data = await asyncio.to_thread(self.db.get_or_create_user, interaction.user.id)
        if not challenged_user_data.get("roblox_username"):
            api_key = bloxlink.get_bloxlink_key(self.db)
            if api_key and interaction.guild_id:
                try:
                    res = await asyncio.to_thread(bloxlink.resolve_discord_to_roblox, interaction.guild_id, interaction.user.id, api_key)
                    if res:
                        _, auto_name = res
                        challenged_user_data = await asyncio.to_thread(self.db.link_roblox, interaction.user.id, auto_name)
                except Exception:
                    pass

        if not challenged_user_data.get("roblox_username"):
            view = discord.ui.View()
            btn_lbl = "Verify on blox.link" if self.lang == "en" else "Пройти верификацию на blox.link"
            view.add_item(discord.ui.Button(label=btn_lbl, url="https://blox.link/verify", style=discord.ButtonStyle.link, emoji="🔗"))
            msg = (
                "⚠️ **Требуется привязка Roblox!**\n"
                "Вы не можете принять вызов на дуэль, пока не подтвердите свой аккаунт Roblox.\n"
                "Привяжите аккаунт через команду `/link` и затем нажмите кнопку снова."
                if self.lang != "en"
                else (
                    "⚠️ **Roblox Verification Required!**\n"
                    "You cannot accept a duel until your Roblox account is verified.\n"
                    "Link your account via `/link` and click the button again."
                )
            )
            await interaction.followup.send(msg, view=view, ephemeral=True)
            return

        # 5. Атомарно переводим статус в accepted
        await asyncio.to_thread(self.db.update_challenge_status, ch["id"], "accepted")

        # 6. Отключаем кнопки на исходном сообщении через независимый View (НЕ мутируем singleton!)
        disabled_view = discord.ui.View()
        disabled_view.add_item(discord.ui.Button(
            label=locales.t("challenge_accept_btn", self.lang),
            style=discord.ButtonStyle.success,
            disabled=True,
            emoji="✅"
        ))
        try:
            if interaction.message and interaction.message.embeds:
                orig_emb = interaction.message.embeds[0]
                emb_dict = orig_emb.to_dict()
                emb_dict["color"] = discord.Color.green().value
                emb_dict["title"] = "✅ Challenge Accepted • Match Starting!" if self.lang == "en" else "✅ Вызов принят • Матч начинается!"
                emb_dict["footer"] = {"text": "GANGHUB League • Status: Accepted" if self.lang == "en" else "GANGHUB League • Статус: Принят"}
                await interaction.message.edit(embed=discord.Embed.from_dict(emb_dict), view=disabled_view)
            else:
                await interaction.message.edit(view=disabled_view)
        except Exception:
            pass

        # 7. Разрешаем участников дуэли
        guild = interaction.guild
        challenged_member = interaction.user
        challenger_member = self.challenger
        if not challenger_member and guild:
            challenger_member = guild.get_member(ch["challenger_id"])
            if not challenger_member:
                try:
                    challenger_member = await guild.fetch_member(ch["challenger_id"])
                except Exception:
                    challenger_member = None

        if not challenger_member:
            await interaction.followup.send("⚠️ Challenge initiator was not found on the server (they may have left)." if self.lang == "en" else "⚠️ Инициатор вызова не найден на сервере (возможно, покинул сервер).")
            return

        # 8. Проверка лимитов матчей (защита от перелива)
        can_play, reason = await asyncio.to_thread(self.db.can_play_match, challenger_member.id, challenged_member.id)
        if not can_play:
            if self.lang == "en":
                reason = "Limit reached: these players have already played the maximum daily matches in the last 24 hours."
            await interaction.followup.send(f"🚫 {reason}")
            return

        # 9. Формируем подробные данные для карточки матча
        p1_data = await asyncio.to_thread(self.db.get_or_create_user, challenger_member.id)
        p2_data = await asyncio.to_thread(self.db.get_or_create_user, challenged_member.id)
        p1_pos = await asyncio.to_thread(self.db.get_user_rank_position, challenger_member.id)
        p2_pos = await asyncio.to_thread(self.db.get_user_rank_position, challenged_member.id)

        p1_rank = get_rank_info(p1_data["rating"], p1_data["rd"], p1_data["wins"] + p1_data["losses"], p1_pos, lang=self.lang)
        p2_rank = get_rank_info(p2_data["rating"], p2_data["rd"], p2_data["wins"] + p2_data["losses"], p2_pos, lang=self.lang)

        p1_rbx = p1_data.get("roblox_username") or ("not linked" if self.lang == "en" else "не привязан")
        p2_rbx = p2_data.get("roblox_username") or ("not linked" if self.lang == "en" else "не привязан")

        # 9. Проверяем и динамически бронируем VIP-сервер под дуэль
        p1_vip = await asyncio.to_thread(self.db.get_user_vip, challenger_member.id)
        p2_vip = await asyncio.to_thread(self.db.get_user_vip, challenged_member.id)

        assigned_slot, assigned_url = await asyncio.to_thread(self.db.get_available_league_vip)
        if assigned_slot:
            await asyncio.to_thread(
                self.db.reserve_league_vip,
                assigned_slot,
                ch["id"],
                interaction.channel_id,
                challenger_member.id,
                challenged_member.id
            )

        resp_role = get_resp_role(guild)
        resp_mention = resp_role.mention if resp_role else "@1v1s Responsible"

        join_vip_label = "Join server" if self.lang == "en" else "Войти на сервер"
        vip_lines = []
        vip_info_summary = ""

        if assigned_slot and assigned_url:
            vip_info_summary = f"VIP {assigned_slot}: {assigned_url}"
        elif p1_vip:
            vip_info_summary = f"VIP {challenger_member.display_name}: {p1_vip}"
        elif p2_vip:
            vip_info_summary = f"VIP {challenged_member.display_name}: {p2_vip}"

        # Кнопки для ветки матча (Вызов судьи + Репорт о крашере/помехе + VIP серверы)
        btn_view = CallRefView(challenger_member.id, challenged_member.id, self.lang, vip_info=vip_info_summary)

        # 1. Если выделена свободная официальная випка Лиги
        if assigned_slot and assigned_url:
            if self.lang == "en":
                vip_lines.append(f"• 🟢 **Assigned League VIP:** **VIP {assigned_slot}** ➔ [{join_vip_label}]({assigned_url})")
                vip_lines.append("  *(Reserved exclusively for this duel until match report)*")
            else:
                vip_lines.append(f"• 🟢 **Назначенный VIP Лиги:** **VIP {assigned_slot}** ➔ [{join_vip_label}]({assigned_url})")
                vip_lines.append("  *(Забронирован специально под вашу дуэль до завершения матча)*")
            btn_view.add_item(discord.ui.Button(label=f"VIP {assigned_slot} (Играть)", url=assigned_url, style=discord.ButtonStyle.link, emoji="🌐"))

        # 2. Если все официальные випки Лиги сейчас заняты
        elif not p1_vip and not p2_vip:
            league_vips = await asyncio.to_thread(self.db.get_league_vips)
            if league_vips:
                if self.lang == "en":
                    vip_lines.append("• ⚠️ **All official League VIP servers are currently occupied by ongoing duels!**")
                    vip_lines.append("  *(Please wait for duels to finish, or use a personal VIP with `/vip set`)*")
                else:
                    vip_lines.append("• ⚠️ **Все официальные VIP-серверы Лиги сейчас заняты активными матчами!**")
                    vip_lines.append("  *(Подождите освобождения сервера или укажите свой VIP через `/vip set`)*")
                for s, u in league_vips.items():
                    btn_view.add_item(discord.ui.Button(label=f"VIP {s} (Занят)", url=u, style=discord.ButtonStyle.link, emoji="🔴"))
            else:
                empty_vip_notice = "*(Personal VIP servers are not linked. Set with `/vip set`)*" if self.lang == "en" else "*(Личные VIP-серверы не привязаны. Назначить можно через `/vip set`)*"
                vip_lines.append(empty_vip_notice)

        # 3. Персональные випки игроков
        if p1_vip:
            vip_lines.append(f"• **VIP {challenger_member.display_name}:** [{join_vip_label}]({p1_vip})")
            btn_view.add_item(discord.ui.Button(label=f"VIP: {challenger_member.display_name[:12]}", url=p1_vip, style=discord.ButtonStyle.link, emoji="🔗"))
        if p2_vip:
            vip_lines.append(f"• **VIP {challenged_member.display_name}:** [{join_vip_label}]({p2_vip})")
            btn_view.add_item(discord.ui.Button(label=f"VIP: {challenged_member.display_name[:12]}", url=p2_vip, style=discord.ButtonStyle.link, emoji="🔗"))

        vip_text = "\n".join(vip_lines)

        chosen_format_name = locales.clean_format_name(ch.get('format', self.match_format), self.lang)
        chosen_server_name = locales.clean_server_name(ch.get('server', self.match_server), self.lang)

        if self.lang == "en":
            match_desc = (
                f"### ⚔️ GANGHUB 1v1 LEAGUE • MATCH SCHEDULED\n\n"
                f"🔴 **Initiator:** {challenger_member.mention} (`{p1_rbx}`)\n"
                f"╰ **Rank:** {p1_rank['badge']} **{p1_rank['tier']}** • `{p1_rank['display']} ELO`\n\n"
                f"🔵 **Opponent:** {challenged_member.mention} (`{p2_rbx}`)\n"
                f"╰ **Rank:** {p2_rank['badge']} **{p2_rank['tier']}** • `{p2_rank['display']} ELO`\n\n"
                f"⚙️ **Duel Settings:**\n"
                f"• Format: **`{chosen_format_name}`**\n"
                f"• Server: **`{chosen_server_name}`**\n\n"
                f"⚖️ **Referee & Monitoring:**\n"
                f"Referees: {resp_mention} — you are assigned to monitor this duel!\n\n"
                f"🕹️ **VIP Servers:**\n{vip_text}\n\n"
                f"📹 **Proof Policy (Anti-Win Trading):**\n"
                f"• Full video recording of **ALL rounds** is strictly required (Medal/YouTube)!\n"
                f"• 15-30s corpse clips and screenshots **will NOT be accepted**!\n\n"
                f"📖 *Full 1v1 league rules and penalty guidelines: `/rules`*"
            )
            match_footer_text = "GANGHUB 1v1 • Click button below to call referee"
        else:
            match_desc = (
                f"### ⚔️ GANGHUB 1v1 LEAGUE • МАТЧ НАЗНАЧЕН\n\n"
                f"🔴 **Инициатор:** {challenger_member.mention} (`{p1_rbx}`)\n"
                f"╰ **Ранг:** {p1_rank['badge']} **{p1_rank['tier']}** • `{p1_rank['display']} ELO`\n\n"
                f"🔵 **Противник:** {challenged_member.mention} (`{p2_rbx}`)\n"
                f"╰ **Ранг:** {p2_rank['badge']} **{p2_rank['tier']}** • `{p2_rank['display']} ELO`\n\n"
                f"⚙️ **Параметры дуэли:**\n"
                f"• Формат: **`{chosen_format_name}`**\n"
                f"• Сервер: **`{chosen_server_name}`**\n\n"
                f"⚖️ **Судейство и Мониторинг:**\n"
                f"Судьи: {resp_mention} — вы назначены на мониторинг этой дуэли!\n\n"
                f"🕹️ **VIP-серверы:**\n{vip_text}\n\n"
                f"📹 **Правило пруфов (Анти-перелив):**\n"
                f"• Для победы **ОБЯЗАТЕЛЕН полный откат всех раундов боя** (Medal/YouTube/файл)!\n"
                f"• Обрезанные клипы трупов и скриншоты **НЕ принимаются**!\n\n"
                f"📖 *Полный регламент 1v1 лиги и правила нарушений: `/rules`*"
            )
            match_footer_text = "GANGHUB 1v1 • Нажмите кнопку ниже для вызова судьи"

        match_embed = discord.Embed(
            title=locales.t("challenge_match_title", self.lang),
            description=match_desc,
            color=discord.Color.gold()
        )
        match_embed.set_footer(text=match_footer_text)

        # 10. Создаем регламентную ветку для дуэли
        thread = None
        try:
            if hasattr(interaction.channel, "create_thread"):
                p1_country = await asyncio.to_thread(self.db.get_user_country, challenger_member.id)
                p2_country = await asyncio.to_thread(self.db.get_user_country, challenged_member.id)
                c_flag = config.get_country_flag(p1_country)
                d_flag = config.get_country_flag(p2_country)
                t_name = f"⚔️・{c_flag}{challenger_member.display_name[:10]} vs {d_flag}{challenged_member.display_name[:10]}"[:100]
                target_msg = self.message or interaction.message
                if target_msg:
                    thread = await target_msg.create_thread(name=t_name, auto_archive_duration=1440)
                else:
                    thread = await interaction.channel.create_thread(name=t_name, auto_archive_duration=1440)
        except Exception:
            thread = None

        if thread:
            try:
                await interaction.followup.send(locales.t("challenge_thread_created", self.lang, thread=thread.mention))
            except Exception:
                pass
            await thread.send(
                content=f"{challenger_member.mention} {challenged_member.mention} {resp_mention}",
                embed=match_embed,
                view=btn_view
            )
        else:
            try:
                await interaction.channel.send(
                    content=f"{challenger_member.mention} {challenged_member.mention} {resp_mention}",
                    embed=match_embed,
                    view=btn_view
                )
            except discord.Forbidden:
                await interaction.followup.send(
                    content=f"{challenger_member.mention} {challenged_member.mention} {resp_mention}",
                    embed=match_embed,
                    view=btn_view
                )

        # 11. Оповещение инициатора вызова в ЛС
        try:
            cr_lang = locales.get_user_lang(self.db, challenger_member.id, fallback=self.lang)
            jump_link = thread.jump_url if thread else (interaction.message.jump_url if interaction.message else "")
            dm_embed = discord.Embed(
                title=locales.t("challenge_dm_accepted_title", cr_lang),
                description=locales.t(
                    "challenge_dm_accepted_challenger",
                    cr_lang,
                    challenged=challenged_member.display_name,
                    thread_url=jump_link
                ),
                color=discord.Color.green()
            )
            dm_embed.set_footer(text=locales.t("challenge_dm_footer_ready", cr_lang))
            await challenger_member.send(embed=dm_embed)
        except Exception:
            pass

    @discord.ui.button(style=discord.ButtonStyle.red, emoji="❌", custom_id="challenge_btn_decline")
    async def btn_decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.db or not interaction.message:
            await interaction.response.send_message("❌ Invalid challenge context." if self.lang == "en" else "❌ Ошибка контекста вызова.", ephemeral=True)
            return

        ch = await self._resolve_challenge(interaction)
        if not ch:
            await interaction.response.send_message("❌ Challenge data is outdated or not found." if self.lang == "en" else "❌ Данные этого вызова устарели или не найдены в базе.", ephemeral=True)
            return

        # 1. МГНОВЕННАЯ проверка авторизации
        if interaction.user.id != ch["challenged_id"]:
            if self.lang == "en":
                auth_msg = f"🚫 **Access Denied**\nYou are not a participant in this duel. The «Decline» button is only for <@{ch['challenged_id']}>."
            else:
                auth_msg = f"🚫 **Доступ ограничен**\nВы не являетесь участником этой дуэли. Кнопка «Отклонить» доступна только для <@{ch['challenged_id']}>."
            await interaction.response.send_message(auth_msg, ephemeral=True)
            return

        if ch.get("status") != "pending":
            await interaction.response.send_message("⚠️ This challenge has already ended (accepted, declined or expired)!" if self.lang == "en" else "⚠️ Этот вызов уже завершен (принят, отклонен или истек)!", ephemeral=True)
            return

        # 2. Мгновенно подтверждаем ответ
        await interaction.response.defer()

        guild = interaction.guild
        challenged_member = interaction.user
        challenger_member = self.challenger
        if not challenger_member and guild:
            challenger_member = guild.get_member(ch["challenger_id"])
            if not challenger_member:
                try:
                    challenger_member = await guild.fetch_member(ch["challenger_id"])
                except Exception:
                    challenger_member = None

        # 3. Проверяем иммунитеты: роль Duck Evade или аккаунт инициатора < 30 дней
        is_evade = has_duck_evade(challenged_member)
        is_new_acc = False
        days_old = 999
        api_key = await asyncio.to_thread(self.db.get_setting, "bloxlink_api_key") or config.BLOXLINK_API_KEY
        if api_key and challenger_member and guild:
            try:
                r_info = await asyncio.to_thread(fetch_roblox_info_by_discord, guild.id, challenger_member.id, api_key)
                if r_info and r_info.get("is_new"):
                    is_new_acc = True
                    days_old = r_info.get("days_old", 0)
            except Exception:
                pass

        is_exempt = is_evade or is_new_acc

        # 4. Обновляем статус в БД и блокируем кнопки на исходном сообщении
        new_status = "declined_exempt" if is_exempt else "ducked"
        await asyncio.to_thread(self.db.update_challenge_status, ch["id"], new_status)

        disabled_view = discord.ui.View()
        disabled_view.add_item(discord.ui.Button(
            label=locales.t("challenge_decline_btn", self.lang),
            style=discord.ButtonStyle.danger,
            disabled=True,
            emoji="🚫"
        ))
        try:
            if interaction.message and interaction.message.embeds:
                orig_emb = interaction.message.embeds[0]
                emb_dict = orig_emb.to_dict()
                emb_dict["color"] = discord.Color.light_grey().value if is_exempt else discord.Color.red().value
                if self.lang == "en":
                    emb_dict["title"] = "⚪ Challenge Declined (Exempt)" if is_exempt else "❌ Challenge Declined • Duck Recorded"
                    emb_dict["footer"] = {"text": f"GANGHUB League • Status: {new_status}"}
                else:
                    emb_dict["title"] = "⚪ Вызов отклонён (Иммунитет)" if is_exempt else "❌ Вызов отклонён • Зафиксирован Дак"
                    emb_dict["footer"] = {"text": f"GANGHUB League • Статус: {new_status}"}
                await interaction.message.edit(embed=discord.Embed.from_dict(emb_dict), view=disabled_view)
            else:
                await interaction.message.edit(view=disabled_view)
        except Exception:
            pass

        if is_exempt:
            reason = locales.t("challenge_exempt_evade", self.lang) if is_evade else locales.t("challenge_exempt_new_acc", self.lang, days=days_old)
            embed = discord.Embed(
                title=locales.t("challenge_declined_exempt_title", self.lang),
                description=locales.t(
                    "challenge_declined_exempt_desc",
                    self.lang,
                    challenger=challenger_member.mention if challenger_member else "Инициатор",
                    challenged=challenged_member.mention,
                    reason=reason
                ),
                color=discord.Color.light_grey()
            )
            embed.set_footer(text="GANGHUB League • Exemption Confirmed" if self.lang == "en" else "GANGHUB League • Иммунитет подтвержден")
            try:
                await interaction.channel.send(embed=embed)
            except discord.Forbidden:
                await interaction.followup.send(embed=embed)

            if challenger_member:
                try:
                    if self.lang == "en":
                        dm_desc = f"❌ {challenged_member.display_name} declined the challenge, but is exempt from Duck role: {reason}."
                    else:
                        dm_desc = f"❌ {challenged_member.display_name} отклонил вызов, но освобожден от роли Duck: {reason}."
                    dm_embed = discord.Embed(
                        title=locales.t("challenge_declined_exempt_title", self.lang),
                        description=dm_desc,
                        color=discord.Color.light_grey()
                    )
                    await challenger_member.send(embed=dm_embed)
                except Exception:
                    pass
        else:
            # Применяем штраф ELO за Дак по формуле Glicko-2 против оппонента (как за проигрыш)
            penalty_val = getattr(config, "DUCK_ELO_PENALTY", 25)
            if challenger_member:
                p_res = await asyncio.to_thread(
                    self.db.apply_glicko_duck_penalty,
                    challenged_member.id,
                    challenger_member.id,
                    "Отказ от вызова (Кнопка)"
                )
            else:
                p_res = await asyncio.to_thread(
                    self.db.apply_duck_penalty,
                    challenged_member.id,
                    float(penalty_val),
                    "Отказ от вызова (Кнопка)"
                )
            old_r = p_res["old_rating"]
            new_r = p_res["rating"]
            tot = p_res["wins"] + p_res["losses"]
            p_pos = await asyncio.to_thread(self.db.get_user_rank_position, challenged_member.id) if tot > 0 else None
            p_rank = get_rank_info(new_r, p_res["rd"], tot, p_pos, lang=self.lang)
            await sync_user_roles(challenged_member, p_rank, guild)

            # Выдаем серверную роль Duck
            duck_role = get_duck_role(guild)
            if duck_role:
                try:
                    await challenged_member.add_roles(
                        duck_role,
                        reason=f"GangHub League: отказ от вызова {challenger_member.display_name if challenger_member else 'соперника'}"
                    )
                except Exception as e:
                    log.warning(f"⚠️ [Duck Role] Не удалось выдать роль {duck_role.name}: {e}")

            # Лог в канал даков (#даки)
            jump_url = interaction.message.jump_url if interaction.message else ""
            try:
                duck_ch = await get_duck_channel(guild, self.db)
                if duck_ch:
                    duck_log_embed = discord.Embed(
                        title="🦆 ФИКСАЦИЯ ДАКА (DUCK) • Отказ от вызова",
                        color=discord.Color.red(),
                        timestamp=discord.utils.utcnow()
                    )
                    duck_log_embed.description = (
                        f"• **Кто дакнул (Duck):** {challenged_member.mention} (`{challenged_member.display_name}`)\n"
                        f"• **Кому дакнул:** {challenger_member.mention if challenger_member else 'Инициатор'} (`{challenger_member.display_name if challenger_member else '—'}`)\n"
                        f"• **Штраф ELO (Glicko-2):** **-{int(round(p_res['penalty']))} ELO** (`{int(round(old_r))} ➔ {int(round(new_r))}`)\n"
                        f"• **Формат боя:** **{locales.clean_format_name(ch.get('format', self.match_format), 'ru')}**\n"
                        f"• **Сервер региона:** **{locales.clean_server_name(ch.get('server', self.match_server), 'ru')}**\n"
                        f"• **Причина:** Игрок нажал кнопку «Отклонить вызов ❌».\n"
                        f"• **Роль Duck:** Выдана автоматически ботом ✅\n"
                        f"• **Ссылка на вызов:** [Перейти к сообщению]({jump_url})"
                    )
                    duck_log_embed.set_footer(text="GangHub League • Официальный лог даков")
                    await duck_ch.send(embed=duck_log_embed)
            except Exception as e:
                log.warning(f"⚠️ Не удалось отправить лог дака в канал даков: {e}")

            embed = discord.Embed(
                title=locales.t("challenge_declined_duck_title", self.lang),
                description=locales.t(
                    "challenge_declined_duck_desc",
                    self.lang,
                    challenger=challenger_member.mention if challenger_member else "Инициатор",
                    challenged=challenged_member.mention
                ),
                color=discord.Color.red()
            )
            embed.set_footer(text="GANGHUB League • Duck Role Assigned" if self.lang == "en" else "GANGHUB League • Роль Duck выдана")
            try:
                await interaction.channel.send(embed=embed)
            except discord.Forbidden:
                await interaction.followup.send(embed=embed)

            guild_name = guild.name.strip() if guild and guild.name and guild.name.strip() else "GANGHUB"
            # Отправляем ЛС нарушителю
            if self.challenged:
                try:
                    cd_lang = locales.get_user_lang(self.db, self.challenged.id, fallback="ru")
                    dm_embed = discord.Embed(
                        title=locales.t("challenge_dm_declined_duck_recipient_title", cd_lang),
                        description=locales.t(
                            "challenge_dm_declined_duck_recipient",
                            cd_lang,
                            challenger=self.challenger.display_name if self.challenger else "Соперник",
                            guild=guild_name
                        ),
                        color=discord.Color.red()
                    )
                    dm_embed.set_footer(text=locales.t("challenge_dm_footer_declined", cd_lang))
                    await self.challenged.send(embed=dm_embed)
                except Exception:
                    pass

            # Отправляем ЛС инициатору вызова
            if self.challenger:
                try:
                    cr_lang = locales.get_user_lang(self.db, self.challenger.id, fallback="ru")
                    dm_embed = discord.Embed(
                        title=locales.t("challenge_dm_declined_duck_challenger_title", cr_lang),
                        description=locales.t(
                            "challenge_dm_declined_duck_challenger",
                            cr_lang,
                            challenged=self.challenged.display_name
                        ),
                        color=discord.Color.green()
                    )
                    dm_embed.set_footer(text=locales.t("challenge_dm_footer_refereeing", cr_lang))
                    await self.challenger.send(embed=dm_embed)
                except Exception:
                    pass

    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji="🗑️", custom_id="challenge_btn_cancel")
    async def btn_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.db or not interaction.message:
            await interaction.response.send_message("❌ Invalid challenge context." if self.lang == "en" else "❌ Ошибка контекста вызова.", ephemeral=True)
            return

        ch = await self._resolve_challenge(interaction)
        if not ch:
            await interaction.response.send_message("❌ Challenge data is outdated or not found." if self.lang == "en" else "❌ Данные этого вызова устарели или не найдены в базе.", ephemeral=True)
            return

        is_challenger = (interaction.user.id == ch["challenger_id"])
        is_admin = interaction.user.guild_permissions.administrator if (interaction.guild and hasattr(interaction.user, "guild_permissions")) else False

        if not (is_challenger or is_admin):
            msg = (
                "🚫 Only the challenger or a server administrator can cancel this duel challenge."
                if self.lang == "en"
                else "🚫 Только создатель вызова или администратор сервера может отменить его."
            )
            await interaction.response.send_message(msg, ephemeral=True)
            return

        if ch.get("status") != "pending":
            await interaction.response.send_message(
                "⚠️ This challenge has already ended or been resolved!" if self.lang == "en" else "⚠️ Этот вызов уже завершен или отменен!",
                ephemeral=True
            )
            return

        await interaction.response.defer()

        # Обновляем статус в базе данных
        await asyncio.to_thread(self.db.update_challenge_status, ch["id"], "cancelled")

        # Отключаем кнопки и обновляем эмбед
        disabled_view = discord.ui.View()
        disabled_view.add_item(discord.ui.Button(
            label="Отменен" if self.lang != "en" else "Cancelled",
            style=discord.ButtonStyle.secondary,
            disabled=True,
            emoji="🚫"
        ))

        try:
            if interaction.message and interaction.message.embeds:
                orig_emb = interaction.message.embeds[0]
                emb_dict = orig_emb.to_dict()
                emb_dict["color"] = discord.Color.dark_grey().value
                emb_dict["title"] = "🚫 Вызов отменен • Challenge Cancelled" if self.lang != "en" else "🚫 Challenge Cancelled"
                emb_dict["footer"] = {"text": "GANGHUB League • Статус: Отменен" if self.lang != "en" else "GANGHUB League • Status: Cancelled"}
                emb_dict["description"] = (orig_emb.description or "") + (
                    f"\n\n🚫 **Вызов отменен {interaction.user.mention}.**"
                    if self.lang != "en"
                    else f"\n\n🚫 **Challenge was cancelled by {interaction.user.mention}.**"
                )
                await interaction.message.edit(embed=discord.Embed.from_dict(emb_dict), view=disabled_view)
            else:
                await interaction.message.edit(view=disabled_view)
        except Exception:
            pass

        # Если это ветка форума, отправляем системное уведомление
        if isinstance(interaction.channel, discord.Thread):
            try:
                await interaction.channel.send(
                    f"🚫 {interaction.user.mention} отменил данный вызов на дуэль. Ветка закрыта."
                    if self.lang != "en"
                    else f"🚫 {interaction.user.mention} cancelled this duel challenge. Thread closed."
                )
            except Exception:
                pass


class MatchesCog(commands.Cog):
    def __init__(self, bot: commands.Bot, db: Database):
        self.bot = bot
        self.db = db
        self._lock = asyncio.Lock() # Защита от Race Condition при одновременной записи матчей
        self._challenge_cooldowns: Dict[int, float] = {} # Временные метки вызовов (user_id -> timestamp)

    async def cog_load(self):
        """Запуск фонового демона 24-часовых вызовов и регистрация persistent views"""
        self.check_expired_challenges_loop.start()
        self.bot.add_view(ChallengeView(bot=self.bot, db=self.db))
        self.bot.add_view(CallRefView())

    async def cog_unload(self):
        self.check_expired_challenges_loop.cancel()

    @tasks.loop(seconds=60)
    async def check_expired_challenges_loop(self):
        """
        Фоновый демон: мониторит 24-часовые вызовы на дуэль.
        Если соперник не ответил за 24 часа — выдает роль Duck (Авто-Дак)
        с соблюдением регламента лиги GangHub (иммунитеты Duck Evade и аккаунт <30 дней).
        """
        if not self.bot.is_ready():
            return
        try:
            expired_list = await asyncio.to_thread(self.db.get_expired_pending_challenges)
            for ch in expired_list:
                await self._process_expired_challenge(ch)
        except Exception as e:
            log.error(f"❌ [Ошибка демона авто-дака]: {e}")

    @check_expired_challenges_loop.before_loop
    async def before_check_expired_challenges(self):
        try:
            await self.bot.wait_until_ready()
        except (RuntimeError, Exception):
            pass

    async def _process_expired_challenge(self, ch: Dict[str, Any]):
        cid = ch["id"]
        guild_id = ch["guild_id"]
        channel_id = ch["channel_id"]
        message_id = ch["message_id"]
        challenger_id = ch["challenger_id"]
        challenged_id = ch["challenged_id"]

        guild = self.bot.get_guild(guild_id)
        if not guild:
            try:
                guild = await self.bot.fetch_guild(guild_id)
            except Exception:
                guild = None

        if not guild:
            await asyncio.to_thread(self.db.update_challenge_status, cid, "expired_abandoned")
            return

        challenged_member = None
        try:
            challenged_member = guild.get_member(challenged_id) or await guild.fetch_member(challenged_id)
        except Exception:
            pass

        challenger_member = None
        try:
            challenger_member = guild.get_member(challenger_id) or await guild.fetch_member(challenger_id)
        except Exception:
            pass

        lang = "ru"

        # 1. Проверяем иммунитет: роль Duck Evade
        is_evade = False
        if challenged_member and has_duck_evade(challenged_member):
            is_evade = True

        # 2. Проверяем иммунитет: возраст Roblox-аккаунта инициатора вызова < 30 дней
        is_new_acc = False
        days_old = 999
        api_key = await asyncio.to_thread(self.db.get_setting, "bloxlink_api_key") or config.BLOXLINK_API_KEY
        if api_key:
            try:
                r_info = await asyncio.to_thread(fetch_roblox_info_by_discord, guild_id, challenger_id, api_key)
                if r_info and r_info.get("is_new"):
                    is_new_acc = True
                    days_old = r_info.get("days_old", 0)
            except Exception:
                pass

        if is_evade:
            await asyncio.to_thread(self.db.update_challenge_status, cid, "expired_exempt")
            reason = locales.t("challenge_exempt_evade", lang)
            title = locales.t("challenge_auto_duck_exempt_title", lang)
            desc = locales.t(
                "challenge_auto_duck_exempt_desc",
                lang,
                challenger=f"<@{challenger_id}>",
                challenged=f"<@{challenged_id}>",
                reason=reason
            )
            embed_color = discord.Color.light_grey()
        elif is_new_acc:
            await asyncio.to_thread(self.db.update_challenge_status, cid, "expired_exempt")
            reason = locales.t("challenge_exempt_new_acc", lang, days=days_old)
            title = locales.t("challenge_auto_duck_exempt_title", lang)
            desc = locales.t(
                "challenge_auto_duck_exempt_desc",
                lang,
                challenger=f"<@{challenger_id}>",
                challenged=f"<@{challenged_id}>",
                reason=reason
            )
            embed_color = discord.Color.light_grey()
        else:
            # Авто-Дак (Duck)
            await asyncio.to_thread(self.db.update_challenge_status, cid, "ducked")

            penalty_val = getattr(config, "DUCK_ELO_PENALTY", 25)
            old_r = 1500.0
            new_r = 1500.0
            actual_penalty = penalty_val
            if challenged_member:
                if challenger_id:
                    p_res = await asyncio.to_thread(
                        self.db.apply_glicko_duck_penalty,
                        challenged_id,
                        challenger_id,
                        "24h Challenge Timeout (Auto-Duck)"
                    )
                else:
                    p_res = await asyncio.to_thread(
                        self.db.apply_duck_penalty,
                        challenged_id,
                        float(penalty_val),
                        "24h Challenge Timeout (Auto-Duck)"
                    )
                old_r = p_res["old_rating"]
                new_r = p_res["rating"]
                actual_penalty = int(round(p_res["penalty"]))
                tot = p_res["wins"] + p_res["losses"]
                p_pos = await asyncio.to_thread(self.db.get_user_rank_position, challenged_id) if tot > 0 else None
                p_rank = get_rank_info(new_r, p_res["rd"], tot, p_pos, lang=lang)
                await sync_user_roles(challenged_member, p_rank, guild)

            duck_role = get_duck_role(guild)
            if duck_role and challenged_member:
                try:
                    await challenged_member.add_roles(
                        duck_role,
                        reason=f"GangHub League: 24h challenge timeout by {challenger_id}"
                    )
                except Exception as e:
                    log.warning(f"⚠️ [Auto-Duck] Не удалось выдать роль {duck_role.name}: {e}")

            # Публикуем официальный лог в канал даков (#даки)
            try:
                duck_ch = await get_duck_channel(guild, self.db)
                if duck_ch:
                    jump_link = f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"
                    duck_log_embed = discord.Embed(
                        title="🦆 ФИКСАЦИЯ ДАКА (DUCK) • Игнорирование вызова (24ч)",
                        color=discord.Color.red(),
                        timestamp=discord.utils.utcnow()
                    )
                    duck_log_embed.description = (
                        f"• **Кто дакнул (Duck):** <@{challenged_id}>\n"
                        f"• **Кому дакнул:** <@{challenger_id}>\n"
                        f"• **Штраф ELO (Glicko-2):** **-{actual_penalty} ELO** (`{int(round(old_r))} ➔ {int(round(new_r))}`)\n"
                        f"• **Формат боя:** **{locales.clean_format_name(ch['format'], 'ru')}**\n"
                        f"• **Сервер региона:** **{locales.clean_server_name(ch['server'], 'ru')}**\n"
                        f"• **Причина:** Игрок проигнорировал вызов в течение 24 часов (Авто-Дак).\n"
                        f"• **Роль Duck:** Выдана автоматически ботом ✅\n"
                        f"• **Ссылка на вызов:** [Перейти к сообщению]({jump_link})"
                    )
                    duck_log_embed.set_footer(text="GangHub League • Официальный лог даков")
                    await duck_ch.send(embed=duck_log_embed)
            except Exception as e:
                log.warning(f"⚠️ Не удалось отправить лог авто-дака в канал даков: {e}")

            title = locales.t("challenge_auto_duck_title", lang)
            desc = locales.t(
                "challenge_auto_duck_desc",
                lang,
                challenger=f"<@{challenger_id}>",
                challenged=f"<@{challenged_id}>"
            )
            embed_color = discord.Color.red()

            guild_name = guild.name.strip() if guild and guild.name and guild.name.strip() else "GANGHUB"
            # Отправляем ЛС (DM) нарушителю
            if challenged_member:
                try:
                    cd_lang = locales.get_user_lang(self.db, challenged_id, fallback="ru")
                    dm_embed = discord.Embed(
                        title=locales.t("challenge_dm_duck_recipient_title", cd_lang),
                        description=locales.t(
                            "challenge_dm_duck_recipient",
                            cd_lang,
                            challenger=f"<@{challenger_id}>",
                            guild=guild_name
                        ),
                        color=discord.Color.red()
                    )
                    dm_embed.set_footer(text=locales.t("challenge_dm_duck_recipient_footer", cd_lang))
                    await challenged_member.send(embed=dm_embed)
                except discord.Forbidden:
                    pass
                except Exception as e:
                    log.warning(f"⚠️ Не удалось доставить ЛС о даке: {e}")

            # Отправляем ЛС (DM) инициатору вызова
            if challenger_member:
                try:
                    cr_lang = locales.get_user_lang(self.db, challenger_id, fallback="ru")
                    dm_embed = discord.Embed(
                        title=locales.t("challenge_dm_duck_challenger_title", cr_lang),
                        description=locales.t(
                            "challenge_dm_duck_challenger",
                            cr_lang,
                            challenged=f"<@{challenged_id}>",
                            guild=guild_name
                        ),
                        color=discord.Color.green()
                    )
                    dm_embed.set_footer(text=locales.t("challenge_dm_duck_challenger_footer", cr_lang))
                    await challenger_member.send(embed=dm_embed)
                except discord.Forbidden:
                    pass
                except Exception as e:
                    log.warning(f"⚠️ Не удалось доставить ЛС инициатору: {e}")

        # Обновляем оригинальное сообщение вызова в канале (отключаем кнопки)
        try:
            channel = guild.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
            if channel:
                msg = await channel.fetch_message(message_id)
                if msg:
                    res_embed = discord.Embed(
                        title=title,
                        description=desc,
                        color=embed_color
                    )
                    res_embed.set_footer(text="GangHub League 1v1 • Challenge status updated" if lang == "en" else "GangHub League 1v1 • Статус вызова обновлен")
                    disabled_view = discord.ui.View(timeout=None)
                    await msg.edit(embed=res_embed, view=disabled_view)
        except Exception as e:
            log.warning(f"⚠️ Не удалось обновить сообщение вызова #{message_id}: {e}")

    match_group = app_commands.Group(name="match", description="Управление и регистрация матчей 1v1", guild_only=True)

    async def _execute_report(
        self,
        interaction: discord.Interaction,
        winner: discord.Member,
        loser: discord.Member,
        proof: Optional[str] = None,
        winner_build: Optional[str] = None,
        loser_build: Optional[str] = None,
        other: Optional[str] = None
    ):
        lang = locales.get_lang(interaction)
        # 1. Защита от 3-секундного таймаута Discord (10062 Unknown Interaction)
        if not interaction.response.is_done():
            await interaction.response.defer()

        is_admin = interaction.user.guild_permissions.administrator if (interaction.guild and hasattr(interaction.user, "guild_permissions")) else False

        async def send_err(msg: str):
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)

        if not is_resp_or_admin(interaction):
            await send_err(locales.t("error_resp_only", lang, role=config.RESP_ROLE_NAME))
            return

        if winner.id == loser.id:
            await send_err(locales.t("error_same_user", lang))
            return

        if winner.bot or loser.bot:
            await send_err(locales.t("error_bot_user", lang))
            return

        # Защита от судейства самого себя (конфликт интересов)
        if interaction.user.id in (winner.id, loser.id):
            await send_err(locales.t("error_self_referee", lang))
            return

        # Валидация ссылки на доказательство (пруф)
        if proof:
            is_valid, err_msg = validate_proof_url(proof, lang=lang)
            if not is_valid:
                await send_err(err_msg)
                return
            proof = proof.strip()

        # 2. Асинхронный лок: исключает двойное нажатие и повреждение рейтингов
        async with self._lock:
            # Защита от перелива и договорных матчей (win-trading) — Администраторам разрешен байпас для тестов
            if not is_admin:
                can_play, reason = await asyncio.to_thread(self.db.can_play_match, winner.id, loser.id)
                if not can_play:
                    if lang == "en":
                        reason = "Limit reached: these players have already played the maximum daily matches in the last 24 hours."
                    await send_err(f"🚫 {reason}")
                    return

            # Выполняем запись в отдельном потоке (I/O не блокирует gateway)
            update, match_id = await asyncio.to_thread(
                self.db.record_match,
                winner_id=winner.id,
                loser_id=loser.id,
                rep_id=interaction.user.id,
                proof_url=proof,
                winner_build=winner_build,
                loser_build=loser_build,
                other=other
            )

            # Получаем свежие данные
            w_user = await asyncio.to_thread(self.db.get_or_create_user, winner.id)
            l_user = await asyncio.to_thread(self.db.get_or_create_user, loser.id)

            w_pos = await asyncio.to_thread(self.db.get_user_rank_position, winner.id)
            l_pos = await asyncio.to_thread(self.db.get_user_rank_position, loser.id)

            w_rank = get_rank_info(w_user["rating"], w_user["rd"], w_user["wins"] + w_user["losses"], w_pos, lang=lang)
            l_rank = get_rank_info(l_user["rating"], l_user["rd"], l_user["wins"] + l_user["losses"], l_pos, lang=lang)

            # 3. Атомарное обновление ролей с защитой от 403 Forbidden
            await sync_user_roles(winner, w_rank, interaction.guild)
            await sync_user_roles(loser, l_rank, interaction.guild)

            # 4. Освобождаем забронированный VIP-сервер Лиги
            freed_slot = await asyncio.to_thread(self.db.release_league_vip_by_players, winner.id, loser.id)

        # Определение названий сыгранных связок для вывода в эмбед
        w_b = (winner_build.strip() if winner_build and winner_build.strip() else f"{w_user.get('stand') or 'Standless'} + {w_user.get('spec') or 'Specless'}")[:48]
        l_b = (loser_build.strip() if loser_build and loser_build.strip() else f"{l_user.get('stand') or 'Standless'} + {l_user.get('spec') or 'Specless'}")[:48]

        # Формируем красивое сообщение
        embed = discord.Embed(
            title=locales.t("match_reported_title", lang),
            description=locales.t("match_reported_desc", lang, rep=interaction.user.mention, match_id=match_id),
            color=discord.Color.green()
        )

        w_delta_str = f"+{update.winner_delta:.1f}" if update.winner_delta >= 0 else f"{update.winner_delta:.1f}"
        l_delta_str = f"{update.loser_delta:.1f}"

        w_change = locales.t(
            "match_rating_change",
            lang,
            before=int(round(update.winner_rating_before)),
            after=int(round(update.winner_rating_after)),
            delta=w_delta_str,
            badge=w_rank["badge"],
            tier=w_rank["tier"]
        )
        w_streak_str = locales.t("match_winner_streak", lang, count=w_user["streak"]) if w_user["streak"] > 0 else ""

        build_label = "🧬 Build" if lang == "en" else "🧬 Связка"
        w_flag = config.get_country_flag(w_user.get("country"))
        l_flag = config.get_country_flag(l_user.get("country"))

        embed.add_field(
            name=locales.t("match_winner_field", lang, name=f"{w_flag}{winner.display_name}"),
            value=f"{w_change}{w_streak_str}\n{build_label}: **{w_b}**",
            inline=False
        )

        l_change = locales.t(
            "match_rating_change",
            lang,
            before=int(round(update.loser_rating_before)),
            after=int(round(update.loser_rating_after)),
            delta=l_delta_str,
            badge=l_rank["badge"],
            tier=l_rank["tier"]
        )

        embed.add_field(
            name=locales.t("match_loser_field", lang, name=f"{l_flag}{loser.display_name}"),
            value=f"{l_change}\n{build_label}: **{l_b}**",
            inline=False
        )

        if proof:
            embed.add_field(
                name=locales.t("match_proof_field", lang),
                value=locales.t("match_proof_link", lang, url=proof),
                inline=False
            )

        if other and other.strip():
            embed.add_field(
                name=locales.t("match_other_field", lang),
                value=discord.utils.escape_markdown(other.strip())[:1024],
                inline=False
            )

        embed.set_footer(text=f"Матч #{match_id}" if lang == "ru" else f"Match #{match_id}")

        # Автоматическое переименование ветки дуэли при завершении и закрытие вызова в БД
        finished_ch = await asyncio.to_thread(self.db.finish_challenge_for_players, winner.id, loser.id)
        target_thread = None
        if isinstance(interaction.channel, discord.Thread):
            target_thread = interaction.channel
        elif finished_ch and finished_ch.get("channel_id") and interaction.guild:
            try:
                ch_obj = interaction.guild.get_channel(finished_ch["channel_id"])
                if not ch_obj:
                    ch_obj = await interaction.guild.fetch_channel(finished_ch["channel_id"])
                if isinstance(ch_obj, discord.Thread):
                    target_thread = ch_obj
            except Exception:
                pass

        # 1. Публикуем результат матча в ветку дуэли или канал
        if target_thread:
            await target_thread.send(embed=embed)
            try:
                new_t_name = f"✅・{w_flag}{winner.display_name[:10]} def. {l_flag}{loser.display_name[:10]}"[:100]
                await target_thread.edit(name=new_t_name)
            except Exception as e:
                log.warning(f"⚠️ Не удалось переименовать ветку дуэли: {e}")
        elif interaction.channel:
            await interaction.channel.send(embed=embed)

        # 2. Публикуем результат матча в глобальный канал результатов Лиги (1v1s-elos)
        results_channel = await get_match_results_channel(interaction.guild, self.db, interaction.client)
        if results_channel:
            already_posted_ids = set()
            if target_thread:
                already_posted_ids.add(target_thread.id)
            if interaction.channel:
                already_posted_ids.add(interaction.channel.id)

            if results_channel.id not in already_posted_ids:
                try:
                    await results_channel.send(embed=embed)
                except Exception as e:
                    log.warning(f"⚠️ Не удалось отправить результат матча #{match_id} в канал результатов {results_channel.id}: {e}")

        # 3. Подтверждение взаимодействия для инициатора
        try:
            if interaction.response.is_done():
                await interaction.edit_original_response(
                    content=f"✅ Результат матча #{match_id} успешно зафиксирован! Победитель: {winner.mention} ({w_delta_str} ELO).",
                    view=None
                )
            else:
                await interaction.response.send_message(embed=embed)
        except Exception:
            pass

    @match_group.command(name="report", description="[Для Респов и Админов] Внести результат матча 1v1")
    @app_commands.describe(
        winner="Игрок, одержавший победу",
        loser="Игрок, потерпевший поражение",
        proof="Ссылка на скриншот/видео подтверждение",
        winner_build="Связка победителя (если отличается от /build, например: GER + Boxing)",
        loser_build="Связка проигравшего (если отличается от /build, например: KCR + Hamon)",
        other="Прочее / Заметки к матчу (например: счёт 2-0, комментарий судьи)"
    )
    async def report(
        self,
        interaction: discord.Interaction,
        winner: discord.Member,
        loser: discord.Member,
        proof: Optional[str] = None,
        winner_build: Optional[str] = None,
        loser_build: Optional[str] = None,
        other: Optional[str] = None
    ):
        await self._execute_report(interaction, winner, loser, proof, winner_build, loser_build, other)

    @app_commands.command(name="report", description="[Для Респов и Админов] Внести результат матча 1v1")
    @app_commands.describe(
        winner="Игрок, одержавший победу",
        loser="Игрок, потерпевший поражение",
        proof="Ссылка на скриншот/видео подтверждение",
        winner_build="Связка победителя (если отличается от /build, например: GER + Boxing)",
        loser_build="Связка проигравшего (если отличается от /build, например: KCR + Hamon)",
        other="Прочее / Заметки к матчу (например: счёт 2-0, комментарий судьи)"
    )
    @app_commands.guild_only()
    async def report_alias(
        self,
        interaction: discord.Interaction,
        winner: discord.Member,
        loser: discord.Member,
        proof: Optional[str] = None,
        winner_build: Optional[str] = None,
        loser_build: Optional[str] = None,
        other: Optional[str] = None
    ):
        await self._execute_report(interaction, winner, loser, proof, winner_build, loser_build, other)

    @commands.command(name="report", aliases=["репорт", "match_report"])
    @commands.guild_only()
    async def prefix_report(
        self,
        ctx: commands.Context,
        winner: discord.Member,
        loser: discord.Member,
        proof: Optional[str] = None,
        *,
        other: Optional[str] = None
    ):
        """Префиксная команда !report @winner @loser [proof] [other]"""
        lang = locales.get_user_lang(self.db, ctx.author.id, fallback="ru")
        is_resp = check_is_resp_or_admin(ctx.author, ctx.guild)

        if not is_resp:
            await ctx.reply("❌ Эта команда доступна только роли @1v1s Responsible или Администраторам." if lang != "en" else "❌ Only @1v1s Responsible or Administrators can report matches.")
            return

        if winner.id == loser.id:
            await ctx.reply("❌ Победитель и проигравший не могут совпадать." if lang != "en" else "❌ Winner and loser cannot be the same player.")
            return

        if winner.bot or loser.bot:
            await ctx.reply("❌ Нельзя указывать ботов в результате матча." if lang != "en" else "❌ Cannot record matches involving bots.")
            return

        if ctx.author.id in (winner.id, loser.id):
            await ctx.reply("❌ Респ не может судить собственный матч!" if lang != "en" else "❌ A referee cannot judge their own match!")
            return

        is_admin = getattr(ctx.author, "guild_permissions", None) and ctx.author.guild_permissions.administrator

        async with self._lock:
            if not is_admin:
                can_play, reason = await asyncio.to_thread(self.db.can_play_match, winner.id, loser.id)
                if not can_play:
                    await ctx.reply(f"🚫 {reason}")
                    return

            update, match_id = await asyncio.to_thread(
                self.db.record_match,
                winner_id=winner.id,
                loser_id=loser.id,
                rep_id=ctx.author.id,
                proof_url=proof,
                other=other
            )
            w_user = await asyncio.to_thread(self.db.get_or_create_user, winner.id)
            l_user = await asyncio.to_thread(self.db.get_or_create_user, loser.id)
            w_pos = await asyncio.to_thread(self.db.get_user_rank_position, winner.id)
            l_pos = await asyncio.to_thread(self.db.get_user_rank_position, loser.id)

            w_rank = get_rank_info(w_user["rating"], w_user["rd"], w_user["wins"] + w_user["losses"], w_pos, lang=lang)
            l_rank = get_rank_info(l_user["rating"], l_user["rd"], l_user["wins"] + l_user["losses"], l_pos, lang=lang)

            await sync_user_roles(winner, w_rank, ctx.guild)
            await sync_user_roles(loser, l_rank, ctx.guild)
            freed_slot = await asyncio.to_thread(self.db.release_league_vip_by_players, winner.id, loser.id)

        w_delta_str = f"+{update.winner_delta:.1f}" if update.winner_delta >= 0 else f"{update.winner_delta:.1f}"
        l_delta_str = f"{update.loser_delta:.1f}"
        w_flag = config.get_country_flag(w_user.get("country"))
        l_flag = config.get_country_flag(l_user.get("country"))
        embed = discord.Embed(
            title="⚔️ Результат 1v1 дуэли внесен" if lang != "en" else "⚔️ 1v1 Duel Result Recorded",
            description=f"Матч #{match_id} внесен судьей {ctx.author.mention}",
            color=discord.Color.green()
        )
        embed.add_field(
            name=f"🏆 Победитель: {w_flag}{winner.display_name}" if lang != "en" else f"🏆 Winner: {w_flag}{winner.display_name}",
            value=f"{w_rank['badge']} **{w_rank['tier']}** • `{int(round(update.winner_rating_after))} ELO` ({w_delta_str})",
            inline=False
        )
        embed.add_field(
            name=f"💀 Проигравший: {l_flag}{loser.display_name}" if lang != "en" else f"💀 Loser: {l_flag}{loser.display_name}",
            value=f"{l_rank['badge']} **{l_rank['tier']}** • `{int(round(update.loser_rating_after))} ELO` ({l_delta_str})",
            inline=False
        )
        if proof:
            embed.add_field(
                name=locales.t("match_proof_field", lang),
                value=locales.t("match_proof_link", lang, url=proof),
                inline=False
            )
        if other and other.strip():
            embed.add_field(
                name=locales.t("match_other_field", lang),
                value=discord.utils.escape_markdown(other.strip())[:1024],
                inline=False
            )
        embed.set_footer(text=f"Матч #{match_id}" if lang != "en" else f"Match #{match_id}")
        await ctx.reply(embed=embed)

        if isinstance(ctx.channel, discord.Thread):
            try:
                new_t_name = f"✅・{w_flag}{winner.display_name[:10]} def. {l_flag}{loser.display_name[:10]}"[:100]
                await ctx.channel.edit(name=new_t_name)
            except Exception:
                pass

        # Публикуем результат матча в глобальный канал результатов Лиги (1v1s-elos)
        results_channel = await get_match_results_channel(ctx.guild, self.db, ctx.bot)
        if results_channel and results_channel.id != ctx.channel.id:
            try:
                await results_channel.send(embed=embed)
            except Exception as e:
                log.warning(f"⚠️ Не удалось отправить результат матча #{match_id} в канал результатов {results_channel.id}: {e}")

    # =========================================================
    # СИСТЕМА ДАКОВ И ШТРАФОВ ELO (/duck и !duck)
    # =========================================================

    async def _execute_duck(
        self,
        executor: Union[discord.Interaction, commands.Context],
        user: discord.Member,
        opponent: Optional[discord.Member] = None,
        penalty: Optional[int] = None,
        reason: Optional[str] = None
    ):
        """Единый исполнитель фиксации дака с вычитанием ELO (Вариант 2: Glicko-2) и выдачей роли Duck"""
        is_interaction = isinstance(executor, discord.Interaction)
        author = executor.user if is_interaction else executor.author
        guild = executor.guild
        channel = executor.channel

        lang = locales.get_lang(executor) if is_interaction else locales.get_user_lang(self.db, author.id, fallback="ru")

        # 1. Проверка прав: только @1v1s Responsible или Администраторы
        is_resp = check_is_resp_or_admin(author, guild)
        if not is_resp:
            err_msg = locales.t("error_resp_only", lang, role=config.RESP_ROLE_NAME)
            if is_interaction:
                await executor.response.send_message(err_msg, ephemeral=True)
            else:
                await executor.reply(err_msg)
            return

        # 2. Нельзя дакать ботов
        if user.bot:
            err_msg = "❌ Нельзя зафиксировать Дак на бота." if lang == "ru" else "❌ Cannot record Duck on a bot."
            if is_interaction:
                await executor.response.send_message(err_msg, ephemeral=True)
            else:
                await executor.reply(err_msg)
            return

        # 3. Автоматическое определение оппонента:
        # Если передан явно -> берем его.
        # Иначе смотрим, есть ли активный вызов в этой ветке/канале -> берем соперника из вызова.
        resolved_opp_id = opponent.id if opponent else None
        ch = None
        if channel and hasattr(channel, "id") and isinstance(channel.id, int):
            ch = await asyncio.to_thread(self.db.get_challenge_by_channel, channel.id)
            if ch:
                if not resolved_opp_id:
                    if user.id == ch.get("challenged_id"):
                        resolved_opp_id = ch.get("challenger_id")
                    elif user.id == ch.get("challenger_id"):
                        resolved_opp_id = ch.get("challenged_id")
                if ch.get("status") in ("pending", "accepted"):
                    await asyncio.to_thread(self.db.update_challenge_status, ch["id"], "ducked")

        actual_reason = reason.strip() if reason and reason.strip() else ("Отказ от дуэли / Дак в ветке" if lang == "ru" else "Duel refusal / Duck in thread")

        # 4. Применяем штраф ELO:
        # Вариант 2: Списание по формуле Glicko-2 ровно как за проигрыш против оппонента (без начисления очков оппоненту).
        # Если оппонент не найден (вызов вне ветки без указания оппонента) или задан явный штраф penalty -> применяем фиксированный штраф.
        if penalty is not None:
            p_res = await asyncio.to_thread(self.db.apply_duck_penalty, user.id, float(penalty), actual_reason)
        elif resolved_opp_id:
            p_res = await asyncio.to_thread(self.db.apply_glicko_duck_penalty, user.id, resolved_opp_id, actual_reason)
        else:
            default_penalty = float(getattr(config, "DUCK_ELO_PENALTY", 25))
            p_res = await asyncio.to_thread(self.db.apply_duck_penalty, user.id, default_penalty, actual_reason)

        old_elo = p_res["old_rating"]
        new_elo = p_res["rating"]
        actual_delta = p_res["delta"]
        tot = p_res["wins"] + p_res["losses"]
        p_pos = await asyncio.to_thread(self.db.get_user_rank_position, user.id) if tot > 0 else None
        r_info = get_rank_info(new_elo, p_res["rd"], tot, p_pos, lang=lang)

        # 5. Синхронизируем ранговые роли игрока при падении рейтинга
        await sync_user_roles(user, r_info, guild)

        # 6. Выдаем роль Duck
        duck_role = get_duck_role(guild)
        duck_role_assigned = False
        if duck_role:
            try:
                await user.add_roles(duck_role, reason=f"GangHub League: Дак зафиксирован {author.display_name}")
                duck_role_assigned = True
            except Exception as e:
                log.warning(f"⚠️ [Duck Command] Не удалось выдать роль {duck_role.name}: {e}")

        # 7. Если канал — ветка дуэли, переименовываем
        if isinstance(channel, discord.Thread):
            try:
                u_country = await asyncio.to_thread(self.db.get_user_country, user.id)
                u_flag = config.get_country_flag(u_country)
                new_t_name = f"🦆・Дак: {u_flag}{user.display_name[:10]}"[:100]
                await channel.edit(name=new_t_name)
            except Exception:
                pass

        # 8. Формируем эмбед для ветки
        delta_str = f"-{int(round(abs(actual_delta)))}" if actual_delta < 0 else f"{int(round(actual_delta))}"
        embed = discord.Embed(
            title="🦆 ФИКСАЦИЯ ДАКА (DUCK) • ШТРАФ РЕЙТИНГА" if lang == "ru" else "🦆 DUCK RECORDED • RATING PENALTY",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow()
        )
        opp_mention_str = f"• **Оппонент:** <@{resolved_opp_id}>\n" if resolved_opp_id else ""
        if lang == "ru":
            embed.description = (
                f"⚠️ **Судья дуэли ({author.mention}) зафиксировал отказ от боя!**\n\n"
                f"• **Нарушитель:** {user.mention} (`{user.display_name}`)\n"
                f"{opp_mention_str}"
                f"• **Штраф ELO (как за проигрыш):** **{delta_str} ELO** (`{int(round(old_elo))} ➔ {int(round(new_elo))}`)\n"
                f"• **Текущий ранг:** {r_info['badge']} **{r_info['tier']}**\n"
                f"• **Роль Duck:** {'Выдана ✅' if duck_role_assigned else 'Уже имеется'}\n"
                f"• **Причина:** {actual_reason}\n"
                f"• **Судья (Responsible):** {author.mention}"
            )
            embed.set_footer(text="GANGHUB League • Регламент вызовов и даков")
        else:
            embed.description = (
                f"⚠️ **Duel Referee ({author.mention}) recorded a fight refusal!**\n\n"
                f"• **Offender:** {user.mention} (`{user.display_name}`)\n"
                f"{opp_mention_str}"
                f"• **ELO Penalty (Loss Delta):** **{delta_str} ELO** (`{int(round(old_elo))} ➔ {int(round(new_elo))}`)\n"
                f"• **Current Rank:** {r_info['badge']} **{r_info['tier']}**\n"
                f"• **Duck Role:** {'Assigned ✅' if duck_role_assigned else 'Already assigned'}\n"
                f"• **Reason:** {actual_reason}\n"
                f"• **Referee:** {author.mention}"
            )
            embed.set_footer(text="GANGHUB League • Challenge & Duck Rules")

        # 9. Отправляем в ветку/канал с прямым пингом нарушителя
        ping_content = f"⚠️ {user.mention}"
        if is_interaction:
            await executor.response.send_message(content=ping_content, embed=embed)
        else:
            await executor.send(content=ping_content, embed=embed)

        # 10. Лог в канал даков (#даки)
        try:
            duck_ch = await get_duck_channel(guild, self.db)
            if duck_ch:
                jump_link = f"https://discord.com/channels/{guild.id}/{channel.id}" if (guild and channel) else ""
                duck_log_embed = discord.Embed(
                    title="🦆 ФИКСАЦИЯ ДАКА (DUCK) • Решение судьи" if lang == "ru" else "🦆 DUCK RECORDED • Referee Decision",
                    color=discord.Color.red(),
                    timestamp=discord.utils.utcnow()
                )
                duck_log_embed.description = (
                    f"• **Кто дакнул (Duck):** {user.mention} (`{user.display_name}`)\n"
                    + (f"• **Кому дакнул:** <@{resolved_opp_id}>\n" if resolved_opp_id else "") +
                    f"• **Штраф ELO (Glicko-2):** **{delta_str} ELO** (`{int(round(old_elo))} ➔ {int(round(new_elo))}`)\n"
                    f"• **Судья (@1v1s Responsible):** {author.mention}\n"
                    f"• **Причина:** {actual_reason}\n"
                    f"• **Роль Duck:** {'Выдана ✅' if duck_role_assigned else 'Уже имеется'}\n"
                    + (f"• **Ветка/Канал:** [Перейти к ветке]({jump_link})" if jump_link else "")
                )
                duck_log_embed.set_footer(text="GangHub League • Официальный лог даков")
                await duck_ch.send(embed=duck_log_embed)
        except Exception as e:
            log.warning(f"⚠️ Не удалось отправить лог дака в канал даков: {e}")

        # 11. Отправка ЛС нарушителю
        try:
            cd_lang = locales.get_user_lang(self.db, user.id, fallback="ru")
            opp_text = f"• **Оппонент:** <@{resolved_opp_id}>\n" if resolved_opp_id else ""
            if cd_lang == "ru":
                dm_embed = discord.Embed(
                    title="🦆 ВАМ ЗАФИКСИРОВАН ДАК (DUCK) В ЛИГЕ GANGHUB",
                    description=(
                        f"Судья **{author.display_name}** зафиксировал отказ от дуэли.\n\n"
                        f"• **Штраф рейтинга (как за проигрыш):** **{delta_str} ELO** (Ваш рейтинг: `{int(round(new_elo))}`)\n"
                        f"{opp_text}"
                        f"• **Причина:** {actual_reason}\n"
                        f"• **Роль Duck:** Начислена на сервере.\n\n"
                        f"Ознакомьтесь с регламентом вызовов в `/rules`."
                    ),
                    color=discord.Color.red()
                )
            else:
                dm_embed = discord.Embed(
                    title="🦆 DUCK STATUS RECORDED IN GANGHUB LEAGUE",
                    description=(
                        f"Referee **{author.display_name}** recorded a duel refusal.\n\n"
                        f"• **Rating Penalty (Loss Delta):** **{delta_str} ELO** (Your rating: `{int(round(new_elo))}`)\n"
                        f"{opp_text}"
                        f"• **Reason:** {actual_reason}\n"
                        f"• **Duck Role:** Assigned on server.\n\n"
                        f"Check challenge rules in `/rules`."
                    ),
                    color=discord.Color.red()
                )
            await user.send(embed=dm_embed)
        except Exception:
            pass

    @app_commands.command(
        name="duck",
        description="[Для Респов] Зафиксировать Дак (отказ от дуэли) и списать ELO как за проигрыш 🦆"
    )
    @app_commands.describe(
        user="Игрок, отказавшийся от дуэли (получит штраф ELO за проигрыш и роль Duck)",
        opponent="Оппонент, от кого был дак (в ветке определится автоматически)",
        penalty="Фиксированный штраф ELO (если не указан, рассчитается по Glicko-2 как за проигрыш)",
        reason="Причина фиксации дака (по умолчанию: Отказ от боя / Дак)"
    )
    @app_commands.guild_only()
    async def duck(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        opponent: Optional[discord.Member] = None,
        penalty: Optional[app_commands.Range[int, 0, 300]] = None,
        reason: Optional[str] = None
    ):
        await self._execute_duck(interaction, user, opponent=opponent, penalty=penalty, reason=reason)

    @commands.command(name="duck", aliases=["дак", "задакать", "задакал"])
    @commands.guild_only()
    async def prefix_duck(
        self,
        ctx: commands.Context,
        user: discord.Member,
        opponent: Optional[discord.Member] = None,
        penalty: Optional[int] = None,
        *,
        reason: Optional[str] = None
    ):
        """[Для Респов] Префиксная команда: !duck @user [@opponent] [штраф] [причина]"""
        await self._execute_duck(ctx, user, opponent=opponent, penalty=penalty, reason=reason)

    @match_group.command(name="undo", description="[Для Респов] Откатить ошибочно внесенный матч")
    @app_commands.describe(match_id="ID матча (если не указан — отменит последний внесенный вами матч)")
    async def undo(self, interaction: discord.Interaction, match_id: Optional[int] = None):
        lang = locales.get_lang(interaction)
        await interaction.response.defer(ephemeral=True)

        if not is_resp_or_admin(interaction):
            await interaction.followup.send(locales.t("error_resp_only", lang, role=config.RESP_ROLE_NAME), ephemeral=True)
            return

        if match_id is None:
            last_m = await asyncio.to_thread(
                self.db.get_last_match_for_rep,
                interaction.user.id,
                interaction.user.guild_permissions.administrator
            )
            if not last_m:
                msg = "❌ No recent matches found to undo." if lang == "en" else "❌ Не найдено последних матчей для отката."
                await interaction.followup.send(msg, ephemeral=True)
                return
            match_id = last_m["id"]
        elif match_id <= 0:
            await interaction.followup.send(
                "❌ Match ID must be a positive integer." if lang == "en" else "❌ ID матча должен быть положительным числом.",
                ephemeral=True
            )
            return

        async with self._lock:
            success, match_data = await asyncio.to_thread(
                self.db.undo_last_match,
                match_id=match_id,
                rep_id=interaction.user.id,
                is_admin=interaction.user.guild_permissions.administrator
            )
            if success and match_data:
                # Синхронизируем роли обратно, чтобы не оставалось «вечных Мастеров»
                for uid in (match_data["winner_id"], match_data["loser_id"]):
                    u_data = await asyncio.to_thread(self.db.get_or_create_user, uid)
                    pos = await asyncio.to_thread(self.db.get_user_rank_position, uid)
                    total = u_data["wins"] + u_data["losses"]
                    r_info = get_rank_info(u_data["rating"], u_data["rd"], total, pos, lang=lang)

                    member = interaction.guild.get_member(uid)
                    if not member:
                        try:
                            member = await interaction.guild.fetch_member(uid)
                        except Exception:
                            member = None

                    if member:
                        await sync_user_roles(member, r_info, interaction.guild)

        if success and match_data:
            embed = discord.Embed(
                title=locales.t("match_undo_success_title", lang),
                description=locales.t("match_undo_success_desc", lang, match_id=match_id),
                color=discord.Color.orange()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

            # Публичное уведомление в ветку/канал матча и переименование ветки
            target_thread = None
            if isinstance(interaction.channel, discord.Thread):
                target_thread = interaction.channel
            else:
                ch_item = await asyncio.to_thread(self.db.get_challenge_by_channel, interaction.channel_id)
                if ch_item and ch_item.get("channel_id") and interaction.guild:
                    try:
                        ch_obj = interaction.guild.get_channel(ch_item["channel_id"])
                        if isinstance(ch_obj, discord.Thread):
                            target_thread = ch_obj
                    except Exception:
                        pass

            public_undo_embed = discord.Embed(
                title="↩️ Матч аннулирован • Результат откатан" if lang != "en" else "↩️ Match Annulled • Result Undone",
                description=(
                    f"⚠️ Респонсибл {interaction.user.mention} аннулировал результат **Матча #{match_id}**!\n"
                    f"• Участники: <@{match_data['winner_id']}> и <@{match_data['loser_id']}>\n"
                    f"• Рейтинги игроков и статистика побед/поражений возвращены в исходное состояние."
                    if lang != "en" else
                    f"⚠️ Referee {interaction.user.mention} has annulled the result of **Match #{match_id}**!\n"
                    f"• Participants: <@{match_data['winner_id']}> and <@{match_data['loser_id']}>\n"
                    f"• Player ratings and win/loss records have been rolled back to their previous state."
                ),
                color=discord.Color.orange()
            )
            public_undo_embed.set_footer(text="GANGHUB League • Referee Decision")

            w_mem = interaction.guild.get_member(match_data["winner_id"]) if interaction.guild else None
            l_mem = interaction.guild.get_member(match_data["loser_id"]) if interaction.guild else None
            w_name = w_mem.display_name if w_mem else str(match_data["winner_id"])
            l_name = l_mem.display_name if l_mem else str(match_data["loser_id"])

            if target_thread:
                try:
                    await target_thread.send(embed=public_undo_embed)
                    undo_t_name = f"↩️・Откат #{match_id}: {w_name[:10]} vs {l_name[:10]}"[:100]
                    await target_thread.edit(name=undo_t_name)
                except Exception as e:
                    log.warning(f"⚠️ Не удалось отправить уведомление об откате в ветку: {e}")
            elif interaction.channel:
                try:
                    await interaction.channel.send(embed=public_undo_embed)
                except Exception:
                    pass

            # Уведомляем общий канал результатов об аннулировании матча
            results_channel = await get_match_results_channel(interaction.guild, self.db, interaction.client)
            if results_channel:
                already_posted_ids = set()
                if target_thread:
                    already_posted_ids.add(target_thread.id)
                if interaction.channel:
                    already_posted_ids.add(interaction.channel.id)

                if results_channel.id not in already_posted_ids:
                    try:
                        await results_channel.send(embed=public_undo_embed)
                    except Exception as e:
                        log.warning(f"⚠️ Не удалось отправить уведомление об откате в канал результатов: {e}")
        elif success:
            embed = discord.Embed(
                title=locales.t("match_undo_success_title", lang),
                description=locales.t("match_undo_success_desc", lang, match_id=match_id),
                color=discord.Color.orange()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.followup.send(
                locales.t("match_undo_fail", lang, match_id=match_id),
                ephemeral=True
            )

    @match_group.command(name="history", description="История последних дуэлей")
    @app_commands.describe(user="Игрок, чью историю посмотреть (по умолчанию — последние дуэли сервера)")
    async def history(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        lang = locales.get_lang(interaction)
        await interaction.response.defer()
        user_id = user.id if user else None
        matches = await asyncio.to_thread(self.db.get_recent_matches, discord_id=user_id, limit=5)

        if lang == "en":
            title = f"📜 Duel History • {user.display_name}" if user else "📜 Recent Server Duels"
        else:
            title = f"📜 История дуэлей • {user.display_name}" if user else "📜 Последние дуэли сервера"
        embed = discord.Embed(title=title, color=discord.Color.blurple())

        if not matches:
            embed.description = "Match history is empty." if lang == "en" else "История матчей пуста."
        else:
            from datetime import datetime, timezone
            lines = []
            for m in matches:
                w_delta = m['winner_after'] - m['winner_before']
                l_delta = m['loser_after'] - m['loser_before']
                w_name = f"<@{m['winner_id']}>"
                l_name = f"<@{m['loser_id']}>"

                match_ts = int(discord.utils.utcnow().timestamp())
                if m.get("created_at"):
                    try:
                        dt = datetime.strptime(str(m["created_at"]).split(".")[0], "%Y-%m-%d %H:%M:%S")
                        match_ts = int(dt.replace(tzinfo=timezone.utc).timestamp())
                    except Exception:
                        pass

                match_prefix = f"**Match #{m['id']}**" if lang == "en" else f"**Матч #{m['id']}**"
                lines.append(
                    f"{match_prefix} • <t:{match_ts}:R>\n"
                    f"🏆 {w_name} (+{w_delta:.0f}) def. 💀 {l_name} ({l_delta:.0f})\n"
                )
            embed.description = "\n".join(lines)

        await interaction.followup.send(embed=embed)

    @match_group.command(name="cancel", description="[Респы/Админы/Игроки] Отменить активную дуэль и освободить VIP-сервер")
    @app_commands.describe(
        opponent="Соперник (если команда вызывается вне ветки матча)",
        reason="Причина отмены дуэли"
    )
    async def match_cancel(
        self,
        interaction: discord.Interaction,
        opponent: Optional[discord.Member] = None,
        reason: Optional[str] = None
    ):
        lang = locales.get_lang(interaction)
        await interaction.response.defer(ephemeral=True)

        is_ref_or_adm = is_resp_or_admin(interaction)
        target_ch = None

        # 1. Если вызвана внутри ветки дуэли — ищем вызов по ID канала/ветки
        if interaction.channel_id:
            target_ch = await asyncio.to_thread(self.db.get_challenge_by_channel, interaction.channel_id)

        # 2. Если не найден по каналу, но указан соперник — ищем по участникам
        if not target_ch and opponent:
            target_ch = await asyncio.to_thread(self.db.get_latest_challenge_for_players, interaction.user.id, opponent.id)

        # 3. Если вызвал игрок без указания соперника — ищем его активный исходящий вызов
        if not target_ch and not is_ref_or_adm:
            target_ch = await asyncio.to_thread(self.db.get_active_outgoing_challenge, interaction.user.id)

        if not target_ch:
            msg = (
                "❌ Active duel not found. Call this command inside the duel thread or specify the opponent: `/match cancel opponent:@User`."
                if lang == "en"
                else "❌ Активная дуэль не найдена. Вызовите команду внутри ветки дуэли или укажите соперника: `/match cancel opponent:@User`."
            )
            await interaction.followup.send(msg, ephemeral=True)
            return

        p1_id = target_ch["challenger_id"]
        p2_id = target_ch["challenged_id"]

        # Проверка прав: Респонсиблы/Админы МОГУТ отменять любые матчи; игроки — ТОЛЬКО свои
        if not is_ref_or_adm and interaction.user.id not in (p1_id, p2_id):
            msg = (
                "🚫 Only duel participants or Referees/Admins can cancel this match."
                if lang == "en"
                else "🚫 Отменить дуэль могут только её участники или Респонсиблы/Администрация сервера."
            )
            await interaction.followup.send(msg, ephemeral=True)
            return

        # Атомарно переводим вызов в статус 'cancelled'
        await asyncio.to_thread(self.db.update_challenge_status, target_ch["id"], "cancelled")

        # Мгновенно освобождаем забронированный VIP-сервер Лиги
        freed_slot = await asyncio.to_thread(self.db.release_league_vip_by_players, p1_id, p2_id)

        # Подготовка имен для сообщения
        p1_mem = interaction.guild.get_member(p1_id) if interaction.guild else None
        p2_mem = interaction.guild.get_member(p2_id) if interaction.guild else None
        p1_name = p1_mem.display_name if p1_mem else f"<@{p1_id}>"
        p2_name = p2_mem.display_name if p2_mem else f"<@{p2_id}>"

        reason_text = f"\n• **Причина:** {reason.strip()}" if reason and reason.strip() else ""
        vip_freed_line = f"\n• 🟢 **VIP-сервер Лиги #{freed_slot} освобожден.**" if freed_slot else ""

        cancel_embed = discord.Embed(
            title="🚫 Дуэль отменена • Match Cancelled" if lang != "en" else "🚫 Duel Cancelled",
            description=(
                f"Дуэль между <@{p1_id}> и <@{p2_id}> была отменена {interaction.user.mention}."
                f"{reason_text}{vip_freed_line}\n"
                f"Все блокировки сняты, игроки могут снова бросать вызовы или вставать в `/queue`."
                if lang != "en" else
                f"The duel between <@{p1_id}> and <@{p2_id}> was cancelled by {interaction.user.mention}."
                f"{reason_text}{vip_freed_line}\n"
                f"Match locks cleared. Players may now challenge again or join `/queue`."
            ),
            color=discord.Color.dark_grey()
        )
        cancel_embed.set_footer(text="GANGHUB League • Match Cancelled")

        # Оповещение ветки / канала
        target_thread = None
        if isinstance(interaction.channel, discord.Thread):
            target_thread = interaction.channel
        elif target_ch.get("channel_id") and interaction.guild:
            try:
                ch_obj = interaction.guild.get_channel(target_ch["channel_id"])
                if isinstance(ch_obj, discord.Thread):
                    target_thread = ch_obj
            except Exception:
                pass

        if target_thread:
            try:
                await target_thread.send(embed=cancel_embed)
                new_t_name = f"🚫・Отменено: {p1_name[:10]} vs {p2_name[:10]}"[:100]
                await target_thread.edit(name=new_t_name)
            except Exception as e:
                log.warning(f"⚠️ Не удалось обновить ветку отмененной дуэли: {e}")
        elif interaction.channel:
            try:
                await interaction.channel.send(embed=cancel_embed)
            except Exception:
                pass

        await interaction.followup.send(
            f"✅ Дуэль успешно отменена.{vip_freed_line}" if lang != "en" else f"✅ Duel successfully cancelled.{vip_freed_line}",
            ephemeral=True
        )

    @app_commands.command(name="challenge", description="Бросить официальный вызов на 1v1 дуэль по регламенту GANGHUB")
    @app_commands.describe(
        user="Игрок, которому вы бросаете вызов",
        format="Формат дуэли (T1 Any vs Any / T2 Main vs Main / T3 Mirror)",
        server="Регион сервера для дуэли"
    )
    @app_commands.choices(
        format=[
            app_commands.Choice(name="T1: Any vs Any (Любой в Любой — Высший приоритет)", value="T1 - Any vs Any"),
            app_commands.Choice(name="T1: Any vs Any [Bo3 Сет]", value="T1 - Any vs Any (Bo3)"),
            app_commands.Choice(name="T2: Main vs Main (Мейн в Мейн — 2-й приоритет)", value="T2 - Main vs Main"),
            app_commands.Choice(name="T2: Main vs Main [Bo3 Сет]", value="T2 - Main vs Main (Bo3)"),
            app_commands.Choice(name="T3: Mirror (Зеркалка — стенд согласуется в ветке)", value="T3 - Mirror"),
            app_commands.Choice(name="Blind Pick (Вслепую в ЛС Респу)", value="Blind Pick (Вслепую)"),
            app_commands.Choice(name="No TS (Без Тайм-стопа)", value="No TS (Без Таймстопа)"),
            app_commands.Choice(name="Specless (Только стенды, без спека)", value="Specless (Без спека)"),
            app_commands.Choice(name="Standless (Только спеки, без стенда)", value="Standless (Без стенда)"),
            app_commands.Choice(name="По договоренности (Custom)", value="По договоренности"),
        ],
        server=[
            app_commands.Choice(name="Hesse (Германия — приоритет EU/СНГ)", value="Hesse (Германия)"),
            app_commands.Choice(name="North Holland (Нидерланды — приоритет EU)", value="North Holland (Нидерланды)"),
            app_commands.Choice(name="London (Великобритания — Западная Европа)", value="London (Великобритания)"),
            app_commands.Choice(name="US East (Восток США / New Jersey)", value="US East (Восток США)"),
            app_commands.Choice(name="По договоренности (Mutual Region)", value="По договоренности"),
        ]
    )
    @app_commands.guild_only()
    async def challenge(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        format: Optional[str] = "T2 - Main vs Main",
        server: Optional[str] = "Hesse (Германия)"
    ):
        lang = locales.get_lang(interaction)
        if user.id == interaction.user.id:
            await interaction.response.send_message(locales.t("challenge_self_error", lang), ephemeral=True)
            return

        if user.bot:
            await interaction.response.send_message(locales.t("error_bot_user", lang), ephemeral=True)
            return

        if user.id in config.CHALLENGE_IMMUNITY_IDS:
            msg = (
                f"🛡️ **Иммунитет к вызовам!**\n"
                f"У игрока {user.mention} активен иммунитет к прямым вызовам на дуэль Лиги. Вы не можете бросить ему вызов."
                if lang != "en"
                else (
                    f"🛡️ **Challenge Immunity!**\n"
                    f"Player {user.mention} has challenge immunity. You cannot challenge this player."
                )
            )
            await interaction.response.send_message(msg, ephemeral=True)
            return

        is_admin = interaction.user.guild_permissions.administrator if (interaction.guild and hasattr(interaction.user, "guild_permissions")) else False

        if not is_admin:
            can_play, reason = await asyncio.to_thread(self.db.can_play_match, interaction.user.id, user.id)
            if not can_play:
                if lang == "en":
                    reason = "Limit reached: you have already played the maximum daily matches in the last 24 hours."
                await interaction.response.send_message(f"🚫 {reason}", ephemeral=True)
                return

            # 1. Лимит открытых ожидающих вызовов (защита от спама дуэлями)
            max_pending = getattr(config, "MAX_PENDING_CHALLENGES_PER_USER", 1)
            pending_cnt = await asyncio.to_thread(self.db.get_pending_challenges_count_for_user, interaction.user.id)
            if pending_cnt >= max_pending:
                msg = (
                    f"⚠️ **Лимит активных вызовов!**\n"
                    f"У вас уже есть открытый ожидающий вызов ({pending_cnt}/{max_pending}). "
                    f"Дождитесь ответа соперника или отмените прошлый вызов командой `/challenge_cancel`, прежде чем бросать новый."
                    if lang != "en"
                    else (
                        f"⚠️ **Active Challenges Limit!**\n"
                        f"You already have a pending duel challenge ({pending_cnt}/{max_pending}). "
                        f"Wait for your opponent's response or cancel your previous challenge with `/challenge_cancel` before creating a new one."
                    )
                )
                await interaction.response.send_message(msg, ephemeral=True)
                return

            # 2. Кулдаун между созданием вызовов (CHALLENGE_COOLDOWN_SECONDS)
            cd_seconds = getattr(config, "CHALLENGE_COOLDOWN_SECONDS", 600)
            now_ts = time.time()
            last_call = self._challenge_cooldowns.get(interaction.user.id, 0.0)
            remaining_cd = cd_seconds - (now_ts - last_call)

            # Если в памяти бота отметки нет, проверяем дату последнего вызова в SQLite БД
            if remaining_cd <= 0:
                last_ch = await asyncio.to_thread(self.db.get_last_challenge_by_challenger, interaction.user.id)
                if last_ch and last_ch.get("created_at"):
                    try:
                        c_str = str(last_ch["created_at"]).split(".")[0]
                        c_dt = datetime.strptime(c_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                        elapsed_db = (datetime.now(timezone.utc) - c_dt).total_seconds()
                        if elapsed_db < cd_seconds:
                            remaining_cd = cd_seconds - elapsed_db
                    except Exception:
                        pass

            if remaining_cd > 0:
                ready_ts = int(now_ts + remaining_cd)
                cd_min = max(1, int(round(cd_seconds / 60)))
                msg = (
                    f"⏳ **Кулдаун на создание вызовов!**\n"
                    f"Вы недавно создавали вызов на дуэль. Вы сможете бросить следующий вызов <t:{ready_ts}:R> (<t:{ready_ts}:t>).\n"
                    f"*(Кулдаун между вызовами: {cd_min} мин.)*"
                    if lang != "en"
                    else (
                        f"⏳ **Challenge Cooldown!**\n"
                        f"You have recently created a duel challenge. You can challenge again <t:{ready_ts}:R> (<t:{ready_ts}:t>).\n"
                        f"*(Cooldown between challenges: {cd_min} min)*"
                    )
                )
                await interaction.response.send_message(msg, ephemeral=True)
                return

        # Защита от параллельных боев: проверяем, не идет ли уже активный матч между игроками
        active_duel = await asyncio.to_thread(self.db.has_active_accepted_challenge, interaction.user.id, user.id)
        if active_duel and not is_admin:
            msg = (
                "🚫 You already have an active ongoing duel with this player! Finish the current match or record its result via `/report` before challenging again."
                if lang == "en"
                else "🚫 У вас уже есть активная дуэль с этим игроком! Завершите текущий бой или внесите его результат через `/report` перед новым вызовом."
            )
            await interaction.response.send_message(msg, ephemeral=True)
            return

        # Защита от спама: проверяем, нет ли уже активного вызова
        pending = await asyncio.to_thread(self.db.get_pending_challenge, interaction.user.id, user.id)
        if pending:
            await interaction.response.send_message(locales.t("challenge_already_pending", lang), ephemeral=True)
            return

        rev_pending = await asyncio.to_thread(self.db.get_pending_challenge, user.id, interaction.user.id)
        if rev_pending:
            await interaction.response.send_message(locales.t("challenge_reverse_pending", lang), ephemeral=True)
            return

        chosen_format = format or "T2 - Main vs Main"
        chosen_server = server or "Hesse (Германия)"

        # Дедлайн ответа — ровно 24 часа по регламенту Лиги
        expires_dt = datetime.now(timezone.utc) + timedelta(hours=24)
        expire_ts = int(expires_dt.timestamp())

        # Чистая локализация формата и сервера для публичного эмбеда
        pub_format = locales.clean_format_name(chosen_format, lang)
        pub_server = locales.clean_server_name(chosen_server, lang)

        p1_data = await asyncio.to_thread(self.db.get_or_create_user, interaction.user.id)
        p2_data = await asyncio.to_thread(self.db.get_or_create_user, user.id)

        # Автоматическая синхронизация через Bloxlink, если ники еще не привязаны
        api_key = bloxlink.get_bloxlink_key(self.db)
        if api_key and interaction.guild_id:
            for uid, udata in ((interaction.user.id, p1_data), (user.id, p2_data)):
                if not udata.get("roblox_username"):
                    try:
                        res = await asyncio.to_thread(bloxlink.resolve_discord_to_roblox, interaction.guild_id, uid, api_key)
                        if res:
                            _, auto_name = res
                            udata["roblox_username"] = auto_name
                            await asyncio.to_thread(self.db.link_roblox, uid, auto_name)
                    except Exception:
                        pass

        # Проверка привязки Roblox у обоих участников вызова
        if not p1_data.get("roblox_username"):
            view = discord.ui.View()
            btn_lbl = "Verify on blox.link" if lang == "en" else "Пройти верификацию на blox.link"
            view.add_item(discord.ui.Button(label=btn_lbl, url="https://blox.link/verify", style=discord.ButtonStyle.link, emoji="🔗"))
            msg = (
                "⚠️ **Требуется привязка Roblox!**\n"
                "Чтобы бросать вызовы на дуэли, ваш аккаунт Roblox должен быть привязан.\n"
                "Используйте команду `/link`, чтобы синхронизировать свой профиль через Bloxlink."
                if lang != "en"
                else (
                    "⚠️ **Roblox Verification Required!**\n"
                    "To challenge players to duels, your Roblox account must be verified.\n"
                    "Use `/link` to sync your profile via Bloxlink."
                )
            )
            await interaction.response.send_message(msg, view=view, ephemeral=True)
            return

        if not p2_data.get("roblox_username"):
            msg = (
                f"⚠️ **Противник не привязал Roblox!**\n"
                f"Игрок {user.mention} ещё не привязал свой аккаунт Roblox.\n"
                f"Дуэли проводятся только между верифицированными игроками. Попросите его привязать аккаунт через `/link`."
                if lang != "en"
                else (
                    f"⚠️ **Opponent has not linked Roblox!**\n"
                    f"Player {user.mention} has not linked their Roblox account yet.\n"
                    f"Duels are only allowed between verified players. Ask them to use `/link`."
                )
            )
            await interaction.response.send_message(msg, ephemeral=True)
            return

        p1_pos = await asyncio.to_thread(self.db.get_user_rank_position, interaction.user.id)
        p2_pos = await asyncio.to_thread(self.db.get_user_rank_position, user.id)

        p1_rank = get_rank_info(p1_data["rating"], p1_data["rd"], p1_data["wins"] + p1_data["losses"], p1_pos, lang=lang)
        p2_rank = get_rank_info(p2_data["rating"], p2_data["rd"], p2_data["wins"] + p2_data["losses"], p2_pos, lang=lang)

        p1_rbx = p1_data.get("roblox_username") or ("not linked" if lang == "en" else "не привязан")
        p2_rbx = p2_data.get("roblox_username") or ("not linked" if lang == "en" else "не привязан")
        p1_flag = config.get_country_flag(p1_data.get("country"))
        p2_flag = config.get_country_flag(p2_data.get("country"))

        if lang == "en":
            challenge_desc = (
                f"### ⚔️ OFFICIAL 1v1 DUEL CHALLENGE\n"
                f"**{interaction.user.mention}** challenges **{user.mention}**!\n\n"
                f"🔴 **Initiator:** {p1_flag}{interaction.user.mention} (`{p1_rbx}`)\n"
                f"╰ **Rank:** {p1_rank['badge']} **{p1_rank['tier']}** • `{p1_rank['display']} ELO`\n\n"
                f"🔵 **Opponent:** {p2_flag}{user.mention} (`{p2_rbx}`)\n"
                f"╰ **Rank:** {p2_rank['badge']} **{p2_rank['tier']}** • `{p2_rank['display']} ELO`\n\n"
                f"⚙️ **Duel Settings:**\n"
                f"• Format: **`{pub_format}`**\n"
                f"• Server: **`{pub_server}`**\n"
                f"• Response Deadline: <t:{expire_ts}:R> (<t:{expire_ts}:t>)\n\n"
                f"⚠️ **League Rules:** The challenged player has **24 hours** to accept.\n"
                f"Declining without exemption or ignoring will automatically record a **Duck** status!"
            )
            challenge_footer_text = "GANGHUB League 1v1 • Click button below to respond"
        else:
            challenge_desc = (
                f"### ⚔️ ВЫЗОВ НА ОФИЦИАЛЬНУЮ ДУЭЛЬ 1v1\n"
                f"**{interaction.user.mention}** бросает вызов **{user.mention}**!\n\n"
                f"🔴 **Инициатор:** {p1_flag}{interaction.user.mention} (`{p1_rbx}`)\n"
                f"╰ **Ранг:** {p1_rank['badge']} **{p1_rank['tier']}** • `{p1_rank['display']} ELO`\n\n"
                f"🔵 **Соперник:** {p2_flag}{user.mention} (`{p2_rbx}`)\n"
                f"╰ **Ранг:** {p2_rank['badge']} **{p2_rank['tier']}** • `{p2_rank['display']} ELO`\n\n"
                f"⚙️ **Параметры дуэли:**\n"
                f"• Формат: **`{pub_format}`**\n"
                f"• Сервер: **`{pub_server}`**\n"
                f"• Дедлайн ответа: <t:{expire_ts}:R> (<t:{expire_ts}:t>)\n\n"
                f"⚠️ **Регламент Лиги:** У вызванного игрока есть **24 часа** на принятие вызова.\n"
                f"При отказе или игнорировании автоматически фиксируется статус **Duck (Дак)**!"
            )
            challenge_footer_text = "GANGHUB League 1v1 • Нажмите кнопку ниже для ответа"

        embed = discord.Embed(
            title=locales.t("challenge_title", lang),
            description=challenge_desc,
            color=discord.Color.gold()
        )
        if interaction.user.display_avatar:
            embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(text=challenge_footer_text)

        view = ChallengeView(
            bot=self.bot,
            db=self.db,
            challenger=interaction.user,
            challenged=user,
            lang=lang,
            match_format=chosen_format,
            match_server=chosen_server
        )

        fights_channel = await get_or_create_fights_channel(interaction.guild, self.db)

        msg = None
        target_chan_id = interaction.channel_id

        # 1. Если это Форум-канал (как на основном сервере find-your-enemy)
        if isinstance(fights_channel, discord.ForumChannel):
            t_name = f"⚔️・{p1_flag}{interaction.user.display_name[:10]} vs {p2_flag}{user.display_name[:10]}"[:100]
            thread_with_msg = await fights_channel.create_thread(
                name=t_name,
                content=f"{user.mention} {interaction.user.mention}",
                embed=embed,
                view=view,
                auto_archive_duration=1440
            )
            thread = thread_with_msg.thread
            msg = thread_with_msg.message
            target_chan_id = thread.id
            view.message = msg

            if lang == "en":
                confirm_txt = f"⚔️ Official duel post created in {fights_channel.mention}: {thread.mention}!"
            else:
                confirm_txt = f"⚔️ Официальная ветка дуэли создана в {fights_channel.mention}: {thread.mention}!"
            await interaction.response.send_message(confirm_txt, ephemeral=True)

        # 2. Обычный текстовый канал
        else:
            await interaction.response.send_message(content=user.mention, embed=embed, view=view)
            msg = await interaction.original_response()
            target_chan_id = interaction.channel_id
            view.message = msg

        try:
            view.message = msg

            # Сохраняем вызов в SQLite для постоянного фонового мониторинга
            cid = await asyncio.to_thread(
                self.db.create_challenge,
                guild_id=int(interaction.guild_id) if interaction.guild_id else 0,
                channel_id=int(target_chan_id) if target_chan_id else 0,
                message_id=int(msg.id) if msg else 0,
                challenger_id=int(interaction.user.id),
                challenged_id=int(user.id),
                format=chosen_format,
                server=chosen_server,
                expires_at=expires_dt
            )
            view.challenge_id = cid

            # Фиксируем время создания вызова для кулдауна
            self._challenge_cooldowns[interaction.user.id] = time.time()
            log.info(f"⚔️ [Вызов #{cid}] Создан вызов {interaction.user.id} -> {user.id} (ветка: {target_chan_id}, msg: {msg.id if msg else 0})")

            # Отправляем красивое оповещение в ЛС вызванному игроку
            guild_name = "GANGHUB"
            if interaction.guild and interaction.guild.name and interaction.guild.name.strip():
                guild_name = interaction.guild.name.strip()

            # Язык получателя: проверяем настройки в БД, затем язык клиента
            dm_lang = locales.get_user_lang(self.db, user.id, fallback=lang)
            dm_format = locales.clean_format_name(chosen_format, dm_lang)
            dm_server = locales.clean_server_name(chosen_server, dm_lang)
            challenger_text = f"{interaction.user.display_name} (@{interaction.user.name})"

            dm_embed = discord.Embed(
                title=locales.t("challenge_dm_title", dm_lang),
                description=locales.t(
                    "challenge_dm_desc",
                    dm_lang,
                    user=user.display_name,
                    challenger=challenger_text,
                    guild=guild_name,
                    format=dm_format,
                    server=dm_server,
                    expire_ts=expire_ts
                ),
                color=discord.Color.gold()
            )
            if interaction.user.display_avatar:
                dm_embed.set_thumbnail(url=interaction.user.display_avatar.url)
            dm_embed.set_footer(text=locales.t("challenge_dm_footer", dm_lang))

            dm_view = discord.ui.View(timeout=None)
            dm_view.add_item(discord.ui.Button(
                label=locales.t("challenge_dm_jump_btn", dm_lang),
                url=msg.jump_url,
                style=discord.ButtonStyle.link,
                emoji="⚔️"
            ))

            try:
                await user.send(embed=dm_embed, view=dm_view)
            except discord.Forbidden:
                pass
            except Exception as e:
                log.warning(f"⚠️ Не удалось доставить ЛС вызова для {user.display_name}: {e}")

        except Exception as e:
            log.error(f"⚠️ Ошибка при создании вызова: {e}")

    @app_commands.command(name="challenge_cancel", description="Отменить ваш активный отправленный вызов на дуэль")
    @app_commands.guild_only()
    async def challenge_cancel(self, interaction: discord.Interaction):
        lang = locales.get_lang(interaction)
        await interaction.response.defer(ephemeral=True)

        ch = await asyncio.to_thread(self.db.get_active_outgoing_challenge, interaction.user.id)
        is_accepted = False
        if not ch and interaction.channel_id:
            ch_candidate = await asyncio.to_thread(self.db.get_challenge_by_channel, interaction.channel_id)
            if ch_candidate and interaction.user.id in (ch_candidate["challenger_id"], ch_candidate["challenged_id"]):
                ch = ch_candidate
                is_accepted = True

        if not ch:
            msg = (
                "❌ You don't have any active outgoing duel challenges to cancel. To cancel an ongoing match, use `/match cancel`."
                if lang == "en"
                else "❌ У вас нет активных отправленных вызовов на дуэль для отмены. Для отмены текущей идущей дуэли используйте `/match cancel`."
            )
            await interaction.followup.send(msg, ephemeral=True)
            return

        # Обновляем статус в базе
        await asyncio.to_thread(self.db.update_challenge_status, ch["id"], "cancelled")
        if is_accepted:
            await asyncio.to_thread(self.db.release_league_vip_by_players, ch["challenger_id"], ch["challenged_id"])

        # Пытаемся обновить исходное сообщение в Discord
        try:
            chan_id = ch.get("channel_id")
            msg_id = ch.get("message_id")
            if chan_id and msg_id:
                chan = self.bot.get_channel(chan_id)
                if not chan:
                    chan = await self.bot.fetch_channel(chan_id)
                if chan:
                    msg = await chan.fetch_message(msg_id)
                    if msg:
                        disabled_view = discord.ui.View()
                        disabled_view.add_item(discord.ui.Button(
                            label="Отменен" if lang != "en" else "Cancelled",
                            style=discord.ButtonStyle.secondary,
                            disabled=True,
                            emoji="🚫"
                        ))
                        if msg.embeds:
                            orig_emb = msg.embeds[0]
                            emb_dict = orig_emb.to_dict()
                            emb_dict["color"] = discord.Color.dark_grey().value
                            emb_dict["title"] = "🚫 Вызов отменен • Challenge Cancelled" if lang != "en" else "🚫 Challenge Cancelled"
                            emb_dict["footer"] = {"text": "GANGHUB League • Статус: Отменен" if lang != "en" else "GANGHUB League • Status: Cancelled"}
                            emb_dict["description"] = (orig_emb.description or "") + (
                                f"\n\n🚫 **Вызов отменен {interaction.user.mention}.**"
                                if lang != "en"
                                else f"\n\n🚫 **Challenge was cancelled by {interaction.user.mention}.**"
                            )
                            await msg.edit(embed=discord.Embed.from_dict(emb_dict), view=disabled_view)
                        else:
                            await msg.edit(view=disabled_view)
        except Exception as e:
            log.warning(f"⚠️ Не удалось обновить сообщение отмененного вызова: {e}")

        opp_mention = f"<@{ch['challenged_id']}>"
        success_msg = (
            f"✅ Your duel challenge against {opp_mention} has been successfully cancelled."
            if lang == "en"
            else f"✅ Ваш вызов на дуэль против {opp_mention} был успешно отменен."
        )
        await interaction.followup.send(success_msg, ephemeral=True)

    @app_commands.command(name="formats", description="Справочник всех соревновательных форматов дуэлей 1v1 в GANGHUB")
    @app_commands.guild_only()
    async def formats(self, interaction: discord.Interaction):
        lang = locales.get_lang(interaction)
        embed = discord.Embed(
            title=locales.t("formats_guide_title", lang),
            description=locales.t("formats_guide_desc", lang),
            color=discord.Color.purple()
        )
        embed.set_footer(text="GangHub League 1v1 • Competitive Duels Rules" if lang == "en" else "GangHub League 1v1 • Регламент соревновательных дуэлей")
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    pass

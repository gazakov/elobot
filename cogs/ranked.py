import asyncio
import io
import re
import urllib.request
import json
import time
from datetime import datetime
from typing import Optional, Dict, Tuple, Any, List
import discord
from discord import app_commands
from discord.ext import commands, tasks
from database import Database
from ranks import get_rank_info
from config import (
    RANKS, SPECIAL_ROLES, RESP_ROLE_NAME,
    COUNTRIES, COUNTRY_COOLDOWN_DAYS, get_country_info, get_country_flag
)
import locales
import bloxlink

# Валидатор ников Roblox: строго 3-20 символов, буквы, цифры, подчёркивание
ROBLOX_USERNAME_REGEX = re.compile(r"^[a-zA-Z0-9_]{3,20}$")

_avatar_bytes_cache: Dict[str, Tuple[bytes, float]] = {}

def fetch_roblox_avatar_bytes(roblox_username: str) -> Optional[bytes]:
    """Запрашивает 3D Headshot аватарку игрока из Roblox и возвращает PNG байты с кэшированием"""
    username_clean = roblox_username.strip().lower()
    now = time.time()
    if username_clean in _avatar_bytes_cache:
        data, cached_at = _avatar_bytes_cache[username_clean]
        if now - cached_at < 3600.0:
            return data

    try:
        req = urllib.request.Request(
            "https://users.roblox.com/v1/usernames/users",
            data=json.dumps({"usernames": [roblox_username]}).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if not data.get("data"):
                return None
            user_id = data["data"][0]["id"]

        thumb_url = f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={user_id}&size=420x420&format=Png&isCircular=false"
        thumb_req = urllib.request.Request(thumb_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(thumb_req, timeout=3.5) as resp:
            thumb_data = json.loads(resp.read().decode("utf-8"))
            if not thumb_data.get("data") or not thumb_data["data"][0].get("imageUrl"):
                return None
            img_url = thumb_data["data"][0]["imageUrl"]

        img_req = urllib.request.Request(img_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(img_req, timeout=3.5) as resp:
            img_bytes = resp.read()
            if img_bytes and img_bytes[:4] == b'\x89PNG':
                _avatar_bytes_cache[username_clean] = (img_bytes, now)
                return img_bytes
    except Exception:
        return None
    return None


_full_avatar_bytes_cache: Dict[str, Tuple[bytes, Dict[str, Any], str, float]] = {}

def fetch_roblox_full_avatar_bytes(username_or_id: Any) -> Optional[Tuple[bytes, Dict[str, Any], str]]:
    """
    Запрашивает полноростовый 3D рендер скина (720x720) и метаданные пользователя Roblox с кэшированием.
    Возвращает (png_bytes, account_info, img_url) или None.
    """
    key = str(username_or_id).strip().lower()
    now = time.time()
    if key in _full_avatar_bytes_cache:
        data, info, url, cached_at = _full_avatar_bytes_cache[key]
        if now - cached_at < 3600.0:
            return data, info, url

    account_info = bloxlink.get_roblox_account_info(username_or_id)
    if not account_info:
        return None

    user_id = account_info["id"]
    try:
        thumb_url = f"https://thumbnails.roblox.com/v1/users/avatar?userIds={user_id}&size=720x720&format=Png&isCircular=false"
        thumb_req = urllib.request.Request(thumb_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(thumb_req, timeout=4.0) as resp:
            thumb_data = json.loads(resp.read().decode("utf-8"))
            if not thumb_data.get("data") or not thumb_data["data"][0].get("imageUrl"):
                return None
            img_url = thumb_data["data"][0]["imageUrl"]

        img_req = urllib.request.Request(img_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(img_req, timeout=4.0) as resp:
            img_bytes = resp.read()
            if img_bytes and img_bytes[:4] == b'\x89PNG':
                _full_avatar_bytes_cache[key] = (img_bytes, account_info, img_url, now)
                _full_avatar_bytes_cache[str(user_id)] = (img_bytes, account_info, img_url, now)
                _full_avatar_bytes_cache[account_info["username"].lower()] = (img_bytes, account_info, img_url, now)
                return img_bytes, account_info, img_url
    except Exception:
        return None
    return None

_avatar_url_cache: Dict[str, Tuple[str, float]] = {}

def fetch_roblox_avatar_url(roblox_username: str) -> Optional[str]:
    """Возвращает прямой URL 3D Headshot аватарки игрока из Roblox с кэшированием"""
    username_clean = roblox_username.strip().lower()
    now = time.time()
    if username_clean in _avatar_url_cache:
        cached_url, cached_at = _avatar_url_cache[username_clean]
        if now - cached_at < 3600.0:
            return cached_url

    try:
        req = urllib.request.Request(
            "https://users.roblox.com/v1/usernames/users",
            data=json.dumps({"usernames": [roblox_username]}).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if not data.get("data"):
                return None
            user_id = data["data"][0]["id"]

        thumb_url = f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={user_id}&size=420x420&format=Png&isCircular=false"
        thumb_req = urllib.request.Request(thumb_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(thumb_req, timeout=3.5) as resp:
            thumb_data = json.loads(resp.read().decode("utf-8"))
            if thumb_data.get("data"):
                img_url = thumb_data["data"][0].get("imageUrl")
                if img_url:
                    _avatar_url_cache[username_clean] = (img_url, now)
                    return img_url
    except Exception:
        return None
    return None


class RulesSelect(discord.ui.Select):
    def __init__(self, lang: str):
        self.lang = lang
        options = [
            discord.SelectOption(
                label=locales.t("rules_menu_overview", lang),
                value="overview",
                description="T1/T2/T3, баны, подсады и основы регламента" if lang == "ru" else "Overview, T1/T2/T3, bans and basics",
                emoji="📌",
                default=True
            ),
            discord.SelectOption(
                label=locales.t("rules_cat_bans_title", lang),
                value="bans",
                description="Ран 8+ сек, читы, спеклесс, брокен связки" if lang == "ru" else "8s running, cheats, specless, broken builds",
                emoji="🚫"
            ),
            discord.SelectOption(
                label=locales.t("rules_cat_formats_title", lang),
                value="formats",
                description="Any vs Any, Main vs Main, баны ультимейтов" if lang == "ru" else "Any vs Any, Main vs Main, ultimate bans",
                emoji="⚔️"
            ),
            discord.SelectOption(
                label=locales.t("rules_cat_stands_title", lang),
                value="stands",
                description="Лимиты GER (2 хила), KCR демон/бокс, KDR" if lang == "ru" else "GER heal cap, KCR demon/box, KDR",
                emoji="⚖️"
            ),
            discord.SelectOption(
                label=locales.t("rules_cat_checks_title", lang),
                value="checks",
                description="Демка аккаунтов/устройств, Hesse/Holland, клипы" if lang == "ru" else "Screen share check, Hesse/Holland, clips",
                emoji="🕵️"
            ),
            discord.SelectOption(
                label=locales.t("rules_cat_duck_title", lang),
                value="duck",
                description="24ч ответ, 3 дня кд, Duck Evade, топ-1 стенды" if lang == "ru" else "24h reply, 3d CD, Duck Evade, top-1 roles",
                emoji="🦆"
            ),
        ]
        super().__init__(
            placeholder=locales.t("rules_menu_placeholder", lang),
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0]
        for opt in self.options:
            opt.default = (opt.value == selected)

        lang = self.lang
        color = discord.Color.gold()
        if selected == "overview":
            title = locales.t("rules_title", lang)
            desc = locales.t("rules_overview_desc", lang)
        elif selected == "bans":
            title = f"{locales.t('rules_title', lang)} • {locales.t('rules_cat_bans_title', lang)}"
            desc = locales.t("rules_cat_bans_desc", lang)
            color = discord.Color.red()
        elif selected == "formats":
            title = f"{locales.t('rules_title', lang)} • {locales.t('rules_cat_formats_title', lang)}"
            desc = locales.t("rules_cat_formats_desc", lang)
            color = discord.Color.purple()
        elif selected == "stands":
            title = f"{locales.t('rules_title', lang)} • {locales.t('rules_cat_stands_title', lang)}"
            desc = locales.t("rules_cat_stands_desc", lang)
            color = discord.Color.blue()
        elif selected == "checks":
            title = f"{locales.t('rules_title', lang)} • {locales.t('rules_cat_checks_title', lang)}"
            desc = locales.t("rules_cat_checks_desc", lang)
            color = discord.Color.dark_teal()
        elif selected == "duck":
            title = f"{locales.t('rules_title', lang)} • {locales.t('rules_cat_duck_title', lang)}"
            desc = locales.t("rules_cat_duck_desc", lang)
            color = discord.Color.orange()
        else:
            title = locales.t("rules_title", lang)
            desc = locales.t("rules_overview_desc", lang)

        embed = discord.Embed(title=title, description=desc, color=color)
        embed.set_footer(text="GangHub League 1v1 • Glicko-2")
        await interaction.response.edit_message(embed=embed, view=self.view)


class RulesView(discord.ui.View):
    def __init__(self, lang: str, author_id: Optional[int] = None):
        super().__init__(timeout=300.0)
        self.lang = lang
        self.author_id = author_id
        self.message = None
        self.add_item(RulesSelect(lang))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.author_id and interaction.user.id != self.author_id:
            msg = (
                "❌ Only the player who called `/rules` can switch menu pages! Use `/rules` yourself to view other sections."
                if self.lang == "en"
                else "❌ Менять разделы правил может только тот, кто вызвал команду! Напишите `/rules`, чтобы открыть своё меню."
            )
            await interaction.response.send_message(msg, ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


class CountryConfirmView(discord.ui.View):
    def __init__(self, cog, db, user_id: int, country_code: str, lang: str):
        super().__init__(timeout=60.0)
        self.cog = cog
        self.db = db
        self.user_id = user_id
        self.country_code = country_code
        self.lang = lang

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Это не ваша кнопка!" if self.lang != "en" else "❌ This button is not for you!", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Подтвердить", style=discord.ButtonStyle.green, emoji="✅")
    async def btn_confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        success, msg = await asyncio.to_thread(self.db.set_user_country, self.user_id, self.country_code, COUNTRY_COOLDOWN_DAYS)
        c_info = get_country_info(self.country_code)
        c_name = c_info["name_ru" if self.lang != "en" else "name_en"] if c_info else self.country_code
        c_flag = c_info["flag"] if c_info else ""

        if not success:
            days = msg.split(":")[1] if ":" in msg else "30"
            err_text = locales.t("country_cooldown_error", self.lang, days=days)
            await interaction.response.edit_message(content=err_text, embed=None, view=None)
            return

        ok_text = locales.t("country_success", self.lang, flag=c_flag, name=c_name)
        await interaction.response.edit_message(content=ok_text, embed=None, view=None)

    @discord.ui.button(label="Отмена", style=discord.ButtonStyle.grey, emoji="❌")
    async def btn_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        cancel_text = locales.t("country_cancelled", self.lang)
        await interaction.response.edit_message(content=cancel_text, embed=None, view=None)



class LeaderboardView(discord.ui.View):
    def __init__(self, cog: Any, db: Database, page: int, total_pages: int, lang: str, caller_id: int):
        super().__init__(timeout=120.0)
        self.cog = cog
        self.db = db
        self.page = page
        self.total_pages = max(1, total_pages)
        self.lang = lang
        self.caller_id = caller_id
        self.message: Optional[discord.Message] = None
        self._update_buttons()

    def _update_buttons(self):
        self.clear_items()

        # Кнопка "Назад"
        btn_prev = discord.ui.Button(
            label="Пред." if self.lang != "en" else "Prev",
            style=discord.ButtonStyle.secondary,
            emoji="◀️",
            disabled=(self.page <= 1)
        )
        btn_prev.callback = self._make_page_callback(-1)
        self.add_item(btn_prev)

        # Индикатор страницы
        page_indicator = discord.ui.Button(
            label=f"{self.page} / {self.total_pages}",
            style=discord.ButtonStyle.primary,
            disabled=True
        )
        self.add_item(page_indicator)

        # Кнопка "Вперед"
        btn_next = discord.ui.Button(
            label="След." if self.lang != "en" else "Next",
            style=discord.ButtonStyle.secondary,
            emoji="▶️",
            disabled=(self.page >= self.total_pages)
        )
        btn_next.callback = self._make_page_callback(1)
        self.add_item(btn_next)

    def _make_page_callback(self, delta: int):
        async def cb(interaction: discord.Interaction):
            if interaction.user.id != self.caller_id:
                msg = (
                    "❌ Only the player who requested `/leaderboard` can use pagination! Use `/leaderboard` yourself."
                    if self.lang == "en"
                    else "❌ Переключать страницы топа может только тот, кто вызвал команду! Напишите `/leaderboard`, чтобы открыть своё меню."
                )
                await interaction.response.send_message(msg, ephemeral=True)
                return

            self.page = max(1, min(self.page + delta, self.total_pages))
            self._update_buttons()
            embed = await self.cog._build_leaderboard_embed(self.page, self.lang)
            await interaction.response.edit_message(embed=embed, view=self)
        return cb

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


class ProfileEditModal(discord.ui.Modal):
    def __init__(self, db: Database, lang: str, current_gang: str = "", current_bio: str = "", current_alts: str = ""):
        super().__init__(title=locales.t("profile_edit_modal_title", lang)[:45])
        self.db = db
        self.lang = lang

        self.gang_input = discord.ui.TextInput(
            label=locales.t("profile_modal_gang_label", lang)[:45],
            placeholder=locales.t("profile_modal_gang_placeholder", lang)[:100],
            default=current_gang or "",
            required=False,
            max_length=32
        )
        self.add_item(self.gang_input)

        self.bio_input = discord.ui.TextInput(
            label=locales.t("profile_modal_bio_label", lang)[:45],
            style=discord.TextStyle.paragraph,
            placeholder=locales.t("profile_modal_bio_placeholder", lang)[:100],
            default=current_bio or "",
            required=False,
            max_length=400
        )
        self.add_item(self.bio_input)

        self.alts_input = discord.ui.TextInput(
            label=locales.t("profile_modal_alts_label", lang)[:45],
            placeholder=locales.t("profile_modal_alts_placeholder", lang)[:100],
            default=current_alts or "",
            required=False,
            max_length=150
        )
        self.add_item(self.alts_input)

    async def on_submit(self, interaction: discord.Interaction):
        clean_gang = re.sub(r"[\r\n\t]+", " ", self.gang_input.value.strip())[:32].strip() if self.gang_input.value else None
        clean_bio = self.bio_input.value.strip()[:400] if self.bio_input.value else None
        clean_alts = re.sub(r"[\r\n\t]+", " ", self.alts_input.value.strip())[:150].strip() if self.alts_input.value else None

        if clean_gang:
            clean_gang = discord.utils.escape_mentions(clean_gang)
        if clean_bio:
            clean_bio = discord.utils.escape_mentions(clean_bio)
        if clean_alts:
            clean_alts = discord.utils.escape_mentions(clean_alts).replace("\\_", "_")

        await asyncio.to_thread(
            self.db.update_user_profile_details,
            interaction.user.id,
            clean_gang,
            clean_bio,
            clean_alts
        )

        embed = discord.Embed(
            title=locales.t("profile_modal_success", self.lang),
            color=discord.Color.green()
        )
        desc_parts = []
        if clean_gang:
            desc_parts.append(f"**{locales.t('profile_gang_field', self.lang)}:** {clean_gang}")
        if clean_alts:
            desc_parts.append(f"**{locales.t('profile_alts_field', self.lang)}:** `{clean_alts}`")
        if clean_bio:
            quoted = "\n".join(f"> {l}" for l in clean_bio.splitlines() if l.strip())
            desc_parts.append(f"**{locales.t('profile_bio_field', self.lang)}:**\n{quoted}")
        if not desc_parts:
            desc_parts.append("*(All extra profile fields cleared)*" if self.lang == "en" else "*(Все дополнительные поля профиля очищены)*")

        embed.description = "\n\n".join(desc_parts)
        embed.set_footer(text="GangHub League 1v1 • Profile Saved")
        await interaction.response.send_message(embed=embed, ephemeral=True)


class ProfileView(discord.ui.View):
    def __init__(
        self,
        bot: commands.Bot,
        db: Database,
        cog: Any,
        target_user: discord.Member,
        lang: str,
        roblox_url: Optional[str] = None,
        is_owner: bool = True,
        current_tab: str = "yba",
        has_roblox: bool = True,
        caller_id: Optional[int] = None
    ):
        super().__init__(timeout=180.0)
        self.bot = bot
        self.db = db
        self.cog = cog
        self.target_user = target_user
        self.lang = lang
        self.roblox_url = roblox_url
        self.is_owner = is_owner
        self.current_tab = current_tab
        self.has_roblox = has_roblox
        self.caller_id = caller_id
        self._setup_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        custom_id = ""
        if interaction.data and isinstance(interaction.data, dict):
            custom_id = interaction.data.get("custom_id", "")

        # 1. Лайки и дизлайки (+Rep / -Rep) могут нажимать ДРУГИЕ пользователи
        if custom_id in ("profile_rep_like", "profile_rep_dislike"):
            if interaction.user.id == self.target_user.id:
                err = "❌ You cannot change reputation of yourself!" if self.lang == "en" else "❌ Вы не можете менять репутацию самому себе!"
                await interaction.response.send_message(err, ephemeral=True)
                return False
            return True

        # 2. Кнопка "Редактировать профиль" — только владелец профиля
        if custom_id == "profile_edit_btn":
            if interaction.user.id != self.target_user.id:
                err = locales.t("profile_edit_not_owner", self.lang)
                await interaction.response.send_message(err, ephemeral=True)
                return False
            return True

        # 3. Вкладки "ЮБА" и "Дискорд" — чужие люди нажимать НЕ могут! Только тот, кто вызвал /profile
        if self.caller_id and interaction.user.id != self.caller_id:
            msg = (
                "❌ Only the player who called `/profile` can switch tabs! Use `/profile` yourself to open your own view."
                if self.lang == "en"
                else "❌ Переключать вкладки профиля может только тот, кто вызвал команду! Напишите `/profile`, чтобы открыть своё меню."
            )
            await interaction.response.send_message(msg, ephemeral=True)
            return False

        return True

    def _setup_buttons(self):
        self.clear_items()

        yba_style = discord.ButtonStyle.primary if self.current_tab in ("yba", "unlinked") else discord.ButtonStyle.secondary
        discord_style = discord.ButtonStyle.primary if self.current_tab == "discord" else discord.ButtonStyle.secondary

        btn_yba_label = "YBA ⚔️" if self.lang == "en" else "ЮБА ⚔️"
        btn_discord_label = "Discord 💬" if self.lang == "en" else "Дискорд 💬"

        # Вкладки навигации (строка 0)
        btn_yba = discord.ui.Button(label=btn_yba_label, style=yba_style, custom_id="profile_tab_yba", row=0)
        btn_yba.callback = self.tab_yba_callback
        self.add_item(btn_yba)

        btn_discord = discord.ui.Button(label=btn_discord_label, style=discord_style, custom_id="profile_tab_discord", row=0)
        btn_discord.callback = self.tab_discord_callback
        self.add_item(btn_discord)

        if self.current_tab in ("yba", "unlinked"):
            if not self.has_roblox:
                if self.is_owner:
                    btn_verify_label = "Verify Roblox" if self.lang == "en" else "Привязать Roblox"
                    self.add_item(discord.ui.Button(label=btn_verify_label, url="https://blox.link/verify", style=discord.ButtonStyle.link, emoji="🔗", row=0))
            else:
                if self.is_owner:
                    btn_label = locales.t("profile_edit_btn", self.lang)
                    edit_btn = discord.ui.Button(label=btn_label, style=discord.ButtonStyle.secondary, emoji="✏️", custom_id="profile_edit_btn", row=0)
                    edit_btn.callback = self.edit_profile_callback
                    self.add_item(edit_btn)

                if self.roblox_url:
                    self.add_item(discord.ui.Button(label="Roblox", url=self.roblox_url, style=discord.ButtonStyle.link, emoji="🔗", row=0))

        # Кнопки репутации (+Rep и -Rep) доступны всегда во 2-й строке для любых пользователей
        btn_like = discord.ui.Button(label="+Rep", style=discord.ButtonStyle.success, emoji="👍", custom_id="profile_rep_like", row=1)
        btn_like.callback = self.rep_like_callback
        self.add_item(btn_like)

        btn_dislike = discord.ui.Button(label="-Rep", style=discord.ButtonStyle.danger, emoji="👎", custom_id="profile_rep_dislike", row=1)
        btn_dislike.callback = self.rep_dislike_callback
        self.add_item(btn_dislike)

    async def tab_yba_callback(self, interaction: discord.Interaction):
        if not self.has_roblox:
            if self.current_tab in ("yba", "unlinked"):
                await interaction.response.defer()
                return
            self.current_tab = "unlinked"
            self._setup_buttons()
            embed = self.cog.build_unlinked_embed(self.target_user, self.lang, is_owner=self.is_owner)
            await interaction.response.edit_message(embed=embed, view=self, attachments=[])
            return

        if self.current_tab == "yba":
            await interaction.response.defer()
            return
        self.current_tab = "yba"
        self._setup_buttons()
        embed, _, _ = await self.cog.build_yba_embed(self.target_user, self.lang)
        await interaction.response.edit_message(embed=embed, view=self, attachments=[])

    async def tab_discord_callback(self, interaction: discord.Interaction):
        if self.current_tab == "discord":
            await interaction.response.defer()
            return
        self.current_tab = "discord"
        self._setup_buttons()
        embed = await self.cog.build_discord_embed(self.target_user, self.lang, has_roblox=self.has_roblox, is_owner=self.is_owner)
        await interaction.response.edit_message(embed=embed, view=self, attachments=[])

    async def rep_like_callback(self, interaction: discord.Interaction):
        if interaction.user.id == self.target_user.id:
            err = "❌ You cannot change reputation of yourself!" if self.lang == "en" else "❌ Вы не можете менять репутацию самому себе!"
            await interaction.response.send_message(err, ephemeral=True)
            return

        ok, msg, rep_data = await asyncio.to_thread(self.db.vote_reputation, interaction.user.id, self.target_user.id, 1)
        if not ok:
            err = "⚠️ You have already given +Rep (like) to this user!" if self.lang == "en" else msg
            await interaction.response.send_message(err, ephemeral=True)
            return

        # Обновляем эмбед на актуальный
        if self.current_tab == "discord":
            embed = await self.cog.build_discord_embed(self.target_user, self.lang, has_roblox=self.has_roblox, is_owner=self.is_owner)
            await interaction.response.edit_message(embed=embed, view=self, attachments=[])
        elif self.current_tab == "yba":
            embed, _, _ = await self.cog.build_yba_embed(self.target_user, self.lang)
            await interaction.response.edit_message(embed=embed, view=self, attachments=[])
        else:
            embed = self.cog.build_unlinked_embed(self.target_user, self.lang, is_owner=self.is_owner)
            await interaction.response.edit_message(embed=embed, view=self, attachments=[])

        sign = f"+{rep_data['rep']}" if rep_data['rep'] > 0 else str(rep_data['rep'])
        if self.lang == "en":
            await interaction.followup.send(
                f"✅ Successfully given **+Rep (like)**!\n{self.target_user.mention}'s reputation: **{sign}** (+{rep_data['likes']} / -{rep_data['dislikes']})",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                f"{msg}\nРепутация {self.target_user.mention}: **{sign}** (+{rep_data['likes']} / -{rep_data['dislikes']})",
                ephemeral=True
            )

    async def rep_dislike_callback(self, interaction: discord.Interaction):
        if interaction.user.id == self.target_user.id:
            err = "❌ You cannot change reputation of yourself!" if self.lang == "en" else "❌ Вы не можете менять репутацию самому себе!"
            await interaction.response.send_message(err, ephemeral=True)
            return

        ok, msg, rep_data = await asyncio.to_thread(self.db.vote_reputation, interaction.user.id, self.target_user.id, -1)
        if not ok:
            err = "⚠️ You have already given -Rep (dislike) to this user!" if self.lang == "en" else msg
            await interaction.response.send_message(err, ephemeral=True)
            return

        # Обновляем эмбед на актуальный
        if self.current_tab == "discord":
            embed = await self.cog.build_discord_embed(self.target_user, self.lang, has_roblox=self.has_roblox, is_owner=self.is_owner)
            await interaction.response.edit_message(embed=embed, view=self, attachments=[])
        elif self.current_tab == "yba":
            embed, _, _ = await self.cog.build_yba_embed(self.target_user, self.lang)
            await interaction.response.edit_message(embed=embed, view=self, attachments=[])
        else:
            embed = self.cog.build_unlinked_embed(self.target_user, self.lang, is_owner=self.is_owner)
            await interaction.response.edit_message(embed=embed, view=self, attachments=[])

        sign = f"+{rep_data['rep']}" if rep_data['rep'] > 0 else str(rep_data['rep'])
        if self.lang == "en":
            await interaction.followup.send(
                f"✅ Successfully given **-Rep (dislike)**!\n{self.target_user.mention}'s reputation: **{sign}** (+{rep_data['likes']} / -{rep_data['dislikes']})",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                f"{msg}\nРепутация {self.target_user.mention}: **{sign}** (+{rep_data['likes']} / -{rep_data['dislikes']})",
                ephemeral=True
            )

    async def edit_profile_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.target_user.id:
            await interaction.response.send_message(locales.t("profile_edit_not_owner", self.lang), ephemeral=True)
            return

        u_data = await asyncio.to_thread(self.db.get_or_create_user, interaction.user.id)
        modal = ProfileEditModal(
            db=self.db,
            lang=self.lang,
            current_gang=u_data.get("gang") or "",
            current_bio=u_data.get("bio") or "",
            current_alts=u_data.get("alts") or ""
        )
        await interaction.response.send_modal(modal)


def is_voice_active(voice_state: Optional[discord.VoiceState]) -> bool:
    """
    Проверяет, что участник действительно активен в голосовом канале с ВКЛЮЧЕННЫМ микрофоном:
    - Находится в голосовом канале (channel is not None)
    - Не в AFK-канале (afk is False)
    - Микрофон включен (не заглушен пользователем self_mute и не заглушен сервером mute)
    - Наушники/звук включены (не задефанен пользователем self_deaf и не задефанен сервером deaf)
    - Не заглушен на трибуне (suppress is False)
    """
    if not voice_state or not getattr(voice_state, "channel", None):
        return False

    if getattr(voice_state, "afk", False):
        return False

    channel = voice_state.channel
    guild = getattr(channel, "guild", None)
    if guild and getattr(guild, "afk_channel_id", None) and channel.id == guild.afk_channel_id:
        return False

    # Микрофон выключен (самим пользователем или сервером)
    if getattr(voice_state, "self_mute", False) or getattr(voice_state, "mute", False):
        return False

    # Наушники/звук выключены (дефен)
    if getattr(voice_state, "self_deaf", False) or getattr(voice_state, "deaf", False):
        return False

    # Заглушен на трибуне (Stage channel listener)
    if getattr(voice_state, "suppress", False):
        return False

    return True


class RankedCog(commands.Cog):
    def __init__(self, bot: commands.Bot, db: Database):
        self.bot = bot
        self.db = db
        self._voice_sessions: Dict[int, float] = {}
        self._rep_cooldowns: Dict[int, float] = {}

    async def cog_load(self):
        self.voice_tracker_task.start()

    def cog_unload(self):
        self.voice_tracker_task.cancel()
        # При выгрузке кога сохраняем время всех текущих активных сессий в БД
        now = time.time()
        for member_id, start_ts in list(self._voice_sessions.items()):
            elapsed = now - start_ts
            if elapsed >= 1.0:
                try:
                    self.db.add_voice_seconds(member_id, elapsed)
                except Exception:
                    pass
        self._voice_sessions.clear()

    @tasks.loop(seconds=15)
    async def voice_tracker_task(self):
        """
        Фоновый цикл: каждые 15 секунд сохраняет набежавшее время участников с ВКЛЮЧЕННЫМ микрофоном.
        Гарантирует, что при перезапуске или краше бота ни одна минута войса не пропадет.
        """
        if not self.bot.is_ready():
            return
        try:
            now = time.time()
            active_member_ids = set()
            for guild in self.bot.guilds:
                channels = list(guild.voice_channels)
                if hasattr(guild, "stage_channels"):
                    channels.extend(guild.stage_channels)
                for vc in channels:
                    if getattr(guild, "afk_channel_id", None) and vc.id == guild.afk_channel_id:
                        continue
                    for member in vc.members:
                        if member.bot:
                            continue
                        if is_voice_active(member.voice):
                            active_member_ids.add(member.id)
                            start_ts = self._voice_sessions.get(member.id)
                            if start_ts is not None:
                                elapsed = now - start_ts
                                if elapsed >= 1.0:
                                    await asyncio.to_thread(self.db.add_voice_seconds, member.id, elapsed)
                            self._voice_sessions[member.id] = now

            # Закрываем сессии тех, кто больше не активен с микрофоном (вышел / замьютился / задефался)
            for member_id in list(self._voice_sessions.keys()):
                if member_id not in active_member_ids:
                    start_ts = self._voice_sessions.pop(member_id, None)
                    if start_ts is not None:
                        elapsed = now - start_ts
                        if elapsed >= 1.0:
                            await asyncio.to_thread(self.db.add_voice_seconds, member_id, elapsed)
        except Exception:
            pass

    @voice_tracker_task.before_loop
    async def before_voice_tracker(self):
        try:
            await self.bot.wait_until_ready()
        except RuntimeError:
            return
        # Инициализация сессий только для тех, кто прямо сейчас в войсе с ВКЛЮЧЕННЫМ микрофоном
        now = time.time()
        for guild in self.bot.guilds:
            channels = list(guild.voice_channels)
            if hasattr(guild, "stage_channels"):
                channels.extend(guild.stage_channels)
            for vc in channels:
                if getattr(guild, "afk_channel_id", None) and vc.id == guild.afk_channel_id:
                    continue
                for member in vc.members:
                    if not member.bot and is_voice_active(member.voice):
                        self._voice_sessions[member.id] = now

    @voice_tracker_task.error
    async def voice_tracker_error(self, error: Exception):
        pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        try:
            await asyncio.to_thread(self.db.increment_message_count, message.author.id)
        except Exception:
            pass

        # Быстрые команды репутации: +rep @User / -rep @User / +реп @User / -реп @User
        raw = message.content.strip().lower()
        if raw.startswith(("+rep", "-rep", "+реп", "-реп")) and message.mentions:
            target = message.mentions[0]
            if not target.bot and target.id != message.author.id:
                now = time.time()
                last_rep = self._rep_cooldowns.get(message.author.id, 0.0)
                if now - last_rep >= 15.0:
                    vote = 1 if raw.startswith(("+rep", "+реп")) else -1
                    ok, msg, rep_data = await asyncio.to_thread(self.db.vote_reputation, message.author.id, target.id, vote)
                    if ok:
                        self._rep_cooldowns[message.author.id] = now
                        score = rep_data["rep"]
                        sign = f"+{score}" if score > 0 else str(score)
                        color = discord.Color.green() if vote > 0 else discord.Color.red()
                        emoji = "📈" if vote > 0 else "📉"
                        action_title = "+Rep" if vote > 0 else "-Rep"
                        embed = discord.Embed(
                            title=f"{emoji} Репутация: {action_title}",
                            description=(
                                f"{message.author.mention} поставил **{action_title}** игроку {target.mention}!\n\n"
                                f"📊 **Текущая репутация:** `{sign}` (👍 `+{rep_data['likes']}` / 👎 `-{rep_data['dislikes']}`)"
                            ),
                            color=color
                        )
                        embed.set_thumbnail(url=target.display_avatar.url)
                        embed.set_footer(text="GANGHUB Community Reputation")
                        try:
                            await message.reply(embed=embed)
                        except Exception:
                            pass

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return
        try:
            now = time.time()
            was_active = is_voice_active(before)
            is_active = is_voice_active(after)

            if was_active and not is_active:
                # Микрофон был выключен (замьютился, задефался, вышел из войса, перешел в AFK)
                start_ts = self._voice_sessions.pop(member.id, None)
                if start_ts is not None:
                    elapsed = now - start_ts
                    if elapsed >= 1.0:
                        await asyncio.to_thread(self.db.add_voice_seconds, member.id, elapsed)
            elif not was_active and is_active:
                # Микрофон был включен (размьютился, снял дефен, зашел в войс с включенным микрофоном)
                self._voice_sessions[member.id] = now
            elif was_active and is_active:
                # Пользователь остался с включенным микрофоном (например, сменил канал)
                start_ts = self._voice_sessions.get(member.id)
                if start_ts is not None:
                    elapsed = now - start_ts
                    if elapsed >= 1.0:
                        await asyncio.to_thread(self.db.add_voice_seconds, member.id, elapsed)
                self._voice_sessions[member.id] = now
            else:
                # Был неактивен и остался неактивен
                self._voice_sessions.pop(member.id, None)
        except Exception:
            pass

    @app_commands.command(name="link", description="Синхронизировать свой верифицированный аккаунт Roblox через Bloxlink")
    @app_commands.describe(roblox_username="Твой ник в Roblox (если у тебя несколько аккаунтов в Bloxlink)")
    @app_commands.guild_only()
    async def link(self, interaction: discord.Interaction, roblox_username: Optional[str] = None):
        lang = locales.get_lang(interaction)
        api_key = bloxlink.get_bloxlink_key(self.db)
        if not api_key:
            await interaction.response.send_message(locales.t("bloxlink_status_inactive", lang), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        # 1. Если передан конкретный никнейм — строго проверяем через Bloxlink именно его
        if roblox_username and roblox_username.strip():
            clean_name = roblox_username.strip().lstrip("@")
            acc_info = await asyncio.to_thread(bloxlink.get_roblox_account_info, clean_name)
            if not acc_info:
                err_msg = (
                    f"❌ Roblox-аккаунт с ником **@{clean_name}** не существует в Roblox!"
                    if lang != "en"
                    else f"❌ Roblox account **@{clean_name}** does not exist in Roblox!"
                )
                await interaction.followup.send(err_msg, ephemeral=True)
                return

            real_username = acc_info["username"]
            roblox_id = acc_info["id"]

            # Проверяем через Bloxlink: привязан ли этот roblox_id к данному Discord ID
            # Проверка А: прямой поиск в Bloxlink (если это основной аккаунт)
            primary_res = await asyncio.to_thread(bloxlink.resolve_discord_to_roblox, interaction.guild_id, interaction.user.id, api_key)
            is_verified = False
            if primary_res and (primary_res[0] == roblox_id or primary_res[1].lower() == real_username.lower()):
                is_verified = True

            # Проверка Б: обратный поиск Bloxlink (если аккаунт привязан на blox.link вторым/третьим)
            if not is_verified:
                linked_discord_ids = await asyncio.to_thread(bloxlink.resolve_roblox_to_discord, interaction.guild_id, roblox_id, api_key)
                if interaction.user.id in linked_discord_ids:
                    is_verified = True

            if not is_verified:
                err_msg = (
                    f"❌ **Bloxlink не подтверждает владение аккаунтом @{real_username}!**\n\n"
                    f"В Лиге GANGHUB все аккаунты строго проверяются через Bloxlink для защиты от подсадов и фейков.\n\n"
                    f"**Чтобы подтвердить этот аккаунт в Bloxlink:**\n"
                    f"1. Зайди на [blox.link](https://blox.link) и нажми на звёздочку рядом с **{real_username}**, чтобы сделать его основным (**Primary ⭐**).\n"
                    f"2. На этом сервере Discord напиши боту Bloxlink команду: `/verify`.\n"
                    f"3. После этого пропиши `/link` снова!"
                    if lang != "en"
                    else f"❌ **Bloxlink does not confirm ownership of @{real_username}!**\n\n"
                         f"In GANGHUB League, all accounts must be strictly verified via Bloxlink.\n\n"
                         f"**To verify this account via Bloxlink:**\n"
                         f"1. Go to [blox.link](https://blox.link) and star **{real_username}** as your **Primary ⭐** account.\n"
                         f"2. On this Discord server, run Bloxlink's command: `/verify`.\n"
                         f"3. Run `/link` again!"
                )
                view = discord.ui.View()
                btn_lbl = "Verify on blox.link" if lang == "en" else "Открыть blox.link"
                view.add_item(discord.ui.Button(label=btn_lbl, url="https://blox.link/verify", style=discord.ButtonStyle.link, emoji="🔗"))
                await interaction.followup.send(err_msg, view=view, ephemeral=True)
                return

            # Аккаунт строго подтвержден через Bloxlink
            try:
                await asyncio.to_thread(self.db.link_roblox, interaction.user.id, real_username)
            except ValueError as e:
                await interaction.followup.send(f"❌ {e}", ephemeral=True)
                return

            embed = discord.Embed(
                title=locales.t("link_success_title", lang),
                description=locales.t("link_auto_success", lang, username=real_username),
                color=discord.Color.green()
            )
            embed.set_thumbnail(url=f"https://www.roblox.com/headshot-thumbnail/image?userId={roblox_id}&width=150&height=150&format=png")
            embed.set_footer(text="GANGHUB League • Bloxlink Verified")
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # 2. Если никнейм не указан — запрашиваем основной аккаунт игрока из Bloxlink
        res = await asyncio.to_thread(bloxlink.resolve_discord_to_roblox, interaction.guild_id, interaction.user.id, api_key)
        if not res:
            view = discord.ui.View()
            btn_lbl = "Verify on blox.link" if lang == "en" else "Пройти верификацию на blox.link"
            view.add_item(discord.ui.Button(label=btn_lbl, url="https://blox.link/verify", style=discord.ButtonStyle.link, emoji="🔗"))
            await interaction.followup.send(locales.t("link_not_in_bloxlink", lang), view=view, ephemeral=True)
            return

        roblox_id, roblox_name = res
        try:
            await asyncio.to_thread(self.db.link_roblox, interaction.user.id, roblox_name)
        except ValueError as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)
            return

        embed = discord.Embed(
            title=locales.t("link_success_title", lang),
            description=locales.t("link_auto_success", lang, username=roblox_name),
            color=discord.Color.green()
        )
        embed.set_thumbnail(url=f"https://www.roblox.com/headshot-thumbnail/image?userId={roblox_id}&width=150&height=150&format=png")
        embed.set_footer(text="GANGHUB League • Bloxlink Verified")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="unlink", description="Отвязать свой аккаунт Roblox от профиля Лиги")
    @app_commands.guild_only()
    async def unlink(self, interaction: discord.Interaction):
        lang = locales.get_lang(interaction)
        await asyncio.to_thread(self.db.unlink_roblox, interaction.user.id)
        msg = "✅ Roblox account unlinked from your profile." if lang == "en" else "✅ Аккаунт Roblox успешно отвязан от вашего профиля."
        await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(name="build", description="Указать свой основной стенд и спек в YBA для профиля")
    @app_commands.describe(
        stand="Твой стенд (например: KCR, SPTW, GER, TWOH, MIH, D4C:LT)",
        spec="Твой спек (Boxing, Pluck, Hamon, Vampirism, Spin)"
    )
    @app_commands.guild_only()
    async def build(self, interaction: discord.Interaction, stand: str, spec: str):
        lang = locales.get_lang(interaction)
        # Очистка от переводов строк, табуляций и лишних пробелов
        clean_stand = re.sub(r"[\r\n\t]+", " ", stand.strip())[:32].strip()
        clean_spec = re.sub(r"[\r\n\t]+", " ", spec.strip())[:32].strip()
        clean_stand = discord.utils.escape_markdown(clean_stand) or "Standless"
        clean_spec = discord.utils.escape_markdown(clean_spec) or "Specless"

        await asyncio.to_thread(self.db.update_user_build, interaction.user.id, clean_stand, clean_spec)

        embed = discord.Embed(
            title=locales.t("build_success_title", lang),
            description=locales.t("build_success_desc", lang, stand=clean_stand, spec=clean_spec),
            color=discord.Color.purple()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    bio_group = app_commands.Group(name="bio", description="Управление описанием/историей профиля", guild_only=True)

    @bio_group.command(name="set", description="Написать о себе или свою историю игрока в профиль")
    @app_commands.describe(text="Твоя история, мейны, стиль игры или статус (до 400 символов)")
    async def bio_set(self, interaction: discord.Interaction, text: str):
        lang = locales.get_lang(interaction)
        clean_text = discord.utils.escape_mentions(text.strip())[:400]
        if not clean_text:
            await interaction.response.send_message(locales.t("bio_clear_success", lang), ephemeral=True)
            return

        await asyncio.to_thread(self.db.update_user_bio, interaction.user.id, clean_text)
        quoted = "\n".join(f"> {l}" for l in clean_text.splitlines() if l.strip())
        await interaction.response.send_message(
            locales.t("bio_set_success", lang, bio=quoted),
            ephemeral=True
        )

    @bio_group.command(name="clear", description="Удалить описание/историю из своего профиля")
    async def bio_clear(self, interaction: discord.Interaction):
        lang = locales.get_lang(interaction)
        await asyncio.to_thread(self.db.update_user_bio, interaction.user.id, None)
        await interaction.response.send_message(locales.t("bio_clear_success", lang), ephemeral=True)

    gang_group = app_commands.Group(name="gang", description="Управление вашей бандой (генгом) в YBA", guild_only=True)

    @gang_group.command(name="set", description="Указать свою банду (генг/клан) в профиле")
    @app_commands.describe(name="Название или тег банды (например: GANGHUB, Passione, Eclipse)")
    async def gang_set(self, interaction: discord.Interaction, name: str):
        lang = locales.get_lang(interaction)
        clean_name = re.sub(r"[\r\n\t]+", " ", name.strip())[:32].strip()
        clean_name = discord.utils.escape_markdown(discord.utils.escape_mentions(clean_name))
        if not clean_name:
            await interaction.response.send_message(locales.t("gang_clear_success", lang), ephemeral=True)
            return

        await asyncio.to_thread(self.db.update_user_gang, interaction.user.id, clean_name)
        await interaction.response.send_message(
            locales.t("gang_set_success", lang, gang=clean_name),
            ephemeral=True
        )

    @gang_group.command(name="clear", description="Удалить привязку к банде из своего профиля")
    async def gang_clear(self, interaction: discord.Interaction):
        lang = locales.get_lang(interaction)
        await asyncio.to_thread(self.db.update_user_gang, interaction.user.id, None)
        await interaction.response.send_message(locales.t("gang_clear_success", lang), ephemeral=True)

    alts_group = app_commands.Group(name="alts", description="Управление списком дополнительных аккаунтов (твинков)", guild_only=True)

    @alts_group.command(name="set", description="Указать свои дополнительные аккаунты Roblox (твинки)")
    @app_commands.describe(accounts="Список ваших доп. аккаунтов (например: alt_acc1, second_player)")
    async def alts_set(self, interaction: discord.Interaction, accounts: str):
        lang = locales.get_lang(interaction)
        clean_accs = re.sub(r"[\r\n\t]+", " ", accounts.strip())[:150].strip()
        clean_accs = discord.utils.escape_mentions(clean_accs).replace("\\_", "_")
        if not clean_accs:
            await interaction.response.send_message(locales.t("alts_clear_success", lang), ephemeral=True)
            return

        await asyncio.to_thread(self.db.update_user_alts, interaction.user.id, clean_accs)
        await interaction.response.send_message(
            locales.t("alts_set_success", lang, alts=clean_accs),
            ephemeral=True
        )

    @alts_group.command(name="clear", description="Очистить список дополнительных аккаунтов")
    async def alts_clear(self, interaction: discord.Interaction):
        lang = locales.get_lang(interaction)
        await asyncio.to_thread(self.db.update_user_alts, interaction.user.id, None)
        await interaction.response.send_message(locales.t("alts_clear_success", lang), ephemeral=True)

    async def resolve_user_roblox(self, target: discord.Member) -> Tuple[dict, bool]:
        """Возвращает (u_data, has_roblox) из базы данных с автоматической привязкой через Bloxlink если не привязан"""
        u_data = await asyncio.to_thread(self.db.get_or_create_user, target.id)
        if not u_data.get("roblox_username") and target.guild:
            api_key = bloxlink.get_bloxlink_key(self.db)
            if api_key:
                try:
                    res = await asyncio.to_thread(bloxlink.resolve_discord_to_roblox, target.guild.id, target.id, api_key)
                    if res:
                        _, auto_name = res
                        u_data = await asyncio.to_thread(self.db.link_roblox, target.id, auto_name)
                except Exception:
                    pass
        return u_data, bool(u_data.get("roblox_username"))

    def build_unlinked_embed(self, target: discord.Member, lang: str, is_owner: bool) -> discord.Embed:
        """Информационный экран, если у пользователя не привязан аккаунт Roblox"""
        if is_owner:
            embed = discord.Embed(
                title="⚠️ " + ("Требуется привязка Roblox" if lang != "en" else "Roblox Link Required"),
                description=(
                    "Для доступа к YBA 1v1 профилю и участия в рейтинговых матчах необходимо подтвердить свой аккаунт Roblox.\n\n"
                    "**Инструкция по привязке:**\n"
                    "1. Пройдите верификацию на [blox.link/verify](https://blox.link/verify)\n"
                    "2. Напишите команду `/link` на сервере для синхронизации\n\n"
                    "После привязки вам откроется полный профиль YBA, ELO, 3D-скин и статистика!"
                    if lang != "en"
                    else (
                        "To access your YBA 1v1 profile and participate in ranked duels, please verify your Roblox account.\n\n"
                        "**Verification steps:**\n"
                        "1. Verify at [blox.link/verify](https://blox.link/verify)\n"
                        "2. Run `/link` in this server to synchronize\n\n"
                        "Once verified, your YBA profile, ELO, 3D skin, and stats will be unlocked!"
                    )
                ),
                color=discord.Color.gold()
            )
            if target.display_avatar:
                embed.set_thumbnail(url=target.display_avatar.url)
            embed.set_footer(text="GANGHUB League • Bloxlink Verification")
        else:
            embed = discord.Embed(
                title="⚠️ " + ("Профиль недоступен" if lang != "en" else "Profile Unavailable"),
                description=(
                    f"Игрок {target.mention} ещё не привязал свой аккаунт Roblox через Bloxlink (`/link`).\n\n"
                    f"Рейтинговый профиль YBA 1v1 открывается только для верифицированных игроков."
                    if lang != "en"
                    else (
                        f"Player {target.mention} has not linked their Roblox account via Bloxlink (`/link`) yet.\n\n"
                        f"YBA 1v1 ranked profile is only visible for verified players."
                    )
                ),
                color=discord.Color.red()
            )
            if target.display_avatar:
                embed.set_thumbnail(url=target.display_avatar.url)
            embed.set_footer(text="GANGHUB League • Bloxlink Verification")
        return embed

    async def build_yba_embed(
        self,
        target: discord.Member,
        lang: str,
        u_data: Optional[dict] = None
    ) -> Tuple[discord.Embed, Optional[discord.File], Optional[str]]:
        if u_data is None:
            u_data, _ = await self.resolve_user_roblox(target)

        wins = u_data["wins"]
        losses = u_data["losses"]
        total = wins + losses
        winrate = round((wins / total) * 100, 1) if total > 0 else 0.0

        pos = await asyncio.to_thread(self.db.get_user_rank_position, target.id) if total > 0 else None
        rank_info = get_rank_info(u_data["rating"], u_data["rd"], total, pos, lang=lang)

        # Формирование стрика
        streak = u_data["streak"]
        if streak > 0:
            streak_text = locales.t("streak_wins", lang, count=streak)
        elif streak < 0:
            streak_text = locales.t("streak_losses", lang, count=abs(streak))
        else:
            streak_text = "—"

        c_code = u_data.get("country")
        c_info = get_country_info(c_code)
        c_flag_str = f"{c_info['flag']} " if c_info else ""

        embed = discord.Embed(
            title=f"{c_flag_str}{locales.t('profile_title', lang, badge=rank_info['badge'], name=target.display_name)}",
            color=discord.Color(rank_info["color"])
        )

        avatar_file = None
        rbx_info = None
        roblox_raw = u_data.get("roblox_username")
        if roblox_raw:
            rbx_url = await asyncio.to_thread(fetch_roblox_avatar_url, roblox_raw)
            if rbx_url:
                embed.set_thumbnail(url=rbx_url)
            elif target.display_avatar:
                embed.set_thumbnail(url=target.display_avatar.url)

            rbx_info = await asyncio.to_thread(bloxlink.get_roblox_account_info, roblox_raw)
        elif target.display_avatar:
            embed.set_thumbnail(url=target.display_avatar.url)

        # Row 1 (Identity & Build - 3 fields)
        if rbx_info:
            roblox_val = f"[{rbx_info['username']}]({rbx_info['profile_url']})"
        elif roblox_raw:
            roblox_val = f"`{roblox_raw}`"
        else:
            roblox_val = locales.t("profile_roblox_empty", lang)

        stand = u_data.get("stand") or "Standless"
        spec = u_data.get("spec") or "Specless"

        if stand == "Standless" and spec == "Specless":
            build_val = locales.t("profile_build_empty", lang)
        else:
            build_val = f"⚔️ **`{stand} + {spec}`**"

        embed.add_field(name=locales.t("profile_roblox_field", lang), value=roblox_val, inline=True)
        tier_display = f"{rank_info['badge']} **{rank_info['tier']}**" + (f" `({total}/5)`" if not rank_info["is_calibrated"] else "")
        embed.add_field(name=locales.t("profile_rank_field", lang), value=tier_display, inline=True)
        embed.add_field(name=locales.t("profile_build_field", lang), value=build_val, inline=True)

        # Row 2 (Rating & Streaks - 3 fields)
        display_rating = rank_info["display"]
        if not rank_info["is_calibrated"]:
            calib_suffix = f" *({total}/5 калибровка)*" if lang != "en" else f" *({total}/5 calibrating)*"
        else:
            calib_suffix = ""
        peak_rating = int(round(u_data['peak_rating']))

        embed.add_field(name=locales.t("profile_elo_field", lang), value=f"**{display_rating}**{calib_suffix}", inline=True)
        embed.add_field(name=locales.t("profile_peak_field", lang), value=f"**{peak_rating}**", inline=True)
        embed.add_field(name=locales.t("profile_streak_field", lang), value=streak_text, inline=True)

        # Row 3 (Winrates & Ladder - 3 fields)
        main_build_name = f"{stand} + {spec}"
        b_stats = await asyncio.to_thread(self.db.get_user_build_stats, target.id, main_build_name)
        if b_stats["total"] > 0:
            b_wr_text = f"**{b_stats['winrate']}%** ({b_stats['wins']}W / {b_stats['losses']}L)"
        else:
            b_wr_text = "— *(0W / 0L)*"

        def _make_wr_bar(w: int, l: int) -> str:
            tot = w + l
            if tot == 0:
                return "▫️ ▫️ ▫️ ▫️ ▫️ ▫️"
            green = int(round((w / tot) * 6))
            green = max(0, min(6, green))
            return ("🟩 " * green + "🟥 " * (6 - green)).strip()

        wr_bar = _make_wr_bar(wins, losses)
        embed.add_field(name=locales.t("profile_winrate_field", lang), value=f"{wr_bar}\n**{winrate}%** ({wins}W / {losses}L)", inline=True)
        embed.add_field(name=locales.t("profile_build_winrate_field", lang), value=b_wr_text, inline=True)
        embed.add_field(name=locales.t("profile_ladder_field", lang), value=f"**#{pos}**" if pos else "—", inline=True)

        # Row 4 (Gang, Created, VIP - 3 fields)
        gang = u_data.get("gang")
        gang_val = f"**{gang}**" if gang else "—"

        if rbx_info:
            if rbx_info.get("is_new"):
                created_val = f"⚠️ `{rbx_info['created_date']}` ({rbx_info['days_old']}d, <30d)" if lang == "en" else f"⚠️ `{rbx_info['created_date']}` ({rbx_info['days_old']} дн., <30 дней!)"
            else:
                created_val = f"`{rbx_info['created_date']}` ({rbx_info['years_old']} y.)" if lang == "en" else f"`{rbx_info['created_date']}` ({rbx_info['years_old']} г.)"
        else:
            created_val = "—"

        user_vip = u_data.get("vip_server_url")
        vip_join_text = "Join 🚀" if lang == "en" else "Перейти 🚀"
        vip_val = f"[{vip_join_text}]({user_vip})" if user_vip else locales.t("profile_vip_empty", lang)

        embed.add_field(name=locales.t("profile_gang_field", lang), value=gang_val, inline=True)
        embed.add_field(name=locales.t("profile_roblox_created_field", lang), value=created_val, inline=True)
        embed.add_field(name=locales.t("profile_vip_field", lang), value=vip_val, inline=True)

        if c_info:
            c_name = c_info["name_ru" if lang != "en" else "name_en"]
            embed.add_field(name=locales.t("country_profile_field", lang), value=f"{c_info['flag']} **{c_name}** (`{c_code}`)", inline=True)

        # Специальный титул (если есть)
        if rank_info.get("special_title"):
            embed.add_field(name=locales.t("profile_title_field", lang), value=rank_info["special_title"], inline=False)

        # Row 5 (Alt Accounts - if set, inline=False)
        alts = u_data.get("alts")
        if alts:
            raw_chips = re.split(r"[,;\s]+", alts.strip())
            chips = [f"`{c.replace(chr(92) + '_', '_')}`" for c in raw_chips if c.strip()]
            if chips:
                embed.add_field(name=locales.t("profile_alts_field", lang), value=", ".join(chips), inline=False)

        # Row 6 (About / Lore - if set, inline=False)
        bio = u_data.get("bio")
        if bio:
            bio_lines = [line.strip() for line in bio.splitlines() if line.strip()]
            quoted_bio = "\n".join(f"> {line}" for line in bio_lines)
            embed.add_field(
                name=locales.t("profile_bio_field", lang),
                value=quoted_bio[:1000],
                inline=False
            )

        footer_text = "GANGHUB League • Click «Discord 💬» to view activity" if lang == "en" else "GANGHUB League • Нажмите «Дискорд 💬» для просмотра активности"
        embed.set_footer(text=footer_text)
        roblox_link = rbx_info.get("profile_url") if rbx_info else None
        return embed, avatar_file, roblox_link

    async def build_discord_embed(
        self,
        target: discord.Member,
        lang: str,
        has_roblox: bool = True,
        is_owner: bool = False
    ) -> discord.Embed:
        act = await asyncio.to_thread(self.db.get_user_activity, target.id)
        rep = await asyncio.to_thread(self.db.get_user_reputation, target.id)

        active_sec = 0.0
        now = time.time()
        # Проверяем: находится ли участник в голосовом канале прямо сейчас с ВКЛЮЧЕННЫМ микрофоном
        if getattr(target, "voice", None) and is_voice_active(target.voice):
            if target.id not in self._voice_sessions:
                self._voice_sessions[target.id] = now
            else:
                active_sec = max(0.0, now - self._voice_sessions[target.id])
        elif target.id in self._voice_sessions:
            active_sec = max(0.0, now - self._voice_sessions.pop(target.id))

        total_voice_sec = (act.get("voice_seconds") or 0.0) + active_sec

        hours = total_voice_sec / 3600.0
        if hours >= 1.0:
            if lang == "en":
                voice_val = f"**{hours:.1f} hrs** ({int(hours)} h. {int((total_voice_sec % 3600) // 60)} min.)"
            else:
                voice_val = f"**{hours:.1f} ч.** ({int(hours)} ч. {int((total_voice_sec % 3600) // 60)} мин.)"
        else:
            mins = int(total_voice_sec // 60)
            if lang == "en":
                voice_val = f"**{mins} min.**" if mins > 0 else "0 min."
            else:
                voice_val = f"**{mins} мин.**" if mins > 0 else "0 мин."

        msg_count = act.get("messages_count") or 0
        msg_val = f"**{msg_count:,}**"

        rank_pos = f"**#{act['activity_rank']}**" if act.get("activity_rank") else "—"

        created_ts = int(target.created_at.timestamp())
        reg_val = f"<t:{created_ts}:D>  *(<t:{created_ts}:R>)*"

        joined_val = "—"
        if hasattr(target, "joined_at") and target.joined_at:
            joined_ts = int(target.joined_at.timestamp())
            joined_val = f"<t:{joined_ts}:D>  *(<t:{joined_ts}:R>)*"

        likes = rep.get("likes") or 0
        dislikes = rep.get("dislikes") or 0
        score = rep.get("rep") or 0
        score_sign = f"+{score}" if score > 0 else str(score)

        if score > 0:
            rep_badge = f"🌟 **Высокая репутация** (`{score_sign}`)" if lang == "ru" else f"🌟 **High Reputation** (`{score_sign}`)"
        elif score < 0:
            rep_badge = f"⚠️ **Отрицательная репутация** (`{score_sign}`)" if lang == "ru" else f"⚠️ **Negative Reputation** (`{score_sign}`)"
        else:
            rep_badge = "⚖️ **Нейтральная репутация** (`0`)" if lang == "ru" else "⚖️ **Neutral Reputation** (`0`)"

        total_votes = likes + dislikes
        if total_votes > 0:
            g = int(round((likes / total_votes) * 6))
            g = max(0, min(6, g))
            rep_bar = ("🟩 " * g + "🟥 " * (6 - g)).strip()
        else:
            rep_bar = "▫️ ▫️ ▫️ ▫️ ▫️ ▫️"

        embed = discord.Embed(
            title=f"💬 Discord Профиль • {target.display_name}" if lang == "ru" else f"💬 Discord Profile • {target.display_name}",
            color=discord.Color.blurple()
        )
        if target.display_avatar:
            embed.set_thumbnail(url=target.display_avatar.url)

        if lang == "en":
            activity_title = "📊 Server Activity"
            activity_text = (
                f"• **Activity Ladder Rank:**  {rank_pos}\n\n"
                f"• **Voice Channel Hours:**  {voice_val}\n\n"
                f"• **Messages Sent:**  {msg_val}"
            )
            dates_title = "📅 Server & Discord Dates"
            dates_text = (
                f"• **Joined Server:**  {joined_val}\n\n"
                f"• **Account Created:**  {reg_val}"
            )
            rep_title = "⭐ Community Reputation"
            rep_text = (
                f"{rep_badge}\n\n"
                f"{rep_bar}\n\n"
                f"**Reputation Balance:**  **{score_sign}**  (👍 **{likes}**  |  👎 **{dislikes}**)"
            )
            if not has_roblox and is_owner:
                footer_text = "GANGHUB Community • Link Roblox via /link to view YBA 1v1 profile"
            else:
                footer_text = "GANGHUB Community • Click 👍 or 👎 below to vote reputation"
        else:
            activity_title = "📊 Активность на сервере"
            activity_text = (
                f"• **Место в топе активности:**  {rank_pos}\n\n"
                f"• **Часов в голосовых каналах:**  {voice_val}\n\n"
                f"• **Отправлено сообщений:**  {msg_val}"
            )
            dates_title = "📅 Даты на сервере и в Discord"
            dates_text = (
                f"• **Присоединился к серверу:**  {joined_val}\n\n"
                f"• **Дата регистрации аккаунта:**  {reg_val}"
            )
            rep_title = "⭐ Репутация сообщества"
            rep_text = (
                f"{rep_badge}\n\n"
                f"{rep_bar}\n\n"
                f"**Баланс отзывов:**  **{score_sign}**  (👍 **{likes}**  |  👎 **{dislikes}**)"
            )
            if not has_roblox and is_owner:
                footer_text = "GANGHUB Community • Привяжите Roblox через /link для открытия профиля YBA"
            else:
                footer_text = "GANGHUB Community • Нажмите 👍 или 👎 ниже для изменения репутации"

        embed.add_field(name=activity_title, value=activity_text, inline=False)
        embed.add_field(name=dates_title, value=dates_text, inline=False)
        embed.add_field(name=rep_title, value=rep_text, inline=False)
        embed.set_footer(text=footer_text)
        return embed

    @commands.command(name="profile", aliases=["p", "профиль"])
    @commands.guild_only()
    async def prefix_profile(self, ctx: commands.Context, user: Optional[discord.Member] = None):
        """Просмотр профиля игрока через префиксную команду !profile [пользователь]"""
        lang = locales.get_user_lang(self.db, ctx.author.id, fallback="ru")
        target = user or ctx.author
        if target.bot:
            await ctx.reply("❌ Cannot view profile of a bot." if lang == "en" else "❌ Нельзя смотреть профиль бота.")
            return

        u_data, has_roblox = await self.resolve_user_roblox(target)
        is_owner = (target.id == ctx.author.id)

        # Профиль YBA показывается только если привязан Roblox
        if has_roblox:
            embed, avatar_file, roblox_link = await self.build_yba_embed(target, lang, u_data=u_data)
            view = ProfileView(
                self.bot, self.db, self, target, lang,
                roblox_url=roblox_link, is_owner=is_owner, current_tab="yba", has_roblox=True,
                caller_id=ctx.author.id
            )
            kwargs = {"embed": embed, "view": view}
            if avatar_file:
                kwargs["file"] = avatar_file
            await ctx.reply(**kwargs)
        else:
            embed = self.build_unlinked_embed(target, lang, is_owner=is_owner)
            view = ProfileView(
                self.bot, self.db, self, target, lang,
                roblox_url=None, is_owner=is_owner, current_tab="unlinked", has_roblox=False,
                caller_id=ctx.author.id
            )
            await ctx.reply(embed=embed, view=view)

    @app_commands.command(name="profile", description="Посмотреть профиль игрока (YBA 1v1 и Discord активность)")
    @app_commands.describe(user="Игрок, чей профиль ты хочешь посмотреть (по умолчанию — твой)")
    @app_commands.guild_only()
    async def profile(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        lang = locales.get_lang(interaction)
        target = user or interaction.user
        if target.bot:
            await interaction.response.send_message(locales.t("error_bot_user", lang), ephemeral=True)
            return

        await interaction.response.defer()
        u_data, has_roblox = await self.resolve_user_roblox(target)
        is_owner = (target.id == interaction.user.id)

        # Профиль YBA показывается только если привязан Roblox
        if has_roblox:
            embed, avatar_file, roblox_link = await self.build_yba_embed(target, lang, u_data=u_data)
            view = ProfileView(
                self.bot, self.db, self, target, lang,
                roblox_url=roblox_link, is_owner=is_owner, current_tab="yba", has_roblox=True,
                caller_id=interaction.user.id
            )
            kwargs = {"embed": embed, "view": view}
            if avatar_file:
                kwargs["file"] = avatar_file
            await interaction.followup.send(**kwargs)
        else:
            embed = self.build_unlinked_embed(target, lang, is_owner=is_owner)
            view = ProfileView(
                self.bot, self.db, self, target, lang,
                roblox_url=None, is_owner=is_owner, current_tab="unlinked", has_roblox=False,
                caller_id=interaction.user.id
            )
            await interaction.followup.send(embed=embed, view=view)

    @commands.command(name="rep", aliases=["реп", "like", "dislike"])
    @commands.guild_only()
    async def rep_command(self, ctx: commands.Context, arg1: str, arg2: Optional[str] = None):
        """Оценить репутацию игрока: !rep + @User или !rep - @User или !rep @User +"""
        lang = locales.get_user_lang(self.db, ctx.author.id, fallback="ru")

        # Разбираем аргументы: arg1 может быть действием (+/-) или пользователем
        action_str = "+"
        target_member: Optional[discord.Member] = None

        if arg1 in ("+", "-", "+1", "-1", "like", "dislike", "лайк", "дизлайк"):
            action_str = arg1
            if ctx.message.mentions:
                target_member = ctx.message.mentions[0]
            elif arg2:
                try:
                    target_member = await commands.MemberConverter().convert(ctx, arg2)
                except Exception:
                    pass
        elif ctx.message.mentions:
            target_member = ctx.message.mentions[0]
            if arg2 and arg2 in ("+", "-", "+1", "-1", "like", "dislike", "лайк", "дизлайк"):
                action_str = arg2
        elif arg2 in ("+", "-", "+1", "-1", "like", "dislike", "лайк", "дизлайк"):
            action_str = arg2
            try:
                target_member = await commands.MemberConverter().convert(ctx, arg1)
            except Exception:
                pass

        if not target_member:
            await ctx.reply("ℹ️ Использование: `/rep` или `!rep + @User` / `!rep - @User`")
            return

        if target_member.bot:
            await ctx.reply("❌ Cannot change reputation of a bot." if lang == "en" else "❌ Ботам нельзя менять репутацию.")
            return
        if ctx.author.id == target_member.id:
            await ctx.reply("❌ You cannot change reputation of yourself!" if lang == "en" else "❌ Вы не можете менять репутацию самому себе!")
            return

        vote = 1 if action_str in ("+", "+1", "like", "лайк", "up", "upvote") else -1
        ok, msg, rep_data = await asyncio.to_thread(self.db.vote_reputation, ctx.author.id, target_member.id, vote)
        if not ok:
            action_name = "+Rep (like)" if vote > 0 else "-Rep (dislike)"
            err = f"⚠️ You have already given {action_name} to this user!" if lang == "en" else msg
            await ctx.reply(err)
            return

        score = rep_data["rep"]
        sign = f"+{score}" if score > 0 else str(score)
        color = discord.Color.green() if vote > 0 else discord.Color.red()
        emoji = "📈" if vote > 0 else "📉"
        action_title = "+Rep" if vote > 0 else "-Rep"

        embed = discord.Embed(
            title=f"{emoji} Репутация: {action_title}",
            description=(
                f"{ctx.author.mention} поставил **{action_title}** игроку {target_member.mention}!\n\n"
                f"📊 **Текущая репутация:** `{sign}` (👍 `+{rep_data['likes']}` / 👎 `-{rep_data['dislikes']}`)"
                if lang != "en"
                else f"{ctx.author.mention} gave **{action_title}** to {target_member.mention}!\n\n"
                     f"📊 **Current reputation:** `{sign}` (👍 `+{rep_data['likes']}` / 👎 `-{rep_data['dislikes']}`)"
            ),
            color=color
        )
        embed.set_thumbnail(url=target_member.display_avatar.url)
        embed.set_footer(text="GANGHUB Community Reputation")
        await ctx.reply(embed=embed)

    @app_commands.command(name="rep", description="Оценить репутацию игрока (+rep или -rep)")
    @app_commands.describe(
        action="Выбрать: + (+rep, лайк) или - (-rep, дизлайк)",
        user="Игрок, которому вы хотите поставить репутацию"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="+ (Поставить +rep / лайк)", value="+"),
        app_commands.Choice(name="- (Поставить -rep / дизлайк)", value="-")
    ])
    @app_commands.guild_only()
    async def rep_slash(self, interaction: discord.Interaction, action: str, user: discord.Member):
        lang = locales.get_lang(interaction)
        if user.bot:
            await interaction.response.send_message("❌ Cannot set reputation for a bot." if lang == "en" else "❌ Ботам нельзя ставить репутацию.", ephemeral=True)
            return
        if interaction.user.id == user.id:
            await interaction.response.send_message("❌ You cannot change reputation of yourself!" if lang == "en" else "❌ Вы не можете менять репутацию самому себе!", ephemeral=True)
            return

        now = time.time()
        last_rep = self._rep_cooldowns.get(interaction.user.id, 0.0)
        if now - last_rep < 30.0:
            rem = int(30.0 - (now - last_rep))
            wait_msg = (
                f"⏳ You have voted recently. You can vote again in `{rem}` sec."
                if lang == "en"
                else f"⏳ Вы недавно оценивали репутацию. Повторить можно через `{rem}` сек."
            )
            await interaction.response.send_message(wait_msg, ephemeral=True)
            return

        vote = 1 if action.strip() in ("+", "+1", "like", "up") else -1
        ok, msg, rep_data = await asyncio.to_thread(self.db.vote_reputation, interaction.user.id, user.id, vote)
        if not ok:
            action_name = "+Rep (like)" if vote > 0 else "-Rep (dislike)"
            err = f"⚠️ You have already given {action_name} to this user!" if lang == "en" else msg
            await interaction.response.send_message(err, ephemeral=True)
            return

        self._rep_cooldowns[interaction.user.id] = now
        score = rep_data["rep"]
        sign = f"+{score}" if score > 0 else str(score)
        color = discord.Color.green() if vote > 0 else discord.Color.red()
        emoji = "📈" if vote > 0 else "📉"
        action_title = "+Rep" if vote > 0 else "-Rep"

        embed = discord.Embed(
            title=f"{emoji} Репутация: {action_title}",
            description=(
                f"{interaction.user.mention} поставил **{action_title}** игроку {user.mention}!\n\n"
                f"📊 **Текущая репутация:** `{sign}` (👍 `+{rep_data['likes']}` / 👎 `-{rep_data['dislikes']}`)"
                if lang != "en"
                else f"{interaction.user.mention} gave **{action_title}** to {user.mention}!\n\n"
                     f"📊 **Current reputation:** `{sign}` (👍 `+{rep_data['likes']}` / 👎 `-{rep_data['dislikes']}`)"
            ),
            color=color
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text="GANGHUB Community Reputation")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="skin", description="Посмотреть полноростовый 3D скин игрока в Roblox")
    @app_commands.describe(
        username="Никнейм в Roblox (например: drainworldtour)",
        user="Либо участник Discord (посмотрит его привязанный скин)"
    )
    @app_commands.guild_only()
    async def skin(
        self,
        interaction: discord.Interaction,
        username: Optional[str] = None,
        user: Optional[discord.Member] = None
    ):
        lang = locales.get_lang(interaction)
        await interaction.response.defer()

        target_name_or_id = None

        if username and username.strip():
            target_name_or_id = username.strip().lstrip("@")
        elif user:
            # Ищем привязанный ник у указанного участника
            u_data = await asyncio.to_thread(self.db.get_or_create_user, user.id)
            if u_data.get("roblox_username"):
                target_name_or_id = u_data["roblox_username"]
            elif interaction.guild_id:
                api_key = bloxlink.get_bloxlink_key(self.db)
                if api_key:
                    res = await asyncio.to_thread(bloxlink.resolve_discord_to_roblox, interaction.guild_id, user.id, api_key)
                    if res:
                        target_name_or_id = res[1]
        else:
            # По умолчанию смотрим скин автора команды
            u_data = await asyncio.to_thread(self.db.get_or_create_user, interaction.user.id)
            if u_data.get("roblox_username"):
                target_name_or_id = u_data["roblox_username"]
            elif interaction.guild_id:
                api_key = bloxlink.get_bloxlink_key(self.db)
                if api_key:
                    res = await asyncio.to_thread(bloxlink.resolve_discord_to_roblox, interaction.guild_id, interaction.user.id, api_key)
                    if res:
                        target_name_or_id = res[1]

        if not target_name_or_id:
            await interaction.followup.send(
                locales.t("skin_not_found_prompt", lang),
                ephemeral=True
            )
            return

        res = await asyncio.to_thread(fetch_roblox_full_avatar_bytes, target_name_or_id)
        if not res:
            await interaction.followup.send(
                locales.t("skin_user_not_found", lang, name=target_name_or_id),
                ephemeral=True
            )
            return

        img_bytes, acc_info, img_url = res

        file = discord.File(io.BytesIO(img_bytes), filename="roblox_full_skin.png")

        embed = discord.Embed(
            title=locales.t("skin_embed_title", lang, display=acc_info["display_name"], user=acc_info["username"]),
            description=f"[{locales.t('skin_profile_link', lang)}]({acc_info['profile_url']})",
            color=discord.Color.blue()
        )
        embed.set_image(url="attachment://roblox_full_skin.png")
        embed.add_field(name=locales.t("skin_field_id", lang), value=f"`{acc_info['id']}`", inline=True)

        if acc_info.get("is_new"):
            created_val = f"⚠️ `{acc_info['created_date']}` ({acc_info['days_old']}d, <30d)" if lang == "en" else f"⚠️ `{acc_info['created_date']}` ({acc_info['days_old']} дн., <30 дней!)"
        else:
            created_val = f"`{acc_info['created_date']}` ({acc_info['years_old']} y.)" if lang == "en" else f"`{acc_info['created_date']}` ({acc_info['years_old']} г. / {acc_info['days_old']} дн.)"

        embed.add_field(name=locales.t("skin_field_created", lang), value=created_val, inline=True)
        embed.set_footer(text="Roblox 3D HD Render • GANGHUB")

        view = discord.ui.View()
        view.add_item(discord.ui.Button(label=locales.t("skin_btn_profile", lang), url=acc_info["profile_url"], style=discord.ButtonStyle.link, emoji="🔗"))
        view.add_item(discord.ui.Button(label=locales.t("skin_btn_hd", lang), url=img_url, style=discord.ButtonStyle.link, emoji="🖼️"))

        await interaction.followup.send(embed=embed, file=file, view=view)

    async def _build_leaderboard_embed(self, page: int, lang: str) -> discord.Embed:
        limit = 10
        offset = (page - 1) * limit
        leaders = await asyncio.to_thread(self.db.get_leaderboard, limit, offset)

        embed = discord.Embed(
            title=locales.t("lb_title", lang),
            description=locales.t("lb_desc", lang, page=page),
            color=discord.Color.gold()
        )

        if not leaders:
            embed.description += locales.t("lb_empty", lang)
        else:
            lines = []
            for i, p in enumerate(leaders, start=offset + 1):
                total = p["wins"] + p["losses"]
                r_info = get_rank_info(p["rating"], p["rd"], total, i, lang=lang)
                clean_nick = discord.utils.escape_markdown(discord.utils.escape_mentions(p['roblox_username'])) if p.get('roblox_username') else ""
                roblox = f"(`{clean_nick}`)" if clean_nick else ""

                medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"`#{i}`"
                c_info = get_country_info(p.get("country"))
                flag_str = f"{c_info['flag']} " if c_info else ""
                lines.append(
                    f"{medal} {flag_str}**<@{p['discord_id']}>** {roblox}\n"
                    f"┗ {r_info['badge']} {int(round(p['rating']))} ELO • {p['wins']}W - {p['losses']}L\n"
                )
            embed.description += "\n".join(lines)

        embed.set_footer(text=locales.t("lb_footer", lang))
        return embed

    @app_commands.command(name="leaderboard", description="Посмотреть таблицу лидеров сервера")
    @app_commands.describe(page="Номер страницы (по 10 игроков на странице)")
    @app_commands.guild_only()
    async def leaderboard(self, interaction: discord.Interaction, page: Optional[int] = 1):
        lang = locales.get_lang(interaction)
        await interaction.response.defer()

        total_count = await asyncio.to_thread(self.db.get_leaderboard_count)
        total_pages = max(1, (total_count + 9) // 10)
        curr_page = max(1, min(page or 1, total_pages))

        embed = await self._build_leaderboard_embed(curr_page, lang)
        view = LeaderboardView(self, self.db, curr_page, total_pages, lang, interaction.user.id)
        msg = await interaction.followup.send(embed=embed, view=view)
        view.message = msg

    @app_commands.command(name="ranks", description="Список доступных рангов и диапазоны ELO")
    @app_commands.guild_only()
    async def ranks(self, interaction: discord.Interaction):
        lang = locales.get_lang(interaction)
        embed = discord.Embed(
            title=locales.t("ranks_title", lang),
            color=discord.Color.blurple()
        )

        embed.add_field(
            name=f"{SPECIAL_ROLES['CALIBRATION']['badge']} {locales.t('ranks_calib_name', lang)}",
            value=locales.t("ranks_calib_desc", lang),
            inline=False
        )

        for r in RANKS:
            max_r = "∞" if r["max_rating"] > 5000 else str(r["max_rating"])
            embed.add_field(
                name=f"{r['badge']} {r['name']}",
                value=f"`{r['min_rating']} – {max_r} ELO`",
                inline=True
            )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="rules", description="Официальные соревновательные правила 1v1 Лиги GANGHUB")
    @app_commands.guild_only()
    async def rules(self, interaction: discord.Interaction):
        lang = locales.get_lang(interaction)
        embed = discord.Embed(
            title=locales.t("rules_title", lang),
            description=locales.t("rules_overview_desc", lang),
            color=discord.Color.gold()
        )
        embed.set_footer(text="GangHub League 1v1 • Glicko-2")
        view = RulesView(lang, author_id=interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view)
        try:
            view.message = await interaction.original_response()
        except Exception:
            pass

    @app_commands.command(name="country", description="Выбрать страну (СНГ и Европа), которую ты представляешь в Лиге")
    @app_commands.describe(country="Выбери страну из списка Европы и СНГ")
    @app_commands.guild_only()
    async def country(self, interaction: discord.Interaction, country: str):
        lang = locales.get_lang(interaction)
        code = country.upper().strip()
        c_info = get_country_info(code)
        if not c_info:
            await interaction.response.send_message(locales.t("country_invalid", lang), ephemeral=True)
            return

        # Проверяем кулдаун
        u_data = await asyncio.to_thread(self.db.get_or_create_user, interaction.user.id)
        if u_data.get("country_updated_at"):
            raw_dt = u_data["country_updated_at"]
            last_upd = None
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
                try:
                    last_upd = datetime.strptime(str(raw_dt), fmt)
                    break
                except Exception:
                    pass
            if not last_upd:
                try:
                    last_upd = datetime.fromisoformat(str(raw_dt))
                except Exception:
                    pass
            if last_upd:
                diff = datetime.utcnow() - last_upd
                cooldown_secs = COUNTRY_COOLDOWN_DAYS * 86400
                if diff.total_seconds() < cooldown_secs:
                    remaining_days = max(1, int(round((cooldown_secs - diff.total_seconds()) / 86400)))
                    await interaction.response.send_message(
                        locales.t("country_cooldown_error", lang, days=remaining_days),
                        ephemeral=True
                    )
                    return

        c_name = c_info["name_ru" if lang != "en" else "name_en"]
        c_flag = c_info["flag"]

        embed = discord.Embed(
            title=locales.t("country_confirm_title", lang),
            description=locales.t("country_confirm_desc", lang, flag=c_flag, name=c_name, code=code, days=COUNTRY_COOLDOWN_DAYS),
            color=discord.Color.blurple()
        )
        view = CountryConfirmView(self, self.db, interaction.user.id, code, lang)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @country.autocomplete("country")
    async def country_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        lang = locales.get_lang(interaction)
        curr = current.lower().strip()
        choices = []
        for code, info in COUNTRIES.items():
            name_ru = info["name_ru"]
            name_en = info["name_en"]
            flag = info["flag"]
            disp_name = name_ru if lang != "en" else name_en
            label = f"{flag} {disp_name} ({code})"
            aliases = info.get("aliases", [])
            if not curr or curr in name_ru.lower() or curr in name_en.lower() or curr in code.lower() or any(curr in a for a in aliases):
                choices.append(app_commands.Choice(name=label[:100], value=code))
                if len(choices) >= 25:
                    break
        return choices

    vip_group = app_commands.Group(name="vip", description="Управление VIP/Приватными серверами игроков и Лиги", guild_only=True)

    @vip_group.command(name="link", description="Получить ссылку на VIP-сервер игрока или Лиги")
    @app_commands.describe(user="Игрок, чью VIP-ссылку посмотреть (по умолчанию — ваша или Лиги)")
    async def vip_link(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        lang = locales.get_lang(interaction)
        target = user or interaction.user

        user_vip = await asyncio.to_thread(self.db.get_user_vip, target.id)
        league_vips = await asyncio.to_thread(self.db.get_league_vips)

        if user_vip:
            embed = discord.Embed(
                title=locales.t("vip_title", lang),
                description=locales.t("vip_user_desc", lang, user=target.mention, link=user_vip),
                color=discord.Color.blue()
            )
            view = discord.ui.View()
            btn_label = f"VIP {target.display_name[:15]}" if target.id != interaction.user.id else locales.t("vip_btn_label", lang)
            view.add_item(discord.ui.Button(label=btn_label, url=user_vip, style=discord.ButtonStyle.link))
            await interaction.response.send_message(embed=embed, view=view, ephemeral=False)
            return

        vips_status = await asyncio.to_thread(self.db.get_league_vips_status)
        if vips_status:
            if lang == "en":
                notice = f"*({target.mention} has no personal VIP, showing official League VIP servers)*\n\n" if user else ""
            else:
                notice = f"*(У {target.mention} нет личного VIP, показаны официальные VIP-серверы Лиги)*\n\n" if user else ""

            v_lines = []
            view = discord.ui.View()
            join_str = "Join" if lang == "en" else "Войти"
            for item in vips_status:
                s = item["slot"]
                u = item["url"]
                occ = item["occupied"]
                if occ:
                    status_lbl = "Occupied" if lang == "en" else "Занят"
                    v_lines.append(f"• 🔴 **VIP {s} ({status_lbl}):** [{join_str}]({u})")
                    view.add_item(discord.ui.Button(label=f"VIP {s} (Занят)", url=u, style=discord.ButtonStyle.link, emoji="🔴"))
                else:
                    status_lbl = "Free" if lang == "en" else "Свободен"
                    v_lines.append(f"• 🟢 **VIP {s} ({status_lbl}):** [{join_str}]({u})")
                    view.add_item(discord.ui.Button(label=f"VIP {s} (Свободен)", url=u, style=discord.ButtonStyle.link, emoji="🟢"))

            embed = discord.Embed(
                title=locales.t("vip_title", lang),
                description=f"{notice}" + "\n".join(v_lines),
                color=discord.Color.gold()
            )
            embed.set_footer(text="GANGHUB 1v1 • Dynamic VIP Allocation" if lang == "en" else "GANGHUB 1v1 • Авто-бронирование VIP серверов")
            await interaction.response.send_message(embed=embed, view=view, ephemeral=False)
            return

        await interaction.response.send_message(
            locales.t("vip_user_not_set", lang, user=target.mention),
            ephemeral=True
        )

    @vip_group.command(name="set", description="Установить свою личную ссылку на VIP-сервер")
    @app_commands.describe(url="Ссылка на ваш приватный сервер Roblox (https://...)")
    async def vip_set(self, interaction: discord.Interaction, url: str):
        lang = locales.get_lang(interaction)
        url = url.strip()
        if not url.startswith("https://"):
            await interaction.response.send_message(locales.t("vip_invalid_url", lang), ephemeral=True)
            return

        await asyncio.to_thread(self.db.set_user_vip, interaction.user.id, url)
        await interaction.response.send_message(locales.t("vip_user_set_success", lang, url=url), ephemeral=True)

    @vip_group.command(name="clear", description="Удалить свою личную ссылку на VIP-сервер")
    async def vip_clear(self, interaction: discord.Interaction):
        lang = locales.get_lang(interaction)
        await asyncio.to_thread(self.db.set_user_vip, interaction.user.id, None)
        await interaction.response.send_message(locales.t("vip_clear_success", lang), ephemeral=True)

    @vip_group.command(name="set_league", description="[Для Респов и Админов] Добавить или обновить VIP-сервер Лиги")
    @app_commands.describe(
        url="Ссылка на официальный приватный сервер Лиги (https://...)",
        slot="Номер слота VIP (1, 2, 3... По умолчанию: 1)"
    )
    async def vip_set_league(self, interaction: discord.Interaction, url: str, slot: Optional[int] = 1):
        from cogs.matches import is_resp_or_admin
        lang = locales.get_lang(interaction)
        if not is_resp_or_admin(interaction):
            await interaction.response.send_message(locales.t("error_resp_only", lang, role=RESP_ROLE_NAME), ephemeral=True)
            return

        url = url.strip()
        if not url.startswith("https://"):
            await interaction.response.send_message(locales.t("vip_invalid_url", lang), ephemeral=True)
            return

        slot_num = max(1, min(slot or 1, 10))
        await asyncio.to_thread(self.db.set_league_vip, slot_num, url)
        msg = f"✅ Official League **VIP {slot_num}** successfully set!" if lang == "en" else f"✅ Официальный сервер Лиги **VIP {slot_num}** успешно установлен!"
        await interaction.response.send_message(msg, ephemeral=True)

    @vip_group.command(name="clear_league", description="[Для Респов и Админов] Удалить VIP-сервер Лиги")
    @app_commands.describe(slot="Номер слота VIP для удаления (1, 2, 3...) или пусто для удаления всех")
    async def vip_clear_league(self, interaction: discord.Interaction, slot: Optional[int] = None):
        from cogs.matches import is_resp_or_admin
        lang = locales.get_lang(interaction)
        if not is_resp_or_admin(interaction):
            await interaction.response.send_message(locales.t("error_resp_only", lang, role=RESP_ROLE_NAME), ephemeral=True)
            return

        await asyncio.to_thread(self.db.remove_league_vip, slot)
        if slot:
            msg = f"✅ League VIP slot #{slot} deleted." if lang == "en" else f"✅ Слот #{slot} VIP-сервера Лиги удален."
        else:
            msg = "✅ All League VIP servers cleared." if lang == "en" else "✅ Все VIP-серверы Лиги очищены."
        await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(name="check_passenger", description="[Для Респов] Проверить игрока на подсад/пассажира через Bloxlink")
    @app_commands.describe(
        user="Игрок, которого вы хотите проверить",
        roblox_username="Ник в Roblox, с которого он играет дуэль (опционально для сверки)"
    )
    @app_commands.guild_only()
    async def check_passenger(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        roblox_username: Optional[str] = None
    ):
        from cogs.matches import is_resp_or_admin
        lang = locales.get_lang(interaction)
        if not is_resp_or_admin(interaction):
            await interaction.response.send_message(locales.t("error_resp_only", lang, role=RESP_ROLE_NAME), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        api_key = bloxlink.get_bloxlink_key(self.db)
        if not api_key:
            await interaction.followup.send(locales.t("bloxlink_status_inactive", lang), ephemeral=True)
            return

        res = await asyncio.to_thread(bloxlink.resolve_discord_to_roblox, interaction.guild_id, user.id, api_key)
        embed = discord.Embed(
            title=locales.t("passenger_title", lang, name=user.display_name),
            color=discord.Color.blue()
        )

        if not res:
            embed.description = locales.t("passenger_unverified", lang)
            embed.color = discord.Color.orange()
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        bloxlink_id, bloxlink_name = res
        embed.add_field(
            name=locales.t("passenger_bloxlink_field", lang),
            value=f"`@{bloxlink_name}` (ID: `{bloxlink_id}`)",
            inline=True
        )

        match_name = roblox_username.strip().lstrip("@") if roblox_username else None
        if match_name:
            embed.add_field(
                name=locales.t("passenger_match_field", lang),
                value=f"`@{match_name}`",
                inline=True
            )
            if bloxlink_name.lower() == match_name.lower():
                embed.add_field(
                    name=locales.t("passenger_status_field", lang),
                    value=locales.t("passenger_match_ok", lang, match=match_name, bloxlink=bloxlink_name),
                    inline=False
                )
                embed.color = discord.Color.green()
            else:
                embed.add_field(
                    name=locales.t("passenger_status_field", lang),
                    value=locales.t("passenger_match_fail", lang, bloxlink=bloxlink_name, match=match_name),
                    inline=False
                )
                embed.color = discord.Color.red()

        # Проверка твинков (обратный поиск Bloxlink)
        alts = await asyncio.to_thread(bloxlink.resolve_roblox_to_discord, interaction.guild_id, bloxlink_id, api_key)
        other_alts = [uid for uid in alts if uid != user.id]
        if other_alts:
            alt_mentions = ", ".join(f"<@{uid}>" for uid in other_alts)
            embed.add_field(
                name="⚠️ Alts / Matches" if lang == "en" else "⚠️ Твинки / Совпадения",
                value=locales.t("passenger_alts_warning", lang, roblox_user=bloxlink_name, alts=alt_mentions),
                inline=False
            )

        embed.set_footer(text="GANGHUB Anti-Smurf Inspection • Bloxlink v4")
        await interaction.followup.send(embed=embed, ephemeral=True)

    bloxlink_group = app_commands.Group(name="bloxlink", description="Настройка интеграции с Bloxlink", guild_only=True)

    @bloxlink_group.command(name="set_key", description="[Для Админов] Установить API-ключ Bloxlink для сервера")
    @app_commands.describe(key="Ключ с https://blox.link/dashboard/user/developer")
    async def bloxlink_set_key(self, interaction: discord.Interaction, key: str):
        lang = locales.get_lang(interaction)
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(locales.t("error_admin_only", lang), ephemeral=True)
            return

        key = key.strip()
        await interaction.response.defer(ephemeral=True)
        valid, msg = await asyncio.to_thread(bloxlink.test_bloxlink_key, interaction.guild_id, key)
        if not valid:
            await interaction.followup.send(locales.t("bloxlink_key_invalid", lang, error=msg), ephemeral=True)
            return

        await asyncio.to_thread(self.db.set_setting, "bloxlink_api_key", key)
        await interaction.followup.send(locales.t("bloxlink_key_saved", lang), ephemeral=True)

    @bloxlink_group.command(name="status", description="Проверить статус подключения Bloxlink к серверу")
    async def bloxlink_status(self, interaction: discord.Interaction):
        lang = locales.get_lang(interaction)
        key = bloxlink.get_bloxlink_key(self.db)
        if key:
            await interaction.response.send_message(locales.t("bloxlink_status_active", lang), ephemeral=True)
        else:
            await interaction.response.send_message(locales.t("bloxlink_status_inactive", lang), ephemeral=True)

    @app_commands.command(name="language", description="Выбрать язык интерфейса бота и ЛС-уведомлений / Bot language")
    @app_commands.describe(language="Выберите язык / Choose language")
    @app_commands.choices(
        language=[
            app_commands.Choice(name="Русский 🇷🇺", value="ru"),
            app_commands.Choice(name="English 🇬🇧", value="en"),
        ]
    )
    async def language(self, interaction: discord.Interaction, language: str):
        selected_lang = "ru" if language.lower().startswith("ru") else "en"
        await asyncio.to_thread(self.db.set_user_language, interaction.user.id, selected_lang)
        msg_key = f"language_changed_{selected_lang}"
        await interaction.response.send_message(locales.t(msg_key, selected_lang), ephemeral=True)

async def setup(bot: commands.Bot):
    # Cog регистрируется из bot.py
    pass

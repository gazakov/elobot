import os
import asyncio
from typing import Optional, Union, List
import discord
from discord import app_commands
from discord.ext import commands
from database import Database
from ranks import get_rank_info, sync_user_roles, ensure_all_rank_roles
import config
from config import BACKUP_DIR
import locales
import bloxlink

class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot, db: Database):
        self.bot = bot
        self.db = db

    season_group = app_commands.Group(
        name="season",
        description="Управление сезонами ELO",
        guild_only=True,
        default_permissions=discord.Permissions(administrator=True)
    )

    @season_group.command(name="info", description="Информация о текущем активном сезоне")
    async def info(self, interaction: discord.Interaction):
        lang = locales.get_lang(interaction)
        await interaction.response.defer()
        season = await asyncio.to_thread(self.db.get_active_season)
        embed = discord.Embed(
            title=locales.t("season_info_title", lang, name=season['name']),
            description=locales.t("season_info_desc", lang, started_at=season['started_at']),
            color=discord.Color.green()
        )
        await interaction.followup.send(embed=embed)

    @season_group.command(name="reset", description="[Только Админы] Сброс сезона и применение Soft Reset")
    @app_commands.describe(
        new_season_name="Название нового сезона (например: Сезон 2)",
        confirm="Подтверждение необратимого сброса сезона"
    )
    async def reset(self, interaction: discord.Interaction, new_season_name: str, confirm: bool = False):
        lang = locales.get_lang(interaction)
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(locales.t("error_admin_only", lang), ephemeral=True)
            return

        # Защита от случайного нажатия (Safety Switch)
        if not confirm:
            if lang == "en":
                msg = (
                    "⚠️ **WARNING! Season reset is irreversible!**\n"
                    "This action will apply a Soft Reset to all players, compress their ratings, and reset season wins/losses.\n"
                    "If you really want to start a new season, run the command with `confirm: True`."
                )
            else:
                msg = (
                    "⚠️ **ВНИМАНИЕ! Сброс сезона необратим!**\n"
                    "Это действие применит Soft Reset ко всем игрокам, сожмет их рейтинги и обнулит сезонные победы/поражения.\n"
                    "Если вы действительно хотите начать новый сезон, запустите команду с параметром `confirm: True`."
                )
            await interaction.response.send_message(msg, ephemeral=True)
            return

        # Санитизация названия сезона (до 32 символов)
        clean_name = discord.utils.escape_markdown(new_season_name.strip()[:32]) or ("New Season" if lang == "en" else "Новый Сезон")

        await interaction.response.defer()
        new_season_id = await asyncio.to_thread(self.db.reset_season, clean_name)

        if lang == "en":
            embed = discord.Embed(
                title="🔄 Season Reset Successfully!",
                description=(
                    f"Started **{clean_name}** (ID: `#{new_season_id}`).\n\n"
                    f"• Applied **Soft Reset**: player ratings shifted closer to 1500.\n"
                    f"• Rating Deviation (RD) increased for quick recalibration at the start of the season!"
                ),
                color=discord.Color.gold()
            )
        else:
            embed = discord.Embed(
                title="🔄 Сезон успешно сброшен!",
                description=(
                    f"Начат **{clean_name}** (ID: `#{new_season_id}`).\n\n"
                    f"• Применен **Soft Reset**: рейтинги игроков приближены к 1500.\n"
                    f"• Параметр неопределенности (RD) повышен для быстрой перекалибровки в начале сезона!"
                ),
                color=discord.Color.gold()
            )
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="setup_roles", description="[Только Админы] Создать на сервере все ранговые роли Лиги")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def setup_roles(self, interaction: discord.Interaction):
        lang = locales.get_lang(interaction)
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(locales.t("error_admin_only", lang), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        me = interaction.guild.me
        if not me or not me.guild_permissions.manage_roles:
            err = (
                "❌ The bot does not have the **Manage Roles** permission! Please grant this permission to the bot in Server Settings."
                if lang == "en"
                else "❌ У бота нет права **«Управлять ролями» (Manage Roles)**! Пожалуйста, выдайте это право роли бота в Настройках сервера."
            )
            await interaction.followup.send(err)
            return

        created = await ensure_all_rank_roles(interaction.guild)
        if created:
            msg = (
                f"✨ Successfully created **{len(created)}** missing league roles:\n" + ", ".join(f"`{r}`" for r in created)
                if lang == "en"
                else f"✨ Успешно создано **{len(created)}** недостающих соревновательных ролей Лиги:\n" + ", ".join(f"`{r}`" for r in created)
            )
        else:
            msg = (
                "✅ All league roles already exist on this server!"
                if lang == "en"
                else "✅ Все соревновательные роли Лиги уже существуют на этом сервере!"
            )
        await interaction.followup.send(msg)

    @app_commands.command(name="setup_channels", description="[Только Админы] Создать категорию Лиги, канал файты-инфо и ветку 'бот'")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def setup_channels(self, interaction: discord.Interaction):
        lang = locales.get_lang(interaction)
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(locales.t("error_admin_only", lang), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        from cogs.matches import get_or_create_fights_channel
        ch = await get_or_create_fights_channel(interaction.guild, self.db)
        if ch:
            ch_type = "Форум" if isinstance(ch, discord.ForumChannel) else "Канал"
            msg = (
                f"✅ Fights {ch_type.lower()} is ready: {ch.mention} in category 🏆 GANGHUB LEAGUE!"
                if lang == "en"
                else f"✅ Соревновательный {ch_type.lower()} дуэлей готов: {ch.mention} в категории 🏆 GANGHUB LEAGUE!"
            )
        else:
            msg = (
                "❌ Failed to set up fights channel. Please check bot permissions (Manage Channels)."
                if lang == "en"
                else "❌ Не удалось создать форум-канал. Проверьте права бота (Управление каналами)."
            )
        await interaction.followup.send(msg)

    @app_commands.command(name="sync_roles", description="[Только Админы] Создать недостающие роли и синхронизировать ELO-ранги")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def sync_roles(self, interaction: discord.Interaction):
        lang = locales.get_lang(interaction)
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(locales.t("error_admin_only", lang), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        me = interaction.guild.me
        if not me or not me.guild_permissions.manage_roles:
            err = (
                "❌ The bot does not have the **Manage Roles** permission! Please grant this permission to the bot in Server Settings."
                if lang == "en"
                else "❌ У бота нет права **«Управлять ролями» (Manage Roles)**! Пожалуйста, выдайте это право роли бота в Настройках сервера."
            )
            await interaction.followup.send(err)
            return

        # 1. Автоматическое создание всех недостающих ролей Лиги
        created_roles = await ensure_all_rank_roles(interaction.guild)

        # 2. Синхронизация ролей участников
        leaders = await asyncio.to_thread(self.db.get_leaderboard, limit=100)
        updated_count = 0
        skipped_hierarchy = 0

        for idx, u in enumerate(leaders, start=1):
            member = interaction.guild.get_member(u["discord_id"])
            if not member:
                try:
                    member = await interaction.guild.fetch_member(u["discord_id"])
                except Exception:
                    member = None

            if member:
                total = u["wins"] + u["losses"]
                r_info = get_rank_info(u["rating"], u["rd"], total, idx, lang=lang)
                res = await sync_user_roles(member, r_info, interaction.guild)
                if res:
                    updated_count += 1
                    # Защита от Discord 429 Rate Limit (не более 10 правок ролей в секунду)
                    await asyncio.sleep(0.35)
                elif member.top_role >= me.top_role:
                    skipped_hierarchy += 1

        embed = discord.Embed(
            title="✅ Синхронизация ролей Лиги" if lang == "ru" else "✅ League Roles Synchronization",
            color=discord.Color.green()
        )
        if created_roles:
            embed.add_field(
                name="✨ Созданы недостающие роли на сервере" if lang == "ru" else "✨ Created Missing Roles",
                value=", ".join(f"`{r}`" for r in created_roles),
                inline=False
            )
        else:
            embed.add_field(
                name="🎭 Роли рангов" if lang == "ru" else "🎭 Rank Roles",
                value="Все соревновательные роли уже созданы на сервере." if lang == "ru" else "All competitive roles already exist on the server.",
                inline=False
            )

        embed.add_field(
            name="👥 Синхронизировано игроков" if lang == "ru" else "👥 Synchronized Players",
            value=f"**{updated_count}** чел.",
            inline=True
        )

        notes = []
        if skipped_hierarchy > 0:
            notes.append(
                f"• **Иерархия ролей:** пропущено **{skipped_hierarchy}** участников (их наивысшая роль выше роли бота)."
                if lang == "ru" else
                f"• **Role Hierarchy:** skipped **{skipped_hierarchy}** members (their top role is higher than the bot's)."
            )

        if notes:
            embed.add_field(
                name="ℹ️ Примечания" if lang == "ru" else "ℹ️ Notes",
                value="\n".join(notes),
                inline=False
            )

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="backup", description="[Только Админы] Создать резервную копию базы данных")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def backup(self, interaction: discord.Interaction):
        lang = locales.get_lang(interaction)
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(locales.t("error_admin_only", lang), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        from datetime import datetime, timezone
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(BACKUP_DIR, f"manual_backup_{timestamp}.sqlite")
        saved_path = await asyncio.to_thread(self.db.backup_db, backup_path)
        msg = f"💾 Database backup saved successfully:\n`{saved_path}`" if lang == "en" else f"💾 Резервная копия базы успешно сохранена:\n`{saved_path}`"
        await interaction.followup.send(msg, ephemeral=True)

    @app_commands.command(name="set_elo", description="[Только Админы] Экстренная ручная корректировка ELO игрока")
    @app_commands.describe(user="Игрок", rating="Новый рейтинг", reason="Причина изменения")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def set_elo(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        rating: float,
        reason: Optional[str] = None
    ):
        lang = locales.get_lang(interaction)
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(locales.t("error_admin_only", lang), ephemeral=True)
            return

        default_reason = "Manual admin adjustment" if lang == "en" else "Корректировка администратором"
        actual_reason = reason or default_reason

        await interaction.response.defer(ephemeral=True)
        rating = max(100.0, min(rating, 3000.0))
        u_data = await asyncio.to_thread(self.db.set_user_rating, user.id, rating, actual_reason)
        total = u_data["wins"] + u_data["losses"]
        pos = await asyncio.to_thread(self.db.get_user_rank_position, user.id) if total > 0 else None
        r_info = get_rank_info(u_data["rating"], u_data["rd"], total, pos, lang=lang)
        await sync_user_roles(user, r_info, interaction.guild)

        if lang == "en":
            reply_msg = f"✅ Set rating for {user.mention} to **{int(round(rating))} ELO** ({r_info['badge']} {r_info['tier']}).\nReason: *{actual_reason}*"
        else:
            reply_msg = f"✅ Игроку {user.mention} установлен рейтинг **{int(round(rating))} ELO** ({r_info['badge']} {r_info['tier']}).\nПричина: *{actual_reason}*"
        await interaction.followup.send(reply_msg, ephemeral=True)

    @app_commands.command(name="sync_commands", description="[Только Админы] Принудительно синхронизировать слэш-команды бота")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def sync_commands(self, interaction: discord.Interaction):
        lang = locales.get_lang(interaction)
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(locales.t("error_admin_only", lang), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        # Очищаем локальные команды гильдии для исключения дублирования
        if interaction.guild:
            self.bot.tree.clear_commands(guild=interaction.guild)
            await self.bot.tree.sync(guild=interaction.guild)
        synced = await self.bot.tree.sync()
        msg = (
            f"⚡ Successfully synced **{len(synced)}** global commands (duplicates removed)!"
            if lang == "en"
            else f"⚡ Успешно синхронизировано **{len(synced)}** глобальных команд (дубликаты удалены)!"
        )
        await interaction.followup.send(msg, ephemeral=True)

    @app_commands.command(name="link_user", description="[Только Админы] Принудительно привязать Roblox-аккаунт игроку")
    @app_commands.describe(user="Игрок Discord", roblox_username="Ник в Roblox")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def link_user(self, interaction: discord.Interaction, user: discord.Member, roblox_username: str):
        lang = locales.get_lang(interaction)
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(locales.t("error_admin_only", lang), ephemeral=True)
            return

        clean_nick = roblox_username.strip().lstrip("@")
        try:
            await asyncio.to_thread(self.db.link_roblox, user.id, clean_nick)
            msg = (
                f"✅ Игроку {user.mention} успешно привязан ник Roblox: `@{clean_nick}`.\n"
                f"Рейтинг, статистика и матчи сохранены в неизменном виде."
                if lang != "en"
                else f"✅ Successfully linked Roblox username `@{clean_nick}` to {user.mention}.\nRatings, stats, and matches preserved."
            )
            await interaction.response.send_message(msg, ephemeral=True)
        except ValueError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    @app_commands.command(name="sync_bloxlink_all", description="[Только Админы] Синхронизировать Roblox-ники всех игроков через Bloxlink")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def sync_bloxlink_all(self, interaction: discord.Interaction):
        lang = locales.get_lang(interaction)
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(locales.t("error_admin_only", lang), ephemeral=True)
            return

        api_key = bloxlink.get_bloxlink_key(self.db)
        if not api_key:
            await interaction.response.send_message(locales.t("bloxlink_status_inactive", lang), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT discord_id FROM users WHERE roblox_username IS NULL OR roblox_username = ''")
            rows = cursor.fetchall()

        if not rows:
            msg = "ℹ️ Все игроки в базе уже имеют привязанный аккаунт Roblox." if lang != "en" else "ℹ️ All players in database already have linked Roblox accounts."
            await interaction.followup.send(msg, ephemeral=True)
            return

        synced = 0
        failed = 0
        for row in rows:
            uid = row["discord_id"]
            try:
                res = await asyncio.to_thread(bloxlink.resolve_discord_to_roblox, interaction.guild_id, uid, api_key)
                if res:
                    _, auto_name = res
                    await asyncio.to_thread(self.db.link_roblox, uid, auto_name)
                    synced += 1
                else:
                    failed += 1
            except Exception:
                failed += 1

        msg = (
            f"🔄 **Синхронизация Bloxlink завершена!**\n\n"
            f"• Автоматически привязано: **{synced}**\n"
            f"• Не найдено в Bloxlink: **{failed}**\n\n"
            f"Все рейтинги, матчи и статистика сохранены без изменений!"
            if lang != "en"
            else (
                f"🔄 **Bloxlink Sync Complete!**\n\n"
                f"• Auto-linked: **{synced}**\n"
                f"• Not found in Bloxlink: **{failed}**\n\n"
                f"All ratings, matches, and stats preserved!"
            )
        )
        await interaction.followup.send(msg, ephemeral=True)

    duck_channel_group = app_commands.Group(
        name="duck_channel",
        description="Управление каналом для публикации логов даков (Duck Logs)",
        guild_only=True,
        default_permissions=discord.Permissions(administrator=True)
    )

    @duck_channel_group.command(name="set", description="[Только Админы] Назначить канал для публикации даков")
    @app_commands.describe(channel="Текстовый канал для логов даков (например: #даки)")
    async def duck_channel_set(self, interaction: discord.Interaction, channel: discord.TextChannel):
        lang = locales.get_lang(interaction)
        await asyncio.to_thread(self.db.set_setting, "duck_channel_id", str(channel.id))
        embed = discord.Embed(
            title="🦆 Duck Channel Configured" if lang == "en" else "🦆 Канал даков настроен",
            description=locales.t("duck_channel_set_success", lang, channel=channel.mention),
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @duck_channel_group.command(name="show", description="Показать текущий канал для логов даков")
    async def duck_channel_show(self, interaction: discord.Interaction):
        lang = locales.get_lang(interaction)
        setting_val = await asyncio.to_thread(self.db.get_setting, "duck_channel_id")
        fallback_text = "*(Not set manually, bot searches for a channel named 'даки' / 'duck')*" if lang == "en" else "*(Не задан вручную, бот ищет канал с именем 'даки' / 'duck')*"
        ch_mention = f"<#{setting_val}>" if setting_val else fallback_text
        embed = discord.Embed(
            title="🦆 Duck Channel" if lang == "en" else "🦆 Канал даков",
            description=locales.t("duck_channel_info", lang, channel=ch_mention),
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    results_channel_group = app_commands.Group(
        name="results_channel",
        description="Управление каналом для публикации результатов дуэлей (1v1s-elos)",
        guild_only=True,
        default_permissions=discord.Permissions(administrator=True)
    )

    @results_channel_group.command(name="set", description="[Только Админы] Назначить канал для публикации результатов матчей")
    @app_commands.describe(channel="Текстовый канал для результатов матчей (например: #1v1s-elos)")
    async def results_channel_set(self, interaction: discord.Interaction, channel: discord.TextChannel):
        lang = locales.get_lang(interaction)
        await asyncio.to_thread(self.db.set_setting, "match_results_channel_id", str(channel.id))
        embed = discord.Embed(
            title="⚔️ Match Results Channel Configured" if lang == "en" else "⚔️ Канал результатов настроен",
            description=locales.t("match_results_channel_set_success", lang, channel=channel.mention),
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @results_channel_group.command(name="show", description="Показать текущий канал для результатов матчей")
    async def results_channel_show(self, interaction: discord.Interaction):
        lang = locales.get_lang(interaction)
        setting_val = await asyncio.to_thread(self.db.get_setting, "match_results_channel_id")
        if not setting_val and getattr(config, "MATCH_RESULTS_CHANNEL_ID", None):
            setting_val = str(config.MATCH_RESULTS_CHANNEL_ID)
        fallback_text = "*(Not set, bot searches for '1v1s-elos' or similar)*" if lang == "en" else "*(Не задан, бот ищет канал '1v1s-elos' или похожий)*"
        ch_mention = f"<#{setting_val}>" if setting_val else fallback_text
        embed = discord.Embed(
            title="⚔️ Match Results Channel" if lang == "en" else "⚔️ Канал результатов матчей",
            description=locales.t("match_results_channel_info", lang, channel=ch_mention),
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    fights_channel_group = app_commands.Group(
        name="fights_channel",
        description="Управление форумом/каналом для создания дуэлей Лиги (elo-1v1)",
        guild_only=True,
        default_permissions=discord.Permissions(administrator=True)
    )

    @fights_channel_group.command(name="set", description="[Только Админы] Назначить форум/канал для дуэлей")
    @app_commands.describe(channel="Форум или текстовый канал для создания дуэлей")
    async def fights_channel_set(self, interaction: discord.Interaction, channel: Union[discord.ForumChannel, discord.TextChannel]):
        lang = locales.get_lang(interaction)
        await asyncio.to_thread(self.db.set_setting, "fights_channel_id", str(channel.id))
        embed = discord.Embed(
            title="⚔️ Fights Channel Configured" if lang == "en" else "⚔️ Канал дуэлей настроен",
            description=locales.t("fights_channel_set_success", lang, channel=channel.mention),
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @fights_channel_group.command(name="show", description="Показать текущий форум/канал для создания дуэлей")
    async def fights_channel_show(self, interaction: discord.Interaction):
        lang = locales.get_lang(interaction)
        setting_val = await asyncio.to_thread(self.db.get_setting, "fights_channel_id")
        if not setting_val and getattr(config, "FIGHTS_INFO_CHANNEL_ID", None):
            setting_val = str(config.FIGHTS_INFO_CHANNEL_ID)
        ch_mention = f"<#{setting_val}>" if setting_val else "*(По умолчанию: elo-1v1)*"
        embed = discord.Embed(
            title="⚔️ Fights Channel" if lang == "en" else "⚔️ Канал дуэлей Лиги",
            description=locales.t("fights_channel_info", lang, channel=ch_mention),
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="admin_country",
        description="[Только Админы] Установить или сбросить страну игрока без кд"
    )
    @app_commands.describe(
        user="Пользователь, которому нужно изменить страну",
        country="Код или название страны (или 'reset' для сброса)"
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def admin_country(self, interaction: discord.Interaction, user: discord.Member, country: str):
        lang = locales.get_lang(interaction)
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(locales.t("error_admin_only", lang), ephemeral=True)
            return

        choice = country.strip().upper()
        if choice in ("RESET", "NONE", "СБРОС", "CLEAR"):
            await asyncio.to_thread(self.db.admin_set_user_country, user.id, None)
            await interaction.response.send_message(
                f"✅ Страна для {user.mention} была успешно сброшена." if lang != "en" else f"✅ Country for {user.mention} has been reset.",
                ephemeral=True
            )
            return

        c_info = config.get_country_info(choice)
        if not c_info:
            await interaction.response.send_message(locales.t("country_invalid", lang), ephemeral=True)
            return

        await asyncio.to_thread(self.db.admin_set_user_country, user.id, choice)
        c_flag = c_info["flag"]
        c_name = c_info["name_ru" if lang != "en" else "name_en"]
        msg = (
            f"✅ Страна для {user.mention} успешно изменена на {c_flag} **{c_name}** (`{choice}`) без кулдауна!"
            if lang != "en" else
            f"✅ Successfully set country for {user.mention} to {c_flag} **{c_name}** (`{choice}`) without cooldown!"
        )
        await interaction.response.send_message(msg, ephemeral=True)

    @admin_country.autocomplete("country")
    async def admin_country_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        lang = locales.get_lang(interaction)
        query = current.lower().strip()
        choices: List[app_commands.Choice[str]] = []

        # Опция сброса
        if not query or any(k in query for k in ("reset", "сброс", "clear", "del", "none")):
            reset_label = "❌ Сбросить страну (Reset country)" if lang != "en" else "❌ Reset country"
            choices.append(app_commands.Choice(name=reset_label, value="RESET"))

        for code, info in config.COUNTRIES.items():
            name_ru = info["name_ru"].lower()
            name_en = info["name_en"].lower()
            code_lower = code.lower()
            flag = info["flag"]

            if not query or query in code_lower or query in name_ru or query in name_en:
                display_name = f"{flag} {info['name_ru' if lang != 'en' else 'name_en']} ({code})"
                choices.append(app_commands.Choice(name=display_name[:100], value=code))

            if len(choices) >= 25:
                break

        return choices


async def setup(bot: commands.Bot):
    pass

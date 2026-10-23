import asyncio
import time
from typing import Dict
import discord
from discord import app_commands
from discord.ext import commands, tasks
from database import Database
from config import QUEUE_CHANNEL_ID
from ranks import get_rank_info
from cogs.matches import get_or_create_fights_channel, CallRefView, get_resp_role
import bloxlink
import locales
from logger import log

QUEUE_TIMEOUT_SECONDS = 900  # 15 минут максимум в очереди

class QueueCog(commands.Cog):
    def __init__(self, bot: commands.Bot, db: Database):
        self.bot = bot
        self.db = db
        # Словарь очереди: {user_id: {"user": discord.Member, "joined_at": float, "rating": float}}
        self.queue: Dict[int, Dict] = {}
        self._cooldowns: Dict[int, float] = {}
        self._lock = asyncio.Lock()
        self.cleanup_task.start()
        self.bot.add_view(QueuePanelView(self))

    def cog_unload(self):
        self.cleanup_task.cancel()

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Если игрок покинул сервер — мгновенно удаляем его из очереди поиска"""
        async with self._lock:
            if member.id in self.queue:
                del self.queue[member.id]

    @tasks.loop(seconds=60)
    async def cleanup_task(self):
        """Фоновая очистка неактивных игроков из очереди (защита от призраков)"""
        try:
            now = time.time()
            expired_ids = []
            async with self._lock:
                for uid, data in list(self.queue.items()):
                    if now - data["joined_at"] > QUEUE_TIMEOUT_SECONDS:
                        expired_ids.append(uid)
                for uid in expired_ids:
                    if uid in self.queue:
                        del self.queue[uid]

                # Очистка старых кулдаунов
                old_cds = [uid for uid, t in self._cooldowns.items() if now - t > 10.0]
                for uid in old_cds:
                    del self._cooldowns[uid]
        except Exception as e:
            log.error(f"❌ [Ошибка cleanup_task]: {e}")

    @cleanup_task.error
    async def cleanup_error(self, error: Exception):
        log.critical(f"🚨 [Критический сбой cleanup_task]: {error}")

    @app_commands.command(name="queue", description="Встать в очередь поиска соперника 1v1 (быстрый поиск)")
    @app_commands.guild_only()
    async def queue_cmd(self, interaction: discord.Interaction):
        await self.join(interaction)

    @app_commands.command(name="quene", description="Встать в очередь поиска соперника 1v1 (быстрый поиск)")
    @app_commands.guild_only()
    async def quene_cmd(self, interaction: discord.Interaction):
        await self.join(interaction)

    @app_commands.command(name="leave", description="Покинуть очередь поиска соперника 1v1")
    @app_commands.guild_only()
    async def leave_cmd(self, interaction: discord.Interaction):
        await self.leave(interaction)

    @app_commands.command(name="queue_status", description="Посмотреть, кто сейчас ищет соперника в очереди")
    @app_commands.guild_only()
    async def queue_status_cmd(self, interaction: discord.Interaction):
        await self.status(interaction)

    @app_commands.command(name="queue_panel", description="[Только Админы] Отправить интерактивную панель с кнопками в этот канал")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def queue_panel_cmd(self, interaction: discord.Interaction):
        await self.setup_panel(interaction)

    async def join(self, interaction: discord.Interaction):
        lang = locales.get_lang(interaction)
        if not interaction.guild:
            await interaction.response.send_message(locales.t("error_guild_only", lang), ephemeral=True)
            return

        if interaction.user.bot:
            await interaction.response.send_message(locales.t("error_bot_user", lang), ephemeral=True)
            return

        # Ограничение по каналу (если настроен QUEUE_CHANNEL_ID)
        if QUEUE_CHANNEL_ID and interaction.channel_id != QUEUE_CHANNEL_ID:
            await interaction.response.send_message(
                locales.t("queue_channel_warn", lang, channel=QUEUE_CHANNEL_ID),
                ephemeral=True
            )
            return

        user_id = interaction.user.id
        now = time.time()

        # Защита от спама и макросов
        if user_id in self._cooldowns and now - self._cooldowns[user_id] < 3.0:
            await interaction.response.send_message(locales.t("queue_cooldown", lang), ephemeral=True)
            return
        self._cooldowns[user_id] = now

        # Защита от 3-секундного таймаута Discord (10062 Unknown Interaction)
        await interaction.response.defer(ephemeral=True)

        # Проверка привязки Roblox (Bloxlink)
        u_data = await asyncio.to_thread(self.db.get_or_create_user, user_id)
        if not u_data.get("roblox_username"):
            # Пробуем автоматически связать через Bloxlink
            api_key = bloxlink.get_bloxlink_key(self.db)
            linked = False
            if api_key and interaction.guild_id:
                res = await asyncio.to_thread(bloxlink.resolve_discord_to_roblox, interaction.guild_id, user_id, api_key)
                if res:
                    _, auto_name = res
                    try:
                        u_data = await asyncio.to_thread(self.db.link_roblox, user_id, auto_name)
                        linked = True
                    except Exception:
                        pass
            if not linked and not u_data.get("roblox_username"):
                view = discord.ui.View()
                btn_lbl = "Verify on blox.link" if lang == "en" else "Пройти верификацию на blox.link"
                view.add_item(discord.ui.Button(label=btn_lbl, url="https://blox.link/verify", style=discord.ButtonStyle.link, emoji="🔗"))
                await interaction.followup.send(
                    "⚠️ **Требуется верификация Roblox!**\n"
                    "Для участия в рейтинговой очереди ваш аккаунт Roblox должен быть подтвержден.\n"
                    "Используйте команду `/link`, чтобы синхронизировать свой профиль через Bloxlink.",
                    view=view,
                    ephemeral=True
                )
                return

        user_rating = u_data["rating"]

        async with self._lock:
            if user_id in self.queue:
                await interaction.followup.send(locales.t("queue_already_in", lang), ephemeral=True)
                return
            queue_snapshot = list(self.queue.items())

        # Проверка лимитов матчей (can_play_match) вне удержания глобального лока очереди
        eligible_candidates = []
        for queued_id, queued_data in queue_snapshot:
            can_play, _ = await asyncio.to_thread(self.db.can_play_match, user_id, queued_id)
            if can_play:
                diff = abs(queued_data["rating"] - user_rating)
                eligible_candidates.append((diff, queued_id))

        eligible_candidates.sort(key=lambda x: x[0])

        opponent = None
        opponent_rating = 0.0
        match_found = False

        async with self._lock:
            if user_id in self.queue:
                await interaction.followup.send(locales.t("queue_already_in", lang), ephemeral=True)
                return

            # Ищем наилучшего соперника, который все еще находится в очереди
            for _, candidate_id in eligible_candidates:
                if candidate_id in self.queue:
                    opponent_data = self.queue.pop(candidate_id)
                    opponent = opponent_data["user"]
                    opponent_rating = opponent_data["rating"]
                    match_found = True
                    break

            if not match_found:
                self.queue[user_id] = {
                    "user": interaction.user,
                    "joined_at": time.time(),
                    "rating": user_rating
                }

        if match_found and opponent:
            p1_pos = await asyncio.to_thread(self.db.get_user_rank_position, interaction.user.id)
            p2_pos = await asyncio.to_thread(self.db.get_user_rank_position, opponent.id)
            p1_rank = get_rank_info(user_rating, u_data.get("rd", 350.0), u_data["wins"] + u_data["losses"], p1_pos, lang=lang)

            p2_data = await asyncio.to_thread(self.db.get_or_create_user, opponent.id)
            p2_rank = get_rank_info(opponent_rating, p2_data.get("rd", 350.0), p2_data["wins"] + p2_data["losses"], p2_pos, lang=lang)

            p1_rbx = u_data.get("roblox_username") or ("not linked" if lang == "en" else "не привязан")
            p2_rbx = p2_data.get("roblox_username") or ("not linked" if lang == "en" else "не привязан")
            diff = int(round(abs(user_rating - opponent_rating)))

            # 1. Авто-выделение свободного VIP-сервера Лиги
            free_slot, free_url = await asyncio.to_thread(self.db.get_available_league_vip)
            p1_vip = await asyncio.to_thread(self.db.get_user_vip, interaction.user.id)
            p2_vip = await asyncio.to_thread(self.db.get_user_vip, opponent.id)

            vip_btn_view = CallRefView(interaction.user.id, opponent.id, lang=lang, vip_info=free_url or "")
            join_vip_label = "Войти на сервер" if lang != "en" else "Join Server"
            vip_lines = []
            if free_slot and free_url:
                vip_lines.append(f"• 🟢 **Официальный VIP Лиги:** **VIP {free_slot}** ➔ [{join_vip_label}]({free_url})")
                vip_btn_view.add_item(discord.ui.Button(label=f"VIP {free_slot} (Играть)", url=free_url, style=discord.ButtonStyle.link, emoji="🌐"))
            elif p1_vip:
                vip_lines.append(f"• **VIP {interaction.user.display_name}:** [{join_vip_label}]({p1_vip})")
                vip_btn_view.add_item(discord.ui.Button(label=f"VIP: {interaction.user.display_name[:12]}", url=p1_vip, style=discord.ButtonStyle.link, emoji="🔗"))
            elif p2_vip:
                vip_lines.append(f"• **VIP {opponent.display_name}:** [{join_vip_label}]({p2_vip})")
                vip_btn_view.add_item(discord.ui.Button(label=f"VIP: {opponent.display_name[:12]}", url=p2_vip, style=discord.ButtonStyle.link, emoji="🔗"))
            else:
                vip_lines.append("• ⚠️ *(Используйте личный VIP через `/vip set` или играйте на 1v1 сервере YBA)*" if lang != "en" else "• ⚠️ *(Use personal VIP with `/vip set` or play on YBA 1v1 server)*")

            vip_block = "\n".join(vip_lines)

            if lang == "en":
                embed = discord.Embed(
                    title="⚔️ OPPONENT FOUND • 1v1 MATCHMAKING",
                    description=(
                        f"🔴 **Player 1:** {interaction.user.mention} (`{p1_rbx}`)\n"
                        f"╰ **Rank:** {p1_rank['badge']} **{p1_rank['tier']}** • `{int(round(user_rating))} ELO`\n\n"
                        f"⚔️ **VS** ⚔️\n\n"
                        f"🔵 **Player 2:** {opponent.mention} (`{p2_rbx}`)\n"
                        f"╰ **Rank:** {p2_rank['badge']} **{p2_rank['tier']}** • `{int(round(opponent_rating))} ELO`\n\n"
                        f"⚖️ **Rating Difference:** ±{diff} ELO\n\n"
                        f"🕹️ **VIP Servers:**\n{vip_block}\n\n"
                        f"📖 *Call referee via button below or record proof for `/report`!*"
                    ),
                    color=discord.Color.gold()
                )
                embed.set_footer(text="GANGHUB League 1v1 • Match Scheduled")
            else:
                embed = discord.Embed(
                    title="⚔️ СОПЕРНИК НАЙДЕН • 1v1 MATCHMAKING",
                    description=(
                        f"🔴 **Игрок 1:** {interaction.user.mention} (`{p1_rbx}`)\n"
                        f"╰ **Ранг:** {p1_rank['badge']} **{p1_rank['tier']}** • `{int(round(user_rating))} ELO`\n\n"
                        f"⚔️ **VS** ⚔️\n\n"
                        f"🔵 **Игрок 2:** {opponent.mention} (`{p2_rbx}`)\n"
                        f"╰ **Ранг:** {p2_rank['badge']} **{p2_rank['tier']}** • `{int(round(opponent_rating))} ELO`\n\n"
                        f"⚖️ **Разница в рейтинге:** ±{diff} ELO\n\n"
                        f"🕹️ **VIP-серверы дуэли:**\n{vip_block}\n\n"
                        f"📖 *Вызовите Респонсибла кнопкой ниже или зафиксируйте результат через `/report`!*"
                    ),
                    color=discord.Color.gold()
                )
                embed.set_footer(text="GANGHUB League 1v1 • Дуэль назначена")

            # 2. Создаем регламентную ветку в форуме Лиги
            fights_channel = await get_or_create_fights_channel(interaction.guild, self.db)
            created_thread = None
            target_chan_id = interaction.channel_id
            target_msg_id = 0
            resp_role = get_resp_role(interaction.guild)
            resp_mention = resp_role.mention if resp_role else "@1v1s Responsible"

            if isinstance(fights_channel, discord.ForumChannel):
                try:
                    t_name = f"⚔️・{interaction.user.display_name[:10]} vs {opponent.display_name[:10]}"
                    thread_with_msg = await fights_channel.create_thread(
                        name=t_name,
                        content=f"{interaction.user.mention} {opponent.mention} {resp_mention}",
                        embed=embed,
                        view=vip_btn_view,
                        auto_archive_duration=1440
                    )
                    created_thread = thread_with_msg.thread
                    target_chan_id = created_thread.id
                    target_msg_id = thread_with_msg.message.id
                except Exception as e:
                    log.warning(f"⚠️ Не удалось создать ветку подбора в форуме: {e}")

            # 3. Фиксируем матч в БД и бронируем VIP-слот
            cid = await asyncio.to_thread(
                self.db.create_challenge,
                guild_id=interaction.guild_id,
                channel_id=target_chan_id,
                message_id=target_msg_id,
                challenger_id=interaction.user.id,
                challenged_id=opponent.id,
                format="T1 - Any vs Any (Queue)",
                server="Hesse (Германия)"
            )
            await asyncio.to_thread(self.db.update_challenge_status, cid, "accepted")
            if free_slot:
                await asyncio.to_thread(
                    self.db.reserve_league_vip,
                    str(free_slot),
                    cid,
                    target_chan_id,
                    interaction.user.id,
                    opponent.id
                )

            # 4. Отправляем уведомление в канал поиска с удобными кнопками перехода
            queue_notify_view = discord.ui.View()
            if created_thread:
                queue_notify_view.add_item(discord.ui.Button(label="Перейти в ветку дуэли", url=created_thread.jump_url, style=discord.ButtonStyle.link, emoji="⚔️"))
            if free_url:
                queue_notify_view.add_item(discord.ui.Button(label=f"VIP {free_slot} (Играть)", url=free_url, style=discord.ButtonStyle.link, emoji="🌐"))

            thread_line = f"\n\n⚔️ **Ветка дуэли:** {created_thread.mention}!" if created_thread else ""
            embed.description += thread_line

            await interaction.channel.send(content=f"{interaction.user.mention} {opponent.mention}", embed=embed, view=queue_notify_view)
            await interaction.followup.send(locales.t("queue_match_found_notify", lang), ephemeral=True)
        else:
            p1_pos = await asyncio.to_thread(self.db.get_user_rank_position, user_id)
            p1_rank = get_rank_info(user_rating, u_data.get("rd", 350.0), u_data["wins"] + u_data["losses"], p1_pos, lang=lang)

            if lang == "en":
                embed = discord.Embed(
                    title="🟢 YOU JOINED THE 1v1 QUEUE",
                    description=(
                        f"• **Your rating:** {p1_rank['badge']} **{p1_rank['tier']}** (`{int(round(user_rating))} ELO`)\n"
                        f"• **Currently in queue:** **{len(self.queue)} player(s)**\n\n"
                        f"⏳ *The bot is searching for an opponent with a similar ELO. Once found, you will be mentioned here.*"
                    ),
                    color=discord.Color.blue()
                )
                embed.set_footer(text="GANGHUB League • Matchmaking Active")
            else:
                embed = discord.Embed(
                    title="🟢 ВЫ ВСТАЛИ В ОЧЕРЕДЬ 1v1",
                    description=(
                        f"• **Ваш рейтинг:** {p1_rank['badge']} **{p1_rank['tier']}** (`{int(round(user_rating))} ELO`)\n"
                        f"• **Сейчас в поиске:** **{len(self.queue)} игрок(ов)**\n\n"
                        f"⏳ *Бот ищет подходящего оппонента с близким ELO. Как только соперник будет найден, вы получите звуковое упоминание.*"
                    ),
                    color=discord.Color.blue()
                )
                embed.set_footer(text="GANGHUB League • Поиск активен")

            # Отправляем сообщение о входе в очередь приватно, чтобы не захламлять чат спамом
            await interaction.followup.send(embed=embed, ephemeral=True)

    async def leave(self, interaction: discord.Interaction):
        lang = locales.get_lang(interaction)
        user_id = interaction.user.id
        now = time.time()
        if user_id in self._cooldowns and now - self._cooldowns[user_id] < 2.0:
            await interaction.response.send_message(locales.t("queue_cooldown", lang), ephemeral=True)
            return
        self._cooldowns[user_id] = now

        async with self._lock:
            if user_id in self.queue:
                del self.queue[user_id]
                await interaction.response.send_message(locales.t("queue_left", lang), ephemeral=True)
            else:
                await interaction.response.send_message(locales.t("queue_not_in", lang), ephemeral=True)

    async def status(self, interaction: discord.Interaction):
        lang = locales.get_lang(interaction)
        async with self._lock:
            if not self.queue:
                embed = discord.Embed(
                    title=locales.t("queue_status_empty_title", lang),
                    description=locales.t("queue_status_empty_desc", lang),
                    color=discord.Color.light_grey()
                )
                await interaction.response.send_message(embed=embed)
                return

            embed = discord.Embed(
                title=locales.t("queue_status_title", lang),
                description=locales.t("queue_status_count", lang, count=len(self.queue)),
                color=discord.Color.blue()
            )

            lines = []
            items = list(self.queue.items())
            for q_id, q_data in items[:15]:
                wait_sec = int(time.time() - q_data["joined_at"])
                waiting_str = locales.t("queue_status_waiting", lang, sec=wait_sec)
                lines.append(f"• <@{q_id}> — `{int(round(q_data['rating']))} ELO` *({waiting_str})*")

            if len(items) > 15:
                lines.append(f"\n*... and {len(items) - 15} more player(s) in queue*" if lang == "en" else f"\n*... и еще {len(items) - 15} игрок(ов) в поиске*")

        embed.description += "\n".join(lines)
        await interaction.response.send_message(embed=embed)

    async def setup_panel(self, interaction: discord.Interaction):
        lang = locales.get_lang(interaction)
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(locales.t("error_admin_only", lang), ephemeral=True)
            return

        if lang == "en":
            embed = discord.Embed(
                title="⚔️ COMPETITIVE 1v1 LEAGUE • GANGHUB",
                description=(
                    "Welcome to automated competitive YBA matchmaking!\n\n"
                    "### 📜 RULES & RATING\n"
                    "• **ELO Matchmaking:** The bot matches you with opponents of similar Glicko-2 rating.\n"
                    "• **Calibration:** First 5 matches have increased multiplier (up to **±162 points** per match).\n"
                    "• **Rank Ladder:** Winning awards Discord roles from 🥉 **Bronze** to 👑 **Grandmaster**.\n"
                    "• **Fair Play:** Limit of 2 matches per day between the same two players.\n\n"
                    "### 🕹️ HOW TO PLAY?\n"
                    "1. Make sure your Roblox account is linked (`/link` command).\n"
                    "2. Click the **Join Queue ⚔️** button below.\n"
                    "3. Once an opponent is found, the bot will tag both of you!"
                ),
                color=discord.Color.gold()
            )
            embed.set_footer(text="GANGHUB League 1v1 • Click button below to start")
            success_msg = "✅ Interactive matchmaking panel created successfully!"
        else:
            embed = discord.Embed(
                title="⚔️ СОРЕВНОВАТЕЛЬНАЯ ЛИГА 1v1 • GANGHUB",
                description=(
                    "Добро пожаловать в автоматический рейтинговый подбор матчей YBA!\n\n"
                    "### 📜 ПРАВИЛА И РЕЙТИНГ\n"
                    "• **Подбор по ELO:** Бот находит соперника с близким рейтингом Glicko-2.\n"
                    "• **Калибровка:** Первые 5 матчей с увеличенным коэффициентом (до **±162 очка** за матч).\n"
                    "• **Ранговая лестница:** За победы автоматически выдаются роли от 🥉 **Bronze** до 👑 **Grandmaster**.\n"
                    "• **Честная игра:** Лимит повторных матчей — не более 2 раз в сутки между одной парой игроков.\n\n"
                    "### 🕹️ КАК НАЧАТЬ ИГРАТЬ?\n"
                    "1. Убедитесь, что ваш Roblox привязан (команда `/link`).\n"
                    "2. Нажмите кнопку **Встать в очередь ⚔️** ниже.\n"
                    "3. Как только соперник найдется, бот создаст уведомление и тегнет вас!"
                ),
                color=discord.Color.gold()
            )
            embed.set_footer(text="GANGHUB League 1v1 • Нажмите кнопку ниже для старта")
            success_msg = "✅ Интерактивная панель поиска успешно установлена!"

        if interaction.guild and interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        view = QueuePanelView(self, lang=lang)
        await interaction.channel.send(embed=embed, view=view)
        await interaction.response.send_message(success_msg, ephemeral=True)

    @commands.command(name="queue", aliases=["quene", "q", "очередь"])
    @commands.guild_only()
    async def prefix_queue(self, ctx: commands.Context):
        """Префиксная подсказка !queue / !quene"""
        lang = locales.get_user_lang(self.db, ctx.author.id, fallback="ru")
        txt = (
            "⚔️ **Поиск матча 1v1 (Очередь):**\n"
            "• Встать в очередь: слэш-команда `/queue` или `/quene`\n"
            "• Выйти из очереди: `/leave`\n"
            "• Посмотреть статус: `/queue_status`"
            if lang == "ru" else
            "⚔️ **1v1 Matchmaking Queue:**\n"
            "• Join queue: slash command `/queue` or `/quene`\n"
            "• Leave queue: `/leave`\n"
            "• View status: `/queue_status`"
        )
        await ctx.reply(txt)


class QueuePanelView(discord.ui.View):
    def __init__(self, queue_cog: QueueCog, lang: str = "ru"):
        super().__init__(timeout=None) # Persistent view: работает вечно
        self.queue_cog = queue_cog
        if lang == "en":
            self.btn_join.label = "Join Queue"
            self.btn_leave.label = "Leave Queue"

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item):
        """Безопасный перехват ошибок интерактивных кнопок без краша UI"""
        msg = "❌ An error occurred while processing the button. Please try again." if locales.get_lang(interaction) == "en" else "❌ Произошла ошибка при обработке нажатия кнопки. Попробуйте еще раз."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass

    @discord.ui.button(label="Встать в очередь", style=discord.ButtonStyle.green, emoji="⚔️", custom_id="yba_btn_queue_join")
    async def btn_join(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.queue_cog.join(interaction)

    @discord.ui.button(label="Покинуть очередь", style=discord.ButtonStyle.red, emoji="❌", custom_id="yba_btn_queue_leave")
    async def btn_leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.queue_cog.leave(interaction)

async def setup(bot: commands.Bot):
    pass

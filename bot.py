import sys
import signal
import asyncio
from typing import Optional

import discord
from discord.ext import commands, tasks

from config import DISCORD_TOKEN, GUILD_ID, GUILD_IDS, ENABLE_MESSAGE_CONTENT, ENABLE_MEMBERS_INTENT
from database import Database
from cogs.ranked import RankedCog
from cogs.matches import MatchesCog
from cogs.queue import QueueCog
from cogs.admin import AdminCog
from cogs.fun import FunCog
from logger import log

def get_bot_intents() -> discord.Intents:
    intents = discord.Intents.default()
    intents.voice_states = True
    if ENABLE_MESSAGE_CONTENT:
        intents.message_content = True
    if ENABLE_MEMBERS_INTENT:
        intents.members = True
    return intents

class YBAEloBot(commands.Bot):
    def __init__(self, intents: Optional[discord.Intents] = None):
        bot_intents = intents or get_bot_intents()
        super().__init__(command_prefix="!", intents=bot_intents)
        self.db = Database()

    @tasks.loop(hours=24)
    async def daily_decay_task(self):
        """Ежедневный фоновый демон: начисляет распад RD неактивным игрокам"""
        try:
            updated = await asyncio.to_thread(self.db.apply_inactivity_decay_all)
            if updated > 0:
                log.info(f"📉 [Анти-кемпинг] Обработан распад RD для неактивных игроков: {updated} чел.")
        except Exception as e:
            log.error(f"❌ [Ошибка демона анти-кемпинга]: {e}")

    @daily_decay_task.error
    async def daily_decay_error(self, error: Exception):
        log.critical(f"🚨 [Критический сбой daily_decay_task]: {error}")

    @daily_decay_task.before_loop
    async def before_daily_decay(self):
        await self.wait_until_ready()

    @tasks.loop(hours=12)
    async def daily_backup_task(self):
        """Регулярный фоновый бэкап базы данных (zero-downtime SQLite online backup)"""
        try:
            bck_path = await asyncio.to_thread(self.db.backup_database)
            log.info(f"💾 [Авто-бэкап] Резервная копия базы успешно создана: {bck_path}")
        except Exception as e:
            log.error(f"❌ [Ошибка демона авто-бэкапа]: {e}")

    @daily_backup_task.error
    async def daily_backup_error(self, error: Exception):
        log.error(f"❌ [Сбой daily_backup_task]: {error}")

    @daily_backup_task.before_loop
    async def before_daily_backup(self):
        await self.wait_until_ready()

    async def setup_hook(self):
        # Добавление когов
        await self.add_cog(RankedCog(self, self.db))
        await self.add_cog(MatchesCog(self, self.db))
        await self.add_cog(QueueCog(self, self.db))
        await self.add_cog(AdminCog(self, self.db))
        await self.add_cog(FunCog(self, self.db))

        # Запуск фоновых демонов
        self.daily_decay_task.start()
        self.daily_backup_task.start()

        # Глобальный перехватчик ошибок для всех слэш-команд
        async def on_tree_error(interaction: discord.Interaction, error: Exception):
            cmd_name = interaction.command.name if interaction.command else "Unknown"
            log.warning(f"⚠️ [Ошибка команды {cmd_name}]: {error}")
            err_msg = "❌ Произошла ошибка при обработке команды. Попробуйте позже."
            if isinstance(error, discord.app_commands.errors.CheckFailure):
                err_msg = "❌ У вас нет прав на использование этой команды."

            try:
                if interaction.response.is_done():
                    await interaction.followup.send(err_msg, ephemeral=True)
                else:
                    await interaction.response.send_message(err_msg, ephemeral=True)
            except Exception:
                pass

        self.tree.on_error = on_tree_error

        # Очистка локальных дубликатов команд гильдии, чтобы не было задвоения с глобальными командами
        if GUILD_IDS:
            for gid in GUILD_IDS:
                try:
                    guild_obj = discord.Object(id=gid)
                    self.tree.clear_commands(guild=guild_obj)
                    await self.tree.sync(guild=guild_obj)
                    log.info(f"🧹 [Синхронизация] Очищены локальные команды для сервера {gid} во избежание дубликатов")
                except Exception as e:
                    log.warning(f"⚠️ Не удалось очистить локальные команды для сервера {gid}: {e}")

        try:
            glob_synced = await self.tree.sync()
            log.info(f"🌍 [Синхронизация] Синхронизировано {len(glob_synced)} глобальных слэш-команд")
        except Exception as e:
            log.warning(f"⚠️ Не удалось синхронизировать глобальные команды: {e}")

    async def on_ready(self):
        season = self.db.get_active_season()
        log.info("=" * 55)
        log.info(f"🤖 Бот запущен как: {self.user.name} (ID: {self.user.id})")
        log.info(f"🏆 Текущий активный сезон: {season['name']} (ID: #{season['id']})")
        log.info("♟️ Рейтинговая система Glicko-2 готова к работе!")
        log.info("=" * 55)

        # Статус бота
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.competing,
                name="1v1 YBA Ranked | /profile"
            )
        )

        # Автоматическая инициализация соревновательной категории и форум-канала Лиги
        from cogs.matches import get_or_create_fights_channel
        for g in self.guilds:
            try:
                ch = await get_or_create_fights_channel(g, self.db)
                if ch:
                    log.info(f"⚔️ [Лига GANGHUB] Форум/канал '{ch.name}' готов (Сервер: {g.name})")
            except Exception as e:
                log.warning(f"⚠️ Не удалось инициализировать канал Лиги на сервере {g.id}: {e}")

    async def close(self):
        log.info("🔌 Безопасное завершение работы бота: сохранение WAL и закрытие БД...")
        try:
            self.daily_decay_task.cancel()
        except Exception:
            pass
        try:
            self.daily_backup_task.cancel()
        except Exception:
            pass
        ranked_cog = self.get_cog("RankedCog")
        if ranked_cog:
            ranked_cog.cog_unload()
        self.db.close()
        await super().close()
        log.info("✅ База данных и сессии бота закрыты корректно.")

async def run_bot():
    if not DISCORD_TOKEN:
        log.critical("❌ ОШИБКА: DISCORD_TOKEN не указан в файле .env!")
        log.info("💡 Создайте файл .env на основе .env.example и укажите токен вашего Discord бота.")
        sys.exit(1)

    intents = get_bot_intents()
    bot = YBAEloBot(intents=intents)

    loop = asyncio.get_running_loop()

    def handle_signal(sig_name: str):
        log.info(f"🛑 Получен системный сигнал {sig_name}, инициируется завершение работы...")
        asyncio.create_task(bot.close())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, handle_signal, sig.name)
        except (NotImplementedError, RuntimeError):
            pass

    async with bot:
        await bot.start(DISCORD_TOKEN)

def main():
    try:
        asyncio.run(run_bot())
    except (KeyboardInterrupt, SystemExit):
        pass

if __name__ == "__main__":
    main()

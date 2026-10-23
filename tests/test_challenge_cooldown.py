import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import time
import discord
from discord.ext import commands

from database import Database
from cogs.matches import MatchesCog, ChallengeView
import config


class TestChallengeCooldown(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        intents = discord.Intents.default()
        self.bot = commands.Bot(command_prefix="!", intents=intents)
        self.db = Database(":memory:")
        self.cog = MatchesCog(self.bot, self.db)
        await self.bot.add_cog(self.cog)

    async def asyncTearDown(self):
        self.db.close()
        await self.bot.close()

    def test_database_challenge_queries(self):
        """Проверка методов БД для отслеживания последнего вызова и количества ожидающих вызовов"""
        # Создаем пользователей
        self.db.get_or_create_user(101, "Player1")
        self.db.get_or_create_user(102, "Player2")
        self.db.get_or_create_user(103, "Player3")

        # 0 вызовов изначально
        self.assertEqual(self.db.get_pending_challenges_count_for_user(101), 0)
        self.assertIsNone(self.db.get_last_challenge_by_challenger(101))

        # Создаем вызов
        cid = self.db.create_challenge(
            guild_id=1,
            channel_id=10,
            message_id=100,
            challenger_id=101,
            challenged_id=102,
            format="T1",
            server="Hesse"
        )
        self.assertEqual(self.db.get_pending_challenges_count_for_user(101), 1)

        last_ch = self.db.get_last_challenge_by_challenger(101)
        self.assertIsNotNone(last_ch)
        self.assertEqual(last_ch["id"], cid)
        self.assertEqual(last_ch["challenged_id"], 102)

        # Завершаем вызов
        self.db.update_challenge_status(cid, "finished")
        self.assertEqual(self.db.get_pending_challenges_count_for_user(101), 0)

    async def test_challenge_cooldown_blocks_second_creation(self):
        """Проверка: игрок на кулдауне не может создать повторный вызов"""
        guild = MagicMock(spec=discord.Guild)
        guild.id = 12345

        user1 = MagicMock(spec=discord.Member)
        user1.id = 1001
        user1.guild_permissions.administrator = False
        user1.mention = "<@1001>"

        target = MagicMock(spec=discord.Member)
        target.id = 2002
        target.bot = False
        target.mention = "<@2002>"

        # Имитируем активный кулдаун (вызов создан 5 секунд назад при кулдауне 600 сек)
        self.cog._challenge_cooldowns[1001] = time.time() - 5.0

        interaction = MagicMock(spec=discord.Interaction)
        interaction.user = user1
        interaction.guild = guild
        interaction.locale = discord.Locale.russian
        interaction.response = MagicMock()
        interaction.response.send_message = AsyncMock()

        # Вызываем команду /challenge
        await self.cog.challenge.callback(self.cog, interaction, target)

        interaction.response.send_message.assert_called_once()
        args, kwargs = interaction.response.send_message.call_args
        msg_text = args[0] if args else kwargs.get("content", "")
        self.assertIn("Кулдаун на создание вызовов", msg_text)
        self.assertTrue(kwargs.get("ephemeral", False))

    async def test_challenge_pending_limit_blocks_spam(self):
        """Проверка: нельзя бросить новый вызов, если уже висит открытый ожидающий вызов"""
        guild = MagicMock(spec=discord.Guild)
        guild.id = 12345

        user1 = MagicMock(spec=discord.Member)
        user1.id = 1001
        user1.guild_permissions.administrator = False
        user1.mention = "<@1001>"

        target = MagicMock(spec=discord.Member)
        target.id = 2002
        target.bot = False
        target.mention = "<@2002>"

        # Создаем активный pending вызов в БД
        self.db.create_challenge(
            guild_id=12345,
            channel_id=10,
            message_id=100,
            challenger_id=1001,
            challenged_id=9999,
            format="T2",
            server="Hesse"
        )

        interaction = MagicMock(spec=discord.Interaction)
        interaction.user = user1
        interaction.guild = guild
        interaction.locale = discord.Locale.russian
        interaction.response = MagicMock()
        interaction.response.send_message = AsyncMock()

        # Вызываем команду /challenge
        await self.cog.challenge.callback(self.cog, interaction, target)

        interaction.response.send_message.assert_called_once()
        args, kwargs = interaction.response.send_message.call_args
        msg_text = args[0] if args else kwargs.get("content", "")
        self.assertIn("Лимит активных вызовов", msg_text)
        self.assertTrue(kwargs.get("ephemeral", False))

    async def test_admin_bypasses_challenge_cooldown(self):
        """Проверка: администраторы игнорируют кулдаун на вызовы"""
        guild = MagicMock(spec=discord.Guild)
        guild.id = 12345

        admin = MagicMock(spec=discord.Member)
        admin.id = 777
        admin.guild_permissions.administrator = True
        admin.mention = "<@777>"

        target = MagicMock(spec=discord.Member)
        target.id = 2002
        target.bot = False
        target.mention = "<@2002>"

        # У админа висит в памяти кулдаун
        self.cog._challenge_cooldowns[777] = time.time()

        interaction = MagicMock(spec=discord.Interaction)
        interaction.user = admin
        interaction.guild = guild
        interaction.locale = discord.Locale.russian
        interaction.response = MagicMock()
        interaction.response.send_message = AsyncMock()

        # Создаем мок ответа до шага создания темы, проверяя, что сообщение об ошибке кулдауна НЕ вызывалось
        self.db.get_or_create_user(777, "AdminRbx")
        self.db.get_or_create_user(2002, "TargetRbx")

        with patch("cogs.matches.get_or_create_fights_channel", return_value=None):
            await self.cog.challenge.callback(self.cog, interaction, target)

        # Сообщение о кулдауне не отправлялось
        if interaction.response.send_message.called:
            args, kwargs = interaction.response.send_message.call_args
            msg_text = args[0] if args else kwargs.get("content", "")
            self.assertNotIn("Кулдаун на создание вызовов", msg_text)

    async def test_resolve_challenge_fallback_to_channel_and_id(self):
        """Проверка: _resolve_challenge успешно находит вызов по channel_id и challenge_id"""
        cid = self.db.create_challenge(
            guild_id=123,
            channel_id=5555,
            message_id=9999,
            challenger_id=101,
            challenged_id=102,
            format="T2 - Main vs Main",
            server="Hesse"
        )

        view = ChallengeView(bot=self.bot, db=self.db, challenge_id=cid)
        interaction = MagicMock(spec=discord.Interaction)
        interaction.channel_id = 5555
        interaction.channel = MagicMock(spec=discord.TextChannel)
        interaction.channel.parent_id = None
        # Сообщение с другим ID (например, после эдита или в треде)
        interaction.message = MagicMock(spec=discord.Message)
        interaction.message.id = 8888
        interaction.message.content = ""
        interaction.message.embeds = []

        resolved = await view._resolve_challenge(interaction)
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["id"], cid)

    async def test_resolve_challenge_fallback_to_participants(self):
        """Проверка: _resolve_challenge находит вызов по участникам из эмбеда сообщения"""
        cid = self.db.create_challenge(
            guild_id=123,
            channel_id=1111,
            message_id=2222,
            challenger_id=301,
            challenged_id=302,
            format="T2 - Main vs Main",
            server="Hesse"
        )

        # Новый view без сохраненного challenge_id (как после перезапуска бота)
        view = ChallengeView(bot=self.bot, db=self.db)
        interaction = MagicMock(spec=discord.Interaction)
        interaction.channel_id = 999999  # Не совпадает
        interaction.channel = MagicMock(spec=discord.TextChannel)
        interaction.channel.parent_id = None
        interaction.message = MagicMock(spec=discord.Message)
        interaction.message.id = 888888  # Не совпадает
        interaction.message.content = "<@301> challenges <@302>"
        interaction.message.embeds = []

        resolved = await view._resolve_challenge(interaction)
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["id"], cid)

    async def test_resolve_challenge_auto_recovery_when_missing_from_db(self):
        """Проверка: _resolve_challenge автоматически восстанавливает вызов в SQLite, если записи не было"""
        view = ChallengeView(bot=self.bot, db=self.db)
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = 777
        interaction.channel_id = 888
        interaction.channel = MagicMock(spec=discord.TextChannel)
        interaction.channel.parent_id = None
        interaction.message = MagicMock(spec=discord.Message)
        interaction.message.id = 999111
        interaction.message.content = "<@501> <@502>"

        embed = MagicMock(spec=discord.Embed)
        embed.title = "⚔️ ВЫЗОВ НА ОФИЦИАЛЬНУЮ ДУЭЛЬ 1v1"
        embed.description = (
            "### ⚔️ ВЫЗОВ НА ОФИЦИАЛЬНУЮ ДУЭЛЬ 1v1\n"
            "<@501> бросает вызов <@502>!\n\n"
            "🔴 **Инициатор:** <@501> (`varenik`)\n"
            "🔵 **Соперник:** <@502> (`theonetoabove`)\n\n"
            "⚙️ **Параметры дуэли:**\n"
            "• Формат: **`T2 — Main vs Main (Мейн в мейн)`**\n"
            "• Сервер: **`Hesse (Германия)`**\n"
            "• Дедлайн ответа: <t:1792750000:R>\n"
        )
        interaction.message.embeds = [embed]

        # В базе исходно НЕТ вызова
        self.assertIsNone(self.db.get_challenge_by_message(999111))

        # Вызываем резолв
        resolved = await view._resolve_challenge(interaction)
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["challenger_id"], 501)
        self.assertEqual(resolved["challenged_id"], 502)
        self.assertEqual(resolved["status"], "pending")

        # Проверяем, что теперь запись ЕСТЬ в SQLite
        db_ch = self.db.get_challenge_by_message(999111)
        self.assertIsNotNone(db_ch)
        self.assertEqual(db_ch["id"], resolved["id"])

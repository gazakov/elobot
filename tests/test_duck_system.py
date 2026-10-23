import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import discord
from discord.ext import commands

from database import Database
from cogs.matches import MatchesCog
import config


class TestDuckSystem(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        intents = discord.Intents.default()
        self.bot = commands.Bot(command_prefix="!", intents=intents)
        self.db = Database(":memory:")
        self.cog = MatchesCog(self.bot, self.db)
        await self.bot.add_cog(self.cog)

    async def asyncTearDown(self):
        self.db.close()
        await self.bot.close()

    async def test_execute_duck_success(self):
        """Проверка: Респонсибл вызывает /duck, ELO списывается, роль выдается, пользователь тегается"""
        guild = MagicMock(spec=discord.Guild)
        guild.id = 123456789

        # Роль Респонсибла
        resp_role = MagicMock(spec=discord.Role)
        resp_role.id = config.RESP_ROLE_ID
        resp_role.name = config.RESP_ROLE_NAME

        # Роль Duck
        duck_role = MagicMock(spec=discord.Role)
        duck_role.id = config.DUCK_ROLE_ID
        duck_role.name = config.DUCK_ROLE_NAME

        guild.roles = [resp_role, duck_role]
        guild.get_role.side_effect = lambda rid: resp_role if rid == config.RESP_ROLE_ID else (duck_role if rid == config.DUCK_ROLE_ID else None)

        # Автор команды - Респонсибл
        author = MagicMock(spec=discord.Member)
        author.id = 1001
        author.mention = "<@1001>"
        author.display_name = "RefereeUser"
        author.roles = [resp_role]

        # Нарушитель (отказался от боя)
        offender = MagicMock(spec=discord.Member)
        offender.id = 2002
        offender.bot = False
        offender.mention = "<@2002>"
        offender.display_name = "DodgerPlayer"
        offender.roles = []
        offender.add_roles = AsyncMock()
        offender.send = AsyncMock()

        # Создаем игрока в БД с рейтингом 1600
        self.db.get_or_create_user(2002, "DodgerRoblox")
        self.db.set_user_rating(2002, 1600.0)

        # Канал (ветка дуэли)
        channel = MagicMock(spec=discord.Thread)
        channel.id = 555666
        channel.edit = AsyncMock()

        # Interaction
        interaction = MagicMock(spec=discord.Interaction)
        interaction.user = author
        interaction.guild = guild
        interaction.channel = channel
        interaction.response = MagicMock()
        interaction.response.send_message = AsyncMock()

        # Вызываем _execute_duck со штрафом 30 ELO
        with patch("cogs.matches.get_duck_channel", return_value=None):
            await self.cog._execute_duck(interaction, offender, penalty=30, reason="Отказ играть в ветке")

        # 1. Проверяем списание рейтинга: 1600 - 30 = 1570
        user_after = self.db.get_or_create_user(2002)
        self.assertEqual(user_after["rating"], 1570.0)

        # 2. Проверяем выдачу роли Duck
        offender.add_roles.assert_called()

        # 3. Проверяем пинг нарушителя в отправленном сообщении
        interaction.response.send_message.assert_called_once()
        args, kwargs = interaction.response.send_message.call_args
        self.assertIn(offender.mention, kwargs.get("content", ""))

        embed = kwargs.get("embed")
        self.assertIsNotNone(embed)
        self.assertIn("-30 ELO", embed.description)
        self.assertIn("Отказ играть в ветке", embed.description)

    async def test_execute_duck_denied_for_regular_user(self):
        """Проверка: обычный игрок без роли Респонсибла не может использовать /duck"""
        guild = MagicMock(spec=discord.Guild)
        guild.roles = []

        regular_user = MagicMock(spec=discord.Member)
        regular_user.id = 3003
        regular_user.roles = []
        regular_user.guild_permissions.administrator = False

        target = MagicMock(spec=discord.Member)
        target.id = 4004
        target.bot = False

        interaction = MagicMock(spec=discord.Interaction)
        interaction.user = regular_user
        interaction.guild = guild
        interaction.locale = discord.Locale.russian
        interaction.response = MagicMock()
        interaction.response.send_message = AsyncMock()

        await self.cog._execute_duck(interaction, target)

        interaction.response.send_message.assert_called_once()
        _, kwargs = interaction.response.send_message.call_args
        self.assertTrue(kwargs.get("ephemeral", False))

    async def test_execute_duck_bot_prevented(self):
        """Проверка: нельзя выдать Дак боту"""
        guild = MagicMock(spec=discord.Guild)
        resp_role = MagicMock(spec=discord.Role)
        resp_role.id = config.RESP_ROLE_ID
        guild.roles = [resp_role]

        author = MagicMock(spec=discord.Member)
        author.id = 1001
        author.roles = [resp_role]

        bot_target = MagicMock(spec=discord.Member)
        bot_target.id = 9999
        bot_target.bot = True

        interaction = MagicMock(spec=discord.Interaction)
        interaction.user = author
        interaction.guild = guild
        interaction.locale = discord.Locale.russian
        interaction.response = MagicMock()
        interaction.response.send_message = AsyncMock()

        await self.cog._execute_duck(interaction, bot_target)

        interaction.response.send_message.assert_called_once()
        args, kwargs = interaction.response.send_message.call_args
        sent_text = args[0] if args else kwargs.get("content", "")
        self.assertTrue("бот" in sent_text.lower() or "bot" in sent_text.lower())

    async def test_execute_duck_glicko_against_opponent(self):
        """Проверка: Вариант 2 — списание ELO нарушителю по Glicko-2 против оппонента (рейтинг оппонента не меняется)"""
        guild = MagicMock(spec=discord.Guild)
        resp_role = MagicMock(spec=discord.Role)
        resp_role.id = config.RESP_ROLE_ID
        resp_role.name = config.RESP_ROLE_NAME

        duck_role = MagicMock(spec=discord.Role)
        duck_role.id = config.DUCK_ROLE_ID
        duck_role.name = config.DUCK_ROLE_NAME

        guild.roles = [resp_role, duck_role]
        guild.get_role.side_effect = lambda rid: resp_role if rid == config.RESP_ROLE_ID else (duck_role if rid == config.DUCK_ROLE_ID else None)

        author = MagicMock(spec=discord.Member)
        author.id = 1001
        author.mention = "<@1001>"
        author.display_name = "RefereeUser"
        author.roles = [resp_role]

        # Нарушитель (1700 ELO, RD=100)
        offender = MagicMock(spec=discord.Member)
        offender.id = 2002
        offender.bot = False
        offender.mention = "<@2002>"
        offender.display_name = "HighEloDodger"
        offender.roles = []
        offender.add_roles = AsyncMock()
        offender.send = AsyncMock()

        self.db.get_or_create_user(2002, "HighEloDodger")
        with self.db._lock:
            with self.db._get_connection() as conn:
                conn.execute("UPDATE users SET rating = 1700.0, rd = 100.0 WHERE discord_id = 2002")
                conn.commit()

        # Оппонент (1500 ELO, RD=100)
        opponent = MagicMock(spec=discord.Member)
        opponent.id = 3003
        opponent.bot = False
        opponent.mention = "<@3003>"
        opponent.display_name = "ChallengerPlayer"

        self.db.get_or_create_user(3003, "ChallengerPlayer")
        with self.db._lock:
            with self.db._get_connection() as conn:
                conn.execute("UPDATE users SET rating = 1500.0, rd = 100.0 WHERE discord_id = 3003")
                conn.commit()

        interaction = MagicMock(spec=discord.Interaction)
        interaction.user = author
        interaction.guild = guild
        interaction.channel = None
        interaction.response = MagicMock()
        interaction.response.send_message = AsyncMock()

        with patch("cogs.matches.get_duck_channel", return_value=None):
            await self.cog._execute_duck(interaction, offender, opponent=opponent)

        # Рейтинг нарушителя упал (как за проигрыш игроку 1500 ELO)
        offender_after = self.db.get_or_create_user(2002)
        self.assertLess(offender_after["rating"], 1700.0)

        # Рейтинг оппонента остался неизменным (защита от накрутки)
        opp_after = self.db.get_or_create_user(3003)
        self.assertEqual(opp_after["rating"], 1500.0)

        # Проверяем, что в сообщении упомянут оппонент
        interaction.response.send_message.assert_called_once()
        _, kwargs = interaction.response.send_message.call_args
        embed = kwargs.get("embed")
        self.assertIsNotNone(embed)
        self.assertIn("<@3003>", embed.description)

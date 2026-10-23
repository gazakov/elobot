import unittest
from unittest.mock import MagicMock
import discord
from discord.ext import commands

from database import Database
from cogs.fun import (
    FunCog,
    build_brazil_embed,
    build_gulag_embed,
    build_fakeban_embed,
    resolve_target_and_extra,
    BRAZIL_GIFS,
    GULAG_GIFS,
    BAN_GIFS,
)


class TestFunCog(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        intents = discord.Intents.default()
        intents.message_content = True
        self.bot = commands.Bot(command_prefix="!", intents=intents)
        self.db = Database(":memory:")
        self.cog = FunCog(self.bot, self.db)
        await self.bot.add_cog(self.cog)

    async def asyncTearDown(self):
        self.db.close()
        await self.bot.close()

    def test_commands_registration(self):
        """Проверка регистрации префиксных команд и их алиасов"""
        cmd_brazil = self.bot.get_command("бразил")
        self.assertIsNotNone(cmd_brazil)
        self.assertIn("brazil", cmd_brazil.aliases)
        self.assertIn("вбразилию", cmd_brazil.aliases)

        cmd_gulag = self.bot.get_command("гулаг")
        self.assertIsNotNone(cmd_gulag)
        self.assertIn("gulag", cmd_gulag.aliases)
        self.assertIn("сибирь", cmd_gulag.aliases)

        cmd_fakeban = self.bot.get_command("фейкбан")
        self.assertIsNotNone(cmd_fakeban)
        self.assertIn("fakeban", cmd_fakeban.aliases)
        self.assertIn("fban", cmd_fakeban.aliases)
        self.assertIn("бан", cmd_fakeban.aliases)

    def test_slash_commands_registration(self):
        """Проверка регистрации слэш-команд в дереве бота"""
        slash_names = [cmd.name for cmd in self.bot.tree.get_commands()]
        self.assertIn("brazil", slash_names)
        self.assertIn("gulag", slash_names)
        self.assertIn("fakeban", slash_names)

    def test_brazil_embed_target_other(self):
        author = MagicMock(spec=discord.Member)
        author.id = 111
        author.mention = "<@111>"

        target = MagicMock(spec=discord.Member)
        target.id = 222
        target.mention = "<@222>"

        embed = build_brazil_embed(author, target, bot_id=999)
        self.assertEqual(embed.title, "🇧🇷 YOU ARE GOING TO BRAZIL!")
        self.assertIn(target.mention, embed.description)
        self.assertIn(embed.image.url, BRAZIL_GIFS)

    def test_brazil_embed_easter_egg_bot(self):
        author = MagicMock(spec=discord.Member)
        author.id = 111
        author.mention = "<@111>"

        bot_target = MagicMock(spec=discord.Member)
        bot_target.id = 999

        embed = build_brazil_embed(author, bot_target, bot_id=999)
        self.assertEqual(embed.title, "🇧🇷 ПОРТАЛ ОТРАЖЕН! / NO U")
        self.assertIn("Uno Reverse Card", embed.description)
        self.assertIn(author.mention, embed.description)

    def test_brazil_embed_self(self):
        author = MagicMock(spec=discord.Member)
        author.id = 111
        author.mention = "<@111>"

        embed = build_brazil_embed(author, author, bot_id=999)
        self.assertEqual(embed.title, "🇧🇷 ДОБРОВОЛЬНЫЙ РЕЙС В БРАЗИЛИЮ")
        self.assertIn(author.mention, embed.description)

    def test_gulag_embed_target_other(self):
        author = MagicMock(spec=discord.Member)
        author.id = 111
        author.mention = "<@111>"

        target = MagicMock(spec=discord.Member)
        target.id = 222
        target.mention = "<@222>"

        embed = build_gulag_embed(author, target, bot_id=999)
        self.assertEqual(embed.title, "⛏️ ПРИГОВОР: ССЫЛКА В ГУЛАГ")
        self.assertIn(target.mention, embed.description)
        self.assertIn(embed.image.url, GULAG_GIFS)

    def test_gulag_embed_easter_egg_bot(self):
        author = MagicMock(spec=discord.Member)
        author.id = 111
        author.mention = "<@111>"

        bot_target = MagicMock(spec=discord.Member)
        bot_target.id = 999

        embed = build_gulag_embed(author, bot_target, bot_id=999)
        self.assertEqual(embed.title, "⛏️ ОШИБКА СИСТЕМЫ: БУНТ ПРЕСЕЧЕН")
        self.assertIn(author.mention, embed.description)

    def test_fakeban_embed_with_reason(self):
        author = MagicMock(spec=discord.Member)
        author.id = 111
        author.mention = "<@111>"

        target = MagicMock(spec=discord.Member)
        target.id = 222
        target.name = "ToxicPlayer"
        target.mention = "<@222>"

        custom_reason = "Кринж 4-й степени в общественном месте"
        embed = build_fakeban_embed(author, target, bot_id=999, reason=custom_reason)

        self.assertEqual(embed.title, "🔨 [SECURITY SYSTEM] ПОЛЬЗОВАТЕЛЬ ЗАБЛОКИРОВАН")
        self.assertIn(target.mention, embed.description)
        self.assertIn(author.mention, embed.description)
        self.assertIn(custom_reason, embed.description)
        self.assertIn(embed.image.url, BAN_GIFS)

    def test_fakeban_embed_easter_egg_bot(self):
        author = MagicMock(spec=discord.Member)
        author.id = 111
        author.mention = "<@111>"

        bot_target = MagicMock(spec=discord.Member)
        bot_target.id = 999

        embed = build_fakeban_embed(author, bot_target, bot_id=999)
        self.assertEqual(embed.title, "🔨 [SECURITY SYSTEM] ACCESS DENIED")
        self.assertIn(author.mention, embed.description)

    async def test_resolve_target_and_extra_mentions(self):
        author = MagicMock(spec=discord.Member)
        author.id = 111

        target = MagicMock(spec=discord.Member)
        target.id = 222

        ctx = MagicMock()
        ctx.author = author
        ctx.message = MagicMock()
        ctx.message.mentions = [target]
        ctx.message.reference = None

        res_target, extra = await resolve_target_and_extra(ctx, "<@222> за читы")
        self.assertEqual(res_target.id, 222)
        self.assertEqual(extra, "за читы")

    async def test_resolve_target_fallback_to_author(self):
        author = MagicMock(spec=discord.Member)
        author.id = 111

        ctx = MagicMock()
        ctx.author = author
        ctx.message = MagicMock()
        ctx.message.mentions = []
        ctx.message.reference = None

        res_target, extra = await resolve_target_and_extra(ctx, None)
        self.assertEqual(res_target.id, 111)
        self.assertIsNone(extra)

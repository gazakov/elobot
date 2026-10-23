import unittest
import discord
from discord.ext import commands
from database import Database

class TestCogsLoading(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        intents = discord.Intents.default()
        self.bot = commands.Bot(command_prefix="!", intents=intents)
        self.db = Database(":memory:")

    async def asyncTearDown(self):
        self.db.close()
        await self.bot.close()

    async def test_all_cogs_load_successfully(self):
        """Проверка: все 5 когов загружаются в discord.py без NameError и синтаксических сбоев"""
        from cogs.ranked import RankedCog
        from cogs.matches import MatchesCog
        from cogs.queue import QueueCog
        from cogs.admin import AdminCog
        from cogs.fun import FunCog

        await self.bot.add_cog(RankedCog(self.bot, self.db))
        await self.bot.add_cog(MatchesCog(self.bot, self.db))
        await self.bot.add_cog(QueueCog(self.bot, self.db))
        await self.bot.add_cog(AdminCog(self.bot, self.db))
        await self.bot.add_cog(FunCog(self.bot, self.db))

        loaded_cogs = list(self.bot.cogs.keys())
        self.assertIn("RankedCog", loaded_cogs)
        self.assertIn("MatchesCog", loaded_cogs)
        self.assertIn("QueueCog", loaded_cogs)
        self.assertIn("AdminCog", loaded_cogs)
        self.assertIn("FunCog", loaded_cogs)

    async def test_app_commands_tree_registration(self):
        """Проверка: все слэш-команды корректно зарегистрированы в CommandTree"""
        from cogs.ranked import RankedCog
        from cogs.matches import MatchesCog
        from cogs.queue import QueueCog
        from cogs.admin import AdminCog

        await self.bot.add_cog(RankedCog(self.bot, self.db))
        await self.bot.add_cog(MatchesCog(self.bot, self.db))
        await self.bot.add_cog(QueueCog(self.bot, self.db))
        await self.bot.add_cog(AdminCog(self.bot, self.db))

        commands = [cmd.name for cmd in self.bot.tree.get_commands()]
        expected = [
            "link", "unlink", "build", "profile", "leaderboard", "ranks", "rules", "vip",
            "match", "report", "duck", "challenge", "challenge_cancel", "formats", "queue", "quene", "leave", "queue_status", "queue_panel",
            "season", "sync_roles", "setup_roles", "setup_channels", "backup",
            "set_elo", "sync_commands", "check_passenger", "bloxlink", "duck_channel", "results_channel", "fights_channel"
        ]
        for exp in expected:
            self.assertIn(exp, commands, f"Команда {exp} должна быть в CommandTree бота")

    async def test_prefix_commands_registration(self):
        """Проверка: префиксные команды !profile, !rep, !report, !queue, !duck зарегистрированы в боте"""
        from cogs.ranked import RankedCog
        from cogs.matches import MatchesCog
        from cogs.queue import QueueCog
        await self.bot.add_cog(RankedCog(self.bot, self.db))
        await self.bot.add_cog(MatchesCog(self.bot, self.db))
        await self.bot.add_cog(QueueCog(self.bot, self.db))

        self.assertIsNotNone(self.bot.get_command("profile"))
        self.assertIsNotNone(self.bot.get_command("rep"))
        self.assertIsNotNone(self.bot.get_command("report"))
        self.assertIsNotNone(self.bot.get_command("queue"))
        self.assertIsNotNone(self.bot.get_command("duck"))
        self.assertIn("p", self.bot.get_command("profile").aliases)
        self.assertIn("профиль", self.bot.get_command("profile").aliases)
        self.assertIn("репорт", self.bot.get_command("report").aliases)
        self.assertIn("quene", self.bot.get_command("queue").aliases)
        self.assertIn("дак", self.bot.get_command("duck").aliases)

    async def test_roblox_avatar_bytes_caching(self):
        """Проверка функции получения и кэширования PNG байтов аватарки Roblox"""
        from cogs.ranked import fetch_roblox_avatar_bytes, _avatar_bytes_cache
        # Ручная установка в кэш
        fake_png = b'\x89PNG\r\n\x1a\nfakeavatarbytes'
        _avatar_bytes_cache["cached_user"] = (fake_png, 9999999999.0)
        res = fetch_roblox_avatar_bytes("cached_user")
        self.assertEqual(res, fake_png)

    def test_profile_view_buttons_linked_vs_unlinked(self):
        """Проверка: у непривязанного пользователя только кнопки репутации (без ЮБА), а у привязанного — обе вкладки"""
        from cogs.ranked import ProfileView
        from unittest.mock import MagicMock

        target = MagicMock()
        target.id = 123456
        cog = MagicMock()

        # 1. Непривязанный пользователь на вкладке Discord (обе вкладки доступны + кнопки репутации)
        view_unlinked = ProfileView(
            bot=self.bot,
            db=self.db,
            cog=cog,
            target_user=target,
            lang="ru",
            has_roblox=False,
            current_tab="discord"
        )
        labels_unlinked = [item.label for item in view_unlinked.children if hasattr(item, "label")]
        self.assertIn("ЮБА ⚔️", labels_unlinked)
        self.assertIn("Дискорд 💬", labels_unlinked)
        self.assertIn("+Rep", labels_unlinked)
        self.assertIn("-Rep", labels_unlinked)

        # 2. Непривязанный пользователь на вкладке YBA (есть кнопка быстрой привязки)
        view_unlinked_yba = ProfileView(
            bot=self.bot,
            db=self.db,
            cog=cog,
            target_user=target,
            lang="ru",
            has_roblox=False,
            is_owner=True,
            current_tab="yba"
        )
        labels_unlinked_yba = [item.label for item in view_unlinked_yba.children if hasattr(item, "label")]
        self.assertIn("ЮБА ⚔️", labels_unlinked_yba)
        self.assertIn("Дискорд 💬", labels_unlinked_yba)
        self.assertIn("Привязать Roblox", labels_unlinked_yba)

        # 3. Привязанный пользователь
        view_linked = ProfileView(
            bot=self.bot,
            db=self.db,
            cog=cog,
            target_user=target,
            lang="ru",
            has_roblox=True,
            current_tab="yba"
        )
        labels_linked = [item.label for item in view_linked.children if hasattr(item, "label")]
        self.assertIn("ЮБА ⚔️", labels_linked)
        self.assertIn("Дискорд 💬", labels_linked)

    async def test_rules_view_interaction_check(self):
        """Проверка: RulesView разрешает переключение страниц только автору команды"""
        from cogs.ranked import RulesView
        from unittest.mock import AsyncMock, MagicMock

        author_id = 11111
        stranger_id = 22222

        view = RulesView(lang="ru", author_id=author_id)

        # 1. Автор вызывает переключение
        inter_author = MagicMock()
        inter_author.user.id = author_id
        inter_author.response.send_message = AsyncMock()

        can_interact = await view.interaction_check(inter_author)
        self.assertTrue(can_interact)
        inter_author.response.send_message.assert_not_called()

        # 2. Другой игрок пытается переключить
        inter_stranger = MagicMock()
        inter_stranger.user.id = stranger_id
        inter_stranger.response.send_message = AsyncMock()

        can_interact_stranger = await view.interaction_check(inter_stranger)
        self.assertFalse(can_interact_stranger)
        inter_stranger.response.send_message.assert_called_once()
        _, kwargs = inter_stranger.response.send_message.call_args
        self.assertTrue(kwargs.get("ephemeral"))

    async def test_profile_view_interaction_check(self):
        """Проверка: ProfileView блокирует переключение вкладок для чужих, но разрешает +Rep/-Rep"""
        from cogs.ranked import ProfileView
        from unittest.mock import AsyncMock, MagicMock

        caller_id = 12345
        stranger_id = 99999
        target = MagicMock()
        target.id = caller_id

        view = ProfileView(
            bot=self.bot,
            db=self.db,
            cog=MagicMock(),
            target_user=target,
            lang="ru",
            has_roblox=True,
            current_tab="yba",
            caller_id=caller_id
        )

        # 1. Вызвавший команду игрок нажимает вкладку (ЮБА / Дискорд)
        inter_caller = MagicMock()
        inter_caller.user.id = caller_id
        inter_caller.data = {"custom_id": "profile_tab_yba"}
        inter_caller.response.send_message = AsyncMock()

        self.assertTrue(await view.interaction_check(inter_caller))
        inter_caller.response.send_message.assert_not_called()

        # 2. Посторонний игрок пытается переключить чужую вкладку (ЮБА / Дискорд) -> блокируется
        inter_stranger = MagicMock()
        inter_stranger.user.id = stranger_id
        inter_stranger.data = {"custom_id": "profile_tab_yba"}
        inter_stranger.response.send_message = AsyncMock()

        self.assertFalse(await view.interaction_check(inter_stranger))
        inter_stranger.response.send_message.assert_called_once()
        _, kwargs = inter_stranger.response.send_message.call_args
        self.assertTrue(kwargs.get("ephemeral"))
        self.assertIn("Переключать вкладки профиля", inter_stranger.response.send_message.call_args[0][0])

        # 3. Посторонний игрок нажимает +Rep (лайк) -> РАЗРЕШЕНО!
        inter_stranger_rep = MagicMock()
        inter_stranger_rep.user.id = stranger_id
        inter_stranger_rep.data = {"custom_id": "profile_rep_like"}
        inter_stranger_rep.response.send_message = AsyncMock()

        self.assertTrue(await view.interaction_check(inter_stranger_rep))
        inter_stranger_rep.response.send_message.assert_not_called()

        # 4. Сам владелец пытается лайкнуть свой же профиль -> блокируется (самолайк запрещён)
        inter_self_rep = MagicMock()
        inter_self_rep.user.id = caller_id
        inter_self_rep.data = {"custom_id": "profile_rep_like"}
        inter_self_rep.response.send_message = AsyncMock()

        self.assertFalse(await view.interaction_check(inter_self_rep))
        inter_self_rep.response.send_message.assert_called_once()
        self.assertIn("не можете менять репутацию самому себе", inter_self_rep.response.send_message.call_args[0][0])

    async def test_challenge_cancel_button_and_db(self):
        """Проверка: кнопка отмены вызова и выборка исходящего вызова в БД"""
        from cogs.matches import ChallengeView
        from unittest.mock import AsyncMock, MagicMock

        p1_id = 111
        p2_id = 222
        stranger_id = 333

        cid = self.db.create_challenge(
            guild_id=123, channel_id=456, message_id=789,
            challenger_id=p1_id, challenged_id=p2_id,
            format="T1", server="Hesse"
        )
        self.assertIsNotNone(cid)

        # Проверка get_active_outgoing_challenge
        out_ch = self.db.get_active_outgoing_challenge(p1_id)
        self.assertIsNotNone(out_ch)
        self.assertEqual(out_ch["id"], cid)
        self.assertEqual(out_ch["status"], "pending")

        view = ChallengeView(bot=self.bot, db=self.db, lang="ru")

        # 1. Посторонний пытается отменить
        fake_msg = MagicMock()
        fake_msg.id = 789
        fake_msg.embeds = []

        inter_stranger = MagicMock()
        inter_stranger.user.id = stranger_id
        inter_stranger.guild.get_member.return_value = None
        inter_stranger.user.guild_permissions.administrator = False
        inter_stranger.message = fake_msg
        inter_stranger.response.send_message = AsyncMock()

        btn = MagicMock()
        await view.btn_cancel.callback(inter_stranger)
        inter_stranger.response.send_message.assert_called_once()
        self.assertIn("Только создатель вызова", inter_stranger.response.send_message.call_args[0][0])

        # 2. Автор отменяет вызов
        inter_author = MagicMock()
        inter_author.user.id = p1_id
        inter_author.user.guild_permissions.administrator = False
        inter_author.message = fake_msg
        inter_author.response.defer = AsyncMock()
        fake_msg.edit = AsyncMock()

        await view.btn_cancel.callback(inter_author)
        inter_author.response.defer.assert_called_once()
        fake_msg.edit.assert_called_once()

        # Проверяем статус в БД
        updated_ch = self.db.get_challenge(cid)
        self.assertEqual(updated_ch["status"], "cancelled")
        self.assertIsNone(self.db.get_active_outgoing_challenge(p1_id))

    async def test_call_ref_button_cooldown(self):
        """Проверка: кулдаун на вызов Респов (защита от спама)"""
        from cogs.matches import CallRefButton, _CALL_REF_COOLDOWNS
        from unittest.mock import AsyncMock, MagicMock

        p1_id = 111
        p2_id = 222
        chan_id = 999000
        _CALL_REF_COOLDOWNS.clear()

        btn = CallRefButton(challenger_id=p1_id, challenged_id=p2_id, lang="ru")

        inter = MagicMock()
        inter.channel_id = chan_id
        inter.user.id = p1_id
        inter.guild.roles = []
        inter.response.send_message = AsyncMock()

        # 1. Первый вызов проходит
        await btn.callback(inter)
        inter.response.send_message.assert_called_once()
        self.assertEqual(inter.response.send_message.call_args[1]["content"], "@1v1s Responsible")

        # 2. Немедленный повторный вызов блокируется кулдауном
        inter2 = MagicMock()
        inter2.channel_id = chan_id
        inter2.user.id = p2_id
        inter2.guild.roles = []
        inter2.response.send_message = AsyncMock()

        await btn.callback(inter2)
        inter2.response.send_message.assert_called_once()
        self.assertIn("уже оповещены", inter2.response.send_message.call_args[0][0])
        self.assertTrue(inter2.response.send_message.call_args[1]["ephemeral"])

    def test_database_active_accepted_and_finish(self):
        """Проверка методов БД has_active_accepted_challenge и finish_challenge_for_players"""
        p1 = 555
        p2 = 666
        cid = self.db.create_challenge(1, 2, 3, p1, p2, "T1", "Hesse")
        self.assertIsNone(self.db.has_active_accepted_challenge(p1, p2))

        # Переводим в accepted
        self.db.update_challenge_status(cid, "accepted")
        active = self.db.has_active_accepted_challenge(p1, p2)
        self.assertIsNotNone(active)
        self.assertEqual(active["id"], cid)

        # Завершаем дуэль
        fin = self.db.finish_challenge_for_players(p1, p2)
        self.assertIsNotNone(fin)
        self.assertEqual(fin["id"], cid)
        self.assertIsNone(self.db.has_active_accepted_challenge(p1, p2))

    async def test_sync_user_roles_allows_owner(self):
        """Проверка: sync_user_roles не блокирует владельца сервера guild.owner_id"""
        from ranks import sync_user_roles, get_rank_info
        from unittest.mock import AsyncMock, MagicMock

        guild = MagicMock()
        owner = MagicMock()
        owner.id = 12345
        guild.owner_id = 12345

        # Бот имеет право управлять ролями
        bot_role = MagicMock()
        bot_role.position = 100
        bot_role.__ge__ = lambda self, other: self.position >= getattr(other, "position", 0)
        bot_role.__lt__ = lambda self, other: self.position < getattr(other, "position", 0)
        guild.me.top_role = bot_role
        guild.me.guild_permissions.manage_roles = True

        master_role = MagicMock()
        master_role.name = "Master"
        master_role.position = 50
        master_role.__ge__ = lambda self, other: self.position >= getattr(other, "position", 0)
        master_role.__lt__ = lambda self, other: self.position < getattr(other, "position", 0)

        top10_role = MagicMock()
        top10_role.name = "Top 10"
        top10_role.position = 40
        top10_role.__ge__ = lambda self, other: self.position >= getattr(other, "position", 0)
        top10_role.__lt__ = lambda self, other: self.position < getattr(other, "position", 0)

        guild.roles = [master_role, top10_role]
        guild.create_role = AsyncMock()

        owner.roles = []
        owner.edit = AsyncMock()

        rank_info = get_rank_info(rating=2050.0, rd=80.0, total_games=10, rank_position=5)
        res = await sync_user_roles(owner, rank_info, guild)
        self.assertEqual(res, "Master")
        owner.edit.assert_called_once()

    async def test_quick_report_choice_flow(self):
        """Проверка: QuickReportChoiceView не вызывает исключений InteractionResponded при defer"""
        from cogs.matches import QuickReportChoiceView
        from unittest.mock import AsyncMock, MagicMock

        cog = MagicMock()
        cog._execute_report = AsyncMock()

        p1 = MagicMock()
        p1.display_name = "Player1"
        p2 = MagicMock()
        p2.display_name = "Player2"

        view = QuickReportChoiceView(cog, p1, p2, lang="ru")
        inter = MagicMock()
        inter.response.edit_message = AsyncMock()

        # Кликаем кнопку первого игрока
        btn_winner = view.children[0]
        await btn_winner.callback(inter)
        inter.response.edit_message.assert_called_once()
        cog._execute_report.assert_called_once()
        _, kwargs = cog._execute_report.call_args
        self.assertEqual(kwargs["winner"], p1)
        self.assertEqual(kwargs["loser"], p2)

    async def test_get_match_results_channel_resolution(self):
        """Проверка: корректное разрешение канала результатов матчей по ID, БД и имени"""
        from cogs.matches import get_match_results_channel
        from unittest.mock import AsyncMock, MagicMock

        guild = MagicMock()
        mock_chan_by_id = MagicMock(spec=discord.TextChannel)
        mock_chan_by_id.id = 1562552971961565247
        mock_chan_by_id.name = "1v1s-elos"

        # 1. По умолчанию находит по config ID
        guild.get_channel.side_effect = lambda cid: mock_chan_by_id if cid == 1562552971961565247 else None
        res = await get_match_results_channel(guild, self.db)
        self.assertEqual(res, mock_chan_by_id)

        # 2. Переопределение через настройку в БД
        custom_chan = MagicMock(spec=discord.TextChannel)
        custom_chan.id = 999888777
        guild.get_channel.side_effect = lambda cid: custom_chan if cid == 999888777 else None
        self.db.set_setting("match_results_channel_id", "999888777")
        res_custom = await get_match_results_channel(guild, self.db)
        self.assertEqual(res_custom, custom_chan)

        # 3. Fallback по имени канала если ID не найден
        self.db.set_setting("match_results_channel_id", "111222333")
        guild.get_channel.side_effect = lambda cid: None
        guild.fetch_channel = AsyncMock(side_effect=Exception("Not found"))
        named_chan = MagicMock(spec=discord.TextChannel)
        named_chan.name = "1v1s-elos"
        guild.text_channels = [named_chan]
        res_fallback = await get_match_results_channel(guild, self.db)
        self.assertEqual(res_fallback, named_chan)

    async def test_get_or_create_fights_channel_resolution(self):
        """Проверка: корректное разрешение форума дуэлей Лиги по ID из config и БД"""
        from cogs.matches import get_or_create_fights_channel
        from unittest.mock import AsyncMock, MagicMock

        guild = MagicMock()
        mock_forum = MagicMock(spec=discord.ForumChannel)
        mock_forum.id = 1562574681637257387
        mock_forum.name = "elo-1v1"

        # 1. По умолчанию находит по config ID (1562574681637257387)
        guild.get_channel.side_effect = lambda cid: mock_forum if cid == 1562574681637257387 else None
        res = await get_or_create_fights_channel(guild, self.db)
        self.assertEqual(res, mock_forum)

        # 2. Переопределение через настройку в БД
        custom_forum = MagicMock(spec=discord.ForumChannel)
        custom_forum.id = 888777666
        guild.get_channel.side_effect = lambda cid: custom_forum if cid == 888777666 else None
        self.db.set_setting("fights_channel_id", "888777666")
        res_custom = await get_or_create_fights_channel(guild, self.db)
        self.assertEqual(res_custom, custom_forum)

    async def test_duck_role_and_channel_resolution(self):
        """Проверка: корректное определение роли Duck (1372618658253111326) и канала даков (1534056814117916702)"""
        from cogs.matches import get_duck_role, get_duck_channel
        from unittest.mock import MagicMock

        guild = MagicMock()
        mock_duck_role = MagicMock(spec=discord.Role)
        mock_duck_role.id = 1372618658253111326
        mock_duck_role.name = "Duck"

        guild.get_role.side_effect = lambda rid: mock_duck_role if rid == 1372618658253111326 else None
        found_role = get_duck_role(guild)
        self.assertEqual(found_role, mock_duck_role)

        mock_duck_chan = MagicMock(spec=discord.TextChannel)
        mock_duck_chan.id = 1534056814117916702
        mock_duck_chan.name = "ducks"

        guild.get_channel.side_effect = lambda cid: mock_duck_chan if cid == 1534056814117916702 else None
        found_chan = await get_duck_channel(guild, self.db)
        self.assertEqual(found_chan, mock_duck_chan)

    async def test_quick_report_conflict_of_interest(self):
        """Проверка: участники дуэли (даже админы) НЕ могут нажать кнопку «Зафиксировать победу» в собственном бою"""
        from cogs.matches import QuickReportButton
        from unittest.mock import AsyncMock, MagicMock

        btn = QuickReportButton(challenger_id=100, challenged_id=200, lang="ru")
        inter = MagicMock()
        inter.user.id = 100  # Один из участников дуэли
        inter.user.guild_permissions.administrator = True
        inter.guild = MagicMock()
        inter.response.send_message = AsyncMock()

        await btn.callback(inter)
        inter.response.send_message.assert_called_once()
        args, kwargs = inter.response.send_message.call_args
        self.assertIn("Конфликт интересов", args[0])

    async def test_1v1_elo_responsible_role_recognized(self):
        """Проверка: роль '⋆ 1v1 Elo Responsible' (1562473046739263622) признается легитимным респом"""
        from cogs.matches import is_resp_or_admin
        from unittest.mock import MagicMock

        inter = MagicMock()
        inter.guild = MagicMock()
        inter.user.guild_permissions.administrator = False
        r_resp = MagicMock()
        r_resp.id = 1562473046739263622
        r_resp.name = "⋆ 1v1 Elo Responsible"
        inter.user.roles = [r_resp]

        self.assertTrue(is_resp_or_admin(inter))

    async def test_profile_unlinked_embed_structure(self):
        """Проверка: build_unlinked_embed возвращает корректные экраны с требованием привязки"""
        from cogs.ranked import RankedCog
        from unittest.mock import MagicMock

        cog = RankedCog(self.bot, self.db)
        target = MagicMock()
        target.id = 777777
        target.display_avatar = None
        target.mention = "<@777777>"

        # 1. Владелец профиля
        emb_owner = cog.build_unlinked_embed(target, "ru", is_owner=True)
        self.assertIn("Требуется привязка Roblox", emb_owner.title)
        self.assertIn("blox.link", emb_owner.description)

        # 2. Чужой профиль
        emb_other = cog.build_unlinked_embed(target, "ru", is_owner=False)
        self.assertIn("Профиль недоступен", emb_other.title)
        self.assertIn("ещё не привязал свой аккаунт", emb_other.description)

    async def test_challenge_immunity(self):
        """Проверка: игрок с иммунитетом (1404137813007532095) защищен от вызовов и даков"""
        import config
        from cogs.matches import MatchesCog, has_duck_evade
        from unittest.mock import MagicMock, AsyncMock

        self.assertIn(1404137813007532095, config.CHALLENGE_IMMUNITY_IDS)

        # 1. Проверка duck evade
        immune_member = MagicMock()
        immune_member.id = 1404137813007532095
        immune_member.roles = []
        self.assertTrue(has_duck_evade(immune_member))

        # 2. Проверка команды /challenge
        cog = MatchesCog(self.bot, self.db)
        inter = MagicMock()
        inter.user.id = 999999999
        inter.user.guild_permissions.administrator = False
        inter.locale = discord.Locale.russian
        inter.response.send_message = AsyncMock()

        target = MagicMock()
        target.id = 1404137813007532095
        target.bot = False
        target.mention = f"<@{target.id}>"

        await cog.challenge.callback(cog, inter, target)
        inter.response.send_message.assert_called_once()
        args, kwargs = inter.response.send_message.call_args
        self.assertIn("Иммунитет к вызовам", args[0])
        self.assertTrue(kwargs.get("ephemeral"))


if __name__ == "__main__":
    unittest.main()

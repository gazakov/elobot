import unittest
import asyncio
import time
from unittest.mock import MagicMock, AsyncMock, patch
import discord
from database import Database
from cogs.ranked import RankedCog, is_voice_active

class TestVoiceTracking(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Database(":memory:")
        self.bot = MagicMock()
        self.bot.is_ready.return_value = True
        self.ranked_cog = RankedCog(self.bot, self.db)

    async def asyncTearDown(self):
        self.db.close()

    def test_is_voice_active_conditions(self):
        """Проверка функции is_voice_active на все возможные состояния войса"""
        # 1. Нет состояния или нет канала
        self.assertFalse(is_voice_active(None))

        no_chan = MagicMock(spec=discord.VoiceState)
        no_chan.channel = None
        self.assertFalse(is_voice_active(no_chan))

        # 2. Нормальный активный канал
        channel = MagicMock(spec=discord.VoiceChannel)
        guild = MagicMock(spec=discord.Guild)
        guild.afk_channel_id = 9999
        channel.guild = guild
        channel.id = 1111

        active_state = MagicMock(spec=discord.VoiceState)
        active_state.channel = channel
        active_state.afk = False
        active_state.self_mute = False
        active_state.mute = False
        active_state.self_deaf = False
        active_state.deaf = False
        active_state.suppress = False
        self.assertTrue(is_voice_active(active_state))

        # 3. AFK канал
        afk_state = MagicMock(spec=discord.VoiceState)
        afk_state.channel = channel
        afk_state.afk = True
        self.assertFalse(is_voice_active(afk_state))

        afk_chan = MagicMock(spec=discord.VoiceChannel)
        afk_chan.id = 9999
        afk_chan.guild = guild
        afk_chan_state = MagicMock(spec=discord.VoiceState)
        afk_chan_state.channel = afk_chan
        afk_chan_state.afk = False
        self.assertFalse(is_voice_active(afk_chan_state))

        # 4. Самозаглушение (self_mute)
        self_mute_state = MagicMock(spec=discord.VoiceState)
        self_mute_state.channel = channel
        self_mute_state.afk = False
        self_mute_state.self_mute = True
        self_mute_state.mute = False
        self.assertFalse(is_voice_active(self_mute_state))

        # 5. Серверный мут (mute)
        server_mute_state = MagicMock(spec=discord.VoiceState)
        server_mute_state.channel = channel
        server_mute_state.afk = False
        server_mute_state.self_mute = False
        server_mute_state.mute = True
        self.assertFalse(is_voice_active(server_mute_state))

        # 6. Заглушение наушников (self_deaf / deaf)
        deaf_state = MagicMock(spec=discord.VoiceState)
        deaf_state.channel = channel
        deaf_state.afk = False
        deaf_state.self_mute = False
        deaf_state.mute = False
        deaf_state.self_deaf = True
        self.assertFalse(is_voice_active(deaf_state))

        # 7. Супрессирован на трибуне (suppress)
        suppress_state = MagicMock(spec=discord.VoiceState)
        suppress_state.channel = channel
        suppress_state.afk = False
        suppress_state.self_mute = False
        suppress_state.mute = False
        suppress_state.self_deaf = False
        suppress_state.deaf = False
        suppress_state.suppress = True
        self.assertFalse(is_voice_active(suppress_state))

    async def test_mute_unmute_voice_events(self):
        """Проверка начисления секунд при включении и отключении микрофона"""
        user_id = 100500
        member = MagicMock(spec=discord.Member)
        member.id = user_id
        member.bot = False

        channel = MagicMock(spec=discord.VoiceChannel)
        channel.id = 123
        channel.guild = MagicMock(afk_channel_id=999)

        # Состояние: unmuted
        unmuted_state = MagicMock(spec=discord.VoiceState)
        unmuted_state.channel = channel
        unmuted_state.afk = False
        unmuted_state.self_mute = False
        unmuted_state.mute = False
        unmuted_state.self_deaf = False
        unmuted_state.deaf = False
        unmuted_state.suppress = False

        # Состояние: muted
        muted_state = MagicMock(spec=discord.VoiceState)
        muted_state.channel = channel
        muted_state.afk = False
        muted_state.self_mute = True
        muted_state.mute = False
        muted_state.self_deaf = False
        muted_state.deaf = False
        muted_state.suppress = False

        # Состояние: disconnected
        none_state = MagicMock(spec=discord.VoiceState)
        none_state.channel = None

        # 1. Зашел в войс С ВКЛЮЧЕННЫМ микрофоном
        await self.ranked_cog.on_voice_state_update(member, none_state, unmuted_state)
        self.assertIn(user_id, self.ranked_cog._voice_sessions)

        # Симулируем 10 секунд разговора
        self.ranked_cog._voice_sessions[user_id] -= 10.0

        # 2. Пользователь замьютил микрофон -> сессия должна закрыться и начислить 10 секунд в БД
        await self.ranked_cog.on_voice_state_update(member, unmuted_state, muted_state)
        self.assertNotIn(user_id, self.ranked_cog._voice_sessions)

        act = self.db.get_user_activity(user_id)
        self.assertGreaterEqual(act["voice_seconds"], 9.0)

        # 3. Пользователь сидит замьюченный -> сессии нет, время НЕ начисляется
        prev_sec = act["voice_seconds"]
        await asyncio.sleep(0.05)
        act2 = self.db.get_user_activity(user_id)
        self.assertEqual(act2["voice_seconds"], prev_sec)

        # 4. Пользователь размьютил микрофон -> новая сессия стартует
        await self.ranked_cog.on_voice_state_update(member, muted_state, unmuted_state)
        self.assertIn(user_id, self.ranked_cog._voice_sessions)

        # Симулируем еще 5 секунд
        self.ranked_cog._voice_sessions[user_id] -= 5.0

        # 5. Пользователь вышел из войса -> время начисляется
        await self.ranked_cog.on_voice_state_update(member, unmuted_state, none_state)
        self.assertNotIn(user_id, self.ranked_cog._voice_sessions)

        act3 = self.db.get_user_activity(user_id)
        self.assertGreaterEqual(act3["voice_seconds"], prev_sec + 4.9)

    async def test_voice_tracker_task_reconciler(self):
        """Проверка фонового цикла: учитывает только участников с включенным микрофоном"""
        u1 = 111 # В войсе с микрофоном
        u2 = 222 # В войсе с мутом

        m1 = MagicMock(spec=discord.Member)
        m1.id = u1
        m1.bot = False
        v1 = MagicMock(spec=discord.VoiceState)
        v1.channel = MagicMock(id=1, guild=MagicMock(afk_channel_id=9))
        v1.afk = False
        v1.self_mute = False
        v1.mute = False
        v1.self_deaf = False
        v1.deaf = False
        v1.suppress = False
        m1.voice = v1

        m2 = MagicMock(spec=discord.Member)
        m2.id = u2
        m2.bot = False
        v2 = MagicMock(spec=discord.VoiceState)
        v2.channel = MagicMock(id=1, guild=MagicMock(afk_channel_id=9))
        v2.afk = False
        v2.self_mute = True
        v2.mute = False
        v2.self_deaf = False
        v2.deaf = False
        v2.suppress = False
        m2.voice = v2

        channel = MagicMock(spec=discord.VoiceChannel)
        channel.id = 1
        channel.members = [m1, m2]

        guild = MagicMock(spec=discord.Guild)
        guild.afk_channel_id = 9
        guild.voice_channels = [channel]

        self.bot.guilds = [guild]

        # 1-й цикл: инициализация сессии для u1
        await self.ranked_cog.voice_tracker_task()
        self.assertIn(u1, self.ranked_cog._voice_sessions)
        self.assertNotIn(u2, self.ranked_cog._voice_sessions)

        # Симулируем 15 секунд
        self.ranked_cog._voice_sessions[u1] -= 15.0

        # 2-й цикл: начисление секунд для u1
        await self.ranked_cog.voice_tracker_task()
        act1 = self.db.get_user_activity(u1)
        self.assertGreaterEqual(act1["voice_seconds"], 14.0)

        act2 = self.db.get_user_activity(u2)
        self.assertEqual(act2["voice_seconds"], 0.0)

if __name__ == "__main__":
    unittest.main()

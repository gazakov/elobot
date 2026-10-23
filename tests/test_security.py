import unittest
import os
from cogs.ranked import ROBLOX_USERNAME_REGEX

def _safe_remove_db(path: str):
    for f in (path, f"{path}-wal", f"{path}-shm"):
        if os.path.exists(f):
            try:
                os.remove(f)
            except OSError:
                pass

class TestSecurityHardening(unittest.TestCase):
    def test_roblox_username_valid(self):
        """Проверка: корректные ники Roblox проходят валидацию"""
        valid_nicks = ["Jotaro", "Dio_Brando", "Pucci123", "Giorno_7", "YBA_Master_99"]
        for nick in valid_nicks:
            self.assertTrue(bool(ROBLOX_USERNAME_REGEX.match(nick)), f"Должен быть валидным: {nick}")

    def test_roblox_username_invalid_griefing(self):
        """Проверка: краш-ники, zalgo, пробелы, инъекции и эмодзи блокируются"""
        invalid_nicks = [
            "ab",                      # Слишком короткий (< 3)
            "A" * 21,                  # Слишком длинный (> 20)
            "Jotaro Kujo",             # Пробел
            "Jotaro@123",              # Спецсимвол @
            "ДиоБрандо",               # Русские буквы (Roblox юзернеймы только латиница)
            "ٴٴٴٴٴٴٴ",                 # Арабский краш-глиф
            "<script>alert(1)</script>", # XSS / HTML инъекция
            "@everyone",               # Попытка пинга
            "👾_Gamer_👾",             # Эмодзи
        ]
        for nick in invalid_nicks:
            self.assertFalse(bool(ROBLOX_USERNAME_REGEX.match(nick)), f"Должен быть заблокирован: {nick}")

    def test_suspicious_iplogger_domains(self):
        """Проверка: IP-логгеры в пруфах блокируются"""
        suspicious_domains = ["grabify", "iplogger", "2no.co", "yip.su", "iplis.ru", "02ip.ru", "ezstat.ru"]
        bad_urls = [
            "https://grabify.link/track123",
            "http://iplogger.org/2abc",
            "https://2no.co/image.png",
        ]
        good_urls = [
            "https://discord.com/channels/123/456/789.png",
            "https://imgur.com/a/abcde",
            "https://youtube.com/watch?v=12345",
        ]

        for url in bad_urls:
            is_bad = any(dom in url.lower() for dom in suspicious_domains)
            self.assertTrue(is_bad, f"Ссылка должна определяться как логгер: {url}")

        for url in good_urls:
            is_bad = any(dom in url.lower() for dom in suspicious_domains)
            self.assertFalse(is_bad, f"Ссылка должна считаться легитимной: {url}")

    def test_proof_url_injection_characters(self):
        """Проверка: ссылки с пробелами, переводами строк и скобками markdown блокируются"""
        forbidden_chars = [" ", "\r", "\n", "\t", ")", "(", "<", ">", "\""]
        malicious_urls = [
            "https://example.com/img.png) [Free Nitro](https://scam.com",
            "https://example.com/img.png\nhttps://scam.com",
            "https://example.com/<script>",
            "https://example.com/test space.png",
        ]
        for url in malicious_urls:
            has_forbidden = any(c in url for c in forbidden_chars)
            self.assertTrue(has_forbidden, f"Инъекция должна быть обнаружена в ссылке: {url}")

    def test_build_input_cleaning(self):
        """Проверка санитизации билда стенда и спека"""
        import re
        import discord
        dirty_stand = "  Star Platinum: The World\n\n  "
        clean = re.sub(r"[\r\n\t]+", " ", dirty_stand.strip())[:32].strip()
        escaped = discord.utils.escape_markdown(clean) or "Standless"
        self.assertEqual(escaped, "Star Platinum: The World")

    def test_proof_url_strict_validation(self):
        """Проверка: новая функция validate_proof_url блокирует Markdown injection и невалидные хосты"""
        from cogs.matches import validate_proof_url
        valid, _ = validate_proof_url("https://youtube.com/watch?v=123")
        self.assertTrue(valid)

        bad_urls = [
            "http:///test",
            "ftp://example.com/proof.png",
            "https://example.com/img.png[click](https://evil.com)",
            "https://grabify.link/track123",
            "javascript:alert(1)",
        ]
        for url in bad_urls:
            val, err = validate_proof_url(url)
            self.assertFalse(val, f"URL {url} должен быть заблокирован: {err}")

    def test_get_user_rank_position_non_existent_and_unranked(self):
        """Проверка SEC-03: несуществующие и несыгравшие игроки получают None вместо #1 места"""
        from database import Database
        import os
        test_db = "test_sec_pos.sqlite"
        _safe_remove_db(test_db)
        db = Database(test_db)

        # Несуществующий пользователь
        self.assertIsNone(db.get_user_rank_position(999999))

        # Пользователь без матчей (0W / 0L)
        db.get_or_create_user(1001, "NewPlayer")
        self.assertIsNone(db.get_user_rank_position(1001))

        # После матча позиция появляется
        db.get_or_create_user(1002, "OtherPlayer")
        db.record_match(1001, 1002, 999)
        self.assertEqual(db.get_user_rank_position(1001), 1)
        self.assertEqual(db.get_user_rank_position(1002), 2)

        db.close()
        _safe_remove_db(test_db)

    def test_undo_last_match_bola_idor_authorization(self):
        """Проверка SEC-01: только автор матча или админ может отменить матч"""
        from database import Database
        import os
        test_db = "test_sec_idor.sqlite"
        _safe_remove_db(test_db)
        db = Database(test_db)

        db.get_or_create_user(1, "P1")
        db.get_or_create_user(2, "P2")
        _, match_id = db.record_match(1, 2, rep_id=777)

        # Попытка чужого респа (ID 888) отменить матч без прав администратора
        success, _ = db.undo_last_match(match_id, rep_id=888, is_admin=False)
        self.assertFalse(success, "Чужой респ не должен иметь права отменить матч!")

        # Автор матча (ID 777) успешно отменяет свой матч
        success_author, match_data = db.undo_last_match(match_id, rep_id=777, is_admin=False)
        self.assertTrue(success_author, "Автор матча должен иметь возможность его отменить")
        self.assertIsNotNone(match_data)

        db.close()
        _safe_remove_db(test_db)

    def test_undo_last_match_archived_season_blocked(self):
        """Проверка SEC-01: запрещен откат матчей архивных сезонов"""
        from database import Database
        import os
        test_db = "test_sec_season.sqlite"
        _safe_remove_db(test_db)
        db = Database(test_db)

        db.get_or_create_user(1, "P1")
        db.get_or_create_user(2, "P2")
        _, m1 = db.record_match(1, 2, rep_id=999)

        # Сброс сезона
        db.reset_season("Сезон 2")

        # Попытка отката матча m1 из Сезона 1 в Сезоне 2
        success, _ = db.undo_last_match(m1, rep_id=999, is_admin=True)
        self.assertFalse(success, "Откат матча из прошлого сезона должен быть заблокирован!")

        db.close()
        _safe_remove_db(test_db)

    def test_undo_last_match_streak_recalculation(self):
        """Проверка SEC-10: корректное восстановление стрика побед при отмене поражения"""
        from database import Database
        import os
        test_db = "test_sec_streak.sqlite"
        _safe_remove_db(test_db)
        db = Database(test_db)

        db.get_or_create_user(1, "P1")
        db.get_or_create_user(2, "P2")

        # 2 победы подряд для P1 (streak = 2)
        db.record_match(1, 2, rep_id=999)
        db.record_match(1, 2, rep_id=999)
        self.assertEqual(db.get_or_create_user(1)["streak"], 2)

        # Поражение P1 (streak = -1)
        _, loss_match_id = db.record_match(2, 1, rep_id=999)
        self.assertEqual(db.get_or_create_user(1)["streak"], -1)

        # Отмена поражения должна вернуть стрик +2, а не сбросить в 0!
        success, _ = db.undo_last_match(loss_match_id)
        self.assertTrue(success)
        self.assertEqual(db.get_or_create_user(1)["streak"], 2)

        db.close()
        _safe_remove_db(test_db)

    def test_is_resp_or_admin_role_spoofing(self):
        """Проверка SEC-02: защита от спуфинга имени роли, когда в конфиге задан Role ID"""
        from unittest.mock import MagicMock
        import config
        from cogs.matches import is_resp_or_admin

        # Задаем RESP_ROLE_ID в конфиге
        original_resp_id = config.RESP_ROLE_ID
        try:
            config.RESP_ROLE_ID = 111222333

            mock_interaction = MagicMock()
            mock_interaction.guild = MagicMock()
            mock_member = MagicMock()
            mock_member.guild_permissions.administrator = False

            # Фейковая роль с именем "Респ", но другим ID 999999
            fake_role = MagicMock()
            fake_role.name = "Респ"
            fake_role.id = 999999
            mock_member.roles = [fake_role]
            mock_interaction.user = mock_member

            # Проверка должна вернуть False!
            self.assertFalse(is_resp_or_admin(mock_interaction), "Фейковая роль с именем 'Респ' не должна давать доступ, если настроен RESP_ROLE_ID")

            # Легитимная роль с правильным ID 111222333
            legit_role = MagicMock()
            legit_role.name = "КастомноеИмя"
            legit_role.id = 111222333
            mock_member.roles = [legit_role]

            self.assertTrue(is_resp_or_admin(mock_interaction), "Роль с правильным RESP_ROLE_ID должна давать доступ")
        finally:
            config.RESP_ROLE_ID = original_resp_id

    def test_sqlite_foreign_keys_and_busy_timeout(self):
        """Проверка SEC-06: PRAGMA foreign_keys включен и busy_timeout настроен"""
        from database import Database
        import os
        test_db = "test_sec_pragmas.sqlite"
        _safe_remove_db(test_db)
        db = Database(test_db)

        cur = db.conn.cursor()
        cur.execute("PRAGMA foreign_keys;")
        fk_enabled = cur.fetchone()[0]
        self.assertEqual(fk_enabled, 1, "PRAGMA foreign_keys должен быть включен (значение 1)")

        cur.execute("PRAGMA busy_timeout;")
        busy_timeout = cur.fetchone()[0]
        self.assertGreaterEqual(busy_timeout, 5000, "PRAGMA busy_timeout должен быть настроен (>= 5000ms)")

        db.close()
        _safe_remove_db(test_db)

    def test_duck_role_and_evade_detection(self):
        """Проверка: поиск роли Duck и распознавание иммунитета Duck Evade"""
        from cogs.matches import get_duck_role, has_duck_evade
        from unittest.mock import MagicMock
        import config

        # 1. Поиск роли Duck
        mock_guild = MagicMock()
        duck_role = MagicMock()
        duck_role.name = "Duck"
        duck_role.id = 555
        mock_guild.roles = [duck_role]
        mock_guild.get_role.return_value = duck_role

        self.assertEqual(get_duck_role(mock_guild), duck_role)

        # 2. Проверка Duck Evade
        mock_member = MagicMock()
        evade_role = MagicMock()
        evade_role.name = "Duck Evade"
        evade_role.id = 777
        mock_member.roles = [evade_role]

        self.assertTrue(has_duck_evade(mock_member))

        # Обычный участник без Duck Evade
        regular_member = MagicMock()
        regular_role = MagicMock()
        regular_role.name = "Silver"
        regular_role.id = 888
        regular_member.roles = [regular_role]

        self.assertFalse(has_duck_evade(regular_member))

    def test_get_duck_channel_lookup(self):
        """Проверка: поиск канала даков по настройке в БД и по авто-поиску имени"""
        import asyncio
        import discord
        from cogs.matches import get_duck_channel
        from database import Database
        from unittest.mock import MagicMock

        mock_guild = MagicMock()
        ch_named = MagicMock(spec=discord.TextChannel)
        ch_named.name = "даки-логи"
        ch_named.id = 999111
        mock_guild.text_channels = [ch_named]
        mock_guild.get_channel.return_value = ch_named

        db = Database(":memory:")
        try:
            # 1. Авто-поиск по имени "даки-логи"
            found = asyncio.run(get_duck_channel(mock_guild, db))
            self.assertEqual(found, ch_named)

            # 2. Поиск по явной настройке в БД
            db.set_setting("duck_channel_id", "777888")
            ch_specific = MagicMock(spec=discord.TextChannel)
            ch_specific.id = 777888
            mock_guild.get_channel.return_value = ch_specific
            found_specific = asyncio.run(get_duck_channel(mock_guild, db))
            self.assertEqual(found_specific, ch_specific)
        finally:
            db.close()

if __name__ == "__main__":
    unittest.main()

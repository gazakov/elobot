import unittest
import os
from database import Database

class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.test_db_path = "test_elo.sqlite"
        if os.path.exists(self.test_db_path):
            os.remove(self.test_db_path)
        self.db = Database(self.test_db_path)

    def tearDown(self):
        self.db.close()
        for f in (self.test_db_path, f"{self.test_db_path}-wal", f"{self.test_db_path}-shm"):
            if os.path.exists(f):
                try:
                    os.remove(f)
                except OSError:
                    pass

    def test_user_creation_and_defaults(self):
        """Проверка создания пользователя и дефолтных значений"""
        user = self.db.get_or_create_user(discord_id=12345, roblox_username="Jotaro")
        self.assertEqual(user["discord_id"], 12345)
        self.assertEqual(user["roblox_username"], "Jotaro")
        self.assertEqual(user["rating"], 1500.0)
        self.assertEqual(user["rd"], 350.0)
        self.assertEqual(user["wins"], 0)
        self.assertEqual(user["losses"], 0)
        self.assertEqual(user["streak"], 0)

    def test_link_roblox_username(self):
        """Проверка привязки никнейма в Roblox"""
        self.db.get_or_create_user(discord_id=111)
        updated = self.db.link_roblox(discord_id=111, roblox_username="DioTheWorld")
        self.assertEqual(updated["roblox_username"], "DioTheWorld")

    def test_record_match(self):
        """Проверка регистрации матча, изменения статы и стриков"""
        self.db.get_or_create_user(101, "WinnerP1")
        self.db.get_or_create_user(102, "LoserP2")

        update, match_id = self.db.record_match(winner_id=101, loser_id=102, rep_id=999, proof_url="http://proof.jpg")
        self.assertGreater(match_id, 0)
        self.assertGreater(update.winner_delta, 100.0)
        self.assertLess(update.loser_delta, -100.0)

        # Проверяем победителя в БД
        winner = self.db.get_or_create_user(101)
        self.assertEqual(winner["wins"], 1)
        self.assertEqual(winner["losses"], 0)
        self.assertEqual(winner["streak"], 1)
        self.assertGreater(winner["peak_rating"], 1500.0)

        # Проверяем проигравшего в БД
        loser = self.db.get_or_create_user(102)
        self.assertEqual(loser["wins"], 0)
        self.assertEqual(loser["losses"], 1)
        self.assertEqual(loser["streak"], -1)

    def test_undo_match(self):
        """Проверка отката ошибочного матча"""
        self.db.get_or_create_user(101, "P1")
        self.db.get_or_create_user(102, "P2")

        update, match_id = self.db.record_match(winner_id=101, loser_id=102, rep_id=999)

        # Откатываем матч
        success, match_data = self.db.undo_last_match(match_id)
        self.assertTrue(success)
        self.assertIsNotNone(match_data)
        self.assertEqual(match_data["id"], match_id)

        # Рейтинги должны вернуться к исходным 1500.0
        p1 = self.db.get_or_create_user(101)
        p2 = self.db.get_or_create_user(102)
        self.assertEqual(p1["rating"], 1500.0)
        self.assertEqual(p1["wins"], 0)
        self.assertEqual(p2["rating"], 1500.0)
        self.assertEqual(p2["losses"], 0)

        # Повторный откат того же матча должен вернуть False
        failed_success, _ = self.db.undo_last_match(match_id)
        self.assertFalse(failed_success)

    def test_undo_preserves_subsequent_match(self):
        """Проверка: откат первого матча не сбрасывает очки за второй честно сыгранный матч!"""
        self.db.get_or_create_user(10, "P1")
        self.db.get_or_create_user(20, "P2")
        self.db.get_or_create_user(30, "P3")

        # Матч 1: P1 побеждает P2 (+162 ELO)
        u1, m1 = self.db.record_match(winner_id=10, loser_id=20, rep_id=999)
        # Матч 2: P1 побеждает P3 (+129 ELO)
        u2, m2 = self.db.record_match(winner_id=10, loser_id=30, rep_id=999)

        p1_mid = self.db.get_or_create_user(10)["rating"]
        self.assertGreater(p1_mid, 1750.0)

        # Откатываем ТОЛЬКО Матч 1
        self.db.undo_last_match(m1)

        p1_final = self.db.get_or_create_user(10)
        # Рейтинг НЕ должен стать 1500! Он должен сохранить победу во 2-м матче
        self.assertGreater(p1_final["rating"], 1500.0)
        self.assertEqual(p1_final["wins"], 1)

    def test_roblox_link_collision_protection(self):
        """Проверка: нельзя украсть чужой привязанный ник Roblox"""
        self.db.link_roblox(100, "BestPlayerYBA")
        with self.assertRaises(ValueError):
            self.db.link_roblox(200, "bestplayeryba") # попытка привязать тот же ник другим Discord ID

    def test_leaderboard_and_ranking(self):
        """Проверка работы таблицы лидеров и позиций"""
        self.db.get_or_create_user(1, "PlayerA")
        self.db.get_or_create_user(2, "PlayerB")
        self.db.get_or_create_user(3, "PlayerC")

        # PlayerA побеждает PlayerB
        self.db.record_match(winner_id=1, loser_id=2, rep_id=999)
        # PlayerA побеждает PlayerC
        self.db.record_match(winner_id=1, loser_id=3, rep_id=999)

        lb = self.db.get_leaderboard()
        # Должны отображаться только игроки с играми
        self.assertEqual(len(lb), 3)
        self.assertEqual(lb[0]["discord_id"], 1) # Победитель на 1 месте

        pos1 = self.db.get_user_rank_position(1)
        self.assertEqual(pos1, 1)

    def test_season_reset(self):
        """Проверка софт-ресета при смене сезона"""
        self.db.get_or_create_user(1, "TopPlayer")
        self.db.get_or_create_user(2, "MidPlayer")

        self.db.record_match(winner_id=1, loser_id=2, rep_id=999)
        p1_before = self.db.get_or_create_user(1)["rating"]

        new_season_id = self.db.reset_season(new_season_name="Сезон 2", compression=0.5)
        self.assertEqual(new_season_id, 2)

        p1_after = self.db.get_or_create_user(1)
        # Рейтинг должен быть ближе к 1500, чем до сброса
        self.assertLess(p1_after["rating"], p1_before)
        self.assertGreater(p1_after["rating"], 1500.0)
        self.assertEqual(p1_after["rd"], 200.0)
        self.assertEqual(p1_after["streak"], 0)
        self.assertEqual(p1_after["wins"], 0)
        self.assertEqual(p1_after["losses"], 0)

    def test_anti_wintrading_limit(self):
        """Проверка защиты от перелива: максимум 2 матча в сутки между одной парой"""
        self.db.get_or_create_user(10, "P1")
        self.db.get_or_create_user(20, "P2")

        # 1-й матч
        can1, _ = self.db.can_play_match(10, 20, max_daily_matches=2)
        self.assertTrue(can1)
        self.db.record_match(10, 20, rep_id=999)

        # 2-й матч
        can2, _ = self.db.can_play_match(10, 20, max_daily_matches=2)
        self.assertTrue(can2)
        self.db.record_match(20, 10, rep_id=999)

        # 3-й матч должен быть заблокирован
        can3, reason = self.db.can_play_match(10, 20, max_daily_matches=2)
        self.assertFalse(can3)
        self.assertIn("Лимит исчерпан", reason)

    def test_backup_database(self):
        """Проверка: резервная копия базы создается атомарно и содержит актуальные данные"""
        self.db.get_or_create_user(777, "BackupTestUser")
        backup_path = "test_bck.sqlite"
        if os.path.exists(backup_path):
            os.remove(backup_path)

        saved = self.db.backup_db(backup_path)
        self.assertTrue(os.path.exists(saved))

        # Читаем бэкап
        bck_db = Database(saved)
        user = bck_db.get_or_create_user(777)
        self.assertEqual(user["roblox_username"], "BackupTestUser")
        bck_db.close()
        if os.path.exists(backup_path):
            os.remove(backup_path)

    def test_cleanup_old_backups(self):
        """Проверка автоматической ротации и очистки бэкапов"""
        test_dir = "test_backups_dir"
        os.makedirs(test_dir, exist_ok=True)
        try:
            # Создаем 5 фиктивных файлов бэкапов
            for i in range(5):
                f_path = os.path.join(test_dir, f"backup_{i}.sqlite")
                with open(f_path, "w") as f:
                    f.write("test")

            # Ограничиваем до max_files=2
            deleted = self.db.cleanup_old_backups(backup_dir=test_dir, max_files=2)
            self.assertEqual(deleted, 3)
            remaining = [f for f in os.listdir(test_dir) if f.endswith(".sqlite")]
            self.assertEqual(len(remaining), 2)
        finally:
            import shutil
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_admin_set_user_rating(self):
        """Проверка: ручная корректировка рейтинга администратором"""
        self.db.get_or_create_user(888, "AdminAdjustUser")
        updated = self.db.set_user_rating(888, 1950.0, reason="Компенсация за баг")
        self.assertEqual(updated["rating"], 1950.0)
        self.assertEqual(updated["peak_rating"], 1950.0)

    def test_update_user_build(self):
        """Проверка обновления стенда и спека игрока"""
        self.db.get_or_create_user(999, "GiornoGiovanna")
        updated = self.db.update_user_build(999, "GER", "Boxing")
        self.assertEqual(updated["stand"], "GER")
        self.assertEqual(updated["spec"], "Boxing")

        fetched = self.db.get_or_create_user(999)
        self.assertEqual(fetched["stand"], "GER")
        self.assertEqual(fetched["spec"], "Boxing")

    def test_apply_inactivity_decay_all(self):
        """Проверка фонового распада RD для неактивных игроков"""
        self.db.get_or_create_user(501, "ActivePlayer")
        self.db.get_or_create_user(502, "InactivePlayer")

        # Симулируем откалиброванный RD
        with self.db._lock:
            with self.db._get_connection() as conn:
                conn.execute("UPDATE users SET rd = 70.0, updated_at = CURRENT_TIMESTAMP WHERE discord_id = 501")
                # Устанавливаем дату обновления 20 дней назад для неактивного игрока
                conn.execute("UPDATE users SET rd = 70.0, updated_at = datetime('now', '-20 days') WHERE discord_id = 502")
                conn.commit()

        decayed_count = self.db.apply_inactivity_decay_all()
        self.assertEqual(decayed_count, 1)

        active = self.db.get_or_create_user(501)
        inactive = self.db.get_or_create_user(502)
        self.assertEqual(active["rd"], 70.0)
        self.assertGreater(inactive["rd"], 70.0)

    def test_apply_duck_penalty(self):
        """Проверка: списание ELO за Дак и сброс винстрика"""
        u = self.db.get_or_create_user(777, "Ducker")
        with self.db._lock:
            with self.db._get_connection() as conn:
                conn.execute("UPDATE users SET rating = 1500.0, streak = 5 WHERE discord_id = 777")
                conn.commit()

        # Применяем штраф 25 ELO
        res = self.db.apply_duck_penalty(777, penalty=25.0, reason="Отказ от боя")
        self.assertEqual(res["old_rating"], 1500.0)
        self.assertEqual(res["rating"], 1475.0)
        self.assertEqual(res["delta"], -25.0)
        self.assertLessEqual(res["streak"], 0)

        # Проверка нижней границы (100.0)
        res_low = self.db.apply_duck_penalty(777, penalty=2000.0)
        self.assertEqual(res_low["rating"], 100.0)

    def test_undo_recalculates_peak_rating(self):
        """Проверка: откат матча сбрасывает накрученный пиковый рейтинг (защита от фейк-флекса)"""
        self.db.get_or_create_user(601, "P1")
        self.db.get_or_create_user(602, "P2")

        # P1 выигрывает матч, поднимает рейтинг и пик
        _, match_id = self.db.record_match(601, 602, 999)
        p1_won = self.db.get_or_create_user(601)
        self.assertGreater(p1_won["peak_rating"], 1500.0)

        # Откатываем матч — пиковый рейтинг должен вернуться к 1500.0, а не оставаться завышенным
        self.db.undo_last_match(match_id)
        p1_reverted = self.db.get_or_create_user(601)
        self.assertEqual(p1_reverted["peak_rating"], 1500.0)
        self.assertEqual(p1_reverted["streak"], 0)

    def test_record_match_same_user_raises(self):
        """Проверка: игра против самого себя вызывает исключение в БД"""
        self.db.get_or_create_user(701, "SelfPlayer")
        with self.assertRaises(ValueError):
            self.db.record_match(winner_id=701, loser_id=701, rep_id=999)

    def test_settings_get_and_set(self):
        """Проверка сохранения и чтения настроек (VIP URL и др.)"""
        self.assertIsNone(self.db.get_setting("vip_server_url"))
        self.db.set_setting("vip_server_url", "https://roblox.com/games/share?code=test")
        self.assertEqual(self.db.get_setting("vip_server_url"), "https://roblox.com/games/share?code=test")
        self.db.set_setting("vip_server_url", "https://roblox.com/games/share?code=updated")
        self.assertEqual(self.db.get_setting("vip_server_url"), "https://roblox.com/games/share?code=updated")

    def test_multiple_league_vips(self):
        """Проверка мульти-слотов VIP-серверов Лиги (VIP 1, VIP 2, etc.)"""
        self.assertEqual(self.db.get_league_vips(), {})
        self.db.set_league_vip(1, "https://roblox.com/vip1")
        self.db.set_league_vip(2, "https://roblox.com/vip2")
        vips = self.db.get_league_vips()
        self.assertEqual(len(vips), 2)
        self.assertEqual(vips["1"], "https://roblox.com/vip1")
        self.assertEqual(vips["2"], "https://roblox.com/vip2")

        # Удаление одного слота
        self.db.remove_league_vip(1)
        vips_after = self.db.get_league_vips()
        self.assertNotIn("1", vips_after)
        self.assertIn("2", vips_after)

        # Очистка всех
        self.db.remove_league_vip(None)
        self.assertEqual(self.db.get_league_vips(), {})

    def test_league_vip_reservations(self):
        """Проверка динамического бронирования, освобождения и статуса VIP-серверов Лиги"""
        self.db.set_league_vip(1, "https://roblox.com/vip1")
        self.db.set_league_vip(2, "https://roblox.com/vip2")

        # 1. Первый свободный слот должен быть 1
        slot, url = self.db.get_available_league_vip()
        self.assertEqual(slot, "1")
        self.assertEqual(url, "https://roblox.com/vip1")

        # 2. Бронируем слот 1 для дуэли
        ok = self.db.reserve_league_vip(slot="1", challenge_id=101, channel_id=201, p1_id=111, p2_id=222)
        self.assertTrue(ok)

        # 3. Теперь свободным должен быть слот 2
        slot2, url2 = self.db.get_available_league_vip()
        self.assertEqual(slot2, "2")
        self.assertEqual(url2, "https://roblox.com/vip2")

        # 4. Бронируем слот 2
        self.db.reserve_league_vip(slot="2", challenge_id=102, channel_id=202, p1_id=333, p2_id=444)

        # 5. Больше свободных слотов нет
        slot_none, url_none = self.db.get_available_league_vip()
        self.assertIsNone(slot_none)
        self.assertIsNone(url_none)

        # 6. Проверяем get_league_vips_status
        status = self.db.get_league_vips_status()
        self.assertEqual(len(status), 2)
        self.assertTrue(status[0]["occupied"])
        self.assertTrue(status[1]["occupied"])

        # 7. Освобождаем слот по игрокам матча (111 vs 222)
        freed = self.db.release_league_vip_by_players(111, 222)
        self.assertEqual(freed, "1")

        # 8. Слот 1 снова свободен!
        slot_freed, url_freed = self.db.get_available_league_vip()
        self.assertEqual(slot_freed, "1")
        self.assertEqual(url_freed, "https://roblox.com/vip1")

        status_after = self.db.get_league_vips_status()
        self.assertFalse(status_after[0]["occupied"])
        self.assertTrue(status_after[1]["occupied"])


    def test_user_personal_vip(self):
        """Проверка сохранения, чтения и очистки персонального VIP-сервера пользователя"""
        self.db.get_or_create_user(801, "PlayerVip")
        self.assertIsNone(self.db.get_user_vip(801))

        # Установка персонального VIP
        self.db.set_user_vip(801, "https://www.roblox.com/share?code=personal1")
        self.assertEqual(self.db.get_user_vip(801), "https://www.roblox.com/share?code=personal1")

        # Проверка что vip_server_url присутствует в словаре пользователя
        u = self.db.get_or_create_user(801)
        self.assertEqual(u["vip_server_url"], "https://www.roblox.com/share?code=personal1")

        # Очистка персонального VIP
        self.db.set_user_vip(801, None)
        self.assertIsNone(self.db.get_user_vip(801))

    def test_user_build_and_stats(self):
        """Проверка сохранения билда, записи матчей по связкам и подсчета винрейта связок"""
        self.db.get_or_create_user(901, "PlayerKCR")
        self.db.get_or_create_user(902, "PlayerGER")

        self.db.update_user_build(901, "KCR", "Boxing")
        self.db.update_user_build(902, "GER", "Hamon")

        u1 = self.db.get_or_create_user(901)
        self.assertEqual(u1["stand"], "KCR")
        self.assertEqual(u1["spec"], "Boxing")

        # До матча стата пустая
        s1 = self.db.get_user_build_stats(901, "KCR + Boxing")
        self.assertEqual(s1["wins"], 0)
        self.assertEqual(s1["winrate"], 0.0)

        # Регистрация матча без явного указания билдов -> подтягиваются дефолтные билды игроков
        _, match_id = self.db.record_match(winner_id=901, loser_id=902, rep_id=999)

        s1_after = self.db.get_user_build_stats(901, "KCR + Boxing")
        self.assertEqual(s1_after["wins"], 1)
        self.assertEqual(s1_after["losses"], 0)
        self.assertEqual(s1_after["winrate"], 100.0)

        s2_after = self.db.get_user_build_stats(902, "GER + Hamon")
        self.assertEqual(s2_after["wins"], 0)
        self.assertEqual(s2_after["losses"], 1)
        self.assertEqual(s2_after["winrate"], 0.0)

        # Откат матча
        self.db.undo_last_match(match_id)
        s1_reverted = self.db.get_user_build_stats(901, "KCR + Boxing")
        self.assertEqual(s1_reverted["wins"], 0)
        self.assertEqual(s1_reverted["losses"], 0)

    def test_record_match_custom_build(self):
        """Проверка матча с кастомной связкой (например, Any vs Any)"""
        self.db.get_or_create_user(905, "PlayerA")
        self.db.get_or_create_user(906, "PlayerB")

        _, match_id = self.db.record_match(
            winner_id=905,
            loser_id=906,
            rep_id=999,
            winner_build="SPTW + Pluck",
            loser_build="TWOH + Spin"
        )

        s_a = self.db.get_user_build_stats(905, "SPTW + Pluck")
        self.assertEqual(s_a["wins"], 1)
        self.assertEqual(s_a["losses"], 0)

        s_b = self.db.get_user_build_stats(906, "TWOH + Spin")
        self.assertEqual(s_b["wins"], 0)
        self.assertEqual(s_b["losses"], 1)

        all_stats_a = self.db.get_all_user_build_stats(905)
        self.assertEqual(len(all_stats_a), 1)
        self.assertEqual(all_stats_a[0]["build_name"], "SPTW + Pluck")

    def test_record_match_with_other_notes(self):
        """Проверка сохранения параметра other (прочее/заметки к матчу)"""
        self.db.get_or_create_user(910, "PlayerX")
        self.db.get_or_create_user(911, "PlayerY")

        _, match_id = self.db.record_match(
            winner_id=910,
            loser_id=911,
            rep_id=999,
            proof_url="https://youtube.com/watch?v=123",
            winner_build="GER + Pluck",
            loser_build="SP + Boxing",
            other="2-0, чистая победа без лагов"
        )

        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT other FROM matches WHERE id = ?", (match_id,))
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["other"], "2-0, чистая победа без лагов")

    def test_user_bio_gang_alts(self):
        """Проверка сохранения и обновления bio, gang, alts"""
        self.db.get_or_create_user(910, "LorePlayer")
        
        # Начальные значения None
        u = self.db.get_or_create_user(910)
        self.assertIsNone(u.get("bio"))
        self.assertIsNone(u.get("gang"))
        self.assertIsNone(u.get("alts"))

        # Установка по отдельности
        self.db.update_user_gang(910, "GANGHUB")
        self.db.update_user_bio(910, "Играю в YBA с 2021 года, мейн KCR.")
        self.db.update_user_alts(910, "alt_account1, smurf_fox")

        u = self.db.get_or_create_user(910)
        self.assertEqual(u["gang"], "GANGHUB")
        self.assertEqual(u["bio"], "Играю в YBA с 2021 года, мейн KCR.")
        self.assertEqual(u["alts"], "alt_account1, smurf_fox")

        # Очистка
        self.db.update_user_gang(910, None)
        self.db.update_user_bio(910, None)
        self.db.update_user_alts(910, None)
        u_cleared = self.db.get_or_create_user(910)
        self.assertIsNone(u_cleared["gang"])
        self.assertIsNone(u_cleared["bio"])
        self.assertIsNone(u_cleared["alts"])

    def test_update_user_profile_details_modal(self):
        """Проверка комплексного обновления профиля (как в Modal)"""
        self.db.get_or_create_user(920, "ModalPlayer")
        self.db.update_user_profile_details(
            discord_id=920,
            gang="Passione",
            bio="Моя длинная история в лиге...",
            alts="second_acc"
        )
        u = self.db.get_or_create_user(920)
        self.assertEqual(u["gang"], "Passione")
        self.assertEqual(u["bio"], "Моя длинная история в лиге...")
        self.assertEqual(u["alts"], "second_acc")

    def test_challenge_create_fetch_and_pending(self):
        """Проверка создания, чтения и поиска активных вызовов в БД"""
        cid = self.db.create_challenge(
            guild_id=123,
            channel_id=456,
            message_id=789,
            challenger_id=111,
            challenged_id=222,
            format="T2 - Main vs Main",
            server="Hesse (Германия)"
        )
        self.assertGreater(cid, 0)

        # Поиск по ID
        ch = self.db.get_challenge(cid)
        self.assertIsNotNone(ch)
        self.assertEqual(ch["challenger_id"], 111)
        self.assertEqual(ch["challenged_id"], 222)
        self.assertEqual(ch["status"], "pending")
        self.assertEqual(ch["format"], "T2 - Main vs Main")
        self.assertEqual(ch["server"], "Hesse (Германия)")

        # Поиск по message_id
        by_msg = self.db.get_challenge_by_message(789)
        self.assertIsNotNone(by_msg)
        self.assertEqual(by_msg["id"], cid)

        # Проверка get_pending_challenge
        pending = self.db.get_pending_challenge(111, 222)
        self.assertIsNotNone(pending)
        self.assertEqual(pending["id"], cid)

        # В обратную сторону (222 -> 111) пока вызова нет
        self.assertIsNone(self.db.get_pending_challenge(222, 111))

    def test_challenge_status_update_and_expiration(self):
        """Проверка обновления статуса вызова и выборки просроченных для Авто-Дака (24h)"""
        from datetime import datetime, timezone, timedelta

        now = datetime.now(timezone.utc)
        past_time = now - timedelta(hours=25)
        future_time = now + timedelta(hours=23)

        # Вызов 1: просрочен (25 часов назад)
        cid_expired = self.db.create_challenge(
            guild_id=123,
            channel_id=456,
            message_id=1001,
            challenger_id=501,
            challenged_id=502,
            format="T1 - Any vs Any",
            server="Hesse (Германия)",
            expires_at=past_time
        )

        # Вызов 2: активный (истекает через 23 часа)
        cid_active = self.db.create_challenge(
            guild_id=123,
            channel_id=456,
            message_id=1002,
            challenger_id=601,
            challenged_id=602,
            format="T2 - Main vs Main",
            server="North Holland (Нидерланды)",
            expires_at=future_time
        )

        # get_expired_pending_challenges должен вернуть только первый вызов
        expired = self.db.get_expired_pending_challenges()
        self.assertEqual(len(expired), 1)
        self.assertEqual(expired[0]["id"], cid_expired)
        self.assertEqual(expired[0]["status"], "pending")

        # Применяем Авто-Дак (статус 'ducked')
        updated = self.db.update_challenge_status(cid_expired, "ducked")
        self.assertTrue(updated)

        # Теперь просроченных pending вызовов не осталось
        expired_after = self.db.get_expired_pending_challenges()
        self.assertEqual(len(expired_after), 0)

        # Активный вызов принимается игроком (статус 'accepted')
        self.db.update_challenge_status_by_message(1002, "accepted")
        ch_active = self.db.get_challenge(cid_active)
        self.assertEqual(ch_active["status"], "accepted")

    def test_user_language_persistence(self):
        """Проверка сохранения и извлечения языковых предпочтений пользователя"""
        # По умолчанию язык не установлен (None)
        self.assertIsNone(self.db.get_user_language(888))

        # Установка русского языка
        self.db.set_user_language(888, "ru")
        self.assertEqual(self.db.get_user_language(888), "ru")

        # Установка английского языка
        self.db.set_user_language(888, "en")
        self.assertEqual(self.db.get_user_language(888), "en")

        # Некорректный язык вызывает ValueError
        with self.assertRaises(ValueError):
            self.db.set_user_language(888, "fr")

    def test_activity_tracking(self):
        """Проверка подсчета сообщений, войса и рейтинга активности"""
        uid = 555
        self.assertEqual(self.db.increment_message_count(uid), 1)
        self.assertEqual(self.db.increment_message_count(uid), 2)
        self.assertEqual(self.db.add_voice_seconds(uid, 3600.0), 3600.0)

        act = self.db.get_user_activity(uid)
        self.assertEqual(act["messages_count"], 2)
        self.assertEqual(act["voice_seconds"], 3600.0)
        self.assertEqual(act["activity_rank"], 1)

    def test_reputation_system(self):
        """Проверка системы лайков и дизлайков (репутации)"""
        target = 777
        u1, u2, u3, u4, u5 = 1, 2, 3, 4, 5
        d1, d2, d3 = 10, 11, 12

        # 5 лайков
        for u in [u1, u2, u3, u4, u5]:
            ok, _, _ = self.db.vote_reputation(u, target, 1)
            self.assertTrue(ok)

        # 3 дизлайка
        for d in [d1, d2, d3]:
            ok, _, _ = self.db.vote_reputation(d, target, -1)
            self.assertTrue(ok)

        rep = self.db.get_user_reputation(target)
        self.assertEqual(rep["likes"], 5)
        self.assertEqual(rep["dislikes"], 3)
        self.assertEqual(rep["rep"], 2)  # 5 - 3 = 2!

        # Самолайк запрещен
        ok, msg, _ = self.db.vote_reputation(target, target, 1)
        self.assertFalse(ok)
        self.assertIn("самому себе", msg)

        # Повторный одинаковый голос отклоняется
        ok, msg, _ = self.db.vote_reputation(u1, target, 1)
        self.assertFalse(ok)
        self.assertIn("уже поставили", msg)

        # Смена голоса с лайка на дизлайк
        ok, _, new_rep = self.db.vote_reputation(u1, target, -1)
        self.assertTrue(ok)
        self.assertEqual(new_rep["likes"], 4)
        self.assertEqual(new_rep["dislikes"], 4)
        self.assertEqual(new_rep["rep"], 0)

    def test_remove_league_vip_clears_reservations(self):
        """Проверка очистки активных броней при удалении VIP-сервера Лиги"""
        self.db.set_league_vip(1, "https://roblox.com/vip1")
        self.db.set_league_vip(2, "https://roblox.com/vip2")

        self.db.reserve_league_vip("1", challenge_id=101, channel_id=201, p1_id=301, p2_id=401)
        self.db.reserve_league_vip("2", challenge_id=102, channel_id=202, p1_id=302, p2_id=402)

        status_before = self.db.get_league_vips_status()
        self.assertTrue(all(v["occupied"] for v in status_before))

        # Удаляем только слот 1
        self.db.remove_league_vip(1)
        status_after_one = self.db.get_league_vips_status()
        self.assertEqual(len(status_after_one), 1)
        self.assertEqual(status_after_one[0]["slot"], "2")
        self.assertTrue(status_after_one[0]["occupied"])

        # Очищаем все оставшиеся слоты
        self.db.remove_league_vip(None)
        status_empty = self.db.get_league_vips_status()
        self.assertEqual(len(status_empty), 0)

    def test_cancel_challenge_for_players_and_channel(self):
        """Проверка отмены дуэли по участникам и по ID ветки/канала"""
        cid = self.db.create_challenge(
            guild_id=1, channel_id=5555, message_id=6666,
            challenger_id=1001, challenged_id=1002,
            format="T2 - Main vs Main", server="Hesse (Германия)"
        )
        self.db.update_challenge_status(cid, "accepted")

        # Отмена по каналу
        cancelled = self.db.cancel_challenge_by_channel(5555)
        self.assertIsNotNone(cancelled)
        self.assertEqual(cancelled["id"], cid)

        ch = self.db.get_challenge_by_channel(5555)
        self.assertEqual(ch["status"], "cancelled")

        # Новый вызов для проверки отмены по игрокам
        cid2 = self.db.create_challenge(
            guild_id=1, channel_id=5556, message_id=6667,
            challenger_id=2001, challenged_id=2002,
            format="T1 - Any vs Any", server="Hesse (Германия)"
        )
        self.db.update_challenge_status(cid2, "accepted")

        cancelled2 = self.db.cancel_challenge_for_players(2001, 2002)
        self.assertIsNotNone(cancelled2)
        self.assertEqual(cancelled2["id"], cid2)

        ch2 = self.db.get_challenge_by_message(6667)
        self.assertEqual(ch2["status"], "cancelled")

    def test_leaderboard_count(self):
        """Проверка подсчета пользователей для пагинации топа"""
        initial_count = self.db.get_leaderboard_count()

        # Создаем пользователей с матчами
        self.db.record_match(winner_id=8801, loser_id=8802, rep_id=999)
        self.db.record_match(winner_id=8803, loser_id=8804, rep_id=999)

        new_count = self.db.get_leaderboard_count()
        self.assertEqual(new_count, initial_count + 4)


if __name__ == "__main__":
    unittest.main()

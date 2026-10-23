import unittest
from glicko_engine import GlickoEngine

class TestGlickoEngine(unittest.TestCase):
    def setUp(self):
        self.engine = GlickoEngine()

    def test_initial_calibration_delta(self):
        """Проверка: в первом матче новичков начисление составляет около ~162 очков"""
        res = self.engine.calculate_match(
            w_rating=1500.0, w_rd=350.0, w_vol=0.06,
            l_rating=1500.0, l_rd=350.0, l_vol=0.06
        )

        self.assertAlmostEqual(res.winner_delta, 162.3, delta=1.0)
        self.assertAlmostEqual(res.loser_delta, -162.3, delta=1.0)
        self.assertGreater(res.winner_rating_after, 1660.0)
        self.assertLess(res.loser_rating_after, 1340.0)
        # RD должно снизиться после игры
        self.assertLess(res.winner_rd_after, 350.0)
        self.assertLess(res.loser_rd_after, 350.0)

    def test_calibrated_delta(self):
        """Проверка: у откалиброванных игроков (низкий RD) шаг изменения очков составляет 10-15"""
        res = self.engine.calculate_match(
            w_rating=1600.0, w_rd=60.0, w_vol=0.06,
            l_rating=1600.0, l_rd=60.0, l_vol=0.06
        )
        self.assertGreaterEqual(res.winner_delta, 8.0)
        self.assertLessEqual(res.winner_delta, 15.0)

    def test_upset_victory(self):
        """Проверка: победа более слабого игрока над сильным дает больше очков (апсет)"""
        # Слабый (1400) побеждает сильного (1800)
        upset = self.engine.calculate_match(
            w_rating=1400.0, w_rd=80.0, w_vol=0.06,
            l_rating=1800.0, l_rd=80.0, l_vol=0.06
        )
        # Сильный (1800) побеждает слабого (1400)
        expected = self.engine.calculate_match(
            w_rating=1800.0, w_rd=80.0, w_vol=0.06,
            l_rating=1400.0, l_rd=80.0, l_vol=0.06
        )
        self.assertGreater(upset.winner_delta, expected.winner_delta)

    def test_soft_reset(self):
        """Проверка: Soft Reset сжимает рейтинг к 1500 и сбрасывает RD"""
        # Игрок с 2000 Elo
        new_rating, new_rd = self.engine.soft_reset(current_rating=2000.0, base_rating=1500.0, compression_factor=0.5)
        self.assertEqual(new_rating, 1750.0) # 1500 + (2000 - 1500) * 0.5 = 1750
        self.assertEqual(new_rd, 200.0)

        # Игрок с 1200 Elo
        low_rating, low_rd = self.engine.soft_reset(current_rating=1200.0, base_rating=1500.0, compression_factor=0.5)
        self.assertEqual(low_rating, 1350.0) # 1500 + (1200 - 1500) * 0.5 = 1350

    def test_rd_decay_inactivity(self):
        """Проверка: инактив увеличивает RD (защита от кемпинга рейтинга)"""
        # Первую неделю RD не растет
        self.assertEqual(self.engine.decay_rd(60.0, days_inactive=5.0), 60.0)
        # Через 30 дней RD должен вырасти
        decayed = self.engine.decay_rd(60.0, days_inactive=30.0)
        self.assertGreater(decayed, 60.0)
        self.assertLessEqual(decayed, 350.0)

if __name__ == "__main__":
    unittest.main()

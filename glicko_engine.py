from dataclasses import dataclass
from typing import Tuple
import glicko2

@dataclass
class RatingUpdateResult:
    winner_rating_before: float
    winner_rating_after: float
    winner_delta: float
    winner_rd_after: float
    winner_vol_after: float

    loser_rating_before: float
    loser_rating_after: float
    loser_delta: float
    loser_rd_after: float
    loser_vol_after: float


class GlickoEngine:
    def __init__(self, default_rating: float = 1500.0, default_rd: float = 350.0, default_vol: float = 0.06):
        self.default_rating = default_rating
        self.default_rd = default_rd
        self.default_vol = default_vol

    def calculate_match(
        self,
        w_rating: float,
        w_rd: float,
        w_vol: float,
        l_rating: float,
        l_rd: float,
        l_vol: float,
    ) -> RatingUpdateResult:
        """
        Рассчитывает новые рейтинги победителя и проигравшего по системе Glicko-2.
        """
        winner = glicko2.Player(rating=w_rating, rd=w_rd, vol=w_vol)
        loser = glicko2.Player(rating=l_rating, rd=l_rd, vol=l_vol)

        # Сохраняем исходные данные соперников до обновления
        orig_w_rating, orig_w_rd = w_rating, w_rd
        orig_l_rating, orig_l_rd = l_rating, l_rd

        # Обновляем победителя (1 против проигравшего)
        winner.update_player([orig_l_rating], [orig_l_rd], [1])
        # Обновляем проигравшего (0 против победителя)
        loser.update_player([orig_w_rating], [orig_w_rd], [0])

        new_w_rating = winner.getRating()
        new_w_rd = winner.getRd()
        new_w_vol = winner.vol

        new_l_rating = loser.getRating()
        new_l_rd = loser.getRd()
        new_l_vol = loser.vol

        return RatingUpdateResult(
            winner_rating_before=orig_w_rating,
            winner_rating_after=new_w_rating,
            winner_delta=new_w_rating - orig_w_rating,
            winner_rd_after=new_w_rd,
            winner_vol_after=new_w_vol,
            loser_rating_before=orig_l_rating,
            loser_rating_after=new_l_rating,
            loser_delta=new_l_rating - orig_l_rating,
            loser_rd_after=new_l_rd,
            loser_vol_after=new_l_vol,
        )

    def decay_rd(self, current_rd: float, days_inactive: float) -> float:
        """
        Математический распад RD от инактива (защита от кемпинга рейтинга):
        Если игрок не играет длительное время, его показатель неопределенности (RD)
        плавно растет в сторону 350, делая его рейтинг провизорным.
        """
        if days_inactive <= 7.0:
            return current_rd # Первую неделю инактива штрафа нет

        # Коэффициент роста неопределенности: ~25 пунктов RD за каждые 2 недели
        c = 25.0 / (14.0 ** 0.5)
        new_rd = (current_rd ** 2 + (c ** 2) * (days_inactive - 7.0)) ** 0.5
        return min(new_rd, self.default_rd)

    def soft_reset(self, current_rating: float, base_rating: float = 1500.0, compression_factor: float = 0.5) -> Tuple[float, float]:
        """
        Мягкий сброс сезона (Soft Reset):
        Сжимает рейтинг игроков ближе к 1500 и увеличивает RD для быстрой перекалибровки.
        """
        new_rating = base_rating + (current_rating - base_rating) * compression_factor
        new_rd = 200.0 # Повышенная неопределенность для начала сезона
        return new_rating, new_rd

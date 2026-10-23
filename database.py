import os
import json
import sqlite3
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Tuple
from config import DB_PATH, BACKUP_DIR, BACKUP_MAX_DAYS, BACKUP_MAX_FILES
from glicko_engine import RatingUpdateResult, GlickoEngine
from logger import log

class Database:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.engine = GlickoEngine()
        self._lock = threading.RLock() # Reentrant Lock: полная изоляция многопоточных вызовов без взаимных блокировок
        if self.db_path != ":memory:" and os.path.dirname(self.db_path):
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self.conn.execute("PRAGMA busy_timeout = 5000;")
        self.init_db()

    def _get_connection(self) -> sqlite3.Connection:
        return self.conn

    def init_db(self):
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                # Включаем WAL-режим для многопоточного чтения/записи без блокировок
                cursor.execute("PRAGMA journal_mode=WAL;")
                cursor.execute("PRAGMA synchronous=NORMAL;")
                cursor.execute("PRAGMA foreign_keys = ON;")
                cursor.execute("PRAGMA busy_timeout = 5000;")

                # Таблица сезонов
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS seasons (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        is_active INTEGER DEFAULT 1,
                        started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Создаем Сезон 1 по умолчанию, если таблица пуста
                cursor.execute("SELECT COUNT(*) FROM seasons")
                if cursor.fetchone()[0] == 0:
                    cursor.execute("INSERT INTO seasons (name, is_active) VALUES (?, 1)", ("Сезон 1",))

                # Таблица игроков
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        discord_id INTEGER PRIMARY KEY,
                        roblox_username TEXT,
                        rating REAL DEFAULT 1500.0,
                        rd REAL DEFAULT 350.0,
                        vol REAL DEFAULT 0.06,
                        wins INTEGER DEFAULT 0,
                        losses INTEGER DEFAULT 0,
                        streak INTEGER DEFAULT 0,
                        peak_rating REAL DEFAULT 1500.0,
                        stand TEXT DEFAULT 'Standless',
                        spec TEXT DEFAULT 'Specless',
                        vip_server_url TEXT DEFAULT NULL,
                        bio TEXT DEFAULT NULL,
                        gang TEXT DEFAULT NULL,
                        alts TEXT DEFAULT NULL,
                        language TEXT DEFAULT NULL,
                        country TEXT DEFAULT NULL,
                        country_updated_at TIMESTAMP DEFAULT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Безопасная миграция колонок stand/spec/vip_server_url/bio/gang/alts/language/activity для существующих баз
                for col_name, col_def in [
                    ("stand", "TEXT DEFAULT 'Standless'"),
                    ("spec", "TEXT DEFAULT 'Specless'"),
                    ("vip_server_url", "TEXT DEFAULT NULL"),
                    ("bio", "TEXT DEFAULT NULL"),
                    ("gang", "TEXT DEFAULT NULL"),
                    ("alts", "TEXT DEFAULT NULL"),
                    ("language", "TEXT DEFAULT NULL"),
                    ("messages_count", "INTEGER DEFAULT 0"),
                    ("voice_seconds", "REAL DEFAULT 0.0"),
                    ("country", "TEXT DEFAULT NULL"),
                    ("country_updated_at", "TIMESTAMP DEFAULT NULL")
                ]:
                    try:
                        cursor.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_def}")
                    except sqlite3.OperationalError:
                        pass

                # Таблица системы репутации и лайков
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS reputation_votes (
                        author_id INTEGER,
                        target_id INTEGER,
                        vote INTEGER NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (author_id, target_id)
                    )
                """)

                # Таблица матчей
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS matches (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        season_id INTEGER,
                        winner_id INTEGER,
                        loser_id INTEGER,
                        winner_before REAL,
                        winner_after REAL,
                        loser_before REAL,
                        loser_after REAL,
                        rep_id INTEGER,
                        proof_url TEXT,
                        winner_build TEXT,
                        loser_build TEXT,
                        other TEXT DEFAULT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (season_id) REFERENCES seasons(id),
                        FOREIGN KEY (winner_id) REFERENCES users(discord_id),
                        FOREIGN KEY (loser_id) REFERENCES users(discord_id)
                    )
                """)

                # Миграция колонок winner_build, loser_build и other для существующих баз
                for col in ["winner_build", "loser_build", "other"]:
                    try:
                        cursor.execute(f"ALTER TABLE matches ADD COLUMN {col} TEXT DEFAULT NULL")
                    except sqlite3.OperationalError:
                        pass

                # Таблица статистики по связкам / билдам
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS user_build_stats (
                        discord_id INTEGER,
                        build_name TEXT,
                        wins INTEGER DEFAULT 0,
                        losses INTEGER DEFAULT 0,
                        PRIMARY KEY (discord_id, build_name)
                    )
                """)

                # Таблица настроек бота
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    )
                """)

                # Таблица 24-часовых вызовов на дуэль (GangHub League Challenges)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS challenges (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        guild_id INTEGER,
                        channel_id INTEGER,
                        message_id INTEGER,
                        challenger_id INTEGER,
                        challenged_id INTEGER,
                        format TEXT,
                        server TEXT,
                        status TEXT DEFAULT 'pending',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        expires_at TIMESTAMP
                    )
                """)

                # Таблица активных броней VIP серверов Лиги под дуэли
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS league_vip_reservations (
                        slot TEXT PRIMARY KEY,
                        challenge_id INTEGER,
                        channel_id INTEGER,
                        player1_id INTEGER,
                        player2_id INTEGER,
                        reserved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Индексы для ультрабыстрых запросов (ускорение в 100x при десятках тысяч матчей)
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_rating ON users(rating DESC, wins DESC);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_matches_users ON matches(winner_id, loser_id);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_matches_created ON matches(created_at);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_build_stats ON user_build_stats(discord_id);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_challenges_pending ON challenges(status, expires_at);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_challenges_msg ON challenges(message_id);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_challenges_pair ON challenges(challenger_id, challenged_id, status);")
                conn.commit()

    def get_active_season(self) -> Dict[str, Any]:
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM seasons WHERE is_active = 1 ORDER BY id DESC LIMIT 1")
                row = cursor.fetchone()
                if row:
                    return dict(row)
                return {"id": 1, "name": "Сезон 1", "is_active": 1}

    def get_or_create_user(self, discord_id: int, roblox_username: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM users WHERE discord_id = ?", (discord_id,))
                row = cursor.fetchone()

                if row:
                    user = dict(row)

                    # Расчет распада RD от инактива (анти-кемпинг рейтинга)
                    if user.get("updated_at"):
                        try:
                            last_str = str(user["updated_at"]).split(".")[0]
                            last_dt = datetime.strptime(last_str, "%Y-%m-%d %H:%M:%S")
                            days_inactive = (datetime.now(timezone.utc).replace(tzinfo=None) - last_dt).total_seconds() / 86400.0
                            if days_inactive > 7.0 and user["rd"] < 350.0:
                                new_rd = self.engine.decay_rd(user["rd"], days_inactive)
                                cursor.execute(
                                    "UPDATE users SET rd = ?, updated_at = CURRENT_TIMESTAMP WHERE discord_id = ?",
                                    (new_rd, discord_id)
                                )
                                conn.commit()
                                user["rd"] = new_rd
                        except Exception:
                            pass

                    if roblox_username and user.get("roblox_username") != roblox_username:
                        cursor.execute(
                            "UPDATE users SET roblox_username = ?, updated_at = CURRENT_TIMESTAMP WHERE discord_id = ?",
                            (roblox_username, discord_id)
                        )
                        conn.commit()
                        user["roblox_username"] = roblox_username
                    return user

                # Создание нового игрока
                cursor.execute(
                    """
                    INSERT INTO users (discord_id, roblox_username, rating, rd, vol, wins, losses, streak, peak_rating)
                    VALUES (?, ?, 1500.0, 350.0, 0.06, 0, 0, 0, 1500.0)
                    """,
                    (discord_id, roblox_username)
                )
                conn.commit()
                cursor.execute("SELECT * FROM users WHERE discord_id = ?", (discord_id,))
                return dict(cursor.fetchone())

    def link_roblox(self, discord_id: int, roblox_username: str) -> Dict[str, Any]:
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                # Защита от угона чужих ников
                cursor.execute(
                    "SELECT discord_id FROM users WHERE LOWER(roblox_username) = LOWER(?) AND discord_id != ?",
                    (roblox_username, discord_id)
                )
                existing = cursor.fetchone()
                if existing:
                    raise ValueError(f"Этот ник Roblox уже занят игроком <@{existing['discord_id']}>!")

                cursor.execute("SELECT * FROM users WHERE discord_id = ?", (discord_id,))
                row = cursor.fetchone()
                if row:
                    cursor.execute(
                        "UPDATE users SET roblox_username = ?, updated_at = CURRENT_TIMESTAMP WHERE discord_id = ?",
                        (roblox_username, discord_id)
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO users (discord_id, roblox_username, rating, rd, vol, wins, losses, streak, peak_rating)
                        VALUES (?, ?, 1500.0, 350.0, 0.06, 0, 0, 0, 1500.0)
                        """,
                        (discord_id, roblox_username)
                    )
                conn.commit()
                cursor.execute("SELECT * FROM users WHERE discord_id = ?", (discord_id,))
                return dict(cursor.fetchone())

    def unlink_roblox(self, discord_id: int) -> bool:
        """Отвязывает аккаунт Roblox от пользователя"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE users SET roblox_username = NULL, updated_at = CURRENT_TIMESTAMP WHERE discord_id = ?",
                    (discord_id,)
                )
                conn.commit()
                return cursor.rowcount > 0

    def record_match(
        self,
        winner_id: int,
        loser_id: int,
        rep_id: int,
        proof_url: Optional[str] = None,
        winner_build: Optional[str] = None,
        loser_build: Optional[str] = None,
        other: Optional[str] = None
    ) -> Tuple[RatingUpdateResult, int]:
        """
        Регистрирует результат матча респом:
        - берет текущие рейтинги
        - рассчитывает Glicko-2
        - обновляет пользователей, связки и логирует матч
        """
        with self._lock:
            if winner_id == loser_id:
                raise ValueError("Победитель и проигравший не могут быть одним и тем же игроком!")

            w_user = self.get_or_create_user(winner_id)
            l_user = self.get_or_create_user(loser_id)

            # Определяем связки игроков (по умолчанию — текущий зарегистрированный билд)
            w_b = (winner_build.strip() if winner_build and winner_build.strip() else f"{w_user.get('stand') or 'Standless'} + {w_user.get('spec') or 'Specless'}")[:48]
            l_b = (loser_build.strip() if loser_build and loser_build.strip() else f"{l_user.get('stand') or 'Standless'} + {l_user.get('spec') or 'Specless'}")[:48]

            update = self.engine.calculate_match(
                w_rating=w_user["rating"],
                w_rd=w_user["rd"],
                w_vol=w_user["vol"],
                l_rating=l_user["rating"],
                l_rd=l_user["rd"],
                l_vol=l_user["vol"]
            )

            season = self.get_active_season()

            with self._get_connection() as conn:
                cursor = conn.cursor()

                # Обновление победителя
                w_streak = w_user["streak"] + 1 if w_user["streak"] > 0 else 1
                w_peak = max(w_user["peak_rating"], update.winner_rating_after)
                cursor.execute(
                    """
                    UPDATE users
                    SET rating = ?, rd = ?, vol = ?, wins = wins + 1, streak = ?, peak_rating = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE discord_id = ?
                    """,
                    (update.winner_rating_after, update.winner_rd_after, update.winner_vol_after, w_streak, w_peak, winner_id)
                )

                # Обновление проигравшего
                l_streak = l_user["streak"] - 1 if l_user["streak"] < 0 else -1
                cursor.execute(
                    """
                    UPDATE users
                    SET rating = ?, rd = ?, vol = ?, losses = losses + 1, streak = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE discord_id = ?
                    """,
                    (update.loser_rating_after, update.loser_rd_after, update.loser_vol_after, l_streak, loser_id)
                )

                # Сохранение матча
                cursor.execute(
                    """
                    INSERT INTO matches (season_id, winner_id, loser_id, winner_before, winner_after, loser_before, loser_after, rep_id, proof_url, winner_build, loser_build, other)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        season["id"],
                        winner_id,
                        loser_id,
                        update.winner_rating_before,
                        update.winner_rating_after,
                        update.loser_rating_before,
                        update.loser_rating_after,
                        rep_id,
                        proof_url,
                        w_b,
                        l_b,
                        other.strip() if other and other.strip() else None
                    )
                )
                match_id = cursor.lastrowid

                # Атомарное обновление статистики по связкам
                cursor.execute(
                    """
                    INSERT INTO user_build_stats (discord_id, build_name, wins, losses)
                    VALUES (?, ?, 1, 0)
                    ON CONFLICT(discord_id, build_name) DO UPDATE SET wins = wins + 1
                    """,
                    (winner_id, w_b)
                )
                cursor.execute(
                    """
                    INSERT INTO user_build_stats (discord_id, build_name, wins, losses)
                    VALUES (?, ?, 0, 1)
                    ON CONFLICT(discord_id, build_name) DO UPDATE SET losses = losses + 1
                    """,
                    (loser_id, l_b)
                )

                conn.commit()

            return update, match_id

    def get_leaderboard(self, limit: int = 10, offset: int = 0) -> List[Dict[str, Any]]:
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT * FROM users
                    WHERE (wins + losses) > 0
                    ORDER BY rating DESC, wins DESC, discord_id ASC
                    LIMIT ? OFFSET ?
                    """,
                    (limit, offset)
                )
                return [dict(r) for r in cursor.fetchall()]

    def get_leaderboard_count(self) -> int:
        """Возвращает общее количество игроков в таблице лидеров с сыгранными матчами"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) AS total FROM users WHERE (wins + losses) > 0")
                row = cursor.fetchone()
                return int(row["total"]) if row else 0

    def can_play_match(self, user1_id: int, user2_id: int, max_daily_matches: int = 2) -> Tuple[bool, str]:
        """
        Защита от перелива (Win-trading):
        Проверяет, сколько раз эта пара игроков дралась за последние 24 часа.
        """
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT COUNT(*) AS match_count FROM matches
                    WHERE ((winner_id = ? AND loser_id = ?) OR (winner_id = ? AND loser_id = ?))
                      AND created_at >= datetime('now', '-1 day')
                    """,
                    (user1_id, user2_id, user2_id, user1_id)
                )
                count = cursor.fetchone()["match_count"]
                if count >= max_daily_matches:
                    return False, f"⚠️ Лимит исчерпан: эти игроки уже сыграли {count}/{max_daily_matches} матчей за последние 24 часа (защита от накрутки ELO)."
                return True, ""

    def get_user_rank_position(self, discord_id: int) -> Optional[int]:
        """Возвращает место игрока в общем топе"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT rating, wins, (wins + losses) AS total FROM users WHERE discord_id = ?",
                    (discord_id,)
                )
                user_row = cursor.fetchone()
                if not user_row or user_row["total"] == 0:
                    return None

                cursor.execute(
                    """
                    SELECT COUNT(*) + 1 AS pos FROM users
                    WHERE (wins + losses) > 0 AND (
                        rating > ?
                        OR (
                            rating = ?
                            AND wins > ?
                        )
                    )
                    """,
                    (user_row["rating"], user_row["rating"], user_row["wins"])
                )
                row = cursor.fetchone()
                return row["pos"] if row else None

    def get_recent_matches(self, discord_id: Optional[int] = None, limit: int = 5) -> List[Dict[str, Any]]:
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if discord_id:
                    cursor.execute(
                        """
                        SELECT m.*, w.roblox_username AS winner_roblox, l.roblox_username AS loser_roblox
                        FROM matches m
                        JOIN users w ON m.winner_id = w.discord_id
                        JOIN users l ON m.loser_id = l.discord_id
                        WHERE m.winner_id = ? OR m.loser_id = ?
                        ORDER BY m.id DESC LIMIT ?
                        """,
                        (discord_id, discord_id, limit)
                    )
                else:
                    cursor.execute(
                        """
                        SELECT m.*, w.roblox_username AS winner_roblox, l.roblox_username AS loser_roblox
                        FROM matches m
                        JOIN users w ON m.winner_id = w.discord_id
                        JOIN users l ON m.loser_id = l.discord_id
                        ORDER BY m.id DESC LIMIT ?
                        """,
                        (limit,)
                    )
                return [dict(r) for r in cursor.fetchall()]

    def get_last_match_for_rep(self, rep_id: int, is_admin: bool = False) -> Optional[Dict[str, Any]]:
        """Возвращает последний внесенный матч (этим респом или последний вообще, если админ)"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if is_admin:
                    cursor.execute("SELECT * FROM matches ORDER BY id DESC LIMIT 1")
                else:
                    cursor.execute("SELECT * FROM matches WHERE rep_id = ? ORDER BY id DESC LIMIT 1", (rep_id,))
                row = cursor.fetchone()
                return dict(row) if row else None

    def undo_last_match(
        self,
        match_id: int,
        rep_id: Optional[int] = None,
        is_admin: bool = False
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Математически корректный откат матча:
        Вычитает заработанную в этом матче дельту очков,
        не ломая и не сбрасывая последующие сыгранные матчи игроков!
        Возвращает (success, match_data) для синхронизации ролей.
        """
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM matches WHERE id = ?", (match_id,))
                match = cursor.fetchone()
                if not match:
                    return False, None

                match = dict(match)

                # Защита от BOLA/IDOR: откат разрешен только в активном сезоне
                active_season = self.get_active_season()
                if match.get("season_id") != active_season["id"]:
                    return False, None

                # Защита от BOLA/IDOR: откат может выполнять только автор матча (rep_id) или администратор
                if not is_admin and rep_id is not None and match.get("rep_id") != rep_id:
                    return False, None

                w_delta = match["winner_after"] - match["winner_before"]
                l_delta = match["loser_after"] - match["loser_before"]

                # Вычисляем максимальный пиковый рейтинг победителя из оставшихся матчей (защита от фейковых пиков)
                cursor.execute(
                    "SELECT MAX(winner_after) AS max_peak FROM matches WHERE winner_id = ? AND id != ?",
                    (match["winner_id"], match_id)
                )
                peak_row = cursor.fetchone()
                recalc_peak = max(1500.0, float(peak_row["max_peak"])) if (peak_row and peak_row["max_peak"] is not None) else 1500.0

                # Откат статистики побед/поражений связок
                if match.get("winner_build"):
                    cursor.execute(
                        """
                        UPDATE user_build_stats
                        SET wins = MAX(0, wins - 1)
                        WHERE discord_id = ? AND build_name = ?
                        """,
                        (match["winner_id"], match["winner_build"])
                    )
                if match.get("loser_build"):
                    cursor.execute(
                        """
                        UPDATE user_build_stats
                        SET losses = MAX(0, losses - 1)
                        WHERE discord_id = ? AND build_name = ?
                        """,
                        (match["loser_id"], match["loser_build"])
                    )

                # Удаляем матч перед пересчетом стриков
                cursor.execute("DELETE FROM matches WHERE id = ?", (match_id,))

                # Точный пересчет серий (стриков) по оставшимся матчам
                w_streak = self._recalculate_user_streak(cursor, match["winner_id"])
                l_streak = self._recalculate_user_streak(cursor, match["loser_id"])

                # Вычитаем дельту у победителя, восстанавливаем стрик и пик (не роняя ниже 100 ELO)
                cursor.execute(
                    """
                    UPDATE users
                    SET rating = MAX(100.0, rating - ?),
                        wins = MAX(0, wins - 1),
                        streak = ?,
                        peak_rating = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE discord_id = ?
                    """,
                    (w_delta, w_streak, recalc_peak, match["winner_id"])
                )

                # Возвращаем проигравшему отнятые очки (l_delta отрицательная: rating - l_delta прибавит очки)
                cursor.execute(
                    """
                    UPDATE users
                    SET rating = MAX(100.0, rating - ?),
                        losses = MAX(0, losses - 1),
                        streak = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE discord_id = ?
                    """,
                    (l_delta, l_streak, match["loser_id"])
                )

                conn.commit()
                return True, match

    def _recalculate_user_streak(self, cursor: sqlite3.Cursor, discord_id: int) -> int:
        """Пересчитывает актуальный стрик побед/поражений по истории матчей"""
        cursor.execute(
            """
            SELECT winner_id, loser_id FROM matches
            WHERE winner_id = ? OR loser_id = ?
            ORDER BY id DESC LIMIT 50
            """,
            (discord_id, discord_id)
        )
        history = cursor.fetchall()
        if not history:
            return 0
        is_win_streak = (history[0]["winner_id"] == discord_id)
        streak = 0
        for row in history:
            if is_win_streak and row["winner_id"] == discord_id:
                streak += 1
            elif not is_win_streak and row["loser_id"] == discord_id:
                streak -= 1
            else:
                break
        return streak

    def reset_season(self, new_season_name: str, compression: float = 0.5) -> int:
        """Сброс сезона: архивирует старый и применяет софт-ресет к игрокам"""
        with self._lock:
            # Создаем автоматический бэкап перед сбросом сезона
            try:
                bck_name = os.path.join(BACKUP_DIR, f"season_reset_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.sqlite")
                self.backup_db(bck_name)
            except Exception:
                pass

            with self._get_connection() as conn:
                cursor = conn.cursor()
                # Деактивируем прошлые сезоны
                cursor.execute("UPDATE seasons SET is_active = 0")
                cursor.execute("INSERT INTO seasons (name, is_active) VALUES (?, 1)", (new_season_name,))
                new_season_id = cursor.lastrowid

                # Софт-ресет для всех игроков
                cursor.execute("SELECT discord_id, rating FROM users")
                users = cursor.fetchall()
                for u in users:
                    new_rating, new_rd = self.engine.soft_reset(u["rating"], compression_factor=compression)
                    cursor.execute(
                        "UPDATE users SET rating = ?, rd = ?, streak = 0, wins = 0, losses = 0 WHERE discord_id = ?",
                        (new_rating, new_rd, u["discord_id"])
                    )
                conn.commit()
                return new_season_id

    def set_user_rating(self, discord_id: int, new_rating: float, reason: str = "") -> Dict[str, Any]:
        """Экстренная ручная корректировка рейтинга игрока администратором"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                user = self.get_or_create_user(discord_id)
                new_peak = max(user["peak_rating"], new_rating)
                cursor.execute(
                    """
                    UPDATE users
                    SET rating = ?, peak_rating = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE discord_id = ?
                    """,
                    (new_rating, new_peak, discord_id)
                )
                conn.commit()
                cursor.execute("SELECT * FROM users WHERE discord_id = ?", (discord_id,))
                return dict(cursor.fetchone())

    def apply_duck_penalty(self, discord_id: int, penalty: float = 25.0, reason: str = "Duck") -> Dict[str, Any]:
        """
        Применяет штраф ELO за Дак (отказ от дуэли или игнорирование вызова).
        Сбрасывает винстрик, снижает рейтинг и возвращает обновленные данные игрока с дельтой.
        """
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                user = self.get_or_create_user(discord_id)
                old_rating = float(user["rating"])
                penalty = float(max(0.0, penalty))
                new_rating = max(100.0, round(old_rating - penalty, 1))
                new_streak = min(0, user.get("streak", 0) - 1) if user.get("streak", 0) > 0 else user.get("streak", 0)
                cursor.execute(
                    """
                    UPDATE users
                    SET rating = ?, streak = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE discord_id = ?
                    """,
                    (new_rating, new_streak, discord_id)
                )
                conn.commit()
                cursor.execute("SELECT * FROM users WHERE discord_id = ?", (discord_id,))
                row = cursor.fetchone()
                res = dict(row) if row else dict(user)
                res["old_rating"] = old_rating
                res["penalty"] = round(old_rating - new_rating, 1)
                res["delta"] = -res["penalty"]
                return res

    def apply_glicko_duck_penalty(
        self,
        ducked_id: int,
        opponent_id: int,
        reason: str = "Duck"
    ) -> Dict[str, Any]:
        """
        Рассчитывает штраф за Дак по формуле Glicko-2 против конкретного оппонента (Вариант 2):
        Нарушитель получает такое же списание рейтинга, как при реальном поражении в матче,
        при этом рейтинг оппонента остается неизменным (защита от абуза винтрейдинга).
        """
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                ducked_user = self.get_or_create_user(ducked_id)
                opp_user = self.get_or_create_user(opponent_id)

                # Считаем матч по Glicko-2: оппонент = winner (1.0), дакнувший = loser (0.0)
                update = self.engine.calculate_match(
                    w_rating=opp_user["rating"],
                    w_rd=opp_user["rd"],
                    w_vol=opp_user["vol"],
                    l_rating=ducked_user["rating"],
                    l_rd=ducked_user["rd"],
                    l_vol=ducked_user["vol"]
                )

                old_rating = float(ducked_user["rating"])
                new_rating = max(100.0, round(update.loser_rating_after, 1))
                new_rd = round(update.loser_rd_after, 1)
                new_vol = update.loser_vol_after
                new_streak = min(0, ducked_user.get("streak", 0) - 1) if ducked_user.get("streak", 0) > 0 else ducked_user.get("streak", 0)

                cursor.execute(
                    """
                    UPDATE users
                    SET rating = ?, rd = ?, vol = ?, streak = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE discord_id = ?
                    """,
                    (new_rating, new_rd, new_vol, new_streak, ducked_id)
                )
                conn.commit()
                cursor.execute("SELECT * FROM users WHERE discord_id = ?", (ducked_id,))
                row = cursor.fetchone()
                res = dict(row) if row else dict(ducked_user)
                res["old_rating"] = old_rating
                res["penalty"] = round(old_rating - new_rating, 1)
                res["delta"] = -res["penalty"]
                res["opponent_rating"] = float(opp_user["rating"])
                return res

    def unlink_roblox(self, discord_id: int) -> bool:
        """Отвязывает аккаунт Roblox от пользователя"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE users SET roblox_username = NULL, updated_at = CURRENT_TIMESTAMP WHERE discord_id = ?",
                    (discord_id,)
                )
                conn.commit()
                return cursor.rowcount > 0

    def backup_db(self, backup_path: str) -> str:
        """
        Создает атомарную резервную копию базы данных без остановки работы бота
        (online zero-downtime backup SQLite) с последующей ротацией старых копий.
        """
        target_dir = os.path.dirname(os.path.abspath(backup_path))
        os.makedirs(target_dir, exist_ok=True)
        with self._lock:
            with sqlite3.connect(backup_path) as bck_conn:
                self.conn.backup(bck_conn)
            self.cleanup_old_backups(backup_dir=target_dir)
        return backup_path

    def backup_database(self, prefix: str = "auto_backup") -> str:
        """Создает автоматическую резервную копию базы данных в BACKUP_DIR с временной меткой"""
        from datetime import datetime, timezone
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(BACKUP_DIR, f"{prefix}_{timestamp}.sqlite")
        return self.backup_db(backup_path)

    def cleanup_old_backups(
        self,
        backup_dir: str = BACKUP_DIR,
        max_days: int = BACKUP_MAX_DAYS,
        max_files: int = BACKUP_MAX_FILES
    ) -> int:
        """
        Удаляет старые бэкапы базы данных по сроку давности (max_days)
        и общему лимиту файлов (max_files) для предотвращения переполнения диска.
        """
        if not os.path.exists(backup_dir):
            return 0

        deleted_count = 0
        now = time.time()
        cutoff_time = now - (max_days * 86400)

        try:
            files = [
                os.path.join(backup_dir, f)
                for f in os.listdir(backup_dir)
                if f.endswith(".sqlite") or f.endswith(".db")
            ]
            files.sort(key=lambda p: os.path.getmtime(p))

            remaining = []
            for path in files:
                try:
                    mtime = os.path.getmtime(path)
                    if mtime < cutoff_time:
                        os.remove(path)
                        deleted_count += 1
                    else:
                        remaining.append(path)
                except OSError:
                    pass

            if len(remaining) > max_files:
                excess = len(remaining) - max_files
                for path in remaining[:excess]:
                    try:
                        os.remove(path)
                        deleted_count += 1
                    except OSError:
                        pass
        except Exception as e:
            log.warning(f"Ошибка при очистке старых бэкапов: {e}")

        return deleted_count

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
                row = cursor.fetchone()
                return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, value)
                )
                conn.commit()

    def update_user_build(self, discord_id: int, stand: str, spec: str) -> Dict[str, Any]:
        """Обновляет любимый стенд и спек игрока для отображения в профиле"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                self.get_or_create_user(discord_id)
                cursor.execute(
                    "UPDATE users SET stand = ?, spec = ?, updated_at = CURRENT_TIMESTAMP WHERE discord_id = ?",
                    (stand[:32], spec[:32], discord_id)
                )
                conn.commit()
                return self.get_or_create_user(discord_id)

    def set_user_vip(self, discord_id: int, vip_url: Optional[str]) -> bool:
        """Сохраняет или удаляет персональную ссылку игрока на приватный VIP-сервер"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                self.get_or_create_user(discord_id)
                cursor.execute(
                    "UPDATE users SET vip_server_url = ?, updated_at = CURRENT_TIMESTAMP WHERE discord_id = ?",
                    (vip_url, discord_id)
                )
                conn.commit()
                return True

    def get_user_vip(self, discord_id: int) -> Optional[str]:
        """Возвращает персональную ссылку игрока на VIP-сервер"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT vip_server_url FROM users WHERE discord_id = ?", (discord_id,))
                row = cursor.fetchone()
                if row and row["vip_server_url"]:
                    return row["vip_server_url"]
                return None

    def set_user_country(self, discord_id: int, country_code: Optional[str], cooldown_days: int = 30) -> Tuple[bool, str]:
        """
        Устанавливает или сбрасывает страну пользователя с защитой по кулдауну.
        Возвращает (success, message).
        """
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                self.get_or_create_user(discord_id)
                cursor.execute("SELECT country, country_updated_at FROM users WHERE discord_id = ?", (discord_id,))
                row = cursor.fetchone()

                # Проверка кулдауна
                if row and row["country_updated_at"] and country_code is not None:
                    raw_dt = row["country_updated_at"]
                    last_upd = None
                    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
                        try:
                            last_upd = datetime.strptime(str(raw_dt), fmt)
                            break
                        except Exception:
                            pass
                    if not last_upd:
                        try:
                            last_upd = datetime.fromisoformat(str(raw_dt))
                        except Exception:
                            pass

                    if last_upd:
                        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
                        if last_upd.tzinfo is not None:
                            last_upd = last_upd.astimezone(timezone.utc).replace(tzinfo=None)
                        diff = now_naive - last_upd
                        cooldown_secs = cooldown_days * 86400
                        if diff.total_seconds() < cooldown_secs:
                            remaining_days = max(1, int(round((cooldown_secs - diff.total_seconds()) / 86400)))
                            return False, f"cooldown:{remaining_days}"

                clean_code = country_code.upper().strip() if country_code else None
                cursor.execute(
                    """
                    UPDATE users
                    SET country = ?, country_updated_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                    WHERE discord_id = ?
                    """,
                    (clean_code, discord_id)
                )
                conn.commit()
                return True, "ok"

    def admin_set_user_country(self, discord_id: int, country_code: Optional[str]) -> bool:
        """Административная установка страны без кулдауна"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                self.get_or_create_user(discord_id)
                clean_code = country_code.upper().strip() if country_code else None
                cursor.execute(
                    """
                    UPDATE users
                    SET country = ?, country_updated_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                    WHERE discord_id = ?
                    """,
                    (clean_code, discord_id)
                )
                conn.commit()
                return True

    def get_user_country(self, discord_id: int) -> Optional[str]:
        """Возвращает код страны пользователя"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT country FROM users WHERE discord_id = ?", (discord_id,))
                row = cursor.fetchone()
                return row["country"] if row and row["country"] else None


    def get_league_vips(self) -> Dict[str, str]:
        """Возвращает словарь слотов VIP серверов Лиги: {'1': 'url1', '2': 'url2', ...}"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT value FROM settings WHERE key = 'league_vips'")
                row = cursor.fetchone()
                if row and row["value"]:
                    try:
                        data = json.loads(row["value"])
                        if isinstance(data, dict):
                            return data
                    except Exception:
                        pass
                # Обратная совместимость с единичным vip_server_url
                cursor.execute("SELECT value FROM settings WHERE key = 'vip_server_url'")
                single = cursor.fetchone()
                if single and single["value"]:
                    return {"1": single["value"]}
                return {}

    def set_league_vip(self, slot: int, url: str) -> Dict[str, str]:
        """Устанавливает VIP ссылку для конкретного слота (1, 2, 3...)"""
        vips = self.get_league_vips()
        vips[str(slot)] = url
        sorted_vips = {k: vips[k] for k in sorted(vips.keys(), key=lambda x: int(x) if x.isdigit() else 999)}
        self.set_setting("league_vips", json.dumps(sorted_vips))
        if str(slot) == "1":
            self.set_setting("vip_server_url", url)
        return sorted_vips

    def remove_league_vip(self, slot: Optional[int] = None) -> Dict[str, str]:
        """Удаляет VIP ссылку из конкретного слота или очищает все слоты, освобождая брони"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if slot is None:
                    cursor.execute("DELETE FROM league_vip_reservations")
                else:
                    cursor.execute("DELETE FROM league_vip_reservations WHERE slot = ?", (str(slot),))
                conn.commit()

        if slot is None:
            self.set_setting("league_vips", "{}")
            self.set_setting("vip_server_url", None)
            return {}
        vips = self.get_league_vips()
        vips.pop(str(slot), None)
        sorted_vips = {k: vips[k] for k in sorted(vips.keys(), key=lambda x: int(x) if x.isdigit() else 999)}
        self.set_setting("league_vips", json.dumps(sorted_vips))
        if "1" in sorted_vips:
            self.set_setting("vip_server_url", sorted_vips["1"])
        else:
            self.set_setting("vip_server_url", None)
        return sorted_vips

    def get_available_league_vip(self) -> Tuple[Optional[str], Optional[str]]:
        """
        Находит первый свободный официальный VIP-сервер Лиги.
        Автоматически очищает старые брони (> 2 часов).
        Возвращает кортеж (номер слота, url) или (None, None), если все заняты.
        """
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                # Очищаем устаревшие брони (если матч завис более чем на 2 часа)
                cursor.execute("DELETE FROM league_vip_reservations WHERE reserved_at < datetime('now', '-2 hours')")
                conn.commit()

                # Получаем все занятые слоты
                cursor.execute("SELECT slot FROM league_vip_reservations")
                busy_slots = {str(row["slot"]) for row in cursor.fetchall()}

        vips = self.get_league_vips()
        sorted_keys = sorted(vips.keys(), key=lambda x: int(x) if x.isdigit() else 999)
        for s in sorted_keys:
            if s not in busy_slots:
                return s, vips[s]
        return None, None

    get_first_free_league_vip = get_available_league_vip

    def reserve_league_vip(self, slot: str, challenge_id: int, channel_id: int, p1_id: int, p2_id: int) -> bool:
        """Бронирует VIP-слот под конкретную дуэль"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO league_vip_reservations 
                    (slot, challenge_id, channel_id, player1_id, player2_id, reserved_at)
                    VALUES (?, ?, ?, ?, ?, datetime('now'))
                    """,
                    (str(slot), challenge_id, channel_id, p1_id, p2_id)
                )
                conn.commit()
                return True

    def release_league_vip_by_challenge(self, challenge_id: int) -> Optional[str]:
        """Освобождает VIP-слот по ID вызова/дуэли"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT slot FROM league_vip_reservations WHERE challenge_id = ?", (challenge_id,))
                row = cursor.fetchone()
                if row:
                    slot = str(row["slot"])
                    cursor.execute("DELETE FROM league_vip_reservations WHERE challenge_id = ?", (challenge_id,))
                    conn.commit()
                    return slot
                return None

    def release_league_vip_by_players(self, p1_id: int, p2_id: int) -> Optional[str]:
        """Освобождает VIP-слот, забронированный кем-то из игроков дуэли"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT slot FROM league_vip_reservations 
                    WHERE player1_id IN (?, ?) OR player2_id IN (?, ?)
                    """,
                    (p1_id, p2_id, p1_id, p2_id)
                )
                row = cursor.fetchone()
                if row:
                    slot = str(row["slot"])
                    cursor.execute(
                        """
                        DELETE FROM league_vip_reservations 
                        WHERE player1_id IN (?, ?) OR player2_id IN (?, ?)
                        """,
                        (p1_id, p2_id, p1_id, p2_id)
                    )
                    conn.commit()
                    return slot
                return None

    def get_league_vips_status(self) -> List[Dict[str, Any]]:
        """Возвращает подробный статус занятости всех VIP слотов Лиги"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM league_vip_reservations")
                reservations = {str(r["slot"]): dict(r) for r in cursor.fetchall()}

        vips = self.get_league_vips()
        sorted_keys = sorted(vips.keys(), key=lambda x: int(x) if x.isdigit() else 999)
        result = []
        for s in sorted_keys:
            res_info = reservations.get(s)
            result.append({
                "slot": s,
                "url": vips[s],
                "occupied": res_info is not None,
                "reservation": res_info
            })
        return result

    def get_user_language(self, discord_id: int) -> Optional[str]:
        """Возвращает сохраненный язык интерфейса пользователя ('ru' или 'en'), если задан"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT language FROM users WHERE discord_id = ?", (discord_id,))
                row = cursor.fetchone()
                if row and row["language"]:
                    lang = str(row["language"]).strip().lower()
                    if lang in ("ru", "en"):
                        return lang
                return None

    def set_user_language(self, discord_id: int, language: str) -> None:
        """Сохраняет выбранный пользователем язык интерфейса ('ru' или 'en')"""
        clean_lang = language.strip().lower()
        if clean_lang not in ("ru", "en"):
            raise ValueError("Язык должен быть 'ru' или 'en'")
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                self.get_or_create_user(discord_id)
                cursor.execute(
                    "UPDATE users SET language = ?, updated_at = CURRENT_TIMESTAMP WHERE discord_id = ?",
                    (clean_lang, discord_id)
                )
                conn.commit()

    def update_user_bio(self, discord_id: int, bio: Optional[str]) -> bool:
        """Обновляет описание/историю профиля игрока"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                self.get_or_create_user(discord_id)
                val = bio[:400].strip() if bio and bio.strip() else None
                cursor.execute(
                    "UPDATE users SET bio = ?, updated_at = CURRENT_TIMESTAMP WHERE discord_id = ?",
                    (val, discord_id)
                )
                conn.commit()
                return True

    def update_user_gang(self, discord_id: int, gang: Optional[str]) -> bool:
        """Обновляет название/тег банды (генга) игрока"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                self.get_or_create_user(discord_id)
                val = gang[:32].strip() if gang and gang.strip() else None
                cursor.execute(
                    "UPDATE users SET gang = ?, updated_at = CURRENT_TIMESTAMP WHERE discord_id = ?",
                    (val, discord_id)
                )
                conn.commit()
                return True

    def update_user_alts(self, discord_id: int, alts: Optional[str]) -> bool:
        """Обновляет список дополнительных аккаунтов (твинков) игрока"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                self.get_or_create_user(discord_id)
                val = alts[:150].strip() if alts and alts.strip() else None
                cursor.execute(
                    "UPDATE users SET alts = ?, updated_at = CURRENT_TIMESTAMP WHERE discord_id = ?",
                    (val, discord_id)
                )
                conn.commit()
                return True

    def update_user_profile_details(
        self,
        discord_id: int,
        gang: Optional[str] = None,
        bio: Optional[str] = None,
        alts: Optional[str] = None
    ) -> bool:
        """Комплексное обновление деталей профиля (для Модального окна)"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                self.get_or_create_user(discord_id)
                g_val = gang[:32].strip() if gang and gang.strip() else None
                b_val = bio[:400].strip() if bio and bio.strip() else None
                a_val = alts[:150].strip() if alts and alts.strip() else None
                cursor.execute(
                    """
                    UPDATE users
                    SET gang = ?, bio = ?, alts = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE discord_id = ?
                    """,
                    (g_val, b_val, a_val, discord_id)
                )
                conn.commit()
                return True

    def get_user_build_stats(self, discord_id: int, build_name: str) -> Dict[str, Any]:
        """Возвращает статистику побед и поражений игрока на конкретной связке"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT wins, losses FROM user_build_stats WHERE discord_id = ? AND build_name = ?",
                    (discord_id, build_name)
                )
                row = cursor.fetchone()
                if row:
                    w = row["wins"]
                    l = row["losses"]
                    total = w + l
                    wr = round((w / total) * 100, 1) if total > 0 else 0.0
                    return {"wins": w, "losses": l, "total": total, "winrate": wr}
                return {"wins": 0, "losses": 0, "total": 0, "winrate": 0.0}

    def get_all_user_build_stats(self, discord_id: int) -> List[Dict[str, Any]]:
        """Возвращает статистику по всем связкам игрока"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT build_name, wins, losses FROM user_build_stats WHERE discord_id = ? ORDER BY (wins + losses) DESC, wins DESC",
                    (discord_id,)
                )
                rows = cursor.fetchall()
                res = []
                for r in rows:
                    w = r["wins"]
                    l = r["losses"]
                    total = w + l
                    wr = round((w / total) * 100, 1) if total > 0 else 0.0
                    res.append({"build_name": r["build_name"], "wins": w, "losses": l, "total": total, "winrate": wr})
                return res

    def apply_inactivity_decay_all(self) -> int:
        """
        Фоновый демон: проверяет всех игроков в базе и начисляет распад RD тем,
        кто не играл более 7 дней (защита от кемпинга рейтинга на уровне всего ладдера).
        """
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT discord_id, rd, updated_at FROM users WHERE rd < 350.0")
                rows = cursor.fetchall()
                updated_count = 0
                now = datetime.now(timezone.utc).replace(tzinfo=None)

                for r in rows:
                    try:
                        last_str = str(r["updated_at"]).split(".")[0]
                        last_dt = datetime.strptime(last_str, "%Y-%m-%d %H:%M:%S")
                        days = (now - last_dt).total_seconds() / 86400.0
                        if days > 7.0:
                            new_rd = self.engine.decay_rd(r["rd"], days)
                            if new_rd > r["rd"]:
                                cursor.execute(
                                    "UPDATE users SET rd = ? WHERE discord_id = ?",
                                    (new_rd, r["discord_id"])
                                )
                                updated_count += 1
                    except Exception:
                        continue

                conn.commit()
                return updated_count

    # -------------------------------------------------------------
    # МЕТОДЫ 24-ЧАСОВОЙ СИСТЕМЫ ВЫЗОВОВ (CHALLENGES & AUTO-DUCK)
    # -------------------------------------------------------------

    def create_challenge(
        self,
        guild_id: int,
        channel_id: int,
        message_id: int,
        challenger_id: int,
        challenged_id: int,
        format: str,
        server: str,
        expires_at: Optional[datetime] = None
    ) -> int:
        """Создает запись о 24-часовом вызове в базе данных"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if expires_at is None:
                    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
                expires_str = expires_at.strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute(
                    """
                    INSERT INTO challenges (
                        guild_id, channel_id, message_id, challenger_id, challenged_id,
                        format, server, status, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                    """,
                    (
                        int(guild_id) if guild_id else 0,
                        int(channel_id) if channel_id else 0,
                        int(message_id) if message_id else 0,
                        int(challenger_id),
                        int(challenged_id),
                        str(format),
                        str(server),
                        expires_str
                    )
                )
                conn.commit()
                return cursor.lastrowid

    def link_challenge_message(self, challenge_id: int, message_id: int, channel_id: Optional[int] = None) -> bool:
        """Связывает запись вызова с актуальным message_id и опционально channel_id"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if channel_id is not None:
                    cursor.execute(
                        "UPDATE challenges SET message_id = ?, channel_id = ? WHERE id = ?",
                        (int(message_id), int(channel_id), int(challenge_id))
                    )
                else:
                    cursor.execute(
                        "UPDATE challenges SET message_id = ? WHERE id = ?",
                        (int(message_id), int(challenge_id))
                    )
                conn.commit()
                return cursor.rowcount > 0

    def get_last_challenge_by_challenger(self, challenger_id: int) -> Optional[Dict[str, Any]]:
        """Возвращает последний созданный вызов данным игроком"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT * FROM challenges
                    WHERE challenger_id = ?
                    ORDER BY id DESC LIMIT 1
                    """,
                    (challenger_id,)
                )
                row = cursor.fetchone()
                return dict(row) if row else None

    def get_pending_challenges_count_for_user(self, user_id: int) -> int:
        """Возвращает количество активных (pending) вызовов, созданных пользователем"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT COUNT(*) as cnt FROM challenges
                    WHERE challenger_id = ? AND status = 'pending' AND datetime(expires_at) > datetime('now')
                    """,
                    (user_id,)
                )
                row = cursor.fetchone()
                return int(row["cnt"]) if row and row["cnt"] is not None else 0

    def get_challenge(self, challenge_id: int) -> Optional[Dict[str, Any]]:
        """Возвращает информацию о вызове по его ID"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM challenges WHERE id = ?", (challenge_id,))
                row = cursor.fetchone()
                return dict(row) if row else None

    def get_challenge_by_message(self, message_id: int) -> Optional[Dict[str, Any]]:
        """Находит вызов по ID сообщения в Discord"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM challenges WHERE message_id = ?", (int(message_id),))
                row = cursor.fetchone()
                return dict(row) if row else None

    def get_challenge_by_channel(self, channel_id: int, pending_only: bool = False) -> Optional[Dict[str, Any]]:
        """Находит вызов по ID канала или ветки в Discord (приоритет активным вызовам status='pending')"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if pending_only:
                    cursor.execute(
                        "SELECT * FROM challenges WHERE channel_id = ? AND status = 'pending' ORDER BY id DESC LIMIT 1",
                        (int(channel_id),)
                    )
                else:
                    cursor.execute(
                        "SELECT * FROM challenges WHERE channel_id = ? ORDER BY (status = 'pending') DESC, id DESC LIMIT 1",
                        (int(channel_id),)
                    )
                row = cursor.fetchone()
                return dict(row) if row else None

    def get_pending_challenge(self, challenger_id: int, challenged_id: int) -> Optional[Dict[str, Any]]:
        """Проверяет наличие активного незавершенного вызова между двумя игроками"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT * FROM challenges 
                    WHERE challenger_id = ? AND challenged_id = ? 
                      AND status = 'pending' 
                      AND datetime(expires_at) > datetime('now')
                    ORDER BY id DESC LIMIT 1
                    """,
                    (challenger_id, challenged_id)
                )
                row = cursor.fetchone()
                return dict(row) if row else None

    def has_active_accepted_challenge(self, user1_id: int, user2_id: int) -> Optional[Dict[str, Any]]:
        """Проверяет, идет ли прямо сейчас активный бой между двумя игроками (status = 'accepted')"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT * FROM challenges 
                    WHERE ((challenger_id = ? AND challenged_id = ?) OR (challenger_id = ? AND challenged_id = ?))
                      AND status = 'accepted' 
                      AND datetime(expires_at) > datetime('now')
                    ORDER BY id DESC LIMIT 1
                    """,
                    (user1_id, user2_id, user2_id, user1_id)
                )
                row = cursor.fetchone()
                return dict(row) if row else None

    def get_latest_challenge_for_players(self, user1_id: int, user2_id: int) -> Optional[Dict[str, Any]]:
        """Возвращает последний активный вызов/дуэль между двумя игроками (accepted или pending)"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT * FROM challenges 
                    WHERE ((challenger_id = ? AND challenged_id = ?) OR (challenger_id = ? AND challenged_id = ?))
                      AND status IN ('accepted', 'pending')
                    ORDER BY id DESC LIMIT 1
                    """,
                    (user1_id, user2_id, user2_id, user1_id)
                )
                row = cursor.fetchone()
                return dict(row) if row else None

    def finish_challenge_for_players(self, user1_id: int, user2_id: int) -> Optional[Dict[str, Any]]:
        """Завершает активный вызов между двумя игроками (переводит status в 'finished')"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT * FROM challenges 
                    WHERE ((challenger_id = ? AND challenged_id = ?) OR (challenger_id = ? AND challenged_id = ?))
                      AND status = 'accepted'
                    ORDER BY id DESC LIMIT 1
                    """,
                    (user1_id, user2_id, user2_id, user1_id)
                )
                row = cursor.fetchone()
                if row:
                    ch_dict = dict(row)
                    cursor.execute("UPDATE challenges SET status = 'finished' WHERE id = ?", (ch_dict["id"],))
                    conn.commit()
                    return ch_dict
                return None

    def cancel_challenge_for_players(self, user1_id: int, user2_id: int) -> Optional[Dict[str, Any]]:
        """Отменяет активный вызов (status='accepted' или 'pending') между двумя игроками"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT * FROM challenges 
                    WHERE ((challenger_id = ? AND challenged_id = ?) OR (challenger_id = ? AND challenged_id = ?))
                      AND status IN ('accepted', 'pending')
                    ORDER BY id DESC LIMIT 1
                    """,
                    (user1_id, user2_id, user2_id, user1_id)
                )
                row = cursor.fetchone()
                if row:
                    ch_dict = dict(row)
                    cursor.execute("UPDATE challenges SET status = 'cancelled' WHERE id = ?", (ch_dict["id"],))
                    conn.commit()
                    return ch_dict
                return None

    def cancel_challenge_by_channel(self, channel_id: int) -> Optional[Dict[str, Any]]:
        """Отменяет активный вызов по ID канала или ветки дуэли"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT * FROM challenges 
                    WHERE channel_id = ? AND status IN ('accepted', 'pending')
                    ORDER BY id DESC LIMIT 1
                    """,
                    (channel_id,)
                )
                row = cursor.fetchone()
                if row:
                    ch_dict = dict(row)
                    cursor.execute("UPDATE challenges SET status = 'cancelled' WHERE id = ?", (ch_dict["id"],))
                    conn.commit()
                    return ch_dict
                return None

    def get_active_outgoing_challenge(self, challenger_id: int) -> Optional[Dict[str, Any]]:
        """Возвращает последний активный исходящий вызов игрока (status=pending, не истек)"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT * FROM challenges 
                    WHERE challenger_id = ? 
                      AND status = 'pending' 
                      AND datetime(expires_at) > datetime('now')
                    ORDER BY id DESC LIMIT 1
                    """,
                    (challenger_id,)
                )
                row = cursor.fetchone()
                return dict(row) if row else None

    def update_challenge_status(self, challenge_id: int, status: str) -> bool:
        """Обновляет статус вызова (accepted, declined, ducked, expired_exempt, etc.)"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE challenges SET status = ? WHERE id = ?", (status, challenge_id))
                conn.commit()
                return cursor.rowcount > 0

    def update_challenge_status_by_message(self, message_id: int, status: str) -> bool:
        """Обновляет статус вызова по ID сообщения"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE challenges SET status = ? WHERE message_id = ?", (status, message_id))
                conn.commit()
                return cursor.rowcount > 0

    def get_expired_pending_challenges(self) -> List[Dict[str, Any]]:
        """Возвращает все вызовы, чей 24-часовой срок истек, но статус все еще pending"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT * FROM challenges
                    WHERE status = 'pending' AND datetime(expires_at) <= datetime('now')
                    ORDER BY id ASC
                    """
                )
                rows = cursor.fetchall()
                return [dict(r) for r in rows]

    def increment_message_count(self, discord_id: int) -> int:
        """Инкрементирует счетчик отправленных сообщений пользователя (атомарный UPSERT)"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO users (discord_id, messages_count)
                    VALUES (?, 1)
                    ON CONFLICT(discord_id) DO UPDATE SET
                        messages_count = COALESCE(users.messages_count, 0) + 1
                    RETURNING messages_count
                    """,
                    (discord_id,)
                )
                row = cursor.fetchone()
                conn.commit()
                return row[0] if row else 1

    def add_voice_seconds(self, discord_id: int, seconds: float) -> float:
        """Добавляет проведенное время в голосовых каналах (атомарный UPSERT)"""
        if seconds <= 0:
            return 0.0
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO users (discord_id, voice_seconds)
                    VALUES (?, ?)
                    ON CONFLICT(discord_id) DO UPDATE SET
                        voice_seconds = COALESCE(users.voice_seconds, 0.0) + excluded.voice_seconds
                    RETURNING voice_seconds
                    """,
                    (discord_id, seconds)
                )
                row = cursor.fetchone()
                conn.commit()
                return row[0] if row else seconds

    def get_user_activity(self, discord_id: int) -> Dict[str, Any]:
        """Возвращает сообщения, время в войсе и место в топе по активу"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT messages_count, voice_seconds FROM users WHERE discord_id = ?", (discord_id,))
                row = cursor.fetchone()
                messages = (row["messages_count"] or 0) if row else 0
                voice = (row["voice_seconds"] or 0.0) if row else 0.0

                # Место в топе активности: 1 сообщение = 60 очков (эквивалент 1 минуте войса)
                score = messages * 60 + int(voice)
                pos = None
                if score > 0:
                    cursor.execute(
                        """
                        SELECT COUNT(*) + 1 AS pos FROM users
                        WHERE (COALESCE(messages_count, 0) * 60 + COALESCE(voice_seconds, 0)) > ?
                        """,
                        (score,)
                    )
                    pos_row = cursor.fetchone()
                    pos = pos_row["pos"] if pos_row else 1

                return {
                    "messages_count": messages,
                    "voice_seconds": voice,
                    "activity_rank": pos
                }

    def vote_reputation(self, author_id: int, target_id: int, vote: int) -> Tuple[bool, str, Dict[str, int]]:
        """
        Ставит лайк (+1) или дизлайк (-1) пользователю.
        Защита от самолайка и возможность изменить голос.
        """
        if author_id == target_id:
            return False, "❌ Вы не можете менять репутацию самому себе!", self.get_user_reputation(target_id)

        vote_val = 1 if vote > 0 else -1
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT vote FROM reputation_votes WHERE author_id = ? AND target_id = ?", (author_id, target_id))
                prev = cursor.fetchone()
                if prev and prev["vote"] == vote_val:
                    action_name = "+Rep (лайк)" if vote_val > 0 else "-Rep (дизлайк)"
                    return False, f"⚠️ Вы уже поставили {action_name} этому пользователю!", self.get_user_reputation(target_id)

                cursor.execute(
                    """
                    INSERT INTO reputation_votes (author_id, target_id, vote, created_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(author_id, target_id) DO UPDATE SET vote = excluded.vote, created_at = CURRENT_TIMESTAMP
                    """,
                    (author_id, target_id, vote_val)
                )
                conn.commit()

        rep_data = self.get_user_reputation(target_id)
        msg = "✅ Вы успешно поставили **+Rep (лайк)**!" if vote_val > 0 else "✅ Вы успешно поставили **-Rep (дизлайк)**!"
        return True, msg, rep_data

    def get_user_reputation(self, target_id: int) -> Dict[str, int]:
        """Возвращает количество лайков, дизлайков и итоговую репутацию"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT 
                        COALESCE(SUM(CASE WHEN vote = 1 THEN 1 ELSE 0 END), 0) AS likes,
                        COALESCE(SUM(CASE WHEN vote = -1 THEN 1 ELSE 0 END), 0) AS dislikes
                    FROM reputation_votes WHERE target_id = ?
                    """,
                    (target_id,)
                )
                row = cursor.fetchone()
                likes = row["likes"] if row else 0
                dislikes = row["dislikes"] if row else 0
                return {
                    "likes": likes,
                    "dislikes": dislikes,
                    "rep": likes - dislikes
                }

    def close(self):
        """Чистое закрытие базы с контрольной точкой WAL"""
        with self._lock:
            try:
                self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                self.conn.close()
            except Exception:
                pass

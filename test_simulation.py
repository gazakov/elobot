"""
Скрипт для демонстрации работы ELO/Glicko-2 и ранговой системы YBA без подключения к Discord.
Показывает калибровку, изменение очков (+162 / -162), смену разрядов и таблицу лидеров.
"""
from database import Database
from ranks import get_rank_info
import os

def run_demo():
    db_file = "demo_elo.sqlite"
    if os.path.exists(db_file):
        os.remove(db_file)

    db = Database(db_file)
    print("🚀 === ТЕСТОВАЯ СИМУЛЯЦИЯ РЕЙТИНГА YBA (GLICKO-2) ===\n")

    # Игроки
    players = [
        (101, "JotaroKujo"),
        (102, "DioBrando"),
        (103, "GiornoGiovanna"),
        (104, "Diavolo"),
        (105, "EnricoPucci"),
    ]

    for uid, rbx in players:
        db.get_or_create_user(uid, rbx)

    print("1️⃣ Все игроки стартуют с 1500 ELO (калибровка, RD = 350):\n")

    # Матч 1: Jotaro vs Dio (Калибровка, первая игра)
    print("⚔️ МАТЧ 1: JotaroKujo VS DioBrando")
    update1, m1 = db.record_match(winner_id=101, loser_id=102, rep_id=999)
    print(f"   🏆 JotaroKujo: 1500 -> {update1.winner_rating_after:.1f} (+{update1.winner_delta:.1f} ELO)")
    print(f"   💀 DioBrando:  1500 -> {update1.loser_rating_after:.1f} ({update1.loser_delta:.1f} ELO)\n")

    # Матч 2: Giorno vs Diavolo
    print("⚔️ МАТЧ 2: GiornoGiovanna VS Diavolo")
    update2, m2 = db.record_match(winner_id=103, loser_id=104, rep_id=999)
    print(f"   🏆 GiornoGiovanna: 1500 -> {update2.winner_rating_after:.1f} (+{update2.winner_delta:.1f} ELO)")
    print(f"   💀 Diavolo:        1500 -> {update2.loser_rating_after:.1f} ({update2.loser_delta:.1f} ELO)\n")

    # Матч 3: Jotaro vs Giorno (Два победителя играют друг с другом)
    print("⚔️ МАТЧ 3: JotaroKujo VS GiornoGiovanna (Оба имеют высокий ELO)")
    update3, m3 = db.record_match(winner_id=101, loser_id=103, rep_id=999)
    print(f"   🏆 JotaroKujo:     {update3.winner_rating_before:.1f} -> {update3.winner_rating_after:.1f} (+{update3.winner_delta:.1f} ELO)")
    print(f"   💀 GiornoGiovanna: {update3.loser_rating_before:.1f} -> {update3.loser_rating_after:.1f} ({update3.loser_delta:.1f} ELO)\n")

    # Матч 4: Jotaro играет еще 3 игры против Пуччи для завершения калибровки
    print("⚔️ Симулируем еще игры Jotaro для выхода из калибровки...")
    for i in range(3):
        db.record_match(winner_id=101, loser_id=105, rep_id=999)

    jotaro = db.get_or_create_user(101)
    j_info = get_rank_info(jotaro["rating"], jotaro["rd"], jotaro["wins"] + jotaro["losses"], rank_position=1)
    print(f"   ✅ Jotaro завершил калибровку! Рейтинг: {jotaro['rating']:.1f}, RD: {jotaro['rd']:.1f}")
    print(f"   🎖️ Присвоен ранг: {j_info['badge']} {j_info['tier']} ({j_info.get('special_title')})\n")

    # Лидерборд
    print("📊 === ИТОГОВАЯ ТАБЛИЦА ЛИДЕРОВ СЕРВЕРА ===")
    leaders = db.get_leaderboard()
    for idx, l in enumerate(leaders, start=1):
        total = l["wins"] + l["losses"]
        r_info = get_rank_info(l["rating"], l["rd"], total, idx)
        cal_mark = "?" if not r_info["is_calibrated"] else ""
        print(f"#{idx:<2} | {r_info['badge']} {l['roblox_username']:<15} | {int(round(l['rating']))}{cal_mark} ELO | {l['wins']}W - {l['losses']}L | Ранг: {r_info['tier']}")

    db.close()
    if os.path.exists(db_file):
        os.remove(db_file)

if __name__ == "__main__":
    run_demo()

from typing import Optional, Dict, Any
import discord

def get_lang(interaction: Optional[discord.Interaction]) -> str:
    """Определяет язык пользователя на основе языка его клиента Discord"""
    if not interaction or not hasattr(interaction, "locale") or not interaction.locale:
        return "en"
    loc_str = str(interaction.locale).lower()
    return "ru" if loc_str.startswith("ru") else "en"


def get_user_lang(db: Any, user_id: int, interaction: Optional[discord.Interaction] = None, fallback: str = "ru") -> str:
    """
    Возвращает предпочитаемый язык конкретного пользователя.
    Приоритет:
    1. Настройка пользователя в БД (/language)
    2. Язык клиента Discord пользователя (если передан interaction и он относится к этому пользователю)
    3. Значение fallback (по умолчанию 'ru' для Лиги GANGHUB)
    """
    if db and hasattr(db, "get_user_language"):
        try:
            saved = db.get_user_language(user_id)
            if saved in ("ru", "en"):
                return saved
        except Exception:
            pass

    if interaction and hasattr(interaction, "user") and interaction.user and interaction.user.id == user_id:
        return get_lang(interaction)

    return fallback


def clean_server_name(server_str: Optional[str], lang: str = "ru") -> str:
    """Возвращает чисто локализованное название региона сервера без смешивания языков"""
    if not server_str:
        return "Hesse (Германия)" if lang == "ru" else "Hesse (Germany)"

    s = server_str.lower()
    if "hesse" in s or "герман" in s or "germany" in s:
        return "Hesse (Германия)" if lang == "ru" else "Hesse (Germany)"
    if "holland" in s or "нидерланд" in s or "netherland" in s:
        return "North Holland (Нидерланды)" if lang == "ru" else "North Holland (Netherlands)"
    if "london" in s or "великобритан" in s or "uk" in s or "britain" in s or "англия" in s:
        return "London (Великобритания)" if lang == "ru" else "London (United Kingdom)"
    if "us east" in s or "сша" in s or "united states" in s or "america" in s:
        return "US East (Восток США)" if lang == "ru" else "US East (United States)"
    if "договор" in s or "custom" in s or "mutual" in s or "соглас" in s:
        return "По договоренности" if lang == "ru" else "Mutual Agreement (Custom)"

    return server_str.strip()


def clean_format_name(mode_str: Optional[str], lang: str = "ru") -> str:
    """Возвращает чисто локализованное название формата боя без смешивания языков"""
    if not mode_str:
        return "T2 — Main vs Main (Мейн в мейн)" if lang == "ru" else "T2: Main vs Main"

    m = mode_str.lower()
    if "t1" in m:
        if "bo3" in m:
            return "T1 — Any vs Any [Bo3 Сет]" if lang == "ru" else "T1: Any vs Any (Bo3 Set)"
        return "T1 — Any vs Any (Любой в любой)" if lang == "ru" else "T1: Any vs Any"
    if "t2" in m:
        if "bo3" in m:
            return "T2 — Main vs Main [Bo3 Сет]" if lang == "ru" else "T2: Main vs Main (Bo3 Set)"
        return "T2 — Main vs Main (Мейн в мейн)" if lang == "ru" else "T2: Main vs Main"
    if "t3" in m or "mirror" in m or "зеркал" in m:
        return "T3 — Mirror (Зеркалка стендов)" if lang == "ru" else "T3: Mirror (Same Stand)"
    if "blind" in m or "вслепую" in m:
        return "Blind Pick (Вслепую в ЛС респу)" if lang == "ru" else "Blind Pick (Secret to Referee)"
    if "no ts" in m or "nots" in m or "таймстоп" in m or "тайм-стоп" in m:
        return "No TS (Без тайм-стопа)" if lang == "ru" else "No TS (No Time Stop)"
    if "specless" in m or "без спека" in m:
        return "Specless (Только стенды, без спека)" if lang == "ru" else "Specless (Stands Only)"
    if "standless" in m or "без стенда" in m:
        return "Standless (Только спеки, без стенда)" if lang == "ru" else "Standless (Specs Only)"
    if "договор" in m or "custom" in m or "mutual" in m:
        return "По договоренности" if lang == "ru" else "Mutual Agreement (Custom)"

    return mode_str.strip()


MESSAGES: Dict[str, Dict[str, str]] = {
    # --- Общие ошибки и проверки прав ---
    "error_admin_only": {
        "ru": "❌ Эта команда доступна только Администраторам сервера.",
        "en": "❌ This command is restricted to Server Administrators only."
    },
    "error_resp_only": {
        "ru": "❌ У тебя нет прав вносить результаты. Эта команда доступна только роли **{role}** или Администраторам.",
        "en": "❌ You don't have permission to report match results. Only **{role}** or Administrators can do this."
    },
    "error_guild_only": {
        "ru": "❌ Эта команда доступна только на сервере!",
        "en": "❌ This command can only be used within a server!"
    },
    "error_bot_user": {
        "ru": "❌ Боты не участвуют в рейтинговой Лиге!",
        "en": "❌ Bots cannot participate in the Ranked League!"
    },
    "error_same_user": {
        "ru": "❌ Победитель и проигравший не могут быть одним и тем же человеком!",
        "en": "❌ Winner and loser cannot be the same player!"
    },
    "error_self_referee": {
        "ru": "❌ Респ не может судить собственный матч! Для внесения результатов позовите другого респа или администратора.",
        "en": "❌ A referee cannot judge their own match! Please call another referee or an administrator."
    },

    # --- /ranks ---
    "ranks_title": {
        "ru": "♟️ GANGHUB ELO",
        "en": "♟️ GANGHUB ELO"
    },
    "ranks_calib_name": {
        "ru": "Unranked / Калибровка",
        "en": "Unranked / Calibration"
    },
    "ranks_calib_desc": {
        "ru": "Первые 5–10 матчей. За победу/поражение начисляется или снимается повышенное количество очков (~100–160).",
        "en": "First 5–10 matches. Wins and losses yield increased rating adjustments (~100–160 ELO)."
    },

    # --- /profile ---
    "profile_title": {
        "ru": "{badge} Профиль {name}",
        "en": "{badge} {name}'s Profile"
    },
    "profile_roblox_field": {
        "ru": "🎮 Roblox Ник",
        "en": "🎮 Roblox Username"
    },
    "profile_roblox_empty": {
        "ru": "*не привязан (/link)*",
        "en": "*not linked (/link)*"
    },
    "profile_rank_field": {
        "ru": "🎖️ Ранг",
        "en": "🎖️ Rank"
    },
    "profile_build_field": {
        "ru": "🧬 Билд YBA",
        "en": "🧬 YBA Build"
    },
    "profile_build_empty": {
        "ru": "*не указан (/build)*",
        "en": "*not set (/build)*"
    },
    "profile_title_field": {
        "ru": "👑 Титул",
        "en": "👑 Title"
    },
    "profile_elo_field": {
        "ru": "📊 Текущий ELO",
        "en": "📊 Current ELO"
    },
    "profile_calib_note": {
        "ru": " *(в процессе калибровки)*",
        "en": " *(calibrating)*"
    },
    "profile_peak_field": {
        "ru": "🏆 Пиковый ELO",
        "en": "🏆 Peak ELO"
    },
    "profile_winrate_field": {
        "ru": "📈 Общий винрейт",
        "en": "📈 Overall Winrate"
    },
    "profile_build_winrate_field": {
        "ru": "🎯 Винрейт на мейне",
        "en": "🎯 Main Build WR"
    },
    "profile_roblox_created_field": {
        "ru": "📅 Регистрация Roblox",
        "en": "📅 Roblox Created"
    },
    "profile_roblox_age_fmt": {
        "ru": "{date} ({years} г. / {days} дн.)",
        "en": "{date} ({years} y. / {days} d.)"
    },
    "profile_roblox_new_warn": {
        "ru": "{date} ⚠️ ({days} дн., <30 дней!)",
        "en": "{date} ⚠️ ({days} d., <30 days!)"
    },
    "profile_streak_field": {
        "ru": "🔥 Серия",
        "en": "🔥 Streak"
    },
    "profile_ladder_field": {
        "ru": "🌐 Место в ладдере",
        "en": "🌐 Ladder Rank"
    },
    "profile_vip_field": {
        "ru": "🕹️ VIP-сервер",
        "en": "🕹️ VIP Server"
    },
    "profile_vip_empty": {
        "ru": "*не привязан (/vip set)*",
        "en": "*not set (/vip set)*"
    },
    "profile_sec_acc": {
        "ru": "🎮 Roblox & Банда",
        "en": "🎮 Roblox & Gang"
    },
    "profile_acc_nick": {
        "ru": "Ник",
        "en": "User"
    },
    "profile_acc_gang": {
        "ru": "Банда",
        "en": "Gang"
    },
    "profile_acc_no_gang": {
        "ru": "*не состоит*",
        "en": "*none*"
    },
    "profile_acc_created": {
        "ru": "Создан",
        "en": "Created"
    },
    "profile_acc_alts": {
        "ru": "Твинки",
        "en": "Alts"
    },
    "profile_sec_yba": {
        "ru": "⚔️ Профиль YBA",
        "en": "⚔️ YBA Profile"
    },
    "profile_yba_rank": {
        "ru": "Ранг",
        "en": "Rank"
    },
    "profile_yba_build": {
        "ru": "Мейн билд",
        "en": "Main Build"
    },
    "profile_yba_vip": {
        "ru": "VIP-сервер",
        "en": "VIP Server"
    },
    "profile_sec_stats": {
        "ru": "📊 Рейтинг и Статистика",
        "en": "📊 Rating & Statistics"
    },
    "profile_stat_current_elo": {
        "ru": "Текущий ELO",
        "en": "Current ELO"
    },
    "profile_stat_peak": {
        "ru": "Пиковый",
        "en": "Peak"
    },
    "profile_stat_streak": {
        "ru": "Серия",
        "en": "Streak"
    },
    "profile_stat_ladder": {
        "ru": "Ладдер",
        "en": "Ladder"
    },
    "profile_stat_overall_wr": {
        "ru": "Общий WR",
        "en": "Overall WR"
    },
    "profile_stat_build_wr": {
        "ru": "Винрейт на мейне",
        "en": "Main Build WR"
    },
    "profile_gang_field": {
        "ru": "🏳️ Банда (Генг)",
        "en": "🏳️ Gang / Crew"
    },
    "profile_alts_field": {
        "ru": "👥 Доп. аккаунты (твинки)",
        "en": "👥 Alt Accounts"
    },
    "profile_bio_field": {
        "ru": "📜 О себе / История",
        "en": "📜 About / Lore"
    },
    "profile_edit_btn": {
        "ru": "Настроить профиль",
        "en": "Edit Profile"
    },
    "profile_edit_modal_title": {
        "ru": "Настройка профиля Лиги",
        "en": "League Profile Setup"
    },
    "profile_modal_gang_label": {
        "ru": "Ваша банда (Генг / Клан)",
        "en": "Your Gang / Crew / Clan"
    },
    "profile_modal_gang_placeholder": {
        "ru": "Например: GANGHUB, Passione, Eclipse...",
        "en": "e.g. GANGHUB, Passione, Eclipse..."
    },
    "profile_modal_bio_label": {
        "ru": "О себе / История игрока (Bio)",
        "en": "About You / Player Lore (Bio)"
    },
    "profile_modal_bio_placeholder": {
        "ru": "Расскажи свою историю, мейны, достижения в YBA...",
        "en": "Share your story, mains, achievements in YBA..."
    },
    "profile_modal_alts_label": {
        "ru": "Доп. аккаунты Roblox (твинки)",
        "en": "Roblox Alt Accounts"
    },
    "profile_modal_alts_placeholder": {
        "ru": "Например: alt_acc1, second_player...",
        "en": "e.g. alt_acc1, second_player..."
    },
    "profile_modal_success": {
        "ru": "✅ Данные профиля успешно сохранены!",
        "en": "✅ Profile details saved successfully!"
    },
    "profile_edit_not_owner": {
        "ru": "❌ Вы можете настраивать только свой собственный профиль!",
        "en": "❌ You can only edit your own profile!"
    },

    # --- /skin ---
    "skin_not_found_prompt": {
        "ru": "❌ Укажите никнейм в Roblox (`/skin username:Ник`) либо привяжите свой аккаунт через `/link`.",
        "en": "❌ Specify a Roblox username (`/skin username:Name`) or link your account via `/link`."
    },
    "skin_user_not_found": {
        "ru": "❌ Игрок `{name}` не найден в Roblox. Проверьте правильность написания ника.",
        "en": "❌ Roblox player `{name}` not found. Please check spelling."
    },
    "skin_embed_title": {
        "ru": "🧍 Скин Roblox • {display} (@{user})",
        "en": "🧍 Roblox Skin • {display} (@{user})"
    },
    "skin_profile_link": {
        "ru": "🔗 Открыть профиль в Roblox",
        "en": "🔗 Open Roblox Profile"
    },
    "skin_field_id": {
        "ru": "🆔 Roblox ID",
        "en": "🆔 Roblox ID"
    },
    "skin_field_created": {
        "ru": "📅 Регистрация",
        "en": "📅 Registered"
    },
    "skin_btn_profile": {
        "ru": "Профиль Roblox",
        "en": "Roblox Profile"
    },
    "skin_btn_hd": {
        "ru": "Открыть в HD",
        "en": "Open in HD"
    },
    "streak_wins": {
        "ru": "🔥 {count} побед(ы) подряд",
        "en": "🔥 {count} win streak"
    },
    "streak_losses": {
        "ru": "❄️ {count} поражений подряд",
        "en": "❄️ {count} loss streak"
    },

    # --- /link ---
    "link_invalid": {
        "ru": "❌ Недопустимый никнейм Roblox!\nНикнейм должен быть от 3 до 20 символов и содержать **только** английские буквы, цифры и символ подчеркивания `_`.",
        "en": "❌ Invalid Roblox username!\nMust be 3 to 20 characters and contain **only** alphanumeric characters and underscores `_`."
    },
    "link_success_title": {
        "ru": "✅ Никнейм привязан!",
        "en": "✅ Username Linked!"
    },
    "link_success_desc": {
        "ru": "Твой Roblox ник **{username}** успешно привязан к аккаунту {mention}.",
        "en": "Your Roblox username **{username}** was successfully linked to {mention}."
    },
    "link_auto_success": {
        "ru": "✅ Твой Roblox-аккаунт успешно синхронизирован через Bloxlink: **@{username}**!",
        "en": "✅ Your Roblox account was automatically linked via Bloxlink: **@{username}**!"
    },
    "link_not_in_bloxlink": {
        "ru": (
            "❌ **Твой Discord-аккаунт не найден или не синхронизирован в Bloxlink!**\n\n"
            "В Лиге GANGHUB все аккаунты строго привязываются через Bloxlink для защиты от подсадов и твинков.\n\n"
            "**Как пройти верификацию Bloxlink:**\n"
            "1. Зайди на [blox.link](https://blox.link) и убедись, что на твоём Roblox-аккаунте горит **золотая звёздочка ⭐ (Primary Account)**.\n"
            "2. В чате этого сервера напиши боту Bloxlink команду: `/verify`.\n"
            "3. После подтверждения вернись и напиши `/link` снова!\n"
            "*(Если у тебя несколько аккаунтов на Bloxlink, можно написать `/link roblox_username:<твой_ник>`)*"
        ),
        "en": (
            "❌ **Your Discord account was not found or synced in Bloxlink!**\n\n"
            "In GANGHUB League, all accounts must be strictly verified via Bloxlink.\n\n"
            "**How to verify via Bloxlink:**\n"
            "1. Visit [blox.link](https://blox.link) and make sure your desired Roblox account has the **Gold Star ⭐ (Primary Account)**.\n"
            "2. In this Discord server, run Bloxlink's `/verify` command.\n"
            "3. Once verified, run `/link` again!\n"
            "*(If you have multiple accounts on Bloxlink, you can also use `/link roblox_username:<username>`)*"
        )
    },
    "link_no_arg_no_key": {
        "ru": "ℹ️ Укажи свой никнейм вручную: `/link roblox_username:<твой_ник>`\n*(Либо администратор может подключить ключ Bloxlink через `/bloxlink set_key` для авто-привязки в 1 клик)*",
        "en": "ℹ️ Please specify your username manually: `/link roblox_username:<username>`\n*(Or an Admin can set Bloxlink API key via `/bloxlink set_key` for 1-click auto-linking)*"
    },

    # --- /bloxlink ---
    "bloxlink_key_saved": {
        "ru": "✅ API-ключ Bloxlink успешно сохранен и активирован для сервера!\nТеперь игроки могут привязывать ник автоматически через `/link`, а Респам доступна проверка `/check_passenger`.",
        "en": "✅ Bloxlink API key saved and activated successfully for this server!\nPlayers can now auto-link via `/link`, and Referees can use `/check_passenger`."
    },
    "bloxlink_key_invalid": {
        "ru": "❌ Ошибка проверки ключа Bloxlink: {error}",
        "en": "❌ Bloxlink key validation error: {error}"
    },
    "bloxlink_status_active": {
        "ru": "🟢 Интеграция с Bloxlink: **Активна**\nСерверный API-ключ подключен и работает.",
        "en": "🟢 Bloxlink Integration: **Active**\nServer API key is connected and working."
    },
    "bloxlink_status_inactive": {
        "ru": "🔴 Интеграция с Bloxlink: **Не настроена**\nАдминистратор может подключить её командой `/bloxlink set_key key:<ключ>`.",
        "en": "🔴 Bloxlink Integration: **Not Configured**\nAn Administrator can connect it using `/bloxlink set_key key:<key>`."
    },

    # --- /check_passenger ---
    "passenger_title": {
        "ru": "🕵️ Проверка на подсад (пассажира) • {name}",
        "en": "🕵️ Anti-Passenger Inspection • {name}"
    },
    "passenger_bloxlink_field": {
        "ru": "🎮 Аккаунт в Bloxlink",
        "en": "🎮 Bloxlink Account"
    },
    "passenger_match_field": {
        "ru": "⚔️ Ник в матче",
        "en": "⚔️ Match Account"
    },
    "passenger_status_field": {
        "ru": "🛡️ Вердикт проверки",
        "en": "🛡️ Inspection Verdict"
    },
    "passenger_match_ok": {
        "ru": "✅ **Чисто:** Ник в матче (`{match}`) полностью совпадает с верифицированным профилем в Bloxlink (`{bloxlink}`).",
        "en": "✅ **Clean:** Match account (`{match}`) matches verified Bloxlink profile (`{bloxlink}`)."
    },
    "passenger_match_fail": {
        "ru": "🚨 **ВНИМАНИЕ! НЕСОВПАДЕНИЕ АККАУНТОВ:**\nВ Bloxlink привязан: `{bloxlink}`\nВ матче заявлен: `{match}`\n*(Высокий риск подсада/бустера! Потребуйте показ демки согласно регламенту GANGHUB)*.",
        "en": "🚨 **WARNING! ACCOUNT MISMATCH:**\nBloxlink verified: `{bloxlink}`\nPlayed as: `{match}`\n*(High smurf/passenger risk! Demand a screen share inspection per GANGHUB rules)*."
    },
    "passenger_unverified": {
        "ru": "⚠️ Пользователь не верифицирован в Bloxlink на этом сервере. Проверьте аккаунт на демке вручную.",
        "en": "⚠️ User is not verified in Bloxlink on this server. Perform a manual screen share check."
    },
    "passenger_alts_warning": {
        "ru": "⚠️ **Внимание:** Этот Roblox-аккаунт также привязан у других участников сервера:\n{alts}",
        "en": "⚠️ **Notice:** This Roblox account is also linked to other server members:\n{alts}"
    },

    # --- /build ---
    "build_success_title": {
        "ru": "🧬 Билд YBA сохранен!",
        "en": "🧬 YBA Build Saved!"
    },
    "build_success_desc": {
        "ru": "Твой профиль обновлен:\n• Стенд: **{stand}**\n• Спек: **{spec}**",
        "en": "Your profile has been updated:\n• Stand: **{stand}**\n• Spec: **{spec}**"
    },

    # --- /bio ---
    "bio_set_success": {
        "ru": "✅ Ваше описание / история сохранена:\n{bio}",
        "en": "✅ Profile bio/lore saved:\n{bio}"
    },
    "bio_clear_success": {
        "ru": "🗑️ Описание профиля удалено.",
        "en": "🗑️ Profile bio removed."
    },

    # --- /gang ---
    "gang_set_success": {
        "ru": "✅ Ваша банда (генг) обновлена: **{gang}**",
        "en": "✅ Gang updated: **{gang}**"
    },
    "gang_clear_success": {
        "ru": "🗑️ Банда удалена из вашего профиля.",
        "en": "🗑️ Gang removed from your profile."
    },

    # --- /alts ---
    "alts_set_success": {
        "ru": "✅ Дополнительные аккаунты сохранены: `{alts}`",
        "en": "✅ Alt accounts saved: `{alts}`"
    },
    "alts_clear_success": {
        "ru": "🗑️ Список дополнительных аккаунтов очищен.",
        "en": "🗑️ Alt accounts list cleared."
    },

    # --- /leaderboard ---
    "lb_title": {
        "ru": "🏆 Таблица лидеров Лиги YBA",
        "en": "🏆 YBA League Leaderboard"
    },
    "lb_desc": {
        "ru": "Страница **{page}** • Топ игроков по рейтингу ELO\n",
        "en": "Page **{page}** • Top Players by ELO Rating\n"
    },
    "lb_empty": {
        "ru": "\n*Матчей еще не было. Будь первым!*",
        "en": "\n*No matches played yet. Be the first!*"
    },
    "lb_empty_page": {
        "ru": "На этой странице пока нет игроков.",
        "en": "There are no players on this page yet."
    },
    "lb_footer": {
        "ru": "Используй /profile для просмотра личной статистики",
        "en": "Use /profile to check your personal stats"
    },

    # --- /queue ---
    "queue_channel_warn": {
        "ru": "⚠️ Поиск соперников разрешен только в канале <#{channel}>!",
        "en": "⚠️ Matchmaking is only allowed in <#{channel}>!"
    },
    "queue_cooldown": {
        "ru": "⏳ Не спамь! Подожди 3 секунды перед повторным входом в очередь.",
        "en": "⏳ Slow down! Please wait 3 seconds before joining queue again."
    },
    "queue_already_in": {
        "ru": "⚠️ Ты уже находишься в очереди поиска!",
        "en": "⚠️ You are already in the matchmaking queue!"
    },
    "queue_not_in": {
        "ru": "❌ Ты не находишься в очереди.",
        "en": "❌ You are not in the queue."
    },
    "queue_left": {
        "ru": "✅ Ты вышел из очереди поиска.",
        "en": "✅ You left the matchmaking queue."
    },
    "queue_joined_title": {
        "ru": "⏳ Ты встал в очередь 1v1",
        "en": "⏳ You joined the 1v1 queue"
    },
    "queue_joined_desc": {
        "ru": "Твой рейтинг: **{rating} ELO**\nИгроков в поиске: **{count}**\n\nКогда найдется соперник, бот тегнет вас обоих в этом канале.",
        "en": "Your rating: **{rating} ELO**\nPlayers in queue: **{count}**\n\nWhen an opponent is found, the bot will mention both of you here."
    },
    "queue_match_found_title": {
        "ru": "⚔️ Соперник найден! Матч готов!",
        "en": "⚔️ Opponent Found! Match Ready!"
    },
    "queue_match_found_desc": {
        "ru": "**{p1_mention}** (`{p1_elo} ELO`)\n**VS**\n**{p2_mention}** (`{p2_elo} ELO`)\n\n🕹️ **Что делать дальше:**\n1. Добавьте друг друга в Roblox или зайдите на общий VIP/1v1 сервер YBA.\n2. Сыграйте дуэль 1 на 1.\n3. Позовите **Респа** или сделайте скриншот победы, чтобы судья внес результат через `/match report`!",
        "en": "**{p1_mention}** (`{p1_elo} ELO`)\n**VS**\n**{p2_mention}** (`{p2_elo} ELO`)\n\n🕹️ **Next Steps:**\n1. Add each other on Roblox or join a 1v1 VIP server in YBA.\n2. Fight the 1v1 duel.\n3. Call a **Referee** or take a victory screenshot so a referee can submit the score via `/match report`!"
    },
    "queue_match_found_footer": {
        "ru": "Удачи в битве стендов!",
        "en": "Good luck in the Stand battle!"
    },
    "queue_match_found_notify": {
        "ru": "⚔️ Соперник найден! Оповещение отправлено в канал.",
        "en": "⚔️ Opponent found! Notification sent to the channel."
    },
    "queue_status_empty_title": {
        "ru": "🔍 Очередь 1v1 пуста",
        "en": "🔍 1v1 Queue is empty"
    },
    "queue_status_empty_desc": {
        "ru": "Напиши `/queue join`, чтобы начать поиск соперника!",
        "en": "Type `/queue join` or click the button to start matchmaking!"
    },
    "queue_status_title": {
        "ru": "🔍 Текущая очередь 1v1",
        "en": "🔍 Current 1v1 Queue"
    },
    "queue_status_count": {
        "ru": "В поиске: **{count}** игрок(ов)\n",
        "en": "Searching: **{count}** player(s)\n"
    },
    "queue_status_waiting": {
        "ru": "ждет {sec} сек",
        "en": "waiting {sec}s"
    },

    # --- /match ---
    "match_reported_title": {
        "ru": "⚔️ Результат 1v1 дуэли подтвержден",
        "en": "⚔️ 1v1 Duel Result Confirmed"
    },
    "match_reported_desc": {
        "ru": "Судья (Респ): {rep}\nМатч ID: `#{match_id}`",
        "en": "Referee: {rep}\nMatch ID: `#{match_id}`"
    },
    "match_winner_field": {
        "ru": "🏆 Победитель: {name}",
        "en": "🏆 Winner: {name}"
    },
    "match_loser_field": {
        "ru": "💀 Проигравший: {name}",
        "en": "💀 Loser: {name}"
    },
    "match_rating_change": {
        "ru": "Рейтинг: **{before}** ➔ **{after}** (`{delta}`)\nРанг: {badge} **{tier}**",
        "en": "Rating: **{before}** ➔ **{after}** (`{delta}`)\nRank: {badge} **{tier}**"
    },
    "match_winner_streak": {
        "ru": "\nСерия: 🔥 {count} побед",
        "en": "\nStreak: 🔥 {count} wins"
    },
    "match_proof_field": {
        "ru": "📎 Доказательство (Пруф)",
        "en": "📎 Match Proof"
    },
    "match_proof_link": {
        "ru": "[Перейти к подтверждению]({url})",
        "en": "[View Proof]({url})"
    },
    "match_footer": {
        "ru": "Рейтинги и роли в Discord обновлены автоматически",
        "en": "Ratings and Discord roles updated automatically"
    },
    "match_undo_success_title": {
        "ru": "↩️ Матч аннулирован",
        "en": "↩️ Match Reverted"
    },
    "match_undo_success_desc": {
        "ru": "Матч `#{match_id}` успешно отменен. Рейтинги и роли игроков в Discord возвращены в исходное состояние.",
        "en": "Match `#{match_id}` has been cancelled. Player ratings and roles have been reverted."
    },
    "match_undo_fail": {
        "ru": "❌ Не удалось отменить матч `#{match_id}`. Возможные причины: матч не существует, относится к архивному сезону, либо у вас нет прав на его откат (откат доступен только судье этого матча или Администратору).",
        "en": "❌ Failed to revert match `#{match_id}`. Reasons: match does not exist, belongs to an archived season, or you are not authorized (only the match referee or an Administrator can revert)."
    },

    # --- /season ---
    "season_info_title": {
        "ru": "📅 {name}",
        "en": "📅 {name}"
    },
    "season_info_desc": {
        "ru": "Статус: **Активен**\nДата старта: `{started_at}`",
        "en": "Status: **Active**\nStart Date: `{started_at}`"
    },

    # --- /rules ---
    "rules_title": {
        "ru": "📜 Официальные правила 1v1 Лиги GANGHUB",
        "en": "📜 Official GANGHUB 1v1 League Rules"
    },
    "rules_overview_desc": {
        "ru": (
            "📌 **Официальный регламент 1v1 турниров GANGHUB**\n\n"
            "Здесь собраны все соревновательные правила Лиги:\n"
            "• **Форматы:** T1 Any vs Any, T2 Main vs Main, T3 SP/GER Mirror\n"
            "• **Запреты раунда:** Ран от 8 сек, пререйдж, абьюз текстур\n"
            "• **Запреты матча:** Подсад (пассажир), читы, спеклесс, брокен-связки (`SCR+Hamon`, `TWOH+Hamon`)\n"
            "• **Пики:** Называйте связки в ветку или одновременно скидывайте в ЛС Респу во избежание контрпика!\n\n"
            "👉 **Выберите интересующий раздел в выпадающем меню ниже**, чтобы прочитать подробные правила!"
        ),
        "en": (
            "📌 **Official GANGHUB 1v1 Tournament Regulations**\n\n"
            "Key competitive league rules summary:\n"
            "• **Formats:** T1 Any vs Any, T2 Main vs Main, T3 SP/GER Mirror\n"
            "• **Round Auto-loss:** 8+ sec running, pre-rage, map abuse\n"
            "• **Match Auto-loss:** Passenger smurf, cheats, specless, broken builds (`SCR+Hamon`, `TWOH+Hamon`)\n"
            "• **Picks:** Declare builds in match thread or DM Referee simultaneously to prevent counterpicks!\n\n"
            "👉 **Select a category from the dropdown menu below** to read detailed rules!"
        )
    },
    "rules_cat_bans_title": {
        "ru": "🚫 Запреты и Автолузы",
        "en": "🚫 Prohibitions & Auto-Losses"
    },
    "rules_cat_bans_desc": {
        "ru": (
            "🚫 **ЗАПРЕЩЕНО: АВТОЛУЗ РАУНДА**\n"
            "• **Ран от 8 секунд и больше:** намеренное убегание от боя. Метание ножей, выстрелы из револьверов **НЕ** сбрасывают 8 секунд!\n"
            "• **Абьюз территории:** уход за текстуры карты, кайт по непредназначенным возвышенностям.\n"
            "• **Пререйдж:** прожатие рейджа до начала раунда.\n"
            "• **Атака без готовности:** нападение до подтверждения готовности оппонента (с отказом переиграть).\n"
            "• **Нарушение условий:** несоблюдение договоренностей перед матчем.\n"
            "• **Намеренный абуз багов:** глитчи текстур, застревания (автолуз раунда или матча в зависимости от тяжести).\n"
            "*(Избежать автолуза раунда можно, если нарушивший игрок согласен переиграть. Абуз переигровок = автолуз матча).*\n\n"
            "🛑 **ЗАПРЕЩЕНО: АВТОЛУЗ МАТЧА (PvP)**\n"
            "• **Пассажир на аккаунте:** игра другого человека на аккаунте во время PvP.\n"
            "• **Лишние спектаторы:** более 1 спектатора от одной стороны (если он выходит сразу — автолуза можно избежать).\n"
            "• **Кик Респа:** исключение судьи (Отвечающего) с VIP-сервера (в зависимости от ситуации Duck или автолуз).\n"
            "• **Додж PvP:** намеренное затягивание матча, уход на Gang Wars (GW) и т.д.\n"
            "• **Читы и стороннее ПО:** перманентный бан в Лиге.\n"
            "• **Спеклесс (Specless):** игра без спека без обоюдного согласия обеих сторон.\n"
            "• **Брокен связки:** `SCR + Hamon` и `TWOH + Hamon` строго запрещены.\n"
            "• **Самовольный свап:** смена стенда/спека после выбора связок без согласия соперника.\n"
            "• **Перезаход:** реконнект без причины и без четких видеодоказательств краша игры."
        ),
        "en": (
            "🚫 **PROHIBITED: ROUND AUTO-LOSS**\n"
            "• **Running 8+ seconds:** Stalling/fleeing combat. Throwing knives/revolvers **DO NOT** reset the 8s timer!\n"
            "• **Map abuse:** Fleeing into textures, climbing unintended high structures.\n"
            "• **Pre-rage:** Activating rage before round start.\n"
            "• **Attacking when unready:** Attacking an unprepared opponent without agreeing to replay.\n"
            "• **Breaching terms:** Violating pre-agreed duel terms.\n"
            "• **Intentional bug abuse:** Geometry bugs, out-of-bounds stalling (round or match auto-loss depending on severity).\n"
            "*(Round auto-loss can be waived if offender agrees to replay. Abusing replays results in match DQ).*\n\n"
            "🛑 **PROHIBITED: MATCH AUTO-LOSS (DQ)**\n"
            "• **Account passenger:** Having another person play on your account during PvP.\n"
            "• **Extra spectators:** More than 1 spectator from one side (waived if extra leaves immediately).\n"
            "• **Kicking Referee:** Kicking the responsible referee from the VIP server (Duck or match DQ).\n"
            "• **Dodging PvP:** Stalling match start, joining Gang Wars instead, etc.\n"
            "• **Cheats & Third-party software:** Instant permanent league ban.\n"
            "• **Specless:** Fighting without a fighting style unless mutually agreed beforehand.\n"
            "• **Banned broken builds:** `SCR + Hamon` and `TWOH + Hamon` are strictly prohibited.\n"
            "• **Unauthorized swap:** Switching stand or spec mid-duel without opponent's consent.\n"
            "• **Rejoining:** Reconnecting without valid video proof of game crash."
        )
    },
    "rules_cat_formats_title": {
        "ru": "⚔️ Форматы и Баны ультимейтов",
        "en": "⚔️ Formats & Ultimate Bans"
    },
    "rules_cat_formats_desc": {
        "ru": (
            "⚔️ **ПРИОРИТЕТ РЕКВЕСТОВ 1vs1:**\n"
            "• **T1 — «Ани в Ани (Any vs Any)»:** стенд разрешено менять только 1 раз (пример: SP, GER vs KC, KCR).\n"
            "• **T2 — «Мейн в Мейн (Main vs Main)»:** если реквест с двух сторон одобрен на игру «мейн в мейн», вы можете назвать лишь одну связку (`/build` в профиле). Свап связки или игра не на своем мейне строго запрещены и караются **Duck**!\n"
            "• **T3 — «Сп миррор / Гер миррор (SP mirror / GER mirror)»**.\n\n"
            "⏰ **ЛИМИТ ВРЕМЕНИ ДЛЯ ИГРЫ:**\n"
            "• Перед игрой нужно расставить рамки лимита времени (пример: *«я могу играть только до 18:00»*).\n\n"
            "🎭 **ОГЛАШЕНИЕ СВЯЗОК И АНТИ-КОНТРПИК:**\n"
            "• При заходе на сервер или в ветке игроки обязаны назвать свой стенд, на котором будут играть.\n"
            "• **Защита от контрпика:** обе стороны могут скинуть свои связки в ЛС Респу (Отвечающему), после чего Респ одновременно оглашает обе связки в ветку матча!\n\n"
            "🛑 **БАНЫ УЛЬТИМАТИВНЫХ СПОСОБНОСТЕЙ:**\n"
            "Игрок вправе забанить ультимейты оппонента:\n"
            "• ⚡ **Awakening (Авейк)**\n"
            "• 🔥 **Rage (Рейдж)** *(кроме рейджа Crazy Diamond)*\n"
            "• 🥊 **Beatdown (Битдаун / BD)**\n"
            "• 🛡️ **Love Train (Лав трейн / LT)**\n"
            "• 💤 **Сон СЧР (SCR Sleep / Conqueror's Will)**\n"
            "• ⏳ **Bites the Dust (Байт зе даст / BTD)**\n"
            "• ⏱️ **Time Stop (Тайм стоп / TS)**\n"
            "• 🌌 **Universe Reset (Юнивёрс ресет / Made in Heaven)**\n"
            "*(Скилл банится именно как активная способность в бою, а не как прокачка в дереве).* "
        ),
        "en": (
            "⚔️ **1v1 REQUEST PRIORITY:**\n"
            "• **T1 — \"Any vs Any\":** Stand can only be swapped once (e.g. SP, GER vs KC, KCR).\n"
            "• **T2 — \"Main vs Main\":** If match is accepted as Main vs Main, players fight strictly on their declared build (`/build` in profile). Swapping builds is strictly prohibited and results in a **Duck**!\n"
            "• **T3 — \"SP mirror / GER mirror\"**.\n\n"
            "⏰ **TIME LIMITS:**\n"
            "• Time limits must be agreed before match start (e.g. *\"I can only play until 18:00\"*).\n\n"
            "🎭 **BUILD DECLARATION & ANTI-COUNTERPICK:**\n"
            "• Upon joining server or in the thread, players must declare their stand.\n"
            "• **Anti-counterpick protection:** Both players may send their builds to the Referee in DMs; the Referee will then reveal both simultaneously in the thread!\n\n"
            "🛑 **ULTIMATE ABILITY BANS:**\n"
            "A player is entitled to ban their opponent's ultimate abilities:\n"
            "• ⚡ **Awakening**\n"
            "• 🔥 **Rage** *(except Crazy Diamond rage)*\n"
            "• 🥊 **Beatdown (BD)**\n"
            "• 🛡️ **Love Train (LT)**\n"
            "• 💤 **SCR Sleep (Conqueror's Will / CW)**\n"
            "• ⏳ **Bites the Dust (BTD)**\n"
            "• ⏱️ **Time Stop (TS)**\n"
            "• 🌌 **Universe Reset (Made in Heaven)**\n"
            "*(Banned as an active combat skill, not as skill tree node).*"
        )
    },
    "rules_cat_stands_title": {
        "ru": "⚖️ Ограничения конкретных стендов",
        "en": "⚖️ Stand-Specific Limitations"
    },
    "rules_cat_stands_desc": {
        "ru": (
            "⚖️ **СТЕНДЫ С ОГРАНИЧЕНИЯМИ:**\n\n"
            "💎 **KDR (Crazy Diamond Requiem):**\n"
            "• Можно использовать строго **БЕЗ хилла**.\n\n"
            "🧬 **GER (Gold Experience Requiem):**\n"
            "• МАКСИМАЛЬНОЕ КОЛИЧЕСТВО ХИЛЛОВ ЗА РАУНД — **2** (два).\n\n"
            "👑 **KCR (King Crimson Requiem):**\n"
            "• **В KCR Mirror:** приоритет игры **БЕЗ скилла Raging Demon**.\n"
            "• **Против стендов БЕЗ ультимейтов:** на KCR **НЕЛЬЗЯ** прокачивать *Raging Demon*, а *Коробка (Box)* может быть прокачана только до **1 уровня** (во избежание рана и отхила в зоне).\n"
            "• **Против Weather Report:** коробка может быть прокачана до 3 уровня (9 секунд).\n"
            "• **Против стендов С ультимейтами:** KCR юзер не имеет права блокировать ультимативную способность и количество её использований (кап коробки остаётся 3)."
        ),
        "en": (
            "⚖️ **STANDS WITH LIMITATIONS:**\n\n"
            "💎 **KDR (Crazy Diamond Requiem):**\n"
            "• Permitted strictly **WITHOUT healing**.\n\n"
            "🧬 **GER (Gold Experience Requiem):**\n"
            "• MAXIMUM HEALS PER ROUND — **2** (two).\n\n"
            "👑 **KCR (King Crimson Requiem):**\n"
            "• **In KCR Mirror:** Priority is strictly **WITHOUT Raging Demon**.\n"
            "• **Against stands WITHOUT ultimate abilities:** KCR **MUST NOT** upgrade *Raging Demon*, and *Box* can only be upgraded to **Level 1** (to prevent stalling and zone healing).\n"
            "• **Against Weather Report:** Box may be upgraded up to Level 3 (9 seconds).\n"
            "• **Against stands WITH ultimate abilities:** KCR user has no right to block ultimate abilities or limit their uses (box cap remains Level 3)."
        )
    },
    "rules_cat_checks_title": {
        "ru": "🕵️ Проверка на подсад (пассажира) и Пруфы",
        "en": "🕵️ Passenger Checks & Proofs"
    },
    "rules_cat_checks_desc": {
        "ru": (
            "🕵️ **ПРОВЕРКА НА ПОДСАД (ПАССАЖИРА):**\n"
            "• Каждый игрок вправе потребовать от Респонсибла проверить соперника на демонстрации экрана (демке).\n"
            "• **Что проверяет Респ:**\n"
            "  1. Свап аккаунтов в Roblox и Discord.\n"
            "  2. Авторизованные устройства в Roblox и Discord.\n"
            "  3. Факт нахождения человека на приватном сервере.\n"
            "  *(Респонсибл имеет право устроить дополнительные проверки).* \n"
            "• **Отказ от показа демки Респу — МГНОВЕННЫЙ АВТОЛУЗ!**\n\n"
            "🌐 **ПРИОРИТЕТ СЕРВЕРОВ ДЛЯ 1v1:**\n"
            "• Сервера: **Hesse**, **North Holland** либо в зависимости от региона, чтобы обеим сторонам было комфортно по пингу.\n\n"
            "📹 **ФИКСАЦИЯ ПОБЕДЫ И ПРУФЫ (ДОКАЗАТЕЛЬСТВА):**\n"
            "• Победа присваивается, когда оппонент согласен с поражением, либо же с помощью клипов с приоритетностью по следующему порядку (возрастание):\n"
            "  1. 🖼️ Скрины\n"
            "  2. 🎬 Клипы\n"
            "  3. 📹 Клипы целого PvP\n"
            "  4. 🏆 Клипы всех PvP\n"
            "• Если вы играете без спектатора в виде Респонсибла, рекомендуется клипать полностью вашу игру на лог (можно через друзей).\n"
            "• **Разрешенные платформы:** Medal.tv, YouTube, Streamable, Twitch, либо видео напрямую в ветку.\n"
            "• ⚠️ **НАКАЗАНИЕ ЗА ПЕРЕЛИВ И ПОДСАД:** любая попытка слить матч, поддаться или накрутить рейтинг карается перманентным баном в Лиге и полным обнулением рейтинга (Wipe ELO) обоим участникам!"
        ),
        "en": (
            "🕵️ **PASSENGER (SMURF/BOOSTER) CHECKS:**\n"
            "• Any player has the right to demand a screen share check of their opponent by a Referee.\n"
            "• **What the Referee inspects:**\n"
            "  1. Account swaps in Roblox and Discord.\n"
            "  2. Authorized devices in Roblox and Discord.\n"
            "  3. Presence of the user on the private server.\n"
            "  *(Referees have full authority to conduct additional checks).* \n"
            "• **Refusal to share screen with Referee = INSTANT DQ!**\n\n"
            "🌐 **1v1 SERVER REGIONS:**\n"
            "• Preferred servers: **Hesse**, **North Holland**, or mutual regional consensus for optimal ping.\n\n"
            "📹 **VICTORY CONFIRMATION & PROOFS:**\n"
            "• Victory is awarded when opponent concedes defeat or through video evidence with ascending priority:\n"
            "  1. 🖼️ Screenshots\n"
            "  2. 🎬 Clips\n"
            "  3. 📹 Full match clip\n"
            "  4. 🏆 Complete recordings of all PvP matches\n"
            "• If playing without an official Referee spectator, it is strongly recommended to clip your entire match for log (can be recorded via friends).\n"
            "• **Accepted platforms:** Medal.tv, YouTube, Streamable, Twitch, or direct videos in thread.\n"
            "• ⚠️ **PENALTY FOR WIN-TRADING & SMURFING:** Instant permanent league ban and full ELO wipe for both parties!"
        )
    },
    "rules_cat_duck_title": {
        "ru": "🦆 Регламент вызовов, Тайминги и Дак (Duck)",
        "en": "🦆 Match Timings, Cooldowns & Duck"
    },
    "rules_cat_duck_desc": {
        "ru": (
            "🦆 **РЕГЛАМЕНТ ВЫЗОВОВ, ТАЙМИНГИ И ДАК (DUCK):**\n"
            "• ⏱️ **Время на ответ:** на принятие вызова дается **24 часа**.\n"
            "• ⏳ **Кулдаун на лог:** кд на лог за роль — **3 дня**.\n"
            "• ⚠️ **Оговорка на лог:** если человек предлагает PvP, но не указывает, что оно на лог — такое PvP не логается.\n"
            "• 🛡️ **Защита от твинков:** если вызов кидает аккаунт с регистрацией < 30 дней в Gang Hub — разрешено дакать без последствий и роли Duck.\n"
            "• 📅 **Переносы:** матч можно перенести максимум 3 раза; без уважительной причины перенос максимум на 1 день.\n"
            "• ⏰ **Лимиты времени:** перед игрой необходимо зафиксировать рамки времени (пример: *«я могу играть только до 18:00»*).\n"
            "• 🚫 Неадекватное поведение в реквесте не обновляет 24 часа и карается ролью Duck.\n\n"
            "👑 **РОЛИ ТОП-1 СТЕНДОВ И DUCK EVADE:**\n"
            "• Роли топ-1 стендов нельзя передавать просто так — каждое PvP на роль должно быть заклипано!\n"
            "• За подкупное/договорное 1v1 за роль — роль забирается у обеих сторон на неделю.\n"
            "• **Роль Duck Evade:**\n"
            "  - Респы/Админы могут доджить PvP без получения Duck только при наличии Duck Evade (на секретки не действует).\n"
            "  - Игроки с Duck Evade либо отказываются от роли, либо не могут кидать 1в1 на роли, но сами обязаны ходить на вызовы."
        ),
        "en": (
            "🦆 **MATCH TIMINGS, COOLDOWNS & DUCK RULES:**\n"
            "• ⏱️ **Reply deadline:** Players have **24 hours** to accept a challenge.\n"
            "• ⏳ **Log cooldown:** Cooldown for ranking/role log is **3 days**.\n"
            "• ⚠️ **Explicit log terms:** If a match was not explicitly specified as \"for log\" prior to play, it cannot be logged.\n"
            "• 🛡️ **New account protection:** Challenges from accounts registered < 30 days in Gang Hub may be declined without receiving a Duck role.\n"
            "• 📅 **Postponements:** Match can be postponed at most 3 times, and without valid reason for at most 1 day.\n"
            "• ⏰ **Time limits:** Duel duration must be stated beforehand (e.g. *\"I can only play until 18:00\"*).\n\n"
            "👑 **TOP-1 STAND ROLES & DUCK EVADE:**\n"
            "• Top-1 stand roles cannot be transferred by agreement; every role match MUST be clipped.\n"
            "• Rigged / win-traded matches result in a 1-week role ban for both players.\n"
            "• **Duck Evade role:**\n"
            "  - Referees/Admins can dodge PvP without receiving Duck only with a Duck Evade role (does not apply to secret stands).\n"
            "  - Duck Evade holders cannot challenge others for roles, but are strictly required to accept role challenges."
        )
    },
    "rules_menu_placeholder": {
        "ru": "Выберите раздел правил...",
        "en": "Select a rules section..."
    },
    "rules_menu_overview": {
        "ru": "📌 Общий обзор регламента",
        "en": "📌 General Overview"
    },

    # --- /vip ---
    "vip_title": {
        "ru": "🕹️ Приватный сервер (VIP)",
        "en": "🕹️ Private VIP Server"
    },
    "vip_user_desc": {
        "ru": "Личный VIP-сервер игрока {user}:\n\n{link}",
        "en": "{user}'s Personal VIP Server:\n\n{link}"
    },
    "vip_league_desc": {
        "ru": "Официальный VIP-сервер Лиги:\n\n{link}",
        "en": "Official League VIP Server:\n\n{link}"
    },
    "vip_user_not_set": {
        "ru": "⚠️ У {user} еще не привязана личная ссылка на VIP-сервер.\nУстановить свою можно через: `/vip set url:<ссылка>`",
        "en": "⚠️ {user} has not set a personal VIP server link yet.\nYou can set yours using: `/vip set url:<link>`"
    },
    "vip_btn_label": {
        "ru": "Войти на VIP-сервер 🚀",
        "en": "Join VIP Server 🚀"
    },
    "vip_user_set_success": {
        "ru": "✅ Ваша личная ссылка на VIP-сервер успешно сохранена:\n<{url}>\nОна будет отображаться в вашем `/profile` и автоматически предлагаться соперникам при вызове `/challenge`!",
        "en": "✅ Your personal VIP server link has been saved:\n<{url}>\nIt will now show on your `/profile` and be offered to opponents in `/challenge`!"
    },
    "vip_clear_success": {
        "ru": "🗑️ Ваша личная ссылка на VIP-сервер удалена.",
        "en": "🗑️ Your personal VIP server link has been cleared."
    },
    "vip_league_set_success": {
        "ru": "✅ Общесерверная ссылка Лиги на VIP-сервер успешно обновлена:\n<{url}>",
        "en": "✅ Official League VIP server link updated successfully:\n<{url}>"
    },
    "vip_invalid_url": {
        "ru": "❌ Некорректная ссылка на VIP-сервер! Ссылка должна начинаться с https://",
        "en": "❌ Invalid VIP server link! Must start with https://"
    },

    # --- /challenge ---
    "challenge_self_error": {
        "ru": "❌ Ты не можешь бросить вызов самому себе!",
        "en": "❌ You cannot challenge yourself!"
    },
    "challenge_already_pending": {
        "ru": "❌ Вы уже отправили активный вызов этому игроку! Дождитесь ответа или истечения 24 часов.",
        "en": "❌ You already have an active pending challenge against this player! Wait for their response or 24h expiration."
    },
    "challenge_reverse_pending": {
        "ru": "ℹ️ Этот игрок уже бросил вам вызов! Проверьте ЛС или канал и нажмите «Принять вызов».",
        "en": "ℹ️ This player already challenged you! Check your DMs or the channel to accept."
    },
    "challenge_title": {
        "ru": "⚔️ Вызов на 1v1 дуэль (GANGHUB)",
        "en": "⚔️ 1v1 Duel Challenge (GANGHUB)"
    },
    "challenge_desc": {
        "ru": (
            "**{challenger}** бросает официальный вызов **{challenged}**!\n\n"
            "• **Формат:** **{format}**\n"
            "• **Сервер:** **{server}**\n"
            "• **Дедлайн:** <t:{expire_ts}:R> (24 часа)\n\n"
            "⚠️ **Регламент GANGHUB:** У противника есть **24 часа** на ответ.\n"
            "Если вызов проигнорирован — игроку автоматически выдается роль **Duck (Авто-Дак)**!"
        ),
        "en": (
            "**{challenger}** has challenged **{challenged}** to an official 1v1 duel!\n\n"
            "• **Format:** **{format}**\n"
            "• **Server:** **{server}**\n"
            "• **Deadline:** <t:{expire_ts}:R> (24 hours)\n\n"
            "⚠️ **GANGHUB Rules:** Opponent has **24 hours** to respond.\n"
            "If ignored, player will automatically receive the **Duck** role (Auto-Duck)!"
        )
    },
    "challenge_dm_title": {
        "ru": "⚔️ Тебе бросили вызов на 1v1 дуэль в Лиге GANGHUB!",
        "en": "⚔️ You have received a 1v1 duel challenge in GANGHUB League!"
    },
    "challenge_dm_desc": {
        "ru": (
            "Привет, **{user}**!\n\n"
            "Игрок **{challenger}** бросил тебе официальный вызов на 1v1 дуэль на сервере **{guild}**!\n\n"
            "• **Формат боя:** {format}\n"
            "• **Регион сервера:** {server}\n"
            "• **Время на ответ:** 24 часа (до <t:{expire_ts}:f>, <t:{expire_ts}:R>)\n\n"
            "🦆 **ВНИМАНИЕ (Авто-Дак):**\n"
            "Если ты не ответишь на вызов в течение 24 часов, тебе автоматически будет выдана роль `Duck` (Авто-Дак) по регламенту GANGHUB!\n\n"
            "👉 Нажми кнопку ниже, чтобы перейти к сообщению и дать ответ."
        ),
        "en": (
            "Hello, **{user}**!\n\n"
            "Player **{challenger}** challenged you to an official 1v1 duel on **{guild}**!\n\n"
            "• **Format:** {format}\n"
            "• **Server:** {server}\n"
            "• **Deadline:** 24 hours (until <t:{expire_ts}:f>, <t:{expire_ts}:R>)\n\n"
            "🦆 **IMPORTANT (Auto-Duck):**\n"
            "If you do not respond within 24 hours, you will automatically receive the `Duck` role (Auto-Duck) under GANGHUB regulations!\n\n"
            "👉 Click the button below to jump to the challenge and respond."
        )
    },
    "challenge_dm_jump_btn": {
        "ru": "Перейти к вызову",
        "en": "Jump to Challenge"
    },
    "challenge_auto_duck_title": {
        "ru": "🦆 Вызов просрочен — Авто-Дак (Duck)",
        "en": "🦆 Challenge Expired — Auto-Duck (Duck)"
    },
    "challenge_auto_duck_desc": {
        "ru": (
            "⏰ **Время на ответ истекло (24 часа)!**\n\n"
            "{challenged} не ответил на официальный вызов от {challenger}.\n"
            "По регламенту GANGHUB игроку {challenged} автоматически присваивается роль **Duck (Авто-Дак)**!"
        ),
        "en": (
            "⏰ **Response time expired (24 hours)!**\n\n"
            "{challenged} did not respond to {challenger}'s official challenge.\n"
            "Under GANGHUB regulations, {challenged} has been automatically awarded the **Duck** role (Auto-Duck)!"
        )
    },
    "challenge_auto_duck_exempt_title": {
        "ru": "⏳ Вызов аннулирован (Иммунитет к Duck)",
        "en": "⏳ Challenge Cancelled (Duck Immunity)"
    },
    "challenge_auto_duck_exempt_desc": {
        "ru": (
            "⏰ Время на ответ вызова от {challenger} к {challenged} истекло (24 часа).\n\n"
            "🛡️ **Освобождение от роли Duck:** {reason}."
        ),
        "en": (
            "⏰ Response time for challenge from {challenger} to {challenged} expired (24 hours).\n\n"
            "🛡️ **Exempt from Duck penalty:** {reason}."
        )
    },
    "challenge_exempt_evade": {
        "ru": "Игрок обладает ролью Duck Evade",
        "en": "Player holds Duck Evade role"
    },
    "challenge_exempt_new_acc": {
        "ru": "Roblox-аккаунт инициатора вызова зарегистрирован менее 30 дней назад ({days} дн.)",
        "en": "Challenger's Roblox account is less than 30 days old ({days} d.)"
    },
    "challenge_dm_duck_recipient": {
        "ru": (
            "🦆 **Время на ответ истекло (24ч)!**\n"
            "Ты не ответил на официальный вызов на 1v1 от {challenger} на сервере **{guild}**.\n"
            "Тебе была автоматически выдана роль **Duck** (Авто-Дак) по регламенту GANGHUB."
        ),
        "en": (
            "🦆 **Challenge response time expired (24h)!**\n"
            "You failed to respond to the 1v1 challenge from {challenger} on **{guild}**.\n"
            "You were automatically assigned the **Duck** role (Auto-Duck) under GANGHUB regulations."
        )
    },
    "challenge_dm_duck_challenger": {
        "ru": (
            "🔔 **Твой вызов для {challenged} завершен по таймауту (24ч)!**\n"
            "Игрок не ответил в установленный срок и получил роль **Duck** (Авто-Дак) на сервере **{guild}**."
        ),
        "en": (
            "🔔 **Your challenge to {challenged} has expired (24h)!**\n"
            "The opponent did not respond in time and has been awarded the **Duck** role on **{guild}**."
        )
    },
    "challenge_dm_accepted_challenger": {
        "ru": "⚔️ **{challenged} принял твой вызов на 1v1 дуэль!**\nСоздана официальная ветка матча: {thread_url}",
        "en": "⚔️ **{challenged} accepted your 1v1 duel challenge!**\nMatch thread created: {thread_url}"
    },
    "challenge_dm_declined_challenger": {
        "ru": "❌ **{challenged} отклонил твой вызов на 1v1 дуэль.**",
        "en": "❌ **{challenged} declined your 1v1 duel challenge.**"
    },
    "challenge_declined_duck_title": {
        "ru": "🦆 Вызов отклонен — Зафиксирован Дак (Duck)",
        "en": "🦆 Challenge Declined — Duck Recorded"
    },
    "challenge_declined_duck_desc": {
        "ru": (
            "❌ {challenged} отклонил вызов на дуэль от {challenger}.\n\n"
            "🦆 По регламенту GANGHUB отказ от вызова фиксируется как **Дак**!\n"
            "Игроку {challenged} автоматически выдана роль **Duck** и отправлен лог в канал даков."
        ),
        "en": (
            "❌ {challenged} declined the duel challenge from {challenger}.\n\n"
            "🦆 Under GANGHUB rules, declining a challenge is recorded as a **Duck**!\n"
            "{challenged} was automatically assigned the **Duck** role and logged in the duck channel."
        )
    },
    "challenge_declined_exempt_title": {
        "ru": "❌ Вызов отклонен (Иммунитет к Duck)",
        "en": "❌ Challenge Declined (Duck Immunity)"
    },
    "challenge_declined_exempt_desc": {
        "ru": (
            "❌ {challenged} отклонил вызов от {challenger}.\n\n"
            "🛡️ **Освобождение от роли Duck:** {reason}."
        ),
        "en": (
            "❌ {challenged} declined the challenge from {challenger}.\n\n"
            "🛡️ **Exempt from Duck penalty:** {reason}."
        )
    },
    "challenge_dm_declined_duck_recipient": {
        "ru": (
            "🦆 **Ты отклонил вызов на дуэль от {challenger}!**\n"
            "По регламенту GANGHUB тебе автоматически присвоена роль **Duck** на сервере **{guild}**.\n"
            "Лог зафиксирован в канале даков."
        ),
        "en": (
            "🦆 **You declined a duel challenge from {challenger}!**\n"
            "Under GANGHUB rules, you have been assigned the **Duck** role on **{guild}**.\n"
            "This was recorded in the duck log channel."
        )
    },
    "challenge_dm_declined_duck_challenger": {
        "ru": (
            "🔔 **Игрок {challenged} отклонил твой вызов на дуэль!**\n"
            "Ему была автоматически выдана роль **Duck** (Дак зафиксирован в канале даков)."
        ),
        "en": (
            "🔔 **Player {challenged} declined your duel challenge!**\n"
            "They were automatically assigned the **Duck** role (recorded in the duck channel)."
        )
    },
    "duck_channel_set_success": {
        "ru": "✅ Канал для фиксации даков успешно установлен: {channel}",
        "en": "✅ Duck log channel successfully set to: {channel}"
    },
    "duck_channel_info": {
        "ru": "🦆 Текущий канал для логов даков: {channel}",
        "en": "🦆 Current duck log channel: {channel}"
    },
    "match_results_channel_set_success": {
        "ru": "✅ Канал для результатов дуэлей успешно установлен: {channel}",
        "en": "✅ Match results channel successfully set to: {channel}"
    },
    "match_results_channel_info": {
        "ru": "⚔️ Текущий канал для результатов дуэлей: {channel}",
        "en": "⚔️ Current match results channel: {channel}"
    },
    "fights_channel_set_success": {
        "ru": "✅ Форум/канал для создания дуэлей Лиги успешно установлен: {channel}",
        "en": "✅ League duel forum/channel successfully set to: {channel}"
    },
    "fights_channel_info": {
        "ru": "⚔️ Текущий форум/канал для создания дуэлей Лиги: {channel}",
        "en": "⚔️ Current League duel forum/channel: {channel}"
    },
    "challenge_format_field": {
        "ru": "⚔️ Формат дуэли",
        "en": "⚔️ Match Format"
    },
    # --- /formats ---
    "formats_guide_title": {
        "ru": "⚔️ Полный справочник соревновательных форматов 1v1 GANGHUB",
        "en": "⚔️ Complete GANGHUB 1v1 Competitive Formats Guide"
    },
    "formats_guide_desc": {
        "ru": (
            "👑 **ИЕРАРХИЯ ПРИОРИТЕТОВ РЕКВЕСТОВ:**\n"
            "• **T1 — Any vs Any (Любой в Любой):**\n"
            "  - **Высший приоритет.** Полная свобода выбора стенда и стиля боя (спека).\n"
            "  - Если брошен T1, соперник обязан играть T1 (отказ считается уклонением).\n"
            "  - Разрешен максимум **1 свап стенда** за сет (напр., SP, GER vs KC, KCR).\n"
            "• **T2 — Main vs Main (Мейн в Мейн):**\n"
            "  - **2-й приоритет.** Игроки выходят **строго на связках, указанных в боте** (`/build` профиля).\n"
            "  - Свап связки или игра на чужом стенде строго **запрещены** (карается DQ / Duck). Контрпик исключен.\n"
            "• **T3 — Mirror (Зеркалка на любом стенде):**\n"
            "  - **3-й приоритет.** Оба игрока играют на одном и том же стенде (выбирается в ветке боя).\n"
            "  - Победа зависит от чистого скилла, таймингов парирования (F) и контроля спека.\n\n"
            "🎯 **СПЕЦИАЛЬНЫЕ РЕЖИМЫ:**\n"
            "• 🙈 **Blind Pick (Вслепую):** игроки скидывают билды в ЛС судье, Респ объявляет их одновременно в ветке во избежание контрпика.\n"
            "• ⏱️ **No TS (Без Тайм-стопа):** запрет использования способности Time Stop.\n"
            "• 🥊 **Specless (Без спека):** чистые стенды без стилей боя (Boxing, Hamon, Pluck, Spin, Vamp).\n"
            "• 🥋 **Standless (Спек на спек):** бой без стендов, только стили боя.\n"
            "• 🏆 **Bo3 Сеты:** серия до 2 побед (Best of 3).\n\n"
            "🌐 **ПРИОРИТЕТ СЕРВЕРОВ:**\n"
            "• 🥇 **Hesse (Германия):** основной сервер EU/СНГ (минимальный средний пинг).\n"
            "• 🥈 **North Holland (Нидерланды):** альтернативный стабильный сервер EU.\n"
            "• 🥉 **London / US East:** для игроков соответствующих регионов.\n"
            "• 🤝 **По договоренности:** компромиссный регион с равным пингом.\n\n"
            "📖 *Полный свод правил нарушений, анти-кемпинга и проверок доступен по команде `/rules`.*"
        ),
        "en": (
            "👑 **REQUEST PRIORITY HIERARCHY:**\n"
            "• **T1 — Any vs Any:**\n"
            "  - **Highest Priority.** Full freedom of stand and fighting style (spec).\n"
            "  - Opponent is strictly required to accept T1 (declining is considered ducking).\n"
            "  - Maximum **1 stand swap** per match allowed.\n"
            "• **T2 — Main vs Main:**\n"
            "  - **2nd Priority.** Duelists play **strictly on their builds declared in the bot** (`/build` in profile).\n"
            "  - Build swap or playing on another stand is strictly **prohibited** (results in DQ / Duck). Anti-counterpick.\n"
            "• **T3 — Mirror (Same Stand):**\n"
            "  - **3rd Priority.** Both players play the identical stand (agreed in thread).\n"
            "  - Pure skill, F-parry timing, and matchup knowledge.\n\n"
            "🎯 **SPECIAL MODES:**\n"
            "• 🙈 **Blind Pick:** builds sent to Referee in DMs to eliminate counterpicking.\n"
            "• ⏱️ **No TS:** Time Stop ability banned.\n"
            "• 🥊 **Specless:** Stand only, no fighting styles.\n"
            "• 🥋 **Standless:** Fighting styles only, no stands.\n"
            "• 🏆 **Bo3 Sets:** First to 2 wins.\n\n"
            "🌐 **SERVER REGIONS:**\n"
            "• 🥇 **Hesse (Germany):** Primary server for EU/CIS.\n"
            "• 🥈 **North Holland:** Alternative high-stability EU server.\n"
            "• 🥉 **London / US East:** For players in respective locations.\n"
            "• 🤝 **Mutual Region:** Region with balanced ping.\n\n"
            "📖 *Detailed regulations, infraction penalties and screen checks: `/rules`.*"
        )
    },
    "challenge_server_field": {
        "ru": "🌐 Сервер региона",
        "en": "🌐 Server Region"
    },
    "challenge_match_title": {
        "ru": "⚔️ Официальная дуэль 1v1 GANGHUB",
        "en": "⚔️ Official GANGHUB 1v1 Duel"
    },
    "challenge_thread_created": {
        "ru": "✅ Вызов принят! Создана официальная ветка дуэли: {thread}\nСудьи (Респы) призваны для мониторинга.",
        "en": "✅ Challenge accepted! Official match thread created: {thread}\nReferees summoned to monitor the match."
    },
    "challenge_call_ref_btn": {
        "ru": "Позвать Респа",
        "en": "Call Referee"
    },
    "challenge_ref_called_title": {
        "ru": "📢 Вызов Респонсибла в ветку!",
        "en": "📢 Referee Summoned to Match Thread!"
    },
    "challenge_ref_called_desc": {
        "ru": "Игрок {user} вызывает Респонсибла {role} для проведения проверки/фиксации боя!\n\n• **Проверка на демке:** Свап аккаунтов, устройств, факт нахождения на сервере.\n• **Фиксация:** После боя судья вносит результат через `/match report`.",
        "en": "Player {user} summons a Referee {role} for screen check or match logging!\n\n• **Screen check:** Account swaps, devices, presence on server.\n• **Match Log:** After the duel, referee records the result via `/match report`."
    },
    "challenge_rules_notice": {
        "ru": "📖 *Полный регламент 1v1 лиги и правила нарушений: `/rules`*",
        "en": "📖 *Full 1v1 league regulations and match rules: `/rules`*"
    },
    "challenge_accept_btn": {
        "ru": "Принять вызов ⚔️",
        "en": "Accept Challenge ⚔️"
    },
    "challenge_decline_btn": {
        "ru": "Отклонить ❌",
        "en": "Decline ❌"
    },
    "challenge_cancel_btn": {
        "ru": "Отменить 🗑️",
        "en": "Cancel 🗑️"
    },
    "challenge_accepted_title": {
        "ru": "⚔️ Вызов принят! Дуэль началась!",
        "en": "⚔️ Challenge Accepted! Match Ready!"
    },
    "challenge_accepted_desc": {
        "ru": (
            "**{p1_mention}** VS **{p2_mention}**\n\n"
            "🕹️ **Что делать дальше:**\n"
            "1. Зайдите на VIP-сервер или общий 1v1 сервер YBA.\n"
            "2. Сыграйте дуэль 1 на 1.\n"
            "3. Позовите **Респа** для внесения счета через `/match report`!"
        ),
        "en": (
            "**{p1_mention}** VS **{p2_mention}**\n\n"
            "🕹️ **Next Steps:**\n"
            "1. Join a VIP server or shared 1v1 server in YBA.\n"
            "2. Fight the 1v1 duel.\n"
            "3. Call a **Referee** to submit the result via `/match report`!"
        )
    },
    "challenge_declined_title": {
        "ru": "❌ Вызов отклонен",
        "en": "❌ Challenge Declined"
    },
    "challenge_declined_desc": {
        "ru": "{challenged} отклонил вызов на дуэль от {challenger}.",
        "en": "{challenged} declined the duel challenge from {challenger}."
    },
    "challenge_timeout_title": {
        "ru": "⏳ Время ответа истекло",
        "en": "⏳ Challenge Expired"
    },
    "challenge_timeout_desc": {
        "ru": "Вызов от {challenger} для {challenged} был аннулирован по таймауту.",
        "en": "The duel challenge from {challenger} to {challenged} has expired."
    },
    "challenge_not_for_you": {
        "ru": "❌ Этот вызов предназначен не вам!",
        "en": "❌ This challenge is not for you!"
    },

    # --- /language ---
    "language_cmd_desc": {
        "ru": "Выбрать язык интерфейса бота и ЛС-уведомлений (ru / en)",
        "en": "Select preferred language for bot interface and DM notifications (ru / en)"
    },
    "language_choice_desc": {
        "ru": "Язык интерфейса",
        "en": "Interface language"
    },
    "language_changed_ru": {
        "ru": "✅ Язык интерфейса успешно установлен: **Русский** 🇷🇺.\nВсе уведомления и ЛС теперь будут приходить на русском языке!",
        "en": "✅ Language changed to: **Русский** 🇷🇺.\nAll notifications and DMs will now be delivered in Russian!"
    },
    "language_changed_en": {
        "ru": "✅ Interface language set to: **English** 🇬🇧.\nAll notifications and DMs will now be delivered in English!",
        "en": "✅ Interface language set to: **English** 🇬🇧.\nAll notifications and DMs will now be delivered in English!"
    },

    # --- Challenge Footers & Titles ---
    "challenge_footer": {
        "ru": "GangHub League 1v1 • Срок на ответ: 24 часа • Авто-Дак",
        "en": "GangHub League 1v1 • Reply deadline: 24 hours • Auto-Duck"
    },
    "challenge_dm_footer": {
        "ru": "GangHub 1v1 League • У тебя есть 24 часа на ответ!",
        "en": "GangHub 1v1 League • You have 24 hours to respond!"
    },
    "challenge_dm_duck_recipient_title": {
        "ru": "🦆 Наказание: Выдана роль Duck (Авто-Дак)",
        "en": "🦆 Penalty: Assigned Duck Role (Auto-Duck)"
    },
    "challenge_dm_duck_recipient_footer": {
        "ru": "GangHub 1v1 League • Истек 24-часовой срок на ответ",
        "en": "GangHub 1v1 League • 24-hour response deadline expired"
    },
    "challenge_dm_duck_challenger_title": {
        "ru": "🦆 Соперник занесен в Duck (Авто-Дак)",
        "en": "🦆 Opponent Marked as Duck (Auto-Duck)"
    },
    "challenge_dm_duck_challenger_footer": {
        "ru": "GangHub 1v1 League • Автоматическое судейство",
        "en": "GangHub 1v1 League • Automated Refereeing"
    },
    "challenge_dm_declined_duck_recipient_title": {
        "ru": "🦆 Тебе выдана роль Duck (Отказ от вызова)",
        "en": "🦆 You Received Duck Role (Challenge Declined)"
    },
    "challenge_dm_declined_duck_challenger_title": {
        "ru": "🦆 Соперник занесен в Duck (Отказ от вызова)",
        "en": "🦆 Opponent Marked as Duck (Challenge Declined)"
    },
    "challenge_dm_footer_declined": {
        "ru": "GangHub 1v1 League • Отказ от вызова",
        "en": "GangHub 1v1 League • Challenge Declined"
    },
    "challenge_dm_footer_refereeing": {
        "ru": "GangHub 1v1 League • Автоматическое судейство",
        "en": "GangHub 1v1 League • Automated Refereeing"
    },
    "challenge_dm_accepted_title": {
        "ru": "⚔️ Вызов на 1v1 принят!",
        "en": "⚔️ 1v1 Challenge Accepted!"
    },
    "challenge_dm_footer_ready": {
        "ru": "GangHub 1v1 League • Матч готов к началу",
        "en": "GangHub 1v1 League • Match is ready to begin"
    },
    "country_cmd_desc": {
        "ru": "Выбрать страну, которую ты представляешь в Лиге GANGHUB",
        "en": "Choose the country you represent in the GANGHUB League"
    },
    "country_param_desc": {
        "ru": "Страна (СНГ и Европа)",
        "en": "Country (CIS and Europe)"
    },
    "country_invalid": {
        "ru": "❌ Указана недоступная или неверная страна. Выберите страну из выпадающего списка!",
        "en": "❌ Invalid or unsupported country specified. Please select from the dropdown!"
    },
    "country_confirm_title": {
        "ru": "🌍 Подтверждение выбора страны",
        "en": "🌍 Country Selection Confirmation"
    },
    "country_confirm_desc": {
        "ru": "Ты выбрал: {flag} **{name}** (`{code}`)\n\n⚠️ **Обрати внимание:**\nЭтот флаг будет отображаться в твоем профиле, ветках дуэлей и таблице лидеров.\nСменить страну можно будет только через **{days} дней**!",
        "en": "You selected: {flag} **{name}** (`{code}`)\n\n⚠️ **Please note:**\nThis flag will be displayed in your profile, duel threads and leaderboard.\nYou will be able to change your country only in **{days} days**!"
    },
    "country_cooldown_error": {
        "ru": "⏳ Ты недавно менял страну! Следующая смена будет доступна через **{days} дн.**",
        "en": "⏳ You recently changed your country! Next change will be available in **{days} days**."
    },
    "country_success": {
        "ru": "✅ Ты успешно установил страну: {flag} **{name}**!",
        "en": "✅ Successfully set your country to: {flag} **{name}**!"
    },
    "country_reset_success": {
        "ru": "✅ Твоя страна была успешно сброшена.",
        "en": "✅ Your country has been successfully reset."
    },
    "country_profile_field": {
        "ru": "🌍 Страна",
        "en": "🌍 Country"
    },
    "country_cancelled": {
        "ru": "❌ Выбор страны отменен.",
        "en": "❌ Country selection cancelled."
    },
}

def t(key: str, lang: str = "en", **kwargs) -> str:
    """Получить переведенную строку с подстановкой параметров"""
    entry = MESSAGES.get(key, {})
    template = entry.get(lang) or entry.get("en") or entry.get("ru") or key
    if kwargs:
        try:
            return template.format(**kwargs)
        except Exception:
            return template
    return template

import asyncio
from typing import Dict, Any, Optional, List
import discord
from config import RANKS, SPECIAL_ROLES, MIN_GAMES_CALIBRATION, MAX_RD_CALIBRATION, DUCK_ROLE_NAME, DUCK_EVADE_ROLE_NAME
from logger import log

_role_lock = asyncio.Lock()

def get_rank_info(
    rating: float,
    rd: float,
    total_games: int,
    rank_position: Optional[int] = None,
    lang: str = "ru"
) -> Dict[str, Any]:
    """
    Возвращает информацию о текущем ранге игрока, бэйдже и цвете.
    """
    # Проверка на калибровку (Lichess стиль)
    if total_games < MIN_GAMES_CALIBRATION or rd > MAX_RD_CALIBRATION:
        calib_tier = "Unranked / Calibration" if lang == "en" else SPECIAL_ROLES["CALIBRATION"]["name"]
        return {
            "name": SPECIAL_ROLES["CALIBRATION"]["name"],
            "badge": SPECIAL_ROLES["CALIBRATION"]["badge"],
            "color": SPECIAL_ROLES["CALIBRATION"]["color"],
            "is_calibrated": False,
            "display": f"{int(round(rating))}?",
            "tier": calib_tier,
            "role_name": SPECIAL_ROLES["CALIBRATION"]["name"],
            "calib_progress": f"{total_games}/{MIN_GAMES_CALIBRATION}",
        }

    # Специальные статусы для топов
    if rank_position == 1:
        top_name = f"{SPECIAL_ROLES['TOP_10']['badge']} Top 10 (Champion #1)" if lang == "en" else f"{SPECIAL_ROLES['TOP_10']['badge']} Top 10 (Чемпион #1)"
    elif rank_position is not None and rank_position <= 10:
        top_name = f"{SPECIAL_ROLES['TOP_10']['badge']} Top 10 (#{rank_position})"
    else:
        top_name = None

    # Поиск стандартного ранга по рейтингу
    for r in RANKS:
        if r["min_rating"] <= rating <= r["max_rating"]:
            return {
                "name": r["name"],
                "badge": r["badge"],
                "color": r["color"],
                "is_calibrated": True,
                "display": f"{int(round(rating))}",
                "tier": r["name"],
                "role_name": r["name"],
                "special_title": top_name,
            }

    # Фолбэк на высший ранг
    highest = RANKS[-1]
    return {
        "name": highest["name"],
        "badge": highest["badge"],
        "color": highest["color"],
        "is_calibrated": True,
        "display": f"{int(round(rating))}",
        "tier": highest["name"],
        "role_name": highest["name"],
        "special_title": top_name,
    }


async def ensure_all_rank_roles(guild: discord.Guild) -> List[str]:
    """
    Проверяет наличие всех ранговых и турнирных ролей Лиги на сервере и создает недостающие.
    Возвращает список названий созданных ролей.
    """
    me = guild.me
    if not me or not me.guild_permissions.manage_roles:
        log.warning(f"❌ [Роли] ensure_all_rank_roles: у бота нет права 'Manage Roles' (Управлять ролями) на сервере {guild.name} ({guild.id})!")
        return []

    created_roles = []
    existing_role_names = {r.name: r for r in guild.roles}

    # Формируем перечень всех соревновательных ролей Лиги (в порядке возрастания)
    roles_to_ensure = []
    for r in RANKS:
        roles_to_ensure.append((r["name"], r["color"]))

    roles_to_ensure.append((SPECIAL_ROLES["TOP_10"]["name"], SPECIAL_ROLES["TOP_10"]["color"]))
    roles_to_ensure.append((SPECIAL_ROLES["TOP_1"]["name"], SPECIAL_ROLES["TOP_1"]["color"]))

    if DUCK_ROLE_NAME:
        roles_to_ensure.append((DUCK_ROLE_NAME, 0xE67E22))
    if DUCK_EVADE_ROLE_NAME:
        roles_to_ensure.append((DUCK_EVADE_ROLE_NAME, 0x992D22))

    async with _role_lock:
        for name, color in roles_to_ensure:
            if name not in existing_role_names:
                try:
                    new_role = await guild.create_role(
                        name=name,
                        color=discord.Color(color),
                        reason="Автоматическое создание соревновательных ролей Лиги GANGHUB"
                    )
                    existing_role_names[name] = new_role
                    created_roles.append(name)
                    log.info(f"✨ [Роли] Создана роль '{name}' на сервере {guild.name}")
                    await asyncio.sleep(0.3)
                except discord.Forbidden as e:
                    log.warning(f"⚠️ [403 Forbidden] Не удалось создать роль '{name}': {e}. Проверьте права бота!")
                except discord.HTTPException as e:
                    log.error(f"❌ [HTTPException] Ошибка при создании роли '{name}': {e}")

    return created_roles


async def sync_user_roles(member: discord.Member, rank_info: Dict[str, Any], guild: discord.Guild) -> Optional[str]:
    """
    Безопасно и атомарно обновляет ранговую роль у игрока.
    - Учитывает иерархию ролей Discord (не крашится, если роль выше бота).
    - Делает ровно 1 HTTP-запрос через member.edit(roles=...) вместо пачки запросов.
    - Защищен от 403 Forbidden при попытке изменить владельца сервера.
    """
    me = guild.me
    if not me or not me.guild_permissions.manage_roles:
        log.warning(f"❌ [Роли] У бота нет права 'Manage Roles' (Управлять ролями) на сервере {guild.name} ({guild.id})! Роль игроку {member.display_name} не выдана.")
        return None

    bot_top_role = me.top_role
    target_role_name = rank_info.get("role_name", rank_info["tier"])
    all_rank_names = [r["name"] for r in RANKS] + [SPECIAL_ROLES["CALIBRATION"]["name"]]

    # Игрокам на калибровке (< 5 матчей) роли не выдаются вообще, чтобы не засорять профиль
    if not rank_info.get("is_calibrated", True):
        current_rank_roles = [
            r for r in member.roles
            if (r.name in all_rank_names or r.name == SPECIAL_ROLES["TOP_10"]["name"]) and r < bot_top_role
        ]
        if current_rank_roles:
            new_roles = [r for r in member.roles if r not in current_rank_roles and r.id != guild.id]
            try:
                await member.edit(roles=new_roles, reason="Игрок находится на калибровке (< 5 матчей)")
            except (discord.Forbidden, discord.HTTPException):
                pass
        return None

    role_to_add = None

    # Поиск существующей роли
    for role in guild.roles:
        if role.name == target_role_name:
            role_to_add = role
            break

    # Если роли еще нет на сервере — пытаемся создать с защитой от Race Condition
    if not role_to_add:
        async with _role_lock:
            # Double-checked locking: повторная проверка наличия роли после захвата блокировки
            for role in guild.roles:
                if role.name == target_role_name:
                    role_to_add = role
                    break
            if not role_to_add:
                try:
                    role_to_add = await guild.create_role(
                        name=target_role_name,
                        color=discord.Color(rank_info["color"]),
                        reason="Создание ранговой роли ELO бота"
                    )
                    log.info(f"✨ [Роли] Автоматически создана роль '{target_role_name}' для {member.display_name}")
                except (discord.Forbidden, discord.HTTPException) as e:
                    log.warning(f"⚠️ [Роли] Не удалось создать роль '{target_role_name}' для {member.display_name}: {e}")
                    return None

    # Проверка иерархии: бот не может выдавать роль, которая выше или равна его наивысшей роли
    if role_to_add >= bot_top_role:
        log.warning(
            f"⚠️ [Иерархия ролей] Невозможно выдать роль '{role_to_add.name}' игроку {member.display_name}: "
            f"роль '{role_to_add.name}' находится ВЫШЕ или на одном уровне с ролью бота '{bot_top_role.name}'! "
            f"Перетащите роль бота ВЫШЕ роли '{role_to_add.name}' в Настройках сервера -> Роли."
        )
        return None

    # Поиск роли Top 10
    top10_role = None
    for role in guild.roles:
        if role.name == SPECIAL_ROLES["TOP_10"]["name"]:
            top10_role = role
            break

    # Формируем новый список ролей: убираем старые ранги (только те, которые ниже роли бота), добавляем целевой
    roles_to_remove = [
        r for r in member.roles
        if (r.name in all_rank_names or r.name == SPECIAL_ROLES["TOP_10"]["name"]) and r < bot_top_role
    ]
    current_roles = [r for r in member.roles if r not in roles_to_remove and r.id != guild.id]
    new_roles = current_roles + [role_to_add]

    # Если игрок входит в Top 10 — выдаем роль Top 10 (создаем при необходимости)
    is_top10 = rank_info.get("special_title") is not None
    if is_top10:
        if not top10_role:
            async with _role_lock:
                for role in guild.roles:
                    if role.name == SPECIAL_ROLES["TOP_10"]["name"]:
                        top10_role = role
                        break
                if not top10_role:
                    try:
                        top10_role = await guild.create_role(
                            name=SPECIAL_ROLES["TOP_10"]["name"],
                            color=discord.Color(SPECIAL_ROLES["TOP_10"]["color"]),
                            reason="Создание роли Top 10 для ладдера Лиги"
                        )
                        log.info(f"✨ [Роли] Создана роль 'Top 10' на сервере {guild.name}")
                    except (discord.Forbidden, discord.HTTPException) as e:
                        log.warning(f"⚠️ [Роли] Не удалось создать роль 'Top 10': {e}")
                        top10_role = None

        if top10_role and top10_role < bot_top_role and top10_role not in new_roles:
            new_roles.append(top10_role)
        elif top10_role and top10_role >= bot_top_role:
            log.warning(
                f"⚠️ [Иерархия ролей] Роль 'Top 10' выше роли бота '{bot_top_role.name}'! "
                f"Перетащите роль бота выше 'Top 10'."
            )

    # Атомарное обновление за ОДИН сетевой запрос
    try:
        if set(new_roles) != set(member.roles):
            await member.edit(roles=new_roles, reason=f"Обновление ELO ранга: {target_role_name}")
            return role_to_add.name
    except discord.Forbidden as e:
        log.warning(
            f"⚠️ [403 Forbidden] Не удалось изменить роли для {member.display_name} ({member.id}): {e}. "
            f"Причина: наивысшая роль участника '{getattr(member.top_role, 'name', 'Unknown')}' или целевая роль "
            f"выше роли бота '{bot_top_role.name}'. Переместите роль бота ВЫШЕ всех ролей игроков и рангов!"
        )
        return None
    except discord.HTTPException as e:
        log.error(f"❌ [HTTPException] Ошибка при обновлении ролей для {member.display_name}: {e}")
        return None

    return role_to_add.name

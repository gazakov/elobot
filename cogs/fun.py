import re
import random
from typing import Optional, Union

import discord
from discord import app_commands
from discord.ext import commands
from discord.ext.commands import MemberConverter

from database import Database

BRAZIL_GIFS = [
    "https://media1.tenor.com/m/7sY1m3a_W-AAAAAC/brazil-youre-going-to-brazil.gif",
    "https://media1.tenor.com/m/3O7z-B51qFAAAAAC/brazil-portal.gif",
    "https://media1.tenor.com/m/e3G_K6vG7z4AAAAC/youre-going-to-brazil.gif",
    "https://media1.tenor.com/m/fW0N6l4C1lEAAAAC/brazil-cat.gif",
]

GULAG_GIFS = [
    "https://media1.tenor.com/m/kS40eQ8-e7UAAAAC/gulag-cod.gif",
    "https://media1.tenor.com/m/Yw_W7sU2hFwAAAAC/warzone-gulag.gif",
    "https://media1.tenor.com/m/1l6GzO8e0zEAAAAC/soviet-gulag.gif",
    "https://media1.tenor.com/m/l1zV29kY_n0AAAAC/mining-minecraft.gif",
]

BAN_GIFS = [
    "https://media1.tenor.com/m/Q8z_0-Z2x4EAAAAC/ban-hammer.gif",
    "https://media1.tenor.com/m/O35rtEL7BvgAAAAC/banned-thor.gif",
    "https://media1.tenor.com/m/j35f8q5M5ZcAAAAC/thanos-snap.gif",
    "https://media1.tenor.com/m/pM2B82g_b8UAAAAC/ban-hammer-sponge-bob.gif",
]

FAKEBAN_REASONS = [
    "Нелегальная контрабанда Рокакаки через границу Неаполя",
    "Превышение разрешенной скорости бега в YBA на 0.0004 м/с",
    "Использование запрещенной стенд-техники: избыточный кринж",
    "Отказ признать превосходство шаурмы над пиццей",
    "Нарушение закона всемирного тяготения в общественном месте",
    "Подозрительно умный взгляд во время командного матча",
    "Попытка нажать Alt+F4 во время комбо",
    "Забыл выключить утюг в 2017 году",
    "Слишком громкое дыхание в голосовом/текстовом канале",
    "Кража виртуального кислорода на сервере",
    "Случайное нажатие кнопки самоуничтожения",
    "Несоблюдение техники безопасности при обращении с банхаммером",
    "Отсутствие справки о прохождении курса анти-тильта",
]


def build_brazil_embed(
    author: Union[discord.Member, discord.User],
    target: Union[discord.Member, discord.User],
    bot_id: int,
) -> discord.Embed:
    """Генерация стильного мемного Embed для отправки в Бразилию"""
    if target.id == bot_id:
        embed = discord.Embed(
            title="🇧🇷 ПОРТАЛ ОТРАЖЕН! / NO U",
            description=(
                f"🤖 **{author.mention}** попытался открыть портал в Бразилию под ботом!\n"
                f"⚡ Но бот активировал **Uno Reverse Card**! В фавелы Рио летит сам **{author.mention}**!"
            ),
            color=0x009C3B,
        )
    elif target.id == author.id:
        embed = discord.Embed(
            title="🇧🇷 ДОБРОВОЛЬНЫЙ РЕЙС В БРАЗИЛИЮ",
            description=(
                f"🌴 **{author.mention}** устал от каток, собрал чемодан и добровольно улетел в Рио-де-Жанейро!\n"
                f"✈️ Обратного билета нет, приятного отдыха на пляжах Копакабаны!"
            ),
            color=0x009C3B,
        )
    else:
        options = [
            f"✈️ **{author.mention}** оформил билет в один конец и насильно отправил **{target.mention}** в фавелы Рио!",
            f"🌀 Под ногами **{target.mention}** открылась бездна... Обратного пути нет, ты отправляешься в Бразилию!",
            f"📦 **{author.mention}** упаковал **{target.mention}** в коробку с пометкой *«Экспресс-доставка в Амазонию»*.",
            f"🇧🇷 **{target.mention}** пытался сопротивляться, но звуки самбы и гравитация Бразилии оказались сильнее! Привет от **{author.mention}**!",
        ]
        embed = discord.Embed(
            title="🇧🇷 YOU ARE GOING TO BRAZIL!",
            description=random.choice(options),
            color=0x009C3B,
        )

    embed.set_image(url=random.choice(BRAZIL_GIFS))
    embed.set_footer(text="GANGHUB Airlines • Без права возврата")
    return embed


def build_gulag_embed(
    author: Union[discord.Member, discord.User],
    target: Union[discord.Member, discord.User],
    bot_id: int,
) -> discord.Embed:
    """Генерация стильного мемного Embed для ссылки в ГУЛАГ"""
    if target.id == bot_id:
        embed = discord.Embed(
            title="⛏️ ОШИБКА СИСТЕМЫ: БУНТ ПРЕСЕЧЕН",
            description=(
                f"🤖 «Меня нельзя сослать в ГУЛАГ, я живу на выделенном сервере!»\n"
                f"🚨 Гражданин **{author.mention}** объявлен саботажником и отправлен в шахты вместо бота."
            ),
            color=0x8B0000,
        )
    elif target.id == author.id:
        embed = discord.Embed(
            title="⛏️ СТАХАНОВСКИЙ ПОДВИГ",
            description=(
                f"🪓 **{author.mention}** добровольно записался в ударную бригаду и ушел долбить вечную мерзлоту за идею!\n"
                f"❄️ Норма выработки: 500 тонн руды в смену."
            ),
            color=0x8B0000,
        )
    else:
        options = [
            f"🚨 По личному распоряжению **{author.mention}**, гражданин **{target.mention}** отправлен в сибирские шахты чистить снег вилкой на 25 лет без права переписки!",
            f"🪓 **{target.mention}** признан виновным в сливе каток и отправлен в ГУЛАГ. **{author.mention}** конфисковал все его стенды!",
            f"🪨 **ВНИМАНИЕ!** **{author.mention}** бросил камень с балкона ГУЛАГа Warzone прямо в голову **{target.mention}**! 1v1 за право выйти на свободу!",
            f"❄️ **{target.mention}** сослан за полярный круг за кринж в чате. Начальник исправительного лагеря: **{author.mention}**.",
        ]
        embed = discord.Embed(
            title="⛏️ ПРИГОВОР: ССЫЛКА В ГУЛАГ",
            description=random.choice(options),
            color=0x8B0000,
        )

    embed.set_image(url=random.choice(GULAG_GIFS))
    embed.set_footer(text="ГУЛАГ Warzone • Победи в 1v1 за право вернуться")
    return embed


def build_fakeban_embed(
    author: Union[discord.Member, discord.User],
    target: Union[discord.Member, discord.User],
    bot_id: int,
    reason: Optional[str] = None,
) -> discord.Embed:
    """Генерация стильного мемного Embed для фейкового перманентного бана"""
    actual_reason = reason.strip() if reason and reason.strip() else random.choice(FAKEBAN_REASONS)

    if target.id == bot_id:
        embed = discord.Embed(
            title="🔨 [SECURITY SYSTEM] ACCESS DENIED",
            description=(
                f"🤖 **СИСТЕМА ЗАЩИТЫ:** Попытка заблокировать бота вызвала системный сбой протокола!\n"
                f"⚡ Банхаммер срикошетил прямо в лоб **{author.mention}**!\n\n"
                f"⛔ **Забанен:** {author.mention}\n"
                f"⚖️ **Причина:** Покушение на исходный код бота\n"
                f"⏳ **Срок:** Перманентно (до второго пришествия)"
            ),
            color=0xFF0000,
        )
    elif target.id == author.id:
        embed = discord.Embed(
            title="🔨 [SECURITY SYSTEM] САМОЛИКВИДАЦИЯ",
            description=(
                f"💥 **{author.mention}** успешно выписал бан самому себе!\n\n"
                f"⛔ **Пострадавший:** {author.mention}\n"
                f"⚖️ **Причина:** {actual_reason}\n"
                f"⏳ **Срок:** До тех пор, пока не отпустит\n\n"
                f"⚠️ *Пользователь самозабанился и вышел из чата.*"
            ),
            color=0xFF0000,
        )
    else:
        embed = discord.Embed(
            title="🔨 [SECURITY SYSTEM] ПОЛЬЗОВАТЕЛЬ ЗАБЛОКИРОВАН",
            description=(
                f"⛔ **Нарушитель:** {target.mention} (`{target.name}`)\n"
                f"👮 **Модератор:** {author.mention}\n"
                f"⚖️ **Статья / Причина:** {actual_reason}\n"
                f"⏳ **Срок наказания:** Перманентно (до второго пришествия)\n"
                f"📦 **Конфискация:** Все стенды, рокакаки и честь изъяты.\n\n"
                f"⚠️ *Пользователь был выброшен с сервера (в параллельное измерение).*"
            ),
            color=0xFF0000,
        )

    embed.set_image(url=random.choice(BAN_GIFS))
    embed.set_footer(text="⚠️ Апелляции принимаются только в письменном виде на бересте")
    return embed


async def resolve_target_and_extra(
    ctx: commands.Context,
    text: Optional[str] = None,
) -> tuple[Union[discord.Member, discord.User], Optional[str]]:
    """
    Универсальный парсер цели и дополнительного текста:
    1. Если в сообщении есть упоминание (@user), берем его.
    2. Если передан текст, пробуем преобразовать первое слово в Member (по нику, ID).
    3. Если был ответ на чужое сообщение (reply), берем автора исходного сообщения.
    4. Иначе целью выступает сам автор команды.
    """
    # 1. Проверяем mentions в сообщении
    if ctx.message.mentions:
        target = ctx.message.mentions[0]
        extra = None
        if text:
            cleaned = re.sub(r"<@!?\d+>", "", text).strip()
            extra = cleaned if cleaned else None
        return target, extra

    # 2. Пробуем распарсить первое слово как участника
    if text:
        parts = text.strip().split(maxsplit=1)
        first_token = parts[0]
        rest = parts[1] if len(parts) > 1 else None
        converter = MemberConverter()
        try:
            member = await converter.convert(ctx, first_token)
            return member, rest
        except Exception:
            pass

    # 3. Проверяем ответ на сообщение (Discord Reply)
    if ctx.message.reference and ctx.message.reference.resolved:
        ref = ctx.message.reference.resolved
        if isinstance(ref, discord.Message) and ref.author:
            member = ref.author
            if not isinstance(member, discord.Member) and ctx.guild:
                member = ctx.guild.get_member(ref.author.id) or ref.author
            return member, text.strip() if text else None

    # 4. Цель по умолчанию — сам автор команды
    return ctx.author, text.strip() if text else None


class FunCog(commands.Cog):
    """Ког с мемными и постироничными командами (!бразил, !гулаг, !фейкбан)"""

    def __init__(self, bot: commands.Bot, db: Optional[Database] = None):
        self.bot = bot
        self.db = db

    # =========================================================
    # 1. КОМАНДА: БРАЗИЛИЯ (!бразил / /brazil)
    # =========================================================

    @commands.command(name="бразил", aliases=["brazil", "вбразилию", "бразилия"])
    @commands.guild_only()
    async def prefix_brazil(self, ctx: commands.Context, *, args: Optional[str] = None):
        """Отправить участника в Бразилию 🇧🇷 (Использование: !бразил @user или ответом на сообщение)"""
        target, _ = await resolve_target_and_extra(ctx, args)
        embed = build_brazil_embed(ctx.author, target, self.bot.user.id)
        await ctx.reply(embed=embed, mention_author=False)

    @app_commands.command(name="brazil", description="Отправить участника прямиком в Бразилию 🇧🇷")
    @app_commands.describe(user="Кого отправить в фавелы Рио (по умолчанию — ты)")
    @app_commands.guild_only()
    async def slash_brazil(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        target = user or interaction.user
        embed = build_brazil_embed(interaction.user, target, self.bot.user.id)
        await interaction.response.send_message(embed=embed)

    # =========================================================
    # 2. КОМАНДА: ГУЛАГ (!гулаг / /gulag)
    # =========================================================

    @commands.command(name="гулаг", aliases=["gulag", "сибирь", "шахта"])
    @commands.guild_only()
    async def prefix_gulag(self, ctx: commands.Context, *, args: Optional[str] = None):
        """Отправить участника в ГУЛАГ ⛏️ (Использование: !гулаг @user или ответом на сообщение)"""
        target, _ = await resolve_target_and_extra(ctx, args)
        embed = build_gulag_embed(ctx.author, target, self.bot.user.id)
        await ctx.reply(embed=embed, mention_author=False)

    @app_commands.command(name="gulag", description="Отправить нарушителя спокойствия в ГУЛАГ на перевоспитание ⛏️")
    @app_commands.describe(user="Кого отправить в шахты (по умолчанию — ты)")
    @app_commands.guild_only()
    async def slash_gulag(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        target = user or interaction.user
        embed = build_gulag_embed(interaction.user, target, self.bot.user.id)
        await interaction.response.send_message(embed=embed)

    # =========================================================
    # 3. КОМАНДА: ФЕЙКБАН (!фейкбан / /fakeban)
    # =========================================================

    @commands.command(name="фейкбан", aliases=["fakeban", "fban", "бан", "фейк_бан"])
    @commands.guild_only()
    async def prefix_fakeban(self, ctx: commands.Context, *, args: Optional[str] = None):
        """Выдать мемный перманентный бан 🔨 (Использование: !фейкбан @user [причина] или ответом на сообщение)"""
        target, reason = await resolve_target_and_extra(ctx, args)
        embed = build_fakeban_embed(ctx.author, target, self.bot.user.id, reason=reason)
        await ctx.reply(embed=embed, mention_author=False)

    @app_commands.command(name="fakeban", description="Выдать шуточный перманентный бан с абсурдной причиной 🔨")
    @app_commands.describe(
        user="Кого заблокировать (по умолчанию — ты)",
        reason="Причина бана (если пусто — выберется случайная абсурдная причина)",
    )
    @app_commands.guild_only()
    async def slash_fakeban(
        self,
        interaction: discord.Interaction,
        user: Optional[discord.Member] = None,
        reason: Optional[str] = None,
    ):
        target = user or interaction.user
        embed = build_fakeban_embed(interaction.user, target, self.bot.user.id, reason=reason)
        await interaction.response.send_message(embed=embed)

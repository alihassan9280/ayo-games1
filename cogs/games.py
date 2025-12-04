import random
import asyncio
import discord
from discord.ext import commands

from utils import db
from utils.common import make_embed, send_log

CURRENCY_EMOJI = "💰"
MAX_BET = 250_000


def parse_bet_and_choice(args):
    amount = None
    choice = None
    for a in args:
        low = a.lower()
        if low in {"h", "head", "heads"}:
            choice = "heads"
        elif low in {"t", "tail", "tails"}:
            choice = "tails"
        elif low == "all":
            amount = "all"
        elif a.isdigit():
            amount = int(a)
    return amount, choice


def parse_bet_only(args):
    amount = None
    for a in args:
        low = a.lower()
        if low == "all":
            amount = "all"
        elif a.isdigit():
            amount = int(a)
    return amount


def resolve_bet_amount(profile, amount):
    if amount == "all":
        bet = profile["cash"]
    else:
        bet = amount

    if bet is None or bet <= 0:
        return None, "❌ Invalid bet amount."

    if profile["cash"] <= 0:
        return None, "❌ You have no cash."

    if bet > profile["cash"]:
        return None, "❌ You don't have that much cash."

    if bet > MAX_BET:
        bet = MAX_BET
    return bet, None


class Games(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    def games_enabled(self):
        return db.are_games_enabled()

    @commands.command(name="cf", aliases=["coinflip", "coin"])
    async def coinflip_command(self, ctx: commands.Context, *args):
        # ayocf / ayo cf
        if not self.games_enabled():
            await ctx.send("🎮 Games are currently disabled by the owner.")
            return

        if len(args) < 2:
            await ctx.send(
                "Usage: `ayo cf <amount> <h/t>` or `ayo cf <h/t> <amount>` (amount or `all`)."
            )
            return

        profile = db.get_profile(ctx.author.id)
        amount, choice = parse_bet_and_choice(args)

        if choice is None:
            await ctx.send("❌ Choose `h` or `t`.")
            return

        bet, err = resolve_bet_amount(profile, amount)
        if err:
            await ctx.send(err)
            return

        loading = make_embed(
            title="Coinflip",
            description=
            (f"🎲 Placing bet **{bet:,} {CURRENCY_EMOJI}** on **{choice}**...\n"
             f"Flipping coin..."),
        )
        msg = await ctx.send(embed=loading)

        await asyncio.sleep(1.5)

        result = random.choice(["heads", "tails"])
        win = (result == choice)

        if win:
            profile["cash"] += bet
            line = f"✅ You **won** **{bet:,} {CURRENCY_EMOJI}**."
        else:
            profile["cash"] -= bet
            line = f"💀 You **lost** **{bet:,} {CURRENCY_EMOJI}**."

        db.save_users()

        # no "New Cash" line, clean & short
        result_embed = make_embed(
            title="Coinflip Result",
            description=(f"🪙 **Result:** {result}\n"
                         f"{line}"),
        )

        await msg.edit(embed=result_embed)

        if ctx.guild:
            log_embed = make_embed(
                title="Coinflip Game",
                description=
                f"{ctx.author} bet **{bet:,}** on **{choice}** → result **{result}**.",
            )
            await send_log(self.bot, ctx.guild, "games", log_embed)

    @commands.command(name="slots", aliases=["s"])
    async def slots_command(self, ctx: commands.Context, *args):
        # ayoslots / ayo slots / ayos all
        if not self.games_enabled():
            await ctx.send("🎮 Games are currently disabled by the owner.")
            return

        if not args:
            await ctx.send("Usage: `ayo slots <amount>` or `ayos all`")
            return

        profile = db.get_profile(ctx.author.id)
        amount = parse_bet_only(args)
        bet, err = resolve_bet_amount(profile, amount)
        if err:
            await ctx.send(err)
            return

        loading = make_embed(
            title="Slots",
            description=(
                f"🎰 Spinning with bet **{bet:,} {CURRENCY_EMOJI}**...\n"
                f"Rolling..."),
        )
        msg = await ctx.send(embed=loading)

        await asyncio.sleep(1.5)

        symbols = ["🍒", "🍋", "⭐", "💎", "7️⃣"]
        a, b, c = random.choice(symbols), random.choice(
            symbols), random.choice(symbols)

        profile["cash"] -= bet
        win_text = f"💸 `{a} {b} {c}` – No match, you lost **{bet:,} {CURRENCY_EMOJI}**."
        if a == b == c:
            win_amount = bet * 3
            profile["cash"] += win_amount
            win_text = f"🎰 JACKPOT! `{a} {b} {c}` → You won **{win_amount:,} {CURRENCY_EMOJI}**!"
        elif a == b or a == c or b == c:
            win_amount = int(bet * 1.5)
            profile["cash"] += win_amount
            win_text = f"✨ Nice! `{a} {b} {c}` → You won **{win_amount:,} {CURRENCY_EMOJI}**!"

        db.save_users()

        desc = (f"**Roll:** `{a} {b} {c}`\n"
                f"{win_text}")
        result_embed = make_embed(title="Slots Result", description=desc)
        await msg.edit(embed=result_embed)

        if ctx.guild:
            log_embed = make_embed(
                title="Slots Game",
                description=f"{ctx.author} bet **{bet:,} {CURRENCY_EMOJI}**.",
            )
            await send_log(self.bot, ctx.guild, "games", log_embed)


async def setup(bot):
    await bot.add_cog(Games(bot))

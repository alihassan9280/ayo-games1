# cogs/crash.py

import random
import asyncio
import math
from collections import deque

import discord
from discord.ext import commands

from utils import db
from utils.common import make_embed, send_log

CURRENCY_EMOJI = "💰"
MAX_BET = 250_000
STOP_EMOJI = "⏹️"


class CrashView(discord.ui.View):
    """
    STOP button view - sirf game owner use kar sakta hai.
    """

    def __init__(self, user_id: int, *, timeout: float = 120.0):
        super().__init__(timeout=timeout)
        self.user_id = user_id
        self.stopped = False

    @discord.ui.button(
        label="STOP",
        emoji=STOP_EMOJI,
        style=discord.ButtonStyle.danger,
    )
    async def stop_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        # Sirf game start karne wala banda click kar sakta hai
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "⚠️ This is not your crash game.",
                ephemeral=True,
            )
            return

        if self.stopped:
            await interaction.response.defer()
            return

        self.stopped = True
        await interaction.response.defer()


class Crash(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.active = set()  # user_id set -> prevent multi-games

        # GLOBAL RTP + STATS
        self.target_rtp = 0.90  # 90% default RTP (owner command se change hoga)
        self.global_stats = {
            "bet_total": 0,
            "paid_out": 0,
            "games": 0,
        }

        # USER streaks: {user_id: {"win": int, "loss": int}}
        self.user_streaks = {}

        # Recent big wins (True/False) anti-lucky-spam ke liye
        self.recent_big_wins = deque(maxlen=50)

    # ======================================
    # OWNER COMMAND: RTP CONTROL
    # ======================================

    @commands.command(name="crashrtp")
    @commands.is_owner()
    async def crash_rtp_command(self,
                                ctx: commands.Context,
                                value: float = None):
        """
        Owner only:
        ayo crashrtp 0.90  -> 90% RTP
        Range: 0.50 - 0.99
        """
        if value is None:
            current = self.target_rtp
            await ctx.send(embed=make_embed(
                title="🎯 Crash RTP",
                description=(f"Current Crash RTP: **{current:.2%}**\n"
                             f"Use `ayo crashrtp 0.85` to set 85% RTP.\n"
                             f"Allowed range: `0.50` - `0.99`."),
            ))
            return

        if not (0.50 <= value <= 0.99):
            await ctx.send(
                "❌ RTP must be between `0.50` and `0.99` (50% - 99%).")
            return

        self.target_rtp = value
        await ctx.send(embed=make_embed(
            title="✅ Crash RTP Updated",
            description=f"New Crash RTP set to **{value:.2%}**",
        ))

    # ======================================
    # MAIN GAME COMMAND
    # ======================================

    @commands.command(name="crash", aliases=["ayocrash"])
    async def crash_command(self, ctx: commands.Context, amount: str = None):
        """
        ayo crash 5000
        ayo crash all
        """
        # Games toggle
        if not db.are_games_enabled():
            await ctx.send("❌ Games are currently disabled.")
            return

        # Already in a game?
        if ctx.author.id in self.active:
            await ctx.send("❌ You already have an active crash game.")
            return

        if amount is None:
            await ctx.send(f"Usage: `ayo crash <amount>` or `ayo crash all`\n"
                           f"Example: `ayo crash 5000`")
            return

        profile = db.get_profile(ctx.author.id)
        balance = profile["cash"]
        raw = amount.lower()

        # Handle "all"
        if raw == "all":
            bet = min(balance, MAX_BET)
        else:
            if not raw.isdigit():
                await ctx.send("❌ Bet must be a positive number or `all`.")
                return
            bet = int(raw)

        if bet <= 0:
            await ctx.send("❌ Bet must be positive.")
            return
        if bet > MAX_BET:
            await ctx.send(f"❌ Max bet is `{MAX_BET:,}` {CURRENCY_EMOJI}.")
            return
        if bet > balance:
            await ctx.send("❌ You don't have enough cash.")
            return

        # Lock user
        self.active.add(ctx.author.id)

        # Take bet immediately
        profile["cash"] -= bet
        db.save_users()

        try:
            # Random crash point with advanced logic
            crash_point = self._generate_crash_point(ctx.author.id, bet)

            multiplier = 1.0
            stopped = False
            cashout_mult = None

            # Initial embed
            embed = make_embed(
                title="🚀 AYO Crash",
                description=
                (f"👤 Player: {ctx.author.mention}\n"
                 f"🎯 **Bet:** `{bet:,}` {CURRENCY_EMOJI}\n"
                 f"📈 **Multiplier:** `1.00x`\n"
                 f"💵 **Potential Cashout:** `{bet:,}` {CURRENCY_EMOJI}\n\n"
                 f"Press the **{STOP_EMOJI} STOP** button **anytime to CASHOUT** before it crashes!"
                 ),
            )

            view = CrashView(ctx.author.id, timeout=120.0)
            msg = await ctx.send(embed=embed, view=view)

            # GAME LOOP
            step_time = 0.25  # seconds per step

            while True:
                await asyncio.sleep(step_time)

                # Agar user ne STOP press kar diya:
                if view.stopped:
                    stopped = True
                    cashout_mult = multiplier
                    break

                # multiplier increase
                multiplier = self._next_multiplier(multiplier)

                # crash check
                if multiplier >= crash_point:
                    break

                # Live update: multiplier + potential cashout
                current_cash = int(bet * multiplier)

                embed.description = (
                    f"👤 Player: {ctx.author.mention}\n"
                    f"🎯 **Bet:** `{bet:,}` {CURRENCY_EMOJI}\n"
                    f"📈 **Multiplier:** `{multiplier:.2f}x`\n"
                    f"💵 **Potential Cashout:** `{current_cash:,}` {CURRENCY_EMOJI}\n\n"
                    f"Press the **{STOP_EMOJI} STOP** button **anytime to CASHOUT** before it crashes!"
                )
                await msg.edit(embed=embed, view=view)

            # Disable button after game ends
            for child in view.children:
                child.disabled = True

            profile = db.get_profile(ctx.author.id)  # reload
            result_desc = ""
            roi_percent = -100.0  # default = full loss
            win_amount = 0
            profit = 0
            win = False

            # WIN condition
            if stopped and cashout_mult is not None and cashout_mult < crash_point:
                win = True
                win_amount = int(bet * cashout_mult)
                profit = win_amount - bet
                profile["cash"] += win_amount

                # XP reward – small
                from_cog = self.bot.get_cog("Economy")
                if from_cog:
                    await from_cog._add_xp_and_check_level(ctx,
                                                           profile,
                                                           xp_gain=8)

                db.save_users()

                roi_percent = (profit / bet) * 100 if bet > 0 else 0

                result_desc = (
                    f"✅ **You CASHED OUT!**\n\n"
                    f"📈 Cashout Multiplier: `{cashout_mult:.2f}x`\n"
                    f"💵 Winnings: `{win_amount:,}` {CURRENCY_EMOJI}\n"
                    f"📊 Profit: `+{profit:,}` {CURRENCY_EMOJI}\n"
                    f"📈 ROI: `+{roi_percent:.1f}%`\n\n"
                    f"💣 Crash Point was: `{crash_point:.2f}x`")
            else:
                # crashed
                crash_mult_display = max(multiplier, crash_point)

                result_desc = (
                    f"💥 **CRASHED!**\n\n"
                    f"📉 Crash Point: `{crash_mult_display:.2f}x`\n"
                    f"❌ You lost your bet of `{bet:,}` {CURRENCY_EMOJI}.\n"
                    f"📈 ROI: `-100.0%`")

            # Update streaks
            streak = self.user_streaks.get(ctx.author.id, {
                "win": 0,
                "loss": 0
            })
            if win:
                streak["win"] += 1
                streak["loss"] = 0
            else:
                streak["loss"] += 1
                streak["win"] = 0
            self.user_streaks[ctx.author.id] = streak

            # Track big wins for anti-lucky spam
            big_win = win and (cashout_mult is not None
                               and cashout_mult >= 3.0)
            self.recent_big_wins.append(big_win)

            # Update global stats for RTP
            self.global_stats["games"] += 1
            self.global_stats["bet_total"] += bet
            if win:
                self.global_stats["paid_out"] += win_amount

            # RTP info (for footer)
            bet_total = self.global_stats["bet_total"]
            paid_out = self.global_stats["paid_out"]
            actual_rtp = (paid_out / bet_total) if bet_total > 0 else 0.0

            # Final embed
            embed.title = "🚀 AYO Crash – Result"
            embed.description = (
                f"👤 Player: {ctx.author.mention}\n"
                f"🎯 Bet: `{bet:,}` {CURRENCY_EMOJI}\n\n"
                f"{result_desc}\n"
                f"📉 Loss Streak: `{streak['loss']}` • 🏆 Win Streak: `{streak['win']}`"
            )
            embed.set_footer(
                text=
                f"AYO Crash • RTP: {actual_rtp:.1%} (Target: {self.target_rtp:.1%})",
                icon_url=ctx.author.display_avatar.url,
            )

            await msg.edit(embed=embed, view=view)

            # LOGS / STATS to games log channel
            try:
                if win and cashout_mult:
                    stats_text = (f"Result: CASHED OUT\n"
                                  f"Bet: {bet:,}\n"
                                  f"Cashout: {cashout_mult:.2f}x\n"
                                  f"Crash: {crash_point:.2f}x\n"
                                  f"ROI: +{roi_percent:.1f}%")
                else:
                    stats_text = (f"Result: CRASHED\n"
                                  f"Bet: {bet:,}\n"
                                  f"Crash: {crash_point:.2f}x")

                log_embed = make_embed(
                    title="🎮 Crash Game",
                    description=(
                        f"Player: {ctx.author} (`{ctx.author.id}`)\n"
                        f"Guild: {ctx.guild.name if ctx.guild else 'DM'}\n\n"
                        f"{stats_text}"),
                )
                await send_log(self.bot, ctx.guild, "games", log_embed)
            except Exception:
                pass

        finally:
            self.active.discard(ctx.author.id)

    # ======================================
    # INTERNAL HELPERS
    # ======================================

    def _generate_crash_point(self, user_id: int, bet: int) -> float:
        """
        Custom distribution + streak protector + anti-lucky + RTP adjust.
        """
        r = random.random()

        # --- Base distribution (tumhari requirement) ---

        # Very rare instant crash ~1.1
        if r < 0.03:
            base = random.uniform(1.10, 1.20)
        # Most common 1.2 - 1.6
        elif r < 0.58:  # +55%
            base = random.uniform(1.20, 1.60)
        # Medium wins 1.6 - 3.0
        elif r < 0.78:  # +20%
            base = random.uniform(1.60, 3.00)
        # High range 3 - 20x (sometimes goes high)
        elif r < 0.95:  # +17%
            base = random.uniform(3.0, 20.0)
        # Ultra rare jackpots 20x - 100x (1 in 20 games)
        else:
            base = random.uniform(20.0, 100.0)

        # --- Streak protector (user based) ---
        streak = self.user_streaks.get(user_id, {"win": 0, "loss": 0})
        loss_streak = streak["loss"]

        # Agar banda bar bar haar raha ho to min multiplier thora safe
        if loss_streak >= 3:
            base = max(base, 1.60)
        if loss_streak >= 5:
            base = max(base, 2.00)

        # --- Anti-lucky spam (global big wins) ---
        if len(self.recent_big_wins) > 10:
            big_win_rate = sum(1 for x in self.recent_big_wins if x) / len(
                self.recent_big_wins)
        else:
            big_win_rate = 0.0

        # Agar recent games mein bohat zyada 3x+ wins aaye hon
        if big_win_rate > 0.35 and base > 3.0:
            # Cap karo 3x - 8x range mein
            base = min(base, random.uniform(3.0, 8.0))

        # --- RTP Adjust (global) ---
        stats = self.global_stats
        bet_total = stats["bet_total"]
        paid_out = stats["paid_out"]

        if bet_total > 0:
            actual_rtp = paid_out / bet_total
            target = self.target_rtp

            # 5% ka buffer
            if actual_rtp < target - 0.05:
                # Players ko thoda buff (house bohat zyada jeet raha)
                base *= 1.15
            elif actual_rtp > target + 0.05:
                # House ko buff (players bohat jeet rahe)
                base *= 0.85

        # Final clamp
        base = max(1.10, min(base, 100.0))
        return round(base, 2)

    def _next_multiplier(self, current: float) -> float:
        """
        Smooth curve: start slow, then speed up.
        """
        if current < 2:
            step = random.uniform(0.05, 0.15)
        elif current < 5:
            step = random.uniform(0.10, 0.25)
        else:
            step = random.uniform(0.20, 0.40)
        return current + step


async def setup(bot):
    await bot.add_cog(Crash(bot))

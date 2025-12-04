# cogs/global_crash.py

import os
import json
import random
import asyncio
import time

import discord
from discord.ext import commands

from utils import db
from utils.common import make_embed, send_log

CURRENCY_EMOJI = "💰"
MAX_BET = 250_000

DATA_DIR = "data"
GLOBAL_CRASH_FILE = os.path.join(DATA_DIR, "global_crash.json")

# Minimum multiplier jahan se cashout allowed hoga
MIN_CASHOUT_MULT = 1.20


def _load_config():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
    if not os.path.exists(GLOBAL_CRASH_FILE):
        return {}
    try:
        with open(GLOBAL_CRASH_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_config(cfg: dict):
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
    try:
        with open(GLOBAL_CRASH_FILE, "w") as f:
            json.dump(cfg, f, indent=4)
    except Exception:
        pass


class GlobalCrashBetView(discord.ui.View):
    """
    Persistent view with bet buttons + STOP.
    """

    def __init__(self, cog, *, timeout=None):
        super().__init__(timeout=timeout)
        self.cog = cog

    async def _place_bet(self, interaction: discord.Interaction, amount: int):
        await self.cog.handle_bet_button(interaction, amount)

    # ========== BET BUTTONS ==========

    @discord.ui.button(
        label="1,000",
        style=discord.ButtonStyle.secondary,
        emoji="💸",
        custom_id="ayo_global_crash_bet_1k",
    )
    async def bet_1k(self, interaction: discord.Interaction,
                     button: discord.ui.Button):
        await self._place_bet(interaction, 1_000)

    @discord.ui.button(
        label="100,000",
        style=discord.ButtonStyle.secondary,
        emoji="💸",
        custom_id="ayo_global_crash_bet_100k",
    )
    async def bet_100k(self, interaction: discord.Interaction,
                       button: discord.ui.Button):
        await self._place_bet(interaction, 100_000)

    @discord.ui.button(
        label="250,000",
        style=discord.ButtonStyle.secondary,
        emoji="💸",
        custom_id="ayo_global_crash_bet_250k",
    )
    async def bet_250k(self, interaction: discord.Interaction,
                       button: discord.ui.Button):
        await self._place_bet(interaction, 250_000)

    # ========== STOP BUTTON ==========

    @discord.ui.button(
        label="STOP (Cashout)",
        style=discord.ButtonStyle.danger,
        emoji="⏹️",
        custom_id="ayo_global_crash_stop",
    )
    async def stop_btn(self, interaction: discord.Interaction,
                       button: discord.ui.Button):
        await self.cog.handle_stop_button(interaction)


class GlobalCrash(commands.Cog):
    """
    Global crash game (event-driven).
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = _load_config()
        self.channel_id: int | None = self.config.get("channel_id")
        self.message_id: int | None = self.config.get("message_id")
        self.main_message: discord.Message | None = None

        # phases: "idle", "cooldown", "running"
        self.phase: str = "idle"

        # cooldown phase bets: user_id -> bet amount
        self.bets: dict[int, int] = {}
        self.bets_lock = asyncio.Lock()

        # running round data
        self.current_round: dict[int, dict] = {}
        self.round_lock = asyncio.Lock()

        # crash round info
        self.current_multiplier: float = 1.0
        self.crash_point: float = 1.0

        # last 3 crash points
        self.last_crashes: list[float] = self.config.get("last_crashes", [])

        # pause flag
        self.paused: bool = self.config.get("paused", False)

        # betting window task
        self._window_task: asyncio.Task | None = None

        # adaptive rate-limit throttle
        self._min_edit_gap: float = 1.0
        self._last_edit_ts: float = 0.0
        self._pending_embed: discord.Embed | None = None
        self._flush_task: asyncio.Task | None = None

        # persistent view
        self.bet_view = GlobalCrashBetView(self, timeout=None)

    async def cog_load(self):
        self.bot.add_view(self.bet_view)

        if self.channel_id:
            channel = self.bot.get_channel(self.channel_id)
            if isinstance(channel, discord.TextChannel):
                await self.ensure_main_message(channel)
                await self.update_main_embed(
                    status=
                    "Waiting for someone to place a bet to start the next round.",
                    show_multiplier=False,
                    force=True,
                )

    # ------------------ Owner commands ------------------

    @commands.command(name="ayocrashchannelset")
    @commands.is_owner()
    async def set_crash_channel(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel | None = None,
    ):
        if channel is None:
            channel = ctx.channel

        self.channel_id = channel.id
        self.message_id = None
        self.main_message = None
        self.config["channel_id"] = channel.id
        self.config["message_id"] = None
        _save_config(self.config)

        await self.ensure_main_message(channel)
        await self.update_main_embed(
            status=
            "Waiting for someone to place a bet to start the next round.",
            show_multiplier=False,
            force=True,
        )

        await ctx.send(f"✅ Global crash channel set to {channel.mention}.")

    @commands.command(name="ayocrashpause")
    @commands.is_owner()
    async def pause_crash(self, ctx: commands.Context):
        self.paused = True
        self.config["paused"] = True
        _save_config(self.config)
        await self.update_main_embed(
            status="⏸️ Global Crash is currently **paused** by the owner.",
            show_multiplier=False,
            force=True,
        )
        await ctx.send("⏸️ Global Crash has been **paused** by the owner.")

    @commands.command(name="ayocrashresume")
    @commands.is_owner()
    async def resume_crash(self, ctx: commands.Context):
        self.paused = False
        self.config["paused"] = False
        _save_config(self.config)
        await self.update_main_embed(
            status=
            "Waiting for someone to place a bet to start the next round.",
            show_multiplier=False,
            force=True,
        )
        await ctx.send("▶️ Global Crash has been **resumed**.")

    # ------------------ Auto-delete extra messages ------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not self.channel_id:
            return
        if message.channel.id != self.channel_id:
            return
        if self.message_id and message.id == self.message_id:
            return
        await asyncio.sleep(7)
        try:
            if self.message_id and message.id == self.message_id:
                return
            await message.delete()
        except Exception:
            pass

    # ------------------ Helpers ------------------

    async def ensure_main_message(self, channel: discord.TextChannel):
        if self.main_message is None and self.message_id:
            try:
                self.main_message = await channel.fetch_message(self.message_id
                                                                )
            except Exception:
                self.main_message = None

        if self.main_message is None:
            embed = make_embed(
                title="🚀 AYO Global Crash",
                description=
                ("Waiting for someone to place a bet to start the next round.\n\n"
                 "Use the buttons below to place your bet.\n"
                 "This channel is reserved for the global crash game."),
            )
            try:
                msg = await channel.send(embed=embed, view=self.bet_view)
            except Exception:
                return
            self.main_message = msg
            self.message_id = msg.id
            self.config["message_id"] = msg.id
            _save_config(self.config)

    async def _edit_main_message(self, embed: discord.Embed, *, force: bool):
        if not self.main_message:
            return

        now = time.monotonic()

        if force:
            self._pending_embed = None
            try:
                await self.main_message.edit(embed=embed, view=self.bet_view)
            except discord.HTTPException as e:
                if e.status == 429:
                    self._min_edit_gap = min(self._min_edit_gap * 2.0, 10.0)
            except Exception:
                pass
            else:
                self._last_edit_ts = now
                self._min_edit_gap = max(self._min_edit_gap * 0.9, 1.0)
            return

        gap = now - self._last_edit_ts
        if gap >= self._min_edit_gap and self._flush_task is None:
            try:
                await self.main_message.edit(embed=embed, view=self.bet_view)
            except discord.HTTPException as e:
                if e.status == 429:
                    self._min_edit_gap = min(self._min_edit_gap * 2.0, 10.0)
            except Exception:
                pass
            else:
                self._last_edit_ts = now
                self._min_edit_gap = max(self._min_edit_gap * 0.9, 1.0)
            return

        self._pending_embed = embed
        if self._flush_task is None:
            self._flush_task = self.bot.loop.create_task(self._flush_pending())

    async def _flush_pending(self):
        try:
            await asyncio.sleep(self._min_edit_gap)
            if not self.main_message:
                return
            if not self._pending_embed:
                return
            embed = self._pending_embed
            self._pending_embed = None
            now = time.monotonic()
            try:
                await self.main_message.edit(embed=embed, view=self.bet_view)
            except discord.HTTPException as e:
                if e.status == 429:
                    self._min_edit_gap = min(self._min_edit_gap * 2.0, 10.0)
            except Exception:
                pass
            else:
                self._last_edit_ts = now
                self._min_edit_gap = max(self._min_edit_gap * 0.9, 1.0)
        finally:
            self._flush_task = None

    async def update_main_embed(
        self,
        status: str,
        show_multiplier: bool = False,
        multiplier: float | None = None,
        crashed: bool = False,
        *,
        force: bool = False,
    ):
        if not self.main_message:
            return

        if self.last_crashes:
            last_str = " | ".join(f"x{v:.2f}" for v in self.last_crashes[-3:])
        else:
            last_str = "no data"

        lines: list[str] = []

        current_mult_for_display = (multiplier if show_multiplier
                                    and multiplier is not None else
                                    self.current_multiplier)

        if self.phase == "cooldown":
            async with self.bets_lock:
                items = list(self.bets.items())
            if items:
                for user_id, amount in items[:15]:
                    user = self.bot.get_user(user_id)
                    name = user.mention if user else f"`{user_id}`"
                    lines.append(f"• {name} – `{amount:,}` {CURRENCY_EMOJI}")
            else:
                lines.append("No bets yet.")
        elif self.phase == "running":
            async with self.round_lock:
                items = list(self.current_round.items())
            if items:
                for user_id, info in items[:15]:
                    user_obj = self.bot.get_user(user_id)
                    name = user_obj.mention if user_obj else f"`{user_id}`"
                    bet = info["bet"]
                    status_flag = info["status"]

                    if status_flag == "cashed":
                        cm = info["cashout_mult"] or 1.0
                        win = info["win_amount"]
                        profit = win - bet
                        lines.append(
                            f"• {name} – CASHED at `x{cm:.2f}` → "
                            f"`{win:,}` ({'+' if profit >= 0 else ''}{profit:,}) {CURRENCY_EMOJI}"
                        )
                    elif status_flag == "lost":
                        lines.append(
                            f"• {name} – LOST, bet `{bet:,}` {CURRENCY_EMOJI}")
                    else:
                        potential = int(bet *
                                        max(1.0, current_mult_for_display))
                        lines.append(
                            f"• {name} – BET `{bet:,}` {CURRENCY_EMOJI} "
                            f"(potential now: `{potential:,}` {CURRENCY_EMOJI})"
                        )
            else:
                lines.append("No players this round.")
        else:
            lines.append("No bets yet. Place a bet to start the next round.")

        bets_text = "\n".join(lines)

        desc_parts = [
            f"📊 **Last crashes:** {last_str}\n",
            status,
            "\n\n💸 **Players / Bets (this round):**\n",
            bets_text,
        ]

        if show_multiplier and multiplier is not None:
            state = "💥 CRASHED" if crashed else "📈 Climbing"
            desc_parts.insert(1, f"{state} – **x{multiplier:.2f}**\n")

        embed = make_embed(
            title="🚀 AYO Global Crash",
            description="".join(desc_parts),
        )

        await self._edit_main_message(embed, force=force)

    # ------------------ Crash Logic ------------------

    def generate_crash_point(self) -> float:
        """
        More realistic / harsher distribution:
        - 1.01–1.20 : 20%
        - 1.20–2.00 : 55%
        - 2.00–10.0 : 20%
        - 10.0–100  : 5%
        """
        r = random.random()
        if r < 0.20:
            return round(random.uniform(1.01, 1.20), 2)
        elif r < 0.75:
            return round(random.uniform(1.20, 2.0), 2)
        elif r < 0.95:
            return round(random.uniform(2.0, 10.0), 2)
        else:
            return round(random.uniform(10.0, 100.0), 2)

    async def start_betting_window(self, channel: discord.TextChannel):
        self.phase = "cooldown"
        await self.update_main_embed(
            status=
            "🕒 Betting window open (~5s). Place your bets to join this round.",
            show_multiplier=False,
            force=True,
        )

        await asyncio.sleep(5)

        async with self.bets_lock:
            round_bets = dict(self.bets)
            self.bets = {}

        if not round_bets:
            self.phase = "idle"
            await self.update_main_embed(
                status=
                "❌ No bets placed. Waiting for someone to place a bet to start the next round.",
                show_multiplier=False,
                force=True,
            )
            self._window_task = None
            return

        async with self.round_lock:
            self.current_round = {}
            for uid, bet in round_bets.items():
                self.current_round[uid] = {
                    "bet": bet,
                    "status": "playing",
                    "cashout_mult": None,
                    "win_amount": 0,
                }

        self.phase = "running"
        try:
            await self.run_crash_round(channel)
        finally:
            self.phase = "idle"
            self._window_task = None

    async def run_crash_round(self, channel: discord.TextChannel):
        self.current_multiplier = 1.0
        self.crash_point = self.generate_crash_point()

        try:
            await self.update_main_embed(
                status="🚀 Round started! Plane taking off...",
                show_multiplier=True,
                multiplier=self.current_multiplier,
                force=True,
            )
            await asyncio.sleep(0.5)

            ended_because_all_cashed = False
            last_update_mult = self.current_multiplier

            while self.current_multiplier < self.crash_point:
                await asyncio.sleep(0.6)

                async with self.round_lock:
                    active_left = any(info["status"] == "playing"
                                      for info in self.current_round.values())
                if not active_left:
                    ended_because_all_cashed = True
                    break

                cur = self.current_multiplier
                if cur < 1.5:
                    step = random.uniform(0.02, 0.06)
                elif cur < 3.0:
                    step = random.uniform(0.03, 0.08)
                elif cur < 10.0:
                    step = random.uniform(0.05, 0.12)
                else:
                    step = random.uniform(0.12, 0.30)

                self.current_multiplier += step

                if abs(self.current_multiplier - last_update_mult) >= 0.08:
                    await self.update_main_embed(
                        status="",
                        show_multiplier=True,
                        multiplier=self.current_multiplier,
                    )
                    last_update_mult = self.current_multiplier

            if ended_because_all_cashed:
                final_mult = self.crash_point
                status_line = (
                    f"✅ All players cashed out!\n"
                    f"💥 Plane would have crashed at **x{self.crash_point:.2f}**."
                )
            else:
                final_mult = max(self.current_multiplier, self.crash_point)
                status_line = "💥 The plane has crashed!"

            await self.update_main_embed(
                status=status_line,
                show_multiplier=True,
                multiplier=final_mult,
                crashed=True,
                force=True,
            )

            total_bet = 0
            total_payout = 0
            lines: list[str] = []

            async with self.round_lock:
                for user_id, info in self.current_round.items():
                    bet = info["bet"]
                    total_bet += bet

                    if info["status"] == "cashed":
                        win = info["win_amount"]
                        profit = win - bet
                        total_payout += win
                        lines.append(
                            f"✅ <@{user_id}> CASHED at `x{info['cashout_mult']:.2f}` → "
                            f"Win: `{win:,}` ({'+' if profit >= 0 else ''}{profit:,}) {CURRENCY_EMOJI}"
                        )
                    elif info["status"] == "lost":
                        profit = -bet
                        lines.append(
                            f"❌ <@{user_id}> CRASHED – Bet: `{bet:,}` ({profit:,} {CURRENCY_EMOJI})"
                        )
                    else:
                        info["status"] = "lost"
                        profit = -bet
                        lines.append(
                            f"❌ <@{user_id}> CRASHED – Bet: `{bet:,}` ({profit:,} {CURRENCY_EMOJI})"
                        )

            if not lines:
                result_text = "No players this round."
            else:
                result_text = "\n".join(lines)

            try:
                await channel.send(embed=make_embed(
                    title="🏁 Global Crash Results",
                    description=
                    (f"📉 Final Multiplier (crash): **x{self.crash_point:.2f}**\n"
                     f"💰 Total Bet: `{total_bet:,}` {CURRENCY_EMOJI}\n"
                     f"💵 Total Paid Out (cashouts): `{total_payout:,}` {CURRENCY_EMOJI}\n\n"
                     f"{result_text}"),
                ))
            except Exception:
                pass

            try:
                crash_val = round(float(self.crash_point), 2)
            except Exception:
                crash_val = self.crash_point

            self.last_crashes.append(crash_val)
            self.last_crashes = self.last_crashes[-3:]
            self.config["last_crashes"] = self.last_crashes
            _save_config(self.config)

            db.save_users()

            try:
                guild = channel.guild
                desc = (
                    f"Channel: {channel.mention} ({channel.id})\n"
                    f"Crash Point: x{self.crash_point:.2f}\n"
                    f"Total Bet: {total_bet:,} {CURRENCY_EMOJI}\n"
                    f"Total Payout: {total_payout:,} {CURRENCY_EMOJI}\n"
                    f"Players: {len(self.current_round)}\n"
                    f"Ended because all cashed: {ended_because_all_cashed}")
                log_embed = make_embed(
                    title="Global Crash Round",
                    description=desc,
                )
                await send_log(self.bot, guild, "games", log_embed)
            except Exception:
                pass

        finally:
            async with self.round_lock:
                self.current_round = {}

            self.phase = "idle"
            try:
                await self.update_main_embed(
                    status=
                    "Waiting for someone to place a bet to start the next round.",
                    show_multiplier=False,
                    force=True,
                )
            except Exception:
                pass

    # ------------------ Button handlers ------------------

    async def handle_bet_button(
        self,
        interaction: discord.Interaction,
        amount: int,
    ):
        user = interaction.user

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                "❌ This can only be used in a server channel.",
                ephemeral=True,
            )
            return

        if not self.channel_id or interaction.channel.id != self.channel_id:
            await interaction.response.send_message(
                "❌ This is not the configured global crash channel.",
                ephemeral=True,
            )
            return

        if self.paused:
            await interaction.response.send_message(
                "⏸️ Global Crash is currently **paused**. No new bets allowed.",
                ephemeral=True,
            )
            return

        if not db.are_games_enabled():
            await interaction.response.send_message(
                "❌ Games are currently disabled.",
                ephemeral=True,
            )
            return

        if self.phase == "running":
            await interaction.response.send_message(
                "⏳ A round is already running. Wait for it to finish.",
                ephemeral=True,
            )
            return

        profile = db.get_profile(user.id)
        balance = profile["cash"]

        async with self.bets_lock:
            current = self.bets.get(user.id, 0)
            new_total = current + amount

            if new_total > MAX_BET:
                await interaction.response.send_message(
                    f"❌ Max bet per round is `{MAX_BET:,}` {CURRENCY_EMOJI}.\n"
                    f"Your total this round would be `{new_total:,}`.",
                    ephemeral=True,
                )
                return

            if balance < amount:
                await interaction.response.send_message(
                    "❌ You don't have enough cash for that bet.",
                    ephemeral=True,
                )
                return

            profile["cash"] -= amount
            self.bets[user.id] = new_total

        db.save_users()

        # ✅ SUCCESS PATH:
        # bas interaction ko ACK karo, koi text-msg nahi
        try:
            await interaction.response.defer(ephemeral=True, thinking=False)
        except Exception:
            pass

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            return

        await self.ensure_main_message(channel)

        if self.phase == "idle":
            if self._window_task is None or self._window_task.done():
                self._window_task = self.bot.loop.create_task(
                    self.start_betting_window(channel))

        await self.update_main_embed(
            status=
            "🕒 Betting window open (~5s). Place your bets to join this round.",
            show_multiplier=False,
        )

    async def handle_stop_button(self, interaction: discord.Interaction):
        user = interaction.user

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                "❌ This can only be used in a server channel.",
                ephemeral=True,
            )
            return

        if not self.channel_id or interaction.channel.id != self.channel_id:
            await interaction.response.send_message(
                "❌ This is not the configured global crash channel.",
                ephemeral=True,
            )
            return

        if self.phase != "running":
            await interaction.response.send_message(
                "⏳ There is no active flying round right now.",
                ephemeral=True,
            )
            return

        if self.current_multiplier < MIN_CASHOUT_MULT:
            await interaction.response.send_message(
                f"⚠️ Too early to cashout. Minimum cashout is **x{MIN_CASHOUT_MULT:.2f}**.",
                ephemeral=True,
            )
            return

        async with self.round_lock:
            info = self.current_round.get(user.id)

            if not info:
                await interaction.response.send_message(
                    "❌ You don't have an active bet in this round.",
                    ephemeral=True,
                )
                return

            if info["status"] == "cashed":
                cm = info.get("cashout_mult", self.current_multiplier)
                await interaction.response.send_message(
                    f"⚠️ You already cashed out at `x{cm:.2f}`.",
                    ephemeral=True,
                )
                return

            if info["status"] == "lost":
                await interaction.response.send_message(
                    "❌ This round is already finished for you.",
                    ephemeral=True,
                )
                return

            if self.current_multiplier >= self.crash_point:
                info["status"] = "lost"
                await interaction.response.send_message(
                    "💥 Too late! The plane already crashed.",
                    ephemeral=True,
                )
                return

            bet = info["bet"]
            cashout_mult = self.current_multiplier
            win_amount = int(bet * cashout_mult)

            info["status"] = "cashed"
            info["cashout_mult"] = cashout_mult
            info["win_amount"] = win_amount

        profile = db.get_profile(user.id)
        profile["cash"] += win_amount
        db.save_users()

        profit = win_amount - bet

        await interaction.response.send_message(
            f"✅ You CASHED OUT at `x{cashout_mult:.2f}`!\n"
            f"💰 Bet: `{bet:,}` {CURRENCY_EMOJI}\n"
            f"🏦 Win: `{win_amount:,}` {CURRENCY_EMOJI}\n"
            f"📊 Profit: `{'+' if profit >= 0 else ''}{profit:,}` {CURRENCY_EMOJI}",
            ephemeral=True,
        )

        await self.update_main_embed(
            status="🚀 Round running... players are cashing out!",
            show_multiplier=True,
            multiplier=self.current_multiplier,
        )


async def setup(bot):
    cog = GlobalCrash(bot)
    await bot.add_cog(cog)

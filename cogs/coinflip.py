# cogs/coinflip.py

import random
import asyncio
import discord
from discord.ext import commands

from utils import db
from utils.common import make_embed, send_log

CURRENCY_EMOJI = "💰"
MAX_BET = 250_000


class CoinflipChallengeView(discord.ui.View):
  """
    Pending challenge view – Accept / Decline buttons
    """

  def __init__(
      self,
      cog,
      ctx: commands.Context,
      challenger: discord.Member,
      opponent: discord.Member,
      bet: int,
      *,
      timeout: float = 60.0,
  ):
    super().__init__(timeout=timeout)
    self.cog = cog
    self.ctx = ctx
    self.challenger = challenger
    self.opponent = opponent
    self.bet = bet
    self.resolved = False
    self.message: discord.Message | None = None

  async def on_timeout(self):
    try:
      if self.resolved or self.message is None:
        return

      for child in self.children:
        child.disabled = True

      embed = self.message.embeds[0]
      embed.description += "\n\n⏰ **Challenge timed out.**"
      await self.message.edit(embed=embed, view=self)

      # FREE PLAYERS ON TIMEOUT
      if self.challenger.id in self.cog.active_players:
        self.cog.active_players.remove(self.challenger.id)
      if self.opponent.id in self.cog.active_players:
        self.cog.active_players.remove(self.opponent.id)
    except Exception:
      pass

  @discord.ui.button(label="Accept",
                     style=discord.ButtonStyle.success,
                     emoji="✅")
  async def accept_button(
      self,
      interaction: discord.Interaction,
      button: discord.ui.Button,
  ):
    if interaction.user.id != self.opponent.id:
      await interaction.response.send_message(
          "⚠️ Only the challenged user can accept this coinflip.",
          ephemeral=True,
      )
      return

    if self.resolved:
      await interaction.response.send_message(
          "⚠️ This coinflip is already resolved.",
          ephemeral=True,
      )
      return

    self.resolved = True
    await interaction.response.defer()

    await self.cog._start_coinflip_game(self, accepted=True)

  @discord.ui.button(label="Decline",
                     style=discord.ButtonStyle.danger,
                     emoji="❌")
  async def decline_button(
      self,
      interaction: discord.Interaction,
      button: discord.ui.Button,
  ):
    if interaction.user.id != self.opponent.id:
      await interaction.response.send_message(
          "⚠️ Only the challenged user can decline this coinflip.",
          ephemeral=True,
      )
      return

    if self.resolved:
      await interaction.response.send_message(
          "⚠️ This coinflip is already resolved.",
          ephemeral=True,
      )
      return

    self.resolved = True
    await interaction.response.defer()

    for child in self.children:
      child.disabled = True

    if self.message:
      try:
        embed = self.message.embeds[0]
        embed.description += (
            f"\n\n❌ **{self.opponent.mention} declined the challenge.**")
        await self.message.edit(embed=embed, view=self)
      except Exception:
        pass

    # FREE PLAYERS ON DECLINE
    if self.challenger.id in self.cog.active_players:
      self.cog.active_players.remove(self.challenger.id)
    if self.opponent.id in self.cog.active_players:
      self.cog.active_players.remove(self.opponent.id)


class DoubleOrNothingView(discord.ui.View):
  """
    After a win -> winner can either TAKE WIN or go DOUBLE OR NOTHING vs the house.
    """

  def __init__(
      self,
      cog,
      ctx: commands.Context,
      winner: discord.Member,
      loser: discord.Member,
      pot: int,
      *,
      timeout: float = 30.0,
  ):
    super().__init__(timeout=timeout)
    self.cog = cog
    self.ctx = ctx
    self.winner = winner
    self.loser = loser
    self.pot = pot
    self.done = False
    self.message: discord.Message | None = None

  async def on_timeout(self):
    try:
      if self.done or self.message is None:
        return

      self.done = True
      for child in self.children:
        child.disabled = True

      embed = self.message.embeds[0]
      embed.description += "\n\n⏰ Time out – win locked in automatically."
      await self.message.edit(embed=embed, view=self)

      await self.cog._finish_coinflip(self.winner, self.loser)
    except Exception:
      pass

  @discord.ui.button(label="Take Win",
                     style=discord.ButtonStyle.success,
                     emoji="✅")
  async def take_win_button(
      self,
      interaction: discord.Interaction,
      button: discord.ui.Button,
  ):
    if interaction.user.id != self.winner.id:
      await interaction.response.send_message(
          "⚠️ Only the winner can choose this.",
          ephemeral=True,
      )
      return

    if self.done:
      await interaction.response.defer()
      return

    self.done = True
    await interaction.response.defer()

    for child in self.children:
      child.disabled = True

    if self.message:
      try:
        embed = self.message.embeds[0]
        embed.description += "\n\n✅ **Win locked in. Enjoy your earnings!**"
        await self.message.edit(embed=embed, view=self)
      except Exception:
        pass

    await self.cog._finish_coinflip(self.winner, self.loser)

  @discord.ui.button(label="Double or Nothing",
                     style=discord.ButtonStyle.danger,
                     emoji="🎲")
  async def double_or_nothing_button(
      self,
      interaction: discord.Interaction,
      button: discord.ui.Button,
  ):
    if interaction.user.id != self.winner.id:
      await interaction.response.send_message(
          "⚠️ Only the winner can choose Double or Nothing.",
          ephemeral=True,
      )
      return

    if self.done:
      await interaction.response.defer()
      return

    self.done = True
    await interaction.response.defer()

    await self.cog._handle_double_or_nothing(self)


class Coinflip(commands.Cog):
  """
    AYO Coinflip PvP – Option A + Double-or-Nothing mix
    """

  def __init__(self, bot):
    self.bot = bot
    self.active_players: set[int] = set()
    self.coinflip_games = {}  # Track active coinflip games

  # ======================================
  # MAIN COMMAND
  # ======================================

  @commands.command(name="pcf", aliases=["pvpcoinflip", "ayocf"])
  async def coinflip_command(
      self,
      ctx: commands.Context,
      amount: str,
      opponent: discord.Member,
  ):
    """
        AYO Coinflip PvP
        Usage:
            ayo pcf 5000 @user
            ayo ayocf 10000 @user
        """
    try:
      if not db.are_games_enabled():
        await ctx.send("❌ Games are currently disabled.")
        return

      if opponent.bot:
        await ctx.send("❌ You cannot challenge a bot.")
        return

      if opponent.id == ctx.author.id:
        await ctx.send("❌ You cannot challenge yourself.")
        return

      if ctx.author.id in self.active_players:
        await ctx.send("❌ You already have an active coinflip.")
        return
      if opponent.id in self.active_players:
        await ctx.send("❌ That user is currently busy in another coinflip.")
        return

      raw = amount.lower()

      profile_challenger = db.get_profile(ctx.author.id)
      balance_challenger = profile_challenger["cash"]

      if raw == "all":
        if balance_challenger <= 0:
          await ctx.send("❌ You don't have any cash to bet.")
          return
        bet = min(balance_challenger, MAX_BET)
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
      if bet > balance_challenger:
        await ctx.send("❌ You don't have enough cash.")
        return

      # Check opponent's balance
      profile_opponent = db.get_profile(opponent.id)
      if bet > profile_opponent["cash"]:
        await ctx.send(
            f"❌ {opponent.mention} doesn't have enough cash for this bet.")
        return

      self.active_players.add(ctx.author.id)
      self.active_players.add(opponent.id)

      embed = make_embed(
          title="🪙 AYO Coinflip Challenge",
          description=
          (f"👤 **Challenger:** {ctx.author.mention}\n"
           f"👤 **Opponent:** {opponent.mention}\n\n"
           f"🎯 **Bet:** `{bet:,}` {CURRENCY_EMOJI} *(each)*\n"
           f"🏦 **Total Pot:** `{bet*2:,}` {CURRENCY_EMOJI}\n\n"
           f"{opponent.mention}, press **Accept** to start or **Decline** to cancel.\n"
           f"⏰ This challenge expires in 60 seconds."),
      )
      view = CoinflipChallengeView(
          self,
          ctx,
          ctx.author,
          opponent,
          bet,
          timeout=60.0,
      )
      msg = await ctx.send(embed=embed, view=view)
      view.message = msg

    except discord.Forbidden:
      await ctx.send(
          "❌ I don't have permission to send messages in this channel.")
      if ctx.author.id in self.active_players:
        self.active_players.remove(ctx.author.id)
      if opponent.id in self.active_players:
        self.active_players.remove(opponent.id)
    except Exception as e:
      print(f"Error in coinflip command: {e}")
      await ctx.send("❌ An error occurred while creating the coinflip.")
      if ctx.author.id in self.active_players:
        self.active_players.remove(ctx.author.id)
      if opponent.id in self.active_players:
        self.active_players.remove(opponent.id)

  # ======================================
  # GAME FLOW HELPERS
  # ======================================

  async def _start_coinflip_game(
      self,
      view: CoinflipChallengeView,
      accepted: bool,
  ):
    ctx = view.ctx
    challenger = view.challenger
    opponent = view.opponent
    bet = view.bet
    msg = view.message

    try:
      for child in view.children:
        child.disabled = True

      if not accepted:
        await msg.edit(view=view)
        if challenger.id in self.active_players:
          self.active_players.remove(challenger.id)
        if opponent.id in self.active_players:
          self.active_players.remove(opponent.id)
        return

      profile_c = db.get_profile(challenger.id)
      profile_o = db.get_profile(opponent.id)

      # Double-check balances
      if profile_c["cash"] < bet or profile_o["cash"] < bet:
        reason = []
        if profile_c["cash"] < bet:
          reason.append(f"{challenger.mention} does not have enough cash.")
        if profile_o["cash"] < bet:
          reason.append(f"{opponent.mention} does not have enough cash.")

        embed = make_embed(
            title="🪙 AYO Coinflip Cancelled",
            description="❌ Challenge cancelled:\n" + "\n".join(reason),
        )
        await msg.edit(embed=embed, view=view)

        if challenger.id in self.active_players:
          self.active_players.remove(challenger.id)
        if opponent.id in self.active_players:
          self.active_players.remove(opponent.id)
        return

      # Deduct bets
      profile_c["cash"] -= bet
      profile_o["cash"] -= bet
      db.save_users()

      pot = bet * 2

      # Update message to show flipping
      await msg.edit(
          embed=make_embed(
              title="🪙 AYO Coinflip – Flipping...",
              description=(f"👤 Challenger: {challenger.mention}\n"
                           f"👤 Opponent: {opponent.mention}\n\n"
                           f"🎯 Bet Each: `{bet:,}` {CURRENCY_EMOJI}\n"
                           f"🏦 Total Pot: `{pot:,}` {CURRENCY_EMOJI}\n\n"
                           f"🌀 **Flipping the coin...**"),
          ),
          view=None,
      )

      # Add suspense
      async with ctx.typing():
        await asyncio.sleep(1.5)

      # Determine winner
      side = random.choice(["HEADS", "TAILS"])
      if side == "HEADS":
        winner = challenger
        loser = opponent
      else:
        winner = opponent
        loser = challenger

      # Award pot to winner
      winner_profile = db.get_profile(winner.id)
      winner_profile["cash"] += pot
      db.save_users()

      # Create result embed
      result_desc = (f"🎲 **Side:** `{side}`\n"
                     f"🏆 **Winner:** {winner.mention}\n\n"
                     f"💰 Bet Each: `{bet:,}` {CURRENCY_EMOJI}\n"
                     f"🏦 Total Pot Won: `{pot:,}` {CURRENCY_EMOJI}\n\n"
                     f"{winner.mention}, choose your action:\n"
                     f"• ✅ **Take Win** - Keep your winnings\n"
                     f"• 🎲 **Double or Nothing** - Risk it all for double!")

      embed = make_embed(
          title="🪙 AYO Coinflip – Result",
          description=result_desc,
      )

      # Create Double or Nothing view
      dn_view = DoubleOrNothingView(
          self,
          ctx,
          winner,
          loser,
          pot,
          timeout=30.0,
      )
      result_msg = await msg.edit(embed=embed, view=dn_view)
      dn_view.message = result_msg

      # Store game info for double or nothing
      self.coinflip_games[winner.id] = {
          "message": msg,
          "winner": winner,
          "loser": loser,
          "pot": pot,
          "original_pot": pot
      }

      # Log the game
      try:
        log_embed = make_embed(
            title="🎮 Coinflip Game",
            description=(f"Challenger: {challenger} (`{challenger.id}`)\n"
                         f"Opponent: {opponent} (`{opponent.id}`)\n"
                         f"Bet: {bet:,} {CURRENCY_EMOJI} each\n"
                         f"Pot: {pot:,} {CURRENCY_EMOJI}\n"
                         f"Side: {side}\n"
                         f"Winner: {winner} (`{winner.id}`)\n"
                         f"(Double or Nothing pending...)"),
        )
        await send_log(self.bot, ctx.guild, "games", log_embed)
      except Exception:
        pass

    except Exception as e:
      print(f"Error in _start_coinflip_game: {e}")
      # Refund players on error
      profile_c = db.get_profile(challenger.id)
      profile_o = db.get_profile(opponent.id)
      profile_c["cash"] += bet
      profile_o["cash"] += bet
      db.save_users()

      if msg:
        try:
          await msg.edit(
              embed=make_embed(
                  title="🪙 AYO Coinflip – Error",
                  description="❌ An error occurred. Bets have been refunded.",
              ),
              view=None,
          )
        except Exception:
          pass

      if challenger.id in self.active_players:
        self.active_players.remove(challenger.id)
      if opponent.id in self.active_players:
        self.active_players.remove(opponent.id)

  async def _handle_double_or_nothing(self, view: DoubleOrNothingView):
    ctx = view.ctx
    winner = view.winner
    loser = view.loser
    pot = view.pot
    msg = view.message

    try:
      for child in view.children:
        child.disabled = True

      # Update message
      embed = msg.embeds[0]
      embed.description += ("\n\n🎲 **Double or Nothing chosen!**\n"
                            "🌀 Flipping again vs **AYO System**...")
      await msg.edit(embed=embed, view=view)

      # Add suspense
      async with ctx.typing():
        await asyncio.sleep(1.5)

      # Double or nothing flip
      result = random.choice(["WIN", "LOSE"])
      winner_profile = db.get_profile(winner.id)

      if result == "WIN":
        # Winner gets double the pot
        winner_profile["cash"] += pot
        db.save_users()

        embed.description += (
            f"\n\n🎉 **🎲 DOUBLE WIN! 🎲**\n"
            f"✅ You won the Double or Nothing!\n"
            f"💰 Extra Won: `+{pot:,}` {CURRENCY_EMOJI}\n"
            f"🏆 Total from Coinflip + D/N: `+{pot*2:,}` {CURRENCY_EMOJI}\n"
            f"💵 Your total winnings: `{pot*2:,}` {CURRENCY_EMOJI}")
      else:
        # Winner loses the original pot
        winner_profile["cash"] -= pot
        db.save_users()

        embed.description += (
            f"\n\n💥 **💸 DOUBLE LOSS! 💸**\n"
            f"❌ You lost the Double or Nothing!\n"
            f"📉 Lost original pot: `-{pot:,}` {CURRENCY_EMOJI}\n"
            f"😭 Final result from this coinflip: `0` {CURRENCY_EMOJI}\n"
            f"💡 Better luck next time!")

      embed.title = "🪙 AYO Coinflip – Double or Nothing Result"
      await msg.edit(embed=embed, view=view)

      await self._finish_coinflip(winner, loser)

      # Log double or nothing result
      try:
        log_embed = make_embed(
            title="🎮 Coinflip Double or Nothing",
            description=(f"Winner: {winner} (`{winner.id}`)\n"
                         f"Loser: {loser} (`{loser.id}`)\n"
                         f"Pot: {pot:,} {CURRENCY_EMOJI}\n"
                         f"Result: {result}"),
        )
        await send_log(self.bot, ctx.guild, "games", log_embed)
      except Exception:
        pass

    except Exception as e:
      print(f"Error in _handle_double_or_nothing: {e}")
      # Clean up on error
      if winner.id in self.coinflip_games:
        del self.coinflip_games[winner.id]
      await self._finish_coinflip(winner, loser)

  async def _finish_coinflip(
      self,
      winner: discord.Member,
      loser: discord.Member,
  ):
    """Clean up after a coinflip game."""
    try:
      # Remove from active players
      if winner.id in self.active_players:
        self.active_players.remove(winner.id)
      if loser.id in self.active_players:
        self.active_players.remove(loser.id)

      # Remove from coinflip games tracking
      if winner.id in self.coinflip_games:
        del self.coinflip_games[winner.id]
    except Exception as e:
      print(f"Error in _finish_coinflip: {e}")

  # ======================================
  # CLEANUP COMMANDS
  # ======================================

  @commands.command(name="coinflipclean", aliases=["cfclean"])
  @commands.is_owner()
  async def coinflip_cleanup(self, ctx: commands.Context):
    """Clean up stuck coinflip games (Owner only)."""
    try:
      count = len(self.active_players)
      self.active_players.clear()
      self.coinflip_games.clear()

      await ctx.send(f"✅ Cleaned up {count} stuck coinflip games.")
    except Exception as e:
      await ctx.send(f"❌ Error cleaning up: {e}")

  @commands.command(name="coinflipstats", aliases=["cfstats"])
  async def coinflip_stats(self, ctx: commands.Context):
    """Show current coinflip statistics."""
    try:
      embed = make_embed(
          title="📊 Coinflip Statistics",
          description=(
              f"👥 **Active Players:** {len(self.active_players)}\n"
              f"🎮 **Active Games:** {len(self.coinflip_games)}\n"
              f"💰 **Max Bet:** `{MAX_BET:,}` {CURRENCY_EMOJI}\n\n"
              f"Use `{ctx.prefix}pcf <amount> @user` to challenge someone!"),
      )
      await ctx.send(embed=embed)
    except Exception:
      pass


async def setup(bot):
  cog = Coinflip(bot)
  await bot.add_cog(cog)

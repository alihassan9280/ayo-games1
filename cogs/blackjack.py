import random
import asyncio

import discord
from discord.ext import commands

from utils import db
from utils.common import make_embed, send_log

CURRENCY_EMOJI = "💰"
MAX_BET = 250_000

# 1️⃣ = Stand, 2️⃣ = Hit, 3️⃣ = Double, 4️⃣ = Split, 5️⃣ = Insurance
EMOJI_ACTIONS = {
    "1️⃣": "stand",
    "2️⃣": "hit",
    "3️⃣": "double",
    "4️⃣": "split",
    "5️⃣": "insurance",
}

RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
VALUES = {
    "A": 11,
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
    "6": 6,
    "7": 7,
    "8": 8,
    "9": 9,
    "10": 10,
    "J": 10,
    "Q": 10,
    "K": 10,
}

HEADER_LINE = "**━━━━━━━━ AYO BLACKJACK ━━━━━━━━**"


def new_deck():
    deck = RANKS * 4
    random.shuffle(deck)
    return deck


def hand_value(hand):
    total = sum(VALUES[c] for c in hand)
    aces = hand.count("A")
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return total


def format_big_hand(hand, hide_first=False):
    """
    Cards always left -> right.
    If hide_first=True: SECOND card hidden, first visible.
    Dealer look: [ 7 ][ ❓ ]
    """
    parts = []
    for i, card in enumerate(hand):
        # hide SECOND card for dealer
        if hide_first and i == 1:
            parts.append("[ ❓ ]")
        else:
            parts.append(f"[ {card} ]")
    return " ".join(parts)


class Blackjack(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.active_games = set()

    # ================= MAIN COMMAND =================

    @commands.command(name="bj", aliases=["blackjack"])
    async def blackjack_command(self, ctx: commands.Context, amount: str):
        """
        ayobj 5000
        ayo bj 5000
        ayobj all
        """
        # games enabled?
        if not db.are_games_enabled():
            await ctx.send("❌ Games are currently disabled.")
            return

        # one active game per user
        if ctx.author.id in self.active_games:
            await ctx.send("❌ You already have an active blackjack game.")
            return

        profile = db.get_profile(ctx.author.id)
        balance = profile["cash"]

        # parse bet
        amt_raw = amount.lower()
        if amt_raw == "all":
            bet = min(balance, MAX_BET)
        else:
            if not amt_raw.isdigit():
                await ctx.send("❌ Bet must be a number or `all`.")
                return
            bet = int(amt_raw)

        if bet <= 0:
            await ctx.send("❌ Bet must be positive.")
            return
        if bet > MAX_BET:
            await ctx.send(f"❌ Max bet is `{MAX_BET:,}` {CURRENCY_EMOJI}.")
            return
        if bet > balance:
            await ctx.send("❌ You don't have enough cash for that bet.")
            return

        self.active_games.add(ctx.author.id)

        try:
            # take base bet
            profile["cash"] -= bet
            db.save_users()

            deck = new_deck()
            # first hand (we support split later)
            first_hand_cards = [deck.pop(), deck.pop()]
            # dealer: index 0 = OPEN, index 1 = HIDDEN
            dealer_cards = [deck.pop(), deck.pop()]

            # each hand dict: cards / bet / finished / busted / doubled
            hands = [{
                "cards": first_hand_cards,
                "bet": bet,
                "finished": False,
                "busted": False,
                "doubled": False,
            }]
            current_index = 0

            # insurance state
            insurance_bet = 0
            # dealer upcard = FIRST card (index 0)
            insurance_possible = dealer_cards[0] == "A"
            insurance_resolved = False

            # === helper: build status text ===
            def build_status(reveal_dealer=False, active_index=0):
                dealer_val = hand_value(
                    dealer_cards) if reveal_dealer else "??"
                dealer_line = (
                    f"🤵 **Dealer** (**{dealer_val}**): "
                    f"{format_big_hand(dealer_cards, hide_first=not reveal_dealer)}"
                )

                lines = [dealer_line, ""]
                for idx, h in enumerate(hands):
                    prefix = "👉 " if idx == active_index and not h[
                        "finished"] and not h["busted"] else "   "
                    tag = f"Hand {idx+1}"
                    val = hand_value(h["cards"])
                    cards_str = format_big_hand(h["cards"])
                    state = ""
                    if h["busted"]:
                        state = " **[BUST]**"
                    elif h["finished"]:
                        state = " **[STAND]**"
                    lines.append(
                        f"{prefix}🃏 **{tag}** (**{val}**): {cards_str}{state}")
                return "\n".join(lines)

            # ===== initial embed (BET CONFIRM) =====
            desc = (
                f"{HEADER_LINE}\n\n"
                f"💰 **Base Bet:** `{bet:,}` {CURRENCY_EMOJI}\n"
                f"🎲 **Total At Risk:** `{bet:,}` {CURRENCY_EMOJI}\n\n"
                f"{build_status(reveal_dealer=False, active_index=current_index)}\n\n"
                "React:\n"
                "1️⃣ Stand  2️⃣ Hit  3️⃣ Double")
            # insurance offer
            if insurance_possible:
                desc += "  5️⃣ Insurance (up to 50% bet)"
            # split possible? (same rank + enough balance)
            can_split = (first_hand_cards[0] == first_hand_cards[1]
                         and profile["cash"] >= bet)
            if can_split:
                desc += "  4️⃣ Split"

            embed = make_embed(
                title="♠️ AYO Blackjack",
                description=desc,
            )
            msg = await ctx.send(embed=embed)
            for e in EMOJI_ACTIONS.keys():
                await msg.add_reaction(e)

            # ===== natural blackjack: PLAYER ONLY =====
            p_val = hand_value(first_hand_cards)
            if p_val == 21:
                await asyncio.sleep(0.7)
                win_amount = int(bet * 2.5)
                profile["cash"] += win_amount
                profile["bj_wins"] = profile.get("bj_wins", 0) + 1
                db.save_users()

                final_result = (
                    f"🎉 **Blackjack!** You win `{win_amount - bet:,}` {CURRENCY_EMOJI}."
                )
                await self._reveal_and_finish_embed(ctx, msg, hands,
                                                    dealer_cards, final_result,
                                                    profile)
                return

            # ================= MAIN LOOP =================
            while True:
                # next active hand index
                try:
                    current_index = next(
                        i for i, h in enumerate(hands)
                        if not h["finished"] and not h["busted"])
                except StopIteration:
                    # all hands done -> dealer plays + settle
                    await self._dealer_and_settle(ctx, msg, hands,
                                                  dealer_cards, profile,
                                                  insurance_possible,
                                                  insurance_bet)
                    return

                active_hand = hands[current_index]

                total_bet_now = sum(h["bet"] for h in hands) + insurance_bet
                desc = (
                    f"{HEADER_LINE}\n\n"
                    f"💰 **Base Bet:** `{bet:,}` {CURRENCY_EMOJI}\n"
                    f"🎲 **Total At Risk:** `{total_bet_now:,}` {CURRENCY_EMOJI}\n\n"
                    f"{build_status(reveal_dealer=False, active_index=current_index)}\n\n"
                    "React:\n"
                    "1️⃣ Stand  2️⃣ Hit")

                # allowed actions (REAL RULES):
                first_turn = len(
                    active_hand["cards"]) == 2 and not active_hand["doubled"]
                # double only first turn + enough balance
                can_double = first_turn and profile["cash"] >= active_hand[
                    "bet"]
                # split only first hand, first turn, same rank, enough balance, and not already split
                can_split_current = (first_turn and active_hand is hands[0]
                                     and active_hand["cards"][0]
                                     == active_hand["cards"][1]
                                     and profile["cash"] >= active_hand["bet"])
                if can_double:
                    desc += "  3️⃣ Double"
                if can_split_current and len(hands) == 1:
                    desc += "  4️⃣ Split"
                if insurance_possible and not insurance_resolved and insurance_bet == 0:
                    desc += "  5️⃣ Insurance"

                embed.description = desc
                await msg.edit(embed=embed)

                def check(reaction, user):
                    return (user.id == ctx.author.id
                            and reaction.message.id == msg.id
                            and str(reaction.emoji) in EMOJI_ACTIONS)

                try:
                    reaction, user = await self.bot.wait_for("reaction_add",
                                                             timeout=40.0,
                                                             check=check)
                except asyncio.TimeoutError:
                    # timeout -> auto stand current hand
                    active_hand["finished"] = True
                    continue

                try:
                    await msg.remove_reaction(reaction.emoji, user)
                except discord.Forbidden:
                    pass

                action = EMOJI_ACTIONS[str(reaction.emoji)]

                # ===== INSURANCE =====
                if action == "insurance":
                    if not (insurance_possible and not insurance_resolved
                            and insurance_bet == 0):
                        continue
                    max_ins = min(active_hand["bet"] // 2, profile["cash"])
                    if max_ins <= 0:
                        continue
                    # auto take max allowed (simple UX)
                    insurance_bet = max_ins
                    profile["cash"] -= insurance_bet
                    db.save_users()
                    await ctx.send(
                        f"🛡️ Insurance taken for `{insurance_bet:,}` {CURRENCY_EMOJI}.",
                        delete_after=4,
                    )
                    continue

                # ===== SPLIT =====
                if action == "split":
                    if not can_split_current or len(hands) > 1:
                        continue
                    card1, card2 = active_hand["cards"]
                    profile["cash"] -= active_hand["bet"]
                    db.save_users()
                    new_bet = active_hand["bet"]
                    hands.clear()
                    hands.append({
                        "cards": [card1, deck.pop()],
                        "bet": new_bet,
                        "finished": False,
                        "busted": False,
                        "doubled": False,
                    })
                    hands.append({
                        "cards": [card2, deck.pop()],
                        "bet": new_bet,
                        "finished": False,
                        "busted": False,
                        "doubled": False,
                    })
                    current_index = 0
                    await ctx.send(
                        f"✂️ Split! Now playing **2 hands** with `{new_bet:,}` {CURRENCY_EMOJI} each.",
                        delete_after=4,
                    )
                    continue

                # ===== DOUBLE =====
                if action == "double":
                    if not can_double:
                        continue
                    profile["cash"] -= active_hand["bet"]
                    active_hand["bet"] *= 2
                    active_hand["doubled"] = True
                    db.save_users()
                    # one card then auto-stand
                    active_hand["cards"].append(deck.pop())
                    if hand_value(active_hand["cards"]) > 21:
                        active_hand["busted"] = True
                    active_hand["finished"] = True
                    await asyncio.sleep(0.6)
                    continue

                # ===== HIT =====
                if action == "hit":
                    active_hand["cards"].append(deck.pop())
                    if hand_value(active_hand["cards"]) > 21:
                        active_hand["busted"] = True
                        active_hand["finished"] = True
                    await asyncio.sleep(0.4)
                    continue

                # ===== STAND =====
                if action == "stand":
                    active_hand["finished"] = True
                    await asyncio.sleep(0.3)
                    continue

        finally:
            self.active_games.discard(ctx.author.id)

    # ================= DEALER + SETTLE =================

    async def _dealer_and_settle(
        self,
        ctx: commands.Context,
        msg: discord.Message,
        hands,
        dealer_cards,
        profile,
        insurance_possible,
        insurance_bet: int,
    ):
        # small helper for dealer animation embed
        async def show_state(text: str):
            dealer_val_now = hand_value(dealer_cards)
            lines = [
                f"🤵 **Dealer** (**{dealer_val_now}**): "
                f"{format_big_hand(dealer_cards, hide_first=False)}",
                "",
            ]
            for idx, h in enumerate(hands):
                tag = f"Hand {idx+1}"
                val = hand_value(h["cards"])
                cards_str = format_big_hand(h["cards"])
                state = ""
                if h["busted"]:
                    state = " **[BUST]**"
                elif h["finished"]:
                    state = " **[STAND]**"
                lines.append(f"🃏 **{tag}** (**{val}**): {cards_str}{state}")
            lines.append("")
            lines.append(text)

            embed = (msg.embeds[0] if msg.embeds else make_embed(
                title="♠️ AYO Blackjack"))
            embed.title = "♠️ AYO Blackjack"
            embed.description = f"{HEADER_LINE}\n\n" + "\n".join(lines)
            await msg.edit(embed=embed)

        # dealer reveal + animation
        await asyncio.sleep(0.6)
        await show_state("▶️ Dealer reveals hand...")

        while hand_value(dealer_cards) < 17:
            dealer_cards.append(random.choice(RANKS))
            await asyncio.sleep(0.8)
            await show_state("🃏 Dealer draws a card...")

        dealer_val = hand_value(dealer_cards)

        total_delta = 0
        result_lines = []

        # insurance resolve
        if insurance_possible and insurance_bet > 0:
            if dealer_val == 21:
                win_ins = insurance_bet * 3
                profile["cash"] += win_ins
                total_delta += win_ins - insurance_bet
                result_lines.append(
                    f"🛡️ Insurance wins `{win_ins - insurance_bet:,}` {CURRENCY_EMOJI}."
                )
            else:
                total_delta -= insurance_bet
                result_lines.append("🛡️ Insurance lost.")

        # each hand result
        for idx, h in enumerate(hands):
            val = hand_value(h["cards"])
            bet = h["bet"]
            tag = f"Hand {idx+1}"

            if h["busted"]:
                total_delta -= bet
                profile["bj_losses"] = profile.get("bj_losses", 0) + 1
                result_lines.append(
                    f"❌ {tag}: Bust (lost `{bet:,}` {CURRENCY_EMOJI}).")
                continue

            if dealer_val > 21:
                win = bet * 2
                profile["cash"] += win
                total_delta += win - bet
                profile["bj_wins"] = profile.get("bj_wins", 0) + 1
                result_lines.append(
                    f"🎉 {tag}: Dealer busts, you win `{win - bet:,}` {CURRENCY_EMOJI}."
                )
            elif val > dealer_val:
                win = bet * 2
                profile["cash"] += win
                total_delta += win - bet
                profile["bj_wins"] = profile.get("bj_wins", 0) + 1
                result_lines.append(
                    f"✅ {tag}: You beat dealer and win `{win - bet:,}` {CURRENCY_EMOJI}."
                )
            elif val < dealer_val:
                total_delta -= bet
                profile["bj_losses"] = profile.get("bj_losses", 0) + 1
                result_lines.append(
                    f"❌ {tag}: Dealer wins (lost `{bet:,}` {CURRENCY_EMOJI}).")
            else:
                profile["cash"] += bet
                result_lines.append(f"😐 {tag}: Push – bet returned.")

        db.save_users()

        result_lines.append(
            f"\n📊 **Net result:** `{total_delta:,}` {CURRENCY_EMOJI}.")
        final_result = "\n".join(result_lines)

        await self._reveal_and_finish_embed(ctx, msg, hands, dealer_cards,
                                            final_result, profile)

        # log
        try:
            log_embed = make_embed(
                title="Blackjack Game",
                description=(f"Player: {ctx.author} (`{ctx.author.id}`)\n"
                             f"Details:\n{final_result}"),
            )
            await send_log(self.bot, ctx.guild, "games", log_embed)
        except Exception:
            pass

    # ================= FINAL EMBED =================

    async def _reveal_and_finish_embed(
        self,
        ctx: commands.Context,
        msg: discord.Message,
        hands,
        dealer_cards,
        result_text: str,
        profile,
    ):
        try:
            await msg.clear_reactions()
        except discord.Forbidden:
            pass

        dealer_val = hand_value(dealer_cards)

        lines = [
            f"🤵 **Dealer** (**{dealer_val}**): "
            f"{format_big_hand(dealer_cards, hide_first=False)}",
            "",
        ]
        for idx, h in enumerate(hands):
            tag = f"Hand {idx+1}"
            val = hand_value(h["cards"])
            cards_str = format_big_hand(h["cards"])
            lines.append(f"🃏 **{tag}** (**{val}**): {cards_str}")
        lines.append("")

        # BJ stats line
        wins = profile.get("bj_wins", 0)
        losses = profile.get("bj_losses", 0)
        lines.append(f"📈 **BJ Stats:** {wins} Wins • {losses} Losses")
        lines.append("")
        lines.append(result_text)

        embed = (msg.embeds[0] if msg.embeds else make_embed(
            title="♠️ AYO Blackjack"))
        embed.title = "♠️ AYO Blackjack"
        embed.description = f"{HEADER_LINE}\n\n" + "\n".join(lines)
        await msg.edit(embed=embed)


async def setup(bot):
    await bot.add_cog(Blackjack(bot))

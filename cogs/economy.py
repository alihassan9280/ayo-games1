import time
import discord
from discord.ext import commands

from utils import db
from utils.common import make_embed, fmt_time, send_log

CURRENCY_EMOJI = "💰"
DAILY_COOLDOWN = 24 * 60 * 60  # 24h
BASE_DAILY = 5000  # new daily base

RINGS = {
    "1": {
        "name": "Silver Ring",
        "price": 100_000
    },
    "2": {
        "name": "Gold Ring",
        "price": 1_000_000
    },
    "3": {
        "name": "Diamond Ring",
        "price": 5_000_000
    },
}

BACKGROUND_SHOP = {
    "bg1": {
        "name": "Dark Neon BG",
        "price": 200_000
    },
    "bg2": {
        "name": "Crimson Wave BG",
        "price": 500_000
    },
    "bg3": {
        "name": "AYO Black Premium",
        "price": 1_000_000
    },
}

# ============= LEVEL / STREAK HELPERS =============


def today_day_number():
    # simple day index
    return int(time.time() // 86400)


def level_reward_for(level: int) -> int:
    """
    Level 1: 100k
    Each level +50k
    After level 5 -> double
    """
    base = 100_000 + 50_000 * (level - 1)
    if level > 5:
        base *= 2
    return base


def xp_needed_for_next(level: int) -> int:
    # simple curve
    return 100 * (level + 1)


class Economy(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    # ============= INTERNAL LEVEL HANDLER =============

    async def _add_xp_and_check_level(self, ctx: commands.Context,
                                      profile: dict, xp_gain: int):
        # safe defaults
        profile.setdefault("level", 0)
        profile.setdefault("xp", 0)

        if xp_gain <= 0:
            return

        profile["xp"] += xp_gain
        leveled = False
        messages = []

        while profile["xp"] >= xp_needed_for_next(profile["level"]):
            req = xp_needed_for_next(profile["level"])
            profile["xp"] -= req
            profile["level"] += 1
            leveled = True

            reward = level_reward_for(profile["level"])
            profile["cash"] = profile.get("cash", 0) + reward
            messages.append(
                f"⬆️ **Level Up!** You reached **Level {profile['level']}** "
                f"and received **{reward:,} {CURRENCY_EMOJI}**.")

        if leveled:
            db.save_users()
            embed = make_embed(
                title="AYO Level System",
                description="\n".join(messages),
            )
            await ctx.send(embed=embed)

    # ============= HELP =============

    @commands.command(name="help")
    async def ayo_help(self, ctx: commands.Context):
        embed = make_embed(
            title="AYO Cash • Commands",
            description=
            "Prefix: `ayo` (always) + optional 2nd prefix via `ayo setprefix`.",
        )
        embed.add_field(
            name="💰 Cash",
            value=(
                "`ayo cash` / `ayocash` – Check your cash\n"
                "`ayo daily` / `ayodaily` – Claim daily reward (streak bonus)\n"
                "`ayo streak` – View your daily streak\n"
                "`ayo give @user amount` – Send cash to someone\n"
                "`ayo gift @user amount` – Gift cash (tracks gifts)\n"
                "`ayo topcash` / `ayotopcash` – Richest users"),
            inline=False,
        )
        embed.add_field(
            name="👤 Profile",
            value=("`ayo profile` / `ayoprofile` – View profile\n"
                   "`ayo about <text>` – Set your about/bio\n"
                   "`ayo banner set <url>` – Set profile banner\n"
                   "`ayo banner remove` – Remove banner\n"
                   "`ayo level` – Check your level & XP"),
            inline=False,
        )
        embed.add_field(
            name="💍 Shop & Inventory",
            value=("`ayo shop` – View rings shop\n"
                   "`ayo shop backgrounds` – View backgrounds shop\n"
                   "`ayo buy <id>` – Buy ring/background (e.g. 1, bg1)\n"
                   "`ayo inventory` / `ayoinv` – View your items\n"
                   "`ayo sell <id>` – Sell item for 50% price\n"
                   "`ayo setbg <id>` – Set active background (e.g. bg1)\n"
                   "`ayo marry @user <id>` – Send marry request\n"
                   "`ayo accept` / `ayo decline` – Accept or decline request\n"
                   "`ayo divorce` – End your marriage\n"
                   "`ayo topmarry` – Top married couples"),
            inline=False,
        )
        embed.add_field(
            name="📈 Levels & Streak",
            value=("`ayo level` – Level & next reward\n"
                   "`ayo streak` – Daily streak details"),
            inline=False,
        )
        embed.add_field(
            name="🎰 Games",
            value=
            ("`ayo cf <amount> <h/t>` – Coinflip (e.g. `ayo cf 5000 t`, `ayo cf t 5000`, `ayocf all h`)\n"
             "`ayo slots <amount>` – Slots (e.g. `ayo slots 5000`, `ayos all`)\n"
             "`ayobj <amount>` – Blackjack (reactions: 1️⃣ hit, 2️⃣ stand, 3️⃣ double)\n"
             "`ayocrash <amount>` – Crash game"),
            inline=False,
        )
        embed.add_field(
            name="🎁 Special",
            value="`ayoclaim` – Claim event reward (if active)",
            inline=False,
        )
        embed.add_field(
            name="🔧 Owner",
            value="`ayo ownerhelp` – Owner-only commands",
            inline=False,
        )
        await ctx.send(embed=embed)

    # ============= CASH & PROFILE =============

    @commands.command(name="cash")
    async def cash_command(self,
                           ctx: commands.Context,
                           member: discord.Member = None):
        target = member or ctx.author
        profile = db.get_profile(target.id)
        embed = make_embed(
            title=f"{target.display_name}'s Cash",
            description=f"**Cash:** {profile['cash']:,} {CURRENCY_EMOJI}",
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command(name="level")
    async def level_command(self,
                            ctx: commands.Context,
                            member: discord.Member = None):
        target = member or ctx.author
        profile = db.get_profile(target.id)
        lvl = profile.get("level", 0)
        xp = profile.get("xp", 0)
        need = xp_needed_for_next(lvl)
        embed = make_embed(
            title=f"{target.display_name} • Level",
            description=
            (f"⭐ **Level:** `{lvl}`\n"
             f"📊 **XP:** `{xp} / {need}`\n"
             f"🎁 Next level reward: `{level_reward_for(lvl + 1):,} {CURRENCY_EMOJI}`"
             ),
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command(name="about")
    async def about_command(self, ctx: commands.Context, *, text: str):
        profile = db.get_profile(ctx.author.id)
        profile["about"] = text[:190]
        db.save_users()
        embed = make_embed(
            title="Profile Updated",
            description=f"✅ About set to:\n```{profile['about']}```",
        )
        await ctx.send(embed=embed)

    @commands.command(name="banner")
    async def banner_command(self,
                             ctx: commands.Context,
                             action: str,
                             *,
                             value: str = None):
        # ayo banner set <url>
        # ayo banner remove
        profile = db.get_profile(ctx.author.id)
        act = action.lower()

        if act == "set":
            if not value:
                await ctx.send("❌ Provide an image URL.")
                return
            if not any(value.lower().endswith(ext)
                       for ext in [".png", ".jpg", ".jpeg", ".webp", ".gif"]):
                await ctx.send(
                    "❌ URL must be a direct image link (.png/.jpg/.jpeg/.webp/.gif)."
                )
                return
            profile["banner_url"] = value
            db.save_users()
            embed = make_embed(
                title="Banner Updated",
                description="✅ Profile banner set.",
            )
            embed.set_image(url=value)
            await ctx.send(embed=embed)

        elif act == "remove":
            profile["banner_url"] = None
            db.save_users()
            embed = make_embed(
                title="Banner Removed",
                description="✅ Profile banner removed.",
            )
            await ctx.send(embed=embed)
        else:
            await ctx.send(
                "Usage: `ayo banner set <url>` or `ayo banner remove`.")

    @commands.command(name="profile")
    async def profile_command(self,
                              ctx: commands.Context,
                              member: discord.Member = None):
        target = member or ctx.author
        profile = db.get_profile(target.id)

        about = profile.get("about") or "No about set. Use `ayo about <text>`."
        married_to = profile.get("married_to")
        ring_id = profile.get("ring_id")
        marriage_text = "Single"
        if married_to:
            try:
                partner = ctx.guild.get_member(
                    int(married_to)) if ctx.guild else None
            except Exception:
                partner = None
            partner_name = partner.display_name if partner else f"ID {married_to}"
            ring_name = RINGS.get(str(ring_id), {}).get("name", "Unknown Ring")
            marriage_text = f"Married to **{partner_name}** with **{ring_name}**"

        active_bg = profile.get("active_bg")
        bg_text = "None"
        if active_bg:
            bg_text = BACKGROUND_SHOP.get(active_bg, {}).get("name", active_bg)

        # new fields
        lvl = profile.get("level", 0)
        xp = profile.get("xp", 0)
        streak = profile.get("streak", 0)

        desc = (
            f"💰 **Cash:** {profile['cash']:,} {CURRENCY_EMOJI}\n"
            f"⭐ **Level:** `{lvl}` (XP: `{xp}/{xp_needed_for_next(lvl)}`)\n"
            f"🔥 **Daily Streak:** `{streak}` day(s)\n"
            f"💍 **Status:** {marriage_text}\n"
            f"🎨 **Background:** {bg_text}\n\n"
            f"📜 **About:**\n{about}\n\n"
            f"🆔 **User ID:** `{target.id}`")

        embed = make_embed(
            title=f"{target.display_name} • Profile",
            description=desc,
        )
        embed.set_thumbnail(url=target.display_avatar.url)

        banner_url = profile.get("banner_url")
        if banner_url:
            embed.set_image(url=banner_url)

        await ctx.send(embed=embed)

    # ============= DAILY + STREAK =============

    @commands.command(name="daily")
    async def daily_command(self, ctx: commands.Context):
        profile = db.get_profile(ctx.author.id)
        now = time.time()
        remaining = profile["daily_last"] + DAILY_COOLDOWN - now
        if remaining > 0:
            embed = make_embed(
                title="Daily Cash",
                description=
                f"⏳ Already claimed. Try again in **{fmt_time(remaining)}**.",
            )
            await ctx.send(embed=embed)
            return

        # streak logic
        profile.setdefault("streak", 0)
        profile.setdefault("last_daily_day", 0)

        today = today_day_number()
        last_day = profile.get("last_daily_day", 0)

        if last_day == 0:
            profile["streak"] = 1
        else:
            if today == last_day + 1:
                profile["streak"] += 1
            elif today == last_day:
                # weird case, but keep same streak
                pass
            else:
                profile["streak"] = 1

        streak = profile["streak"]

        # base 5000 + 10% per streak continuation
        bonus_multiplier = 1.0 + 0.10 * (streak - 1)
        amount = int(BASE_DAILY * bonus_multiplier)

        # 7-day & 30-day bonus
        extra_lines = []
        if streak % 7 == 0:
            bonus7 = 25_000
            amount += bonus7
            extra_lines.append(
                f"🎁 **7-day streak bonus:** +`{bonus7:,}` {CURRENCY_EMOJI}")
        if streak % 30 == 0:
            bonus30 = 150_000
            amount += bonus30
            extra_lines.append(
                f"💎 **30-day MEGA bonus:** +`{bonus30:,}` {CURRENCY_EMOJI}")

        profile["cash"] += amount
        profile["daily_last"] = now
        profile["last_daily_day"] = today

        # XP for daily
        await self._add_xp_and_check_level(ctx, profile, xp_gain=10)

        db.save_users()

        extra_text = "\n".join(extra_lines) if extra_lines else ""
        desc = (f"✅ You claimed **{amount:,} {CURRENCY_EMOJI}**.\n"
                f"🔥 Current streak: **{streak}** day(s).\n"
                f"{extra_text}")

        embed = make_embed(
            title="Daily Cash",
            description=desc,
        )
        await ctx.send(embed=embed)

        if ctx.guild:
            log_embed = make_embed(
                title="Daily Claimed",
                description=
                f"{ctx.author} claimed **{amount:,} {CURRENCY_EMOJI}** (streak {streak}).",
            )
            await send_log(self.bot, ctx.guild, "daily", log_embed)

    @commands.command(name="streak")
    async def streak_command(self,
                             ctx: commands.Context,
                             member: discord.Member = None):
        target = member or ctx.author
        profile = db.get_profile(target.id)
        streak = profile.get("streak", 0)
        last_day = profile.get("last_daily_day", 0)
        today = today_day_number()
        broken = last_day and today > last_day + 1
        status = "✅ Active" if not broken and streak > 0 else "❌ Broken / Not started"

        embed = make_embed(
            title=f"{target.display_name} • Daily Streak",
            description=(f"🔥 **Streak:** `{streak}` day(s)\n"
                         f"📆 **Status:** {status}\n"
                         f"💰 Base daily: `{BASE_DAILY:,} {CURRENCY_EMOJI}`\n"
                         f"📈 Each day: +10% bonus"),
        )
        await ctx.send(embed=embed)

    # ============= GIVE / GIFT / TOPCASH =============

    @commands.command(name="give")
    async def give_command(self, ctx: commands.Context, member: discord.Member,
                           amount: str):
        if member.bot:
            await ctx.send("❌ You can't give cash to bots.")
            return

        if not amount.isdigit():
            await ctx.send("❌ Amount must be a positive number.")
            return

        amount_int = int(amount)
        if amount_int <= 0:
            await ctx.send("❌ Amount must be positive.")
            return

        sender_profile = db.get_profile(ctx.author.id)
        receiver_profile = db.get_profile(member.id)

        if sender_profile["cash"] < amount_int:
            embed = make_embed(
                title="Transfer Failed",
                description="❌ You don't have enough cash.",
            )
            await ctx.send(embed=embed)
            return

        sender_profile["cash"] -= amount_int
        receiver_profile["cash"] += amount_int
        db.save_users()

        embed = make_embed(
            title="Transfer Complete",
            description=
            (f"✅ {ctx.author.mention} sent **{amount_int:,} {CURRENCY_EMOJI}** to {member.mention}.\n"
             f"Your new cash: **{sender_profile['cash']:,} {CURRENCY_EMOJI}**"
             ),
        )
        await ctx.send(embed=embed)

        if ctx.guild:
            log_embed = make_embed(
                title="Cash Transfer",
                description=
                (f"{ctx.author} → {member}: **{amount_int:,} {CURRENCY_EMOJI}**\n"
                 f"Sender new cash: {sender_profile['cash']:,} {CURRENCY_EMOJI}"
                 ),
            )
            await send_log(self.bot, ctx.guild, "cash", log_embed)

    @commands.command(name="gift")
    async def gift_command(self, ctx: commands.Context, member: discord.Member,
                           amount: str):
        """ayo gift @user amount – same as give but tracked as gift."""
        if member.bot:
            await ctx.send("❌ You can't gift cash to bots.")
            return
        if member.id == ctx.author.id:
            await ctx.send("❌ You can't gift yourself.")
            return
        if not amount.isdigit():
            await ctx.send("❌ Amount must be a positive number.")
            return

        amount_int = int(amount)
        if amount_int <= 0:
            await ctx.send("❌ Amount must be positive.")
            return

        sender_profile = db.get_profile(ctx.author.id)
        receiver_profile = db.get_profile(member.id)

        if sender_profile["cash"] < amount_int:
            await ctx.send("❌ You don't have enough cash.")
            return

        sender_profile["cash"] -= amount_int
        receiver_profile["cash"] += amount_int

        sender_profile["gifts_sent"] = sender_profile.get("gifts_sent", 0) + 1
        receiver_profile["gifts_received"] = receiver_profile.get(
            "gifts_received", 0) + 1

        # XP for social gift
        await self._add_xp_and_check_level(ctx, sender_profile, xp_gain=5)

        db.save_users()

        embed = make_embed(
            title="🎁 Gift Sent",
            description=
            (f"{ctx.author.mention} gifted **{amount_int:,} {CURRENCY_EMOJI}** to {member.mention}.\n"
             f"Your new cash: **{sender_profile['cash']:,} {CURRENCY_EMOJI}**"
             ),
        )
        await ctx.send(embed=embed)

        if ctx.guild:
            log_embed = make_embed(
                title="Gift Transfer",
                description=
                (f"{ctx.author} 🎁 {member}: **{amount_int:,} {CURRENCY_EMOJI}**"
                 ),
            )
            await send_log(self.bot, ctx.guild, "cash", log_embed)

    @commands.command(name="topcash")
    async def topcash_command(self, ctx: commands.Context):
        users = db.get_users()
        if not users:
            await ctx.send("No data yet.")
            return

        sorted_users = sorted(
            users.items(),
            key=lambda kv: kv[1].get("cash", 0),
            reverse=True,
        )

        lines = []
        rank = 1
        for user_id, data in sorted_users:
            member = ctx.guild.get_member(int(user_id)) if ctx.guild else None
            if not member:
                continue
            lines.append(
                f"**{rank}.** {member.display_name} – `{data.get('cash', 0):,}` {CURRENCY_EMOJI}"
            )
            rank += 1
            if rank > 10:
                break

        if not lines:
            await ctx.send("No users with cash in this server yet.")
            return

        embed = make_embed(
            title="🏆 Top Cash",
            description="\n".join(lines),
        )
        await ctx.send(embed=embed)

    # ============= SHOP / INVENTORY / SELL =============

    @commands.command(name="shop")
    async def shop_command(self, ctx: commands.Context, category: str = None):
        # ayo shop          -> rings
        # ayo shop bg       -> backgrounds
        cat = (category or "").lower()

        if cat in {"background", "backgrounds", "bg", "bgs"}:
            lines = []
            for bid, info in BACKGROUND_SHOP.items():
                lines.append(
                    f"`{bid}` • **{info['name']}** – `{info['price']:,} {CURRENCY_EMOJI}`"
                )
            desc = "🎨 **Backgrounds Shop**\n" + "\n".join(lines)
            desc += "\n\nUse `ayo buy <id>` to purchase (e.g. `ayo buy bg1`)."
            embed = make_embed(
                title="AYO Shop • Backgrounds",
                description=desc,
            )
            await ctx.send(embed=embed)
            return

        # default: rings
        lines = []
        for rid, info in RINGS.items():
            lines.append(
                f"`{rid}` • **{info['name']}** – `{info['price']:,} {CURRENCY_EMOJI}`"
            )
        desc = "💍 **Rings Shop**\n" + "\n".join(lines)
        desc += "\n\nUse `ayo buy <id>` to purchase."
        embed = make_embed(
            title="AYO Shop • Rings",
            description=desc,
        )
        await ctx.send(embed=embed)

    @commands.command(name="buy")
    async def buy_command(self, ctx: commands.Context, item_id: str):
        # ayo buy 1   / ayo buy bg1
        item_id = item_id.strip()

        profile = db.get_profile(ctx.author.id)
        if "backgrounds" not in profile or profile["backgrounds"] is None:
            profile["backgrounds"] = {}

        if item_id in RINGS:
            info = RINGS[item_id]
            price = info["price"]
            if profile["cash"] < price:
                await ctx.send("❌ Not enough cash for this ring.")
                return
            profile["cash"] -= price
            profile["rings"][item_id] = profile["rings"].get(item_id, 0) + 1
            item_name = info["name"]
            extra = f"Owned: `{profile['rings'][item_id]}`"

        elif item_id in BACKGROUND_SHOP:
            info = BACKGROUND_SHOP[item_id]
            price = info["price"]
            if profile["cash"] < price:
                await ctx.send("❌ Not enough cash for this background.")
                return
            profile["cash"] -= price
            profile["backgrounds"][item_id] = profile["backgrounds"].get(
                item_id, 0) + 1
            item_name = info["name"]
            extra = f"Owned: `{profile['backgrounds'][item_id]}`"

        else:
            await ctx.send(
                "❌ Invalid item id. Use `ayo shop` or `ayo shop backgrounds`.")
            return

        db.save_users()

        embed = make_embed(
            title="Purchase Complete",
            description=
            (f"✅ You bought **{item_name}** for **{info['price']:,} {CURRENCY_EMOJI}**.\n"
             f"{extra}\n"
             f"New cash: `{profile['cash']:,} {CURRENCY_EMOJI}`"),
        )
        await ctx.send(embed=embed)

        if ctx.guild:
            log_embed = make_embed(
                title="Shop Purchase",
                description=
                f"{ctx.author} bought {item_name} for {info['price']:,} {CURRENCY_EMOJI}.",
            )
            await send_log(self.bot, ctx.guild, "cash", log_embed)

    @commands.command(name="inventory", aliases=["inv"])
    async def inventory_command(self,
                                ctx: commands.Context,
                                member: discord.Member = None):
        # ayo inventory / ayoinv
        target = member or ctx.author
        profile = db.get_profile(target.id)

        rings = profile.get("rings") or {}
        bgs = profile.get("backgrounds") or {}

        ring_lines = []
        for rid, info in RINGS.items():
            count = rings.get(rid, 0)
            if count > 0:
                ring_lines.append(f"`{rid}` • **{info['name']}** × `{count}`")

        bg_lines = []
        for bid, info in BACKGROUND_SHOP.items():
            count = bgs.get(bid, 0)
            if count > 0:
                bg_lines.append(f"`{bid}` • **{info['name']}** × `{count}`")

        if not ring_lines and not bg_lines:
            desc = "You don't own any items yet.\nUse `ayo shop` and `ayo shop backgrounds` to buy."
        else:
            desc = ""
            if ring_lines:
                desc += "💍 **Rings**\n" + "\n".join(ring_lines) + "\n\n"
            if bg_lines:
                desc += "🎨 **Backgrounds**\n" + "\n".join(bg_lines)

        embed = make_embed(
            title=f"{target.display_name}'s Inventory",
            description=desc,
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command(name="sell")
    async def sell_command(self, ctx: commands.Context, item_id: str):
        # ayo sell 1    (ring)
        # ayo sell bg1  (background)
        profile = db.get_profile(ctx.author.id)
        item_id = item_id.strip()

        rings = profile.get("rings") or {}
        bgs = profile.get("backgrounds") or {}

        if item_id in RINGS:
            count = rings.get(item_id, 0)
            if count <= 0:
                await ctx.send("❌ You don't own that ring.")
                return
            price = RINGS[item_id]["price"]
            sell_price = price // 2
            rings[item_id] = count - 1
            item_name = RINGS[item_id]["name"]

        elif item_id in BACKGROUND_SHOP:
            count = bgs.get(item_id, 0)
            if count <= 0:
                await ctx.send("❌ You don't own that background.")
                return
            price = BACKGROUND_SHOP[item_id]["price"]
            sell_price = price // 2
            bgs[item_id] = count - 1
            if profile.get("active_bg") == item_id and bgs[item_id] <= 0:
                profile["active_bg"] = None
            item_name = BACKGROUND_SHOP[item_id]["name"]

        else:
            await ctx.send("❌ Invalid item id.")
            return

        profile["rings"] = rings
        profile["backgrounds"] = bgs
        profile["cash"] += sell_price
        db.save_users()

        embed = make_embed(
            title="Item Sold",
            description=
            (f"✅ Sold **{item_name}** for **{sell_price:,} {CURRENCY_EMOJI}** "
             f"(50% of original price)."),
        )
        await ctx.send(embed=embed)

    @commands.command(name="setbg")
    async def setbg_command(self, ctx: commands.Context, item_id: str):
        # ayo setbg bg1
        profile = db.get_profile(ctx.author.id)
        bgs = profile.get("backgrounds") or {}
        item_id = item_id.strip()

        if item_id not in BACKGROUND_SHOP:
            await ctx.send(
                "❌ Invalid background id. Use `ayo shop backgrounds`.")
            return

        if bgs.get(item_id, 0) <= 0:
            await ctx.send("❌ You don't own that background.")
            return

        profile["active_bg"] = item_id
        profile["backgrounds"] = bgs
        db.save_users()

        name = BACKGROUND_SHOP[item_id]["name"]
        embed = make_embed(
            title="Background Set",
            description=f"✅ Active background set to **{name}**.",
        )
        await ctx.send(embed=embed)

    # ============= MARRY SYSTEM =============

    @commands.command(name="marry", aliases=["ayomarry"])
    async def marry_command(self, ctx: commands.Context,
                            member: discord.Member, ring_id: str):
        ring_id = ring_id.strip()
        if ring_id not in RINGS:
            await ctx.send("❌ Invalid ring id. Use `ayo shop`.")
            return

        if member.bot:
            await ctx.send("❌ You can't marry a bot.")
            return

        if member.id == ctx.author.id:
            await ctx.send("❌ You can't marry yourself.")
            return

        p1 = db.get_profile(ctx.author.id)
        p2 = db.get_profile(member.id)

        if p1["married_to"] or p2["married_to"]:
            await ctx.send("❌ One of you is already married.")
            return

        if p2.get("marry_request_from"):
            await ctx.send("❌ That user already has a pending proposal.")
            return

        if p1["rings"].get(ring_id, 0) <= 0:
            await ctx.send(
                "❌ You don't own that ring. Buy from `ayo shop` first.")
            return

        p2["marry_request_from"] = str(ctx.author.id)
        p2["marry_request_ring"] = ring_id
        db.save_users()

        ring_name = RINGS[ring_id]["name"]
        embed = make_embed(
            title="💍 Marriage Request",
            description=(
                f"{ctx.author.mention} proposed to {member.mention} "
                f"with a **{ring_name}**.\n\n"
                f"{member.mention}, use `ayo accept` or `ayo decline`."),
        )
        await ctx.send(embed=embed)

    @commands.command(name="accept")
    async def accept_marry(self, ctx: commands.Context):
        p2 = db.get_profile(ctx.author.id)
        from_id = p2.get("marry_request_from")
        ring_id = p2.get("marry_request_ring")

        if not from_id or not ring_id:
            await ctx.send("❌ You don't have any pending marry request.")
            return

        proposer_id = int(from_id)
        p1 = db.get_profile(proposer_id)

        if p1["married_to"] or p2["married_to"]:
            p2["marry_request_from"] = None
            p2["marry_request_ring"] = None
            db.save_users()
            await ctx.send("❌ Someone is already married, request cleared.")
            return

        if p1["rings"].get(ring_id, 0) <= 0:
            p2["marry_request_from"] = None
            p2["marry_request_ring"] = None
            db.save_users()
            await ctx.send(
                "❌ The proposer no longer has that ring. Request cancelled.")
            return

        p1["rings"][ring_id] -= 1

        p1["married_to"] = str(ctx.author.id)
        p1["ring_id"] = ring_id
        p1["marriages"] += 1

        p2["married_to"] = str(proposer_id)
        p2["ring_id"] = ring_id
        p2["marriages"] += 1

        p2["marry_request_from"] = None
        p2["marry_request_ring"] = None

        db.save_users()

        ring_name = RINGS[ring_id]["name"]
        proposer = ctx.guild.get_member(proposer_id) if ctx.guild else None

        embed = make_embed(
            title="💍 Marriage Accepted",
            description=(
                f"🎉 {ctx.author.mention} accepted the proposal from "
                f"{proposer.mention if proposer else f'`{proposer_id}`'} "
                f"with a **{ring_name}**!"),
        )
        await ctx.send(embed=embed)

    @commands.command(name="decline")
    async def decline_marry(self, ctx: commands.Context):
        p2 = db.get_profile(ctx.author.id)
        from_id = p2.get("marry_request_from")
        ring_id = p2.get("marry_request_ring")

        if not from_id or not ring_id:
            await ctx.send("❌ You don't have any pending marry request.")
            return

        proposer_id = int(from_id)

        p2["marry_request_from"] = None
        p2["marry_request_ring"] = None
        db.save_users()

        proposer = ctx.guild.get_member(proposer_id) if ctx.guild else None
        embed = make_embed(
            title="💍 Marriage Declined",
            description=(
                f"{ctx.author.mention} declined the proposal from "
                f"{proposer.mention if proposer else f'`{proposer_id}`'}."),
        )
        await ctx.send(embed=embed)

    @commands.command(name="divorce", aliases=["divoice"])
    async def divorce_command(self, ctx: commands.Context):
        p = db.get_profile(ctx.author.id)
        partner_id_str = p.get("married_to")

        if not partner_id_str:
            await ctx.send("❌ You are not married.")
            return

        partner_id = int(partner_id_str)
        partner_profile = db.get_profile(partner_id)

        p["married_to"] = None
        p["ring_id"] = None
        partner_profile["married_to"] = None
        partner_profile["ring_id"] = None

        p["marry_request_from"] = None
        p["marry_request_ring"] = None
        if partner_profile.get("marry_request_from") == str(ctx.author.id):
            partner_profile["marry_request_from"] = None
            partner_profile["marry_request_ring"] = None

        db.save_users()

        partner_member = ctx.guild.get_member(
            partner_id) if ctx.guild else None
        embed = make_embed(
            title="💔 Divorce",
            description=
            (f"{ctx.author.mention} divorced "
             f"{partner_member.mention if partner_member else f'`{partner_id}`'}."
             ),
        )
        await ctx.send(embed=embed)

    @commands.command(name="topmarry")
    async def topmarry_command(self, ctx: commands.Context):
        users = db.get_users()
        if not users:
            await ctx.send("No data yet.")
            return

        pairs = {}
        for user_id, pdata in users.items():
            married_to = pdata.get("married_to")
            ring_id = pdata.get("ring_id")
            if not married_to:
                continue
            try:
                u = int(user_id)
                v = int(married_to)
            except ValueError:
                continue
            key = tuple(sorted((u, v)))
            if key in pairs:
                continue
            pairs[key] = ring_id

        if not pairs:
            await ctx.send("No marriages yet.")
            return

        lines = []
        rank = 1
        for (u, v), ring_id in pairs.items():
            m1 = ctx.guild.get_member(u) if ctx.guild else None
            m2 = ctx.guild.get_member(v) if ctx.guild else None
            if not m1 or not m2:
                continue
            ring_name = RINGS.get(str(ring_id), {}).get("name", "Unknown Ring")
            lines.append(
                f"**{rank}.** {m1.display_name} ❤️ {m2.display_name} – **{ring_name}**"
            )
            rank += 1
            if rank > 10:
                break

        if not lines:
            await ctx.send("No marriages in this server yet.")
            return

        embed = make_embed(
            title="💍 Top Couples",
            description="\n".join(lines),
        )
        await ctx.send(embed=embed)

    # ============= SPECIAL CLAIM =============

    @commands.command(name="claim")
    async def claim_command(self, ctx: commands.Context):
        # ayoclaim / ayo claim
        claim_cfg = db.get_claim_config()
        if not claim_cfg.get("enabled", False):
            await ctx.send("❌ There is no active claim right now.")
            return

        now = time.time()
        expires = claim_cfg.get("expires_at", 0)
        amount = claim_cfg.get("amount", 0)

        if now > expires or amount <= 0:
            db.disable_claim()
            await ctx.send("❌ Claim event has expired.")
            return

        uid = str(ctx.author.id)
        if uid in claim_cfg.get("claimed_users", []):
            await ctx.send("❌ You already claimed this reward.")
            return

        profile = db.get_profile(ctx.author.id)
        profile["cash"] += amount
        db.save_users()

        claim_cfg["claimed_users"].append(uid)
        db.save_config()

        embed = make_embed(
            title="Special Claim",
            description=f"✅ You claimed **{amount:,} {CURRENCY_EMOJI}**.",
        )
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Economy(bot))

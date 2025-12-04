import os
import time
import asyncio
import discord
from discord.ext import commands

from utils import db
from utils.common import make_embed, send_log

OWNER_ID = int(os.getenv("OWNER_ID") or 0)
CURRENCY_EMOJI = "💰"


def is_owner():

    async def predicate(ctx: commands.Context):
        if ctx.author.id != OWNER_ID:
            raise commands.CheckFailure(
                "Only the bot owner can use this command.")
        return True

    return commands.check(predicate)


class Owner(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    # ================= OWNER HELP =================

    @commands.command(name="ownerhelp")
    @is_owner()
    async def owner_help(self, ctx: commands.Context):
        desc = (
            "**Economy Control**\n"
            "`ayo addmoney @user amount` – Give cash\n"
            "`ayo removemoney @user amount` – Remove cash\n"
            "`ayo setmoney @user amount` – Set exact cash\n"
            "`ayo resetuser @user` – Reset user data to default\n"
            "`ayo cashall amount` – Add cash to ALL users\n"
            "`ayo botusers` – Show bot users summary\n"
            "`ayo uinfo <id>` – Investigate user ID\n\n"
            "**Claim Events**\n"
            "`ayo setclaim amount` – Enable 24h global claim (ayoclaim)\n"
            "`ayo disableclaim` – Turn off claim\n\n"
            "**System**\n"
            "`ayo backupdb` – Save users.json\n"
            "`ayo setprefix <symbol/off>` – Set 2nd prefix (e.g. !, ?, h)\n"
            "`ayo panel` – Owner control panel / dashboard\n\n"
            "**Games**\n"
            "`ayo disablegames` – Turn off games\n"
            "`ayo enablegames` – Turn games back on\n\n"
            "**Logs**\n"
            "`ayo setlog <type> #channel` – Set log (cash/games/daily/admin/all)\n"
            "`ayo logtest <type> <msg>` – Send test log\n\n"
            "**Announcements**\n"
            "`ayo announce <message>` – Global embed to all servers\n"
            "`ayo announcehere <message>` – Aesthetic embed in this channel")
        embed = make_embed(
            title="Owner Commands",
            description=desc,
        )
        await ctx.send(embed=embed)

    # ================= OWNER PANEL / DASHBOARD =================

    @commands.command(name="panel", aliases=["opanel", "ownerpanel"])
    @is_owner()
    async def owner_panel(self, ctx: commands.Context):
        users = db.get_users()
        total_users = len(users)
        total_cash = sum(u.get("cash", 0) for u in users.values())
        guild_count = len(self.bot.guilds)

        games_enabled = db.are_games_enabled()
        second_prefix = db.get_second_prefix()

        # claim info
        claim_cfg = db.get_claim_config()
        now = time.time()
        active = claim_cfg.get("enabled", False) and now < claim_cfg.get(
            "expires_at", 0)
        claim_status = "🟢 Active" if active else "🔴 Inactive"
        claim_desc = claim_status
        if claim_cfg.get("enabled", False):
            claim_desc += (
                f" • Reward: `{claim_cfg.get('amount', 0):,} {CURRENCY_EMOJI}`"
            )

        # logs info
        log_lines = []
        for t in ["cash", "games", "daily", "admin"]:
            cid = db.get_log_channel(t)
            ch = self.bot.get_channel(cid) if cid else None
            if ch:
                log_lines.append(f"**{t}:** {ch.mention}")
            else:
                log_lines.append(f"**{t}:** `Not set`")
        logs_text = "\n".join(
            log_lines) if log_lines else "No logs configured."

        # current guild stats
        guild_users = 0
        richest_lines = []
        if ctx.guild:
            # count users in this guild with data
            for uid, pdata in users.items():
                try:
                    member = ctx.guild.get_member(int(uid))
                except Exception:
                    member = None
                if member:
                    guild_users += 1
            # top 3 in this guild
            guild_entries = []
            for uid, pdata in users.items():
                try:
                    member = ctx.guild.get_member(int(uid))
                except Exception:
                    member = None
                if not member:
                    continue
                guild_entries.append((member, pdata.get("cash", 0)))
            guild_entries.sort(key=lambda x: x[1], reverse=True)
            for idx, (member, cash) in enumerate(guild_entries[:3], start=1):
                richest_lines.append(
                    f"**{idx}.** {member.display_name} – `{cash:,}` {CURRENCY_EMOJI}"
                )

        guild_rich_text = "\n".join(
            richest_lines) if richest_lines else "No data."

        latency_ms = round(self.bot.latency * 1000)

        desc = (
            f"👑 **Owner:** {ctx.author.mention}\n"
            f"🛰️ **Ping:** `{latency_ms} ms`\n\n"
            f"🌐 **Servers:** `{guild_count}`\n"
            f"👥 **Total Users (DB):** `{total_users}`\n"
            f"💰 **Total Cash (DB):** `{total_cash:,} {CURRENCY_EMOJI}`\n"
            f"🎮 **Games:** {'🟢 Enabled' if games_enabled else '🔴 Disabled'}\n"
            f"🔑 **Second Prefix:** `{second_prefix}`\n")

        embed = make_embed(
            title="AYO Owner Panel",
            description=desc,
        )
        if ctx.guild:
            embed.add_field(
                name=f"📊 {ctx.guild.name} • Local Stats",
                value=(f"Users with data: `{guild_users}`\n\n"
                       f"🏆 **Top 3 (this server)**\n{guild_rich_text}"),
                inline=False,
            )
        embed.add_field(
            name="🎁 Claim Event",
            value=claim_desc,
            inline=False,
        )
        embed.add_field(
            name="📝 Logs",
            value=logs_text,
            inline=False,
        )
        embed.set_footer(text="AYO Control Center • Owner Only")
        await ctx.send(embed=embed)

    # ================= GLOBAL ANNOUNCEMENTS =================

    @commands.command(name="announcehere", aliases=["sayembed", "announcech"])
    @is_owner()
    async def announce_here(self, ctx: commands.Context, *, message: str):
        """
        Aesthetic announcement only in current channel.
        """
        embed = make_embed(
            title="📢 AYO Announcement",
            description=message,
        )
        embed.set_footer(
            text=
            f"Sent by {ctx.author} • {ctx.guild.name if ctx.guild else 'AYO GAMES'}"
        )
        await ctx.send(embed=embed)

    @commands.command(name="announce", aliases=["broadcast", "globalannounce"])
    @is_owner()
    async def announce_global(self, ctx: commands.Context, *, message: str):
        """
        Send one nice embed to every server where the bot is.
        No @everyone spam, just clean announcement.
        """
        if not message.strip():
            await ctx.send("❌ Please provide a message.")
            return

        sent = 0
        failed = 0

        for guild in self.bot.guilds:
            # try system channel first
            channel = guild.system_channel

            # if no system channel or no perms, find first usable text channel
            if channel is None or not channel.permissions_for(
                    guild.me).send_messages:
                channel = None
                for ch in guild.text_channels:
                    if ch.permissions_for(guild.me).send_messages:
                        channel = ch
                        break

            if not channel:
                failed += 1
                continue

            embed = make_embed(
                title="📢 AYO Global Announcement",
                description=message,
            )
            embed.set_footer(text=f"Sent by {ctx.author} • AYO GAMES")
            try:
                await channel.send(embed=embed)
                sent += 1
                await asyncio.sleep(0.3)  # small delay to avoid rate limits
            except Exception:
                failed += 1
                continue

        # log admin usage
        if ctx.guild:
            log_embed = make_embed(
                title="Global Announcement Sent",
                description=
                f"By: {ctx.author} (`{ctx.author.id}`)\nSent to `{sent}` servers, failed `{failed}`.",
            )
            await send_log(self.bot, ctx.guild, "admin", log_embed)

        await ctx.send(
            f"✅ Announcement sent to **{sent}** server(s). Failed: `{failed}`."
        )

    # ================= ECONOMY ADMIN =================

    @commands.command(name="addmoney")
    @is_owner()
    async def addmoney_command(self, ctx: commands.Context,
                               member: discord.Member, amount: int):
        if amount <= 0:
            await ctx.send("Amount must be positive.")
            return

        profile = db.get_profile(member.id)
        profile["cash"] += amount
        db.save_users()

        embed = make_embed(
            title="Add Cash",
            description=
            f"✅ Added **{amount:,} {CURRENCY_EMOJI}** to {member.mention}.",
        )
        await ctx.send(embed=embed)

        if ctx.guild:
            log_embed = make_embed(
                title="Admin Add Cash",
                description=
                f"{ctx.author} → {member}: +**{amount:,} {CURRENCY_EMOJI}**",
            )
            await send_log(self.bot, ctx.guild, "admin", log_embed)

    @commands.command(name="removemoney")
    @is_owner()
    async def removemoney_command(self, ctx: commands.Context,
                                  member: discord.Member, amount: int):
        if amount <= 0:
            await ctx.send("Amount must be positive.")
            return

        profile = db.get_profile(member.id)
        old = profile["cash"]
        profile["cash"] = max(0, profile["cash"] - amount)
        db.save_users()

        embed = make_embed(
            title="Remove Cash",
            description=
            f"✅ Removed **{amount:,} {CURRENCY_EMOJI}** from {member.mention}.",
        )
        await ctx.send(embed=embed)

        if ctx.guild:
            log_embed = make_embed(
                title="Admin Remove Cash",
                description=
                f"{ctx.author} → {member}: -**{amount:,} {CURRENCY_EMOJI}** (from {old:,})",
            )
            await send_log(self.bot, ctx.guild, "admin", log_embed)

    @commands.command(name="setmoney")
    @is_owner()
    async def setmoney_command(self, ctx: commands.Context,
                               member: discord.Member, amount: int):
        if amount < 0:
            await ctx.send("Amount can't be negative.")
            return

        profile = db.get_profile(member.id)
        old = profile["cash"]
        profile["cash"] = amount
        db.save_users()

        embed = make_embed(
            title="Set Cash",
            description=
            f"✅ Set {member.mention}'s cash to **{amount:,} {CURRENCY_EMOJI}** (was {old:,}).",
        )
        await ctx.send(embed=embed)

        if ctx.guild:
            log_embed = make_embed(
                title="Admin Set Cash",
                description=
                f"{ctx.author} set {member} cash from {old:,} to {amount:,}.",
            )
            await send_log(self.bot, ctx.guild, "admin", log_embed)

    @commands.command(name="resetuser")
    @is_owner()
    async def resetuser_command(self, ctx: commands.Context,
                                member: discord.Member):
        users = db.get_users()
        uid = str(member.id)
        users.pop(uid, None)
        db.get_profile(member.id)
        db.save_users()

        embed = make_embed(
            title="Reset User",
            description=
            f"✅ {member.mention}: Profile reset to default (250,000 {CURRENCY_EMOJI}).",
        )
        await ctx.send(embed=embed)

    @commands.command(name="backupdb")
    @is_owner()
    async def backupdb_command(self, ctx: commands.Context):
        db.save_users()
        embed = make_embed(
            title="Backup",
            description="✅ users.json saved.",
        )
        await ctx.send(embed=embed)

    @commands.command(name="setprefix")
    @is_owner()
    async def setprefix_command(self, ctx: commands.Context, new_prefix: str):
        low = new_prefix.lower()
        if low in {"off", "none", "disable"}:
            db.set_second_prefix(None)
            await ctx.send("✅ Second prefix disabled. Only `ayo` works now.")
            return

        if len(new_prefix) > 3:
            await ctx.send("❌ Keep prefix short (1–3 chars).")
            return

        db.set_second_prefix(new_prefix)
        await ctx.send(
            f"✅ Second prefix set to `{new_prefix}`.\n"
            f"Examples: `{new_prefix}profile`, `{new_prefix} profile`, `{new_prefix}cash`."
        )

    @commands.command(name="botusers")
    @is_owner()
    async def botusers_command(self, ctx: commands.Context):
        users = db.get_users()
        total_users = len(users)
        total_cash = sum(u.get("cash", 0) for u in users.values())

        lines = []
        count_in_guild = 0
        if ctx.guild:
            for uid, pdata in users.items():
                member = ctx.guild.get_member(int(uid))
                if not member:
                    continue
                count_in_guild += 1
                lines.append(
                    f"{member} – `{pdata.get('cash', 0):,}` {CURRENCY_EMOJI}")
                if len(lines) >= 10:
                    break

        desc = (
            f"**Total bot users (global):** `{total_users}`\n"
            f"**Total cash (global):** `{total_cash:,} {CURRENCY_EMOJI}`\n")
        if ctx.guild:
            desc += f"**Users in this server with data:** `{count_in_guild}`"

        embed = make_embed(title="Bot Users Overview", description=desc)
        if lines:
            embed.add_field(
                name="Sample users in this server",
                value="\n".join(lines),
                inline=False,
            )
        await ctx.send(embed=embed)

    @commands.command(name="uinfo")
    @is_owner()
    async def uinfo_command(self, ctx: commands.Context, user_id: int):
        users = db.get_users()
        uid = str(user_id)
        pdata = users.get(uid)
        member = ctx.guild.get_member(user_id) if ctx.guild else None

        if not pdata:
            await ctx.send("No data found for that user ID.")
            return

        last_daily = pdata.get("daily_last", 0)
        last_daily_str = "Never"
        if last_daily:
            last_daily_str = f"<t:{int(last_daily)}:R>"

        desc = (
            f"**User ID:** `{user_id}`\n"
            f"**User:** {member.mention if member else 'Not in this server'}\n"
            f"💰 **Cash:** {pdata.get('cash', 0):,} {CURRENCY_EMOJI}\n"
            f"💍 **Married To:** {pdata.get('married_to', None)}\n"
            f"**Marriages Count:** {pdata.get('marriages', 0)}\n"
            f"**Last Daily:** {last_daily_str}")
        embed = make_embed(
            title="User Investigate",
            description=desc,
        )
        await ctx.send(embed=embed)

    @commands.command(name="setlog")
    @is_owner()
    async def setlog_command(self, ctx: commands.Context, log_type: str,
                             channel: discord.TextChannel):
        log_type = log_type.lower()
        if log_type not in {"cash", "games", "daily", "admin", "all"}:
            await ctx.send("Types: `cash`, `games`, `daily`, `admin`, `all`.")
            return

        if log_type == "all":
            for t in ["cash", "games", "daily", "admin"]:
                db.set_log_channel(t, channel.id)
        else:
            db.set_log_channel(log_type, channel.id)

        await ctx.send(
            f"✅ Log channel for `{log_type}` set to {channel.mention}.")

    @commands.command(name="logtest")
    @is_owner()
    async def logtest_command(self, ctx: commands.Context, log_type: str, *,
                              msg: str):
        embed = make_embed(
            title="Log Test",
            description=msg,
        )
        if ctx.guild:
            await send_log(self.bot, ctx.guild, log_type.lower(), embed)
            await ctx.send("Test log sent (if log channel is set).")
        else:
            await ctx.send("Must be used in a server.")

    # ========== GAMES ON/OFF ==========

    @commands.command(name="disablegames")
    @is_owner()
    async def disablegames_command(self, ctx: commands.Context):
        db.set_games_enabled(False)
        await ctx.send("✅ Games have been **disabled** for now.")

    @commands.command(name="enablegames")
    @is_owner()
    async def enablegames_command(self, ctx: commands.Context):
        db.set_games_enabled(True)
        await ctx.send("✅ Games are **enabled** again.")

    # ========== CASHALL ==========

    @commands.command(name="cashall")
    @is_owner()
    async def cashall_command(self, ctx: commands.Context, amount: int):
        if amount == 0:
            await ctx.send("Amount must be non-zero.")
            return

        users = db.get_users()
        for pdata in users.values():
            pdata["cash"] = pdata.get("cash", 0) + amount
        db.save_users()

        sign = "+" if amount > 0 else ""
        embed = make_embed(
            title="Cash All",
            description=
            f"✅ Gave **{sign}{amount:,} {CURRENCY_EMOJI}** to all registered users.",
        )
        await ctx.send(embed=embed)

    # ========== CLAIM EVENT CONTROL ==========

    @commands.command(name="setclaim")
    @is_owner()
    async def setclaim_command(self, ctx: commands.Context, amount: int):
        if amount <= 0:
            await ctx.send("Amount must be positive.")
            return

        db.set_claim(amount, duration_seconds=24 * 60 * 60)
        embed = make_embed(
            title="Claim Event Started",
            description=(f"✅ Claim enabled for 24h.\n"
                         f"Reward: **{amount:,} {CURRENCY_EMOJI}**\n"
                         f"Users can use `ayoclaim` once."),
        )
        await ctx.send(embed=embed)

    @commands.command(name="disableclaim")
    @is_owner()
    async def disableclaim_command(self, ctx: commands.Context):
        db.disable_claim()
        embed = make_embed(
            title="Claim Event Disabled",
            description="✅ Claim has been turned off.",
        )
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Owner(bot))

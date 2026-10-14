"""Real-money deposits through the AYO Easypaisa gateway.

ayo deposit <amount>   -> creates a payment order and DMs a "Pay now" link
ayo deposits           -> your last deposits
Paid orders are credited automatically as AYO Cash (COINS_PER_RS per rupee).

Env: GATEWAY_URL (e.g. https://pay.example.com or http://127.0.0.1:8080), GATEWAY_BOT_KEY, COINS_PER_RS
"""
import os

import aiohttp
import discord
from discord.ext import commands, tasks

from utils import db
from utils.common import make_embed, send_log

GATEWAY = os.getenv("GATEWAY_URL", "").rstrip("/")
BOT_KEY = os.getenv("GATEWAY_BOT_KEY", "")
COINS_PER_RS = int(os.getenv("COINS_PER_RS", "1000"))


class Deposit(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.session = None
        if GATEWAY and BOT_KEY:
            self.credit_loop.start()

    async def cog_unload(self):
        self.credit_loop.cancel()
        if self.session:
            await self.session.close()

    async def api(self, method, path, json=None):
        if self.session is None:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
        async with self.session.request(method, GATEWAY + path, json=json,
                                        headers={"X-Bot-Key": BOT_KEY}) as r:
            data = await r.json(content_type=None)
            return r.status, data

    @commands.command(name="deposit")
    async def deposit_command(self, ctx: commands.Context, amount: str = None):
        if not (GATEWAY and BOT_KEY):
            return await ctx.send(embed=make_embed("Deposit", "Deposits are not configured yet."))
        if amount is None:
            return await ctx.send(embed=make_embed(
                "Deposit", f"Usage: `ayo deposit <rupees>`\nRate: **Rs 1 = {COINS_PER_RS:,} AYO Cash**"))
        try:
            status, data = await self.api("POST", "/v1/bot/orders",
                                          {"discord_user_id": str(ctx.author.id), "amount": amount})
        except Exception:
            return await ctx.send(embed=make_embed("Deposit", "Payment server is offline. Try again later."))
        if status != 201:
            return await ctx.send(embed=make_embed("Deposit", data.get("error", "Could not create deposit.")))
        coins = int(float(data["amount"]) * COINS_PER_RS)
        emb = make_embed("💳 Deposit created",
                         f"Pay **Rs {data['amount']}** via Easypaisa to receive **{coins:,} AYO Cash**.\n"
                         f"Link expires in 30 minutes.\nOrder: `{data['id']}`")
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Pay now", url=data["pay_url"]))
        try:
            await ctx.author.send(embed=emb, view=view)
            await ctx.send(embed=make_embed("Deposit", "Check your DMs for the payment link 📩"))
        except discord.Forbidden:
            await ctx.send(embed=emb, view=view)

    @commands.command(name="deposits")
    async def deposits_command(self, ctx: commands.Context):
        if not (GATEWAY and BOT_KEY):
            return await ctx.send(embed=make_embed("Deposits", "Deposits are not configured yet."))
        try:
            status, rows = await self.api("GET", f"/v1/bot/users/{ctx.author.id}/orders")
        except Exception:
            return await ctx.send(embed=make_embed("Deposits", "Payment server is offline."))
        if status != 200 or not rows:
            return await ctx.send(embed=make_embed("Deposits", "No deposits yet. Use `ayo deposit <rupees>`."))
        lines = [f"`{r['id']}` · Rs {r['amount']} · **{r['status']}**"
                 + (" · credited ✅" if r["credited"] else "") for r in rows]
        await ctx.send(embed=make_embed("Your deposits", "\n".join(lines)))

    @tasks.loop(seconds=20)
    async def credit_loop(self):
        """Credit paid orders exactly once: remember credited ids locally before acking."""
        try:
            status, rows = await self.api("GET", "/v1/bot/credits")
        except Exception:
            return
        if status != 200:
            return
        cfg = db.get_config()
        done = cfg.setdefault("credited_orders", [])
        for r in rows:
            oid = r["id"]
            if oid not in done:
                coins = r["amount_paisa"] * COINS_PER_RS // 100
                prof = db.get_profile(int(r["discord_user_id"]))
                prof["cash"] = prof.get("cash", 0) + coins
                done.append(oid)
                db.save_users()
                db.save_config()
                await self.announce(r, coins)
            try:
                await self.api("POST", f"/v1/bot/credits/{oid}/ack")
            except Exception:
                pass   # retried next loop; local list prevents double credit
        if len(done) > 5000:
            del done[:-5000]
            db.save_config()

    @credit_loop.before_loop
    async def before(self):
        await self.bot.wait_until_ready()

    async def announce(self, r, coins):
        user = self.bot.get_user(int(r["discord_user_id"]))
        emb = make_embed("✅ Deposit received",
                         f"Rs {r['amount']} received · **{coins:,} AYO Cash** added.\nTrx: `{r['payment_tid']}`")
        if user:
            try:
                await user.send(embed=emb)
            except discord.HTTPException:
                pass
        for guild in self.bot.guilds:
            if guild.get_member(int(r["discord_user_id"])):
                log = make_embed("Deposit credited",
                                 f"<@{r['discord_user_id']}> · Rs {r['amount']} → {coins:,} cash · order `{r['id']}`")
                try:
                    await send_log(self.bot, guild, "cash", log)
                except Exception:
                    pass
                break


async def setup(bot):
    await bot.add_cog(Deposit(bot))

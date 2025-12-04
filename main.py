import os
import discord
from discord.ext import commands

from utils import db

TOKEN = os.getenv("DISCORD_TOKEN")

INTENTS = discord.Intents.default()
INTENTS.message_content = True
INTENTS.members = True

# Init DB at startup
db.init_db()


def dynamic_prefix(bot, message):
    # Permanent prefixes
    prefixes = ["ayo ", "ayo"]  # with space + without space

    # 2nd prefix from DB (global / custom)
    second = db.get_second_prefix()
    if second:
        prefixes.append(second + " ")
        prefixes.append(second)

    return prefixes


class AyoBot(commands.Bot):

    async def setup_hook(self):
        # Load all cogs here
        await self.load_extension("cogs.economy")
        await self.load_extension("cogs.games")
        await self.load_extension("cogs.owner")
        await self.load_extension("cogs.blackjack")
        await self.load_extension("cogs.crash")
        await self.load_extension("cogs.coinflip")
        await self.load_extension("cogs.global_crash")


bot = AyoBot(
    command_prefix=dynamic_prefix,
    intents=INTENTS,
    help_command=None,
)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} ({bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="ayo help • AYO Cash")
                              )


if __name__ == "__main__":
    if not TOKEN:
        print("DISCORD_TOKEN env var missing.")
    else:
        bot.run(TOKEN)

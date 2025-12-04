import discord
from . import db


def make_embed(title: str = None, description: str = None) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=description,
        color=0x000000,  # pure black aesthetic
    )
    embed.set_footer(text="AYO Cash • by Ali YT")
    return embed


def fmt_time(seconds: int) -> str:
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    parts = []
    if h > 0:
        parts.append(f"{h}h")
    if m > 0:
        parts.append(f"{m}m")
    if s > 0 or not parts:
        parts.append(f"{s}s")
    return " ".join(parts)


async def send_log(bot, guild, log_type: str, embed: discord.Embed):
    channel_id = db.get_log_channel(log_type)
    if not channel_id:
        return
    channel = guild.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except Exception:
            return
    try:
        await channel.send(embed=embed)
    except Exception:
        pass

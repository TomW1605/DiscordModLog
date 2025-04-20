from datetime import datetime, timezone

import discord
from discord.ext import commands

# Replace with your bot's token and the channel ID where logs will be sent
BOT_TOKEN = "MTM2MzM4MDYzOTgxODMxNzk5NA.G85DB1.V8hgCZLfmrE4tlSVoK9a8AAAwRi-Cmddl9cpa4"
LOG_CHANNEL_ID = 1362708435447320737  # Replace with the ID of the channel to log actions

intents = discord.Intents.default()
intents.guilds = True
intents.guild_messages = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}!")

@bot.event
async def on_audit_log_entry_create(entry):
    guild = entry.guild
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    if not log_channel:
        return

    embed = discord.Embed(
        timestamp=entry.created_at,
        title=f"Unknown Action: {entry.action}",
        description=""
    )

    if entry.target:
        embed.description += f"**User:** {entry.target.nick or entry.target.display_name} (<@{entry.target.id}>)"
    embed.description += f"\n**Moderator:** {entry.user.nick or entry.user.display_name} (<@{entry.user.id}>)"

    if entry.action == discord.AuditLogAction.ban:
        embed.title="🚨 Ban Action"
        embed.colour=discord.Color.red()
        embed.description += f"\n**Reason:** {entry.reason or "No reason provided."}"

    elif entry.action == discord.AuditLogAction.unban:
        embed.title="✅ Unban Action"
        embed.colour=discord.Color.green()

    elif entry.action == discord.AuditLogAction.kick:
        embed.title="⚠️ Kick Action"
        embed.colour=discord.Color.orange()
        embed.description += f"\n**Reason:** {entry.reason or "No reason provided."}"

    elif entry.action == discord.AuditLogAction.member_update:
        if "timed_out_until" in entry.before.__dict__ and entry.before.timed_out_until != entry.after.timed_out_until:
            if entry.after.timed_out_until:
                timeout_duration = entry.after.timed_out_until - entry.created_at
                embed.title="⏳ Timeout Action"
                embed.colour=discord.Color.blue()
                embed.description += f"\n**Reason:** {entry.reason or "No reason provided."}"
                embed.description += f"\n**Timed Out For:** {timeout_duration}"
            else:
                embed.title="⏳ Timeout Removed"
                embed.colour=discord.Color.blue()

        if "mute" in entry.before.__dict__ and entry.before.mute != entry.after.mute:
            mute_status = "Muted" if entry.after.mute else "Unmuted"
            embed.title=f"🔇 {mute_status} Action"
            embed.colour=discord.Color.orange()

    elif entry.action == discord.AuditLogAction.member_disconnect:
        embed.title="🔊 User Disconnected"
        embed.colour=discord.Color.dark_red()

    elif entry.action == discord.AuditLogAction.message_delete:
        embed.title = "🗑️ Message Deleted"
        embed.colour = discord.Color.dark_red()
        embed.description += f"\n**Channel:** <#{entry.extra.channel.id}>"

    message = await log_channel.send(embed=embed)
    print(message)

bot.run(BOT_TOKEN)
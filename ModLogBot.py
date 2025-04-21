from datetime import datetime, timedelta

import discord
from discord.ext import commands
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, func
from sqlalchemy.orm import sessionmaker, declarative_base

# Replace with your bot's token and the channel ID where logs will be sent
BOT_TOKEN = "MTM2MzM4MDYzOTgxODMxNzk5NA.G85DB1.V8hgCZLfmrE4tlSVoK9a8AAAwRi-Cmddl9cpa4"
LOG_CHANNEL_ID = 1362708435447320737  # Replace with the ID of the channel to log actions

intents = discord.Intents.default()
intents.guilds = True
intents.guild_messages = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

class ActionType:
    UNKNOWN = 0
    BAN = 1
    UNBAN = 2
    KICK = 3
    TIMEOUT = 4
    TIMEOUT_REMOVED = 5
    MUTED = 6
    UNMUTED = 7
    MEMBER_DISCONNECT = 8
    MESSAGE_DELETE = 9
    WARNING = 10

# Database setup
Base = declarative_base()
engine = create_engine("sqlite:///mod_logs.db")
Session = sessionmaker(bind=engine)
session = Session()

# Log model
class Log(Base):
    __tablename__ = "logs"
    log_id = Column(Integer, primary_key=True, autoincrement=True)
    log_time = Column(DateTime, nullable=False)
    mod_user_id = Column(Integer, nullable=False)
    target_user_id = Column(Integer, nullable=True)
    log_message_id = Column(Integer, nullable=False)
    action_type = Column(Integer, nullable=False)
    reason = Column(String, nullable=True)
    timeout_end_time = Column(DateTime, nullable=True)
    channel_id = Column(Integer, nullable=True)

# Create the table
Base.metadata.create_all(engine)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}!")

@bot.event
async def on_audit_log_entry_create(entry):
    guild = entry.guild
    log_channel = guild.get_channel(LOG_CHANNEL_ID)

    action_type = ActionType.UNKNOWN
    reason = entry.reason
    timeout_end_time = None
    channel_id = None

    embed = discord.Embed(
        timestamp=entry.created_at,
        title=f"Unknown Action: {entry.action}",
        description=""
    )

    if isinstance(entry.target, discord.Member):
        embed.description += f"**User:** {entry.target.nick or entry.target.display_name} (<@{entry.target.id}>)"
    embed.description += f"\n**Moderator:** {entry.user.nick or entry.user.display_name} (<@{entry.user.id}>)"

    if entry.action == discord.AuditLogAction.ban:
        embed.title="🚨 Ban Action"
        embed.colour=discord.Color.red()
        embed.description += f"\n**Reason:** {entry.reason or "No reason provided."}"
        action_type = ActionType.BAN

    elif entry.action == discord.AuditLogAction.unban:
        embed.title="✅ Unban Action"
        embed.colour=discord.Color.green()
        action_type = ActionType.UNBAN

    elif entry.action == discord.AuditLogAction.kick:
        embed.title="⚠️ Kick Action"
        embed.colour=discord.Color.orange()
        embed.description += f"\n**Reason:** {entry.reason or "No reason provided."}"
        action_type = ActionType.KICK

    elif entry.action == discord.AuditLogAction.member_update:
        if "timed_out_until" in entry.before.__dict__ and entry.before.timed_out_until != entry.after.timed_out_until:
            if entry.after.timed_out_until:
                timeout_duration = entry.after.timed_out_until - entry.created_at
                timeout_duration += timedelta(seconds=1)
                embed.title="⏳ Timeout Action"
                embed.colour=discord.Color.blue()
                embed.description += f"\n**Reason:** {entry.reason or "No reason provided."}"
                embed.description += f"\n**Timed Out For:** {str(timeout_duration).split('.')[0]}"
                action_type = ActionType.TIMEOUT
                timeout_end_time = entry.after.timed_out_until
            else:
                embed.title="⏳ Timeout Removed"
                embed.colour=discord.Color.blue()
                action_type = ActionType.TIMEOUT_REMOVED

        if "mute" in entry.before.__dict__ and entry.before.mute != entry.after.mute:
            mute_status = "Muted" if entry.after.mute else "Unmuted"
            embed.title=f"🔇 {mute_status} Action"
            embed.colour=discord.Color.orange()
            action_type = ActionType.MUTED if entry.after.mute else ActionType.UNMUTED

    elif entry.action == discord.AuditLogAction.member_disconnect:
        embed.title="🔊 User Disconnected"
        embed.colour=discord.Color.dark_red()
        action_type = ActionType.MEMBER_DISCONNECT

    elif entry.action == discord.AuditLogAction.message_delete:
        embed.title = "🗑️ Message Deleted"
        embed.colour = discord.Color.dark_red()
        embed.description += f"\n**Channel:** <#{entry.extra.channel.id}>"
        action_type = ActionType.MESSAGE_DELETE
        channel_id = entry.extra.channel.id

    if entry.target:
        results = (
            session.query(Log.action_type, func.count(Log.action_type))
            .filter(Log.target_user_id == entry.target.id)
            .filter(Log.log_time >= datetime.now() - timedelta(days=30))
            .group_by(Log.action_type)
            .all()
        )
        actions = {action_type: count for action_type, count in results}
        warnings = actions.get(ActionType.WARNING, 0) + (1 if action_type == ActionType.WARNING else 0)
        deleted_messages = actions.get(ActionType.MESSAGE_DELETE, 0) + (1 if action_type == ActionType.MESSAGE_DELETE else 0)
        timeouts = actions.get(ActionType.TIMEOUT, 0) + (1 if action_type == ActionType.TIMEOUT else 0)
        embed.set_footer(text=f"Warnings: {warnings} | Deleted Messages: {deleted_messages} | Timeouts: {timeouts}")

    message = None
    if log_channel:
        message = await log_channel.send(embed=embed)

    # Save the log to the database
    log_entry = Log(
        log_time=entry.created_at,
        mod_user_id=entry.user.id,
        target_user_id=entry.target.id if entry.target else None,
        log_message_id=message.id if message else None,
        action_type=action_type,
        reason=reason,
        timeout_end_time=timeout_end_time,
        channel_id=channel_id
    )
    session.add(log_entry)
    session.commit()

bot.run(BOT_TOKEN)
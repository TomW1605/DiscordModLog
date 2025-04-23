import os
import shutil
from datetime import datetime, timedelta
from typing import Optional, Literal

import discord
import yaml
from discord.ext import commands
from sqlalchemy import create_engine, Column, Integer, String, DateTime, func, JSON
from sqlalchemy.orm import sessionmaker, declarative_base

intents = discord.Intents.default()
intents.guilds = True
intents.guild_messages = True
intents.members = True
intents.message_content = True

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
os.makedirs('/config', exist_ok=True)
Base = declarative_base()
engine = create_engine("sqlite:////config/mod_logs.db")
Session = sessionmaker(bind=engine)
session = Session()

# Config setup
if not os.path.exists('/config/config.yml'):
    shutil.copyfile("config.example.yml", "/config/config.yml")

with open("/config/config.yml", mode='r') as f:
    config = yaml.safe_load(f)

BOT_TOKEN = os.getenv('BOT_TOKEN', None)
if BOT_TOKEN is None:
    try:
        BOT_TOKEN = config["bot"]["token"]
    except KeyError:
        pass
if BOT_TOKEN is None:
    raise ValueError("BOT_TOKEN is not set in config.yml or environment variables.")

SERVERS = {}
for server in config["servers"]:
    if config["servers"][server]["id"] and config["servers"][server]["log_channel_id"]:
        server_id = config["servers"][server]["id"]
        log_channel_id = config["servers"][server]["log_channel_id"]
        try:
            server_id = int(server_id)
        except ValueError:
            print(f"Server ID `{server_id}` is not a valid server ID. Skipping.")
            continue
        try:
            log_channel_id = int(log_channel_id)
        except ValueError:
            print(f"Log Channel ID `{log_channel_id}` is not a valid channel ID. Skipping.")
            continue

        SERVERS[server_id] = {
            "name": server,
            "log_channel_id": log_channel_id
        }

# Log model
class Log(Base):
    __tablename__ = "logs"
    log_id = Column(Integer, primary_key=True, autoincrement=True)
    log_time = Column(DateTime, nullable=False)
    guild_id = Column(Integer, nullable=False)
    mod_user_id = Column(Integer, nullable=False)
    target_user_id = Column(Integer, nullable=True)
    log_message_id = Column(Integer, nullable=True)
    action_type = Column(Integer, nullable=False)
    log_data = Column(JSON, nullable=False)

# Create the table
Base.metadata.create_all(engine)

def delete_old_logs():
    # Calculate the cutoff date (3 months ago)
    cutoff_date = datetime.now() - timedelta(days=90)

    # Query and delete logs older than the cutoff date
    old_logs = session.query(Log).filter(Log.log_time < cutoff_date).all()
    for log in old_logs:
        session.delete(log)

    # Commit the changes to the database
    session.commit()

def get_server(server_id: int):
    try:
        return SERVERS[server_id]
    except KeyError:
        print(f"Server with ID {server_id} not found in config")
        return None

def get_log_channel_id(server_id: int):
    try:
        return get_server(server_id)['log_channel_id']
    except TypeError:
        return None

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}!")

@bot.event
async def on_audit_log_entry_create(entry):
    guild = entry.guild
    log_channel = guild.get_channel(get_log_channel_id(guild.id))

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

    log_data = {}

    if entry.action == discord.AuditLogAction.ban:
        embed.title="🚨 Ban Action"
        embed.colour=discord.Color.red()
        embed.description += f"\n**Reason:** {entry.reason or 'No reason provided.'}"
        action_type = ActionType.BAN
        log_data["reason"] = entry.reason

    elif entry.action == discord.AuditLogAction.unban:
        embed.title="✅ Unban Action"
        embed.colour=discord.Color.green()
        action_type = ActionType.UNBAN

    elif entry.action == discord.AuditLogAction.kick:
        embed.title="🥾 Kick Action"
        embed.colour=discord.Color.orange()
        embed.description += f"\n**Reason:** {entry.reason or 'No reason provided.'}"
        action_type = ActionType.KICK
        log_data["reason"] = entry.reason

    elif entry.action == discord.AuditLogAction.member_update:
        if "timed_out_until" in entry.before.__dict__ and entry.before.timed_out_until != entry.after.timed_out_until:
            if entry.after.timed_out_until:
                timeout_duration = entry.after.timed_out_until - entry.created_at
                timeout_duration += timedelta(seconds=1)
                embed.title="⏳ Timeout Action"
                embed.colour=discord.Color.blue()
                embed.description += f"\n**Reason:** {entry.reason or 'No reason provided.'}"
                embed.description += f"\n**Timed Out For:** {str(timeout_duration).split('.')[0]}"
                action_type = ActionType.TIMEOUT
                log_data["reason"] = entry.reason
                log_data["timeout_end_time"] = entry.after.timed_out_until.isoformat()
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
        log_data["channel_id"] = entry.extra.channel.id

    if action_type == ActionType.UNKNOWN:
        return

    if isinstance(entry.target, discord.Member):
        results = (
            session.query(Log.action_type, func.count(Log.action_type))
            .filter(Log.guild_id == guild.id)
            .filter(Log.target_user_id == entry.target.id)
            .filter(Log.log_time >= datetime.now() - timedelta(days=30))
            .group_by(Log.action_type)
            .all()
        )
        actions = {action_type: count for action_type, count in results}
        warnings = actions.get(ActionType.WARNING, 0)
        deleted_messages = actions.get(ActionType.MESSAGE_DELETE, 0) + (1 if action_type == ActionType.MESSAGE_DELETE else 0)
        timeouts = actions.get(ActionType.TIMEOUT, 0) + (1 if action_type == ActionType.TIMEOUT else 0)
        embed.set_footer(text=f"Warnings: {warnings} | Deleted Messages: {deleted_messages} | Timeouts: {timeouts}")

    message = None
    if log_channel:
        message = await log_channel.send(embed=embed)
    else:
        print("No log channel set, skipping log message.")

    # Save the log to the database
    log_entry = Log(
        log_time=entry.created_at,
        guild_id=guild.id,
        mod_user_id=entry.user.id,
        target_user_id=entry.target.id if isinstance(entry.target, discord.Member) else None,
        log_message_id=message.id if message else None,
        action_type=action_type,
        log_data=log_data,
    )
    session.add(log_entry)
    session.commit()

    if log_channel:
        if (action_type in [ActionType.MUTED, ActionType.MEMBER_DISCONNECT, ActionType.MESSAGE_DELETE] or
                (action_type in [ActionType.BAN, ActionType.KICK, ActionType.TIMEOUT] and entry.reason is None)):
            await log_channel.send(f"Hey <@{entry.user.id}>, can you add some context to this action?")
    else:
        print("No log channel set, skipping mod tag message.")

    delete_old_logs()

@bot.command()
@commands.guild_only()
@commands.is_owner()
async def sync(ctx: commands.Context, guilds: commands.Greedy[discord.Object], spec: Optional[Literal["~", "*", "^"]] = None) -> None:
    if not guilds:
        if spec == "~":
            synced = await ctx.bot.tree.sync(guild=ctx.guild)
        elif spec == "*":
            ctx.bot.tree.copy_global_to(guild=ctx.guild)
            synced = await ctx.bot.tree.sync(guild=ctx.guild)
        elif spec == "^":
            ctx.bot.tree.clear_commands(guild=ctx.guild)
            await ctx.bot.tree.sync(guild=ctx.guild)
            synced = []
        else:
            synced = await ctx.bot.tree.sync()

        await ctx.send(
            f"Synced {len(synced)} commands {'globally' if spec is None else 'to the current guild.'}"
        )
        return

    ret = 0
    for guild in guilds:
        try:
            await ctx.bot.tree.sync(guild=guild)
        except discord.HTTPException:
            pass
        else:
            ret += 1

    await ctx.send(f"Synced the tree to {ret}/{len(guilds)}.")

@bot.tree.command()
async def warn(interaction: discord.Interaction, user: discord.Member, reason: str) -> None:
    guild = interaction.guild
    log_channel = guild.get_channel(get_log_channel_id(guild.id))

    embed = discord.Embed(
        timestamp=interaction.created_at,
        title=f"⚠️ Warning Issued",
        description="",
        colour=discord.Color.yellow()
    )
    embed.description += f"**User:** {user.nick or user.display_name} (<@{user.id}>)"
    embed.description += f"\n**Moderator:** {interaction.user.nick or interaction.user.display_name} (<@{interaction.user.id}>)"
    embed.description += f"\n**Reason:** {reason}"

    log_data = {"reason": reason}

    if user:
        results = (
            session.query(Log.action_type, func.count(Log.action_type))
            .filter(Log.guild_id == guild.id)
            .filter(Log.target_user_id == user.id)
            .filter(Log.log_time >= datetime.now() - timedelta(days=30))
            .group_by(Log.action_type)
            .all()
        )
        actions = {action_type: count for action_type, count in results}
        warnings = actions.get(ActionType.WARNING, 0) + 1
        deleted_messages = actions.get(ActionType.MESSAGE_DELETE, 0)
        timeouts = actions.get(ActionType.TIMEOUT, 0)
        embed.set_footer(text=f"Warnings: {warnings} | Deleted Messages: {deleted_messages} | Timeouts: {timeouts}")

    message = None
    if log_channel:
        message = await log_channel.send(embed=embed)
    else:
        print("No log channel set, skipping log message.")

    # Save the log to the database
    log_entry = Log(
        log_time=interaction.created_at,
        guild_id=guild.id,
        mod_user_id=interaction.user.id,
        target_user_id=user.id,
        log_message_id=message.id if message else None,
        action_type=ActionType.WARNING,
        log_data=log_data,
    )
    session.add(log_entry)
    session.commit()

    await interaction.response.send_message("Warning Logged", ephemeral=True)

    delete_old_logs()

@bot.tree.command()
async def history(interaction: discord.Interaction, user: discord.Member) -> None:
    guild = interaction.guild
    log_channel = guild.get_channel(get_log_channel_id(guild.id))

    embed = discord.Embed(
        timestamp=interaction.created_at,
        title=f"📜 User History",
        description="",
        colour=discord.Color.purple()
    )
    embed.description += f"**User:** {user.nick or user.display_name} (<@{user.id}>)"

    user_history = (
        session.query(Log)
        .filter(Log.guild_id == guild.id)
        .filter(Log.target_user_id == user.id)
        .filter(Log.log_time >= datetime.now() - timedelta(days=30))
        .all()
    )

    for item in user_history:
        action = item.action_type
        action_text = None
        if action == ActionType.BAN:
            action_text = "Ban"
        elif action == ActionType.KICK:
            action_text = "Kick"
        elif action == ActionType.TIMEOUT:
            action_text = "Timeout"
        elif action == ActionType.MESSAGE_DELETE:
            action_text = "Message Deleted"
        elif action == ActionType.WARNING:
            action_text = "Warning"

        if action_text:
            if guild.id and get_log_channel_id(guild.id) and item.log_message_id:
                embed.description += f"\n**{action_text}:**  https://discord.com/channels/{guild.id}/{get_log_channel_id(guild.id)}/{item.log_message_id}"
            else:
                embed.description += f"\n**{action_text}**"

    results = (
        session.query(Log.action_type, func.count(Log.action_type))
        .filter(Log.guild_id == guild.id)
        .filter(Log.target_user_id == user.id)
        .filter(Log.log_time >= datetime.now() - timedelta(days=30))
        .group_by(Log.action_type)
        .all()
    )
    actions = {action_type: count for action_type, count in results}
    warnings = actions.get(ActionType.WARNING, 0)
    deleted_messages = actions.get(ActionType.MESSAGE_DELETE, 0)
    timeouts = actions.get(ActionType.TIMEOUT, 0)
    embed.set_footer(text=f"Warnings: {warnings} | Deleted Messages: {deleted_messages} | Timeouts: {timeouts}")

    if log_channel:
        await log_channel.send(embed=embed)
    else:
        print("No log channel set, skipping log message.")

    await interaction.response.send_message(embed=embed, ephemeral=True)

bot.run(BOT_TOKEN)

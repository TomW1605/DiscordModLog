import os
import shutil
from datetime import datetime, timedelta
from typing import Optional, Literal

import discord
import sqlalchemy
import yaml
from discord.ext import commands
from sqlalchemy import create_engine, Column, Integer, DateTime, func, JSON
from sqlalchemy.orm import sessionmaker, declarative_base

BUILD_DATE = os.getenv('BUILD_DATE', None)
VERSION = os.getenv('VERSION', None)

intents = discord.Intents.default()
intents.guilds = True
intents.guild_messages = True
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

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
    NICKNAME_CHANGED = 11

need_reason = [
    ActionType.MUTED,
    ActionType.MEMBER_DISCONNECT,
    ActionType.MESSAGE_DELETE,
    ActionType.NICKNAME_CHANGED,
    ActionType.BAN,
    ActionType.KICK,
    ActionType.TIMEOUT
]

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

def check_config():
    servers = {}
    for server in config["servers"]:
        if config["servers"][server]["id"] and config["servers"][server]["log_channel_id"]:
            server_id = config["servers"][server]["id"]
            try:
                server_id = int(server_id)
            except ValueError:
                print(f"Server ID `{server_id}` is not a valid server ID. Skipping.")
                continue

            log_channel_id = config["servers"][server]["log_channel_id"]
            try:
                log_channel_id = int(log_channel_id)
            except ValueError:
                print(f"Log Channel ID `{log_channel_id}` is not a valid channel ID. Skipping.")
                continue

            report_channel_id = config["servers"][server].get("report_channel_id", None)
            try:
                report_channel_id = int(report_channel_id)
            except (ValueError, TypeError):
                print(f"Report Channel ID `{log_channel_id}` is not a valid channel ID. Skipping.")
                pass

            ignored_channels = []
            if "ignored_channels" in config["servers"][server]:
                for ignored_channel in config["servers"][server]["ignored_channels"]:
                    try:
                        ignored_channels.append(int(ignored_channel))
                    except ValueError:
                        print(f"Ignored Channel ID `{ignored_channel}` is not a valid channel ID. Skipping.")

            servers[server_id] = {
                "name": server,
                "log_channel_id": log_channel_id,
                "report_channel_id": report_channel_id,
                "ignored_channels": ignored_channels
            }
    return servers
SERVERS = check_config()

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

def verify_db_tables(conn, metadata):
    """checks that the tables declared in metadata are actually in the db"""
    for table in metadata.tables.values():
        check = sqlalchemy.MetaData()
        check.reflect(conn, table.schema, True, (table.name,))
        check = check.tables[table.key]
        for column in table.c:
            if column.name not in check.c:
                raise Exception("table %s does not contain column %s" %
                                (table.key, column.name))
            check_column = check.c[column.name]
            if not isinstance(check_column.type, column.type.__class__):
                raise Exception("column %s.%s is %s but expected %s" %
                                (table.key, column.name, check_column.type, column.type))

verify_db_tables(engine.connect(), Base.metadata)

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
    except KeyError:
        print(f"Log channel ID not found for server {server_id}")
        return None
    except TypeError:
        return None

def get_ignored_channels(server_id: int):
    try:
        return get_server(server_id)['ignored_channels']
    except KeyError:
        print(f"Ignored channel not found for server {server_id}")
        return []
    except TypeError:
        return []

@bot.event
async def on_ready():
    print(f"Build date: {BUILD_DATE}")
    print(f"Version: {VERSION}")
    print(f"Logged in as {bot.user}!")

@bot.event
async def on_audit_log_entry_create(entry):
    guild = entry.guild
    log_channel = guild.get_channel(get_log_channel_id(guild.id))

    able_to_send = True
    if not log_channel:
        able_to_send = False
        print(f"Log channel not found for guild '{guild.name}' ({guild.id}). Skipping log message.")
    else:
        permissions = log_channel.permissions_for(guild.me)
        if not (permissions.send_messages and permissions.embed_links):
            able_to_send = False
            print(f"Bot does not have permission to send messages and embed links in log channel '{log_channel.name}' ({log_channel.id}). Skipping log message.")

    action_type = ActionType.UNKNOWN

    embed = discord.Embed(
        timestamp=entry.created_at,
        title=f"Unknown Action: {entry.action}",
        description=""
    )

    if isinstance(entry.target, discord.Member):
        embed.description += f"**User:** {entry.target.nick or entry.target.display_name} (<@{entry.target.id}>)"
    elif isinstance(entry.target, discord.User):
        embed.description += f"**User:** {entry.target.display_name} (<@{entry.target.id}>)"
    elif hasattr(entry, 'target') and hasattr(entry.target, 'id'):
        try:
            entry.target = await bot.fetch_user(entry.target.id)
            if entry.target:
                embed.description += f"**User:** {entry.target.display_name} (<@{entry.target.id}>)"
            else:
                embed.description += f"**User:** <@{entry.target.id}>"
        except discord.NotFound:
            embed.description += f"**User:** <@{entry.target.id}> (User not found)"
    embed.description += f"\n**Moderator:** {entry.user.nick or entry.user.display_name} (<@{entry.user.id}>)"

    log_data = {}

    if entry.action == discord.AuditLogAction.ban:
        embed.title="🚨 Baned"
        embed.colour=discord.Colour.red()
        embed.description += f"\n**Reason:** {entry.reason or 'No reason provided.'}"
        action_type = ActionType.BAN
        log_data["reason"] = entry.reason

    elif entry.action == discord.AuditLogAction.unban:
        embed.title="✅ Unbaned"
        embed.colour=discord.Colour.red()
        action_type = ActionType.UNBAN

    elif entry.action == discord.AuditLogAction.kick:
        embed.title="🥾 Kicked"
        embed.colour=discord.Colour.red()
        embed.description += f"\n**Reason:** {entry.reason or 'No reason provided.'}"
        action_type = ActionType.KICK
        log_data["reason"] = entry.reason

    elif entry.action == discord.AuditLogAction.member_update:
        if "timed_out_until" in entry.before.__dict__ and entry.before.timed_out_until != entry.after.timed_out_until:
            if entry.after.timed_out_until:
                timeout_duration = entry.after.timed_out_until - entry.created_at
                timeout_duration += timedelta(seconds=1)
                embed.title="⏳ Timedout"
                embed.colour=discord.Colour.orange()
                embed.description += f"\n**Reason:** {entry.reason or 'No reason provided.'}"
                embed.description += f"\n**Timed Out For:** {str(timeout_duration).split('.')[0]}"
                action_type = ActionType.TIMEOUT
                log_data["reason"] = entry.reason
                log_data["timeout_end_time"] = entry.after.timed_out_until.isoformat()
            else:
                embed.title="⏳ Timeout Removed"
                embed.colour=discord.Colour.orange()
                action_type = ActionType.TIMEOUT_REMOVED

        if "mute" in entry.before.__dict__ and entry.before.mute != entry.after.mute:
            mute_status = "Muted" if entry.after.mute else "Unmuted"
            embed.title=f"🔇 {mute_status}"
            embed.colour=discord.Colour.purple()
            action_type = ActionType.MUTED if entry.after.mute else ActionType.UNMUTED

        if "nick" in entry.before.__dict__ and entry.before.nick != entry.after.nick and entry.target.id != entry.user.id:
            embed.title=f"📝 Nickname Changed"
            embed.colour=discord.Colour.purple()

            user = await bot.fetch_user(entry.target.id)

            embed.description += f"\n**Before:** {entry.before.nick or user.display_name}"
            embed.description += f"\n**After:** {entry.after.nick or user.display_name}"

            action_type = ActionType.NICKNAME_CHANGED

            log_data["old_nick"] = entry.before.nick or user.display_name
            log_data["new_nick"] = entry.after.nick or user.display_name

    elif entry.action == discord.AuditLogAction.member_disconnect:
        embed.title="🔊 Disconnected From Voice"
        embed.colour=discord.Colour.purple()
        action_type = ActionType.MEMBER_DISCONNECT

    elif entry.action == discord.AuditLogAction.message_delete:
        if entry.extra.channel.id in get_ignored_channels(guild.id):
            print(f"Message delete action ignored for channel `{entry.extra.channel.name} ({entry.extra.channel.id})` in guild `{guild.name} ({guild.id})`.")
            return
        embed.title = "🗑️ Message Deleted"
        embed.colour = discord.Colour.magenta()
        embed.description += f"\n**Channel:** <#{entry.extra.channel.id}>"
        action_type = ActionType.MESSAGE_DELETE
        log_data["channel_id"] = entry.extra.channel.id

    if action_type == ActionType.UNKNOWN:
        return

    if isinstance(entry.target, discord.Member) or isinstance(entry.target, discord.User):
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
        kicks = actions.get(ActionType.KICK, 0) + (1 if action_type == ActionType.KICK else 0)
        bans = actions.get(ActionType.BAN, 0) + (1 if action_type == ActionType.BAN else 0)
        embed.set_footer(text=f"Warnings: {warnings} | Deleted Messages: {deleted_messages} | Timeouts: {timeouts} | Kicks: {kicks} | Bans: {bans}")

    message = None
    if able_to_send:
        message = await log_channel.send(embed=embed)
        if action_type in need_reason and entry.reason is None:
            await log_channel.send(f"Hey <@{entry.user.id}>, can you add some context to this action?")
        elif not (isinstance(entry.target, discord.Member) or isinstance(entry.target, discord.User)):
            await log_channel.send(f"Hey <@{entry.user.id}>, can you add some context to this action?")

    # Save the log to the database
    log_entry = Log(
        log_time=entry.created_at,
        guild_id=guild.id,
        mod_user_id=entry.user.id,
        target_user_id=entry.target.id if isinstance(entry.target, discord.Member) or isinstance(entry.target, discord.User) else None,
        log_message_id=message.id if message else None,
        action_type=action_type,
        log_data=log_data,
    )
    session.add(log_entry)
    session.commit()

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

    able_to_send = True
    if not log_channel:
        able_to_send = False
        print(f"Log channel not found for guild '{guild.name}' ({guild.id}). Skipping log message.")
    else:
        permissions = log_channel.permissions_for(guild.me)
        if not (permissions.send_messages and permissions.embed_links):
            able_to_send = False
            print(f"Bot does not have permission to send messages and embed links in log channel '{log_channel.name}' ({log_channel.id}). Skipping log message.")

    embed = discord.Embed(
        timestamp=interaction.created_at,
        title=f"⚠️ Warning Issued",
        description="",
        colour=discord.Colour.yellow()
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
        kicks = actions.get(ActionType.KICK, 0)
        bans = actions.get(ActionType.BAN, 0)
        embed.set_footer(text=f"Warnings: {warnings} | Deleted Messages: {deleted_messages} | Timeouts: {timeouts} | Kicks: {kicks} | Bans: {bans}")

    message = None
    if able_to_send:
        message = await log_channel.send(embed=embed)

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
        colour=discord.Colour.light_grey()
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
    kicks = actions.get(ActionType.KICK, 0)
    bans = actions.get(ActionType.BAN, 0)
    embed.set_footer(text=f"Warnings: {warnings} | Deleted Messages: {deleted_messages} | Timeouts: {timeouts} | Kicks: {kicks} | Bans: {bans}")

    if log_channel:
        await log_channel.send(embed=embed)
    else:
        print("No log channel set, skipping log message.")

    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command()
async def version(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(f"Bot online\nVersion: {VERSION}\nBuild date: {BUILD_DATE}")

bot.run(BOT_TOKEN)

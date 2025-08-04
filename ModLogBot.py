import os
import shutil
from datetime import datetime, timedelta
from typing import Optional, Literal, List

import discord
import sqlalchemy
import yaml
from discord import app_commands
from discord.app_commands import Choice
from discord.ext import commands
from sqlalchemy import create_engine, Column, Integer, DateTime, func, JSON, BLOB
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

config_folder_path = "/config/"

# Database setup
if config_folder_path != "":
    os.makedirs(config_folder_path, exist_ok=True)
Base = declarative_base()
engine = create_engine(f"sqlite:///{config_folder_path}mod_logs.db")
Session = sessionmaker(bind=engine)
session = Session()

# Config setup
if not os.path.exists(f'{config_folder_path}config.yml'):
    shutil.copyfile("config.example.yml", f"{config_folder_path}config.yml")

def load_config():
    with open(f"{config_folder_path}config.yml", mode='r') as f:
        config = yaml.safe_load(f)
    return config
config = load_config()

BOT_TOKEN = os.getenv('BOT_TOKEN', None)
if BOT_TOKEN is None:
    try:
        BOT_TOKEN = config["bot"]["token"]
    except KeyError:
        pass
if BOT_TOKEN is None:
    raise ValueError("BOT_TOKEN is not set in config.yml or environment variables.")

def load_servers():
    servers = {}
    for server in config["servers"]:
        if config["servers"][server]["id"]:
            server_id = config["servers"][server]["id"]
            try:
                server_id = int(server_id)
            except ValueError:
                print(f"Server ID `{server_id}` is not a valid server ID. Skipping server.")
                continue

            log_channel_id = config["servers"][server].get("log_channel_id", None)
            try:
                log_channel_id = int(log_channel_id)
            except (ValueError, TypeError):
                print(f"Log Channel ID `{log_channel_id}` is not a valid channel ID. Logging disabled for server `{server_id}`.")

            report_channel_id = config["servers"][server].get("report_channel_id", None)
            try:
                report_channel_id = int(report_channel_id)
            except (ValueError, TypeError):
                print(f"Report Channel ID `{report_channel_id}` is not a valid channel ID. Reporting disabled for server `{server_id}`")

            report_role_ping_id = config["servers"][server].get("report_role_ping_id", None)
            try:
                report_role_ping_id = int(report_role_ping_id)
            except (ValueError, TypeError):
                print(f"Report Ping ID `{report_role_ping_id}` is not a valid ID. Report pings disabled for server `{server_id}`")

            ignored_channels = []
            if "ignored_channels" in config["servers"][server]:
                for ignored_channel in config["servers"][server]["ignored_channels"]:
                    try:
                        ignored_channels.append(int(ignored_channel))
                    except (ValueError, TypeError):
                        print(f"Ignored Channel ID `{ignored_channel}` is not a valid channel ID. Skipping channel.")

            servers[server_id] = {
                "name": server,
                "log_channel_id": log_channel_id,
                "report_channel_id": report_channel_id,
                "report_role_ping_id": report_role_ping_id,
                "ignored_channels": ignored_channels
            }
    return servers
SERVERS = None

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
    log_attachment = Column(BLOB, nullable=True)

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

def get_report_channel_id(server_id: int):
    try:
        return get_server(server_id)['report_channel_id']
    except KeyError:
        print(f"Report channel ID not found for server {server_id}")
        return None
    except TypeError:
        return None

def get_report_role_ping_id(server_id: int):
    try:
        return get_server(server_id)['report_role_ping_id']
    except KeyError:
        print(f"Report ping ID not found for server {server_id}")
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
        comment = ""
        if (
                (action_type in need_reason and entry.reason is None) or
                (not (isinstance(entry.target, discord.Member) or isinstance(entry.target, discord.User)))
        ):
            comment = f"Hey <@{entry.user.id}>, can you add some context to this action?"
        message = await log_channel.send(comment, embed=embed)

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

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if isinstance(message.channel, discord.DMChannel):
        await handle_dm(message)

    if isinstance(message.guild, discord.Guild):
        await handle_guild_message(message)

    await bot.process_commands(message)

async def handle_dm(message):
    print(f"Received DM from {message.author.name}: {message.content}")
    await message.reply("Thank you for your message! Please use the `/report` command to report issues", mention_author=False)

async def handle_guild_message(message):
    pass

@bot.command()
# @commands.guild_only()
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

@bot.command()
@commands.is_owner()
async def reload_servers(ctx: commands.Context) -> None:
    global config
    config = load_config()
    global SERVERS
    SERVERS = load_servers()
    await ctx.send(f"Servers reloaded.")

@bot.tree.command(description="Log a warning to a user (does not send a message to the user)")
@app_commands.guild_only()
@app_commands.describe(
    user="User warned",
    reason="Reason for the warning",
    attachment="Attachment related to the warning (image, etc., optional)"
)
async def warn(interaction: discord.Interaction, user: discord.Member, reason: str, attachment: discord.Attachment=None) -> None:
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

    file = None
    if attachment:
        file = await attachment.to_file()
        if file.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
            embed.set_image(url=f"attachment://{file.filename}")

    log_data = {
        "reason": reason,
        "attachment_filename": attachment.filename if attachment else None,
    }

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
        message = await log_channel.send(embed=embed, file=file)

    # Save the log to the database
    log_entry = Log(
        log_time=interaction.created_at,
        guild_id=guild.id,
        mod_user_id=interaction.user.id,
        target_user_id=user.id,
        log_message_id=message.id if message else None,
        action_type=ActionType.WARNING,
        log_data=log_data,
        log_attachment=await attachment.read() if attachment else None,
    )
    session.add(log_entry)
    session.commit()

    await interaction.response.send_message("Warning Logged", ephemeral=True)

    delete_old_logs()

@bot.tree.command(description="View the moderation history of a user")
@app_commands.guild_only()
@app_commands.describe(user="User to view history for")
async def history(interaction: discord.Interaction, user: discord.Member | discord.User) -> None:
    guild = interaction.guild
    log_channel = guild.get_channel(get_log_channel_id(guild.id))

    embed = discord.Embed(
        timestamp=interaction.created_at,
        title=f"📜 User History",
        description="",
        colour=discord.Colour.light_grey()
    )
    mod = interaction.user
    embed.description += f"**Requester:** {mod.nick or mod.display_name} (<@{mod.id}>)"
    embed.description += f"\n**User:** {getattr(user, 'nick', None) or user.display_name} (<@{user.id}>)"
    if not isinstance(user, discord.Member):
        embed.description += f"\n**User is not currently a member of this server**"

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
        if interaction.channel.id == log_channel.id:
            await interaction.response.send_message(embed=embed)
        else:
            await log_channel.send(embed=embed)
            await interaction.response.send_message(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(description="Send a report to server staff")
@app_commands.dm_only()
@app_commands.describe(
    server="Server to report in",
    report_comment="The report itself",
    user="User to report (optional)",
    message_link="Link to the message being reported (optional)",
    attachment="Attachment related to the report (optional)"
)
async def report(
        interaction: discord.Interaction,
        server: str,
        report_comment: str,
        user: discord.User = None,
        message_link: str=None,
        attachment: discord.Attachment=None
) -> None:
    print(interaction.data)
    if not server.isdigit() or int(server) not in SERVERS:
        for mutual_server in interaction.user.mutual_guilds:
            if mutual_server.name == server:
                server = mutual_server.id
                break

    if not server.isdigit() or int(server) not in SERVERS:
        print(f"Invalid server ID: {server}")
        await interaction.response.send_message("Invalid server selected. If you took some time to submit yor report, the server selection may have timed out. Please edit your report and select the server again.")
        return

    report_channel_id = get_report_channel_id(int(server))
    if not report_channel_id:
        print(f"Report channel not set for server `{server}`.")
        await interaction.response.send_message("Report channel not set for this server.")
        return

    report_channel = bot.get_channel(report_channel_id)
    if not report_channel:
        print(f"Report channel with ID `{report_channel_id}` not found in server `{server}`.")
        await interaction.response.send_message("Report channel not found.")
        return

    report_role_ping_id = get_report_role_ping_id(int(server))

    embed = discord.Embed(
        timestamp=interaction.created_at,
        title=f"Member Report",
        description=""
    )

    embed.description += f"**Reporter:** {interaction.user.display_name} (<@{interaction.user.id}>)"
    if user:
        embed.description += f"\n**Reported User:** {user.display_name} (<@{user.id}>)"
    embed.description += f"\n**Comment:** {report_comment}"
    if message_link:
        embed.description += f"\n**Message:** {message_link}"
    if attachment:
        embed.set_image(url=attachment.url)

    if report_role_ping_id:
        await report_channel.send(f"<@&{report_role_ping_id}> Member Report", embed=embed)
    else:
        await report_channel.send(embed=embed)
    await interaction.response.send_message(f"Thank you for your report! It has been sent to the server staff.")

@report.autocomplete('server')
async def server_autocomplete(interaction: discord.Interaction, current: str) -> List[Choice[str]]:
    report_servers = [server_id for server_id, server in SERVERS.items() if server['report_channel_id'] is not None]
    mutual_servers = interaction.user.mutual_guilds
    # return [Choice(name=server.name, value=str(server.id)) for server in mutual_servers if server.id in report_servers]
    servers = [server for server in mutual_servers if server.id in report_servers]
    return [
        app_commands.Choice(name=server.name, value=str(server.id))
        for server in servers if current.lower() in server.name.lower()
    ]

@bot.tree.command(description="Check the bot version and build date")
async def version(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(f"Bot online\nVersion: {VERSION}\nBuild date: {BUILD_DATE}")

if __name__ == "__main__":
    verify_db_tables(engine.connect(), Base.metadata)

    # global SERVERS
    SERVERS = load_servers()
    bot.run(BOT_TOKEN)

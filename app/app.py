import os
import json
import asyncio
from datetime import datetime, UTC

import discord
from discord import app_commands
from discord.ext import commands

from modules.discord_api import call, get_posts_channel, send_request_post
from modules.modals.add_me import AddMeModal
from modules.modals.crunchy_simulcast import CrunchySimulcastModal
from modules.modals.hidive_simulcast import HidiveSimulcastModal
from modules.modals.media_request import MediaRequestModal
from modules.modals.queue_add import QueueAddModal
from modules.modals.remove_me import RemoveMeModal
from modules.modals.status_request import StatusRequestModal
from modules.views.bulk_action_confirm import BulkActionConfirmView, build_preview_embeds
from modules.views.report_pager import ReportPager, make_report_embeds
from modules.vars import (
    BOT_TOKEN,
    DONE_TAG_NAME,
    GUILD_ID,
    FETCH_ARCHIVED_PRIVATE,
    FETCH_ARCHIVED_PUBLIC,
    INCLUDE_ATTACHMENTS,
    INCLUDE_EMBED_URLS,
    MAX_MESSAGES_PER_THREAD,
    POST_CHANNEL_ID,
    REPORTS_DIR,
    SETTINGS_FILE,
    ensure_dirs,
    format_date,
    is_open_thread,
    is_mod,
    is_owner,
    load_settings,
    mention,
    next_report_id,
    report_path,
    save_json,
    save_settings,
    title_matches,
    thread_has_done_tag,
    to_utc,
)


intents = discord.Intents.default()
intents.guilds = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

queue_group = app_commands.Group(name="queue", description="Queue manager")
thread_export_group = app_commands.Group(name="thrdexp", description="Thread/posts exporter")
req_group = app_commands.Group(name="req", description="Create a request post in the posts channel")
posts_group = app_commands.Group(name="posts", description="Manage posts in the posts channel")


async def queue_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:

    settings = await load_settings()
    queue_map = settings.get("queue")

    if not isinstance(queue_map, dict) or len(queue_map) == 0:
        return []

    current = current.strip().lower()

    choices = []
    index = 1

    for user_key in queue_map:
        identifier_value = str(queue_map.get(user_key, "")).strip()

        if identifier_value != "":
            label = f"{index}. {user_key} - `{identifier_value}`"
        else:
            label = f"{index}. {user_key} - *(not set)*"

        label_lower = label.lower()
        user_key_lower = str(user_key).lower()

        if current != "":
            if current not in label_lower and current not in user_key_lower:
                index += 1
                continue

        # discord has a 100 character limit on autocomplete choices, so truncate if needed
        if len(label) > 100:
            label = label[:97] + "..."

        choices.append(app_commands.Choice(name=label, value=str(user_key)))

        if len(choices) >= 25:
            break

        index += 1

    return choices


@queue_group.command(name="add", description="Add a user to the queue (mods & owner only)")
async def queue_add(interaction: discord.Interaction, user: discord.User = None, plex: str | None = None) -> None:

    if not is_mod(interaction):
        await interaction.response.send_message("You are not authorized to use this command.", ephemeral=True)
        return

    if plex is not None:
        plex_value = str(plex).strip()
    else:
        plex_value = ""

    if plex_value != "":
        identifier_value = plex_value

        settings = await load_settings()
        queue_map = settings.get("queue")
        if not isinstance(queue_map, dict):
            queue_map = {}

        if user is not None:
            user_key = mention(user)
        else:
            user_key = f"{identifier_value} (not on discord)"

        previous = queue_map.get(user_key)
        queue_map[user_key] = identifier_value
        settings["queue"] = queue_map

        await save_settings(settings)

        if previous is None:
            msg = f"Added {user_key} to the queue with `{identifier_value}`."
        else:
            msg = f"Updated {user_key} in the queue to `{identifier_value}`."

        embed = discord.Embed(title="Queue Updated", description=msg)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    await interaction.response.send_modal(QueueAddModal(user))


@queue_group.command(name="remove", description="Remove a user from the queue (mods & owner only)")
@app_commands.autocomplete(entry=queue_autocomplete)
async def queue_remove(interaction: discord.Interaction, entry: str) -> None:

    if not is_mod(interaction):
        await interaction.response.send_message("You are not authorized to use this command.", ephemeral=True)
        return

    settings = await load_settings()
    queue_map = settings.get("queue")

    if not isinstance(queue_map, dict) or len(queue_map) == 0:
        await interaction.response.send_message("Queue is empty.", ephemeral=True)
        return

    entry_key = entry.strip()
    if entry_key == "":
        await interaction.response.send_message("Missing entry.", ephemeral=True)
        return

    if entry_key in queue_map:
        removed_value = queue_map.pop(entry_key)
        settings["queue"] = queue_map
        await save_settings(settings)

        embed = discord.Embed(
            title="Queue Updated",
            description=f"Removed {entry_key} (was `{removed_value}`)",
        )
    else:
        embed = discord.Embed(title="Not Found", description=f"{entry_key} is not in the queue.")

    await interaction.response.send_message(embed=embed, ephemeral=True)


@queue_group.command(name="show", description="Show the queue")
async def queue_show(interaction: discord.Interaction, hidden: bool = True) -> None:

    settings = await load_settings()
    queue_map = settings.get("queue")

    if not isinstance(queue_map, dict) or len(queue_map) == 0:
        await interaction.response.send_message("Queue is empty.", ephemeral=hidden)
        return

    lines = []
    index = 1

    for user_key in queue_map:
        identifier_value = str(queue_map.get(user_key, "")).strip()

        if identifier_value != "":
            lines.append(f"{index}. {user_key} - `{identifier_value}`")
        else:
            lines.append(f"{index}. {user_key} - *(not set)*")

        index += 1

    embed = discord.Embed(title="Queue", description="\n".join(lines))
    await interaction.response.send_message(embed=embed, ephemeral=hidden)


async def fetch_all_threads(forum_channel: discord.ForumChannel) -> list[discord.Thread]:

    # get active threads first (only returns unarchived threads, but thats most of what we want and is fast to fetch)
    threads = []
    for thread in list(forum_channel.threads):
        threads.append(thread)

    if FETCH_ARCHIVED_PUBLIC:
        async for thread in forum_channel.archived_threads(limit=None):
            threads.append(thread)

    if FETCH_ARCHIVED_PRIVATE:
        try:
            async for thread in forum_channel.archived_threads(limit=None, private=True):
                threads.append(thread)
        except TypeError:
            pass
        except discord.Forbidden:
            pass

    deduped = {}
    for thread in threads:
        deduped[thread.id] = thread

    out = []
    for thread_id in deduped:
        out.append(deduped[thread_id])

    return out


async def export_thread_dict(thread: discord.Thread) -> dict:

    limit = MAX_MESSAGES_PER_THREAD if MAX_MESSAGES_PER_THREAD is not None else 500

    messages: list[discord.Message] = []
    async for message in thread.history(limit=limit, oldest_first=False):
        if message.type not in (discord.MessageType.default, discord.MessageType.thread_starter_message):
            continue
        messages.append(message)

    # reverse to get oldest_first order, since we fetched with oldest_first=False to get the most recent messages faster
    messages.reverse()

    exported_messages = []
    for message in messages:
        msg_obj = {
            "id": message.id,
            "created_at": to_utc(message.created_at),
            "author": {"id": message.author.id, "name": str(message.author)},
            "content": message.content,
        }

        if INCLUDE_ATTACHMENTS:
            attachment_urls = []
            for attachment in message.attachments:
                attachment_urls.append(attachment.url)
            msg_obj["attachments"] = attachment_urls

        if INCLUDE_EMBED_URLS:
            embed_urls = []
            for embed in message.embeds:
                if getattr(embed, "url", None):
                    embed_urls.append(embed.url)
            msg_obj["embed_urls"] = embed_urls

        exported_messages.append(msg_obj)

    return {
        "thread_id": thread.id,
        "title": thread.name,
        "url": f"https://discord.com/channels/{thread.guild.id}/{thread.id}",
        "open": is_open_thread(thread),
        "archived": thread.archived,
        "locked": thread.locked,
        "created_at": to_utc(thread.created_at),
        "messages": exported_messages,
    }


async def get_channel(channel_id: int):

    channel = bot.get_channel(channel_id)
    if channel is not None:
        return channel

    try:
        fetched = await bot.fetch_channel(channel_id)
        return fetched
    except Exception:
        return None


async def report_id_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:

    settings = await load_settings()
    report_map = settings.get("thrdexp")

    if not isinstance(report_map, dict):
        return []

    current = current.strip().lower()

    keys = []
    for key in report_map.keys():
        keys.append(str(key))

    def sort_key(value: str):
        try:
            return (0, int(value))
        except Exception:
            return (1, value)

    keys.sort(key=sort_key)

    choices = []
    for key in keys:
        path = report_map.get(key)
        label = key
        if path:
            try:
                created = datetime.fromtimestamp(os.path.getmtime(path), tz=UTC)
                label = format_date(created, hour12=True)
            except Exception:
                label = key

        if current == "" or current in label.lower() or current in key.lower():
            choices.append(app_commands.Choice(name=label, value=key))
        if len(choices) >= 25:
            break

    return choices


@thread_export_group.command(name="create", description="Create an export report (owner only)")
async def thread_export_create(interaction: discord.Interaction, posts_channel_id: str | None = None) -> None:

    if not is_owner(interaction):
        await interaction.response.send_message("You are not authorized to use this command.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    if posts_channel_id is not None and str(posts_channel_id).strip() != "":
        raw_channel_id = str(posts_channel_id).strip()
    else:
        raw_channel_id = POST_CHANNEL_ID.strip()

    if raw_channel_id == "":
        await interaction.followup.send("Missing posts_channel_id and POST_CHANNEL_ID env var is not set.")
        return

    try:
        channel_id = int(raw_channel_id)
    except Exception:
        await interaction.followup.send(f"Invalid posts_channel_id: {raw_channel_id!r}")
        return

    channel = await get_channel(channel_id)
    if channel is None:
        await interaction.followup.send("Could not find that channel ID (bot not in server / no access / wrong ID).")
        return

    settings = await load_settings()
    report_map = settings.get("thrdexp")
    if not isinstance(report_map, dict):
        report_map = {}

    report_id = next_report_id(report_map)
    path = report_path(report_id)

    report = {
        "report_id": str(report_id),
        "created_at": to_utc(datetime.now(UTC)),
        "created_by": {"id": interaction.user.id, "name": str(interaction.user)},
        "channel": {"id": channel_id, "name": getattr(channel, "name", "unknown"), "type": str(type(channel))},
        "config": {},
    }

    if isinstance(channel, discord.ForumChannel):
        threads = await fetch_all_threads(channel)

        matching_threads = []
        for thread in threads:
            if title_matches(thread.name):
                matching_threads.append(thread)

        selected_threads = []
        for thread in matching_threads:
            if not thread_has_done_tag(thread):
                selected_threads.append(thread)

        selected_threads.sort(key=lambda thread: thread.created_at or datetime.min.replace(tzinfo=UTC))

        report["summary"] = {
            "total_threads_found": len(threads),
            "matching_threads": len(matching_threads),
            "selected_threads": len(selected_threads),
        }

        export_semaphore = asyncio.Semaphore(4)

        async def bounded_export(thread: discord.Thread):
            async with export_semaphore:
                try:
                    return await call(lambda: export_thread_dict(thread), label="thrdexp")
                except Exception as e:
                    return {
                        "thread_id": thread.id,
                        "title": thread.name,
                        "url": f"https://discord.com/channels/{thread.guild.id}/{thread.id}",
                        "error": f"{type(e).__name__}: {e}",
                    }

        exported_threads = await asyncio.gather(
            *[bounded_export(thread) for thread in selected_threads],
        )

        report["threads"] = exported_threads

    elif isinstance(channel, discord.TextChannel):
        messages: list[discord.Message] = []
        limit = MAX_MESSAGES_PER_THREAD if MAX_MESSAGES_PER_THREAD is not None else 500

        async for message in channel.history(limit=limit, oldest_first=True):
            if message.type != discord.MessageType.default:
                continue
            messages.append(message)

        exported = []
        for message in messages:
            msg_obj = {
                "id": message.id,
                "created_at": to_utc(message.created_at),
                "author": {"id": message.author.id, "name": str(message.author)},
                "content": message.content,
            }

            if INCLUDE_ATTACHMENTS:
                attachment_urls = []
                for attachment in message.attachments:
                    attachment_urls.append(attachment.url)
                msg_obj["attachments"] = attachment_urls

            exported.append(msg_obj)

        report["summary"] = {"messages_exported": len(exported)}
        report["messages"] = exported

    else:
        await interaction.followup.send(f"Unsupported channel type: {type(channel)}")
        return

    try:
        ensure_dirs()
        save_json(path, report)
    except Exception as e:
        await interaction.followup.send(f"Failed to write report to {path}: {e}")
        return

    report_map[str(report_id)] = path
    settings["thrdexp"] = report_map
    await save_settings(settings)

    embed = discord.Embed(
        title="Export Created",
        description=f"Created report `{report_id}` and saved it to `{path}`.",
    )

    summary = report.get("summary")
    if isinstance(summary, dict):
        for key in summary:
            embed.add_field(name=str(key), value=str(summary[key]), inline=True)

    await interaction.followup.send(embed=embed)


@thread_export_group.command(name="remove", description="Remove an export report (owner only)")
@app_commands.autocomplete(report_id=report_id_autocomplete)
async def thread_export_remove(interaction: discord.Interaction, report_id: str) -> None:

    if not is_owner(interaction):
        await interaction.response.send_message("You are not authorized to use this command.", ephemeral=True)
        return

    settings = await load_settings()
    report_map = settings.get("thrdexp")

    if not isinstance(report_map, dict) or len(report_map) == 0:
        await interaction.response.send_message("No reports exist.", ephemeral=True)
        return

    report_id = str(report_id).strip()
    path = report_map.get(report_id)

    if not path:
        await interaction.response.send_message(f"Report `{report_id}` not found.", ephemeral=True)
        return

    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception as e:
        await interaction.response.send_message(f"Failed to remove file `{path}`: {e}", ephemeral=True)
        return

    report_map.pop(report_id, None)
    settings["thrdexp"] = report_map
    await save_settings(settings)

    await interaction.response.send_message(f"Removed report `{report_id}` (deleted `{path}`).", ephemeral=True)


@thread_export_group.command(name="show", description="Show an export report (mods & owner only)")
@app_commands.autocomplete(report_id=report_id_autocomplete)
async def thread_export_show(interaction: discord.Interaction, report_id: str, hidden: bool = True) -> None:

    if not is_mod(interaction):
        await interaction.response.send_message("You are not authorized to use this command.", ephemeral=True)
        return

    settings = await load_settings()
    report_map = settings.get("thrdexp")

    if not isinstance(report_map, dict) or len(report_map) == 0:
        await interaction.response.send_message("No reports exist.", ephemeral=True)
        return

    report_id = str(report_id).strip()
    path = report_map.get(report_id)

    if not path:
        await interaction.response.send_message(f"Report `{report_id}` not found.", ephemeral=True)
        return

    if not os.path.exists(path):
        await interaction.response.send_message(f"Report file missing on disk: `{path}`", ephemeral=True)
        return

    try:
        with open(path, "r", encoding="utf-8") as handle:
            report = json.load(handle)
        if not isinstance(report, dict):
            report = {}
    except Exception as e:
        await interaction.response.send_message(f"Could not read report JSON: {e}", ephemeral=True)
        return

    embeds = make_report_embeds(report)

    if not isinstance(embeds, list) or len(embeds) == 0:
        await interaction.response.send_message("Report was empty or invalid.", ephemeral=True)
        return

    if len(embeds) == 1:
        await interaction.response.send_message(embed=embeds[0], ephemeral=hidden)
        return

    view = ReportPager(embeds, interaction.user.id)
    await interaction.response.send_message(embed=embeds[0], view=view, ephemeral=hidden)

    try:
        view.message = await interaction.original_response()
    except Exception:
        pass


@req_group.command(name="mediarequest", description="Make a normal media request")
@app_commands.describe(
    name="Title name (optional. if omitted a modal will ask)",
    url="TVDB/TMDB/Simkl link (optional. if omitted a modal will ask)",
    notes="Extra notes (optional)",
)
async def req_mediarequest(interaction: discord.Interaction, name: str | None = None, url: str | None = None, notes: str | None = None) -> None:

    if name is None or str(name).strip() == "" or url is None or str(url).strip() == "":
        await interaction.response.send_modal(MediaRequestModal())
        return

    user_mention = f"<@{interaction.user.id}>"

    name_value = str(name).strip()
    url_value = str(url).strip()

    notes_value = ""
    if notes is not None:
        notes_value = str(notes).strip()

    title = f"[MEDIA REQUEST]: {name_value}"
    body = (
        f'{user_mention} requests adding "{name_value}" to the server.\n'
        f"URL: {url_value}\n\n"
        "Extra notes by user:\n"
        f"{notes_value if notes_value != '' else '(none)'}"
    )

    await send_request_post(interaction, title, body, simkl_url=url_value)


@req_group.command(name="crunchysimulcast", description="Request a Crunchyroll simulcast")
@app_commands.describe(
    name="Title name (optional. if omitted a modal will ask)",
    infolink="TMDB/TVDB/Simkl link for the info card (optional. if omitted a modal will ask)",
    url="Crunchyroll link (optional. if omitted a modal will ask)",
    notes="Extra notes (optional)",
)
async def req_crunchysimulcast(interaction: discord.Interaction, name: str | None = None, infolink: str | None = None, url: str | None = None, notes: str | None = None) -> None:

    if (name is None or str(name).strip() == ""
            or infolink is None or str(infolink).strip() == ""
            or url is None or str(url).strip() == ""):
        await interaction.response.send_modal(CrunchySimulcastModal())
        return

    user_mention = f"<@{interaction.user.id}>"

    name_value = str(name).strip()
    url_value = str(url).strip()
    info_value = str(infolink).strip()

    notes_value = ""
    if notes is not None:
        notes_value = str(notes).strip()

    title = f'[MEDIA REQUEST]: Add simulcast "{name_value}"'
    body = (
        f'{user_mention} requests adding "{name_value}" from Crunchyroll to the auto downloader.\n'
        f"URL: {url_value}\n\n"
        "Extra notes by user:\n"
        f"{notes_value if notes_value != '' else '(none)'}"
    )

    await send_request_post(interaction, title, body, simkl_url=info_value)


@req_group.command(name="hidivesimulcast", description="Request a HiDive simulcast")
@app_commands.describe(
    name="Title name (optional. if omitted a modal will ask)",
    infolink="TMDB/TVDB/Simkl link for the info card (optional. if omitted a modal will ask)",
    url="HiDive link (optional. if omitted a modal will ask)",
    notes="Extra notes (optional)",
)
async def req_hidivesimulcast(interaction: discord.Interaction, name: str | None = None, infolink: str | None = None, url: str | None = None, notes: str | None = None) -> None:

    if (name is None or str(name).strip() == ""
            or infolink is None or str(infolink).strip() == ""
            or url is None or str(url).strip() == ""):
        await interaction.response.send_modal(HidiveSimulcastModal())
        return

    user_mention = f"<@{interaction.user.id}>"

    name_value = str(name).strip()
    url_value = str(url).strip()
    info_value = str(infolink).strip()

    notes_value = ""
    if notes is not None:
        notes_value = str(notes).strip()

    title = f'[MEDIA REQUEST]: Add simulcast "{name_value}"'
    body = (
        f'{user_mention} requests adding "{name_value}" from HiDive to the auto downloader.\n'
        f"URL: {url_value}\n\n"
        "Extra notes by user:\n"
        f"{notes_value if notes_value != '' else '(none)'}"
    )

    await send_request_post(interaction, title, body, simkl_url=info_value)


@req_group.command(name="statusrequest", description="Request the status of a title")
@app_commands.describe(
    name="Title name (optional. if omitted a modal will ask)",
    notes="Extra notes (optional)",
)
async def req_statusrequest(interaction: discord.Interaction, name: str | None = None, notes: str | None = None) -> None:

    if name is None or str(name).strip() == "":
        await interaction.response.send_modal(StatusRequestModal())
        return

    user_mention = f"<@{interaction.user.id}>"

    name_value = str(name).strip()

    notes_value = ""
    if notes is not None:
        notes_value = str(notes).strip()

    title = f'[STATUS REQUEST]: Whats the status of "{name_value}"?'
    body = (
        f'{user_mention} is requesting the status of "{name_value}".\n\n'
        "Extra notes by user:\n"
        f"{notes_value if notes_value != '' else '(none)'}"
    )

    await send_request_post(interaction, title, body)


@req_group.command(name="addme", description="Request to be added to the server")
@app_commands.describe(
    plexusername="Plex username/email (optional. if omitted a modal will ask)"
)
async def req_addme(interaction: discord.Interaction, plexusername: str | None = None) -> None:

    if plexusername is None or str(plexusername).strip() == "":
        await interaction.response.send_modal(AddMeModal())
        return

    user_mention = f"<@{interaction.user.id}>"
    plex_value = str(plexusername).strip()

    title = f'[ACCOUNT REQUEST]: Add user "{plex_value}"'
    body = (
        f"{user_mention} is requesting to be added to the server.\n"
        f"Plex username/email: {plex_value}"
    )

    await send_request_post(interaction, title, body)


@req_group.command(name="removeme", description="Request to be removed from the server")
@app_commands.describe(
    plexusername="Plex username/email (optional. if omitted a modal will ask)"
)
async def req_removeme(interaction: discord.Interaction, plexusername: str | None = None) -> None:

    if plexusername is None or str(plexusername).strip() == "":
        await interaction.response.send_modal(RemoveMeModal())
        return

    user_mention = f"<@{interaction.user.id}>"
    plex_value = str(plexusername).strip()

    title = f'[REMOVAL REQUEST]: Remove user "{plex_value}"'
    body = (
        f"{user_mention} is requesting to be removed from the server.\n"
        f"Plex username/email: {plex_value}"
    )

    await send_request_post(interaction, title, body)


@posts_group.command(name="closedone", description="Close all open posts that have the done/added/closed tag (owner only)")
@app_commands.describe(
    lock="Also lock each post after archiving (default: archive only)",
)
async def posts_closedone(interaction: discord.Interaction, lock: bool = False) -> None:

    if not is_owner(interaction):
        await interaction.response.send_message("You are not authorized to use this command.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    channel = await get_posts_channel(bot)
    if channel is None:
        await interaction.followup.send(
            "POST_CHANNEL_ID is not set correctly, or I can't access that channel.",
        )
        return

    if not isinstance(channel, discord.ForumChannel):
        await interaction.followup.send("The posts channel isn't a forum channel; nothing to do.")
        return

    threads = await fetch_all_threads(channel)

    candidates = []
    for thread in threads:
        if thread_has_done_tag(thread) and is_open_thread(thread):
            candidates.append(thread)

    candidates.sort(key=lambda t: t.created_at or datetime.min.replace(tzinfo=UTC))

    if len(candidates) == 0:
        await interaction.followup.send("No open posts have the done tag. Nothing to close.")
        return

    embeds = build_preview_embeds(
        candidates,
        header_title="Close Done Posts - Confirm",
        header_description=(
            f"Found **{len(candidates)}** open post(s) with the `{DONE_TAG_NAME}` tag.\n"
            f"Lock after archiving: **{'yes' if lock else 'no'}**\n\n"
            "Click **Continue** to close them, or **Cancel** to abort."
        ),
        page_title_prefix="Posts to close",
    )

    async def close_action(thread):
        await call(
            lambda: thread.edit(archived=True, locked=lock, reason="closed via /posts closedone"),
            label="closedone",
        )

    view = BulkActionConfirmView(
        embeds=embeds,
        user_id=interaction.user.id,
        threads=candidates,
        action=close_action,
        copy={
            "progress_title": "Closing posts…",
            "result_title": "Close Done Posts - Result",
            "result_verb": "Closed",
            "cancelled_message": "No posts were closed.",
        },
    )
    await interaction.followup.send(embed=embeds[0], view=view)

    try:
        view.message = await interaction.original_response()
    except Exception:
        pass


@posts_group.command(name="restore", description="Reopen archived posts that don't have the done tag (owner only)")
async def posts_restore(interaction: discord.Interaction) -> None:

    if not is_owner(interaction):
        await interaction.response.send_message("You are not authorized to use this command.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    channel = await get_posts_channel(bot)
    if channel is None:
        await interaction.followup.send(
            "POST_CHANNEL_ID is not set correctly, or I can't access that channel.",
        )
        return

    if not isinstance(channel, discord.ForumChannel):
        await interaction.followup.send("The posts channel isn't a forum channel; nothing to do.")
        return

    threads = await fetch_all_threads(channel)

    candidates = []
    for thread in threads:
        if thread.archived and not thread.locked and not thread_has_done_tag(thread):
            candidates.append(thread)

    candidates.sort(key=lambda thread: thread.created_at or datetime.min.replace(tzinfo=UTC))

    if len(candidates) == 0:
        await interaction.followup.send("No archived posts without the done tag. Nothing to restore.")
        return

    embeds = build_preview_embeds(
        candidates,
        header_title="Restore Posts - Confirm",
        header_description=(
            f"Found **{len(candidates)}** archived post(s) without the `{DONE_TAG_NAME}` tag.\n"
            "These appear to have been auto-closed by Discord.\n\n"
            "Click **Continue** to reopen them, or **Cancel** to abort."
        ),
        page_title_prefix="Posts to restore",
    )

    async def restore_action(thread: discord.Thread):
        await call(
            lambda: thread.edit(archived=False, reason="reopened via /posts restore"),
            label="restore",
        )

    view = BulkActionConfirmView(
        embeds=embeds,
        user_id=interaction.user.id,
        threads=candidates,
        action=restore_action,
        copy={
            "progress_title": "Restoring posts…",
            "result_title": "Restore Posts - Result",
            "result_verb": "Restored",
            "cancelled_message": "No posts were restored.",
        },
    )
    await interaction.followup.send(embed=embeds[0], view=view)

    try:
        view.message = await interaction.original_response()
    except Exception:
        pass


@bot.event
async def on_ready() -> None:
    ensure_dirs()

    try:
        bot.tree.add_command(queue_group)
    except Exception:
        pass

    try:
        bot.tree.add_command(thread_export_group)
    except Exception:
        pass

    try:
        bot.tree.add_command(req_group)
    except Exception:
        pass

    try:
        bot.tree.add_command(posts_group)
    except Exception:
        pass

    await bot.wait_until_ready()

    try:
        if str(GUILD_ID).strip() != "":
            guild_obj = discord.Object(id=int(str(GUILD_ID).strip()))
            bot.tree.copy_global_to(guild=guild_obj)
            synced = await bot.tree.sync(guild=guild_obj)
            print(f"Synced {len(synced)} application command(s) to guild {guild_obj.id}.")
        else:
            synced = await bot.tree.sync()
            print(f"Synced {len(synced)} application command(s) globally.")
    except Exception as e:
        print(f"Command sync failed: {e!r}")

    print(f"Logged in as {bot.user} (id={bot.user.id})")
    print(f"settings file: {os.path.abspath(SETTINGS_FILE)}")
    print(f"reports dir: {os.path.abspath(REPORTS_DIR)}")


def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit("Missing BOT_TOKEN environment variable.")

    ensure_dirs()
    bot.run(BOT_TOKEN)


if __name__ == "__main__":
    main()

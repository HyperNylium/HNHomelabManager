import asyncio
import discord

from modules.vars import POST_CHANNEL_ID, SIMKL_CLIENT_ID
from modules.simkl import fetch_show_embed


async def call(coro_factory, *, label: str = "discord", attempts: int = 5):
    last_error = None
    for n in range(attempts):
        try:
            return await coro_factory()
        except discord.Forbidden as e:
            print(f"[{label}] permission denied: Forbidden: {e}")
            raise

        except discord.HTTPException as e:
            last_error = e
            retry_after = getattr(e, "retry_after", None)
            if retry_after is None:
                retry_after = min(30, 2 ** n)
            await asyncio.sleep(float(retry_after) + 0.25)

        except Exception as e:
            last_error = e
            await asyncio.sleep(min(30, 2 ** n))

    print(f"[{label}] giving up after {attempts} attempts: {last_error}")
    raise last_error


async def get_posts_channel(bot: discord.Client):
    raw_channel_id = POST_CHANNEL_ID.strip()
    if raw_channel_id == "":
        return None

    try:
        channel_id = int(raw_channel_id)
    except Exception:
        return None

    channel = bot.get_channel(channel_id)
    if channel is not None:
        return channel

    try:
        fetched = await bot.fetch_channel(channel_id)
        return fetched
    except Exception:
        return None


async def create_post(channel: discord.abc.GuildChannel, title: str, body: str):
    if isinstance(channel, discord.ForumChannel):
        created = await channel.create_thread(name=title, content=body)

        if isinstance(created, tuple) and len(created) >= 1:
            thread = created[0]
        else:
            thread = created

        try:
            return ("thread", thread.jump_url, thread)
        except Exception:
            return ("thread", None, thread)

    if isinstance(channel, discord.TextChannel):
        message = await channel.send(f"**{title}**\n\n{body}")
        try:
            return ("message", message.jump_url, message)
        except Exception:
            return ("message", None, message)

    return (None, None, None)


async def send_request_post(interaction: discord.Interaction, title: str, body: str, *, simkl_url: str | None = None) -> None:
    posts_channel = await get_posts_channel(interaction.client)
    if posts_channel is None:
        await interaction.response.send_message(
            "POST_CHANNEL_ID is not set correctly, or I can't access that channel.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)

    try:
        created_type, jump_url, created_item = await create_post(posts_channel, title, body)
    except discord.Forbidden:
        await interaction.followup.send("I don't have permission to post in the posts channel.")
        return

    except discord.HTTPException as e:
        await interaction.followup.send(f"Discord error creating post: {e}")
        return

    except Exception as e:
        await interaction.followup.send(f"Unexpected error creating post: {e}")
        return

    if created_type is None or jump_url is None:
        await interaction.followup.send("That channel type is not supported for posting.")
        return

    await interaction.followup.send(f"Request posted: {jump_url}")

    should_add_card = (
        isinstance(created_item, discord.Thread)
        and simkl_url is not None
        and str(simkl_url).strip() != ""
        and SIMKL_CLIENT_ID.strip() != ""
    )
    if should_add_card:
        try:
            embed = await fetch_show_embed(simkl_url)
            if embed is not None:
                await created_item.send(embed=embed)
            else:
                await created_item.send("_Couldn't find this on Simkl._")
        except Exception:
            pass

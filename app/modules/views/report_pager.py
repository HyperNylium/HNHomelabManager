import discord

from modules.vars import shorten, to_discord_timestamp


def make_report_embeds(report: dict) -> list[discord.Embed]:
    embeds = []

    report_id = str(report.get("report_id", "unknown"))
    created_at = to_discord_timestamp(report.get("created_at", ""))

    channel_info = report.get("channel", {})
    channel_id = str(channel_info.get("id", "unknown"))
    channel_name = str(channel_info.get("name", "unknown"))

    created_by = report.get("created_by", {})
    creator_name = str(created_by.get("name", "unknown"))
    creator_id = str(created_by.get("id", "unknown"))

    summary = report.get("summary", {})

    header = discord.Embed(
        title=f"Thread Export Report {report_id}",
        description=f"Channel: **{channel_name}** (`{channel_id}`)\nCreated: **{created_at}**",
    )

    header.add_field(name="Created by", value=f"{creator_name} (`{creator_id}`)", inline=False)

    if isinstance(summary, dict):
        for key in summary:
            header.add_field(name=str(key), value=str(summary[key]), inline=True)

    embeds.append(header)

    threads = report.get("threads")
    messages = report.get("messages")

    # one page per batch of forum threads
    if isinstance(threads, list):
        per_page = 10
        page_index = 0

        total_pages = (len(threads) + per_page - 1) // per_page

        while page_index * per_page < len(threads):
            start_index = page_index * per_page
            end_index = start_index + per_page

            thread_slice = threads[start_index:end_index]

            page = discord.Embed(title=f"Threads (page {page_index + 1} of {total_pages})")

            item_index = start_index + 1

            for thread_obj in thread_slice:
                title = str(thread_obj.get("title", "untitled"))
                url = str(thread_obj.get("url", ""))
                created = to_discord_timestamp(thread_obj.get("created_at", ""))

                is_open = thread_obj.get("open", False)
                is_archived = thread_obj.get("archived", False)
                is_locked = thread_obj.get("locked", False)

                msg_list = thread_obj.get("messages", [])
                msg_count = 0
                if isinstance(msg_list, list):
                    msg_count = len(msg_list)

                flags = []
                if is_open:
                    flags.append("open")
                else:
                    flags.append("closed")

                if is_archived:
                    flags.append("archived")

                if is_locked:
                    flags.append("locked")

                name_line = f"**{shorten(title, 180)}**"
                if url != "":
                    name_line = f"{name_line}\n{url}"

                meta_line = f"Created: {created} | Messages: `{msg_count}` | {', '.join(flags)}"

                field_value = f"{name_line}\n{meta_line}"
                page.add_field(name=f"{item_index}.", value=shorten(field_value, 1024), inline=False)

                item_index += 1

            embeds.append(page)
            page_index += 1

        return embeds

    # one page per batch of channel messages
    if isinstance(messages, list):
        per_page = 10
        page_index = 0

        total_pages = (len(messages) + per_page - 1) // per_page

        while page_index * per_page < len(messages):
            start_index = page_index * per_page
            end_index = start_index + per_page

            message_slice = messages[start_index:end_index]

            page = discord.Embed(title=f"Messages (page {page_index + 1} of {total_pages})")

            item_index = start_index + 1

            for msg_obj in message_slice:
                created = to_discord_timestamp(msg_obj.get("created_at", ""))
                author = msg_obj.get("author", {})
                author_name = str(author.get("name", "unknown"))
                content = str(msg_obj.get("content", ""))

                value = f"{created} - **{shorten(author_name, 64)}**\n{shorten(content, 800)}"
                page.add_field(name=f"{item_index}.", value=shorten(value, 1024), inline=False)

                item_index += 1

            embeds.append(page)
            page_index += 1

        return embeds

    return embeds


class ReportPager(discord.ui.View):
    def __init__(self, embeds: list[discord.Embed], user_id: int):
        super().__init__(timeout=300)
        self.embeds = embeds
        self.user_id = user_id
        self.index = 0
        self.message: discord.Message | None = None
        self.update_buttons()

    def update_buttons(self) -> None:
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                if child.custom_id == "prev":
                    child.disabled = self.index <= 0
                if child.custom_id == "next":
                    child.disabled = self.index >= (len(self.embeds) - 1)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This pager isn't for you.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

        try:
            if self.message:
                await self.message.edit(view=self)
        except Exception:
            pass

    @discord.ui.button(label="Prev", style=discord.ButtonStyle.secondary, custom_id="prev")
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.index > 0:
            self.index -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.index], view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary, custom_id="next")
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.index < (len(self.embeds) - 1):
            self.index += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.index], view=self)

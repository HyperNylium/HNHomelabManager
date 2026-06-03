from collections.abc import Awaitable, Callable

import discord

from modules.vars import shorten


def build_preview_embeds(
    threads: list,
    *,
    header_title: str,
    header_description: str,
    page_title_prefix: str,
) -> list[discord.Embed]:
    embeds = []

    header = discord.Embed(
        title=header_title,
        description=header_description,
    )
    embeds.append(header)

    per_page = 10
    total_pages = (len(threads) + per_page - 1) // per_page
    page_index = 0

    while page_index * per_page < len(threads):
        start_index = page_index * per_page
        end_index = start_index + per_page
        page_threads: list[discord.Thread] = threads[start_index:end_index]

        page = discord.Embed(title=f"{page_title_prefix} (page {page_index + 1} of {total_pages})")

        item_index = start_index + 1
        for thread in page_threads:
            title = str(getattr(thread, "name", "untitled"))
            url = f"https://discord.com/channels/{thread.guild.id}/{thread.id}"

            # discord renders this tag in each viewers own local time
            created_at = getattr(thread, "created_at", None)
            if created_at is not None:
                created = discord.utils.format_dt(created_at, "f")
            else:
                created = "unknown-time"

            value = f"**{shorten(title, 180)}**\n{url}\nCreated: {created}"
            page.add_field(name=f"{item_index}.", value=shorten(value, 1024), inline=False)
            item_index += 1

        embeds.append(page)
        page_index += 1

    return embeds


class BulkActionConfirmView(discord.ui.View):
    def __init__(
        self,
        *,
        embeds: list[discord.Embed],
        user_id: int,
        threads: list[discord.Thread],
        action: Callable[[discord.Thread], Awaitable[None]],
        copy: dict,
    ):
        super().__init__(timeout=300)
        self.embeds = embeds
        self.user_id = user_id
        self.threads = threads
        self.action = action
        self.copy = copy
        self.index = 0
        self.message = None
        self.finished = False
        self.update_buttons()

    def update_buttons(self) -> None:
        single_page = len(self.embeds) <= 1
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                if child.custom_id == "bac_prev":
                    child.disabled = single_page or self.index <= 0
                if child.custom_id == "bac_next":
                    child.disabled = single_page or self.index >= (len(self.embeds) - 1)

    def disable_all(self) -> None:
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This confirmation isn't for you.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        if self.finished:
            return

        self.disable_all()
        try:
            if self.message:
                await self.message.edit(view=self)
        except Exception:
            pass

    @discord.ui.button(label="Prev", style=discord.ButtonStyle.secondary, custom_id="bac_prev")
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.index > 0:
            self.index -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.index], view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary, custom_id="bac_next")
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.index < (len(self.embeds) - 1):
            self.index += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.index], view=self)

    @discord.ui.button(label="Continue", style=discord.ButtonStyle.success, custom_id="bac_continue")
    async def on_continue(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.finished = True
        self.disable_all()

        await interaction.response.defer()

        total = len(self.threads)
        status_embed = discord.Embed(
            title=self.copy["progress_title"],
            description=f"0 / {total} done.",
        )

        try:
            await interaction.edit_original_response(embed=status_embed, view=self)
        except Exception:
            pass

        done_count = 0
        failures: list[tuple[str, str, str]] = []

        for index, thread in enumerate(self.threads, start=1):
            try:
                await self.action(thread)
                done_count += 1
            except Exception as e:
                title = str(getattr(thread, "name", "untitled"))
                url = f"https://discord.com/channels/{thread.guild.id}/{thread.id}"
                failures.append((title, url, f"{type(e).__name__}: {e}"))

            if index % 25 == 0:
                progress = discord.Embed(
                    title=self.copy["progress_title"],
                    description=f"{done_count} / {total} done ({len(failures)} failed).",
                )
                try:
                    await interaction.edit_original_response(embed=progress, view=self)
                except Exception:
                    pass

        result_embed = discord.Embed(
            title=self.copy["result_title"],
            description=f"{self.copy['result_verb']} **{done_count}** of **{total}** post(s).",
        )

        if failures:
            failure_lines = []
            for title, url, err in failures[:10]:
                failure_lines.append(f"• [{shorten(title, 80)}]({url}) - `{shorten(err, 120)}`")

            extra = ""
            if len(failures) > 10:
                extra = f"\n…and {len(failures) - 10} more."

            result_embed.add_field(
                name=f"Failures ({len(failures)})",
                value=shorten("\n".join(failure_lines) + extra, 1024),
                inline=False,
            )

        try:
            await interaction.edit_original_response(embed=result_embed, view=self)
        except Exception:
            pass

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, custom_id="bac_cancel")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.finished = True
        self.disable_all()

        cancelled = discord.Embed(
            title="Cancelled",
            description=self.copy["cancelled_message"],
        )
        await interaction.response.edit_message(embed=cancelled, view=self)

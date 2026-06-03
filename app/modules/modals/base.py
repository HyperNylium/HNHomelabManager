import discord

from modules.discord_api import send_request_post


class RequestModal(discord.ui.Modal):
    def __init__(self, *, title: str, fields: list[discord.ui.TextInput]):
        super().__init__(title=title)
        for field in fields:
            self.add_item(field)

    def build_post(self, interaction: discord.Interaction) -> tuple[str, str]:
        raise NotImplementedError

    async def on_submit(self, interaction: discord.Interaction) -> None:
        title, body = self.build_post(interaction)
        simkl_url = getattr(self, "simkl_url", None)
        await send_request_post(interaction, title, body, simkl_url=simkl_url)

import discord

from modules.modals.base import RequestModal


class AddMeModal(RequestModal):
    def __init__(self):
        self.plexusername = discord.ui.TextInput(
            label="Plex username/email",
            required=True,
            max_length=200,
        )
        super().__init__(title="Account request", fields=[self.plexusername])

    def build_post(self, interaction):
        user_mention = f"<@{interaction.user.id}>"
        plex_value = str(self.plexusername.value).strip()
        title = f'[ACCOUNT REQUEST]: Add user "{plex_value}"'
        body = (
            f"{user_mention} is requesting to be added to the server.\n"
            f"Plex username/email: {plex_value}"
        )
        return title, body

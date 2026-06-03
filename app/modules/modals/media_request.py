import discord

from modules.modals.base import RequestModal


class MediaRequestModal(RequestModal):
    def __init__(self):
        self.name = discord.ui.TextInput(label="Name", required=True, max_length=200)
        self.url = discord.ui.TextInput(label="TVDB/TMDB/Simkl URL", required=True, max_length=400)
        self.notes = discord.ui.TextInput(
            label="Notes",
            required=False,
            style=discord.TextStyle.paragraph,
            max_length=1000,
        )
        super().__init__(title="Media request", fields=[self.name, self.url, self.notes])

    def build_post(self, interaction):
        user_mention = f"<@{interaction.user.id}>"
        name_value = str(self.name.value).strip()
        url_value = str(self.url.value).strip()
        notes_value = str(self.notes.value).strip()
        self.simkl_url = url_value

        title = f"[MEDIA REQUEST]: {name_value}"
        body = (
            f'{user_mention} requests adding "{name_value}" to the server.\n'
            f"URL: {url_value}\n\n"
            "Extra notes by user:\n"
            f"{notes_value if notes_value != '' else '(none)'}"
        )
        return title, body

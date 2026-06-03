import discord

from modules.modals.base import RequestModal


class StatusRequestModal(RequestModal):
    def __init__(self):
        self.name = discord.ui.TextInput(label="Title name", required=True, max_length=200)
        self.notes = discord.ui.TextInput(
            label="Notes",
            required=False,
            style=discord.TextStyle.paragraph,
            max_length=1000,
        )
        super().__init__(title="Status request", fields=[self.name, self.notes])

    def build_post(self, interaction):
        user_mention = f"<@{interaction.user.id}>"
        name_value = str(self.name.value).strip()
        notes_value = str(self.notes.value).strip()
        title = f'[STATUS REQUEST]: Whats the status of "{name_value}"?'
        body = (
            f'{user_mention} is requesting the status of "{name_value}".\n\n'
            "Extra notes by user:\n"
            f"{notes_value if notes_value != '' else '(none)'}"
        )
        return title, body

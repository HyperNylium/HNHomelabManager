import discord

from modules.vars import is_mod, load_settings, mention, save_settings


class QueueAddModal(discord.ui.Modal):
    def __init__(self, target_user: discord.abc.User | None = None):
        super().__init__(title="Add user to queue")
        self.target_user = target_user

        self.identifier = discord.ui.TextInput(
            label="Plex username or email",
            placeholder="e.g. myplexuser or me@example.com",
            required=True,
            max_length=128,
        )
        self.add_item(self.identifier)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not is_mod(interaction):
            await interaction.response.send_message("You are not authorized to use this command.", ephemeral=True)
            return

        identifier_value = str(self.identifier.value).strip()
        if identifier_value == "":
            await interaction.response.send_message("Identifier cannot be empty.", ephemeral=True)
            return

        settings = await load_settings()
        queue_map = settings.get("queue")
        if not isinstance(queue_map, dict):
            queue_map = {}

        if self.target_user is not None:
            user_key = mention(self.target_user)
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

import discord

class DisconnectedUserSelectView(discord.ui.View):
    message: discord.Message = None

    def __init__(self):
        super().__init__(timeout=None)

    async def on_timeout(self):
        if self.message:
            await self.message.edit(view=None)
        return

    @discord.ui.select(placeholder="Select disconnected User", cls=discord.ui.UserSelect)
    async def user_select(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        if len(interaction.data['values']) < 0:
            await interaction.response.send_message("No user selected.", ephemeral=True)
            return
        user_id = interaction.data['values'][0]

        user = interaction.guild.get_member(int(user_id))
        if user is None:
            await interaction.response.send_message("Selected user not found in the server.", ephemeral=True)
            return

        self.message = interaction.message
        self.timeout = 10
        await self.message.edit(view=self)
        await interaction.response.send_message(f"Log linked to {user.nick or user.display_name} (<@{user.id}>).", ephemeral=True)

        print(interaction)
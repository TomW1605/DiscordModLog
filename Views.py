import discord

class DisconnectedUserSelectView(discord.ui.View):
    log_entry = None
    message: discord.Message = None

    def __init__(self, db_session):
        super().__init__(timeout=None)

        self.db_session = db_session

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

        embed = self.message.embeds[0]
        embed.description = f"**User:** {user.nick or user.display_name} (<@{user.id}>)\n" + embed.description

        self.timeout = 10
        await self.message.edit(embed=embed, view=self)
        await interaction.response.send_message(f"Log linked to {user.nick or user.display_name} (<@{user.id}>).", ephemeral=True)

        self.log_entry.target_user_id = user.id
        self.db_session.commit()

        print(interaction)
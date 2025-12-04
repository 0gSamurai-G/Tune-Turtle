import discord
from discord.ext import commands
import asyncio
import yt_dlp
import os
import random

# --- Configuration ---
# CRITICAL CHANGE: Reading the token securely from the environment new.
# You MUST set the DISCORD_BOT_TOKEN variable in your Railway dashboard.
ALLOWED_SERVERS = {1439561356960464979}
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")

# --- yt-dlp Options ---
YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0'
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

# --- Player Class for Guild State Management ---
class MusicPlayer:
    def __init__(self, bot, guild):
        self.bot = bot
        self.guild = guild
        self.queue = asyncio.Queue()
        self.current = None
        self.volume = 0.5
        self.skip_votes = set()
        self.voice_client = None

        self._loop = asyncio.get_event_loop()
        self._play_next = asyncio.Event()
        self.player = self._loop.create_task(self.player_loop())

    # --- Utility Methods ---

    @staticmethod
    async def get_source(url):
        data = await asyncio.to_thread(ytdl.extract_info, url, download=False)
        if 'entries' in data:
            data = data['entries'][0]

        return {
            'webpage_url': data['webpage_url'],
            'requester': data.get('requester', 'Unknown'),
            'title': data.get('title', 'Unknown Title'),
            'url': data['url']
        }

    def after_song(self, error=None):
        if error:
            print(f'Player error: {error}')

        self.current = None
        self.skip_votes.clear()
        self._play_next.set()

    # --- Main Player Loop ---
    async def player_loop(self):
        await self.bot.wait_until_ready()

        while not self.bot.is_closed():
            self._play_next.clear()

            try:
                # Wait for the next song in the queue (with a 5-minute timeout)
                async with asyncio.timeout(300):
                    song_info = await self.queue.get()
            except asyncio.TimeoutError:
                # Disconnect if no song is added for 5 minutes
                if self.voice_client:
                    await self.voice_client.disconnect()
                return

            self.current = song_info

            # Create the FFmpeg audio source from the stream URL
            source = discord.FFmpegPCMAudio(
                song_info['url'],
                before_options='-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
                options='-vn -b:a 192k'
            )
            # Apply volume control (Source is wrapped)
            source = discord.PCMVolumeTransformer(source, volume=self.volume)

            # Play the source and set the 'after' callback
            self.voice_client.play(source, after=lambda e: self.after_song(e))

            # Send 'Now Playing' confirmation
            channel = song_info['ctx'].channel
            embed = discord.Embed(
                title="▶️ Now Playing",
                description=f"[{song_info['title']}]({song_info['webpage_url']})",
                color=discord.Color.green()
            )
            embed.set_footer(text=f"Requested by {song_info['requester']}")
            await channel.send(embed=embed)

            await self._play_next.wait()

    # --- Cleanup ---
    def destroy(self):
        """Cleans up the player loop and state."""
        if self.voice_client:
            self._loop.create_task(self.voice_client.disconnect())
        self.player.cancel()

# --- Bot Initialization ---

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Dictionary to hold a MusicPlayer instance for each guild
players = {}

def get_player(ctx):
    """Retrieves or creates the MusicPlayer instance for the guild."""
    if ctx.guild.id not in players:
        players[ctx.guild.id] = MusicPlayer(bot, ctx.guild)
    return players[ctx.guild.id]

# ---------------------------------------------
## 👑 Role Hierarchy Control Functions
# ---------------------------------------------

def get_highest_role(members):
    """Finds the highest role among a list of members based on position."""
    highest_role = None
    for member in members:
        if member.bot:
            continue
        
        if member.roles:
            member_highest_role = member.top_role
            if highest_role is None or member_highest_role.position > highest_role.position:
                highest_role = member_highest_role
                
    return highest_role

def can_override(ctx):
    """
    Checks if the command author can override control in the voice channel.
    True if the author is alone, is an admin/owner, or has a higher role
    than everyone else in the VC.
    """
    # Owner/Admin always overrides
    if ctx.author == ctx.guild.owner or ctx.author.guild_permissions.administrator:
        return True

    player = get_player(ctx)
    if player.voice_client is None:
        return True # If bot isn't connected, anyone can start it.

    vc = player.voice_client.channel
    
    # Get all non-bot members currently in the channel (excluding the author)
    current_listeners = [m for m in vc.members if not m.bot and m != ctx.author]

    # If only the author is in the VC (and the bot), allow control.
    if not current_listeners:
        return True

    author_top_role = ctx.author.top_role
    highest_vc_role = get_highest_role(current_listeners)

    # If the author's role position is STRICTLY higher than the highest role present, allow override.
    if highest_vc_role is not None and author_top_role.position > highest_vc_role.position:
        return True
    
    return False

# Custom check decorator
def is_high_rank():
    async def predicate(ctx):
        if can_override(ctx):
            return True
        else:
            await ctx.send("🛑 **Permission Denied:** A user with a higher or equal role is currently controlling the voice channel.")
            return False
    return commands.check(predicate)


@bot.event
async def on_ready():
    """Confirms the bot is running and connected to Discord."""
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')
    print('------')

    unauthorized_guilds = []
    for guild in bot.guilds:
        if guild.id not in ALLOWED_SERVERS:
            unauthorized_guilds.append(guild.name)
            await guild.leave()
            
    if unauthorized_guilds:
        print(f"🚫 CLEANUP: Left the following unauthorized guilds on startup: {', '.join(unauthorized_guilds)}")

    await bot.change_presence(activity=discord.Game(name="The beat never stops."))

@bot.event
async def on_guild_join(guild):
    """3. 🛡️ CHECK ON NEW INVITE"""
    if guild.id not in ALLOWED_SERVERS:
        print(f"❌ UNAUTHORIZED JOIN: Leaving Guild '{guild.name}' (ID: {guild.id})")
        # Optional: Add a polite message here before leaving
        await guild.leave()
    else:
        print(f"✅ ALLOWED JOIN: Staying in Guild '{guild.name}' (ID: {guild.id})")

# ---------------------------------------------
## 📝 Error Handling
# ---------------------------------------------

@bot.event
async def on_command_error(ctx, error):
    """Global error handler for commands."""
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.CheckFailure):
        # Already handled by is_high_rank() check sending a message
        return 
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing argument. Usage: `{ctx.prefix}{ctx.command.name} {ctx.command.signature}`")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ Member not found.")
    elif isinstance(error, commands.NoPrivateMessage):
        await ctx.send("❌ This command cannot be used in private messages.")
    elif isinstance(error, commands.CommandInvokeError):
        original = error.original
        if isinstance(original, discord.ClientException) and 'Already connected' in str(original):
            return
        elif isinstance(original, asyncio.TimeoutError):
            await ctx.send("❌ Could not connect to the voice channel (Timed out).")
        elif isinstance(original, IndexError) and 'pop from empty list' in str(original):
             await ctx.send("❌ The queue is empty! Add a song first.")
        else:
            print(f"Unhandled CommandInvokeError in {ctx.command}: {original}")
            await ctx.send(f"❌ An internal error occurred: `{original}`")
    else:
        print(f"Unhandled error type: {type(error).__name__}")
        raise error

# ---------------------------------------------
## 🎵 Music Commands (With Hierarchy Logic)
# ---------------------------------------------

@bot.command(name='join', aliases=['connect'], help='Tells the bot to join the voice channel.')
async def join(ctx, channel: discord.VoiceChannel = None):
    if not channel and ctx.author.voice:
        channel = ctx.author.voice.channel

    if not channel:
        await ctx.send("❌ You must be in a voice channel or specify one!")
        return

    player = get_player(ctx)
    if ctx.voice_client:
        if ctx.voice_client.channel == channel:
            await ctx.send("I'm already here!")
            return

        # CHECK HIERARCHY BEFORE MOVING
        if not can_override(ctx):
            await ctx.send("🛑 **Permission Denied:** Cannot move the bot, as a higher-rank user is in the current voice channel.")
            return

        await ctx.voice_client.move_to(channel)
    else:
        # CHECK HIERARCHY BEFORE CONNECTING to a different channel
        if channel != ctx.author.voice.channel and not can_override(ctx):
            await ctx.send("🛑 **Permission Denied:** Cannot force the bot into a channel if a higher-rank user is in the VC.")
            return
            
        player.voice_client = await channel.connect()

    await ctx.send(f"✅ Joined **{channel.name}**")

@bot.command(name='leave', aliases=['disconnect', 'stop'], help='Stops playing and disconnects the bot.')
@is_high_rank() # Apply hierarchy check
async def leave(ctx):
    player = get_player(ctx)
    if player.voice_client and player.voice_client.is_connected():
        player.voice_client.stop()
        player.destroy()
        del players[ctx.guild.id]
        await ctx.send("👋 Disconnected and queue cleared!")
    else:
        await ctx.send("❌ I'm not in a voice channel.")

@bot.command(name='play', aliases=['p'], help='Plays a song from a URL or search term.')
async def play(ctx, *, search_term: str):
    if not ctx.voice_client:
        if ctx.author.voice:
            # Auto-join respects hierarchy because it uses the modified !join command
            await ctx.invoke(join) 
        else:
            await ctx.send("❌ You need to join a voice channel first, or use `!join`.")
            return

    # Check hierarchy before queuing a song if the user doesn't have permissions to override
    if not can_override(ctx):
        # Even if a lower rank can't control the bot, they can still add to the queue 
        pass # Allow low rank to queue

    player = get_player(ctx)

    await ctx.send(f"🔎 Searching for `{search_term}`...")

    try:
        song_info = await MusicPlayer.get_source(search_term)
        song_info['ctx'] = ctx
        song_info['requester'] = ctx.author.display_name

        await player.queue.put(song_info)

        if player.voice_client.is_playing():
            await ctx.send(f"➕ Added **{song_info['title']}** to the queue.")
        else:
            pass # player_loop starts playing
            
    except Exception as e:
        await ctx.send(f"❌ Failed to process search term: `{e}`")
        print(f"YTDL Error: {e}")


@bot.command(name='skip', aliases=['s'], help='Votes to skip the current song.')
async def skip(ctx):
    player = get_player(ctx)
    if not player.voice_client or not player.voice_client.is_playing():
        await ctx.send("❌ Nothing is currently playing.")
        return

    # Owner/Admin skip without voting (already a form of rank override)
    if ctx.author == ctx.guild.owner or ctx.author.guild_permissions.administrator:
        player.voice_client.stop()
        await ctx.send(f"⏩ **Skipped** by Administrator.")
        return

    # If a high-rank user is present, only high-rank users can vote (or admin can skip)
    # This prevents lower ranks from starting a vote if a higher rank is present.
    if not can_override(ctx) and ctx.author.top_role.position < get_highest_role(player.voice_client.channel.members).position:
        await ctx.send("🛑 You cannot initiate a skip vote while a higher-rank user is present.")
        return


    # Standard voting logic for everyone else
    voice_channel = player.voice_client.channel
    members = [m for m in voice_channel.members if not m.bot]
    required_votes = int(len(members) * 0.5) + 1

    if ctx.author in player.skip_votes:
        await ctx.send("You have already voted to skip this song.", ephemeral=True)
        return

    player.skip_votes.add(ctx.author)

    if len(player.skip_votes) >= required_votes:
        player.voice_client.stop()
        await ctx.send(f"⏩ Vote successful! **Skipping** the current song.")
    else:
        remaining = required_votes - len(player.skip_votes)
        await ctx.send(f"🗳️ Vote received: **{len(player.skip_votes)}/{required_votes}** votes to skip. {remaining} more needed.")

@bot.command(name='queue', aliases=['q'], help='Shows the current song queue.')
async def show_queue(ctx):
    player = get_player(ctx)
    if player.queue.empty():
        await ctx.send("The song queue is empty.")
        return

    queue_list = list(player.queue._queue)

    queue_display = "\n".join([
        f"**{i+1}.** [{song['title']}]({song['webpage_url']}) - Requested by {song['requester']}"
        for i, song in enumerate(queue_list)
    ])

    embed = discord.Embed(
        title="🎧 Song Queue",
        description=queue_display,
        color=discord.Color.blue()
    )
    if player.current:
         embed.add_field(name="Current", value=f"[{player.current['title']}]({player.current['webpage_url']})", inline=False)

    await ctx.send(embed=embed)


@bot.command(name='volume', aliases=['vol'], help='Sets the playback volume (1-100).')
@commands.has_permissions(manage_channels=True) # Already restricted, no hierarchy change needed
async def set_volume(ctx, volume: int):
    player = get_player(ctx)
    if not player.voice_client:
        await ctx.send("❌ I'm not playing anything yet.")
        return

    if not 0 <= volume <= 100:
        await ctx.send("❌ Volume must be between 0 and 100.")
        return

    player.volume = volume / 100.0

    if player.voice_client.source:
        player.voice_client.source.volume = player.volume

    await ctx.send(f"🔊 Volume set to **{volume}%**.")

@bot.command(name='pause', help='Pauses the current song.')
@is_high_rank() # Apply hierarchy check
async def pause(ctx):
    player = get_player(ctx)
    if player.voice_client and player.voice_client.is_playing():
        player.voice_client.pause()
        await ctx.send("⏸️ Paused.")
    else:
        await ctx.send("❌ Nothing is playing.")

@bot.command(name='resume', help='Resumes the paused song.')
@is_high_rank() # Apply hierarchy check
async def resume(ctx):
    player = get_player(ctx)
    if player.voice_client and player.voice_client.is_paused():
        player.voice_client.resume()
        await ctx.send("▶️ Resumed.")
    else:
        await ctx.send("❌ Nothing is paused.")

# --- Run the Bot ---
if __name__ == "__main__":
    if DISCORD_BOT_TOKEN:
        bot.run(DISCORD_BOT_TOKEN)
    else:
        print("Bot token not found. Please set the DISCORD_BOT_TOKEN environment variable.")
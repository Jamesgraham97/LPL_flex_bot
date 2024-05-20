import discord
import requests
import sqlite3
import asyncio
import collections
import random
import os
from discord.ext import commands, tasks
from discord.ui import Select, View


intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.message_content = True  # Ensure this is set for message content
bot = commands.Bot(command_prefix='!', intents=intents)

# Load environment variables
RIOT_API_KEY = os.getenv("RIOT_API_KEY")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# Database setup
conn = sqlite3.connect('lpl_Flex_Stats.db')
c = conn.cursor()

# Create tables if they do not exist
c.execute('''
CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    summoner_name TEXT UNIQUE,
    game_name TEXT,
    tag_line TEXT
)
''')

c.execute('''
CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id TEXT,
    player_id INTEGER,
    role TEXT,
    win BOOLEAN,
    FOREIGN KEY (player_id) REFERENCES players(id),
    UNIQUE (match_id, player_id)
)
''')
conn.commit()

# Function to fetch account information by Riot ID
def get_account_info_by_riot_id(game_name, tag_line):
    url = f'https://europe.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{game_name}/{tag_line}?api_key={RIOT_API_KEY}'
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error: {e}")
        return {}

# Function to fetch summoner data by PUUID
def get_summoner_data_by_puuid(encrypted_puuid):
    url = f'https://euw1.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{encrypted_puuid}?api_key={RIOT_API_KEY}'
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
      #  print(f"Summoner Data: {data}")
        return data
    except requests.exceptions.RequestException as e:
        print(f"Error: {e}")
        return {}

# Function to fetch match history
def get_match_history(encrypted_puuid, queue_id, count):
    url = f'https://europe.api.riotgames.com/lol/match/v5/matches/by-puuid/{encrypted_puuid}/ids?queue={queue_id}&start=0&count={count}&api_key={RIOT_API_KEY}'
    try:
        print(f"Fetching match history with URL: {url}")  # Debugging statement
        response = requests.get(url)
        response.raise_for_status()
        matches = response.json()
        return matches
    except requests.exceptions.RequestException as e:
        print(f"Error fetching match history: {e}")
        return []

# Function to fetch match details
def get_match_details(match_id):
    url = f'https://europe.api.riotgames.com/lol/match/v5/matches/{match_id}?api_key={RIOT_API_KEY}'
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error: {e}")
        return {}

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')
    check_new_matches.start()

# Command to register a player
@bot.command()
async def register(ctx, game_name: str, tag_line: str):
    game_name_lower = game_name.lower()  # Normalize case for comparison
    tag_line_lower = tag_line.lower()  # Normalize case for comparison
    
    account_info = get_account_info_by_riot_id(game_name_lower, tag_line_lower)
    if 'puuid' not in account_info:
        await ctx.send(f"Failed to retrieve PUUID for {game_name}#{tag_line}")
        return

    print(f"Account Info: {account_info}")

    summoner_name = account_info['gameName']  # Preserve original case

    try:
        c.execute('INSERT OR IGNORE INTO players (summoner_name, game_name, tag_line) VALUES (?, ?, ?)', (summoner_name, game_name_lower, tag_line_lower))
        conn.commit()
        await ctx.send(f'Registered {summoner_name} as {game_name}#{tag_line}')
        print(f'Registered player: {summoner_name} as {game_name_lower}#{tag_line_lower}')
    except sqlite3.Error as e:
        await ctx.send(f"An error occurred: {e}")
        print(f"SQLite error: {e}")

# Command to list all registered players
@bot.command()
async def players(ctx):
    players = c.execute('SELECT summoner_name, game_name, tag_line FROM players').fetchall()
    if players:
        player_list = '\n'.join([f'{player[0]} (Riot ID: {player[1]}#{player[2]})' for player in players])
        await ctx.send(f'Registered players:\n{player_list}')
    else:
        await ctx.send('No registered players.')

# Command to remove a player
@bot.command()
async def remove(ctx, summoner_name: str):
    c.execute('DELETE FROM players WHERE summoner_name = ?', (summoner_name,))
    conn.commit()
    await ctx.send(f'Removed {summoner_name}')

async def fetch_match_details(game_name, tag_line, num_matches=5):
    await asyncio.sleep(1)  # Add delay to respect rate limit
    try:
        account_info = get_account_info_by_riot_id(game_name, tag_line)
        if 'puuid' not in account_info:
            raise Exception(f"Failed to retrieve PUUID for {game_name}#{tag_line}")
        puuid = account_info['puuid']
        matches = get_match_history(puuid, 440, num_matches)  # Queue ID 440 for ranked flex

        print(f'Matches fetched for {game_name}#{tag_line}: {matches}')

        summoner_name = account_info['gameName']  # Preserve original case

        # Known alias mapping
        alias_mapping = {
            "UMBREON": "UmbreonReaper"
        }

        # If summoner_name has an alias, use it
        effective_summoner_name = alias_mapping.get(summoner_name, summoner_name)

        for match_id in matches:
            match_details = get_match_details(match_id)
            print(f'Match details for {match_id}')

            participant_names = [participant['summonerName'] for participant in match_details['info']['participants']]
            print(f'Participants in match {match_id}: {participant_names}')

            found = False
            for participant in match_details['info']['participants']:
                print(f"Checking participant {participant['summonerName']} against {effective_summoner_name}")
                if participant['summonerName'].lower() == effective_summoner_name.lower():
                    found = True
                    role = participant['individualPosition']
                    win = participant['win']
                    player_id = c.execute('SELECT id FROM players WHERE LOWER(summoner_name) = LOWER(?)', (summoner_name.lower(),)).fetchone()
                    if player_id is None:
                        print(f"No player found in database for summoner name: {summoner_name}")
                        continue

                    player_id = player_id[0]
                    try:
                        print(f'Inserting match {match_id} for player {effective_summoner_name} with role {role} and win {win}')
                        c.execute('INSERT OR IGNORE INTO matches (match_id, player_id, role, win) VALUES (?, ?, ?, ?)', (match_id, player_id, role, win))
                        conn.commit()
                        print(f'Successfully inserted match {match_id}')
                    except sqlite3.Error as e:
                        print(f"SQLite error: {e}")
                    break
            if not found:
                print(f"No matching participant found for {effective_summoner_name} in match {match_id}")

    except Exception as e:
        print(f'Error in fetch_match_details: {e}')


    except Exception as e:
        print(f'Error in fetch_match_details: {e}')

@bot.command()
async def account_info(ctx, game_name: str, tag_line: str):
    account_info = get_account_info_by_riot_id(game_name, tag_line)
    if 'puuid' not in account_info:
        await ctx.send(f"Failed to retrieve PUUID for {game_name}#{tag_line}")
        return

    await ctx.send(f"Account Info for {game_name}#{tag_line}: {account_info}")



# Background task to check for new matches
@tasks.loop(minutes=15)
async def check_new_matches():
    players = c.execute('SELECT game_name, tag_line FROM players').fetchall()
    for player in players:
        game_name, tag_line = player
        await fetch_match_details(game_name, tag_line)

# Command to manually update stats
@bot.command()
async def update(ctx, game_name: str, tag_line: str):
    await fetch_match_details(game_name, tag_line)
    await ctx.send(f'Updated stats for {game_name}#{tag_line}')

# Command to display win rates
@bot.command()
async def winrate(ctx, summoner_name: str):
    try:
        summoner_name_lower = summoner_name.lower()  # Normalize case
        player_id = c.execute('SELECT id FROM players WHERE LOWER(summoner_name) = LOWER(?)', (summoner_name_lower,)).fetchone()
        if not player_id:
            await ctx.send(f'No data found for {summoner_name}.')
            print(f"No data found for {summoner_name}.")  # Debugging output
            return
        player_id = player_id[0]
        roles = c.execute('SELECT DISTINCT role FROM matches WHERE player_id = ?', (player_id,)).fetchall()
        
        print(f'Player ID: {player_id}')
        print(f'Roles: {roles}')
        
        results = []
        for role in roles:
            role_name = role[0]
            wins = c.execute('SELECT COUNT(*) FROM matches WHERE player_id = ? AND role = ? AND win = 1', (player_id, role_name)).fetchone()[0]
            total = c.execute('SELECT COUNT(*) FROM matches WHERE player_id = ? AND role = ?', (player_id, role_name)).fetchone()[0]
            
            print(f'Role: {role_name}, Wins: {wins}, Total: {total}')
            
            win_rate = (wins / total) * 100 if total > 0 else 0
            results.append(f'{role_name}: {win_rate:.2f}%')

        if results:
            await ctx.send('\n'.join(results))
        else:
            await ctx.send(f'No recorded matches for {summoner_name}.')
    except Exception as e:
        print(f'Error in winrate command: {e}')
        await ctx.send(f'An error occurred while processing win rates for {summoner_name}.')


# Command to display roles played by the summoner
@bot.command()
async def roles(ctx, summoner_name: str):
    player_id = c.execute('SELECT id FROM players WHERE summoner_name = ?', (summoner_name,)).fetchone()
    if not player_id:
        await ctx.send(f'No data found for {summoner_name}.')
        return
    player_id = player_id[0]
    roles = c.execute('SELECT role, COUNT(*) FROM matches WHERE player_id = ? GROUP BY role', (player_id,)).fetchall()
    if roles:
        role_list = '\n'.join([f'{role[0]}: {role[1]}' for role in roles])
        await ctx.send(f'Roles played by {summoner_name}:\n{role_list}')
    else:
        await ctx.send(f'No matches found for {summoner_name}.')

# Command to display all players and their win rates for each role
@bot.command()
async def playerwinrates(ctx):
    players = c.execute('SELECT summoner_name FROM players').fetchall()
    if not players:
        await ctx.send('No registered players.')
        return

    results = []
    for player in players:
        summoner_name = player[0]
        player_id = c.execute('SELECT id FROM players WHERE summoner_name = ?', (summoner_name,)).fetchone()[0]
        roles = c.execute('SELECT DISTINCT role FROM matches WHERE player_id = ?', (player_id,)).fetchall()
        if not roles:
            continue
        role_winrates = []
        for role in roles:
            role_name = role[0]
            wins = c.execute('SELECT COUNT(*) FROM matches WHERE player_id = ? AND role = ? AND win = 1', (player_id, role_name)).fetchone()[0]
            total = c.execute('SELECT COUNT(*) FROM matches WHERE player_id = ? AND role = ?', (player_id, role_name)).fetchone()[0]
            win_rate = (wins / total) * 100 if total > 0 else 0
            role_winrates.append(f'**{role_name.capitalize()}**: {win_rate:.2f}%')
        results.append(f'**{summoner_name}**:\n' + ' | '.join(role_winrates))

    formatted_output = '\n\n'.join(results)
    await ctx.send(formatted_output)


# Add this global variable to store weights
role_weights = collections.defaultdict(lambda: {'Top': 1, 'Jungle': 1, 'Mid': 1, 'ADC': 1, 'Support': 1})

@bot.command()
async def new_session(ctx):
    global role_weights
    role_weights = collections.defaultdict(lambda: {'Top': 1, 'Jungle': 1, 'Mid': 1, 'ADC': 1, 'Support': 1})
    await ctx.send('New session started. Role weights have been reset.')

@bot.command()
async def generate_teams(ctx):
    players = c.execute('SELECT summoner_name FROM players').fetchall()
    if len(players) < 5:
        await ctx.send('Not enough registered players to generate a team.')
        return

    player_options = [discord.SelectOption(label=player[0], value=player[0]) for player in players]

    class PlayerSelect(discord.ui.Select):
        def __init__(self, options):
            super().__init__(placeholder="Select 5 players", min_values=5, max_values=5, options=options)

        async def callback(self, interaction: discord.Interaction):
            selected_players = self.values

            # Weighted role assignment
            assigned_roles = {}
            for role in ['Top', 'Jungle', 'Mid', 'ADC', 'Support']:
                player = random.choices(selected_players, weights=[role_weights[p][role] for p in selected_players], k=1)[0]
                assigned_roles[role] = player
                selected_players.remove(player)
                # Increase weight for the assigned role
                role_weights[player][role] *= 2

            team_output = ', '.join([f'{role}: {player}' for role, player in assigned_roles.items()])
            await interaction.response.send_message(f'Team generated: {team_output}')

    select = PlayerSelect(player_options)
    view = View()
    view.add_item(select)
    await ctx.send('Select players to form a team:', view=view)



@bot.command()
async def debug_players(ctx):
    players = c.execute('SELECT * FROM players').fetchall()
    if players:
        player_list = '\n'.join([f'{player[0]}: {player[1]} (Riot ID: {player[2]}#{player[3]})' for player in players])
        await ctx.send(f'Registered players:\n{player_list}')
    else:
        await ctx.send('No registered players.')

@bot.command()
async def debug_matches(ctx, summoner_name: str):
    player_id = c.execute('SELECT id FROM players WHERE LOWER(summoner_name) = LOWER(?)', (summoner_name.lower(),)).fetchone()
    if player_id:
        player_id = player_id[0]
        matches = c.execute('SELECT * FROM matches WHERE player_id = ?', (player_id,)).fetchall()
        if matches:
            match_list = '\n'.join([f'Match ID: {match[1]}, Role: {match[3]}, Win: {match[4]}' for match in matches])
            await ctx.send(f'Matches for {summoner_name}:\n{match_list}')
        else:
            await ctx.send(f'No matches found for {summoner_name}.')
    else:
        await ctx.send(f'No player found with the name {summoner_name}.')

# Run the bot
bot.run(DISCORD_BOT_TOKEN)

import io
import os
import sys
import subprocess
import asyncio
import logging
import json
from datetime import time
import aiohttp
import mysql.connector
from io import BytesIO
from collections import Counter
import matplotlib.pyplot as plt

# Auto-install packages
try:
    import discord
    from discord import app_commands
    from discord.ext import commands, tasks
    import mysql.connector
    import aiohttp
except ImportError:
    try:
        subprocess.check_call([
            sys.executable, "-m", "pip", "install",
            "discord.py", "mysql-connector-python", "aiohttp"
        ])
    except Exception as e:
        print(f"[setup] Auto-install failed: {e}")
        sys.exit(1)
    os.execl(sys.executable, sys.executable, *sys.argv)

import discord
from discord import app_commands
from discord.ext import commands, tasks
import mysql.connector
import logging

# Patch discord logging to prevent format crash
try:
    for handler in logging.getLogger("discord.gateway").handlers:
        handler.setFormatter(logging.Formatter("%(asctime)s:%(levelname)s:%(name)s: %(message)s"))
except Exception as e:
    print(f"[logging] Patch failed: {e}")

# Silence session resume and other info logs
try:
    logging.getLogger("discord").setLevel(logging.WARNING)
except Exception as e:
    print(f"[logging] Set level failed: {e}")

intents = discord.Intents.default()
intents.guilds = True
intents.messages = True
intents.message_content = True

bot = commands.Bot(command_prefix="/", intents=intents)

GLOBAL_DATA_FILE = "global_data.json"
DB_CONFIG_FILE = "db_config.json"

def prompt_db_config():
    print("\n=== MCxDiscord Database Setup ===")

    host = input("MySQL Host: ").strip()

    print()
    port = input("MySQL Port [3306]: ").strip() or "3306"

    print()
    user = input("MySQL User: ").strip()

    print()
    password = input("MySQL Password: ").strip()

    print()
    database = input("MySQL Database: ").strip()

    config = {
        "host": host,
        "port": int(port),
        "user": user,
        "password": password,
        "database": database
    }

    with open(DB_CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)

    print("\n✅ Saved DB config to db_config.json.")
    print("   Restart the bot if you change these settings.\n")
    return config

def load_db_config():
    if os.path.exists(DB_CONFIG_FILE):
        with open(DB_CONFIG_FILE, "r") as f:
            return json.load(f)
    else:
        return prompt_db_config()

db_config = load_db_config()

warned_versions = {}  # (guild_id, channel_id): version_str or "fail" or "ok"
blocked_messages = {}
last_unlinked_ping = {}
MCXDEV_ID = 806806527192334356
MCX_LOGO_URL = "https://cdn.modrinth.com/data/l3UqzYGx/9aca66c04eef38ce55e85c642962e1fa0b29ba1c.png"

debug_global_stats = {
    "messages": [],
    "versions": {},
    "guilds": []
}

def get_db():
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS MCxDISCORD (
                id INT AUTO_INCREMENT PRIMARY KEY,
                guild_id VARCHAR(32),
                channel_id VARCHAR(32),
                mc_ip VARCHAR(64),
                auth_token TEXT
            )
        """)
        conn.commit()
        return conn
    except Exception as e:
        print(f"[db] Connection failed: {e}")
        return None


async def update_presence():
    try:
        conn = get_db()
        count = 0
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM MCxDISCORD")
            result = cursor.fetchone()
            count = result[0] if result else 0
            conn.close()
        await bot.change_presence(activity=discord.Game(name=f"Linking {count} servers!"))
    except Exception as e:
        print(f"[presence] Failed to update presence: {e}")

@tasks.loop(seconds=10)
async def daily_calculator():
    raw_current_time = time.time()
    current_time = time.gmtime(raw_current_time)
    required_time = datetime.time(hour=0, minute=0)



    if required_time.minute == current_time.tm_min and required_time.hour == current_time.tm_hour:
        for cell in debug_global_stats["messages"]:
            try:
                cell[2].append(cell[1]) # Adds counted messages from on_message event into the list
                cell[1] = 0 # Resets the messages
            except Exception as e:
                print(f"[daily_calculator] Error processing message cell: {e}")



@bot.event
async def on_disconnect():
    with open(GLOBAL_DATA_FILE, "w") as f:
        json.dump(debug_global_stats, f, indent=2)


@bot.event
async def on_guild_join(guild: discord.Guild):
    debug_global_stats["guilds"].add({"id": guild.id, "name": guild.name})

@bot.event
async def on_guild_remove(guild: discord.Guild):
    debug_global_stats["guilds"].remove({"id": guild.id, "name": guild.name})

def is_admin():
    async def predicate(interaction: discord.Interaction):
        try:
            return interaction.user.guild_permissions.administrator
        except Exception:
            return False
    return app_commands.check(predicate)


async def get_latest_versions():
    try:
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get("https://api.modrinth.com/v2/project/mcxdiscord/version", timeout=10) as resp:
                    data = await resp.json()
                    versions = {}
                    to_update = {}
                    for version in data:
                        ver = version["version_number"]
                        downloads = version["downloads"]
                        to_update[ver] = downloads
                        platform = "spigot" if "spigot" in ver.lower() else "paper"
                        if platform not in versions:
                            versions[platform] = ver
                    debug_global_stats["versions"] = to_update
                    return versions
            except Exception as e:
                print(f"[version check] Failed to fetch Modrinth versions: {e}")
                return {}
    except Exception as e:
        print(f"[version check] Session error: {e}")
        return {}


@tasks.loop(seconds=10)
async def version_checker():
    try:
        conn = get_db()
        if not conn:
            return

        cursor = conn.cursor()
        cursor.execute("SELECT guild_id, channel_id, mc_ip, auth_token FROM MCxDISCORD")
        rows = cursor.fetchall()
        conn.close()

        latest_versions = await get_latest_versions()

        async with aiohttp.ClientSession() as session:
            for guild_id, channel_id, mc_ip, token in rows:
                try:
                    async with session.post(f"http://{mc_ip}/link", data={"token": token}, timeout=5) as resp:
                        if resp.status != 200:
                            continue
                except Exception:
                    continue

                version = None
                try:
                    async with session.get(f"http://{mc_ip}/version", timeout=5) as vresp:
                        if vresp.status == 200:
                            version = (await vresp.text()).strip()
                except Exception:
                    pass

                key = (guild_id, channel_id)
                channel = bot.get_channel(int(channel_id))
                if not channel:
                    continue

                guild = bot.get_guild(int(guild_id))
                owner = guild.owner if guild else None

                if not version:
                    if warned_versions.get(key) != "fail":
                        warned_versions[key] = "fail"
                        embed = discord.Embed(
                            title="❗ Outdated Plugin!",
                            description="This server is missing the version endpoint.\nDownload the latest: https://modrinth.com/plugin/mcxdiscord",
                            color=0xff0000
                        )
                        try:
                            await channel.send(embed=embed)
                        except Exception:
                            pass
                        if owner:
                            try:
                                await owner.send(embed=embed)
                            except Exception:
                                pass
                    continue

                platform = "spigot" if "spigot" in version.lower() else "paper"
                latest = latest_versions.get(platform)

                if latest and version == latest:
                    if warned_versions.get(key) != "ok":
                        warned_versions[key] = "ok"
                        embed = discord.Embed(
                            title="✅ Plugin Updated!",
                            description=f"Thanks for updating to {version} — you're now running the latest version.",
                            color=0x00ff00
                        )
                        try:
                            await channel.send(embed=embed)
                        except Exception:
                            pass
                        if owner:
                            try:
                                await owner.send(embed=embed)
                            except Exception:
                                pass

                elif latest and version != latest:
                    if warned_versions.get(key) != version:
                        warned_versions[key] = version
                        embed = discord.Embed(
                            title="🔁 Outdated Plugin Detected!",
                            description=f"You're running {version} — latest for {platform} is {latest}\nDownload: https://modrinth.com/plugin/mcxdiscord",
                            color=0xff0000
                        )
                        try:
                            await channel.send(embed=embed)
                        except Exception:
                            pass
                        if owner:
                            try:
                                await owner.send(embed=embed)
                            except Exception:
                                pass
    except Exception as e:
        print(f"[version_checker] Error in loop: {e}")

import asyncio, subprocess, sys, os, tempfile
from discord import ui, app_commands

AUTHORIZED_USERS = {806806527192334356}

# --- Async git helper ---
async def async_git_run(args, password=None):
    env = os.environ.copy()
    script_path = None
    if password:
        # Temporary script that echoes the password
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write(f'#!/bin/sh\necho "{password}"\n')
            script_path = f.name
        os.chmod(script_path, 0o700)
        env["GIT_ASKPASS"] = script_path

    try:
        result = await asyncio.to_thread(
            subprocess.run,
            args,
            {"check": True, "capture_output": True, "text": True, "env": env}
        )
        return result.stdout
    finally:
        if script_path:
            os.remove(script_path)

# --- Modal for password input ---
class GitPasswordModal(ui.Modal, title="Git Password / Token"):
    password = ui.TextInput(label="Password or Token", required=True)

    def __init__(self, interaction, force: bool):
        super().__init__()
        self.interaction = interaction
        self.force = force

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            await async_git_run(["git", "fetch"], self.password.value)
            current_commit = (await async_git_run(["git", "rev-parse", "HEAD"], self.password.value)).strip()
            remote_commit = (await async_git_run(["git", "rev-parse", "origin/main"], self.password.value)).strip()

            if not self.force and current_commit == remote_commit:
                await interaction.followup.send("✅ Already up to date.", ephemeral=True)
                return

            if self.force:
                await async_git_run(["git", "reset", "--hard", "origin/main"], self.password.value)
                action_text = "Force-updated repository to latest commit."
            else:
                await async_git_run(["git", "pull"], self.password.value)
                action_text = "Updated repository to latest commit."

            await interaction.followup.send(f"✅ {action_text}\nRestarting...", ephemeral=True)

            python_exec = sys.executable
            os.execv(python_exec, [python_exec, "app.py"])

        except subprocess.CalledProcessError as e:
            await interaction.followup.send(f"❌ Git operation failed:\n```\n{e}\n```", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Unexpected error:\n```\n{e}\n```", ephemeral=True)


@bot.tree.command(name="link", description="Link a channel to a Minecraft server")
@is_admin()
@app_commands.describe(
    channel="Channel to link",
    mc_ip="Minecraft server IP",
    port="Plugin port",
    auth_token="Authentication token"
)
async def link(interaction: discord.Interaction, channel: discord.TextChannel, mc_ip: str, port: int, auth_token: str):
    try:
        await interaction.response.send_message(embed=discord.Embed(
            title="🔗 Linking...", description="Working...", color=0xffff00), ephemeral=True)

        full_address = f"{mc_ip}:{port}"
        embed = discord.Embed(title="🔗 Link Result", color=0xffff00)
        embed.add_field(name="Channel", value=channel.mention, inline=False)
        embed.add_field(name="MC IP", value=mc_ip, inline=True)
        embed.add_field(name="Port", value=str(port), inline=True)

        plugin_ok = False
        debug_log = []

        async with aiohttp.ClientSession() as session:
            for attempt in range(1, 6):
                try:
                    async with session.post(
                        f"http://{mc_ip}:{port}/link",
                        data={"token": auth_token},
                        timeout=5
                    ) as resp:
                        debug_log.append(f"[try {attempt}] plugin = {resp.status} {resp.reason}")
                        if resp.status == 200:
                            plugin_ok = True
                            break
                except Exception as e:
                    debug_log.append(f"[try {attempt}] plugin = {e}")
                await asyncio.sleep(0.5)

            embed.add_field(
                name="Plugin Test",
                value="✅ Connected" if plugin_ok else "❌ Failed to reach plugin",
                inline=False
            )

            try:
                async with session.get(f"https://api.mcsrvstat.us/2/{mc_ip}", timeout=5) as resp:
                    data = await resp.json()
                    if data.get("online"):
                        embed.add_field(name="Ping Test", value="✅ Server reached", inline=False)
                    else:
                        embed.add_field(name="Ping Test", value="❌ Server not reached.", inline=False)
            except Exception as e:
                embed.add_field(name="Ping Test", value=f"❌ Ping failed: {e}", inline=False)

        if not plugin_ok:
            embed.add_field(
                name="Debug Hint",
                value="Run /plugins and make sure **MCxDiscord** shows up green. If it does and this still fails, report the issue at https://github.com/Semmelbrot12/MCxDiscord/issues.",
                inline=False
            )
            debug_text = "\n".join(debug_log)
            if len(debug_text) <= 1024:
                embed.add_field(name="Plugin Logs", value=debug_text, inline=False)
                await interaction.edit_original_response(embed=embed)
            else:
                await interaction.edit_original_response(embed=embed)
                await interaction.followup.send(
                    file=discord.File(io.StringIO(debug_text), filename="plugin_debug_log.txt"),
                    ephemeral=True
                )
            return

        conn = get_db()
        if not conn:
            embed.add_field(name="Database", value="❌ Connection failed", inline=False)
            await interaction.edit_original_response(embed=embed)
            return

        try:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO MCxDISCORD (guild_id, channel_id, mc_ip, auth_token) VALUES (%s, %s, %s, %s)",
                (str(interaction.guild_id), str(channel.id), full_address, auth_token)
            )
            conn.commit()
            embed.add_field(name="Database", value="✅ Linked successfully", inline=False)
            await update_presence()
        except Exception as e:
            embed.add_field(name="Database", value=f"❌ Error saving link: {e}", inline=False)
        finally:
            conn.close()

        await interaction.edit_original_response(embed=embed)
    except Exception as e:
        print(f"[link] Command error: {e}")
        try:
            await interaction.response.send_message("❌ An error occurred during linking.", ephemeral=True)
        except:
            pass


@bot.tree.command(name="unlink", description="Unlink a channel")
@is_admin()
@app_commands.describe(channel="Channel to unlink")
async def unlink(interaction: discord.Interaction, channel: discord.TextChannel):
    try:
        conn = get_db()
        if conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM MCxDISCORD WHERE guild_id = %s AND channel_id = %s", (
                str(interaction.guild_id), str(channel.id)
            ))
            conn.commit()
            conn.close()
            await update_presence()
            warned_versions.pop((str(interaction.guild_id), str(channel.id)), None)

        embed = discord.Embed(title="🗑️ Unlink Result", color=0xff0000)
        embed.add_field(name="Channel", value=channel.mention, inline=False)
        embed.add_field(name="Status", value="✅ Unlinked", inline=False)
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        print(f"[unlink] Command error: {e}")
        try:
            await interaction.response.send_message("❌ An error occurred during unlinking.", ephemeral=True)
        except:
            pass

@bot.tree.command(name="playerlist", description="Get the list of online players on the linked Minecraft server")
@is_admin()
async def playerlist(interaction: discord.Interaction):
    try:
        await interaction.response.defer(ephemeral=True)

        conn = get_db()
        if not conn:
            await interaction.followup.send("❌ Database connection failed.", ephemeral=True)
            return

        cursor = conn.cursor()
        cursor.execute(
            "SELECT mc_ip, auth_token FROM MCxDISCORD WHERE guild_id = %s AND channel_id = %s",
            (str(interaction.guild_id), str(interaction.channel.id))
        )
        result = cursor.fetchone()
        conn.close()

        if not result:
            await interaction.followup.send("❌ This channel is not linked to a Minecraft server.", ephemeral=True)
            return

        mc_ip, auth_token = result

        # Assume the plugin exposes /playerlist endpoint that returns plain text list of players
        url = f"http://{mc_ip}/playerlist"

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, timeout=5) as resp:
                    if resp.status != 200:
                        await interaction.followup.send(f"❌ Failed to fetch player list (HTTP {resp.status}).", ephemeral=True)
                        return
                    text = await resp.text()
            except Exception as e:
                await interaction.followup.send(f"❌ Error fetching player list: {e}", ephemeral=True)
                return

        players = text.strip().splitlines()
        if not players or players == ['']:
            await interaction.followup.send("No players are currently online.", ephemeral=True)
            return

        # Format list (max 2000 chars for Discord message)
        player_list = ", ".join(players)
        if len(player_list) > 1900:
            player_list = player_list[:1900] + "…"

        embed = discord.Embed(
            title="🧑‍🤝‍🧑 Online Players",
            description=player_list,
            color=0x00ffff
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    except Exception as e:
        print(f"[playerlist] Command error: {e}")
        try:
            await interaction.response.send_message("❌ An error occurred while fetching the player list.", ephemeral=True)
        except:
            pass


@bot.tree.command(name="links", description="List all linked channels")
@is_admin()
async def links(interaction: discord.Interaction):
    try:
        embed = discord.Embed(title="📄 Linked Channels", color=0x00ffff)
        conn = get_db()
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, channel_id, mc_ip FROM MCxDISCORD WHERE guild_id = %s", (
                str(interaction.guild_id),))
            results = cursor.fetchall()
            conn.close()
            if results:
                for id_, chan_id, ip in results:
                    embed.add_field(name=f"ID: {id_} - <#{chan_id}>", value=f"MC IP: {ip}", inline=False)
            else:
                embed.description = "No channels linked."
        else:
            embed.description = "❌ DB error. Report this to https://github.com/Semmelbrot12/MCxDiscord/issues"

        await interaction.response.send_message(embed=embed)
    except Exception as e:
        print(f"[links] Command error: {e}")
        try:
            await interaction.response.send_message("❌ An error occurred listing links.", ephemeral=True)
        except:
            pass



# --- /manage command with embed GUI and PTR check ---
from discord import ui
import time, socket, json, asyncio, aiohttp, discord

# --- PTR cache setup ---
PTR_CACHE_FILE = "ptr_cache.json"
PTR_CACHE_DURATION = 24 * 3600  # 24 hours

if os.path.exists(PTR_CACHE_FILE):
    try:
        with open(PTR_CACHE_FILE, "r") as f:
            ptr_cache = json.load(f)
    except Exception:
        ptr_cache = {}
else:
    ptr_cache = {}

def save_ptr_cache():
    try:
        with open(PTR_CACHE_FILE, "w") as f:
            json.dump(ptr_cache, f, indent=2)
    except Exception as e:
        print(f"[PTR Cache] Failed to save: {e}")

async def resolve_ptr(host):
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, lambda: socket.gethostbyaddr(host)[0].lower())
    except Exception:
        return "unknown"

# --- GUI classes ---
class CommandModal(ui.Modal, title="Run Console Command"):
    cmd = ui.TextInput(label="Command", placeholder="say Hello world", required=True)
    def __init__(self, view):
        super().__init__()
        self.view = view
    async def on_submit(self, interaction: discord.Interaction):
        try:
            result = await self.view.run_command(self.cmd.value)
            ok = result.get("ok", False)
            msg = result.get("cmd") or result.get("error") or "No response."
            color = 0x00ff00 if ok else 0xff0000
            embed = discord.Embed(title="Command Result", description=msg, color=color)
            await interaction.response.edit_message(embed=embed, view=self.view)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error running command: {e}", ephemeral=True)

class ManageView(ui.View):
    def __init__(self, mc_ip, port, token):
        super().__init__(timeout=120)
        self.mc_ip = mc_ip
        self.port = port
        self.token = token

    async def fetch_stats(self):
        url = f"http://{self.mc_ip}:{self.port}/server/stats"
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data={"token": self.token}, timeout=7) as resp:
                return await resp.json()

    async def fetch_players(self):
        url = f"http://{self.mc_ip}:{self.port}/server/players"
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data={"token": self.token}, timeout=7) as resp:
                return await resp.json()

    async def fetch_embed(self):
        url = f"http://{self.mc_ip}:{self.port}/server/embed"
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data={"token": self.token}, timeout=7) as resp:
                return await resp.json()

    async def run_command(self, cmd):
        url = f"http://{self.mc_ip}:{self.port}/server/command"
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data={"token": self.token, "cmd": cmd}, timeout=10) as resp:
                return await resp.json()

    @ui.button(label="Server Stats", style=discord.ButtonStyle.primary, custom_id="stats")
    async def stats_btn(self, interaction: discord.Interaction, button: ui.Button):
        try:
            stats = await self.fetch_stats()
            embed = discord.Embed(title="Server Stats", color=0x3498db)
            uptime = stats.get("uptimeMs", 0) // 1000
            embed.add_field(name="Uptime", value=f"{uptime//3600:02}:{(uptime%3600)//60:02}:{uptime%60:02}", inline=True)
            cpu = stats.get("cpu", {})
            embed.add_field(name="CPU", value=f"System: {cpu.get('systemPercent',-1)}% | Proc: {cpu.get('processPercent',-1)}% | Cores: {cpu.get('cores','?')}", inline=True)
            ram = stats.get("ram", {})
            embed.add_field(name="RAM", value=f"{ram.get('heapUsedBytes',0)//(1024**2)}/{ram.get('heapTotalBytes',0)//(1024**2)} MB", inline=True)
            storage = stats.get("storage", {})
            embed.add_field(name="Storage", value=f"{storage.get('usedBytes',0)//(1024**3)}/{storage.get('totalBytes',0)//(1024**3)} GB", inline=True)
            await interaction.response.edit_message(embed=embed, view=self)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error fetching stats: {e}", ephemeral=True)

    @ui.button(label="Players", style=discord.ButtonStyle.secondary, custom_id="players")
    async def players_btn(self, interaction: discord.Interaction, button: ui.Button):
        try:
            data = await self.fetch_players()
            players = data.get("players", [])
            names = ", ".join(p.get("name","?") for p in players) or "No players online."
            embed = discord.Embed(title=f"Players ({len(players)})", description=names, color=0x00ffff)
            await interaction.response.edit_message(embed=embed, view=self)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error fetching players: {e}", ephemeral=True)

    @ui.button(label="Run Command", style=discord.ButtonStyle.danger, custom_id="command")
    async def command_btn(self, interaction: discord.Interaction, button: ui.Button):
        modal = CommandModal(self)
        await interaction.response.send_modal(modal)

    @ui.button(label="Show Embed", style=discord.ButtonStyle.success, custom_id="embed")
    async def embed_btn(self, interaction: discord.Interaction, button: ui.Button):
        try:
            data = await self.fetch_embed()
            embeds = data.get("embeds", [])
            if embeds:
                e = embeds[0]
                embed = discord.Embed(title=e.get("title","Server Status"), color=0xadd8e6)
                for f in e.get("fields", []):
                    embed.add_field(name=f.get("name","-"), value=f.get("value","-"), inline=f.get("inline",False))
                await interaction.response.edit_message(embed=embed, view=self)
            else:
                await interaction.response.send_message("❌ No embed data returned.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error fetching embed: {e}", ephemeral=True)


@bot.tree.command(name="manage", description="Manage the linked Minecraft server (GUI)")
@is_admin()
async def manage(interaction: discord.Interaction):
    try:
        conn = get_db()
        if not conn:
            await interaction.response.send_message("❌ DB connection failed.", ephemeral=True)
            return
        cursor = conn.cursor()
        cursor.execute(
            "SELECT mc_ip, auth_token FROM MCxDISCORD WHERE guild_id = %s AND channel_id = %s",
            (str(interaction.guild_id), str(interaction.channel.id))
        )
        result = cursor.fetchone()
        conn.close()
        if not result:
            await interaction.response.send_message("❌ This channel is not linked.", ephemeral=True)
            return

        mc_ip, token = result
        port = 80
        if ":" in mc_ip:
            host, port_str = mc_ip.split(":", 1)
            try:
                port = int(port_str)
            except ValueError:
                pass
        else:
            host = mc_ip

        # --- PTR check with 24h cache ---
        cache_key = f"{interaction.guild_id}-{interaction.channel.id}"
        now = time.time()
        cached_entry = ptr_cache.get(cache_key)
        ptr = "unknown"
        warning_msg = None

        if cached_entry and now - cached_entry.get("timestamp", 0) < PTR_CACHE_DURATION:
            ptr = cached_entry.get("ptr", "unknown")
        else:
            # notify user that a one-time check is running
            await interaction.response.send_message(
                "🔍 Running a one-time host check (PTR lookup)...", ephemeral=True
            )
            ptr = await resolve_ptr(host)
            ptr_cache[cache_key] = {"ptr": ptr, "timestamp": now}
            save_ptr_cache()

        # Hetzner / FreeMcServer.net detection
        review_button = None
        if "hetzner" in ptr or "freemcserver" in ptr:
            warning_msg = (
                "⚠️ An automated check suspects that this server is hosted on FreeMcServer.net. "
                " Therefore, the /manage command has been disabled." 
                "If you are **not** using FreeMcServer.Net, please click the button below."
                
            )

            class ReviewButton(discord.ui.View):
                def __init__(self):
                    super().__init__(timeout=None)

                @discord.ui.button(label="I am not using FreeMcServer.net", style=discord.ButtonStyle.red, emoji="🚫")
                async def confirm(self, interaction_btn: discord.Interaction, button: discord.ui.Button):
                    log_channel = interaction.client.get_channel(1386716323706437683)
                    if log_channel:
                        embed = discord.Embed(
                            title="🕵️ Host Review Requested",
                            color=0xe67e22
                        )
                        embed.add_field(name="Guild", value=f"{interaction.guild.name} (`{interaction.guild_id}`)", inline=False)
                        embed.add_field(name="Channel", value=f"<#{interaction.channel.id}> (`{interaction.channel.id}`)", inline=False)
                        embed.add_field(name="Server IP", value=f"{host}:{port}", inline=False)
                        embed.set_footer(text=f"Requested by {interaction.user} ({interaction.user.id})")
                        await log_channel.send(embed=embed)

                    await interaction_btn.response.send_message(
                        "✅ Thank you. We will review this as soon as possible, usually no longer than 24 hours.",
                        ephemeral=True
                    )

            review_button = ReviewButton()

        # Send main GUI
        view = ManageView(host, port, token)
        embed = discord.Embed(
            title="MC×Discord Server Manager",
            description="Use the buttons below to manage your server.",
            color=0x3498db
        )
        if warning_msg:
            embed.add_field(name="Notice", value=warning_msg, inline=False)

        if review_button:
            await interaction.followup.send(embed=embed, view=review_button, ephemeral=True)
        else:
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    except Exception as e:
        print(f"[manage] Command error: {e}")
        try:
            await interaction.response.send_message("❌ An error occurred in /manage.", ephemeral=True)
        except:
            pass


@bot.tree.command(name="broadcast", description="Broadcast a message to all linked channels")
async def broadcast(interaction: discord.Interaction, header: str, message: str):
    try:
        if interaction.user.id != MCXDEV_ID:
            embed = discord.Embed(
                title="❌ Permission Denied",
                description="Only runnable by MC× Staff",
                color=0xadd8e6
            )
            embed.set_thumbnail(url=MCX_LOGO_URL)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        conn = get_db()
        if not conn:
            await interaction.followup.send("❌ Database connection failed.", ephemeral=True)
            return

        cursor = conn.cursor()
        cursor.execute("SELECT guild_id, channel_id FROM MCxDISCORD")
        rows = cursor.fetchall()
        conn.close()

        embed = discord.Embed(
            title=header,
            description=message,
            color=0xadd8e6
        )
        embed.set_thumbnail(url=MCX_LOGO_URL)

        success = 0
        for guild_id, channel_id in rows:
            try:
                channel = await bot.fetch_channel(int(channel_id))
                await channel.send(embed=embed)
                success += 1
            except Exception as e:
                print(f"[broadcast] Failed for {channel_id}: {e}")

        await interaction.followup.send(f"📣 Broadcast sent to {success} channels.", ephemeral=True)
    except Exception as e:
        print(f"[broadcast] Command error: {e}")
        try:
            await interaction.response.send_message("❌ An error occurred during broadcast.", ephemeral=True)
        except:
            pass
        

import matplotlib.pyplot as plt
from io import BytesIO
from collections import Counter


# Assuming your bot tracks these
bot.messages_seen = {}        # {guild_id: message_count}
bot.server_versions = {}      # {guild_id: "1.21.1", ...}
bot.start_time = datetime.utcnow()


MESSAGE_COUNT_FILE = "message_counts.json"

def load_message_counts():
    if os.path.exists(MESSAGE_COUNT_FILE):
        with open(MESSAGE_COUNT_FILE, "r") as f:
            return json.load(f)
    return {}

async def save_message_counts_periodically():
    while True:
        try:
            with open(MESSAGE_COUNT_FILE, "w") as f:
                json.dump(bot.messages_seen, f)
        except Exception as e:
            print(f"Error saving message counts: {e}")
        await asyncio.sleep(60)  # save every 60 seconds

@bot.event
async def on_message(message):
    # Ignore system messages
    if not message.guild or not message.channel:
        return

    # Skip bots unless it's the Minecraft bridge webhook
    if message.webhook_id:
        webhook_name = None
        try:
            webhook = await message.channel.fetch_webhook(message.webhook_id)
            webhook_name = webhook.name
        except Exception:
            pass
        if webhook_name != "MC×Disc Link":
            return
    elif message.author.bot:
        return

    # Only count messages from linked channels
    if getattr(bot, "linked_channels", None) and message.channel.id in bot.linked_channels:
        guild_id = str(message.guild.id)
        bot.messages_seen[guild_id] = bot.messages_seen.get(guild_id, 0) + 1

    await bot.process_commands(message)



@bot.tree.command(name="stats", description="Show bot usage statistics with charts")
async def stats(interaction: discord.Interaction):
    # --- Defer the interaction so Discord doesn't timeout ---
    await interaction.response.defer()

    # --- Load DB config ---
    with open("db_config.json", "r") as f:
        db_config = json.load(f)

    # --- Text stats ---
    uptime = datetime.utcnow() - bot.start_time
    uptime_str = str(uptime).split(".")[0]

    total_guilds = len(bot.guilds)
    total_members = sum(g.member_count for g in bot.guilds)
    total_messages = sum(bot.messages_seen.values())

    # --- Server size breakdown ---
    size_counts = {"<50":0,"<250":0,"<500":0,"<2500":0,"2500+":0}
    for g in bot.guilds:
        m = g.member_count
        if m < 50: size_counts["<50"] += 1
        elif m < 250: size_counts["<250"] += 1
        elif m < 500: size_counts["<500"] += 1
        elif m < 2500: size_counts["<2500"] += 1
        else: size_counts["2500+"] += 1

    embed = discord.Embed(title="🤖 Bot Stats", color=discord.Color.green())
    embed.add_field(name="Uptime", value=uptime_str, inline=True)
    embed.add_field(name="Servers", value=total_guilds, inline=True)
    embed.add_field(name="Total Users", value=total_members, inline=True)
    embed.add_field(name="Total Messages Seen", value=total_messages, inline=True)
    embed.add_field(
        name="Server Size Breakdown",
        value="\n".join(f"{k}: {v}" for k,v in size_counts.items()),
        inline=False
    )

    files = []

    # --- Messages per server bar chart ---
    if bot.messages_seen:
        guild_names = [bot.get_guild(gid).name for gid in bot.messages_seen.keys()]
        message_counts = [bot.messages_seen[gid] for gid in bot.messages_seen.keys()]

        plt.figure(figsize=(8, max(4, len(guild_names)*0.5)))
        plt.barh(guild_names, message_counts, color='skyblue')
        plt.xlabel("Messages")
        plt.title("Messages per Server")
        buf_messages = BytesIO()
        plt.tight_layout()
        plt.savefig(buf_messages, format='png')
        buf_messages.seek(0)
        plt.close()
        files.append(discord.File(buf_messages, filename="messages.png"))
        embed.set_image(url="attachment://messages.png")

    # --- Server size pie chart ---
    plt.figure(figsize=(6,6))
    plt.pie(size_counts.values(), labels=size_counts.keys(), autopct='%1.1f%%', startangle=140)
    plt.title("Server Size Distribution")
    buf_sizes = BytesIO()
    plt.savefig(buf_sizes, format='png')
    buf_sizes.seek(0)
    plt.close()
    files.append(discord.File(buf_sizes, filename="sizes.png"))

    # --- Fetch plugin versions concurrently via HTTP ---
    bot.server_versions = {}
    connection = mysql.connector.connect(
        host=db_config["host"],
        port=db_config["port"],
        user=db_config["user"],
        password=db_config["password"],
        database=db_config["database"]
    )
    cursor = connection.cursor()
    cursor.execute("SELECT guild_id, mc_ip FROM MCxDISCORD")
    rows = cursor.fetchall()
    cursor.close()
    connection.close()

    async def fetch_version(session, guild_id, mc_ip):
        ip, port = mc_ip.split(":")
        url = f"http://{ip}:{port}/version"
        try:
            async with session.get(url, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    bot.server_versions[guild_id] = data.get("version", "Unknown")
                else:
                    bot.server_versions[guild_id] = "Unknown"
        except Exception:
            bot.server_versions[guild_id] = "Unknown"

    async with aiohttp.ClientSession() as session:
        tasks = [fetch_version(session, guild_id, mc_ip) for guild_id, mc_ip in rows]
        await asyncio.gather(*tasks)

    # --- Plugin versions pie chart ---
    if bot.server_versions:
        version_counter = Counter(bot.server_versions.values())
        plt.figure(figsize=(6,6))
        plt.pie(version_counter.values(), labels=version_counter.keys(), autopct='%1.1f%%', startangle=140)
        plt.title("Plugin Versions Distribution")
        buf_versions = BytesIO()
        plt.savefig(buf_versions, format='png')
        buf_versions.seek(0)
        plt.close()
        files.append(discord.File(buf_versions, filename="versions.png"))

    # --- Send the final embed with files ---
    await interaction.followup.send(embed=embed, files=files)

###

# List of allowed user IDs
ALLOWED_IDS = [1121504039146889248, 806806527192334356]

@bot.tree.command(name="gitupdate", description="Update the bot via SSH and restart")
async def gitupdate(interaction: discord.Interaction):
    if interaction.user.id not in ALLOWED_IDS:
        return await interaction.response.send_message("❌ You are not authorized.", ephemeral=True)

    await interaction.response.defer(ephemeral=True)

    try:
        cwd = os.path.dirname(os.path.abspath(__file__))

        # Ensure SSH key is loaded in ssh-agent (adjust path if needed)
        subprocess.run(["ssh-add", os.path.expanduser("~/.ssh/id_rsa")], check=True)

        # Pull latest changes via SSH
        subprocess.run(["git", "fetch", "origin"], cwd=cwd, check=True)
        subprocess.run(["git", "pull", "origin", "main"], cwd=cwd, check=True)

        # Get current commit hash
        version = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=cwd
        ).decode().strip()

        embed = discord.Embed(
            title="✅ Update complete! Restarting...",
            description=f"Running version `{version}`",
            color=0x00FF00
        )
        await interaction.followup.send(embed=embed)

        # Restart the bot
        os.execv(sys.executable, [sys.executable] + sys.argv)

    except subprocess.CalledProcessError as e:
        await interaction.followup.send(f"❌ Git update failed:\n```\n{e}\n```")
###

@bot.tree.command(name="debug", description="Send a test debug message to a linked channel by DB ID")
@app_commands.describe(row_id="The ID from the MCxDISCORD table")
async def debug(interaction: discord.Interaction, row_id: int):
    try:
        if interaction.user.id != MCXDEV_ID:
            embed = discord.Embed(
                title="❌ Permission Denied",
                description="Only runnable by MC× Developers",
                color=0xadd8e6
            )
            embed.set_thumbnail(url=MCX_LOGO_URL)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        conn = get_db()
        if not conn:
            await interaction.followup.send("❌ Database connection failed.", ephemeral=True)
            return

        cursor = conn.cursor()
        cursor.execute("SELECT guild_id, channel_id FROM MCxDISCORD WHERE id = %s", (row_id,))
        result = cursor.fetchone()
        conn.close()

        if not result:
            await interaction.followup.send(f"❌ No entry found with ID {row_id}.", ephemeral=True)
            return

        guild_id, channel_id = result
        embed = discord.Embed(
            title="Debug",
            description="This message was triggered by a MC×Discord developer.",
            color=0xadd8e6
        )
        embed.set_thumbnail(url=MCX_LOGO_URL)

        try:
            channel = await bot.fetch_channel(int(channel_id))
            await channel.send(embed=embed)
            status = "✅ Sent successfully."
        except discord.Forbidden:
            status = "❌ Missing permissions to send."
        except discord.NotFound:
            status = "❌ Channel not found."
        except Exception as e:
            status = f"❌ Error: {type(e).__name__}: {e}"

        guild = bot.get_guild(int(guild_id))
        guild_name = guild.name if guild else f"{guild_id} (unknown)"
        try:
            channel_obj = await bot.fetch_channel(int(channel_id))
            channel_name = f"{channel_obj.name} ({channel_id})"
            channel_mention = channel_obj.mention
        except Exception:
            channel_name = f"{channel_id}"
            channel_mention = f"<#{channel_id}>"

        result_embed = discord.Embed(
            title="📡 Debug Result",
            color=0xadd8e6
        )
        result_embed.add_field(name="Guild", value=guild_name, inline=False)
        result_embed.add_field(name="Channel", value=f"{channel_name} ({channel_mention})", inline=False)
        result_embed.add_field(name="Status", value=status, inline=False)
        await interaction.followup.send(embed=result_embed, ephemeral=True)
    except Exception as e:
        print(f"[debug] Command error: {e}")
        try:
            await interaction.response.send_message("❌ An error occurred during debug.", ephemeral=True)
        except:
            pass


@bot.event
async def on_message(message: discord.Message):
    try:
        found = False
        for cell in debug_global_stats["messages"]:
            try:
                if cell[0] == message.guild.name:
                    found = True
                    cell[1] += 1
            except Exception as e:
                print(f"[on_message] Error processing message cell: {e}")
        if not found:
            debug_global_stats["messages"].append([message.guild.name, 0, []])

        if message.author.bot or not message.guild:
            return

        conn = get_db()
        if not conn:
            return

        cursor = conn.cursor()
        cursor.execute("SELECT mc_ip, auth_token FROM MCxDISCORD WHERE guild_id = %s AND channel_id = %s", (
            str(message.guild.id), str(message.channel.id)
        ))
        result = cursor.fetchone()
        conn.close()

        if result:
            mc_ip, auth_token = result
            async with aiohttp.ClientSession() as session:
                try:
                    resp = await session.post(
                        f"http://{mc_ip}/chat",
                        data={"token": auth_token, "user": message.author.display_name, "msg": message.content},
                        timeout=5
                    )
                    if resp.status == 403:
                        try:
                            await message.add_reaction("❌")
                            blocked_messages[message.id] = message.author.id
                        except Exception as e:
                            print(f"[moderation] Failed to react: {e}")
                except Exception as e:
                    print(f"[moderation] Chat forwarding error: {e}")
    except Exception as e:
        print(f"[on_message] Error: {e}")



@bot.event
async def on_reaction_add(reaction, user):
    try:
        if reaction.message.id not in blocked_messages:
            return
        if str(reaction.emoji) != "❌":
            return

        original_author_id = blocked_messages[reaction.message.id]
        if user.id != original_author_id:
            return

        embed = discord.Embed(
            title="⚠️ Message Blocked by Moderation",
            description="ChatMod Rule Violation. Please keep your messages appropriate.",
            color=0xff0000
        )
        embed.set_footer(text="If you believe this was a mistake, contact a moderator.")
        try:
            await reaction.message.channel.send(content=user.mention, embed=embed)
        except Exception as e:
            print(f"[moderation] Failed to send moderation embed: {e}")
    except Exception as e:
        print(f"[on_reaction_add] Error: {e}")


@tasks.loop(hours=24)
async def unlinked_reminder():
    try:
        today = datetime.utcnow().date()

        conn = get_db()
        linked_guilds = set()
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT guild_id FROM MCxDISCORD")
            linked_guilds.update(row[0] for row in cursor.fetchall())
            conn.close()

        for guild in bot.guilds:
            try:
                if str(guild.id) in linked_guilds:
                    continue
                if last_unlinked_ping.get(guild.id) == today:
                    continue

                embed = discord.Embed(
                    title="You didn't link yet!",
                    description=(
                        "To experience the full power of **MC×Discord**, please use /link "
                        "inside the Minecraft channel you want to connect.\n\n"
                        "This enables chat, version checking, broadcast alerts, and more!"
                    ),
                    color=0x3498db  # Blue
                )

                for channel in guild.text_channels:
                    try:
                        await channel.send(embed=embed)
                    except Exception:
                        continue

                last_unlinked_ping[guild.id] = today
            except Exception as e:
                print(f"[unlinked_reminder] Failed sending to guild {guild.id}: {e}")
    except Exception as e:
        print(f"[unlinked_reminder] Error in loop: {e}")

TOKEN_FILE = "token.txt"
TOKEN_CHECKER = "token_checker.py"

@bot.event
async def on_ready():
    print(f"[ready] Logged in as {bot.user}")

    global debug_global_stats

    # Load global stats / message counts safely
    if os.path.exists(GLOBAL_DATA_FILE):
        try:
            with open(GLOBAL_DATA_FILE, "r") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    # Merge loaded data with defaults
                    debug_global_stats.update({
                        "messages": data.get("messages", []),
                        "versions": data.get("versions", {}),
                        "guilds": data.get("guilds", [])
                    })
                else:
                    print("[warning] Invalid data type in GLOBAL_DATA_FILE; resetting stats.")
        except Exception as e:
            print(f"[warning] Failed to load GLOBAL_DATA_FILE: {e}")
    else:
        # Create the file if it doesn't exist
        try:
            with open(GLOBAL_DATA_FILE, "w") as f:
                json.dump(debug_global_stats, f, indent=2)
        except Exception as e:
            print(f"[warning] Failed to create GLOBAL_DATA_FILE: {e}")

    # Load per-bot message counts
    bot.messages_seen = load_message_counts()
    bot.loop.create_task(save_message_counts_periodically())

    # Sync slash commands
    try:
        await bot.tree.sync()
        print("[ready] Slash commands synced!")
    except Exception as e:
        print(f"[ready] Failed to sync slash commands: {e}")

    # Start background tasks
    version_checker.start()
    daily_calculator.start()
    await update_presence()


# Run the bot
if os.path.exists(TOKEN_FILE):
    with open(TOKEN_FILE, "r") as f:
        token = f.read().strip()
    bot.run(token)
else:
    # If token.txt does not exist, start token_checker.py
    subprocess.run(["python", TOKEN_CHECKER])

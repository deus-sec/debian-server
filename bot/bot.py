import discord
from discord import app_commands
from discord.ext import commands
import subprocess
import os
import asyncio
import re
from dotenv import load_dotenv
from datetime import datetime

load_dotenv('/opt/happyfork-bot/.env')
TOKEN      = os.getenv('DISCORD_BOT_TOKEN')
CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID'))
GUILD_ID   = int(os.getenv('DISCORD_GUILD_ID'))
ALERT_FILE = '/tmp/ssh_alert.txt'
AUTHELIA_NOTIF_FILE = '/var/log/authelia/notifications.txt'

intents = discord.Intents.default()
bot = commands.Bot(command_prefix='!', intents=intents)

# ── Boutons SSH ──────────────────────────────────────────
class SSHAlertView(discord.ui.View):
    def __init__(self, ip: str):
        super().__init__(timeout=300)
        self.ip = ip

    @discord.ui.button(label="✅ Connexion légitime", style=discord.ButtonStyle.success)
    async def legitimate(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.clear_items()
        await interaction.response.edit_message(
            embed=interaction.message.embeds[0].set_footer(text=f"✅ Validée par {interaction.user.name}"),
            view=self
        )

    @discord.ui.button(label="🚫 Bloquer cette IP", style=discord.ButtonStyle.danger)
    async def block(self, interaction: discord.Interaction, button: discord.ui.Button):
        result = subprocess.run(
            ["ufw", "deny", "from", self.ip, "comment", f"Bloque par {interaction.user.name} via Discord"],
            capture_output=True, text=True
        )
        self.clear_items()
        embed = interaction.message.embeds[0]
        embed.color = 0xe74c3c
        embed.set_footer(text=f"🚫 IP {self.ip} bloquée par {interaction.user.name}")
        await interaction.response.edit_message(embed=embed, view=self)
        await interaction.followup.send(f"🚫 `ufw deny from {self.ip}` exécuté.", ephemeral=True)

# ── Surveillance fichier alertes SSH ────────────────────
async def watch_ssh_alerts():
    await bot.wait_until_ready()
    ch = bot.get_channel(CHANNEL_ID)
    last_mtime = 0
    while True:
        try:
            mtime = os.path.getmtime(ALERT_FILE)
            if mtime != last_mtime:
                last_mtime = mtime
                with open(ALERT_FILE) as f:
                    data = {}
                    for line in f:
                        if '=' in line:
                            k, v = line.strip().split('=', 1)
                            data[k] = v
                pam_type = data.get('PAM_TYPE', '')
                user     = data.get('PAM_USER', '?')
                ip       = data.get('PAM_RHOST', '?')
                date     = data.get('DATE', '?')
                if pam_type == 'open_session':
                    embed = discord.Embed(title="🔔 Connexion SSH", color=0xe67e22)
                    embed.add_field(name="Utilisateur", value=user, inline=True)
                    embed.add_field(name="IP source",   value=ip,   inline=True)
                    embed.add_field(name="Heure",       value=date, inline=False)
                    await ch.send(embed=embed, view=SSHAlertView(ip))
                elif pam_type == 'close_session':
                    embed = discord.Embed(title="✅ Déconnexion SSH", color=0x2ecc71)
                    embed.add_field(name="Utilisateur", value=user, inline=True)
                    embed.add_field(name="IP source",   value=ip,   inline=True)
                    embed.add_field(name="Heure",       value=date, inline=False)
                    await ch.send(embed=embed)
        except Exception as e:
            print(f"Erreur lecture alerte : {e}")
        await asyncio.sleep(2)

# ── Surveillance notifications Authelia ─────────────────
async def watch_authelia_notifications():
    await bot.wait_until_ready()
    ch = bot.get_channel(CHANNEL_ID)
    last_size = 0
    while True:
        try:
            size = os.path.getsize(AUTHELIA_NOTIF_FILE)
            if size > last_size:
                with open(AUTHELIA_NOTIF_FILE, 'r') as f:
                    content = f.read()
                codes = re.findall(r'\b[A-Z0-9]{8}\b', content)
                users = re.findall(r'intended for (\w+)\.', content)
                if codes and users:
                    code = codes[-1]
                    user = users[-1]
                    embed = discord.Embed(
                        title="🔐 HappyFork — Code de vérification",
                        color=0x3498db
                    )
                    embed.add_field(name="Utilisateur", value=user, inline=False)
                    embed.add_field(name="Code", value=f"`{code}`", inline=False)
                    embed.set_footer(text="Transmettre ce code à l'utilisateur. Valable quelques minutes.")
                    await ch.send(embed=embed)
                last_size = size
        except Exception as e:
            pass
        await asyncio.sleep(2)

# ── Événements ───────────────────────────────────────────
@bot.event
async def on_ready():
    await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
    bot.loop.create_task(watch_ssh_alerts())
    bot.loop.create_task(watch_authelia_notifications())
    ch = bot.get_channel(CHANNEL_ID)
    if ch:
        embed = discord.Embed(title="🟢 HappyFork Bot en ligne", color=0x2ecc71,
                              description=f"Connecté — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        await ch.send(embed=embed)

# ── Commandes slash ──────────────────────────────────────
@bot.tree.command(name="status", description="État des services HappyFork", guild=discord.Object(id=GUILD_ID))
async def status(interaction: discord.Interaction):
    services = ["postgresql", "filebrowser", "apache2", "authelia", "caddy", "fail2ban", "happyfork-bot", "sync-api"]
    lines = []
    for s in services:
        r = subprocess.run(["systemctl", "is-active", s], capture_output=True, text=True)
        icon = "🟢" if r.stdout.strip() == "active" else "🔴"
        lines.append(f"{icon} `{s}`")
    embed = discord.Embed(title="📊 État des services", description="\n".join(lines), color=0x3498db)
    embed.timestamp = datetime.now()
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="bans", description="IPs bannies par Fail2ban", guild=discord.Object(id=GUILD_ID))
async def bans(interaction: discord.Interaction):
    r = subprocess.run(["fail2ban-client", "status", "sshd"], capture_output=True, text=True)
    banned = ""
    for line in r.stdout.splitlines():
        if "Banned IP" in line:
            banned = line.split(":")[-1].strip()
    desc = f"`{banned}`" if banned else "Aucune IP bannie."
    embed = discord.Embed(title="🚫 IPs bannies SSH", description=desc, color=0xe74c3c)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="unban", description="Débannir une IP", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(ip="Adresse IP à débannir")
async def unban(interaction: discord.Interaction, ip: str):
    r = subprocess.run(["fail2ban-client", "set", "sshd", "unbanip", ip], capture_output=True, text=True)
    color = 0x2ecc71 if r.returncode == 0 else 0xe74c3c
    msg = f"`{ip}` débannie." if r.returncode == 0 else f"Erreur : `{r.stderr.strip()}`"
    embed = discord.Embed(title="🔓 Déban IP", description=msg, color=color)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="logs", description="20 dernières lignes SSH", guild=discord.Object(id=GUILD_ID))
async def logs(interaction: discord.Interaction):
    r = subprocess.run(["journalctl", "-u", "ssh", "-n", "20", "--no-pager"], capture_output=True, text=True)
    lines = r.stdout[-1800:] if len(r.stdout) > 1800 else r.stdout
    embed = discord.Embed(title="📋 Logs SSH", description=f"```{lines}```", color=0x95a5a6)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="exports", description="Fichiers CSV disponibles", guild=discord.Object(id=GUILD_ID))
async def exports(interaction: discord.Interaction):
    r = subprocess.run(["ls", "-lht", "/srv/exports/"], capture_output=True, text=True)
    embed = discord.Embed(title="📁 Exports CSV", description=f"```{r.stdout[:1800]}```", color=0x9b59b6)
    await interaction.response.send_message(embed=embed)

bot.run(TOKEN)

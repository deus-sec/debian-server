# Installation Guide
PASTE THIS ON OBSIDIAN 
> **Version 2.0 — April 2026**  
> Secure server stack on Debian 13 — full setup from scratch.

---

## Before you start — collect these values

Store them in a password manager (KeePass, ProtonPass...) before starting.

| Variable | Description | Your value |
|---|---|---|
| `YOUR_IP` | VM IP address (run `ip a` after boot) | ____________ |
| `GATEWAY_IP` | Hypervisor gateway (VMware: usually `x.x.x.1`) | ____________ |
| `DISCORD_WEBHOOK` | Discord webhook URL (see §A) | ____________ |
| `DISCORD_BOT_TOKEN` | Discord bot token (see §B) | ____________ |
| `DISCORD_CHANNEL_ID` | Discord channel ID (see §C) | ____________ |
| `DISCORD_GUILD_ID` | Discord server ID (see §C) | ____________ |
| `SECRET_JWT` | Random 32+ char string (see §D) | ____________ |
| `SECRET_SESSION` | Random 32+ char string (see §D) | ____________ |
| `SECRET_STORAGE` | Random 32+ char string (see §D) | ____________ |

---

## Appendix A — Create a Discord Webhook

1. Open Discord → go to your server
2. Right-click the target channel → **Edit Channel**
3. **Integrations** → **Webhooks** → **New Webhook**
4. Name it (e.g. `server-alerts`)
5. Copy the webhook URL → this is your `DISCORD_WEBHOOK`

Format: `https://discord.com/api/webhooks/123456789/xxxxxxxxxxxxx`

---

## Appendix B — Create a Discord Bot and get the Token

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications)
2. **New Application** → name it (e.g. `deus-bot`)
3. Go to the **Bot** tab → **Add Bot**
4. Under Token → **Reset Token** → copy it → this is your `DISCORD_BOT_TOKEN`
5. Enable **Privileged Gateway Intents**:
   - Message Content Intent ✅
   - Server Members Intent ✅
6. Go to **OAuth2** → **URL Generator**
   - Scopes: `bot` + `applications.commands`
   - Bot Permissions: `Send Messages`, `Embed Links`, `Use Slash Commands`
7. Copy the generated URL → open it → invite the bot to your server

---

## Appendix C — Find Discord IDs

> Enable **Developer Mode** in Discord: User Settings → Advanced → Developer Mode ✅

- **Channel ID**: Right-click the channel → **Copy ID**
- **Guild ID** (Server ID): Right-click the server name → **Copy ID**

---

## Appendix D — Generate secrets

```bash
openssl rand -hex 32   # SECRET_JWT
openssl rand -hex 32   # SECRET_SESSION
openssl rand -hex 32   # SECRET_STORAGE
```

Run the command 3 times and save each result separately.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [System setup](#2-system-setup)
3. [PostgreSQL 17](#3-postgresql-17)
4. [CSV export](#4-csv-export)
5. [Filebrowser](#5-filebrowser)
6. [Adminer](#6-adminer)
7. [SSL certificate](#7-ssl-certificate)
8. [Authelia](#8-authelia)
9. [Caddy](#9-caddy)
10. [Web portal](#10-web-portal)
11. [UFW](#11-ufw)
12. [Fail2ban](#12-fail2ban)
13. [SSH Discord alerts](#13-ssh-discord-alerts)
14. [Discord bot](#14-discord-bot)
15. [Sync API](#15-sync-api)
16. [WireGuard VPN](#16-wireguard-vpn)
17. [Maintenance scripts](#17-maintenance-scripts)
18. [Final check](#18-final-check)
19. [User management](#19-user-management)

---

## 1. Prerequisites

- Debian 13 (bare metal or VM — min: 2 vCPU, 4GB RAM, 28GB disk)
- Root access
- Active internet connection
- Values collected from the table above

---

## 2. System setup

### 2.1 Update and base tools

```bash
apt update && apt upgrade -y
apt install -y curl wget git nano ufw fail2ban net-tools sudo qrencode wireguard wireguard-tools
```

### 2.2 Check VM IP

```bash
ip a | grep inet
```

> Note the IP — this is your `YOUR_IP`. Use throughout the configuration.  
> If the IP changes between sessions (different network), use the `change-ip` script (§17.4).

### 2.3 Create admin user

```bash
useradd -m -s /bin/bash admin
passwd admin
usermod -aG sudo admin
```

### 2.4 Timezone

```bash
timedatectl set-timezone Europe/Brussels
# Adapt as needed: Europe/Paris, America/New_York, etc.
timedatectl status
```

---

## 3. PostgreSQL 17

### 3.1 Install

```bash
apt install -y postgresql postgresql-contrib
systemctl enable postgresql
systemctl start postgresql
```

### 3.2 Create database and users

> ⚠️ The `!` character in passwords breaks bash. Always use `su -s /bin/bash postgres` + `set +H`.

```bash
su -s /bin/bash postgres
set +H
psql -c "CREATE DATABASE my_database;"
psql -c "CREATE USER db_app WITH ENCRYPTED PASSWORD 'YourPassword1!';"
psql -c "CREATE USER db_reader WITH ENCRYPTED PASSWORD 'YourPassword2!';"
psql -c "GRANT ALL PRIVILEGES ON DATABASE my_database TO db_app;"
psql -c "GRANT CONNECT ON DATABASE my_database TO db_reader;"
psql -d my_database -c "GRANT SELECT ON ALL TABLES IN SCHEMA public TO db_reader;"
psql -d my_database -c "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO db_reader;"
exit
```

> `db_app` = full access (application)  
> `db_reader` = read-only (CSV exports)

### 3.3 Configure pg_hba.conf

> ⚠️ Use `md5` — do NOT use `scram-sha-256` as Adminer (PHP) does not support it correctly.

```bash
cat > /etc/postgresql/17/main/pg_hba.conf << 'EOF'
local   all             postgres                                peer
local   all             all                                     md5
host    all             all             127.0.0.1/32            md5
host    all             all             ::1/128                 md5
local   replication     all                                     peer
host    replication     all             127.0.0.1/32            md5
host    replication     all             ::1/128                 md5
EOF
systemctl restart postgresql
```

### 3.4 Create table and grant permissions

```bash
su -s /bin/bash postgres
psql -d my_database << 'EOF'
CREATE TABLE clients (
  id SERIAL PRIMARY KEY,
  last_name VARCHAR(100) NOT NULL,
  first_name VARCHAR(100) NOT NULL,
  email VARCHAR(200) UNIQUE NOT NULL,
  phone VARCHAR(20),
  created_at TIMESTAMP DEFAULT NOW()
);
\q
EOF

set +H
psql -d my_database -c "GRANT ALL PRIVILEGES ON TABLE clients TO db_app;"
psql -d my_database -c "GRANT USAGE, SELECT ON SEQUENCE clients_id_seq TO db_app;"
psql -d my_database -c "GRANT SELECT ON TABLE clients TO db_reader;"
exit
```

---

## 4. CSV export

### 4.1 Export directory

```bash
mkdir -p /srv/exports
chown root:root /srv/exports
chmod 755 /srv/exports
```

### 4.2 Export script

```bash
cat > /usr/local/bin/export_csv.sh << 'EOF'
#!/bin/bash
DATE=$(date '+%Y%m%d_%H%M')
OUTPUT="/srv/exports/data_${DATE}.csv"
sudo -u postgres psql -d my_database -c "
  COPY (SELECT * FROM clients ORDER BY id)
  TO STDOUT WITH CSV HEADER
" > "$OUTPUT"
cp "$OUTPUT" /srv/exports/data_latest.csv
echo "$(date) - Export OK : $OUTPUT" >> /var/log/server_export.log
EOF
chmod +x /usr/local/bin/export_csv.sh
```

### 4.3 Hourly cron

```bash
(crontab -l 2>/dev/null; echo '0 * * * * /usr/local/bin/export_csv.sh') | crontab -
```

---

## 5. Filebrowser

### 5.1 Install

```bash
curl -fsSL https://raw.githubusercontent.com/filebrowser/get/master/get.sh | bash
```

### 5.2 Configure

```bash
mkdir -p /var/lib/filebrowser
filebrowser -d /var/lib/filebrowser/filebrowser.db config init
filebrowser -d /var/lib/filebrowser/filebrowser.db config set \
  --address 0.0.0.0 \
  --port 8080 \
  --root /srv/exports \
  --auth.method=noauth \
  --baseurl /files
```

### 5.3 Systemd service

```bash
cat > /etc/systemd/system/filebrowser.service << 'EOF'
[Unit]
Description=Filebrowser
After=network.target

[Service]
User=root
ExecStart=/usr/local/bin/filebrowser -d /var/lib/filebrowser/filebrowser.db
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now filebrowser
```

---

## 6. Adminer

> ⚠️ **Critical points**:
> - Install via `apt` only
> - Always select **PostgreSQL** in the dropdown (not MySQL!)
> - Clear browser cookies if session issues occur
> - Use a private/incognito tab on first login

### 6.1 Install

```bash
apt install -y apache2 php libapache2-mod-php adminer
a2enmod headers
a2enconf adminer
```

### 6.2 Configure Apache on port 8081

```bash
sed -i 's/Listen 80/Listen 8081/' /etc/apache2/ports.conf
sed -i 's/<VirtualHost \*:80>/<VirtualHost *:8081>/' /etc/apache2/sites-enabled/000-default.conf
```

### 6.3 Adminer config

```bash
cat > /etc/adminer/conf.php << 'EOF'
<?php
include '/usr/share/adminer/adminer.php';
?>
EOF
```

### 6.4 Cookie and header config

```bash
cat > /etc/apache2/conf-available/adminer.conf << 'EOF'
Alias /adminer /etc/adminer
<Directory /etc/adminer>
    Require all granted
    DirectoryIndex conf.php
    AllowOverride All
    php_value session.cookie_path "/"
    php_value session.cookie_secure 0
    php_value session.cookie_samesite "Lax"
</Directory>

<IfModule mod_headers.c>
    Header edit Set-Cookie "path=/adminer/" "path=/db/adminer/"
</IfModule>
EOF
systemctl restart apache2
```

### 6.5 PHP session permissions

```bash
chown www-data:www-data /var/lib/php/sessions/
chmod 733 /var/lib/php/sessions/
```

> **Adminer login**:
> - System: **PostgreSQL** (important — not MySQL!)
> - Server: `localhost`
> - Username: `db_app`
> - Password: your password
> - Database: `my_database`

---

## 7. SSL certificate

```bash
mkdir -p /etc/authelia

# Replace YOUR_IP with your actual VM IP
openssl req -x509 -newkey rsa:4096 \
  -keyout /etc/authelia/key.pem \
  -out /etc/authelia/cert.pem \
  -days 365 -nodes \
  -subj '/CN=YOUR_IP' \
  -addext 'subjectAltName=IP:YOUR_IP'

chown root:root /etc/authelia/key.pem /etc/authelia/cert.pem
chmod 644 /etc/authelia/key.pem /etc/authelia/cert.pem
```

> Certificate is tied to the IP. If the IP changes, run the `change-ip` script (§17.4).

---

## 8. Authelia

### 8.1 Install

```bash
apt install -y gnupg
curl -s https://apt.authelia.com/organization/signing.asc | gpg --dearmor -o /usr/share/keyrings/authelia.gpg
echo 'deb [arch=amd64 signed-by=/usr/share/keyrings/authelia.gpg] https://apt.authelia.com/stable/debian/debian bookworm main' > /etc/apt/sources.list.d/authelia.list
apt update && apt install -y authelia
```

### 8.2 Configuration

```bash
# Replace all placeholders with your values
cat > /etc/authelia/configuration.yml << 'EOF'
jwt_secret: YOUR_SECRET_JWT
default_redirection_url: https://YOUR_IP
default_2fa_method: totp

server:
  address: tcp://0.0.0.0:9091
  tls:
    certificate: /etc/authelia/cert.pem
    key: /etc/authelia/key.pem

authentication_backend:
  file:
    path: /etc/authelia/users.yml
    password:
      algorithm: argon2id

access_control:
  default_policy: two_factor

session:
  secret: YOUR_SECRET_SESSION
  expiration: 1h
  inactivity: 30m
  cookies:
    - domain: YOUR_IP
      authelia_url: https://YOUR_IP:9091
      default_redirection_url: https://YOUR_IP

regulation:
  max_retries: 3
  find_time: 2m
  ban_time: 12h

storage:
  encryption_key: YOUR_SECRET_STORAGE
  local:
    path: /var/lib/authelia/db.sqlite3

notifier:
  filesystem:
    filename: /var/log/authelia/notifications.txt
EOF
```

### 8.3 Create first user

```bash
# Generate password hash
authelia crypto hash generate argon2 --password 'YourPassword!'
# Copy the hash output (starts with $argon2id$...)
```

```bash
cat > /etc/authelia/users.yml << 'EOF'
users:
  admin:
    disabled: false
    displayname: Administrator
    password: PASTE_HASH_HERE
    email: admin@yourdomain.com
    groups: [admins, users]
EOF
```

> ⚠️ No quotes around the hash in users.yml  
> ⚠️ Username is case-sensitive — always lowercase

### 8.4 Permissions and start

```bash
useradd -r -s /bin/false authelia 2>/dev/null || true
mkdir -p /var/lib/authelia /var/log/authelia
chown -R authelia:authelia /var/lib/authelia /var/log/authelia
chown root:authelia /etc/authelia/users.yml
chmod 640 /etc/authelia/users.yml
systemctl enable --now authelia
```

---

## 9. Caddy

### 9.1 Install

```bash
apt install -y debian-keyring debian-archive-keyring
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
apt update && apt install -y caddy
```

### 9.2 Caddyfile

```bash
# Replace YOUR_IP with your actual VM IP
cat > /etc/caddy/Caddyfile << 'EOF'
{
    auto_https off
}

(tls-transport) {
    transport http {
        tls_insecure_skip_verify
    }
}

https://YOUR_IP {
    tls /etc/authelia/cert.pem /etc/authelia/key.pem

    handle /db/* {
        uri strip_prefix /db
        reverse_proxy localhost:8081 {
            header_up X-Forwarded-Proto "https"
            header_up X-Forwarded-Ssl "on"
        }
    }

    forward_auth https://localhost:9091 {
        uri /api/authz/forward-auth
        import tls-transport
        copy_headers Remote-User Remote-Groups Remote-Name Remote-Email
    }

    handle /sync {
        reverse_proxy localhost:9099
    }

    handle /files/* {
        reverse_proxy localhost:8080
    }

    handle / {
        root * /var/www/portal
        file_server
    }
}
EOF
systemctl enable --now caddy
```

---

## 10. Web portal

```bash
mkdir -p /var/www/portal
cat > /var/www/portal/index.html << 'HTMLEOF'
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Secure Portal</title>
<style>
  body{font-family:Arial,sans-serif;background:#1a1a2e;color:white;display:flex;
    flex-direction:column;align-items:center;justify-content:center;min-height:100vh;margin:0}
  .cards{display:flex;gap:24px;flex-wrap:wrap;justify-content:center;margin-top:40px}
  .card{background:#16213e;border-radius:12px;padding:36px 32px;text-align:center;
    text-decoration:none;color:white;border:2px solid #0f3460;transition:0.2s;width:220px}
  .card:hover{background:#0f3460;transform:translateY(-4px)}
  .icon{font-size:2.8em;margin-bottom:14px}
  .sync-btn{margin-top:40px;background:none;border:2px solid #0f3460;color:#aaa;
    padding:10px 28px;border-radius:8px;cursor:pointer;font-size:0.9em;transition:0.2s}
  .sync-btn:hover{background:#0f3460;color:white}
  #sync-msg{margin-top:12px;font-size:0.85em;color:#4CAF50;display:none}
</style>
</head>
<body>
  <h1>Secure Portal</h1>
  <p style="color:#aaa">2FA authentication required</p>
  <div class="cards">
    <a class="card" href="/files/">
      <div class="icon">📂</div>
      <h2>Files</h2>
      <p>Exports and shared files</p>
    </a>
    <a class="card" href="/db/adminer/">
      <div class="icon">🗄️</div>
      <h2>Database</h2>
      <p>PostgreSQL access</p>
    </a>
  </div>
  <button class="sync-btn" onclick="syncNow()">Force CSV sync</button>
  <p id="sync-msg">Sync triggered.</p>
  <script>
    function syncNow(){
      fetch('/sync',{method:'POST'}).then(()=>{
        document.getElementById('sync-msg').style.display='block';
        setTimeout(()=>document.getElementById('sync-msg').style.display='none',4000);
      });
    }
  </script>
</body>
</html>
HTMLEOF
```

---

## 11. UFW

```bash
ufw allow 22/tcp
ufw allow 443/tcp
ufw allow 9091/tcp
ufw allow 51820/udp
ufw --force enable
ufw status
```

---

## 12. Fail2ban

```bash
# Replace GATEWAY_IP with your hypervisor/router IP
cat > /etc/fail2ban/jail.local << 'EOF'
[DEFAULT]
ignoreip = 127.0.0.1/8 GATEWAY_IP

[sshd]
enabled = true
port = ssh
filter = sshd
logpath = /var/log/auth.log
maxretry = 3
findtime = 10m
bantime = 12h
EOF
systemctl enable --now fail2ban
```

> Whitelist your gateway IP to avoid locking yourself out during SSH sessions from the host machine.

---

## 13. SSH Discord alerts

### 13.1 Discord config file

```bash
cat > /etc/authelia/discord.env << 'EOF'
DISCORD_WEBHOOK=https://discord.com/api/webhooks/YOUR_WEBHOOK_HERE
EOF
chmod 600 /etc/authelia/discord.env
```

### 13.2 SSH alert script

```bash
cat > /usr/local/bin/ssh_alert.sh << 'EOF'
#!/bin/bash
cat > /tmp/ssh_alert.txt << ALERTEOF
PAM_TYPE=${PAM_TYPE}
PAM_USER=${PAM_USER}
PAM_RHOST=${PAM_RHOST}
DATE=$(date '+%Y-%m-%d %H:%M:%S')
ALERTEOF
EOF
chmod +x /usr/local/bin/ssh_alert.sh
```

### 13.3 PAM SSH configuration

```bash
echo 'session optional pam_exec.so /usr/local/bin/ssh_alert.sh' >> /etc/pam.d/sshd
```

---

## 14. Discord bot

### 14.1 Python setup

```bash
apt install -y python3-pip python3-venv
mkdir -p /opt/deus-bot
python3 -m venv /opt/deus-bot/venv
/opt/deus-bot/venv/bin/pip install discord.py python-dotenv
```

### 14.2 Configure

```bash
# Replace with your values (see Appendix B and C)
cat > /opt/deus-bot/.env << 'EOF'
DISCORD_BOT_TOKEN=YOUR_BOT_TOKEN
DISCORD_CHANNEL_ID=YOUR_CHANNEL_ID
DISCORD_GUILD_ID=YOUR_GUILD_ID
EOF
chmod 600 /opt/deus-bot/.env
```

### 14.3 Deploy bot

```bash
cp bot.py /opt/deus-bot/bot.py
```

### 14.4 Systemd service

```bash
cat > /etc/systemd/system/deus-bot.service << 'EOF'
[Unit]
Description=Deus Discord Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/deus-bot
ExecStart=/opt/deus-bot/venv/bin/python bot.py
Restart=always
RestartSec=10s

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now deus-bot
```

---

## 15. Sync API

```bash
cat > /usr/local/bin/sync-api.py << 'EOF'
#!/usr/bin/env python3
from http.server import HTTPServer, BaseHTTPRequestHandler
import subprocess

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/sync':
            subprocess.Popen(['/usr/local/bin/export_csv.sh'])
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'OK')
    def log_message(self, *args): pass

HTTPServer(('127.0.0.1', 9099), Handler).serve_forever()
EOF
chmod +x /usr/local/bin/sync-api.py

cat > /etc/systemd/system/sync-api.service << 'EOF'
[Unit]
Description=Sync API
After=network.target

[Service]
ExecStart=/usr/bin/python3 /usr/local/bin/sync-api.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now sync-api
```

---

## 16. WireGuard VPN

### 16.1 Generate server keys

```bash
cd /etc/wireguard
wg genkey | tee server_private.key | wg pubkey > server_public.key
chmod 600 server_private.key
```

### 16.2 Server configuration

```bash
# Check your network interface name: ip a | grep 'state UP'
# Replace ens33 if different (eth0, enp3s0, etc.)
cat > /etc/wireguard/wg0.conf << EOF
[Interface]
PrivateKey = $(cat /etc/wireguard/server_private.key)
Address = 10.0.0.1/24
ListenPort = 51820
PostUp = iptables -A FORWARD -i wg0 -j ACCEPT; iptables -t nat -A POSTROUTING -o ens33 -j MASQUERADE
PostDown = iptables -D FORWARD -i wg0 -j ACCEPT; iptables -t nat -D POSTROUTING -o ens33 -j MASQUERADE
EOF
chmod 600 /etc/wireguard/wg0.conf
```

### 16.3 Enable IP forwarding

```bash
echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
sysctl -p
```

### 16.4 Generate client profiles

```bash
# Edit the client list to match your team
CLIENTS="alice bob charlie"
SERVER_PUB=$(cat /etc/wireguard/server_public.key)
IP_INDEX=2

for client in $CLIENTS; do
    wg genkey | tee /etc/wireguard/client_${client}_private.key | wg pubkey > /etc/wireguard/client_${client}_public.key

    cat >> /etc/wireguard/wg0.conf << EOF

[Peer]
# $client
PublicKey = $(cat /etc/wireguard/client_${client}_public.key)
AllowedIPs = 10.0.0.${IP_INDEX}/32
EOF

    cat > /etc/wireguard/client_${client}.conf << EOF
[Interface]
PrivateKey = $(cat /etc/wireguard/client_${client}_private.key)
Address = 10.0.0.${IP_INDEX}/24
DNS = 8.8.8.8

[Peer]
PublicKey = ${SERVER_PUB}
Endpoint = YOUR_IP:51820
AllowedIPs = YOUR_IP/32
PersistentKeepalive = 25
EOF

    IP_INDEX=$((IP_INDEX + 1))
done

systemctl enable --now wg-quick@wg0
```

### 16.5 Display QR codes

```bash
# All clients
for client in alice bob charlie; do
    echo "=== QR CODE $client ==="
    qrencode -t ansiutf8 < /etc/wireguard/client_${client}.conf
done

# Single client
qrencode -t ansiutf8 < /etc/wireguard/client_alice.conf
```

> User installs the **WireGuard** app on their phone and scans their QR code.

---

## 17. Maintenance scripts

### 17.1 Root aliases

```bash
cat >> /root/.bashrc << 'EOF'
alias srv-bans='/usr/local/bin/srv-bans.sh'
alias srv-unban='bash /usr/local/bin/srv-unban.sh'
alias srv-change-ip='bash /usr/local/bin/change-ip.sh'
EOF
source /root/.bashrc
```

### 17.2 srv-bans script

```bash
cat > /usr/local/bin/srv-bans.sh << 'EOF'
#!/bin/bash
source /etc/authelia/discord.env
BANS=$(fail2ban-client status sshd 2>/dev/null | grep -A1 'Banned IP' | tail -1 | sed 's/.*Banned IP list://' | xargs)
DESC=${BANS:-'No banned IPs.'}
curl -s -X POST "$DISCORD_WEBHOOK" \
  -H 'Content-Type: application/json' \
  -d "{\"embeds\":[{\"title\":\"Banned SSH IPs\",\"description\":\"$DESC\",\"color\":15158332}]}"
EOF
chmod +x /usr/local/bin/srv-bans.sh
```

### 17.3 srv-unban script

```bash
cat > /usr/local/bin/srv-unban.sh << 'EOF'
#!/bin/bash
source /etc/authelia/discord.env
[ -z "$1" ] && echo 'Usage: srv-unban <IP>' && exit 1
fail2ban-client set sshd unbanip "$1"
curl -s -X POST "$DISCORD_WEBHOOK" \
  -H 'Content-Type: application/json' \
  -d "{\"embeds\":[{\"title\":\"IP unbanned\",\"description\":\"$1 removed from ban list.\",\"color\":3066993}]}" > /dev/null
echo "$1 unbanned."
EOF
chmod +x /usr/local/bin/srv-unban.sh
```

### 17.4 change-ip script

> Run this script every time you switch networks (home/school/office).

```bash
cat > /usr/local/bin/change-ip.sh << 'EOF'
#!/bin/bash
set -e
CURRENT_IP=$(hostname -I | awk '{print $1}')
echo "Detected IP: $CURRENT_IP"
read -p "Confirm? (y/n): " CONFIRM
[ "$CONFIRM" != "y" ] && read -p "Manual IP: " CURRENT_IP

echo "[1/4] Authelia..."
sed -i "s/domain: .*/domain: $CURRENT_IP/" /etc/authelia/configuration.yml
sed -i "s|authelia_url: .*|authelia_url: https://$CURRENT_IP:9091|" /etc/authelia/configuration.yml
sed -i "s|default_redirection_url: .*|default_redirection_url: https://$CURRENT_IP|" /etc/authelia/configuration.yml

echo "[2/4] SSL certificate..."
openssl req -x509 -newkey rsa:4096 -keyout /etc/authelia/key.pem -out /etc/authelia/cert.pem \
  -days 365 -nodes -subj "/CN=$CURRENT_IP" -addext "subjectAltName=IP:$CURRENT_IP" 2>/dev/null
chmod 644 /etc/authelia/key.pem /etc/authelia/cert.pem

echo "[3/4] Caddy..."
sed -i "s/https:\/\/[0-9.]*/https:\/\/$CURRENT_IP/g" /etc/caddy/Caddyfile

echo "[4/4] Restarting services..."
systemctl restart authelia && sleep 2 && systemctl restart caddy

echo "Done. Access: https://$CURRENT_IP"
EOF
chmod +x /usr/local/bin/change-ip.sh
```

### 17.5 Fix certificate permissions at boot

```bash
cat > /etc/systemd/system/fix-caddy-certs.service << 'EOF'
[Unit]
Description=Fix Caddy cert permissions
Before=caddy.service
After=network.target

[Service]
Type=oneshot
ExecStart=/bin/chmod 644 /etc/authelia/cert.pem /etc/authelia/key.pem
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now fix-caddy-certs
```

---

## 18. Final check

### 18.1 All services status

```bash
systemctl is-active postgresql filebrowser apache2 authelia caddy fail2ban deus-bot sync-api wg-quick@wg0
```

> All should return `active`.

### 18.2 Listening ports

```bash
ss -tlnp | grep -E '443|8080|8081|9091|9099|5432|22'
```

### 18.3 Portal test

```bash
curl -k -I https://YOUR_IP | head -3
```

> Should return `HTTP/2 302` (redirect to Authelia).

---

## 19. User management

### 19.1 Add an Authelia user

```bash
# 1. Generate password hash
authelia crypto hash generate argon2 --password 'UserPassword!'

# 2. Edit users.yml — no quotes around the hash
nano /etc/authelia/users.yml
```

Add at the end of the file:
```yaml
  username:
    disabled: false
    displayname: Full Name
    password: $argon2id$v=19$...HASH...
    email: user@yourdomain.com
    groups: [users]
```

```bash
# 3. Restart Authelia
systemctl restart authelia
```

### 19.2 First login procedure

1. Go to `https://YOUR_IP`
2. Enter username (**lowercase**) and password
3. Authelia generates a verification code → bot sends it to Discord automatically
4. If bot misses it → run `/code` on Discord
5. Enter the code → click "Register device" → scan QR with **2FAS**
6. Next logins: username + password + 2FAS code (6 digits, refreshes every 30s)

### 19.3 Add a WireGuard profile

```bash
# Replace USERNAME and X with real values
wg genkey | tee /etc/wireguard/client_USERNAME_private.key | wg pubkey > /etc/wireguard/client_USERNAME_public.key

cat >> /etc/wireguard/wg0.conf << EOF

[Peer]
# USERNAME
PublicKey = $(cat /etc/wireguard/client_USERNAME_public.key)
AllowedIPs = 10.0.0.X/32
EOF

cat > /etc/wireguard/client_USERNAME.conf << EOF
[Interface]
PrivateKey = $(cat /etc/wireguard/client_USERNAME_private.key)
Address = 10.0.0.X/24
DNS = 8.8.8.8

[Peer]
PublicKey = $(cat /etc/wireguard/server_public.key)
Endpoint = YOUR_IP:51820
AllowedIPs = YOUR_IP/32
PersistentKeepalive = 25
EOF

systemctl restart wg-quick@wg0
qrencode -t ansiutf8 < /etc/wireguard/client_USERNAME.conf
```

### 19.4 Disable a user

```bash
nano /etc/authelia/users.yml
# disabled: false → disabled: true
systemctl restart authelia
```

---

## Appendix E — Useful commands

```bash
# Check current IP
ip a | grep inet

# Switch network
srv-change-ip

# Services status
systemctl is-active postgresql filebrowser apache2 authelia caddy fail2ban deus-bot sync-api

# Banned IPs
srv-bans

# Unban an IP
srv-unban X.X.X.X

# Re-display a WireGuard QR code
qrencode -t ansiutf8 < /etc/wireguard/client_USERNAME.conf

# Get last Authelia code manually
grep -oE '[A-Z0-9]{8}' /var/log/authelia/notifications.txt | tail -1

# Live SSH logs
tail -f /var/log/auth.log | grep -E 'Accepted|Failed'

# Direct PostgreSQL connection
psql -h localhost -U db_app -d my_database -W
```

---

*deus-sec — github.com/deus-sec/debian-server*

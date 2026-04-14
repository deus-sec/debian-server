# debian-server

Secure server stack on Debian 13 with automated Discord monitoring.  
Built for small teams requiring authenticated access to sensitive data with real-time alerting.

---

## Stack

| Component | Role |
|---|---|
| PostgreSQL 17 | Database with role-based access |
| Adminer | Web database interface |
| Filebrowser | File sharing interface |
| Authelia | 2FA authentication gateway (TOTP) |
| Caddy | Reverse proxy with TLS |
| WireGuard | VPN for remote access |
| Fail2ban | SSH brute-force protection |
| Discord Bot | Real-time alerts and remote commands |

---

## Features

- Single HTTPS entry point — all services behind Authelia 2FA
- SSH connection alerts on Discord with one-click block button
- Authelia verification codes forwarded automatically to Discord
- Slash commands : `/status` `/bans` `/unban` `/logs` `/exports` `/code`
- Automatic CSV exports on schedule with manual sync trigger
- WireGuard VPN profiles with QR code generation
- IP change script for multi-network environments (home/school/office)

---

## Requirements

- Debian 13 (bare metal or VM)
- Discord server with a bot token and webhook
- 2FAS app on mobile for TOTP

---

## Installation

See [docs/installation.md](docs/installation.md) for the full step-by-step guide.  
Covers everything from a blank Debian install to a fully operational stack.

---

## Quick start

```bash
# After cloning
cp bot/.env.example bot/.env
# Fill in your Discord credentials in .env

# Copy bot to server
scp -r bot/ user@your-server:/opt/deus-bot/

# Follow installation guide for the full stack
```

---

## Discord Bot

The bot monitors two files in real time :

- `/tmp/ssh_alert.txt` — written by PAM on every SSH session
- `/var/log/authelia/notifications.txt` — written by Authelia on 2FA code generation

Any update triggers an embed in your Discord channel.  
The `/code` command retrieves the last Authelia verification code on demand.

---

## Security notes

- All services listen on localhost only — Caddy is the single public-facing component
- Authelia enforces TOTP on every session — no bypass
- Fail2ban bans after 3 failed SSH attempts — 12h ban
- WireGuard tunnel gives access to the server only — not to the host network
- Certificate is self-signed — accept the browser warning on first access

---

## File structure

```
deus-sec/
├── README.md
├── bot/
│   ├── bot.py
│   └── .env.example
├── docs/
│   └── installation.md
└── scripts/
    ├── export_csv.sh
    ├── ssh_alert.sh
    └── change_ip.sh
```

---

## License

MIT

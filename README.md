# MeshCompute – Secure Lightweight Bot Network

MeshCompute is a Go-based WebSocket relay server that connects a **Controller** (Python CLI) to multiple **Bots** (Python, compilable to EXE or APK).

Commands, interactive shells, file uploads, and system information – secured by bot authentication, token hashing, and optional TLS.

---

# Table of Contents

- [Features](#features)
- [Architecture Overview](#architecture-overview)
- [Quick Start](#quick-start)
- [Detailed Setup Guides](#detailed-setup-guides)
  - [1. Server Setup (Docker)](#1-server-setup-docker)
  - [2. Controller Setup](#2-controller-setup)
  - [3. Bot Setup (Python or Build as EXE/APK)](#3-bot-setup-python-or-build-as-exeapk)
- [Controller Commands](#controller-commands)
- [Security](#security)
- [Repository Structure](#repository-structure)
- [FAQ](#faq)

---

# MeshCompute – Secure Lightweight Bot Network

MeshCompute is a Go-based WebSocket relay server that connects a **Controller** (Python CLI) to multiple **Bots** (Python, compilable to EXE or APK).  
Commands, interactive shells, file uploads, and system information – secured by bot authentication, token hashing, and TLS encryption.

---

# Features

- **Controller** ↔ **Server** ↔ **Bots** over WebSocket (WSS)
- Interactive shell, remote command execution, system info, process list, ping, Python code execution
- File upload to single bots or all at once
- Bot authentication via pre-shared secrets
- Controller token hashed (SHA-256) on the server
- Redis backend for bot presence and heartbeats (password-protected)
- Automatic TLS encryption (self-signed or Let's Encrypt ready)
- Ready-to-build EXE (Windows) and APK (Android) with external JSON config
- Fully Dockerized server with one-command deployment
- **Zero manual configuration** – three setup scripts do everything

---

# Quick Start (local test without Docker)

```bash
git clone https://github.com/Kiwilus/meshcompute.git
cd meshcompute

# 1. Run server & Redis with Docker
cd docker && docker compose up -d

# 2. Start a bot (replace with your server's secret)
export BOT_SECRET="<secret_for_bot01>"
python3 client/main.py

# 3. Start the controller
export AUTH_TOKEN="<your_token>"
export SERVER_URL="ws://localhost:8080/ws"
python3 controller/main.py
```

For production with TLS, use the automated setup scripts below.

---

# Automated Setup Scripts

Three scripts in the `scripts/` folder handle everything. Run them in this order:

---

## 1. Server Setup (`scripts/setup_server.sh`)

Creates a deployment package (`~/meshcompute-deploy`) that you copy to any Linux server with Docker.

```bash
cd scripts
chmod +x setup_server.sh
./setup_server.sh
```

### What it does:
- Asks for server IP/domain + HTTPS port (default 443)
- Generates:
  - `AUTH_TOKEN`
  - Redis password
  - 3 bot secrets
- Creates self-signed TLS certificate
- Builds `~/meshcompute-deploy`

### Deploy to server:

```bash
scp -r ~/meshcompute-deploy user@your-server:~/
```

### Start server:

```bash
cd ~/meshcompute-deploy/docker
docker compose up -d
```

Server runs at:

```
wss://your-domain:443/ws
```

---

## 2. Controller Setup (`scripts/setup_controller.sh`)

Connects to an existing server.

```bash
cd scripts
chmod +x setup_controller.sh
./setup_controller.sh
```

### What it does:
- Requests `AUTH_TOKEN`
- Requests server URL
- Creates `.env`
- Configures controller for self-signed TLS

### Start controller:

```bash
cd ..
python3 controller/main.py
```

---

## 3. Bot Setup (`scripts/setup_bot.sh`)

Builds a standalone bot (EXE or APK).

```bash
cd scripts
chmod +x setup_bot.sh
./setup_bot.sh
```

### Options:
- `exe` (Windows)
- `apk` (Android)

### Output:
- `meshcompute-bot/dist/meshbot.exe`
- or APK in `meshcompute-bot/`

---

## Run a bot

### Option A – environment variables

```bash
export BOT_ID="my-bot"
export BOT_SECRET="secret"
export SERVER_URL="wss://server:443/ws"
python3 client/main.py
```

### Option B – JSON config

```json
{
  "bot_id": "my-bot",
  "bot_secret": "secret",
  "server_url": "wss://server:443/ws"
}
```

Place next to executable.

---

# Controller Commands

| Command | Description |
|---|---|
| `list` | Show connected bots |
| `shell <id>` | Interactive remote shell |
| `exec <id> <cmd>` | Run shell command |
| `sysinfo <id>` | System information |
| `ps <id>` | Top 30 processes |
| `ping <id>` | Pong test |
| `python <id> <code>` | Execute Python code |
| `upload <id> <file>` | Send file |

Use `all` instead of an ID for mass commands (except `shell` and `python`).

---

# Security

- **TLS:** WebSocket over `wss://`
- **Controller auth:** SHA-256 hashed token
- **Bot auth:** Pre-shared secrets required
- **Redis password:** Randomly generated
- **File safety:** Filename sanitization
- **Certificates:** Self-signed by default, Let's Encrypt supported

---

# Repository Structure

```text
meshcompute/
├── builder/
├── client/
├── controller/
├── common/
├── docker/
├── scripts/
├── server/
├── requirements.txt
└── README.md
```

---

# Troubleshooting

| Problem | Fix |
|---|---|
| docker compose missing variables | `.env` not in docker folder |
| SSL WRONG_VERSION_NUMBER | TLS mismatch (ws vs wss) |
| CERTIFICATE_VERIFY_FAILED | Self-signed cert not trusted |
| Bot disconnects immediately | Wrong BOT_SECRET |
| go version error | downgrade go.mod to 1.21 |

---

# Contributing

Pull requests are welcome. Open an issue first for discussion.
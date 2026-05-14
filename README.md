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

# Features

- **Controller** ↔ **Server** ↔ **Many Bots** over WebSocket
- Interactive shell
- Remote command execution
- System information & process listing
- Ping / pong connectivity checks
- Python code execution on bots
- File upload to individual bots or all bots
- Bot authentication via shared secrets
- Controller token hashing (SHA-256)
- Redis backend for presence + heartbeats
- Password-protected Redis
- Optional TLS encryption (`wss://`)
- Self-signed certificates included
- Let's Encrypt compatible
- EXE build support (Windows)
- APK build support (Android)
- Fully Dockerized deployment
- Automated setup scripts
- Zero manual configuration

---

# Architecture Overview

```text
        Controller
     (Python CLI)
            │
            │  wss://
            ▼
     ┌───────────────┐
     │   Go Server   │
     │ + Redis Cache │
     └───────────────┘
            │
            │  wss://
            ▼
        Bot(s)
 (Python / EXE / APK)
```

Authentication flow:

```text
Controller ---> AUTH_TOKEN ---> Server
Bot ---------> BOT_SECRET ----> Server
```

---

# Quick Start

If you want to test MeshCompute locally without TLS:

## 1. Clone the repository

```bash
git clone https://github.com/Kiwilus/meshcompute.git
cd meshcompute
```

## 2. Generate secrets

```bash
python3 builder/generate_secrets.py
```

This creates:

- `.env`
- Bot configuration files
- Random authentication secrets

---

## 3. Start server + Redis

```bash
cd docker
docker compose up -d
```

---

## 4. Start a bot

Use one of the generated bot secrets:

```bash
export BOT_SECRET="<secret_for_bot01>"
python3 client/main.py
```

---

## 5. Start the controller

```bash
python3 controller/main.py
```

At the prompt:

```text
meshctrl >
```

Type:

```text
list
```

to see connected bots.

---

# Detailed Setup Guides

The `scripts/` folder contains fully automated setup scripts.

These scripts:

- generate secure secrets
- configure TLS
- prepare deployment packages
- require minimal user input

---

# 1. Server Setup (Docker)

Run this locally first.

The script prepares a deployment folder for any Linux server with Docker installed.

## Run the setup script

```bash
cd scripts
chmod +x setup_server.sh
./setup_server.sh
```

---

## You will be asked for

- Public IP or domain
- HTTPS port (default: `443`)

---

## The script automatically

- Generates:
  - `AUTH_TOKEN`
  - Redis password
  - Bot secrets
- Creates:
  - Self-signed TLS certificate
  - Docker deployment package
- Builds:
  - `meshcompute-deploy/`

---

## Copy deployment to server

```bash
scp -r ../meshcompute-deploy user@your-server:~/
```

---

## Start on the server

```bash
cd ~/meshcompute-deploy/docker
docker compose up -d
```

Server endpoint:

```text
wss://your-domain:443/ws
```

---

## Important

Keep the generated secrets safe.

You will need them for:

- Controller authentication
- Bot authentication

---

# 2. Controller Setup

Run this on the machine you will use to control bots.

## Start setup

```bash
cd scripts
chmod +x setup_controller.sh
./setup_controller.sh
```

---

## Required information

- Server URL

Example:

```text
wss://my-server.com:443/ws
```

- `AUTH_TOKEN`

(from the server setup output)

---

## The script will

- Clone the repository
- Install dependencies
- Generate `.env`
- Configure the controller automatically

---

## Start controller

```bash
cd ../meshcompute-controller
python3 controller/main.py
```

Prompt:

```text
meshctrl >
```

---

# 3. Bot Setup (Python or Build as EXE/APK)

Each bot requires:

- `bot_id`
- `bot_secret`

The server setup script generates:

- `bot01`
- `bot02`
- `bot03`

with unique secrets.

---

# Option A — Run as Python Script

Ideal for testing.

```bash
cd meshcompute

export BOT_SECRET="<secret_for_bot01>"

python3 client/main.py
```

The bot connects automatically.

---

# Option B — Build EXE or APK

Build a standalone executable with the secret baked in.

No Python installation required on the target device.

## Start build script

```bash
cd scripts
chmod +x setup_bot.sh
./setup_bot.sh
```

---

## The script asks for

- Bot ID
- Bot secret
- Server URL
- Target platform:
  - `exe`
  - `apk`

---

## Output files

Windows:

```text
meshcompute-bot/dist/meshbot_bot01.exe
```

Android:

```text
meshcompute-bot/meshbot_bot01.apk
```

Copy the generated file to the target machine and run it.

The bot connects automatically.

---

# Controller Commands

| Command | Description |
|---|---|
| `list` | Show connected bots |
| `shell <bot_id>` | Open interactive shell |
| `exec <bot_id> <cmd>` | Execute shell command |
| `sysinfo <bot_id>` | Display system information |
| `ps <bot_id>` | List top processes |
| `ping <bot_id>` | Ping a bot |
| `python <bot_id> <code>` | Execute Python code |
| `upload <bot_id> <file> [remote_name]` | Upload file |
| `help` | Show help |
| `exit` / `quit` | Disconnect controller |

---

## Broadcast Support

You may use:

```text
all
```

instead of a bot ID for:

- `exec`
- `sysinfo`
- `ps`
- `ping`
- `upload`

Not supported for:

- `shell`
- `python`

---

# Security

MeshCompute includes multiple security layers.

---

## TLS Encryption

- Uses `wss://`
- Self-signed certificate by default
- Replaceable with Let's Encrypt certificates

---

## Controller Authentication

- `AUTH_TOKEN`
- SHA-256 hashed on the server
- Plain token never stored

---

## Bot Authentication

- Each bot requires a unique pre-shared secret
- Unauthorized bots cannot connect

---

## Redis Security

- Password protected
- Random secure password generation

---

## File Upload Protection

- Filenames sanitized
- Prevents path traversal attacks

---

## Secret Management

- High entropy generated secrets
- No hardcoded credentials

---

# Production Recommendations

For production deployments:

- Use trusted TLS certificates
- Enable Redis persistence
- Configure backups
- Run bots in containers or VMs
- Restrict server access via firewall/VPN

---

# Repository Structure

```text
meshcompute/
├── builder/
│   ├── generate_secrets.py
│   ├── build_exe.py
│   ├── build_apk.sh
│   └── bot_configs/
│
├── client/
│   └── main.py
│
├── controller/
│   └── main.py
│
├── common/
│   └── config.py
│
├── docker/
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── .env.example.server
│
├── scripts/
│   ├── setup_server.sh
│   ├── setup_controller.sh
│   └── setup_bot.sh
│
├── server/
│   ├── main.go
│   ├── go.mod
│   └── go.sum
│
├── requirements.txt
├── .gitignore
└── README.md
```

---

# FAQ

## Does MeshCompute require Docker?

Only the server requires Docker.

Bots and controllers can run directly with Python or as standalone binaries.

---

## Can I use Let's Encrypt?

Yes.

Replace the generated self-signed certificate with your Let's Encrypt certificate files.

---

## Can multiple controllers connect?

Currently designed for a single controller connection.

---

## Is Android supported?

Yes.

Bots can be compiled as APKs.

---

## Is Windows supported?

Yes.

Bots can be built as standalone `.exe` files.

---

# Disclaimer

MeshCompute is intended for:

- educational purposes
- private infrastructure management
- lab environments
- authorized remote administration

Only use it on systems you own or are explicitly authorized to manage.
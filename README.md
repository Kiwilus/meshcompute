# meshcompute
A simple distributed computing system where multiple clients connect to a central server to execute tasks and share computational power.

##  Features

- Real-time WebSocket communication
- Central Relay Server
- Controller with clean colored terminal interface
- Persistent Bot IDs
- Heartbeat system + automatic offline detection
- Shell command execution
- Python code execution on bots
- Easy to extend
- Cross-platform (Windows/Linux)

---

## Project structure
```
meshcompute/
├── controller/
│   ├── main.py          # Your control interface
│   └── config.py
├── server/
│   ├── main.py          # Relay server
│   └── bots.py
├── client/
│   ├── main.py          # The bot
│   ├── config.py
│   └── bot_id.txt       # Persistent ID
├── common/
│   └── messages.py
├── README.md
└── requirements.txt
```
---
## Architecture

```mermaid
A[Local Controller] <--> B[VPS Relay Server] <--> C[Client/bot]
```
Controller → Runs on your local machine (you interact here)

Relay Server → Runs 24/7 on a VPS, forwards commands and results

Client → Runs on target machines/servers and connects to the relay server

---

## Installation

### 1. Clone repository
```bash
git clone https://github.com/Kiwilus/meshcompute.git
```
```bash
cd meshcompute
```

### 2. Install dependencies

#### with uv:
```bash
uv sync
```

#### or

#### using pip
```bash
pip install -r requirements.txt
```

---

## how to run

### 1. server

clone the repo on your server and install dependencies and just run it

### 2. controller
Edit ```controller/main.py``` and set your servers IP:

```bash
VPS_URL = "ws://YOUR_VPS_IP:8765"
```

then start:
```bash
cd controller
```
```bash
python main.py
```

### 3. clients
```bash
cd client
```
```bash
python main.py
```

## Roadmap

### Current
Basic WebSocket communication

Controller + Relay Server

Shell & Python execution

Heartbeat system

### Next
Script to compile .apk and .exe files for clients

File upload / download

Docker support

Logging system

Commands table

Install script


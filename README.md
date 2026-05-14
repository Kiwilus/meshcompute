# meshcompute
A simple distributed computing system where multiple clients connect to a central server to execute tasks and share computational power.

---

## Features

- Real-time communication via WebSockets
- Central **Relay Server** (best run on a VPS)
- Beautiful, colorful **Controller Terminal** (local)
- Persistent Bot IDs
- Heartbeat system with automatic offline detection
- Remote shell command execution
- Execute Python code directly on bots
- Cross-platform (Windows & Linux)
- redis database for tasks

---

## Architecture
Your PC (Controller)  <───WebSocket───>  VPS (Relay Server)  <───WebSocket───>  Bots/Clients

- **Controller**: Your local control center
- **Relay Server**: Message broker running 24/7
- **Clients/Bots**: The worker machines

---

## Install dependencies

### if you use uv
```bash
uv synv
```

### or with pip
```bash
pip install -r requirements.txt
```

## Configuration

on your server:
```bash
cp .env.example.server .env
```
and edit the **SERVER_HOST** and the **AUTH_TOKEN**

on your clients and controller
```bash
cp .env.example .env
```
and edit the **SERVER_HOST**, **AUTH_TOKEN(the same as on server)**, **SERVER_URL**(just the IP addres not the port) and **REDIS_URL**(just the IP adress not the port) 

## Quick start

### server
you need to deploay a redis database on your server and run
```bash
python3 run_server.py
```

### on your clients
```bash
python3 run_client.py
```

### on your controller
```bash
python3 run_controller.py
```

## controller command

| Command                             | Describtion                                       |
|-------------------------------------|---------------------------------------------------|
| list                                | Shows all connected bots with their status        |
| exec <bot_id or all> <command>      | Runs a shell command on one or all bots           |
| sysinfo <bot_id or all>             | Retrieves system information (CPU, RAM, OS)       |
| python <bot_id or all> <code>       | Executes Python code on the bots                  |
| ps <bot_id or all>                  | Displays the process list of the bots             |
| ping <bot_id or all>                | Tests reachability                                |
| clear / cls                         | Clears the screen                                 |
| exit                                | Exits the controller                              |
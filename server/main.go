// server/main.go
package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
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
	authTokenHash       string
	registrationTokenHash string
	redisAddr           string
	redisPassword       string
	serverPort          = ":8080"
	botSecrets          map[string]string // bot_id -> secret
	botAuthOn           bool
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
	// --- Controller-Token ---
	token := getEnv("AUTH_TOKEN", "change_me_please_secure_token_123")
	authTokenHash = hashString(token)

	// --- Registration-Token ---
	regToken := getEnv("REGISTRATION_TOKEN", "")
	if regToken != "" {
		registrationTokenHash = hashString(regToken)
		log.Println("Bot-Registrierung AKTIVIERT")
	} else {
		log.Println("Bot-Registrierung DEAKTIVIERT (REGISTRATION_TOKEN nicht gesetzt)")
	}

	// --- Redis ---
	redisAddr = getEnv("REDIS_URL", "localhost:6379")
	redisPassword = getEnv("REDIS_PASSWORD", "")

	// --- Bot-Authentifizierung (statische Secrets) ---
	secretsJSON := os.Getenv("BOT_SECRETS")
	if secretsJSON != "" {
		if err := json.Unmarshal([]byte(secretsJSON), &botSecrets); err != nil {
			log.Fatalf("Fehler beim Parsen von BOT_SECRETS: %v", err)
		}
		botAuthOn = true
		log.Println("Statische Bot-Authentifizierung AKTIVIERT")
	} else {
		log.Println("Warnung: Keine BOT_SECRETS gesetzt – Bots werden ohne Authentifizierung akzeptiert")
	}

	serverPort = ":" + getEnv("SERVER_PORT", "8080")

	hub = &Hub{
		clients:    make(map[string]*Client),
		register:   make(chan *Client),
		unregister: make(chan *Client),
		redis: redis.NewClient(&redis.Options{
			Addr:     redisAddr,
			Password: redisPassword,
			MaxRetries: 5,
		}),
	}

	if _, err := hub.redis.Ping(context.Background()).Result(); err != nil {
		log.Printf("Warnung: Redis nicht erreichbar: %v", err)
	}

	go hub.run()
	go hub.cleanupInactiveBots()

	http.HandleFunc("/ws", handleWebSocket)

	if os.Getenv("TLS_CERT") != "" && os.Getenv("TLS_KEY") != "" {
		log.Printf("MeshCompute Server läuft auf wss://0.0.0.0%s", serverPort)
		log.Fatal(http.ListenAndServeTLS(serverPort, os.Getenv("TLS_CERT"), os.Getenv("TLS_KEY"), nil))
	} else {
		log.Printf("MeshCompute Server läuft auf ws://0.0.0.0%s", serverPort)
		log.Fatal(http.ListenAndServe(serverPort, nil))
	}
}

func getEnv(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}

func hashString(s string) string {
	h := sha256.Sum256([]byte(s))
	return hex.EncodeToString(h[:])
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
			if client.typ == "client" {
				ctx := context.Background()
				h.redis.SRem(ctx, "active_bots", client.id)
				h.redis.Del(ctx, "bot:"+client.id)
				shellSessions.Range(func(key, value interface{}) bool {
					if value.(string) == client.id {
						shellSessions.Delete(key)
					}
					return true
				})
			}
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
		Type              string `json:"type"`
		AuthToken         string `json:"auth_token,omitempty"`
		RegistrationToken string `json:"registration_token,omitempty"`
		BotID             string `json:"bot_id,omitempty"`
		BotSecret         string `json:"bot_secret,omitempty"`
	}
	if err := wsjson.Read(c.ctx, c.conn, &initMsg); err != nil {
		return
	}

	switch initMsg.Type {
	case "controller":
		if hashString(initMsg.AuthToken) != authTokenHash {
			log.Println("❌ Falscher Auth Token")
			return
		}
		c.typ = "controller"
		c.id = "ctrl_" + fmt.Sprint(time.Now().UnixNano())

	case "register_bot":
		// Bot-Registrierung nur mit gültigem Registration-Token
		if registrationTokenHash == "" || hashString(initMsg.RegistrationToken) != registrationTokenHash {
			log.Println("❌ Bot-Registrierung fehlgeschlagen: ungültiges Registration Token")
			return
		}
		newID := initMsg.BotID
		if newID == "" {
			newID = "bot-" + fmt.Sprint(time.Now().UnixNano())
		}
		newSecret := initMsg.BotSecret
		if newSecret == "" {
			newSecret = fmt.Sprintf("%x", sha256.Sum256([]byte(newID+fmt.Sprint(time.Now().UnixNano()))))
		}
		// Speichere das Secret in Redis (und ggf. in lokaler Map)
		hub.redis.HSet(context.Background(), "registered_bots", newID, newSecret)
		// Teile dem Bot seine neuen Credentials mit
		wsjson.Write(c.ctx, c.conn, map[string]interface{}{
			"type":       "registration_ok",
			"bot_id":     newID,
			"bot_secret": newSecret,
		})
		log.Printf("✅ Neuer Bot registriert: %s", newID)
		c.conn.Close(websocket.StatusNormalClosure, "registration done")
		return

	case "client":
		if initMsg.BotID == "" {
			return
		}
		// Prüfe zuerst statische Secrets, dann dynamisch registrierte
		authenticated := false
		if botAuthOn {
			expectedSecret, exists := botSecrets[initMsg.BotID]
			if exists && initMsg.BotSecret == expectedSecret {
				authenticated = true
			}
		} else {
			authenticated = true
		}
		if !authenticated {
			// Prüfe in Redis registrierte Bots
			regSecret, err := hub.redis.HGet(context.Background(), "registered_bots", initMsg.BotID).Result()
			if err == nil && regSecret == initMsg.BotSecret {
				authenticated = true
			}
		}
		if !authenticated {
			log.Printf("❌ Bot-Authentifizierung fehlgeschlagen für %s", initMsg.BotID)
			return
		}
		c.typ = "client"
		c.id = initMsg.BotID
		hub.redis.SAdd(context.Background(), "active_bots", c.id)
		hub.redis.HSet(context.Background(), "bot:"+c.id, "heartbeat", time.Now().Unix())
		go heartbeatSender(c)

	default:
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
	case "shell_input":
		h.forwardToClient(sender, msg)
	default:
		h.forwardToController(sender, msg)
	}
}

func (h *Hub) handleControllerCommand(sender *Client, msg map[string]interface{}) {
	action := fmt.Sprintf("%v", msg["action"])
	taskID := fmt.Sprintf("%v", msg["task_id"])

	if action == "list" {
		h.sendBotList(sender, taskID)
		return
	}
	if action == "shell" {
		h.startShellSession(sender, msg)
		return
	}
	if action == "upload" {
		h.handleUpload(sender, msg, taskID)
		return
	}
	h.broadcastCommand(msg)
}

func (h *Hub) sendBotList(controller *Client, taskID string) {
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
	wsjson.Write(controller.ctx, controller.conn, map[string]interface{}{
		"type":    "result",
		"task_id": taskID,
		"data":    map[string]interface{}{"bots": bots},
	})
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

func (h *Hub) handleUpload(controller *Client, msg map[string]interface{}, taskID string) {
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
		"task_id": taskID,
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

func (h *Hub) forwardToClient(sender *Client, msg map[string]interface{}) {
	taskID, _ := msg["task_id"].(string)
	if taskID == "" {
		return
	}
	botID, ok := shellSessions.Load(taskID)
	if !ok {
		return
	}
	h.mu.RLock()
	defer h.mu.RUnlock()
	for id, client := range h.clients {
		if id == botID && client.typ == "client" {
			wsjson.Write(client.ctx, client.conn, msg)
			return
		}
	}
}

func (h *Hub) cleanupInactiveBots() {
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()
	for range ticker.C {
		h.mu.Lock()
		for id, client := range h.clients {
			if client.typ == "client" {
				val, err := h.redis.HGet(context.Background(), "bot:"+id, "heartbeat").Result()
				if err != nil {
					continue
				}
				var lastHeartbeat int64
				fmt.Sscanf(val, "%d", &lastHeartbeat)
				if time.Now().Unix()-lastHeartbeat > 90 {
					log.Printf("Bot %s timeout, removing", id)
					h.redis.SRem(context.Background(), "active_bots", id)
					h.redis.Del(context.Background(), "bot:"+id)
					delete(h.clients, id)
					client.conn.Close(websocket.StatusNormalClosure, "heartbeat timeout")
					shellSessions.Range(func(key, value interface{}) bool {
						if value.(string) == id {
							shellSessions.Delete(key)
						}
						return true
					})
				}
			}
		}
		h.mu.Unlock()
	}
}
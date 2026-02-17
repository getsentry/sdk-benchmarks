package main

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"html/template"
	"log"
	"math/rand"
	"net/http"
	"os"
	"sort"
	"strconv"

	_ "github.com/lib/pq"
)

// sentryMiddleware is nil in baseline builds, set via init() in main_sentry.go.
var sentryMiddleware func(http.Handler) http.Handler

var db *sql.DB

var fortuneTemplate = template.Must(template.New("fortunes").Parse(`<!DOCTYPE html>
<html>
<head><title>Fortunes</title></head>
<body>
<table>
<tr><th>id</th><th>message</th></tr>
{{range .}}<tr><td>{{.ID}}</td><td>{{.Message}}</td></tr>
{{end}}
</table>
</body>
</html>`))

type World struct {
	ID           int `json:"id"`
	RandomNumber int `json:"randomNumber"`
}

type Fortune struct {
	ID      int
	Message string
}

func getEnv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func main() {
	dsn := fmt.Sprintf(
		"host=%s port=%s user=%s password=%s dbname=%s sslmode=disable",
		getEnv("DB_HOST", "postgres"),
		getEnv("DB_PORT", "5432"),
		getEnv("DB_USER", "benchmarkdbuser"),
		getEnv("DB_PASS", "benchmarkdbpass"),
		getEnv("DB_NAME", "hello_world"),
	)

	var err error
	db, err = sql.Open("postgres", dsn)
	if err != nil {
		log.Fatalf("failed to open db: %v", err)
	}
	db.SetMaxOpenConns(64)
	db.SetMaxIdleConns(64)

	mux := http.NewServeMux()
	mux.HandleFunc("/health", healthHandler)
	mux.HandleFunc("/json", jsonHandler)
	mux.HandleFunc("/db", dbHandler)
	mux.HandleFunc("/queries", queriesHandler)
	mux.HandleFunc("/fortunes", fortunesHandler)

	var handler http.Handler = mux
	if sentryMiddleware != nil {
		handler = sentryMiddleware(mux)
	}

	log.Println("listening on :8080")
	log.Fatal(http.ListenAndServe(":8080", handler))
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	w.WriteHeader(http.StatusOK)
	fmt.Fprint(w, "OK")
}

func jsonHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"message": "Hello, World!"})
}

func dbHandler(w http.ResponseWriter, r *http.Request) {
	id := rand.Intn(10000) + 1
	var world World
	err := db.QueryRow("SELECT id, randomnumber FROM world WHERE id = $1", id).Scan(&world.ID, &world.RandomNumber)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(world)
}

const maxQueries = 500

func queriesHandler(w http.ResponseWriter, r *http.Request) {
	n, err := strconv.Atoi(r.URL.Query().Get("queries"))
	if err != nil || n < 1 {
		n = 1
	}
	if n > maxQueries {
		n = maxQueries
	}

	worlds := make([]World, n)
	for i := 0; i < n; i++ {
		id := rand.Intn(10000) + 1
		err := db.QueryRow("SELECT id, randomnumber FROM world WHERE id = $1", id).Scan(&worlds[i].ID, &worlds[i].RandomNumber)
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(worlds)
}

func fortunesHandler(w http.ResponseWriter, r *http.Request) {
	rows, err := db.Query("SELECT id, message FROM fortune")
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	defer rows.Close()

	fortunes := []Fortune{{ID: 0, Message: "Additional fortune added at request time."}}
	for rows.Next() {
		var f Fortune
		if err := rows.Scan(&f.ID, &f.Message); err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		fortunes = append(fortunes, f)
	}

	sort.Slice(fortunes, func(i, j int) bool {
		return fortunes[i].Message < fortunes[j].Message
	})

	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	fortuneTemplate.Execute(w, fortunes)
}

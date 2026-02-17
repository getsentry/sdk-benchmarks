package main

import (
	"database/sql"
	"fmt"
	"html/template"
	"log"
	"math/rand"
	"net/http"
	"os"
	"sort"
	"strconv"

	"github.com/gin-gonic/gin"
	_ "github.com/lib/pq"
)

// sentryMiddleware is nil in baseline builds, set via init() in main_sentry.go.
var sentryMiddleware gin.HandlerFunc

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

	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	r.SetHTMLTemplate(fortuneTemplate)

	if sentryMiddleware != nil {
		r.Use(sentryMiddleware)
	}

	r.GET("/health", healthHandler)
	r.GET("/json", jsonHandler)
	r.GET("/db", dbHandler)
	r.GET("/queries", queriesHandler)
	r.GET("/fortunes", fortunesHandler)

	log.Println("listening on :8080")
	log.Fatal(r.Run(":8080"))
}

func healthHandler(c *gin.Context) {
	c.String(http.StatusOK, "OK")
}

func jsonHandler(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"message": "Hello, World!"})
}

func dbHandler(c *gin.Context) {
	id := rand.Intn(10000) + 1
	var world World
	err := db.QueryRow("SELECT id, randomnumber FROM world WHERE id = $1", id).Scan(&world.ID, &world.RandomNumber)
	if err != nil {
		c.String(http.StatusInternalServerError, err.Error())
		return
	}
	c.JSON(http.StatusOK, world)
}

func queriesHandler(c *gin.Context) {
	n, err := strconv.Atoi(c.DefaultQuery("queries", "1"))
	if err != nil || n < 1 {
		n = 1
	}
	if n > 500 {
		n = 500
	}

	worlds := make([]World, n)
	for i := 0; i < n; i++ {
		id := rand.Intn(10000) + 1
		err := db.QueryRow("SELECT id, randomnumber FROM world WHERE id = $1", id).Scan(&worlds[i].ID, &worlds[i].RandomNumber)
		if err != nil {
			c.String(http.StatusInternalServerError, err.Error())
			return
		}
	}
	c.JSON(http.StatusOK, worlds)
}

func fortunesHandler(c *gin.Context) {
	rows, err := db.Query("SELECT id, message FROM fortune")
	if err != nil {
		c.String(http.StatusInternalServerError, err.Error())
		return
	}
	defer rows.Close()

	fortunes := []Fortune{{ID: 0, Message: "Additional fortune added at request time."}}
	for rows.Next() {
		var f Fortune
		if err := rows.Scan(&f.ID, &f.Message); err != nil {
			c.String(http.StatusInternalServerError, err.Error())
			return
		}
		fortunes = append(fortunes, f)
	}

	sort.Slice(fortunes, func(i, j int) bool {
		return fortunes[i].Message < fortunes[j].Message
	})

	c.Header("Content-Type", "text/html; charset=utf-8")
	fortuneTemplate.Execute(c.Writer, fortunes)
}

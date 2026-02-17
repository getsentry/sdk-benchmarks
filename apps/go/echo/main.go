package main

import (
	"database/sql"
	"fmt"
	"html/template"
	"io"
	"log"
	"math/rand"
	"net/http"
	"os"
	"sort"
	"strconv"

	"github.com/labstack/echo/v4"
	_ "github.com/lib/pq"
)

// sentryMiddleware is nil in baseline builds, set via init() in main_sentry.go.
var sentryMiddleware echo.MiddlewareFunc

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

// Template renderer for Echo
type templateRenderer struct {
	templates *template.Template
}

func (t *templateRenderer) Render(w io.Writer, name string, data interface{}, c echo.Context) error {
	return t.templates.ExecuteTemplate(w, name, data)
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

	e := echo.New()
	e.HideBanner = true
	e.Renderer = &templateRenderer{templates: fortuneTemplate}

	if sentryMiddleware != nil {
		e.Use(sentryMiddleware)
	}

	e.GET("/health", healthHandler)
	e.GET("/json", jsonHandler)
	e.GET("/db", dbHandler)
	e.GET("/queries", queriesHandler)
	e.GET("/fortunes", fortunesHandler)

	log.Println("listening on :8080")
	log.Fatal(e.Start(":8080"))
}

func healthHandler(c echo.Context) error {
	return c.String(http.StatusOK, "OK")
}

func jsonHandler(c echo.Context) error {
	return c.JSON(http.StatusOK, map[string]string{"message": "Hello, World!"})
}

func dbHandler(c echo.Context) error {
	id := rand.Intn(10000) + 1
	var world World
	err := db.QueryRow("SELECT id, randomnumber FROM world WHERE id = $1", id).Scan(&world.ID, &world.RandomNumber)
	if err != nil {
		return c.String(http.StatusInternalServerError, err.Error())
	}
	return c.JSON(http.StatusOK, world)
}

func queriesHandler(c echo.Context) error {
	n, err := strconv.Atoi(c.QueryParam("queries"))
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
			return c.String(http.StatusInternalServerError, err.Error())
		}
	}
	return c.JSON(http.StatusOK, worlds)
}

func fortunesHandler(c echo.Context) error {
	rows, err := db.Query("SELECT id, message FROM fortune")
	if err != nil {
		return c.String(http.StatusInternalServerError, err.Error())
	}
	defer rows.Close()

	fortunes := []Fortune{{ID: 0, Message: "Additional fortune added at request time."}}
	for rows.Next() {
		var f Fortune
		if err := rows.Scan(&f.ID, &f.Message); err != nil {
			return c.String(http.StatusInternalServerError, err.Error())
		}
		fortunes = append(fortunes, f)
	}

	sort.Slice(fortunes, func(i, j int) bool {
		return fortunes[i].Message < fortunes[j].Message
	})

	c.Response().Header().Set("Content-Type", "text/html; charset=utf-8")
	return fortuneTemplate.Execute(c.Response().Writer, fortunes)
}

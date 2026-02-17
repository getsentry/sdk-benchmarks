package main

import (
	"fmt"
	"log"
	"net/http"
	"sync/atomic"
)

var envelopeCount atomic.Int64

func main() {
	http.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodPost {
			count := envelopeCount.Add(1)
			if count%100 == 0 {
				log.Printf("Received %d envelopes", count)
			}
			w.Header().Set("Content-Type", "application/json")
			fmt.Fprintf(w, `{"id":"fake-event-id"}`)
			return
		}
		w.WriteHeader(http.StatusOK)
	})

	log.Println("fakerelay listening on :5000")
	log.Fatal(http.ListenAndServe(":5000", nil))
}

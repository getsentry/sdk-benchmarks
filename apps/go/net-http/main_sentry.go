//go:build instrumented

package main

import (
	"os"

	"github.com/getsentry/sentry-go"
	sentryhttp "github.com/getsentry/sentry-go/http"
)

func init() {
	if err := sentry.Init(sentry.ClientOptions{
		Dsn:              os.Getenv("SENTRY_DSN"),
		EnableTracing:    true,
		TracesSampleRate: 1.0,
	}); err != nil {
		panic("sentry init: " + err.Error())
	}
	sentryMiddleware = sentryhttp.New(sentryhttp.Options{
		Repanic: true,
	}).Handle
}

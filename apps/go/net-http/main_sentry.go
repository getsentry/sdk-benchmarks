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
		TracesSampleRate: 1.0,
	}); err != nil {
		panic("sentry init: " + err.Error())
	}
	sentryMiddleware = sentryhttp.New(sentryhttp.Options{}).Handle
}

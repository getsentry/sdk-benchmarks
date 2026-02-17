//go:build instrumented

package main

import (
	"os"

	"github.com/getsentry/sentry-go"
	sentrygin "github.com/getsentry/sentry-go/gin"
)

func init() {
	if err := sentry.Init(sentry.ClientOptions{
		Dsn:              os.Getenv("SENTRY_DSN"),
		TracesSampleRate: 1.0,
	}); err != nil {
		panic("sentry init: " + err.Error())
	}
	sentryMiddleware = sentrygin.New(sentrygin.Options{})
}

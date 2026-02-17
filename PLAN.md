# Sentry SDK Benchmarking Tool — Implementation Plan

## Context

Sentry needs a reliable, standardized way to benchmark SDK performance overhead across languages and frameworks. Three previous attempts exist:
- **sentry-sdk-benchmark** (archived): Best architecture (Docker Compose, vegeta, fakerelay, baseline vs. instrumented), but too manual and no CI integration.
- **sdk-measurements** (stale): Over-engineered with Argo Workflows + InfluxDB + Grafana infrastructure; died from complexity.
- **testing-sentry-python** (active): Functional testing only, not benchmarks, but useful as an integration catalog.

This tool takes the best ideas from all three (Docker-based isolation, vegeta load generation, fakerelay, baseline/instrumented comparison) while keeping infrastructure to zero (no InfluxDB, no Grafana, no Argo). Everything runs in Docker locally or in GitHub Actions.

---

## Architecture

### How It Works

```
bench run python/django --sdk-version=2.1.0

  1. Render docker-compose.yml from Jinja2 template
  2. Run baseline variant (app without SDK) N times:
     - docker compose up (postgres, app, loadgen)
     - vegeta hits all 4 endpoints at fixed RPS
     - collect latency (vegeta JSON) + CPU/memory (docker stats)
  3. Run instrumented variant (app with Sentry SDK) N times:
     - docker compose up (postgres, app, loadgen, fakerelay)
     - same load profile
  4. Compare: compute overhead % with statistical significance (t-test)
  5. Output: Markdown report + JSON results
```

### Key Design Decisions

- **Python CLI** using click — simple, no Go toolchain needed
- **Vegeta** for load generation (fixed RPS, avoids coordinated omission) — runs inside Docker
- **Fakerelay** (ported from archived repo) as mock Sentry server — isolates SDK overhead from network latency
- **docker stats** for CPU/memory — replaces cAdvisor, dramatically simpler
- **Single app source, two Dockerfiles** per framework — baseline and instrumented share identical app code, eliminating drift
- **4 endpoints per app** (JSON, single DB query, multi DB query, fortunes template) — richer than previous 1-endpoint approach
- **Go build tags** for Go apps — zero SDK code in baseline binary

---

## Repository Structure

```
sdk-benchmarks/
├── bench.py                          # CLI entrypoint
├── pyproject.toml                    # Python project (click, jinja2, pyyaml, scipy)
├── Makefile
│
├── .github/
│   ├── workflows/
│   │   ├── ci.yml                    # Self-test
│   │   ├── benchmark.yml             # Reusable workflow for SDK repos
│   │   └── trend.yml                 # Scheduled trend benchmarks
│   └── actions/
│       └── benchmark/action.yml      # Composite action wrapper
│
├── apps/
│   ├── python/
│   │   ├── common/postgres/          # Shared TechEmpower DB schema + seed data
│   │   ├── django/
│   │   │   ├── app/                  # Django project (views, models, templates)
│   │   │   ├── Dockerfile.baseline
│   │   │   ├── Dockerfile.instrumented
│   │   │   ├── requirements.txt
│   │   │   ├── requirements-sentry.txt.tmpl
│   │   │   └── sentry_init.py
│   │   ├── flask/                    # Same pattern
│   │   └── fastapi/                  # Same pattern (async/ASGI)
│   └── go/
│       ├── common/postgres/          # Same DB
│       ├── net-http/
│       │   ├── main.go               # All 4 endpoints
│       │   ├── main_sentry.go        # //go:build instrumented
│       │   ├── go.mod.tmpl
│       │   ├── Dockerfile.baseline
│       │   └── Dockerfile.instrumented
│       ├── gin/                      # Same pattern
│       └── echo/                     # Same pattern
│
├── tools/
│   ├── fakerelay/                    # Mock Sentry ingest server (Go)
│   │   ├── main.go
│   │   └── Dockerfile
│   └── loadgen/                      # Vegeta wrapper
│       ├── run.sh                    # Warmup + measurement phases
│       └── Dockerfile
│
├── configs/                          # Per-app benchmark configs
│   ├── python-django.yaml
│   ├── python-flask.yaml
│   ├── python-fastapi.yaml
│   ├── go-net-http.yaml
│   ├── go-gin.yaml
│   └── go-echo.yaml
│
├── templates/
│   └── docker-compose.yml.j2        # Service topology template
│
├── lib/                              # Python library modules
│   ├── runner.py                     # Docker Compose orchestration
│   ├── metrics.py                    # Parse vegeta output + docker stats
│   ├── compare.py                    # Statistical comparison (t-test)
│   ├── report.py                     # Markdown/JSON report generation
│   └── github.py                     # PR comment formatting
│
└── results/                          # Git-ignored local results
```

---

## App Endpoints (all apps implement these)

| Endpoint | Path | Purpose |
|----------|------|---------|
| JSON | `/json` | `{"message":"Hello, World!"}` — isolates pure SDK middleware overhead |
| Single Query | `/db` | SELECT 1 random row — tests single span creation |
| Multi Query | `/queries?queries=10` | SELECT 10 random rows — tests span tree depth |
| Fortunes | `/fortunes` | SELECT + sort + HTML template — most realistic workload |

All use a shared PostgreSQL with TechEmpower's World + Fortune tables.

---

## Benchmark Config Format

```yaml
# configs/python-django.yaml
language: python
framework: django
app_dir: apps/python/django

endpoints:
  - name: json
    path: /json
  - name: db-single
    path: /db
  - name: db-multi
    path: /queries?queries=10
  - name: fortunes
    path: /fortunes

load:
  rps: 100
  duration: 30s
  warmup: 10s
  connections: 10

iterations: 10

resources:
  app:
    cpus: "2"
    memory: "512m"
  postgres:
    cpus: "1"
    memory: "256m"
```

---

## Metrics Collected

| Metric | Source | How |
|--------|--------|-----|
| Latency (p50, p90, p95, p99, mean, max) | Vegeta | JSON output to volume mount |
| Throughput (actual RPS) | Vegeta | Same |
| CPU (mean %, max %) | docker stats | Polled every 1s during load |
| Memory (mean MB, max MB) | docker stats | Same |
| Startup time | Orchestrator | Time from `up` to health check 200 |

---

## Comparison & Regression Detection

- For each metric, collect all N iteration values per variant
- Compute overhead: `(instrumented_mean - baseline_mean) / baseline_mean * 100`
- Statistical significance via two-sample t-test (p < 0.05)
- Flag regression if overhead exceeds threshold (default: 5% latency, 10% CPU/memory)
- Output: Markdown table with per-endpoint, per-metric comparison + status indicators

---

## GitHub Action Integration

### Reusable workflow (primary integration point)

SDK repos call this from their CI:

```yaml
# In sentry-python/.github/workflows/benchmark.yml
jobs:
  bench:
    uses: getsentry/sdk-benchmarks/.github/workflows/benchmark.yml@main
    with:
      app: python/django
      sdk-version: "git+https://github.com/${{ github.repository }}@${{ github.head_ref }}"
      post-comment: true
```

The workflow runs benchmarks, compares baseline vs. instrumented, and posts a sticky PR comment with results.

### Trend tracking

- Scheduled weekly workflow runs benchmarks across latest SDK versions
- Results appended as JSON to a `gh-pages` branch
- Static HTML page with Chart.js renders overhead trends over time
- Zero infrastructure — just GitHub Pages

---

## Implementation Phases

### Phase 1: Core CLI + Django app (start here)
1. Initialize repo: `git init`, `pyproject.toml`, basic CLI skeleton with `click`
2. Implement `apps/python/common/postgres/` — Dockerfile + init.sql (TechEmpower schema)
3. Implement `apps/python/django/` — all 4 endpoints, `Dockerfile.baseline`, `Dockerfile.instrumented`, `sentry_init.py`
4. Implement `tools/fakerelay/` — minimal Go HTTP server that accepts POST, responds 200 (port from archived repo)
5. Implement `tools/loadgen/` — Docker container running vegeta with warmup + measurement
6. Implement `templates/docker-compose.yml.j2` — app, postgres, loadgen, fakerelay
7. Implement `configs/python-django.yaml`
8. Implement `lib/runner.py` — orchestrate compose up/down, poll docker stats, collect results
9. Implement `lib/metrics.py` — parse vegeta JSON output + docker stats samples
10. Implement `lib/compare.py` — t-test comparison, overhead computation
11. Implement `lib/report.py` — Markdown report generation
12. Wire it all together in `bench.py` — `run` and `compare` commands

### Phase 2: Flask + FastAPI apps
1. Implement `apps/python/flask/` — same 4 endpoints, gunicorn
2. Implement `apps/python/fastapi/` — same 4 endpoints, uvicorn (async)
3. Add configs for both
4. Validate cross-framework consistency

### Phase 3: Go apps
1. Implement `apps/go/common/postgres/` (shared DB)
2. Implement `apps/go/net-http/` with build tags for baseline/instrumented
3. Implement `apps/go/gin/` and `apps/go/echo/`
4. Add `go.mod.tmpl` templating for SDK version pinning
5. Add configs

### Phase 4: GitHub Action
1. Create `.github/workflows/benchmark.yml` reusable workflow
2. Create `.github/actions/benchmark/action.yml` composite action
3. Implement PR comment posting (`lib/github.py`)
4. Self-test CI workflow

### Phase 5: Trend Tracking
1. `sdk-bench trend` subcommand
2. `gh-pages` branch with static HTML + Chart.js
3. `.github/workflows/trend.yml` scheduled workflow

---

## Verification

After Phase 1, verify end-to-end locally:
```bash
# Install the CLI
pip install -e .

# Run the Django benchmark
bench run python/django --iterations=3

# Should output a Markdown table showing baseline vs. instrumented overhead
# Verify: latency overhead is small but measurable (typically 2-8%)
# Verify: all 4 endpoints are benchmarked
# Verify: results JSON is written to results/
```

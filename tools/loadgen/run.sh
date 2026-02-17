#!/usr/bin/env sh
set -eu

# ---------------------------------------------------------------------------
# Vegeta load-generator wrapper
#
# Runs two phases against a target HTTP application:
#   1. Warmup  – discards results (lets JIT / connection pools stabilise)
#   2. Measure – captures latency & throughput as JSON + a human report
#
# All behaviour is controlled via environment variables (see defaults below).
# ---------------------------------------------------------------------------

# --- Configuration (with defaults) ----------------------------------------
TARGET_HOST="${TARGET_HOST:?TARGET_HOST is required (e.g. app:8080)}"
RPS="${RPS:-100}"
DURATION="${DURATION:-30s}"
WARMUP="${WARMUP:-10s}"
ENDPOINTS="${ENDPOINTS:-/json}"
RESULTS_DIR="${RESULTS_DIR:-/results}"
CONNECTIONS="${CONNECTIONS:-10}"
WORKERS="${WORKERS:-10}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-60}"

# --- Wait for target health -----------------------------------------------
echo "Waiting for http://${TARGET_HOST}/health to return 200 ..."
elapsed=0
while [ "$elapsed" -lt "$HEALTH_TIMEOUT" ]; do
    if wget -q -O /dev/null --spider "http://${TARGET_HOST}/health" 2>/dev/null; then
        echo "Target is healthy."
        break
    fi
    sleep 1
    elapsed=$((elapsed + 1))
done

if [ "$elapsed" -ge "$HEALTH_TIMEOUT" ]; then
    echo "ERROR: Target did not become healthy within ${HEALTH_TIMEOUT}s" >&2
    exit 1
fi

# --- Build vegeta targets file --------------------------------------------
TARGETS_FILE="/tmp/targets.txt"
: > "$TARGETS_FILE"

# Split ENDPOINTS on commas
IFS=','
for path in $ENDPOINTS; do
    echo "GET http://${TARGET_HOST}${path}" >> "$TARGETS_FILE"
done
unset IFS

echo "Targets:"
cat "$TARGETS_FILE"

# --- Ensure results directory exists --------------------------------------
mkdir -p "$RESULTS_DIR"

# --- Phase 1: Warmup (results discarded) ---------------------------------
echo ""
echo "=== Warmup phase (${WARMUP}, ${RPS} rps) ==="
vegeta attack \
    -rate="${RPS}" \
    -duration="${WARMUP}" \
    -targets="$TARGETS_FILE" \
    -workers="${WORKERS}" \
    -connections="${CONNECTIONS}" \
    > /dev/null

echo "Warmup complete."

# --- Phase 2: Measurement ------------------------------------------------
echo ""
echo "=== Measurement phase (${DURATION}, ${RPS} rps) ==="
vegeta attack \
    -rate="${RPS}" \
    -duration="${DURATION}" \
    -targets="$TARGETS_FILE" \
    -workers="${WORKERS}" \
    -connections="${CONNECTIONS}" \
    | tee /tmp/results.bin \
    | vegeta encode --to json \
    > "${RESULTS_DIR}/results.json"

# --- Generate human-readable report --------------------------------------
vegeta report /tmp/results.bin > "${RESULTS_DIR}/report.txt"

echo ""
echo "=== Report ==="
cat "${RESULTS_DIR}/report.txt"

echo ""
echo "Results written to ${RESULTS_DIR}/results.json"
echo "Report  written to ${RESULTS_DIR}/report.txt"

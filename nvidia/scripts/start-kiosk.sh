#!/usr/bin/env bash

set -Eeuo pipefail
umask 077

readonly KIOSK_URL="http://127.0.0.1:8000/"
readonly HEALTH_URL="http://127.0.0.1:8000/health"
readonly STATE_DIR="/home/user/.local/state/vision-kiosk"
readonly LOG_FILE="${STATE_DIR}/kiosk.log"
readonly MAX_LAUNCH_ATTEMPTS=3
readonly PAGE_READY_TIMEOUT_SECONDS=30
readonly STABLE_RUNTIME_SECONDS=45

mkdir -p "$STATE_DIR"

log() {
  printf '%s %s\n' "$(date --iso-8601=seconds)" "$*" | tee -a "$LOG_FILE"
}

find_browser() {
  local candidate
  for candidate in \
    /usr/bin/google-chrome-stable \
    /usr/bin/google-chrome \
    /usr/bin/chromium \
    /usr/bin/chromium-browser \
    /home/user/.local/bin/google-chrome; do
    if [ -x "$candidate" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

wait_for_backend() {
  local wait_count=0

  log "Waiting for Vision AI backend and frontend..."
  until curl --fail --silent --show-error --noproxy '*' --connect-timeout 1 --max-time 2 \
    "$HEALTH_URL" >/dev/null \
    && curl --fail --silent --show-error --noproxy '*' --connect-timeout 1 --max-time 2 \
      "$KIOSK_URL" >/dev/null; do
    wait_count=$((wait_count + 1))
    if (( wait_count % 10 == 0 )); then
      log "Backend is not ready yet; continuing to wait."
    fi
    sleep 1
  done
  log "Backend and frontend are ready."
}

wait_for_page() {
  local browser_pid="$1"
  local profile_dir="$2"
  local elapsed=0
  local devtools_port=""
  local page_list=""

  while (( elapsed < PAGE_READY_TIMEOUT_SECONDS )); do
    if ! kill -0 "$browser_pid" 2>/dev/null; then
      return 1
    fi

    if [ -s "${profile_dir}/DevToolsActivePort" ]; then
      devtools_port="$(sed -n '1p' "${profile_dir}/DevToolsActivePort")"
      if [[ "$devtools_port" =~ ^[0-9]+$ ]]; then
        page_list="$(curl --silent --show-error --noproxy '*' --connect-timeout 1 --max-time 1 \
          "http://127.0.0.1:${devtools_port}/json/list" 2>/dev/null || true)"
        if [[ "$page_list" == *"\"url\": \"${KIOSK_URL}\""* ]]; then
          return 0
        fi
      fi
    fi

    sleep 1
    elapsed=$((elapsed + 1))
  done

  return 1
}

runtime_base="${XDG_RUNTIME_DIR:-/tmp}"
mkdir -p "$runtime_base"

exec 9>"${runtime_base}/vision-kiosk-launcher.lock"
if ! flock -n 9; then
  log "Another Vision Kiosk launcher is already running; exiting."
  exit 0
fi

browser_bin="$(find_browser || true)"
if [ -z "$browser_bin" ]; then
  log "ERROR: No supported Chromium or Chrome executable was found."
  exit 1
fi

log "Using browser: ${browser_bin} ($("$browser_bin" --version 2>/dev/null || echo unknown-version))"
wait_for_backend

for (( attempt=1; attempt<=MAX_LAUNCH_ATTEMPTS; attempt++ )); do
  profile_dir="$(mktemp -d "${runtime_base}/vision-kiosk-profile.XXXXXX")"
  launch_started="$(date +%s)"

  log "Launching Kiosk (attempt ${attempt}/${MAX_LAUNCH_ATTEMPTS}) with clean profile ${profile_dir}."

  "$browser_bin" \
    --kiosk \
    --no-first-run \
    --no-default-browser-check \
    --noerrdialogs \
    --disable-session-crashed-bubble \
    --disable-background-networking \
    --disable-component-update \
    --disable-domain-reliability \
    --disable-sync \
    --disable-extensions \
    --disable-dev-shm-usage \
    --disable-gpu \
    --disable-features=Translate,OptimizationHints,MediaRouter \
    --password-store=basic \
    --autoplay-policy=no-user-gesture-required \
    --disable-pinch \
    --overscroll-history-navigation=0 \
    --remote-debugging-address=127.0.0.1 \
    --remote-debugging-port=0 \
    --user-data-dir="$profile_dir" \
    "$KIOSK_URL" >>"$LOG_FILE" 2>&1 &
  browser_pid=$!

  if ! wait_for_page "$browser_pid" "$profile_dir"; then
    log "Kiosk did not load the target page within ${PAGE_READY_TIMEOUT_SECONDS}s; restarting it."
    kill -TERM "$browser_pid" 2>/dev/null || true
    wait "$browser_pid" 2>/dev/null || true
    sleep "$attempt"
    continue
  fi

  log "Kiosk page is loaded successfully."
  set +e
  wait "$browser_pid"
  browser_status=$?
  set -e

  runtime_seconds=$(( $(date +%s) - launch_started ))
  if (( runtime_seconds >= STABLE_RUNTIME_SECONDS )); then
    log "Kiosk exited after ${runtime_seconds}s (status ${browser_status}); treating this as an intentional close."
    exit "$browser_status"
  fi

  if ! curl --fail --silent --noproxy '*' --connect-timeout 1 --max-time 2 \
    "$HEALTH_URL" >/dev/null; then
    log "Backend is offline; not restarting the Kiosk."
    exit 0
  fi

  log "Kiosk exited too early after ${runtime_seconds}s (status ${browser_status}); retrying with a fresh profile."
  sleep "$attempt"
done

log "ERROR: Kiosk failed to remain running after ${MAX_LAUNCH_ATTEMPTS} attempts."
exit 1

#!/usr/bin/env bash
# Wait for the backend FastAPI service to be fully online
echo "Waiting for Vision AI backend to start..."
while ! curl -s http://127.0.0.1:8000/health >/dev/null; do
  sleep 1
done

echo "Backend is online. Launching Chromium in Kiosk mode..."

# Run Chromium in Kiosk mode pointing to our local frontend
# Added flags to ignore setup/checks and prevent bar popups
/home/user/.local/bin/google-chrome \
  --kiosk \
  --no-first-run \
  --no-default-browser-check \
  --autoplay-policy=no-user-gesture-required \
  --check-for-update-interval=31536000 \
  --disable-pinch \
  --overscroll-history-navigation=0 \
  http://127.0.0.1:8000/

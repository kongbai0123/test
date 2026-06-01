#!/usr/bin/env bash
echo "Stopping Vision AI Kiosk system..."

# Stop the backend service
sudo systemctl stop vision-system.service

# Close any running Chromium windows
pkill -f "google-chrome"
pkill -f "chromium"

echo "System stopped."

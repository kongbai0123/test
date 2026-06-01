#!/usr/bin/env bash
# Exit immediately if a command exits with a non-zero status
set -e

echo "=================================================="
echo "  Starting Vision AI Kiosk System Installation    "
echo "=================================================="

# 1. Ensure NVM environment is loaded
echo "Loading Node.js environment..."
export NVM_DIR="/home/user/.nvm"
if [ -s "$NVM_DIR/nvm.sh" ]; then
    . "$NVM_DIR/nvm.sh"
else
    echo "ERROR: NVM not found at $NVM_DIR"
    exit 1
fi

# 2. Build the React Frontend
echo "Building React frontend..."
cd /home/user/workspace/nvidia/frontend
npm run build
echo "Frontend built successfully!"

# 3. Create target directory /opt/vision-system
echo "Creating deployment target directory: /opt/vision-system..."
sudo mkdir -p /opt/vision-system
sudo chown -R user:user /opt/vision-system

# 4. Copy codebase to /opt/vision-system
echo "Copying files to /opt/vision-system..."
# Remove any existing contents to prevent conflict
rm -rf /opt/vision-system/*
cp -r /home/user/workspace/nvidia/backend /opt/vision-system/
cp -r /home/user/workspace/nvidia/frontend /opt/vision-system/
cp -r /home/user/workspace/nvidia/config /opt/vision-system/
cp -r /home/user/workspace/nvidia/scripts /opt/vision-system/

# Make sure scripts are executable
chmod +x /opt/vision-system/scripts/*.sh

# 5. Set up Python Virtual Environment in backend
echo "Setting up Python virtual environment..."
# Check and install python3-venv package if not present
if ! dpkg -s python3-venv >/dev/null 2>&1; then
    echo "python3-venv package not found. Installing..."
    sudo apt-get update
    sudo apt-get install -y python3-venv
fi
python3 -m venv --system-site-packages /opt/vision-system/backend/venv
# Activate venv and install dependencies
/opt/vision-system/backend/venv/bin/pip install --upgrade pip
/opt/vision-system/backend/venv/bin/pip install fastapi uvicorn psutil pyyaml


# 6. Install and enable Systemd Service
echo "Installing Systemd service..."
sudo cp /opt/vision-system/scripts/vision-system.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable vision-system.service
sudo systemctl start vision-system.service
echo "Systemd service installed and started successfully!"

# 7. Configure GNOME Autostart for Kiosk mode
echo "Configuring GNOME Autostart..."
mkdir -p /home/user/.config/autostart
cp /opt/vision-system/scripts/vision-kiosk.desktop /home/user/.config/autostart/
chmod +x /home/user/.config/autostart/vision-kiosk.desktop
if [ -f "/home/user/Desktop/Vision_Kiosk.desktop" ]; then
    chmod +x /home/user/Desktop/Vision_Kiosk.desktop
    gio set /home/user/Desktop/Vision_Kiosk.desktop metadata::trusted yes || true
fi
echo "Autostart configured successfully!"

# 8. Configure GDM3 Auto-Login
echo "Configuring GDM3 Auto-login..."
GDM3_CONF="/etc/gdm3/custom.conf"
if [ -f "$GDM3_CONF" ]; then
    # Backup the original configuration
    sudo cp "$GDM3_CONF" "${GDM3_CONF}.bak"
    
    # Configure auto-login settings
    sudo sed -i 's/^#\s*AutomaticLoginEnable\s*=\s*true/AutomaticLoginEnable=true/' "$GDM3_CONF"
    sudo sed -i 's/^#\s*AutomaticLogin\s*=\s*user1/AutomaticLogin=user/' "$GDM3_CONF"
    
    # In case they were not commented out but just not set
    if ! grep -q "^AutomaticLoginEnable=true" "$GDM3_CONF"; then
        sudo sed -i '/\[daemon\]/a AutomaticLoginEnable=true\nAutomaticLogin=user' "$GDM3_CONF"
    fi
    echo "GDM3 Auto-login configured!"
else
    echo "WARNING: $GDM3_CONF not found. Skipping auto-login configuration."
fi

echo "=================================================="
echo "  Installation Complete! Please restart the Jetson  "
echo "  to boot directly into Chromium Kiosk mode.      "
echo "=================================================="

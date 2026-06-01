#!/usr/bin/env bash
cat > ~/Desktop/Open_USB.desktop <<EOF
[Desktop Entry]
Type=Application
Name=Open USB
Comment=Auto mount and open USB drive
Exec=$HOME/usb-open.sh
Icon=drive-removable-media-usb
Terminal=true
Categories=Utility;
EOF

chmod +x ~/Desktop/Open_USB.desktop
echo "桌面捷徑已建立在 ~/Desktop/Open_USB.desktop"

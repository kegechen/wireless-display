#!/bin/bash
echo "=== Wireless Display Client Setup (UOS) ==="
echo ""
echo "Installing Python dependencies..."
pip3 install --user Pillow 2>/dev/null || sudo apt install -y python3-pil
echo ""
echo "Checking PyQt5..."
python3 -c "import PyQt5; print('PyQt5 OK')" 2>/dev/null || sudo apt install -y python3-pyqt5
echo ""
echo "Done! Start client with:"
echo "  python3 client/main.py --host <WINDOWS_IP>"
echo ""

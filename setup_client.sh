#!/bin/bash
echo "=== Wireless Display Client Setup ==="
echo ""

echo "[1/3] 安装 Python 依赖 ..."
pip3 install --user Pillow 2>/dev/null || sudo apt install -y python3-pil
echo ""

echo "[2/3] 检查 PyQt5 ..."
python3 -c "import PyQt5; print('  OK: PyQt5 已安装')" 2>/dev/null || {
    echo "  安装 PyQt5 ..."
    sudo apt install -y python3-pyqt5
}
echo ""

echo "[3/3] 检查 ffmpeg (H.264 模式需要) ..."
if command -v ffmpeg &>/dev/null; then
    echo "  OK: $(ffmpeg -version 2>&1 | head -1)"
else
    echo "  安装 ffmpeg ..."
    sudo apt install -y ffmpeg
fi
echo ""

echo "=== 安装完成 ==="
echo ""
echo "启动命令:"
echo "  ./start_client.sh <服务端IP>"
echo "  或: python3 client/main.py --host <服务端IP>"
echo ""

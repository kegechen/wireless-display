#!/bin/bash
# 客户端启动脚本
# 用法:
#   ./start_client.sh 192.168.137.1          # 连接指定 IP
#   ./start_client.sh 192.168.137.1 9876     # 指定端口
#   ./start_client.sh                        # 交互式输入 IP

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

HOST="${1:-}"
PORT="${2:-9876}"

if [ -z "$HOST" ]; then
    echo "=== Wireless Display Client ==="
    echo ""
    read -rp "请输入服务端 IP 地址: " HOST
    if [ -z "$HOST" ]; then
        echo "已取消"
        exit 1
    fi
fi

echo ""
echo "连接到 $HOST:$PORT ..."
echo "快捷键: ESC=退出  F11=切换全屏"
echo ""

python3 client/main.py --host "$HOST" --port "$PORT"

#!/bin/bash
# start.sh — 启动 Knowledge Hub 服务
cd "$(dirname "$0")"

# 使用 .venv 中的 Python
PYTHON="$(pwd)/.venv/bin/python3"

# 启动服务（后台运行）
echo "启动 Knowledge Hub..."
nohup $PYTHON hub_server.py > logs/server.log 2>&1 &
echo $! > logs/server.pid
echo "PID: $(cat logs/server.pid)"
echo "日志: logs/server.log"
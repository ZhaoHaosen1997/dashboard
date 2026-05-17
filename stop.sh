#!/bin/bash
cd "$(dirname "$0")"

# 杀掉占用8850端口的进程
PID=$(lsof -t -i:8850 2>/dev/null || netstat -tlnp 2>/dev/null | grep :8850 | awk '{print $7}' | cut -d'/' -f1)

if [ -n "$PID" ]; then
    echo "停止 Dashboard 服务 (PID: $PID)..."
    kill $PID 2>/dev/null
    sleep 1
    echo "已停止"
else
    echo "Dashboard 服务未运行"
fi

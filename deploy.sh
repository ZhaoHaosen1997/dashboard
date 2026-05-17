#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "=== Dashboard 部署脚本 ==="

# 检查依赖
echo "[1/3] 检查依赖..."
if ! python -c "import flask" 2>/dev/null; then
    echo "安装依赖..."
    pip install -r requirements.txt
fi

# 停止旧进程
echo "[2/3] 停止旧进程..."
bash stop.sh

# 启动服务
echo "[3/3] 启动服务..."
if [ -d .venv/bin/activate ]; then
    source .venv/bin/activate
fi
nohup python app.py > dashboard.log 2>&1 &
echo "PID: $!"

sleep 2
if curl -s http://localhost:8850 > /dev/null 2>&1; then
    echo "✓ 服务已启动: http://localhost:8850"
else
    echo "✗ 启动失败，查看日志: tail -f dashboard.log"
fi

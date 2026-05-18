#!/bin/bash
set -e
echo "=== Dashboard 代码同步脚本 ==="

SOURCE="/mnt/c/mycode/dashboard"
TARGET="/home/zhaohaosen/applications/dashboard"

# 1. 停止服务
echo "[1/4] 停止服务..."
sudo systemctl stop dashboard || true

# 2. 拉取新代码（排除 config.db 和 .git）
echo "[2/4] 拉取新代码..."
rsync -av --exclude='config.db' --exclude='.git' --exclude='__pycache__' --exclude='.workbuddy' \
    "$SOURCE/" "$TARGET/"

# 3. 重启服务
echo "[3/4] 重启服务..."
sudo systemctl restart dashboard

# 4. 检查状态
echo "[4/4] 检查状态..."
sudo systemctl status dashboard --no-pager

echo ""
echo "=== 完成！访问 http://localhost:8850 ==="

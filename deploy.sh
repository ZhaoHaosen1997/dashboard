#!/bin/bash
set -e
echo "=== Dashboard 部署脚本 ==="

# 重启服务（自动处理停止+启动）
echo "[1/1] 重启 Dashboard 服务..."
sudo systemctl restart dashboard

sleep 2
sudo systemctl status dashboard --no-pager

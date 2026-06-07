#!/usr/bin/env bash
# sync-to-pi.sh — 从 Windows 同步代码到树莓派（或其他远程主机）并重启服务
#
# 使用方式（在 Git Bash 里执行）：
#   bash sync-to-pi.sh
#
# 配置说明：
#   修改下方 PI_USER、PI_HOST、PI_DIR 为实际部署目标
#   要求：目标主机已安装 rsync，SSH 免密已配置
#
# ⚠️  以下文件始终排除，绝不覆盖目标机数据：
#     config.db          — 目标机生产数据库
#     backend/config.yml — 目标机专属配置（含网卡名等机器特定参数）
#     ~/.dashboard/.key  — Fernet 密钥（在 home 目录，不在同步路径）

set -e

# ── 按实际环境修改以下三行 ────────────────────────────────────
PI_USER="<your-username>"
PI_HOST="<your-raspberry-pi-ip>"
PI_DIR="/home/<your-username>/applications/dashboard/"
# ─────────────────────────────────────────────────────────────

SERVICE="dashboard"
PI_REMOTE="$PI_USER@$PI_HOST"

# 获取脚本所在目录（即项目根目录）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "====================================="
echo " Dashboard → 树莓派 部署"
echo " 源：$SCRIPT_DIR"
echo " 目标：$PI_REMOTE:$PI_DIR"
echo "====================================="

echo ""
echo "[1/3] rsync 同步代码（排除数据库、本机配置和临时文件）..."
MSYS_NO_PATHCONV=1 wsl -d DebianDev -- rsync -av --checksum \
  --exclude='config.db' \
  --exclude='backend/config.yml' \
  --exclude='.git' \
  --exclude='.workbuddy' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.venv' \
  --exclude='deploy_package.tar.gz' \
  "/mnt/c/mycode/dashboard/" \
  "$PI_REMOTE:$PI_DIR"

echo ""
echo "[2/3] 重启服务..."
ssh -o StrictHostKeyChecking=no "$PI_REMOTE" "sudo systemctl restart $SERVICE"

echo ""
echo "[3/3] 验证服务状态..."
ssh -o StrictHostKeyChecking=no "$PI_REMOTE" "
  sleep 2
  STATUS=\$(sudo systemctl is-active $SERVICE)
  echo \"服务状态：\$STATUS\"
  if [ \"\$STATUS\" = 'active' ]; then
    echo '✅ 部署成功！'
    echo ''
    echo '最近 10 条日志：'
    sudo journalctl -u $SERVICE -n 10 --no-pager
  else
    echo '❌ 服务未正常启动，查看日志：'
    sudo journalctl -u $SERVICE -n 30 --no-pager
    exit 1
  fi
"

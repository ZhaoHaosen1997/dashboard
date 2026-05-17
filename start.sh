#!/bin/bash
cd "$(dirname "$0")"

# 激活虚拟环境并启动
if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
fi

# 如果没有虚拟环境，用系统Python
if [ ! -f .venv/bin/activate ]; then
    echo "未检测到虚拟环境，使用系统Python..."
fi

echo "启动 Dashboard 服务..."
python app.py

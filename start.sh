#!/bin/bash
echo "启动 Dashboard 服务..."
sudo systemctl start dashboard
sudo systemctl status dashboard --no-pager

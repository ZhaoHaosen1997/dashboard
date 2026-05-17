@echo off
chcp 65001 >nul
cd /d %~dp0

echo 启动 Dashboard 服务...

REM 检查是否有虚拟环境
if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
    echo [虚拟环境] 已激活
) else (
    echo [提示] 未检测到虚拟环境，使用系统Python
)

REM 启动服务
python app.py

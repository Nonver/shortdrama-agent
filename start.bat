@echo off
cd /d %~dp0backend
echo 启动 AI 短剧剧本 Agent ...
echo 用户端: http://127.0.0.1:8090/
echo 后台:   http://127.0.0.1:8090/admin
echo 默认后台账号 admin（初始口令见部署说明）
start "" http://127.0.0.1:8090/
"../.venv/Scripts/python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8090
pause

@echo off
chcp 65001 >nul
cd /d C:\dev\rdom
title rdom discord
echo 디스코드 제어 봇 - 이 창을 닫으면 /명령이 멈춥니다.
.venv\Scripts\python.exe -u tools\discord_bot.py
pause

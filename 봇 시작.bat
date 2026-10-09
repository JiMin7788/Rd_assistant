@echo off
chcp 65001 >nul
cd /d C:\dev\rdom
title rdom gear bot
echo 기어덱 봇 시작 - 이 창을 닫으면 봇이 멈춥니다.
.venv\Scripts\python.exe -u tools\supervisor.py %*
pause

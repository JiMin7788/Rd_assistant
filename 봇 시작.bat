@echo off
chcp 65001 >nul
cd /d C:\dev\rdom
.venv\Scripts\python.exe -u tools\run_all.py %*

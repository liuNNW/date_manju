@echo off
title 自动刷新 HiTwo 短剧榜（每 10 分钟）
cd /d "%~dp0"
set PY=F:\dsh0202\home\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe
if not exist "%PY%" set PY=python
set PYTHONIOENCODING=gbk

:loop
echo [%date% %time%] 正在刷新榜单数据...
"%PY%" build_rank_page.py --no-episodes
echo [%date% %time%] 完成，10 分钟后再次刷新。浏览器里按 F5 看最新。
timeout /t 600 /nobreak >nul
goto loop
@echo off
title 刷新 HiTwo 短剧榜
cd /d "%~dp0"
set PY=F:\dsh0202\home\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe
if not exist "%PY%" set PY=python
set PYTHONIOENCODING=gbk

echo.
echo   ============================================
echo    HiTwo 短剧榜 · 一键刷新
echo   ============================================
echo.

"%PY%" build_rank_page.py --no-episodes
if errorlevel 1 goto FAIL

echo.
echo   数据已更新，正在打开最新页面...
start "" "短剧榜单.html"
exit

:FAIL
echo.
echo   [失败] 没抓到数据，检查网络后重试。
echo   若提示找不到 python，请把 python 加入 PATH，或编辑本文件里的 PY 路径。
echo.
pause
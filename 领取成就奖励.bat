@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title 临时领取成就奖励
set "PYTHONIOENCODING=utf-8"
set "PATH=%CD%\toolkit;%CD%\toolkit\Scripts;%CD%\toolkit\Lib\site-packages\adbutils\binaries;%PATH%"
echo 请先暂停 OAS 的运行任务，并将游戏登录到需要领奖的角色。
echo 默认使用 OAS1 的设备设置，领取当前登录角色已经达成的成就奖励。
echo.
"%CD%\toolkit\python.exe" -m dev_tools.claim_achievement_rewards %*
set "CLAIM_RESULT=%ERRORLEVEL%"
echo.
if "%CLAIM_RESULT%"=="0" (echo 领奖流程已结束。) else (echo 领奖未完成，请查看上方错误信息。)
pause
exit /b %CLAIM_RESULT%

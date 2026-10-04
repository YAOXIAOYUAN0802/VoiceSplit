@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 人声 / 背景音乐分离工具

echo ================ 自动诊断 ================
echo 程序目录: %~dp0
echo.
echo [1/3] 检查运行库与模型 ...
"人声伴奏分离工具.exe" --selftest
set RC=%ERRORLEVEL%
echo.
if "%RC%"=="0" (
  echo [2/3] 自检通过，正在打开操作界面 ...
) else (
  echo [2/3] 自检未通过，请把上面的信息发给开发者。
  pause
  exit /b %RC%
)
echo [3/3] 启动界面
"人声伴奏分离工具.exe"

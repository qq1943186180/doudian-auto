@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ==========================================
echo   抖店自动处理
echo ==========================================
echo.

set "REPORT_DIR=work\auto-pilot-20261110\report"
set "FACTS=%REPORT_DIR%\facts-needed.json"
set "PY=.venv\Scripts\python.exe"

if not exist "%PY%" (
  echo [错误] 找不到虚拟环境 .venv
  echo 请确认在项目根目录运行。
  pause
  exit /b 1
)

rem 如果资料表已经填过真实值，就带上 --apply 去写；否则只巡检。
set "HAS_FACTS="
if exist "%FACTS%" (
  "%PY%" -X utf8 -c "import json,sys;d=json.load(open(r'%FACTS%',encoding='utf-8'));ok=any(v.strip() and v.strip()!='待确认' for i in d.get('items',[]) for v in (i.get('attributes') or {}).values());sys.exit(0 if ok else 1)" >nul 2>&1
  if !errorlevel!==0 set "HAS_FACTS=1"
)

if defined HAS_FACTS (
  echo 检测到已填写的资料，将写入商品并核对...
  echo.
  "%PY%" -X utf8 -m doudian_auto.cli batch auto --apply --facts "%FACTS%" --shop 销霁百货 --report-dir "%REPORT_DIR%"
) else (
  echo 正在巡检全店商品，只读不改...
  echo.
  "%PY%" -X utf8 -m doudian_auto.cli batch auto --report-dir "%REPORT_DIR%"
)

echo.
echo ==========================================
if exist "%FACTS%" (
  echo 需要你填写的资料表：
  echo   %FACTS%
  echo.
  echo 在空引号里填真实值，不知道就写 待确认。
  echo 填完保存，再双击本文件。
) else (
  echo 没有需要你补的资料，全部处理完毕。
)
echo ==========================================
echo.
pause

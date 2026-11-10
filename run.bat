@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"
set "REPORT_DIR=work\auto-pilot-20261110\report"
set "FACTS=%REPORT_DIR%\facts-needed.json"
if not exist "%PY%" (
  echo 找不到项目Python，请检查安装。
  pause
  exit /b 1
)
echo 1. 新鲜只读预检和报告
echo 2. 执行已授权任务：发布已填属性、核查未知提交、处理已就绪图文
choice /C 12 /N /M "请选择 1 或 2："
if errorlevel 2 goto apply
"%PY%" -X utf8 -m doudian_auto.cli batch auto --report-dir "%REPORT_DIR%"
goto result
:apply
if exist "%FACTS%" (
  "%PY%" -X utf8 -m doudian_auto.cli batch auto --apply --facts "%FACTS%" --shop 销霁百货 --report-dir "%REPORT_DIR%"
) else (
  "%PY%" -X utf8 -m doudian_auto.cli batch auto --apply --shop 销霁百货 --report-dir "%REPORT_DIR%"
)
:result
if errorlevel 1 (
  echo 本轮发生错误，请查看终端与已有任务证据，不能据此认为未提交。
) else (
  echo 本轮已结束；是否完成请看 auto-report.md 的实际动作和最终队列。
)
echo 报告目录：%REPORT_DIR%
echo 已填写的资料会保留。只有被报告核验通过的项目才算完成。
pause

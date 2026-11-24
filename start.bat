@echo off
rem 業務データ処理ツールの画面を開く（初回は setup が必要：README を参照）
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo 先に README の「はじめに」の手順で準備をしてください。
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m dataprep

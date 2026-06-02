$ErrorActionPreference = "Stop"

python -m pip install --upgrade pip
python -m pip install --upgrade ".[desktop]" pyinstaller

python -m PyInstaller `
  --noconfirm `
  --clean `
  --windowed `
  --name DeepSeekTuLAgent `
  --collect-data deepseek_tulagent `
  --hidden-import webview `
  src/deepseek_tulagent/desktop/app.py

Write-Host "Built dist\DeepSeekTuLAgent\DeepSeekTuLAgent.exe"

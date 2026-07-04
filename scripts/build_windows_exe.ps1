# Optional: build a standalone Windows .exe of the Fathom desktop app.
#
# You do NOT need this to run the desktop app. The simplest path is:
#     py -3 -m pip install --upgrade "deepseek-tulagent[desktop]"
#     deepseekTulDesktop
# Build an exe only if you want a double-clickable bundle for machines without Python.

$ErrorActionPreference = "Stop"

python -m pip install --upgrade pip
# pywebview pulls in its Windows backend (pythonnet / WebView2) via environment markers.
python -m pip install --upgrade ".[desktop]" pyinstaller

# --collect-all bundles data files (the desktop assets/ HTML/CSS/JS) AND submodules;
# the explicit hidden-imports cover pywebview's Windows backend, which PyInstaller's
# static analysis otherwise misses (the usual source of "module not found" crashes).
python -m PyInstaller `
  --noconfirm `
  --clean `
  --windowed `
  --name DeepSeekTuLAgent `
  --collect-all deepseek_tulagent `
  --collect-all webview `
  --collect-submodules webview `
  --hidden-import clr `
  --hidden-import proxy_tools `
  --hidden-import bottle `
  --hidden-import webview.platforms.edgechromium `
  --hidden-import webview.platforms.winforms `
  --hidden-import webview.platforms.mshtml `
  src/deepseek_tulagent/desktop/app.py

Write-Host ""
Write-Host "Built dist\DeepSeekTuLAgent\DeepSeekTuLAgent.exe"
Write-Host "If the window is blank, install the Microsoft Edge WebView2 Runtime (a free system component)."

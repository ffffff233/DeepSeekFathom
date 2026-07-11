# Optional: build a standalone Windows .exe of the Fathom desktop app.
#
# You do NOT need this to run the desktop app. The simplest path is:
#     py -3 -m pip install --upgrade "deepseek-tulagent[desktop]"
#     deepseekfathom-desktop
# Build an exe only if you want a double-clickable bundle for machines without Python.

$ErrorActionPreference = "Stop"

python -m pip install --upgrade pip
# pywebview pulls in its Windows backend (pythonnet / WebView2) via environment markers.
python -m pip install --upgrade ".[desktop]" pyinstaller

# The checked-in spec pins package discovery and UI assets to this checkout. Generating
# a spec with --collect-all here can silently pull an older site-packages frontend.
python -m PyInstaller --noconfirm --clean DeepSeekFathom.spec

$iscc = @(
  "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
  "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
  "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($iscc) {
  $version = python -c "from deepseek_tulagent.desktop import DESKTOP_VERSION; print(DESKTOP_VERSION)"
  & $iscc "/DMyAppVersion=$version" scripts/windows_installer.iss
  if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed with exit code $LASTEXITCODE" }
} else {
  Write-Warning "Inno Setup 6 was not found; the portable app was built, but the Setup exe was skipped."
}

Write-Host ""
Write-Host "Built dist\DeepSeekFathom\DeepSeekFathom.exe"
if ($iscc) { Write-Host "Built dist\installer\DeepSeekFathom-$version-Setup.exe" }
Write-Host "If the window is blank, install the Microsoft Edge WebView2 Runtime (a free system component)."

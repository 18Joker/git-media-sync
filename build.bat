@echo off
rem 一键打包成单个 exe（产物在 dist\GitMediaDownloader.exe）
cd /d %~dp0
.venv\Scripts\python.exe -m PyInstaller --onefile --windowed --name GitMediaDownloader ^
  --collect-submodules aligo ^
  --hidden-import qrcode_terminal --hidden-import coloredlogs ^
  --noconfirm main.py
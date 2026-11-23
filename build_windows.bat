@echo off
setlocal
cd /d "%~dp0"
py -3.12 -m venv .venv
if errorlevel 1 exit /b 1
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pytest -q
if errorlevel 1 exit /b 1
python -m PyInstaller --noconfirm --clean --onefile --windowed --name SodiumFlowNext --collect-all pyqtgraph --collect-all PySide6 --hidden-import scipy.signal run.py
if errorlevel 1 exit /b 1
echo Executable: dist\SodiumFlowNext.exe
endlocal

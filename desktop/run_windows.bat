@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel% neq 0 (
  echo Python не найден. Установите Python 3.10+ с https://www.python.org/downloads/
  echo При установке отметьте галочку "Add python.exe to PATH".
  pause
  exit /b 1
)
if not exist .venv (
  echo Первый запуск: создаю окружение и ставлю зависимости...
  py -3 -m venv .venv || goto :error
  .venv\Scripts\python -m pip install --upgrade pip >nul
  .venv\Scripts\python -m pip install -r requirements.txt || goto :error
)
start "" .venv\Scripts\pythonw -m gogame
exit /b 0
:error
echo Не удалось установить зависимости.
pause

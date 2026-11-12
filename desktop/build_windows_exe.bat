@echo off
chcp 65001 >nul
rem Сборка самостоятельной программы GoTrainer.exe (не требует Python у пользователя)
cd /d "%~dp0"
if not exist .venv ( py -3 -m venv .venv && .venv\Scripts\python -m pip install -r requirements.txt )
.venv\Scripts\python -m pip install pyinstaller
.venv\Scripts\python -m PyInstaller --noconfirm packaging\gotrainer.spec || goto :error
if exist katago xcopy /E /I /Y katago dist\GoTrainer\katago
echo.
echo Готово: папка dist\GoTrainer, программа GoTrainer.exe
pause
exit /b 0
:error
echo Сборка не удалась.
pause

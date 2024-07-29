@echo off
rem Получить текущий путь, где находится скрипт
openfiles >nul 2>&1
if %errorlevel% neq 0 (
    echo Запуск с правами администратора...
    powershell start -verb runas '%~0'
    exit /b
)

set "projectPath=%~dp0"

rem Перейти в директорию проекта
cd /d "%projectPath%"

rem Активировать виртуальное окружение
call ".venv\Scripts\activate.bat"

rem Запустить Python скрипт
python client.py
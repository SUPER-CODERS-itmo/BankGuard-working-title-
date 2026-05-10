@echo off
chcp 65001 >nul
title BEN Fraud Monitor

echo.
echo  ██████╗ ███████╗███╗   ██╗
echo  ██╔══██╗██╔════╝████╗  ██║
echo  ██████╔╝█████╗  ██╔██╗ ██║
echo  ██╔══██╗██╔══╝  ██║╚██╗██║
echo  ██████╔╝███████╗██║ ╚████║
echo  ╚═════╝ ╚══════╝╚═╝  ╚═══╝
echo.
echo  Fraud Monitor — Система запуска
echo  ================================
echo.

:: Переходим в корень проекта (папка где лежит этот bat файл)
cd /d "%~dp0"

:: Проверка Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] Python не найден. Установите Python и добавьте в PATH.
    pause
    exit /b 1
)

:: Установка зависимостей если нужно
echo [1/3] Проверка зависимостей...
python -m pip install -q aiosqlite fastapi uvicorn pandas httpx aiogram aiohttp-socks >nul 2>&1
echo       Готово.

:: Проверка данных
echo [2/3] Проверка базы данных...
if not exist "data\ecosystem_data.db" (
    echo       База данных не найдена. Запускаю генерацию...
    python db_creator.py
    if errorlevel 1 (
        echo [ОШИБКА] Не удалось создать базу данных.
        pause
        exit /b 1
    )
    echo       Генерация fraud_cases_detected.csv...
    python generate_fraud_cases.py
) else (
    echo       База данных найдена.
)

if not exist "data\fraud_cases_detected.csv" (
    echo       CSV не найден. Генерирую...
    python generate_fraud_cases.py
)

echo [3/3] Запуск сервисов...
echo.

:: Устанавливаем NO_PROXY чтобы запросы к localhost не шли через VPN
set NO_PROXY=localhost,127.0.0.1

:: Запускаем API в отдельном окне
echo  ^> Запуск BEN API на http://localhost:8000 ...
start "BEN API" cmd /k "cd /d %~dp0 && python -m uvicorn api:app --port 8000"

:: Ждём секунду чтобы API успел подняться
timeout /t 2 /nobreak >nul

:: Запускаем бота в отдельном окне
echo  ^> Запуск Telegram-бота...
start "BEN Bot" cmd /k "cd /d %~dp0\bot && set NO_PROXY=localhost,127.0.0.1 && python main.py"

echo.
echo  ================================
echo  Оба сервиса запущены!
echo.
echo  API:  http://localhost:8000/docs
echo  Бот:  проверь Telegram
echo.
echo  Для остановки закрой окна BEN API и BEN Bot
echo  ================================
echo.
pause

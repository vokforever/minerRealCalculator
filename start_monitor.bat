@echo off
echo Запуск мониторинга затрат электричества...
echo.

REM Проверяем наличие Python
python --version >nul 2>&1
if errorlevel 1 (
    echo Ошибка: Python не найден в системе
    echo Установите Python и добавьте его в PATH
    pause
    exit /b 1
)

REM Проверяем наличие необходимых файлов
if not exist "electricity_monitor.py" (
    echo Ошибка: Файл electricity_monitor.py не найден
    pause
    exit /b 1
)

if not exist "devices_config.json" (
    echo Ошибка: Файл devices_config.json не найден
    pause
    exit /b 1
)

if not exist "tariff_settings.json" (
    echo Ошибка: Файл tariff_settings.json не найден
    pause
    exit /b 1
)

echo Файлы конфигурации найдены
echo.

REM Устанавливаем зависимости если нужно
echo Проверка зависимостей...
pip install -r requirements.txt >nul 2>&1
if errorlevel 1 (
    echo Предупреждение: Не удалось установить зависимости
    echo Продолжаем запуск...
)

echo.
echo Запуск мониторинга...
echo Для остановки нажмите Ctrl+C
echo.

REM Запускаем мониторинг
python electricity_monitor.py

echo.
echo Мониторинг остановлен
pause

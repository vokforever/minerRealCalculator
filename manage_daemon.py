#!/usr/bin/env python3
"""
Скрипт для управления демоном мониторинга электричества на VPS.
Позволяет запускать, останавливать, проверять статус демона.
"""

import os
import sys
import signal
import time
import json
from pathlib import Path
from datetime import datetime

def get_pid_from_file():
    """Получает PID из файла"""
    pid_file = "monitor_daemon.pid"
    if os.path.exists(pid_file):
        try:
            with open(pid_file, 'r') as f:
                return int(f.read().strip())
        except (ValueError, IOError):
            return None
    return None

def is_process_running(pid):
    """Проверяет, работает ли процесс с указанным PID"""
    if pid is None:
        return False
    
    try:
        # Отправляем сигнал 0 для проверки существования процесса
        os.kill(pid, 0)
        return True
    except OSError:
        return False

def get_process_info(pid):
    """Получает информацию о процессе"""
    if not is_process_running(pid):
        return None
    
    try:
        # Получаем время создания процесса
        stat_file = f"/proc/{pid}/stat"
        if os.path.exists(stat_file):
            with open(stat_file, 'r') as f:
                stats = f.read().split()
                if len(stats) > 21:
                    # 22-й элемент - время создания процесса в тиках
                    start_time = int(stats[21])
                    # Получаем время загрузки системы
                    with open('/proc/uptime', 'r') as f:
                        uptime = float(f.read().split()[0])
                    
                    # Рассчитываем время работы процесса
                    process_uptime = uptime - (start_time / 100)  # 100 тиков в секунду
                    return {
                        "pid": pid,
                        "uptime_seconds": process_uptime,
                        "uptime_hours": process_uptime / 3600
                    }
    except Exception:
        pass
    
    return {"pid": pid, "uptime_seconds": None, "uptime_hours": None}

def start_daemon():
    """Запускает демон"""
    pid = get_pid_from_file()
    
    if pid and is_process_running(pid):
        print(f"❌ Демон уже запущен (PID: {pid})")
        return False
    
    print("🚀 Запуск демона мониторинга...")
    
    try:
        # Запускаем демон в фоновом режиме
        import subprocess
        
        # Запускаем с nohup для работы в фоне
        cmd = [
            "nohup", 
            sys.executable, 
            "run_monitor_daemon.py"
        ]
        
        # Перенаправляем вывод в файлы
        with open("nohup.out", "w") as out, open("nohup.err", "w") as err:
            process = subprocess.Popen(
                cmd,
                stdout=out,
                stderr=err,
                start_new_session=True
            )
        
        # Ждем немного для запуска
        time.sleep(2)
        
        # Проверяем, запустился ли
        new_pid = get_pid_from_file()
        if new_pid and is_process_running(new_pid):
            print(f"✅ Демон успешно запущен (PID: {new_pid})")
            print(f"   Логи: monitor_daemon.log")
            print(f"   Вывод: nohup.out")
            print(f"   Ошибки: nohup.err")
            return True
        else:
            print("❌ Не удалось запустить демон")
            return False
            
    except Exception as e:
        print(f"❌ Ошибка запуска: {e}")
        return False

def stop_daemon():
    """Останавливает демон"""
    pid = get_pid_from_file()
    
    if not pid or not is_process_running(pid):
        print("❌ Демон не запущен")
        return False
    
    print(f"🛑 Остановка демона (PID: {pid})...")
    
    try:
        # Отправляем сигнал SIGTERM
        os.kill(pid, signal.SIGTERM)
        
        # Ждем завершения
        for i in range(10):
            if not is_process_running(pid):
                print("✅ Демон успешно остановлен")
                return True
            time.sleep(1)
        
        # Если не завершился, принудительно завершаем
        print("⚠️  Принудительное завершение...")
        os.kill(pid, signal.SIGKILL)
        time.sleep(1)
        
        if not is_process_running(pid):
            print("✅ Демон принудительно остановлен")
            return True
        else:
            print("❌ Не удалось остановить демон")
            return False
            
    except Exception as e:
        print(f"❌ Ошибка остановки: {e}")
        return False

def restart_daemon():
    """Перезапускает демон"""
    print("🔄 Перезапуск демона...")
    
    if stop_daemon():
        time.sleep(2)
        if start_daemon():
            print("✅ Демон успешно перезапущен")
            return True
        else:
            print("❌ Не удалось перезапустить демон")
            return False
    else:
        print("❌ Не удалось остановить демон для перезапуска")
        return False

def show_status():
    """Показывает статус демона"""
    print("=" * 60)
    print("СТАТУС ДЕМОНА МОНИТОРИНГА ЭЛЕКТРИЧЕСТВА")
    print("=" * 60)
    
    pid = get_pid_from_file()
    
    if pid and is_process_running(pid):
        print(f"🟢 Статус: ЗАПУЩЕН")
        print(f"PID: {pid}")
        
        # Получаем информацию о процессе
        process_info = get_process_info(pid)
        if process_info and process_info.get("uptime_hours"):
            print(f"Время работы: {process_info['uptime_hours']:.1f} часов")
        
        # Проверяем файлы данных
        print("\n📁 Файлы данных:")
        data_dir = Path("electricity_data")
        if data_dir.exists():
            current_file = data_dir / "current_electricity_data.json"
            historical_file = data_dir / "historical_electricity_data.json"
            
            if current_file.exists():
                try:
                    with open(current_file, 'r') as f:
                        data = json.load(f)
                    size = current_file.stat().st_size
                    records = data.get("total_records", 0)
                    last_update = data.get("last_update", "N/A")
                    print(f"  ✅ Текущие данные: {size} байт, {records} записей")
                    print(f"     Последнее обновление: {last_update}")
                except Exception as e:
                    print(f"  ❌ Ошибка чтения текущих данных: {e}")
            else:
                print("  ❌ Файл текущих данных не найден")
            
            if historical_file.exists():
                try:
                    with open(historical_file, 'r') as f:
                        data = json.load(f)
                    size = historical_file.stat().st_size
                    pending = data.get("total_pending", 0)
                    last_sync = data.get("last_sync", "N/A")
                    print(f"  ✅ Исторические данные: {size} байт, {pending} ожидают")
                    print(f"     Последняя синхронизация: {last_sync}")
                except Exception as e:
                    print(f"  ❌ Ошибка чтения исторических данных: {e}")
            else:
                print("  ❌ Файл исторических данных не найден")
        else:
            print("  ❌ Директория данных не найдена")
        
        # Проверяем логи
        print("\n📋 Логи:")
        log_files = [
            "monitor_daemon.log",
            "electricity_monitor.log",
            "nohup.out",
            "nohup.err"
        ]
        
        for log_file in log_files:
            if os.path.exists(log_file):
                size = os.path.getsize(log_file)
                mtime = datetime.fromtimestamp(os.path.getmtime(log_file))
                print(f"  ✅ {log_file}: {size} байт, изменен: {mtime.strftime('%Y-%m-%d %H:%M:%S')}")
            else:
                print(f"  ❌ {log_file}: не найден")
    
    else:
        print("🔴 Статус: ОСТАНОВЛЕН")
        print("PID: не найден")
        
        # Проверяем, есть ли PID файл
        if os.path.exists("monitor_daemon.pid"):
            print("⚠️  Обнаружен устаревший PID файл")
    
    print("=" * 60)

def show_logs(lines=50):
    """Показывает последние строки логов"""
    log_file = "monitor_daemon.log"
    
    if not os.path.exists(log_file):
        print(f"❌ Файл логов {log_file} не найден")
        return
    
    print(f"\n📋 Последние {lines} строк логов ({log_file}):")
    print("-" * 60)
    
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            all_lines = f.readlines()
            last_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
            
            for line in last_lines:
                print(line.rstrip())
                
    except Exception as e:
        print(f"❌ Ошибка чтения логов: {e}")

def cleanup():
    """Очищает устаревшие файлы"""
    print("🧹 Очистка устаревших файлов...")
    
    # Удаляем устаревший PID файл если процесс не работает
    pid = get_pid_from_file()
    if pid and not is_process_running(pid):
        try:
            os.remove("monitor_daemon.pid")
            print("✅ Удален устаревший PID файл")
        except Exception as e:
            print(f"⚠️  Не удалось удалить PID файл: {e}")
    
    # Проверяем размер логов
    log_files = ["monitor_daemon.log", "nohup.out", "nohup.err"]
    for log_file in log_files:
        if os.path.exists(log_file):
            size_mb = os.path.getsize(log_file) / (1024 * 1024)
            if size_mb > 10:  # Больше 10 МБ
                print(f"⚠️  Лог файл {log_file} большой: {size_mb:.1f} МБ")
                print("   Рекомендуется очистка или ротация")

def main():
    """Основная функция"""
    if len(sys.argv) < 2:
        print("Использование:")
        print("  python manage_daemon.py <команда>")
        print("\nКоманды:")
        print("  start     - Запустить демон")
        print("  stop      - Остановить демон")
        print("  restart   - Перезапустить демон")
        print("  status    - Показать статус")
        print("  logs      - Показать логи")
        print("  cleanup   - Очистить устаревшие файлы")
        return
    
    command = sys.argv[1].lower()
    
    if command == "start":
        start_daemon()
    elif command == "stop":
        stop_daemon()
    elif command == "restart":
        restart_daemon()
    elif command == "status":
        show_status()
    elif command == "logs":
        lines = int(sys.argv[2]) if len(sys.argv) > 2 else 50
        show_logs(lines)
    elif command == "cleanup":
        cleanup()
    else:
        print(f"❌ Неизвестная команда: {command}")
        print("Используйте: start, stop, restart, status, logs, cleanup")

if __name__ == "__main__":
    main()

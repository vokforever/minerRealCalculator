#!/usr/bin/env python3
"""
Скрипт для настройки автоматического запуска мониторинга электричества при загрузке VPS.
Создает systemd сервис для автоматического управления.
"""

import os
import sys
import subprocess
from pathlib import Path

def check_root():
    """Проверяет, запущен ли скрипт от root"""
    if os.geteuid() != 0:
        print("❌ Этот скрипт должен быть запущен от имени root")
        print("   Используйте: sudo python setup_autostart.py")
        return False
    return True

def get_current_directory():
    """Получает текущую рабочую директорию"""
    return os.getcwd()

def create_systemd_service(working_dir):
    """Создает systemd сервис"""
    service_name = "electricity-monitor"
    service_content = f"""[Unit]
Description=Electricity Monitor Daemon
After=network.target
Wants=network.target

[Service]
Type=simple
User=root
WorkingDirectory={working_dir}
ExecStart={sys.executable} {working_dir}/run_monitor_daemon.py
Restart=always
RestartSec=30
StandardOutput=journal
StandardError=journal
SyslogIdentifier=electricity-monitor

# Ограничения ресурсов
MemoryMax=512M
CPUQuota=50%

# Переменные окружения
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
"""
    
    service_file = f"/etc/systemd/system/{service_name}.service"
    
    try:
        with open(service_file, 'w') as f:
            f.write(service_content)
        
        print(f"✅ Создан systemd сервис: {service_file}")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка создания сервиса: {e}")
        return False

def create_logrotate_config():
    """Создает конфигурацию logrotate для ротации логов"""
    config_content = """# Ротация логов мониторинга электричества
/root/minerRealCalculator/*.log {
    daily
    missingok
    rotate 7
    compress
    delaycompress
    notifempty
    create 644 root root
    postrotate
        systemctl reload electricity-monitor >/dev/null 2>&1 || true
    endscript
}

/root/minerRealCalculator/nohup.out {
    daily
    missingok
    rotate 3
    compress
    delaycompress
    notifempty
    create 644 root root
}

/root/minerRealCalculator/nohup.err {
    daily
    missingok
    rotate 3
    compress
    delaycompress
    notifempty
    create 644 root root
}
"""
    
    config_file = "/etc/logrotate.d/electricity-monitor"
    
    try:
        with open(config_file, 'w') as f:
            f.write(config_content)
        
        print(f"✅ Создана конфигурация logrotate: {config_file}")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка создания logrotate: {e}")
        return False

def create_cron_jobs():
    """Создает cron задачи для обслуживания"""
    cron_content = """# Обслуживание мониторинга электричества
# Очистка старых данных каждые 7 дней в 2:00
0 2 * * 0 cd /root/minerRealCalculator && python manage_daemon.py cleanup >/dev/null 2>&1

# Проверка статуса каждые 6 часов
0 */6 * * * cd /root/minerRealCalculator && python manage_daemon.py status >/dev/null 2>&1

# Перезапуск сервиса каждые 24 часа в 3:00 (если нужно)
# 0 3 * * * systemctl restart electricity-monitor >/dev/null 2>&1
"""
    
    # Создаем временный файл
    temp_cron = "/tmp/electricity-monitor-cron"
    
    try:
        with open(temp_cron, 'w') as f:
            f.write(cron_content)
        
        # Добавляем в crontab
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True
        )
        
        current_cron = result.stdout if result.returncode == 0 else ""
        
        # Проверяем, есть ли уже наши задачи
        if "electricity-monitor" not in current_cron:
            # Добавляем новые задачи
            with open(temp_cron, 'r') as f:
                new_cron = f.read()
            
            # Объединяем существующие и новые задачи
            combined_cron = current_cron + "\n" + new_cron
            
            # Создаем временный файл с объединенным содержимым
            temp_combined = "/tmp/combined-cron"
            with open(temp_combined, 'w') as f:
                f.write(combined_cron)
            
            # Обновляем crontab
            subprocess.run(["crontab", temp_combined], check=True)
            
            # Удаляем временные файлы
            os.remove(temp_cron)
            os.remove(temp_combined)
            
            print("✅ Добавлены cron задачи")
        else:
            print("ℹ️  Cron задачи уже существуют")
            os.remove(temp_cron)
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка создания cron задач: {e}")
        if os.path.exists(temp_cron):
            os.remove(temp_cron)
        return False

def enable_and_start_service():
    """Включает и запускает systemd сервис"""
    try:
        # Перезагружаем systemd
        subprocess.run(["systemctl", "daemon-reload"], check=True)
        print("✅ Systemd перезагружен")
        
        # Включаем автозапуск
        subprocess.run(["systemctl", "enable", "electricity-monitor"], check=True)
        print("✅ Сервис включен для автозапуска")
        
        # Запускаем сервис
        subprocess.run(["systemctl", "start", "electricity-monitor"], check=True)
        print("✅ Сервис запущен")
        
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Ошибка systemd: {e}")
        return False
    except Exception as e:
        print(f"❌ Неожиданная ошибка: {e}")
        return False

def show_status():
    """Показывает статус сервиса"""
    try:
        print("\n📊 Статус сервиса:")
        subprocess.run(["systemctl", "status", "electricity-monitor"], check=False)
        
        print("\n📋 Последние логи:")
        subprocess.run(["journalctl", "-u", "electricity-monitor", "-n", "10", "--no-pager"], check=False)
        
    except Exception as e:
        print(f"❌ Ошибка получения статуса: {e}")

def create_management_script():
    """Создает удобный скрипт управления"""
    script_content = """#!/bin/bash
# Скрипт управления мониторингом электричества

case "$1" in
    start)
        systemctl start electricity-monitor
        echo "✅ Мониторинг запущен"
        ;;
    stop)
        systemctl stop electricity-monitor
        echo "🛑 Мониторинг остановлен"
        ;;
    restart)
        systemctl restart electricity-monitor
        echo "🔄 Мониторинг перезапущен"
        ;;
    status)
        systemctl status electricity-monitor
        ;;
    logs)
        journalctl -u electricity-monitor -f
        ;;
    enable)
        systemctl enable electricity-monitor
        echo "✅ Автозапуск включен"
        ;;
    disable)
        systemctl disable electricity-monitor
        echo "❌ Автозапуск отключен"
        ;;
    *)
        echo "Использование: $0 {start|stop|restart|status|logs|enable|disable}"
        exit 1
        ;;
esac
"""
    
    script_file = "/usr/local/bin/electricity-monitor"
    
    try:
        with open(script_file, 'w') as f:
            f.write(script_content)
        
        # Делаем исполняемым
        os.chmod(script_file, 0o755)
        
        print(f"✅ Создан скрипт управления: {script_file}")
        print("   Использование: electricity-monitor {start|stop|restart|status|logs|enable|disable}")
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка создания скрипта управления: {e}")
        return False

def main():
    """Основная функция"""
    print("🚀 Настройка автоматического запуска мониторинга электричества")
    print("=" * 70)
    
    # Проверяем права root
    if not check_root():
        sys.exit(1)
    
    # Получаем текущую директорию
    working_dir = get_current_directory()
    print(f"📁 Рабочая директория: {working_dir}")
    
    # Проверяем наличие необходимых файлов
    required_files = [
        "run_monitor_daemon.py",
        "electricity_monitor.py",
        "devices_config.json",
        "tariff_settings.json"
    ]
    
    missing_files = []
    for file_path in required_files:
        if not Path(file_path).exists():
            missing_files.append(file_path)
    
    if missing_files:
        print(f"❌ Отсутствуют необходимые файлы: {', '.join(missing_files)}")
        print("   Убедитесь, что все файлы находятся в текущей директории")
        sys.exit(1)
    
    print("✅ Все необходимые файлы найдены")
    
    # Создаем systemd сервис
    print("\n🔧 Создание systemd сервиса...")
    if not create_systemd_service(working_dir):
        sys.exit(1)
    
    # Создаем конфигурацию logrotate
    print("\n📋 Настройка ротации логов...")
    if not create_logrotate_config():
        print("⚠️  Продолжаем без logrotate...")
    
    # Создаем cron задачи
    print("\n⏰ Настройка cron задач...")
    if not create_cron_jobs():
        print("⚠️  Продолжаем без cron...")
    
    # Создаем скрипт управления
    print("\n🛠️  Создание скрипта управления...")
    if not create_management_script():
        print("⚠️  Продолжаем без скрипта управления...")
    
    # Включаем и запускаем сервис
    print("\n🚀 Включение и запуск сервиса...")
    if not enable_and_start_service():
        print("❌ Не удалось запустить сервис")
        print("   Проверьте логи: journalctl -u electricity-monitor")
        sys.exit(1)
    
    # Показываем статус
    print("\n" + "=" * 70)
    print("🎉 Настройка завершена успешно!")
    print("=" * 70)
    
    show_status()
    
    print("\n📝 Инструкции по использованию:")
    print("   Запуск: systemctl start electricity-monitor")
    print("   Остановка: systemctl stop electricity-monitor")
    print("   Статус: systemctl status electricity-monitor")
    print("   Логи: journalctl -u electricity-monitor -f")
    print("   Или используйте: electricity-monitor {start|stop|restart|status|logs}")
    
    print("\n🔍 Проверка работы:")
    print("   python manage_daemon.py status")
    print("   ls -la electricity_data/")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⏹️  Настройка прервана пользователем")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Критическая ошибка: {e}")
        sys.exit(1)

#!/usr/bin/env python3
"""
Скрипт для запуска мониторинга затрат электричества как демона на VPS.
Автоматически перезапускается при сбоях и работает в фоновом режиме.
"""

import os
import sys
import time
import logging
import signal
import atexit
from pathlib import Path
from datetime import datetime

# Настройка логирования
log_file = "monitor_daemon.log"
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class MonitorDaemon:
    """Демон для мониторинга электричества на VPS"""
    
    def __init__(self):
        self.running = False
        self.monitor_process = None
        self.restart_count = 0
        self.max_restarts = 10
        self.restart_delay = 30  # секунды
        
        # Регистрируем обработчики сигналов
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
        atexit.register(self.cleanup)
        
        logger.info("Демон мониторинга инициализирован")
    
    def _signal_handler(self, signum, frame):
        """Обработчик сигналов для корректного завершения"""
        logger.info(f"Получен сигнал {signum}, завершение работы...")
        self.stop()
        sys.exit(0)
    
    def start_monitor(self):
        """Запускает процесс мониторинга"""
        try:
            logger.info("Запуск процесса мониторинга...")
            
            # Импортируем и запускаем мониторинг
            from electricity_monitor import ElectricityMonitor
            
            # Создаем монитор
            self.monitor = ElectricityMonitor(
                devices_config_path="devices_config.json",
                tariff_settings_path="tariff_settings.json"
            )
            
            # Запускаем мониторинг
            self.monitor.start_monitoring()
            self.running = True
            self.restart_count = 0
            
            logger.info("Мониторинг успешно запущен")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка запуска мониторинга: {e}")
            return False
    
    def stop(self):
        """Останавливает демон"""
        logger.info("Остановка демона мониторинга...")
        self.running = False
        
        if hasattr(self, 'monitor') and self.monitor:
            try:
                self.monitor.stop_monitoring()
                logger.info("Мониторинг остановлен")
            except Exception as e:
                logger.error(f"Ошибка остановки мониторинга: {e}")
    
    def cleanup(self):
        """Очистка при завершении"""
        logger.info("Выполняется очистка...")
        self.stop()
    
    def run(self):
        """Основной цикл демона"""
        logger.info("Демон мониторинга запущен")
        
        while True:
            try:
                if not self.running:
                    # Запускаем мониторинг
                    if self.start_monitor():
                        logger.info("Мониторинг запущен, ожидание...")
                        
                        # Ждем завершения или сбоя
                        while self.running:
                            time.sleep(10)
                            
                            # Проверяем статус мониторинга
                            if hasattr(self, 'monitor'):
                                try:
                                    # Проверяем, что мониторинг активен
                                    if not self.monitor.monitoring_active:
                                        logger.warning("Мониторинг неактивен, перезапуск...")
                                        break
                                except Exception as e:
                                    logger.error(f"Ошибка проверки статуса: {e}")
                                    break
                    else:
                        # Не удалось запустить
                        if self.restart_count < self.max_restarts:
                            self.restart_count += 1
                            logger.warning(f"Попытка перезапуска {self.restart_count}/{self.max_restarts}")
                            time.sleep(self.restart_delay)
                        else:
                            logger.error("Превышено максимальное количество перезапусков")
                            break
                else:
                    time.sleep(1)
                    
            except KeyboardInterrupt:
                logger.info("Получен сигнал прерывания")
                break
            except Exception as e:
                logger.error(f"Критическая ошибка в демоне: {e}")
                time.sleep(10)
        
        logger.info("Демон завершает работу")
        self.cleanup()


def create_pid_file():
    """Создает PID файл для управления демоном"""
    pid = os.getpid()
    pid_file = "monitor_daemon.pid"
    
    try:
        with open(pid_file, 'w') as f:
            f.write(str(pid))
        logger.info(f"PID файл создан: {pid_file} (PID: {pid})")
        return pid_file
    except Exception as e:
        logger.error(f"Ошибка создания PID файла: {e}")
        return None


def remove_pid_file(pid_file):
    """Удаляет PID файл"""
    if pid_file and os.path.exists(pid_file):
        try:
            os.remove(pid_file)
            logger.info("PID файл удален")
        except Exception as e:
            logger.error(f"Ошибка удаления PID файла: {e}")


def main():
    """Основная функция"""
    logger.info("=" * 60)
    logger.info("ЗАПУСК МОНИТОРИНГА ЭЛЕКТРИЧЕСТВА")
    logger.info("=" * 60)
    
    # Проверяем наличие необходимых файлов
    required_files = [
        "electricity_monitor.py",
        "devices_config.json", 
        "tariff_settings.json"
    ]
    
    missing_files = []
    for file_path in required_files:
        if not Path(file_path).exists():
            missing_files.append(file_path)
    
    if missing_files:
        logger.error(f"Отсутствуют необходимые файлы: {', '.join(missing_files)}")
        logger.error("Убедитесь, что все файлы находятся в текущей директории")
        return 1
    
    logger.info("Все необходимые файлы найдены")
    
    # Создаем PID файл
    pid_file = create_pid_file()
    
    try:
        # Создаем и запускаем демон
        daemon = MonitorDaemon()
        daemon.run()
        
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        return 1
    
    finally:
        # Удаляем PID файл при завершении
        if 'pid_file' in locals():
            remove_pid_file(pid_file)
    
    return 0


if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("Программа прервана пользователем")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Неожиданная ошибка: {e}")
        sys.exit(1)

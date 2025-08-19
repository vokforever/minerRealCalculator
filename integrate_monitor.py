#!/usr/bin/env python3
"""
Скрипт для интеграции мониторинга затрат электричества в основную программу.
Запускает мониторинг как отдельный процесс для обеспечения надежности.
"""

import os
import sys
import time
import logging
import subprocess
import signal
import json
from pathlib import Path
from datetime import datetime

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
    handlers=[
        logging.FileHandler('monitor_integration.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class MonitorIntegration:
    """Интеграция мониторинга электричества с основной программой"""
    
    def __init__(self, 
                 monitor_script: str = "electricity_monitor.py",
                 devices_config: str = "devices_config.json",
                 tariff_settings: str = "tariff_settings.json"):
        """
        Инициализация интеграции
        
        Args:
            monitor_script: Путь к скрипту мониторинга
            devices_config: Путь к конфигурации устройств
            tariff_settings: Путь к настройкам тарифов
        """
        self.monitor_script = Path(monitor_script)
        self.devices_config = Path(devices_config)
        self.tariff_settings = Path(tariff_settings)
        
        # Проверяем существование файлов
        self._validate_files()
        
        # Процесс мониторинга
        self.monitor_process = None
        self.monitor_pid = None
        
        # Статус
        self.is_running = False
        
        # Настройки перезапуска
        self.restart_on_failure = True
        self.max_restart_attempts = 5
        self.restart_delay = 60  # секунды
        self.restart_attempts = 0
        
        # Сигналы для корректного завершения
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _validate_files(self):
        """Проверяет существование необходимых файлов"""
        required_files = [
            self.monitor_script,
            self.devices_config,
            self.tariff_settings
        ]
        
        missing_files = []
        for file_path in required_files:
            if not file_path.exists():
                missing_files.append(str(file_path))
        
        if missing_files:
            error_msg = f"Отсутствуют необходимые файлы: {', '.join(missing_files)}"
            logger.error(error_msg)
            raise FileNotFoundError(error_msg)
        
        logger.info("Все необходимые файлы найдены")
    
    def start_monitor(self):
        """Запускает процесс мониторинга"""
        if self.is_running:
            logger.warning("Мониторинг уже запущен")
            return False
        
        try:
            logger.info("Запуск процесса мониторинга электричества...")
            
            # Команда для запуска мониторинга
            cmd = [
                sys.executable,
                str(self.monitor_script),
                "--devices", str(self.devices_config),
                "--tariffs", str(self.tariff_settings)
            ]
            
            # Запускаем процесс
            self.monitor_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            self.monitor_pid = self.monitor_process.pid
            self.is_running = True
            self.restart_attempts = 0
            
            logger.info(f"Мониторинг запущен с PID: {self.monitor_pid}")
            
            # Запускаем мониторинг процесса
            self._start_process_monitoring()
            
            return True
            
        except Exception as e:
            logger.error(f"Ошибка запуска мониторинга: {e}")
            return False
    
    def stop_monitor(self):
        """Останавливает процесс мониторинга"""
        if not self.is_running:
            logger.warning("Мониторинг не запущен")
            return
        
        try:
            logger.info("Остановка процесса мониторинга...")
            
            if self.monitor_process:
                # Отправляем сигнал SIGTERM
                self.monitor_process.terminate()
                
                # Ждем завершения процесса
                try:
                    self.monitor_process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    logger.warning("Процесс не завершился, принудительно завершаем...")
                    self.monitor_process.kill()
                    self.monitor_process.wait()
                
                self.monitor_process = None
                self.monitor_pid = None
            
            self.is_running = False
            logger.info("Мониторинг остановлен")
            
        except Exception as e:
            logger.error(f"Ошибка остановки мониторинга: {e}")
    
    def _start_process_monitoring(self):
        """Запускает мониторинг процесса в отдельном потоке"""
        import threading
        
        def monitor_process():
            while self.is_running:
                try:
                    if self.monitor_process:
                        # Проверяем статус процесса
                        return_code = self.monitor_process.poll()
                        
                        if return_code is not None:
                            # Процесс завершился
                            logger.warning(f"Процесс мониторинга завершился с кодом: {return_code}")
                            
                            # Получаем вывод для диагностики
                            stdout, stderr = self.monitor_process.communicate()
                            if stdout:
                                logger.info(f"STDOUT: {stdout}")
                            if stderr:
                                logger.error(f"STDERR: {stderr}")
                            
                            # Перезапускаем если необходимо
                            if self.restart_on_failure and self.restart_attempts < self.max_restart_attempts:
                                self.restart_attempts += 1
                                logger.info(f"Попытка перезапуска {self.restart_attempts}/{self.max_restart_attempts}")
                                
                                time.sleep(self.restart_delay)
                                self.start_monitor()
                            else:
                                logger.error("Превышено максимальное количество попыток перезапуска")
                                self.is_running = False
                                break
                    
                    time.sleep(5)  # Проверяем каждые 5 секунд
                    
                except Exception as e:
                    logger.error(f"Ошибка мониторинга процесса: {e}")
                    time.sleep(10)
        
        # Запускаем мониторинг в отдельном потоке
        monitor_thread = threading.Thread(target=monitor_process, daemon=True)
        monitor_thread.start()
        
        logger.info("Мониторинг процесса запущен")
    
    def get_status(self) -> dict:
        """Получает статус мониторинга"""
        status = {
            "is_running": self.is_running,
            "pid": self.monitor_pid,
            "restart_attempts": self.restart_attempts,
            "max_restart_attempts": self.max_restart_attempts,
            "uptime": None
        }
        
        if self.is_running and self.monitor_process:
            try:
                # Получаем время работы процесса
                import psutil
                process = psutil.Process(self.monitor_pid)
                create_time = process.create_time()
                uptime = time.time() - create_time
                status["uptime"] = uptime
            except Exception as e:
                logger.debug(f"Не удалось получить время работы процесса: {e}")
        
        return status
    
    def get_electricity_stats(self) -> dict:
        """Получает статистику потребления электричества"""
        try:
            # Проверяем файлы данных
            data_dir = Path("electricity_data")
            current_data_file = data_dir / "current_electricity_data.json"
            historical_data_file = data_dir / "historical_electricity_data.json"
            
            stats = {
                "monitor_status": "stopped",
                "data_files": {},
                "last_update": None,
                "total_records": 0,
                "pending_sync": 0
            }
            
            if self.is_running:
                stats["monitor_status"] = "running"
            
            # Читаем данные из файлов
            if current_data_file.exists():
                try:
                    with open(current_data_file, 'r', encoding='utf-8') as f:
                        current_data = json.load(f)
                    
                    stats["data_files"]["current"] = {
                        "exists": True,
                        "size": current_data_file.stat().st_size,
                        "last_update": current_data.get("last_update"),
                        "total_records": current_data.get("total_records", 0)
                    }
                    stats["last_update"] = current_data.get("last_update")
                    stats["total_records"] = current_data.get("total_records", 0)
                    
                except Exception as e:
                    logger.error(f"Ошибка чтения текущих данных: {e}")
                    stats["data_files"]["current"] = {"exists": True, "error": str(e)}
            
            if historical_data_file.exists():
                try:
                    with open(historical_data_file, 'r', encoding='utf-8') as f:
                        historical_data = json.load(f)
                    
                    stats["data_files"]["historical"] = {
                        "exists": True,
                        "size": historical_data_file.stat().st_size,
                        "last_sync": historical_data.get("last_sync"),
                        "total_pending": historical_data.get("total_pending", 0)
                    }
                    stats["pending_sync"] = historical_data.get("total_pending", 0)
                    
                except Exception as e:
                    logger.error(f"Ошибка чтения исторических данных: {e}")
                    stats["data_files"]["historical"] = {"exists": True, "error": str(e)}
            
            return stats
            
        except Exception as e:
            logger.error(f"Ошибка получения статистики: {e}")
            return {"error": str(e)}
    
    def manual_sync(self):
        """Запускает ручную синхронизацию с Supabase"""
        if not self.is_running:
            logger.warning("Мониторинг не запущен, синхронизация недоступна")
            return False
        
        try:
            # Отправляем сигнал процессу для ручной синхронизации
            if self.monitor_process and self.monitor_pid:
                import psutil
                process = psutil.Process(self.monitor_pid)
                
                # Отправляем SIGUSR1 для ручной синхронизации
                process.send_signal(signal.SIGUSR1)
                logger.info("Отправлен сигнал для ручной синхронизации")
                return True
            else:
                logger.error("Процесс мониторинга недоступен")
                return False
                
        except Exception as e:
            logger.error(f"Ошибка ручной синхронизации: {e}")
            return False
    
    def _signal_handler(self, signum, frame):
        """Обработчик сигналов для корректного завершения"""
        logger.info(f"Получен сигнал {signum}, завершение работы...")
        self.stop_monitor()
        sys.exit(0)


def main():
    """Основная функция"""
    try:
        # Создаем интеграцию
        integration = MonitorIntegration()
        
        # Запускаем мониторинг
        if integration.start_monitor():
            logger.info("Интеграция мониторинга запущена")
            
            # Основной цикл
            try:
                while True:
                    # Показываем статус каждые 5 минут
                    time.sleep(300)
                    
                    status = integration.get_status()
                    stats = integration.get_electricity_stats()
                    
                    logger.info(f"Статус: {status}")
                    logger.info(f"Статистика: {stats}")
                    
            except KeyboardInterrupt:
                logger.info("Получен сигнал остановки...")
        
        else:
            logger.error("Не удалось запустить мониторинг")
            return 1
        
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        return 1
    
    finally:
        # Останавливаем мониторинг при завершении
        if 'integration' in locals():
            integration.stop_monitor()
    
    return 0


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)

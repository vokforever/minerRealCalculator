import os
import json
import time
import logging
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
import schedule
from pathlib import Path

# Настройка логирования
logger = logging.getLogger(__name__)

@dataclass
class ElectricityRecord:
    """Запись о потреблении электричества"""
    timestamp: str
    device_id: str
    device_name: str
    location: str
    power_w: float
    energy_kwh: float
    is_on: bool
    voltage: Optional[float] = None
    current: Optional[float] = None
    cost_rub: Optional[float] = None
    day_energy_kwh: Optional[float] = None
    night_energy_kwh: Optional[float] = None

class ElectricityMonitor:
    """Монитор затрат электричества с сохранением в JSON и синхронизацией с Supabase"""
    
    def __init__(self, 
                 devices_config_path: str,
                 tariff_settings_path: str,
                 data_dir: str = "electricity_data",
                 sync_interval_hours: int = 12):
        """
        Инициализация монитора
        
        Args:
            devices_config_path: Путь к конфигурации устройств
            tariff_settings_path: Путь к настройкам тарифов
            data_dir: Директория для хранения JSON файлов
            sync_interval_hours: Интервал синхронизации с Supabase в часах
        """
        self.devices_config_path = devices_config_path
        self.tariff_settings_path = tariff_settings_path
        self.data_dir = Path(data_dir)
        self.sync_interval_hours = sync_interval_hours
        
        # Создаем директорию для данных если её нет
        self.data_dir.mkdir(exist_ok=True)
        
        # Загружаем конфигурации
        self.devices = self._load_devices_config()
        self.tariff_settings = self._load_tariff_settings()
        
        # Состояние мониторинга
        self.monitoring_active = False
        self.monitor_thread = None
        
        # Кэш последних показаний для расчета потребления
        self.last_counters = {}
        self.last_timestamps = {}
        
        # Файл для текущих данных
        self.current_data_file = self.data_dir / "current_electricity_data.json"
        self.historical_data_file = self.data_dir / "historical_electricity_data.json"
        
        # Инициализируем файлы данных
        self._init_data_files()
        
        # Импортируем необходимые модули
        self._import_dependencies()
        
    def _import_dependencies(self):
        """Импортирует необходимые зависимости"""
        try:
            from main import (
                get_device_status_cloud_enhanced,
                calculate_session_cost,
                supabase
            )
            self.get_device_status = get_device_status_cloud_enhanced
            self.calculate_session_cost = calculate_session_cost
            self.supabase = supabase
            self.dependencies_loaded = True
            logger.info("Зависимости успешно загружены")
        except ImportError as e:
            logger.warning(f"Не удалось загрузить зависимости: {e}")
            self.dependencies_loaded = False
    
    def _load_devices_config(self) -> List[Dict]:
        """Загружает конфигурацию устройств"""
        try:
            with open(self.devices_config_path, 'r', encoding='utf-8') as f:
                devices = json.load(f)
            logger.info(f"Загружена конфигурация для {len(devices)} устройств")
            return devices
        except Exception as e:
            logger.error(f"Ошибка загрузки конфигурации устройств: {e}")
            return []
    
    def _load_tariff_settings(self) -> Dict:
        """Загружает настройки тарифов"""
        try:
            with open(self.tariff_settings_path, 'r', encoding='utf-8') as f:
                tariffs = json.load(f)
            logger.info(f"Загружены тарифные настройки для локаций: {list(tariffs.keys())}")
            return tariffs
        except Exception as e:
            logger.error(f"Ошибка загрузки тарифных настроек: {e}")
            return {}
    
    def _init_data_files(self):
        """Инициализирует файлы данных"""
        # Файл текущих данных (каждые 5 минут)
        if not self.current_data_file.exists():
            initial_data = {
                "last_update": datetime.now().isoformat(),
                "records": [],
                "total_records": 0
            }
            self._save_json(self.current_data_file, initial_data)
            logger.info(f"Создан файл текущих данных: {self.current_data_file}")
        
        # Файл исторических данных (для синхронизации с Supabase)
        if not self.historical_data_file.exists():
            initial_historical = {
                "last_sync": datetime.now().isoformat(),
                "pending_records": [],
                "total_pending": 0
            }
            self._save_json(self.historical_data_file, initial_historical)
            logger.info(f"Создан файл исторических данных: {self.historical_data_file}")
    
    def _save_json(self, file_path: Path, data: Dict):
        """Сохраняет данные в JSON файл"""
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        except Exception as e:
            logger.error(f"Ошибка сохранения в {file_path}: {e}")
    
    def _load_json(self, file_path: Path) -> Dict:
        """Загружает данные из JSON файла"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка загрузки из {file_path}: {e}")
            return {}
    
    def _calculate_energy_consumption(self, device_id: str, current_counter: float) -> float:
        """Рассчитывает потребление энергии с момента последнего измерения"""
        if device_id not in self.last_counters:
            self.last_counters[device_id] = current_counter
            return 0.0
        
        last_counter = self.last_counters[device_id]
        energy_kwh = current_counter - last_counter
        
        # Обновляем последний счетчик
        self.last_counters[device_id] = current_counter
        
        # Возвращаем только положительные значения
        return max(0.0, energy_kwh)
    
    def _calculate_cost(self, location: str, energy_kwh: float, 
                       day_energy_kwh: float, night_energy_kwh: float) -> float:
        """Рассчитывает стоимость потребления"""
        if location not in self.tariff_settings:
            logger.warning(f"Тарифы для локации {location} не найдены")
            return 0.0
        
        location_tariff = self.tariff_settings[location]
        tariff_type = location_tariff.get("tariff_type", "single")
        ranges = location_tariff.get("ranges", [{}])[0] if location_tariff.get("ranges") else {}
        
        if tariff_type == "day_night":
            day_rate = ranges.get("day_rate", 4.82)
            night_rate = ranges.get("night_rate", 3.39)
            cost = (day_energy_kwh * day_rate) + (night_energy_kwh * night_rate)
        else:
            day_rate = ranges.get("day_rate", 4.82)
            cost = energy_kwh * day_rate
        
        return cost
    
    def _split_energy_by_zones(self, energy_kwh: float, timestamp: datetime) -> tuple:
        """Разделяет энергию на дневную и ночную зоны"""
        hour = timestamp.hour
        
        # Дневной тариф: 7:00 - 23:00
        if 7 <= hour < 23:
            day_energy = energy_kwh
            night_energy = 0.0
        else:
            day_energy = 0.0
            night_energy = energy_kwh
        
        return day_energy, night_energy
    
    def record_electricity_data(self):
        """Записывает данные о потреблении электричества каждые 5 минут"""
        if not self.dependencies_loaded:
            logger.warning("Зависимости не загружены, пропуск записи")
            return
        
        logger.info("Запись данных о потреблении электричества...")
        current_time = datetime.now()
        records = []
        
        for device in self.devices:
            try:
                device_id = device["device_id"]
                device_name = device["name"]
                location = device["location"]
                
                # Получаем статус устройства
                is_on, counter, device_data = self.get_device_status(device_id)
                
                if device_data is None:
                    logger.warning(f"Не удалось получить данные для устройства {device_name}")
                    continue
                
                # Получаем текущую мощность
                power_w = device_data.get('cur_power', 0.0)
                voltage = device_data.get('cur_voltage')
                current = device_data.get('cur_current')
                
                # Рассчитываем потребление энергии
                energy_kwh = self._calculate_energy_consumption(device_id, counter)
                
                # Разделяем на дневную и ночную зоны
                day_energy, night_energy = self._split_energy_by_zones(energy_kwh, current_time)
                
                # Рассчитываем стоимость
                cost_rub = self._calculate_cost(location, energy_kwh, day_energy, night_energy)
                
                # Создаем запись
                record = ElectricityRecord(
                    timestamp=current_time.isoformat(),
                    device_id=device_id,
                    device_name=device_name,
                    location=location,
                    power_w=power_w,
                    energy_kwh=energy_kwh,
                    is_on=is_on,
                    voltage=voltage,
                    current=current,
                    cost_rub=cost_rub,
                    day_energy_kwh=day_energy,
                    night_energy_kwh=night_energy
                )
                
                records.append(asdict(record))
                
                logger.debug(f"Записаны данные для {device_name}: мощность={power_w}Вт, "
                           f"энергия={energy_kwh:.3f}кВт·ч, стоимость={cost_rub:.2f}руб")
                
            except Exception as e:
                logger.error(f"Ошибка записи данных для устройства {device.get('name', 'Unknown')}: {e}")
        
        if records:
            # Сохраняем в файл текущих данных
            self._save_current_data(records)
            
            # Добавляем в исторические данные для синхронизации
            self._add_to_historical_data(records)
            
            logger.info(f"Записаны данные для {len(records)} устройств")
        else:
            logger.warning("Нет данных для записи")
    
    def _save_current_data(self, records: List[Dict]):
        """Сохраняет текущие данные в JSON файл"""
        try:
            current_data = self._load_json(self.current_data_file)
            
            # Добавляем новые записи
            current_data["records"].extend(records)
            current_data["last_update"] = datetime.now().isoformat()
            current_data["total_records"] = len(current_data["records"])
            
            # Ограничиваем количество записей (храним последние 1000)
            max_records = 1000
            if len(current_data["records"]) > max_records:
                current_data["records"] = current_data["records"][-max_records:]
                current_data["total_records"] = len(current_data["records"])
                logger.info(f"Ограничено количество записей до {max_records}")
            
            self._save_json(self.current_data_file, current_data)
            
        except Exception as e:
            logger.error(f"Ошибка сохранения текущих данных: {e}")
    
    def _add_to_historical_data(self, records: List[Dict]):
        """Добавляет записи в исторические данные для синхронизации"""
        try:
            historical_data = self._load_json(self.historical_data_file)
            
            # Добавляем новые записи
            historical_data["pending_records"].extend(records)
            historical_data["total_pending"] = len(historical_data["pending_records"])
            
            self._save_json(self.historical_data_file, historical_data)
            
        except Exception as e:
            logger.error(f"Ошибка добавления в исторические данные: {e}")
    
    def sync_with_supabase(self):
        """Синхронизирует данные с Supabase"""
        if not self.dependencies_loaded:
            logger.warning("Зависимости не загружены, пропуск синхронизации")
            return
        
        logger.info("Начало синхронизации с Supabase...")
        
        try:
            historical_data = self._load_json(self.historical_data_file)
            pending_records = historical_data.get("pending_records", [])
            
            if not pending_records:
                logger.info("Нет данных для синхронизации")
                return
            
            logger.info(f"Синхронизация {len(pending_records)} записей...")
            
            # Группируем записи по устройствам для создания сессий
            device_sessions = {}
            
            for record in pending_records:
                device_id = record["device_id"]
                if device_id not in device_sessions:
                    device_sessions[device_id] = []
                device_sessions[device_id].append(record)
            
            # Создаем сессии для каждого устройства
            synced_count = 0
            for device_id, records in device_sessions.items():
                try:
                    # Сортируем записи по времени
                    sorted_records = sorted(records, key=lambda x: x["timestamp"])
                    
                    # Создаем сессии на основе временных интервалов
                    sessions = self._create_sessions_from_records(device_id, sorted_records)
                    
                    # Сохраняем сессии в Supabase
                    for session in sessions:
                        try:
                            response = self.supabase.table("miner_energy_sessions").insert(session).execute()
                            if response.data:
                                synced_count += 1
                                logger.debug(f"Сессия синхронизирована: {session['miner_device_id']}")
                            else:
                                logger.warning(f"Пустой ответ при сохранении сессии: {session['miner_device_id']}")
                        except Exception as e:
                            logger.error(f"Ошибка сохранения сессии в Supabase: {e}")
                    
                except Exception as e:
                    logger.error(f"Ошибка обработки сессий для устройства {device_id}: {e}")
            
            # Очищаем синхронизированные записи
            if synced_count > 0:
                historical_data["pending_records"] = []
                historical_data["total_pending"] = 0
                historical_data["last_sync"] = datetime.now().isoformat()
                self._save_json(self.historical_data_file, historical_data)
                
                logger.info(f"Успешно синхронизировано {synced_count} сессий с Supabase")
            else:
                logger.warning("Не удалось синхронизировать данные с Supabase")
                
        except Exception as e:
            logger.error(f"Ошибка синхронизации с Supabase: {e}")
    
    def _create_sessions_from_records(self, device_id: str, records: List[Dict]) -> List[Dict]:
        """Создает сессии из записей для сохранения в Supabase"""
        sessions = []
        
        if not records:
            return sessions
        
        # Находим информацию об устройстве
        device_info = next((d for d in self.devices if d["device_id"] == device_id), None)
        if not device_info:
            logger.warning(f"Информация об устройстве {device_id} не найдена")
            return sessions
        
        location = device_info["location"]
        
        # Группируем записи в сессии по временным интервалам
        current_session = None
        
        for record in records:
            timestamp = datetime.fromisoformat(record["timestamp"])
            
            if current_session is None:
                # Начинаем новую сессию
                current_session = {
                    "miner_device_id": device_id,
                    "miner_location": location,
                    "session_start_time": timestamp.isoformat(),
                    "session_end_time": timestamp.isoformat(),
                    "energy_kwh": record["energy_kwh"],
                    "cost_rub": record["cost_rub"],
                    "tariff_type": "day_night",  # По умолчанию
                    "day_energy_kwh": record["day_energy_kwh"],
                    "night_energy_kwh": record["night_energy_kwh"]
                }
            else:
                # Продолжаем текущую сессию
                current_session["session_end_time"] = timestamp.isoformat()
                current_session["energy_kwh"] += record["energy_kwh"]
                current_session["cost_rub"] += record["cost_rub"]
                current_session["day_energy_kwh"] += record["day_energy_kwh"]
                current_session["night_energy_kwh"] += record["night_energy_kwh"]
        
        if current_session:
            sessions.append(current_session)
        
        return sessions
    
    def start_monitoring(self):
        """Запускает мониторинг"""
        if self.monitoring_active:
            logger.warning("Мониторинг уже запущен")
            return
        
        logger.info("Запуск мониторинга затрат электричества...")
        self.monitoring_active = True
        
        # Запускаем мониторинг в отдельном потоке
        self.monitor_thread = threading.Thread(target=self._monitoring_loop, daemon=True)
        self.monitor_thread.start()
        
        # Настраиваем расписание
        self._setup_schedule()
        
        logger.info("Мониторинг запущен")
    
    def stop_monitoring(self):
        """Останавливает мониторинг"""
        if not self.monitoring_active:
            logger.warning("Мониторинг не запущен")
            return
        
        logger.info("Остановка мониторинга...")
        self.monitoring_active = False
        
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=5)
        
        logger.info("Мониторинг остановлен")
    
    def _monitoring_loop(self):
        """Основной цикл мониторинга"""
        while self.monitoring_active:
            try:
                # Записываем данные каждые 5 минут
                self.record_electricity_data()
                
                # Ждем 5 минут
                time.sleep(300)
                
            except Exception as e:
                logger.error(f"Ошибка в цикле мониторинга: {e}")
                time.sleep(60)  # Ждем минуту перед повторной попыткой
    
    def _setup_schedule(self):
        """Настраивает расписание синхронизации"""
        # Синхронизация в 6:00 и 18:00 каждый день
        schedule.every().day.at("06:00").do(self.sync_with_supabase)
        schedule.every().day.at("18:00").do(self.sync_with_supabase)
        
        # Запускаем планировщик в отдельном потоке
        def schedule_runner():
            while self.monitoring_active:
                schedule.run_pending()
                time.sleep(60)
        
        schedule_thread = threading.Thread(target=schedule_runner, daemon=True)
        schedule_thread.start()
        
        logger.info("Планировщик синхронизации запущен (6:00 и 18:00)")
    
    def get_current_stats(self) -> Dict:
        """Получает текущую статистику потребления"""
        try:
            current_data = self._load_json(self.current_data_file)
            historical_data = self._load_json(self.historical_data_file)
            
            # Рассчитываем статистику за последние 24 часа
            current_time = datetime.now()
            day_ago = current_time - timedelta(days=1)
            
            recent_records = [
                record for record in current_data.get("records", [])
                if datetime.fromisoformat(record["timestamp"]) > day_ago
            ]
            
            # Группируем по локациям
            location_stats = {}
            total_energy = 0.0
            total_cost = 0.0
            
            for record in recent_records:
                location = record["location"]
                if location not in location_stats:
                    location_stats[location] = {
                        "energy_kwh": 0.0,
                        "cost_rub": 0.0,
                        "devices": set()
                    }
                
                location_stats[location]["energy_kwh"] += record["energy_kwh"]
                location_stats[location]["cost_rub"] += record["cost_rub"]
                location_stats[location]["devices"].add(record["device_id"])
                total_energy += record["energy_kwh"]
                total_cost += record["cost_rub"]
            
            # Преобразуем set в list для JSON
            for location in location_stats:
                location_stats[location]["devices"] = list(location_stats[location]["devices"])
            
            stats = {
                "last_update": current_data.get("last_update"),
                "total_records": current_data.get("total_records", 0),
                "pending_sync": historical_data.get("total_pending", 0),
                "last_sync": historical_data.get("last_sync"),
                "last_24h": {
                    "total_energy_kwh": total_energy,
                    "total_cost_rub": total_cost,
                    "location_stats": location_stats
                }
            }
            
            return stats
            
        except Exception as e:
            logger.error(f"Ошибка получения статистики: {e}")
            return {}
    
    def manual_sync(self):
        """Ручная синхронизация с Supabase"""
        logger.info("Запуск ручной синхронизации...")
        self.sync_with_supabase()
    
    def cleanup_old_data(self, days_to_keep: int = 30):
        """Очищает старые данные"""
        try:
            current_data = self._load_json(self.current_data_file)
            historical_data = self._load_json(self.historical_data_file)
            
            cutoff_time = datetime.now() - timedelta(days=days_to_keep)
            
            # Очищаем текущие данные
            if "records" in current_data:
                filtered_records = [
                    record for record in current_data["records"]
                    if datetime.fromisoformat(record["timestamp"]) > cutoff_time
                ]
                current_data["records"] = filtered_records
                current_data["total_records"] = len(filtered_records)
                self._save_json(self.current_data_file, current_data)
            
            # Очищаем исторические данные
            if "pending_records" in historical_data:
                filtered_pending = [
                    record for record in historical_data["pending_records"]
                    if datetime.fromisoformat(record["timestamp"]) > cutoff_time
                ]
                historical_data["pending_records"] = filtered_pending
                historical_data["total_pending"] = len(filtered_pending)
                self._save_json(self.historical_data_file, historical_data)
            
            logger.info(f"Очищены данные старше {days_to_keep} дней")
            
        except Exception as e:
            logger.error(f"Ошибка очистки старых данных: {e}")


# Функция для запуска мониторинга
def start_electricity_monitoring(devices_config_path: str = "devices_config.json",
                                tariff_settings_path: str = "tariff_settings.json"):
    """Запускает мониторинг затрат электричества"""
    try:
        monitor = ElectricityMonitor(
            devices_config_path=devices_config_path,
            tariff_settings_path=tariff_settings_path
        )
        
        monitor.start_monitoring()
        
        logger.info("Мониторинг затрат электричества запущен")
        logger.info("Данные записываются каждые 5 минут")
        logger.info("Синхронизация с Supabase: 6:00 и 18:00")
        
        return monitor
        
    except Exception as e:
        logger.error(f"Ошибка запуска мониторинга: {e}")
        return None


if __name__ == "__main__":
    # Настройка логирования
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
        handlers=[
            logging.FileHandler('electricity_monitor.log'),
            logging.StreamHandler()
        ]
    )
    
    # Запускаем мониторинг
    monitor = start_electricity_monitoring()
    
    if monitor:
        try:
            # Держим программу запущенной
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            logger.info("Получен сигнал остановки...")
            monitor.stop_monitoring()
            logger.info("Мониторинг остановлен")

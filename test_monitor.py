#!/usr/bin/env python3
"""
Скрипт для тестирования системы мониторинга электричества.
Позволяет проверить работу всех компонентов без запуска полного мониторинга.
"""

import json
import time
import logging
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
    handlers=[
        logging.FileHandler('test_monitor.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def test_config_files():
    """Тестирует конфигурационные файлы"""
    print("🔧 Тестирование конфигурационных файлов...")
    
    # Проверяем devices_config.json
    try:
        with open('devices_config.json', 'r', encoding='utf-8') as f:
            devices = json.load(f)
        print(f"✅ devices_config.json: загружено {len(devices)} устройств")
        
        for device in devices:
            required_fields = ['device_id', 'name', 'location']
            missing_fields = [field for field in required_fields if field not in device]
            if missing_fields:
                print(f"⚠️  Устройство {device.get('name', 'Unknown')}: отсутствуют поля {missing_fields}")
            else:
                print(f"  ✅ {device['name']} ({device['device_id']}) в {device['location']}")
                
    except FileNotFoundError:
        print("❌ devices_config.json не найден")
        return False
    except json.JSONDecodeError as e:
        print(f"❌ Ошибка парсинга devices_config.json: {e}")
        return False
    except Exception as e:
        print(f"❌ Ошибка чтения devices_config.json: {e}")
        return False
    
    # Проверяем tariff_settings.json
    try:
        with open('tariff_settings.json', 'r', encoding='utf-8') as f:
            tariffs = json.load(f)
        print(f"✅ tariff_settings.json: загружены тарифы для {len(tariffs)} локаций")
        
        for location, tariff in tariffs.items():
            if 'tariff_type' not in tariff:
                print(f"⚠️  Локация {location}: отсутствует тип тарифа")
            elif 'ranges' not in tariff:
                print(f"⚠️  Локация {location}: отсутствуют диапазоны тарифов")
            else:
                print(f"  ✅ {location}: {tariff['tariff_type']}, {len(tariff['ranges'])} диапазонов")
                
    except FileNotFoundError:
        print("❌ tariff_settings.json не найден")
        return False
    except json.JSONDecodeError as e:
        print(f"❌ Ошибка парсинга tariff_settings.json: {e}")
        return False
    except Exception as e:
        print(f"❌ Ошибка чтения tariff_settings.json: {e}")
        return False
    
    return True


def test_dependencies():
    """Тестирует доступность зависимостей"""
    print("\n📦 Тестирование зависимостей...")
    
    dependencies = [
        ('schedule', 'schedule'),
        ('psutil', 'psutil'),
        ('supabase', 'supabase'),
        ('tinytuya', 'tinytuya'),
        ('dotenv', 'python-dotenv')
    ]
    
    all_available = True
    
    for package_name, import_name in dependencies:
        try:
            __import__(import_name)
            print(f"✅ {package_name}: доступен")
        except ImportError:
            print(f"❌ {package_name}: не установлен")
            all_available = False
    
    return all_available


def test_main_module_import():
    """Тестирует импорт основного модуля"""
    print("\n🔌 Тестирование импорта основного модуля...")
    
    try:
        # Пробуем импортировать основные функции
        from main import (
            get_device_status_cloud_enhanced,
            calculate_session_cost,
            supabase
        )
        print("✅ Основные функции main.py доступны")
        return True
    except ImportError as e:
        print(f"❌ Ошибка импорта main.py: {e}")
        return False
    except Exception as e:
        print(f"❌ Неожиданная ошибка при импорте main.py: {e}")
        return False


def test_monitor_creation():
    """Тестирует создание монитора"""
    print("\n🏗️  Тестирование создания монитора...")
    
    try:
        from electricity_monitor import ElectricityMonitor
        
        monitor = ElectricityMonitor(
            devices_config_path="devices_config.json",
            tariff_settings_path="tariff_settings.json"
        )
        
        print("✅ Монитор успешно создан")
        print(f"  Устройств: {len(monitor.devices)}")
        print(f"  Локаций: {len(monitor.tariff_settings)}")
        print(f"  Директория данных: {monitor.data_dir}")
        
        return monitor
        
    except Exception as e:
        print(f"❌ Ошибка создания монитора: {e}")
        return None


def test_data_files_creation(monitor):
    """Тестирует создание файлов данных"""
    print("\n📁 Тестирование создания файлов данных...")
    
    try:
        # Проверяем создание директории
        if monitor.data_dir.exists():
            print(f"✅ Директория {monitor.data_dir} существует")
        else:
            print(f"❌ Директория {monitor.data_dir} не создана")
            return False
        
        # Проверяем файлы данных
        current_file = monitor.current_data_file
        historical_file = monitor.historical_data_file
        
        if current_file.exists():
            print(f"✅ Файл текущих данных: {current_file}")
        else:
            print(f"❌ Файл текущих данных не создан: {current_file}")
            return False
        
        if historical_file.exists():
            print(f"✅ Файл исторических данных: {historical_file}")
        else:
            print(f"❌ Файл исторических данных не создан: {historical_file}")
            return False
        
        # Проверяем содержимое файлов
        try:
            current_data = monitor._load_json(current_file)
            historical_data = monitor._load_json(historical_file)
            
            print(f"  Текущие данные: {current_data.get('total_records', 0)} записей")
            print(f"  Исторические данные: {historical_data.get('total_pending', 0)} ожидают")
            
        except Exception as e:
            print(f"⚠️  Ошибка чтения файлов данных: {e}")
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка тестирования файлов данных: {e}")
        return False


def test_simulation(monitor):
    """Тестирует симуляцию записи данных"""
    print("\n🧪 Тестирование симуляции записи данных...")
    
    try:
        # Создаем тестовые данные
        test_records = [
            {
                "timestamp": datetime.now().isoformat(),
                "device_id": "test_device_1",
                "device_name": "Test Miner 1",
                "location": "Test Location",
                "power_w": 1500.0,
                "energy_kwh": 0.125,
                "is_on": True,
                "voltage": 220.0,
                "current": 6.8,
                "cost_rub": 0.60,
                "day_energy_kwh": 0.125,
                "night_energy_kwh": 0.0
            },
            {
                "timestamp": (datetime.now() + timedelta(minutes=5)).isoformat(),
                "device_id": "test_device_2",
                "device_name": "Test Miner 2",
                "location": "Test Location",
                "power_w": 2000.0,
                "energy_kwh": 0.167,
                "is_on": True,
                "voltage": 220.0,
                "current": 9.1,
                "cost_rub": 0.80,
                "day_energy_kwh": 0.167,
                "night_energy_kwh": 0.0
            }
        ]
        
        # Сохраняем тестовые данные
        monitor._save_current_data(test_records)
        monitor._add_to_historical_data(test_records)
        
        print("✅ Тестовые данные сохранены")
        
        # Проверяем статистику
        stats = monitor.get_current_stats()
        print(f"  Статистика: {stats.get('total_records', 0)} записей, "
              f"{stats.get('pending_sync', 0)} ожидают синхронизации")
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка симуляции: {e}")
        return False


def test_cleanup(monitor):
    """Тестирует очистку данных"""
    print("\n🧹 Тестирование очистки данных...")
    
    try:
        # Очищаем данные старше 1 дня (для тестирования)
        monitor.cleanup_old_data(days_to_keep=1)
        print("✅ Очистка данных выполнена")
        
        # Проверяем результат
        stats = monitor.get_current_stats()
        print(f"  После очистки: {stats.get('total_records', 0)} записей")
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка очистки данных: {e}")
        return False


def main():
    """Основная функция тестирования"""
    print("🚀 Запуск тестирования системы мониторинга электричества")
    print("=" * 60)
    
    # Счетчики тестов
    total_tests = 0
    passed_tests = 0
    
    # Тест 1: Конфигурационные файлы
    total_tests += 1
    if test_config_files():
        passed_tests += 1
    
    # Тест 2: Зависимости
    total_tests += 1
    if test_dependencies():
        passed_tests += 1
    
    # Тест 3: Импорт основного модуля
    total_tests += 1
    if test_main_module_import():
        passed_tests += 1
    
    # Тест 4: Создание монитора
    total_tests += 1
    monitor = test_monitor_creation()
    if monitor:
        passed_tests += 1
        
        # Тест 5: Файлы данных
        total_tests += 1
        if test_data_files_creation(monitor):
            passed_tests += 1
        
        # Тест 6: Симуляция
        total_tests += 1
        if test_simulation(monitor):
            passed_tests += 1
        
        # Тест 7: Очистка
        total_tests += 1
        if test_cleanup(monitor):
            passed_tests += 1
    
    # Результаты
    print("\n" + "=" * 60)
    print("📊 РЕЗУЛЬТАТЫ ТЕСТИРОВАНИЯ")
    print("=" * 60)
    print(f"Всего тестов: {total_tests}")
    print(f"Пройдено: {passed_tests}")
    print(f"Провалено: {total_tests - passed_tests}")
    
    if passed_tests == total_tests:
        print("🎉 Все тесты пройдены успешно!")
        print("✅ Система готова к работе")
        return True
    else:
        print("⚠️  Некоторые тесты провалены")
        print("🔧 Проверьте конфигурацию и зависимости")
        return False


if __name__ == "__main__":
    try:
        success = main()
        exit_code = 0 if success else 1
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n⏹️  Тестирование прервано пользователем")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Критическая ошибка: {e}")
        sys.exit(1)

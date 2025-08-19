#!/usr/bin/env python3
"""
Тестовый скрипт для проверки мониторинга электричества
"""

import time
import json
from datetime import datetime
from pathlib import Path

def test_electricity_data_save():
    """Тестирует сохранение данных электричества"""
    print("Тестирование сохранения данных электричества...")
    
    # Имитируем данные устройства
    test_device = {
        "device_id": "test_device_001",
        "device_name": "Test Miner",
        "location": "test_location"
    }
    
    # Имитируем данные электричества
    power_w = 1500.0
    energy_kwh = 0.125  # 5 минут при 1500Вт
    is_on = True
    voltage = 220.0
    current = 6.8
    
    # Импортируем функцию из main.py
    try:
        from main import save_electricity_data
        
        # Сохраняем данные
        save_electricity_data(
            device_id=test_device["device_id"],
            device_name=test_device["device_name"],
            location=test_device["location"],
            power_w=power_w,
            energy_kwh=energy_kwh,
            is_on=is_on,
            voltage=voltage,
            current=current
        )
        
        print("✓ Данные электричества успешно сохранены")
        
        # Проверяем созданные файлы
        data_dir = Path("electricity_data")
        current_file = data_dir / "electricity_data.json"
        history_file = data_dir / "electricity_history.json"
        
        if current_file.exists():
            with open(current_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            print(f"✓ Файл текущих данных создан: {len(data.get('records', []))} записей")
        
        if history_file.exists():
            with open(history_file, 'r', encoding='utf-8') as f:
                history = json.load(f)
            print(f"✓ Файл истории создан: {len(history.get('pending_records', []))} записей")
        
        return True
        
    except ImportError as e:
        print(f"✗ Ошибка импорта: {e}")
        return False
    except Exception as e:
        print(f"✗ Ошибка тестирования: {e}")
        return False

def test_electricity_data_structure():
    """Проверяет структуру созданных файлов"""
    print("\nПроверка структуры файлов...")
    
    try:
        data_dir = Path("electricity_data")
        current_file = data_dir / "electricity_data.json"
        history_file = data_dir / "electricity_history.json"
        
        if current_file.exists():
            with open(current_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            print("Структура файла текущих данных:")
            print(f"  - last_update: {data.get('last_update')}")
            print(f"  - total_records: {data.get('total_records')}")
            print(f"  - records: {len(data.get('records', []))} записей")
            
            if data.get('records'):
                record = data['records'][0]
                print("  Пример записи:")
                for key, value in record.items():
                    print(f"    {key}: {value}")
        
        if history_file.exists():
            with open(history_file, 'r', encoding='utf-8') as f:
                history = json.load(f)
            
            print("\nСтруктура файла истории:")
            print(f"  - last_sync: {history.get('last_sync')}")
            print(f"  - total_pending: {history.get('total_pending')}")
            print(f"  - pending_records: {len(history.get('pending_records', []))} записей")
        
        return True
        
    except Exception as e:
        print(f"✗ Ошибка проверки структуры: {e}")
        return False

def simulate_multiple_readings():
    """Имитирует несколько измерений для тестирования"""
    print("\nИмитация нескольких измерений...")
    
    try:
        from main import save_electricity_data
        
        test_device = {
            "device_id": "test_device_002",
            "device_name": "Test Miner 2",
            "location": "test_location_2"
        }
        
        # Имитируем несколько измерений
        for i in range(3):
            power_w = 1500.0 + (i * 100)  # Разная мощность
            energy_kwh = 0.125 + (i * 0.025)  # Разное потребление
            is_on = True
            voltage = 220.0 + (i * 2)  # Разное напряжение
            current = 6.8 + (i * 0.2)  # Разный ток
            
            save_electricity_data(
                device_id=test_device["device_id"],
                device_name=test_device["device_name"],
                location=test_device["location"],
                power_w=power_w,
                energy_kwh=energy_kwh,
                is_on=is_on,
                voltage=voltage,
                current=current
            )
            
            print(f"  Измерение {i+1}: мощность={power_w}Вт, энергия={energy_kwh:.3f}кВт·ч")
            time.sleep(1)  # Небольшая пауза
        
        print("✓ Имитация измерений завершена")
        return True
        
    except Exception as e:
        print(f"✗ Ошибка имитации: {e}")
        return False

def main():
    """Основная функция тестирования"""
    print("=" * 50)
    print("ТЕСТИРОВАНИЕ МОНИТОРИНГА ЭЛЕКТРИЧЕСТВА")
    print("=" * 50)
    
    # Тест 1: Сохранение данных
    if not test_electricity_data_save():
        print("Тест 1 провален")
        return
    
    # Тест 2: Проверка структуры
    if not test_electricity_data_structure():
        print("Тест 2 провален")
        return
    
    # Тест 3: Имитация измерений
    if not simulate_multiple_readings():
        print("Тест 3 провален")
        return
    
    print("\n" + "=" * 50)
    print("ВСЕ ТЕСТЫ ПРОЙДЕНЫ УСПЕШНО!")
    print("=" * 50)
    print("\nФайлы созданы в директории 'electricity_data/':")
    print("  - electricity_data.json - текущие данные")
    print("  - electricity_history.json - данные для синхронизации")
    print("\nДанные будут синхронизироваться с Supabase в 6:00 и 18:00")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Тестовый скрипт для проверки команд мониторинга электроэнергии
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Добавляем текущую директорию в путь
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Загружаем переменные окружения
load_dotenv()

# Настраиваем логирование
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_electricity_today():
    """Тестирует функцию получения данных о потреблении за сегодня"""
    logger.info("Тестирование функции получения данных за сегодня...")
    
    try:
        from main import get_today_spending
        
        today_stats = get_today_spending()
        
        if today_stats:
            logger.info("✅ Данные за сегодня получены успешно")
            logger.info(f"   Количество локаций: {len(today_stats)}")
            
            for location, stats in today_stats.items():
                logger.info(f"   📍 {location}:")
                logger.info(f"      Энергия: {stats.get('total_energy', 0):.3f} кВт·ч")
                logger.info(f"      Стоимость: {stats.get('total_cost', 0):.2f} RUB")
                logger.info(f"      Источник: {stats.get('source', 'Unknown')}")
                
                if stats.get('devices'):
                    logger.info(f"      Устройств: {len(stats['devices'])}")
            
            return True
        else:
            logger.warning("⚠️ Данные за сегодня не найдены")
            return True  # Не считаем ошибкой отсутствие данных
            
    except Exception as e:
        logger.error(f"❌ Ошибка тестирования функции за сегодня: {e}")
        return False

def test_electricity_72h():
    """Тестирует функцию получения данных о потреблении за 72 часа"""
    logger.info("Тестирование функции получения данных за 72 часа...")
    
    try:
        from main import get_72h_consumption_from_api
        
        # Тестируем для каждой локации
        from main import DEVICES
        locations = set(device["location"] for device in DEVICES)
        
        if not locations:
            logger.warning("⚠️ Нет настроенных локаций")
            return True
        
        for location in locations:
            logger.info(f"   Тестирование локации: {location}")
            api_data = get_72h_consumption_from_api(location)
            
            if api_data['total_energy'] > 0:
                logger.info(f"      ✅ API данные получены: {api_data['total_energy']:.3f} кВт·ч")
                logger.info(f"      Стоимость: {api_data['total_cost']:.2f} RUB")
                logger.info(f"      День: {api_data['day_energy']:.3f} кВт·ч")
                logger.info(f"      Ночь: {api_data['night_energy']:.3f} кВт·ч")
            else:
                logger.info(f"      ⚠️ API данные не получены для {location}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка тестирования функции за 72 часа: {e}")
        return False

def test_energy_data_function():
    """Тестирует функцию получения данных из базы"""
    logger.info("Тестирование функции получения данных из базы...")
    
    try:
        from main import get_energy_data
        
        end_date = datetime.now()
        start_date = end_date - timedelta(hours=72)
        
        energy_data = get_energy_data(start_date, end_date)
        
        if energy_data:
            logger.info(f"✅ Данные из базы получены: {len(energy_data)} записей")
            
            # Группируем по локациям
            location_stats = {}
            for session in energy_data:
                location = session.get("miner_location", "Unknown")
                if location not in location_stats:
                    location_stats[location] = {"count": 0, "total_energy": 0}
                
                location_stats[location]["count"] += 1
                location_stats[location]["total_energy"] += session.get("energy_kwh", 0)
            
            for location, stats in location_stats.items():
                logger.info(f"   📍 {location}: {stats['count']} записей, {stats['total_energy']:.3f} кВт·ч")
        else:
            logger.info("ℹ️ Данные из базы не найдены (это нормально для новых установок)")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка тестирования функции базы данных: {e}")
        return False

def test_device_configuration():
    """Тестирует конфигурацию устройств"""
    logger.info("Тестирование конфигурации устройств...")
    
    try:
        from main import DEVICES
        
        if DEVICES:
            logger.info(f"✅ Найдено {len(DEVICES)} устройств")
            
            for device in DEVICES:
                logger.info(f"   🖥️ {device['name']} ({device['device_id']})")
                logger.info(f"      Локация: {device['location']}")
                logger.info(f"      Активно: {device.get('is_active', True)}")
        else:
            logger.warning("⚠️ Устройства не настроены")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка тестирования конфигурации устройств: {e}")
        return False

def main():
    """Основная функция тестирования"""
    logger.info("🚀 Начало тестирования команд мониторинга электроэнергии")
    
    tests = [
        ("Конфигурация устройств", test_device_configuration),
        ("Функция за сегодня", test_electricity_today),
        ("Функция за 72 часа", test_electricity_72h),
        ("Функция базы данных", test_energy_data_function)
    ]
    
    results = []
    
    for test_name, test_func in tests:
        logger.info(f"\n{'='*50}")
        logger.info(f"Тест: {test_name}")
        logger.info(f"{'='*50}")
        
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            logger.error(f"Критическая ошибка в тесте {test_name}: {e}")
            results.append((test_name, False))
    
    # Выводим итоговые результаты
    logger.info(f"\n{'='*50}")
    logger.info("ИТОГОВЫЕ РЕЗУЛЬТАТЫ ТЕСТИРОВАНИЯ")
    logger.info(f"{'='*50}")
    
    passed = 0
    total = len(results)
    
    for test_name, result in results:
        status = "✅ ПРОЙДЕН" if result else "❌ ПРОВАЛЕН"
        logger.info(f"{test_name}: {status}")
        if result:
            passed += 1
    
    logger.info(f"\nРезультат: {passed}/{total} тестов пройдено")
    
    if passed == total:
        logger.info("🎉 Все тесты пройдены успешно!")
        return True
    else:
        logger.warning(f"⚠️ {total - passed} тестов не пройдено")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

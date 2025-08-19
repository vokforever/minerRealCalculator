#!/usr/bin/env python3
"""
Скрипт для управления мониторингом затрат электричества.
Позволяет запускать, останавливать, проверять статус и управлять мониторингом.
"""

import argparse
import sys
import json
import time
from pathlib import Path
from datetime import datetime

# Импортируем модуль мониторинга
try:
    from electricity_monitor import ElectricityMonitor
    from integrate_monitor import MonitorIntegration
except ImportError as e:
    print(f"Ошибка импорта модулей: {e}")
    print("Убедитесь, что файлы electricity_monitor.py и integrate_monitor.py находятся в текущей директории")
    sys.exit(1)


def show_status(integration: MonitorIntegration):
    """Показывает статус мониторинга"""
    print("=" * 60)
    print("СТАТУС МОНИТОРИНГА ЭЛЕКТРИЧЕСТВА")
    print("=" * 60)
    
    # Статус процесса
    status = integration.get_status()
    print(f"Статус: {'🟢 ЗАПУЩЕН' if status['is_running'] else '🔴 ОСТАНОВЛЕН'}")
    
    if status['is_running']:
        print(f"PID: {status['pid']}")
        if status['uptime']:
            uptime_hours = status['uptime'] / 3600
            print(f"Время работы: {uptime_hours:.1f} часов")
        print(f"Попытки перезапуска: {status['restart_attempts']}/{status['max_restart_attempts']}")
    else:
        print("Процесс не запущен")
    
    print()
    
    # Статистика данных
    stats = integration.get_electricity_stats()
    print("СТАТИСТИКА ДАННЫХ:")
    print(f"Статус монитора: {stats.get('monitor_status', 'unknown')}")
    print(f"Последнее обновление: {stats.get('last_update', 'N/A')}")
    print(f"Всего записей: {stats.get('total_records', 0)}")
    print(f"Ожидают синхронизации: {stats.get('pending_sync', 0)}")
    
    # Информация о файлах
    if 'data_files' in stats:
        print("\nФАЙЛЫ ДАННЫХ:")
        for file_type, file_info in stats['data_files'].items():
            if file_info.get('exists'):
                print(f"  {file_type}: ✅ {file_info.get('size', 0)} байт")
                if file_type == 'current':
                    print(f"    Последнее обновление: {file_info.get('last_update', 'N/A')}")
                    print(f"    Записей: {file_info.get('total_records', 0)}")
                elif file_type == 'historical':
                    print(f"    Последняя синхронизация: {file_info.get('last_sync', 'N/A')}")
                    print(f"    Ожидают: {file_info.get('total_pending', 0)}")
            else:
                print(f"  {file_type}: ❌ не найден")
    
    print("=" * 60)


def show_recent_data(monitor: ElectricityMonitor, hours: int = 24):
    """Показывает недавние данные потребления"""
    try:
        stats = monitor.get_current_stats()
        
        print(f"\nДАННЫЕ ЗА ПОСЛЕДНИЕ {hours} ЧАСОВ:")
        print("-" * 40)
        
        if 'last_24h' in stats:
            last_24h = stats['last_24h']
            print(f"Общее потребление: {last_24h.get('total_energy_kwh', 0):.3f} кВт·ч")
            print(f"Общая стоимость: {last_24h.get('total_cost_rub', 0):.2f} руб.")
            
            if 'location_stats' in last_24h:
                print("\nПо локациям:")
                for location, loc_stats in last_24h['location_stats'].items():
                    print(f"  {location}:")
                    print(f"    Энергия: {loc_stats.get('energy_kwh', 0):.3f} кВт·ч")
                    print(f"    Стоимость: {loc_stats.get('cost_rub', 0):.2f} руб.")
                    print(f"    Устройств: {len(loc_stats.get('devices', []))}")
        else:
            print("Данные недоступны")
            
    except Exception as e:
        print(f"Ошибка получения данных: {e}")


def show_file_contents(file_path: str, max_lines: int = 20):
    """Показывает содержимое файла данных"""
    try:
        file_path = Path(file_path)
        if not file_path.exists():
            print(f"Файл {file_path} не найден")
            return
        
        print(f"\nСОДЕРЖИМОЕ ФАЙЛА: {file_path}")
        print("-" * 50)
        
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Показываем структуру
        if isinstance(data, dict):
            print("Структура файла:")
            for key, value in data.items():
                if isinstance(value, list):
                    print(f"  {key}: список из {len(value)} элементов")
                elif isinstance(value, dict):
                    print(f"  {key}: словарь с ключами {list(value.keys())}")
                else:
                    print(f"  {key}: {value}")
            
            # Показываем последние записи если есть
            if 'records' in data and data['records']:
                print(f"\nПоследние {min(max_lines, len(data['records']))} записей:")
                for i, record in enumerate(data['records'][-max_lines:]):
                    print(f"  {i+1}. {record.get('timestamp', 'N/A')} - "
                          f"{record.get('device_name', 'Unknown')}: "
                          f"{record.get('energy_kwh', 0):.3f} кВт·ч")
        
    except Exception as e:
        print(f"Ошибка чтения файла: {e}")


def main():
    """Основная функция"""
    parser = argparse.ArgumentParser(
        description="Управление мониторингом затрат электричества",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  python manage_monitor.py start          # Запустить мониторинг
  python manage_monitor.py stop           # Остановить мониторинг
  python manage_monitor.py status         # Показать статус
  python manage_monitor.py sync           # Ручная синхронизация
  python manage_monitor.py data           # Показать данные
  python manage_monitor.py files          # Показать содержимое файлов
        """
    )
    
    parser.add_argument('action', choices=['start', 'stop', 'status', 'sync', 'data', 'files'],
                       help='Действие для выполнения')
    
    parser.add_argument('--devices', default='devices_config.json',
                       help='Путь к конфигурации устройств (по умолчанию: devices_config.json)')
    
    parser.add_argument('--tariffs', default='tariff_settings.json',
                       help='Путь к настройкам тарифов (по умолчанию: tariff_settings.json)')
    
    parser.add_argument('--hours', type=int, default=24,
                       help='Количество часов для показа данных (по умолчанию: 24)')
    
    parser.add_argument('--max-lines', type=int, default=20,
                       help='Максимальное количество строк для показа (по умолчанию: 20)')
    
    args = parser.parse_args()
    
    try:
        # Создаем интеграцию
        integration = MonitorIntegration(
            monitor_script="electricity_monitor.py",
            devices_config=args.devices,
            tariff_settings=args.tariffs
        )
        
        if args.action == 'start':
            print("Запуск мониторинга...")
            if integration.start_monitor():
                print("✅ Мониторинг успешно запущен")
                show_status(integration)
            else:
                print("❌ Не удалось запустить мониторинг")
                sys.exit(1)
        
        elif args.action == 'stop':
            print("Остановка мониторинга...")
            integration.stop_monitor()
            print("✅ Мониторинг остановлен")
        
        elif args.action == 'status':
            show_status(integration)
        
        elif args.action == 'sync':
            if integration.is_running:
                print("Запуск ручной синхронизации...")
                if integration.manual_sync():
                    print("✅ Сигнал синхронизации отправлен")
                else:
                    print("❌ Не удалось запустить синхронизацию")
            else:
                print("❌ Мониторинг не запущен, синхронизация недоступна")
        
        elif args.action == 'data':
            if integration.is_running:
                # Создаем монитор для получения данных
                monitor = ElectricityMonitor(
                    devices_config_path=args.devices,
                    tariff_settings_path=args.tariffs
                )
                show_recent_data(monitor, args.hours)
            else:
                print("❌ Мониторинг не запущен, данные недоступны")
        
        elif args.action == 'files':
            print("СОДЕРЖИМОЕ ФАЙЛОВ ДАННЫХ:")
            
            # Показываем текущие данные
            current_file = Path("electricity_data/current_electricity_data.json")
            if current_file.exists():
                show_file_contents(str(current_file), args.max_lines)
            else:
                print("Файл текущих данных не найден")
            
            # Показываем исторические данные
            historical_file = Path("electricity_data/historical_electricity_data.json")
            if historical_file.exists():
                show_file_contents(str(historical_file), args.max_lines)
            else:
                print("Файл исторических данных не найден")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

# Система мониторинга затрат электричества

Система для автоматического мониторинга затрат электричества майнинг-фермы с записью данных каждые 5 минут и синхронизацией с Supabase 2 раза в день.

## 🚀 Основные возможности

- **Автоматическая запись данных каждые 5 минут** - обеспечивает непрерывность данных даже при сбоях серверов
- **Локальное хранение в JSON** - экономит ресурсы Supabase и обеспечивает надежность
- **Автоматическая синхронизация с Supabase** - 2 раза в день (6:00 и 18:00)
- **Расчет стоимости по тарифам** - поддержка дневных/ночных тарифов и диапазонов потребления
- **Мониторинг процесса** - автоматический перезапуск при сбоях
- **Управление через командную строку** - простые команды для управления

## 📁 Структура файлов

```
minerRealCalculator/
├── electricity_monitor.py      # Основной модуль мониторинга
├── integrate_monitor.py        # Интеграция с основной программой
├── manage_monitor.py           # Скрипт управления через командную строку
├── electricity_data/           # Директория для JSON файлов
│   ├── current_electricity_data.json    # Текущие данные (каждые 5 мин)
│   └── historical_electricity_data.json # Данные для синхронизации
├── devices_config.json         # Конфигурация устройств
├── tariff_settings.json        # Настройки тарифов
└── requirements.txt            # Зависимости Python
```

## 🔧 Установка и настройка

### 1. Установка зависимостей

```bash
pip install -r requirements.txt
```

### 2. Проверка конфигурации

Убедитесь, что у вас есть файлы:
- `devices_config.json` - конфигурация устройств Tuya
- `tariff_settings.json` - настройки тарифов
- `.env` - переменные окружения для Supabase и Tuya

### 3. Структура конфигурации устройств

```json
[
  {
    "device_id": "your_device_id",
    "name": "Device Name",
    "location": "Location Name"
  }
]
```

### 4. Структура тарифных настроек

```json
{
  "Location Name": {
    "tariff_type": "day_night",
    "ranges": [
      {
        "min_kwh": 0,
        "max_kwh": 150,
        "day_rate": 4.82,
        "night_rate": 3.39
      }
    ]
  }
}
```

## 🚀 Использование

### Запуск мониторинга

```bash
# Запуск через интеграцию
python integrate_monitor.py

# Или через скрипт управления
python manage_monitor.py start
```

### Управление через командную строку

```bash
# Показать статус
python manage_monitor.py status

# Запустить мониторинг
python manage_monitor.py start

# Остановить мониторинг
python manage_monitor.py stop

# Ручная синхронизация с Supabase
python manage_monitor.py sync

# Показать данные за последние 24 часа
python manage_monitor.py data

# Показать содержимое файлов данных
python manage_monitor.py files

# Показать данные за указанное количество часов
python manage_monitor.py data --hours 48

# Показать больше строк в файлах
python manage_monitor.py files --max-lines 50
```

### Прямой запуск мониторинга

```bash
python electricity_monitor.py
```

## 📊 Структура данных

### Запись о потреблении (ElectricityRecord)

```python
@dataclass
class ElectricityRecord:
    timestamp: str           # Время записи (ISO format)
    device_id: str          # ID устройства
    device_name: str        # Имя устройства
    location: str           # Локация
    power_w: float         # Текущая мощность (Вт)
    energy_kwh: float      # Потребление энергии (кВт·ч)
    is_on: bool            # Статус включения
    voltage: float         # Напряжение (В)
    current: float         # Ток (А)
    cost_rub: float        # Стоимость (руб)
    day_energy_kwh: float  # Дневное потребление
    night_energy_kwh: float # Ночное потребление
```

### Файл текущих данных

```json
{
  "last_update": "2024-01-01T12:00:00",
  "records": [
    {
      "timestamp": "2024-01-01T12:00:00",
      "device_id": "device_1",
      "device_name": "Miner 1",
      "location": "Location 1",
      "power_w": 1500.0,
      "energy_kwh": 0.125,
      "is_on": true,
      "cost_rub": 0.60,
      "day_energy_kwh": 0.125,
      "night_energy_kwh": 0.0
    }
  ],
  "total_records": 1
}
```

### Файл исторических данных

```json
{
  "last_sync": "2024-01-01T06:00:00",
  "pending_records": [],
  "total_pending": 0
}
```

## ⚙️ Настройки

### Интервалы записи и синхронизации

- **Запись данных**: каждые 5 минут
- **Синхронизация с Supabase**: 6:00 и 18:00 каждый день
- **Очистка старых данных**: по умолчанию через 30 дней

### Настройка через код

```python
from electricity_monitor import ElectricityMonitor

monitor = ElectricityMonitor(
    devices_config_path="devices_config.json",
    tariff_settings_path="tariff_settings.json",
    data_dir="electricity_data",           # Директория для данных
    sync_interval_hours=12                # Интервал синхронизации
)

# Запуск мониторинга
monitor.start_monitoring()

# Ручная синхронизация
monitor.manual_sync()

# Получение статистики
stats = monitor.get_current_stats()

# Очистка старых данных
monitor.cleanup_old_data(days_to_keep=30)
```

## 🔍 Мониторинг и диагностика

### Логи

- `electricity_monitor.log` - логи мониторинга
- `monitor_integration.log` - логи интеграции
- `mining_calculator.log` - логи основной программы

### Проверка статуса

```bash
# Статус процесса
python manage_monitor.py status

# Проверка файлов данных
ls -la electricity_data/

# Просмотр логов
tail -f electricity_monitor.log
```

### Автоматический перезапуск

Система автоматически перезапускает мониторинг при сбоях:
- Максимум 5 попыток перезапуска
- Задержка 60 секунд между попытками
- Логирование всех попыток перезапуска

## 🚨 Обработка ошибок

### Типичные проблемы и решения

1. **Зависимости не загружены**
   - Проверьте наличие `main.py` и его функций
   - Убедитесь в корректности импортов

2. **Ошибки подключения к Tuya API**
   - Проверьте настройки в `.env`
   - Проверьте лимиты API запросов

3. **Ошибки Supabase**
   - Проверьте подключение к базе данных
   - Проверьте права доступа к таблицам

4. **Проблемы с файлами данных**
   - Проверьте права доступа к директории
   - Проверьте свободное место на диске

### Восстановление после сбоя

```bash
# Остановка мониторинга
python manage_monitor.py stop

# Проверка статуса
python manage_monitor.py status

# Запуск мониторинга
python manage_monitor.py start

# Проверка данных
python manage_monitor.py data
```

## 📈 Интеграция с основной программой

### Автоматический запуск

Добавьте в `main.py`:

```python
from electricity_monitor import ElectricityMonitor

# В функции main() или при инициализации
electricity_monitor = ElectricityMonitor()
electricity_monitor.start_monitoring()
```

### Получение данных в основной программе

```python
# Получение статистики потребления
stats = electricity_monitor.get_current_stats()

# Ручная синхронизация
electricity_monitor.manual_sync()

# Очистка старых данных
electricity_monitor.cleanup_old_data()
```

## 🔒 Безопасность

- Данные сохраняются локально в JSON файлах
- Синхронизация с Supabase через защищенное соединение
- Логирование всех операций для аудита
- Автоматическая очистка старых данных

## 📝 Лицензия

Система интегрирована в основной проект minerRealCalculator.

## 🤝 Поддержка

При возникновении проблем:
1. Проверьте логи в соответствующих файлах
2. Используйте команду `python manage_monitor.py status`
3. Проверьте конфигурацию устройств и тарифов
4. Убедитесь в доступности Tuya API и Supabase

## 🔄 Обновления

Для обновления системы:
1. Остановите мониторинг: `python manage_monitor.py stop`
2. Обновите файлы кода
3. Перезапустите мониторинг: `python manage_monitor.py start`
4. Проверьте статус: `python manage_monitor.py status`

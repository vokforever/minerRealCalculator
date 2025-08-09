import os
from dotenv import load_dotenv
import tinytuya
import time
import json
from datetime import datetime, date

# Загрузить переменные из .env файла
load_dotenv()

TUYA_ACCESS_ID = os.getenv("TUYA_ACCESS_ID")
TUYA_ACCESS_SECRET = os.getenv("TUYA_ACCESS_SECRET")
TUYA_API_URL = os.getenv("TUYA_API_URL")

if not all([TUYA_ACCESS_ID, TUYA_ACCESS_SECRET, TUYA_API_URL]):
    raise ValueError("Одна или несколько переменных окружения не заданы в .env файле!")

# Подключение к Tuya Cloud
c = tinytuya.Cloud(
    apiRegion="eu",
    apiKey=TUYA_ACCESS_ID,
    apiSecret=TUYA_ACCESS_SECRET
)

# ID устройств для мониторинга
DEVICE_IDS = [
    {"id": "bf421b4b994bed8190bxrg", "name": "4060rig"},
    {"id": "bfbc32c786cf0519a2pt6g", "name": "RIG2 nvidia pavlenko"}
]

# Файл для хранения данных
DATA_FILE = "electricity_data.json"
MONTHLY_BASE_FILE = "monthly_base.json"


# Функция для получения данных об электричестве
def get_electricity_data(device_id, device_name):
    try:
        status = c.getstatus(device_id)
        if status.get('success'):
            result = status.get('result', [])

            # Ищем нужные параметры в ответе
            cur_power = None
            add_ele = None
            cur_voltage = None
            cur_current = None

            for item in result:
                if item.get('code') == 'cur_power':
                    cur_power = item.get('value')
                elif item.get('code') == 'add_ele':
                    add_ele = item.get('value')
                elif item.get('code') == 'cur_voltage':
                    cur_voltage = item.get('value')
                elif item.get('code') == 'cur_current':
                    cur_current = item.get('value')

            # Корректировка значений согласно информации из GitHub issues
            # Значения мощности и напряжения могут приходить в деци-единицах (умноженными на 10)
            if cur_power is not None and cur_power > 1000:
                cur_power = cur_power / 10  # Переводим из дециватт в ватты

            if cur_voltage is not None and cur_voltage > 1000:
                cur_voltage = cur_voltage / 10  # Переводим из децивольт в вольты

            if cur_current is not None:
                cur_current = cur_current / 1000  # Переводим из миллиампер в амперы

            # Формируем результат
            data = {
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'device_id': device_id,
                'device_name': device_name,
                'current_power_w': cur_power,
                'current_voltage_v': cur_voltage,
                'current_current_a': cur_current,
                'total_energy_kwh': add_ele
            }

            return data
        else:
            print(f"Ошибка получения статуса для устройства {device_name} ({device_id}): {status}")
            return None
    except Exception as e:
        print(f"Исключение при получении данных для устройства {device_name} ({device_id}): {str(e)}")
        return None


# Функция для инициализации или обновления базовых значений для месячного расчета
def init_monthly_base():
    today = date.today()
    current_month = today.strftime("%Y-%m")

    # Проверяем наличие файла с базовыми значениями
    if os.path.exists(MONTHLY_BASE_FILE):
        with open(MONTHLY_BASE_FILE, 'r', encoding='utf-8') as f:
            monthly_data = json.load(f)

        # Проверяем, не начался ли новый месяц
        if monthly_data.get('month') == current_month:
            return monthly_data

    # Если файла нет или начался новый месяц, создаем/обновляем базовые значения
    print(f"Инициализация базовых значений для месяца {current_month}")
    monthly_data = {
        'month': current_month,
        'devices': {}
    }

    # Получаем текущие значения общего расхода для всех устройств
    for device in DEVICE_IDS:
        device_id = device['id']
        device_name = device['name']

        data = get_electricity_data(device_id, device_name)
        if data and data['total_energy_kwh'] is not None:
            monthly_data['devices'][device_id] = {
                'name': device_name,
                'base_energy': data['total_energy_kwh']
            }
            print(f"Установлено базовое значение для {device_name}: {data['total_energy_kwh']} кВт*ч")

    # Сохраняем базовые значения
    with open(MONTHLY_BASE_FILE, 'w', encoding='utf-8') as f:
        json.dump(monthly_data, f, ensure_ascii=False, indent=2)

    return monthly_data


# Функция для расчета месячного расхода
def calculate_monthly_usage(device_id, current_energy, monthly_data):
    if device_id not in monthly_data['devices']:
        return None

    base_energy = monthly_data['devices'][device_id]['base_energy']
    if base_energy is None or current_energy is None:
        return None

    # Расчет месячного расхода
    monthly_usage = current_energy - base_energy
    return max(0, monthly_usage)  # Убедимся, что значение не отрицательное


# Функция для расчета примерной стоимости потребления
def calculate_cost(power_kw, hours_per_month=24 * 30, rate_per_kwh=5.5):  # 5.5 рублей за кВт*ч
    if power_kw is None:
        return None
    monthly_consumption = power_kw * hours_per_month
    return monthly_consumption * rate_per_kwh


# Функция для сохранения данных в файл
def save_data_to_file(data, filename=DATA_FILE):
    try:
        # Загружаем существующие данные, если файл есть
        existing_data = []
        if os.path.exists(filename):
            with open(filename, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)

        # Добавляем новые данные
        existing_data.append(data)

        # Сохраняем обновленные данные
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(existing_data, f, ensure_ascii=False, indent=2)

        print(f"Данные сохранены в файл {filename}")
    except Exception as e:
        print(f"Ошибка сохранения данных в файл: {str(e)}")


# Функция для вывода данных в консоль
def print_data(data, monthly_usage):
    print(f"\n[{data['timestamp']}] {data['device_name']} ({data['device_id']}):")
    print(f"  Текущая мощность: {data['current_power_w']} Вт ({data['current_power_w'] / 1000:.3f} кВт)")

    if data['current_voltage_v'] is not None:
        print(f"  Напряжение: {data['current_voltage_v']:.1f} В")

    if data['current_current_a'] is not None:
        print(f"  Ток: {data['current_current_a']:.2f} А")

    print(f"  Общий расход: {data['total_energy_kwh']} кВт*ч")

    if monthly_usage is not None:
        print(f"  Расход за месяц: {monthly_usage:.3f} кВт*ч")

        # Расчет примерной стоимости
        if data['current_power_w'] is not None and data['current_power_w'] > 0:
            cost = calculate_cost(data['current_power_w'] / 1000)
            print(f"  Примерная стоимость в месяц: {cost:.2f} руб.")
    else:
        print("  Расход за месяц: нет данных")


# Основная функция для мониторинга
def monitor_electricity():
    print("Начало мониторинга расхода электричества...")
    print(f"Мониторинг устройств: {[dev['name'] for dev in DEVICE_IDS]}")
    print("Данные будут обновляться каждые 10 минут")

    # Инициализируем базовые значения для месячного расчета
    monthly_data = init_monthly_base()

    while True:
        try:
            # В начале каждого месяца обновляем базовые значения
            today = date.today()
            current_month = today.strftime("%Y-%m")
            if monthly_data.get('month') != current_month:
                print(f"Обнаружен новый месяц {current_month}, обновляем базовые значения...")
                monthly_data = init_monthly_base()

            for device in DEVICE_IDS:
                data = get_electricity_data(device['id'], device['name'])
                if data:
                    # Рассчитываем месячный расход
                    monthly_usage = calculate_monthly_usage(device['id'], data['total_energy_kwh'], monthly_data)

                    # Выводим данные
                    print_data(data, monthly_usage)

                    # Сохраняем данные
                    save_data_to_file(data)

            # Ждем 10 минут (600 секунд)
            print("\nОжидание 10 минут до следующего замера...")
            time.sleep(600)
        except KeyboardInterrupt:
            print("\nМониторинг остановлен пользователем")
            break
        except Exception as e:
            print(f"Ошибка в основном цикле: {str(e)}")
            time.sleep(60)  # Ждем минуту перед повторной попыткой


if __name__ == "__main__":
    monitor_electricity()
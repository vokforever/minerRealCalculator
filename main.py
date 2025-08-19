import os
import time
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
from supabase import create_client, Client
from dotenv import load_dotenv
import tinytuya
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.enums import ParseMode
from functools import wraps
from threading import Lock
from pycoingecko import CoinGeckoAPI
import numpy as np
from openai import OpenAI
from cerebras.cloud.sdk import Cerebras

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
    handlers=[
        logging.FileHandler('mining_calculator.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv()

# Tuya Cloud настройки
TUYA_ACCESS_ID = os.getenv("TUYA_ACCESS_ID")
TUYA_ACCESS_SECRET = os.getenv("TUYA_ACCESS_SECRET")
TUYA_API_REGION = os.getenv("TUYA_API_REGION", "eu")

# Supabase настройки
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TARIFF_SETTINGS_PATH = os.getenv("TARIFF_SETTINGS_PATH", "tariff_settings.json")

# Telegram Bot настройки
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_ADMIN_ID = os.getenv("TELEGRAM_ADMIN_ID")

# OpenRouter AI настройки
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
REASONING_MODEL = os.getenv("REASONING_MODEL", "deepseek/deepseek-r1-0528:free")
OPENROUTER_SITE_URL = os.getenv("OPENROUTER_SITE_URL", "https://mining-farm.ru")
OPENROUTER_SITE_NAME = os.getenv("OPENROUTER_SITE_NAME", "Mining Farm Analytics")

# Cerebras AI настройки
CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY")
CEREBRAS_MODEL = os.getenv("CEREBRAS_MODEL", "qwen-3-235b-a22b-thinking-2507")

# Проверка переменных
required_vars = [TUYA_ACCESS_ID, TUYA_ACCESS_SECRET, SUPABASE_URL, SUPABASE_KEY]
if not all(required_vars):
    raise ValueError("Проверьте .env файл: все переменные должны быть заданы!")

if not TELEGRAM_BOT_TOKEN:
    logger.warning("TELEGRAM_BOT_TOKEN не задан, функция бота будет отключена")

if not OPENROUTER_API_KEY and not CEREBRAS_API_KEY:
    logger.warning(
        "Не заданы ключи для AI-сервисов (OPENROUTER_API_KEY или CEREBRAS_API_KEY), AI-функции будут отключены")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Инициализация CoinGecko API
cg = CoinGeckoAPI()

# Загрузка конфигурации устройств
def load_devices_from_database():
    """Загружает конфигурацию устройств из базы данных Supabase"""
    try:
        response = supabase.table('miner_devices_config').select('*').eq('is_active', True).execute()
        if response.data:
            devices = response.data
            logger.info(f"Загружена конфигурация для {len(devices)} устройств из базы данных")
            return devices
        else:
            logger.warning("Не найдено активных устройств в базе данных")
            return []
    except Exception as e:
        logger.error(f"Ошибка загрузки конфигурации устройств из базы данных: {e}")
        # Fallback к пустому списку устройств
        return []

def add_device_to_database(device_id: str, name: str, location: str) -> bool:
    """Добавляет новое устройство в базу данных"""
    try:
        response = supabase.table('miner_devices_config').insert({
            'device_id': device_id,
            'name': name,
            'location': location,
            'is_active': True
        }).execute()
        
        if response.data:
            logger.info(f"Устройство {name} ({device_id}) успешно добавлено в базу данных")
            return True
        else:
            logger.error(f"Не удалось добавить устройство {name} в базу данных")
            return False
    except Exception as e:
        logger.error(f"Ошибка при добавлении устройства {name}: {e}")
        return False

def update_device_in_database(device_id: str, name: str = None, location: str = None, is_active: bool = None) -> bool:
    """Обновляет существующее устройство в базе данных"""
    try:
        update_data = {}
        if name is not None:
            update_data['name'] = name
        if location is not None:
            update_data['location'] = location
        if is_active is not None:
            update_data['is_active'] = is_active
            
        if not update_data:
            logger.warning("Нет данных для обновления устройства")
            return False
            
        response = supabase.table('miner_devices_config').update(update_data).eq('device_id', device_id).execute()
        
        if response.data:
            logger.info(f"Устройство {device_id} успешно обновлено в базе данных")
            return True
        else:
            logger.error(f"Не удалось обновить устройство {device_id} в базе данных")
            return False
    except Exception as e:
        logger.error(f"Ошибка при обновлении устройства {device_id}: {e}")
        return False

def delete_device_from_database(device_id: str) -> bool:
    """Удаляет устройство из базы данных (устанавливает is_active = False)"""
    try:
        response = supabase.table('miner_devices_config').update({'is_active': False}).eq('device_id', device_id).execute()
        
        if response.data:
            logger.info(f"Устройство {device_id} успешно деактивировано в базе данных")
            return True
        else:
            logger.error(f"Не удалось деактивировать устройство {device_id} в базе данных")
            return False
    except Exception as e:
        logger.error(f"Ошибка при деактивации устройства {device_id}: {e}")
        return False

def refresh_devices_from_database():
    """Обновляет список устройств из базы данных"""
    global DEVICES
    try:
        DEVICES = load_devices_from_database()
        logger.info(f"Список устройств обновлен: {len(DEVICES)} активных устройств")
        return True
    except Exception as e:
        logger.error(f"Ошибка при обновлении списка устройств: {e}")
        return False

try:
    DEVICES = load_devices_from_database()
    if not DEVICES:
        logger.warning("Конфигурация устройств пуста, некоторые функции могут работать некорректно")
except Exception as e:
    logger.error(f"Критическая ошибка загрузки конфигурации устройств: {e}")
    DEVICES = []  # Устанавливаем пустой список как fallback

# Загрузка тарифных настроек
try:
    with open(TARIFF_SETTINGS_PATH, "r", encoding="utf-8") as f:
        TARIFF_SETTINGS = json.load(f)
    logger.info(f"Загружены тарифные настройки для локаций: {list(TARIFF_SETTINGS.keys())}")
except Exception as e:
    logger.error(f"Ошибка загрузки тарифных настроек: {e}")
    raise

# Подключение к Tuya Cloud
try:
    tuya_cloud = tinytuya.Cloud(
        apiRegion=TUYA_API_REGION,
        apiKey=TUYA_ACCESS_ID,
        apiSecret=TUYA_ACCESS_SECRET
    )
    logger.info(f"Успешное подключение к Tuya Cloud (регион: {TUYA_API_REGION})")
except Exception as e:
    logger.error(f"Ошибка подключения к Tuya Cloud: {e}")
    raise

# Инициализация Telegram бота
bot = Bot(token=TELEGRAM_BOT_TOKEN) if TELEGRAM_BOT_TOKEN else None
dp = Dispatcher()

# Инициализация AI-клиентов
openai_client = None
cerebras_client = None

if OPENROUTER_API_KEY:
    openai_client = OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=OPENROUTER_API_KEY,
        max_retries=0,  # Disable automatic retries
        timeout=10.0  # Add timeout
    )

if CEREBRAS_API_KEY:
    cerebras_client = Cerebras(
        api_key=CEREBRAS_API_KEY,
    )

# Глобальные переменные для хранения состояния устройств
device_states = {}  # {device_id: {'last_state': bool, 'last_counter': float, 'session_start': datetime}}
last_counters = {}  # {device_id: float}
monitoring_active = True
notification_queue = asyncio.Queue()

# Курс валюты
exchange_rate_cache = {
    'rate': None,
    'timestamp': None,
    'source': 'CoinGecko'
}


class ExchangeRateManager:
    """Класс для управления курсом USDT/RUB"""

    @staticmethod
    def get_usdt_rub_rate_from_coingecko() -> Optional[float]:
        """Получение курса USDT/RUB с CoinGecko (рыночный курс, не P2P)"""
        try:
            price_data = cg.get_price(ids='tether', vs_currencies='rub')
            if 'tether' in price_data and 'rub' in price_data['tether']:
                rate = price_data['tether']['rub']
                logger.info(f"Получен курс с CoinGecko: 1 USDT = {rate} RUB")
                return rate
            else:
                logger.warning("Не удалось получить курс USDT/RUB с CoinGecko")
                return None
        except Exception as e:
            logger.error(f"Ошибка при получении курса с CoinGecko: {e}")
            return None

    @staticmethod
    def get_usdt_rub_rate() -> Optional[float]:
        """Основная функция для получения курса USDT/RUB с кэшированием"""
        global exchange_rate_cache
        # Проверяем кэш (обновляем каждые 5 минут)
        if (exchange_rate_cache['rate'] is not None and
                exchange_rate_cache['timestamp'] and
                (datetime.now() - exchange_rate_cache['timestamp']).total_seconds() < 300):
            return exchange_rate_cache['rate']

        logger.info("Получение курса USDT/RUB с CoinGecko...")
        rate = ExchangeRateManager.get_usdt_rub_rate_from_coingecko()
        if rate is not None:
            exchange_rate_cache['rate'] = rate
            exchange_rate_cache['timestamp'] = datetime.now()
            exchange_rate_cache['source'] = 'CoinGecko'
            return rate
        return None

    @staticmethod
    def get_rate_info() -> Dict[str, any]:
        """Получить информацию о курсе"""
        return {
            'rate': exchange_rate_cache.get('rate'),
            'source': exchange_rate_cache.get('source', 'CoinGecko'),
            'timestamp': exchange_rate_cache.get('timestamp')
        }


# Управление ограничениями API
class APIRateLimiter:
    """Класс для управления ограничениями Tuya API"""

    def __init__(self, max_requests_per_second=500, max_requests_per_day=500000):
        self.max_requests_per_second = max_requests_per_second
        self.max_requests_per_day = max_requests_per_day
        self.requests_today = 0
        self.last_reset = datetime.now().date()
        self.request_timestamps = []
        self.lock = Lock()

    def can_make_request(self):
        """Проверить, можно ли сделать запрос к API"""
        with self.lock:
            # Сброс счетчика в начале нового дня
            if datetime.now().date() != self.last_reset:
                self.requests_today = 0
                self.last_reset = datetime.now().date()
                self.request_timestamps = []

            # Проверка дневного лимита
            if self.requests_today >= self.max_requests_per_day:
                logger.warning(f"Достигнут дневной лимит API запросов: {self.requests_today}")
                return False

            # Проверка лимита в секунду
            now = time.time()
            # Удаляем старые запросы (старше 1 секунды)
            self.request_timestamps = [ts for ts in self.request_timestamps if now - ts < 1.0]
            if len(self.request_timestamps) >= self.max_requests_per_second:
                logger.warning(f"Достигнут лимит запросов в секунду: {len(self.request_timestamps)}")
                return False
            return True

    def record_request(self):
        """Зарегистрировать запрос к API"""
        with self.lock:
            self.requests_today += 1
            self.request_timestamps.append(time.time())

    def get_status(self):
        """Получить текущий статус использования API"""
        with self.lock:
            now = time.time()
            recent_requests = len([ts for ts in self.request_timestamps if now - ts < 1.0])
            return {
                "requests_today": self.requests_today,
                "requests_per_second": recent_requests,
                "daily_limit": self.max_requests_per_day,
                "second_limit": self.max_requests_per_second
            }


# Инициализация лимитера API
api_limiter = APIRateLimiter()


# Кэширование данных
class DataCache:
    """Класс для кэширования данных энергопотребления"""

    def __init__(self, cache_duration_hours=1):
        self.cache = {}
        self.cache_duration = timedelta(hours=cache_duration_hours)
        self.lock = Lock()

    def get(self, key):
        """Получить данные из кэша"""
        with self.lock:
            if key in self.cache:
                data, timestamp = self.cache[key]
                if datetime.now() - timestamp < self.cache_duration:
                    return data
                else:
                    del self.cache[key]
            return None

    def set(self, key, data):
        """Сохранить данные в кэш"""
        with self.lock:
            self.cache[key] = (data, datetime.now())

    def clear(self):
        """Очистить кэш"""
        with self.lock:
            self.cache.clear()


# Инициализация кэша
data_cache = DataCache()


def rate_limit(func):
    """Декоратор для контроля частоты запросов к API"""

    @wraps(func)
    def wrapper(*args, **kwargs):
        if not api_limiter.can_make_request():
            logger.warning(f"Превышен лимит API запросов. Пропуск вызова {func.__name__}")
            return None
        api_limiter.record_request()
        return func(*args, **kwargs)

    return wrapper


def get_device_status_cloud_enhanced(device_id: str) -> Tuple[bool, float, Optional[dict]]:
    """Расширенная функция получения статуса устройства с попыткой получить DPS 17"""
    logger.debug(f"Запрос статуса устройства {device_id}")

    # Проверяем кэш
    cache_key = f"device_status_{device_id}"
    cached_data = data_cache.get(cache_key)
    if cached_data:
        logger.debug(f"Используются кэшированные данные для устройства {device_id}")
        return cached_data

    @rate_limit
    def _make_request():
        try:
            # Получаем базовый статус
            status = tuya_cloud.getstatus(device_id)
            logger.debug(f"Ответ от Tuya Cloud для устройства {device_id}: {status}")

            # Если успешно, пробуем получить дополнительные DPS включая 17 (потребление энергии)
            if status and status.get('success'):
                try:
                    # Пробуем получить расширенный статус с DPS 17
                    enhanced_status = tuya_cloud.getdps(device_id)
                    if enhanced_status and enhanced_status.get('success'):
                        # Объединяем данные
                        if 'result' in enhanced_status:
                            status['result'].extend(enhanced_status.get('result', []))
                except Exception as e:
                    logger.debug(f"Не удалось получить расширенный DPS: {e}")
            return status
        except Exception as e:
            logger.error(f"Ошибка запроса статуса устройства {device_id}: {e}")
            return None

    status = _make_request()
    if status and status.get('success'):
        result = status.get('result', [])
        is_on = False
        counter = 0.0
        cur_power = None
        cur_voltage = None
        cur_current = None
        add_ele = 0.0  # DPS 17 - добавленное потребление энергии
        device_data = {}

        # Проверяем формат данных и обрабатываем правильно
        for item in result:
            # Проверяем, является ли элемент словарем
            if isinstance(item, dict):
                code = item.get('code')
                value = item.get('value')
            elif isinstance(item, str):
                # Если элемент - строка, пропускаем его
                continue
            else:
                # Неизвестный формат, пропускаем
                continue

            if code is None or value is None:
                continue

            device_data[code] = value

            if code == 'switch':
                is_on = value
            elif code == 'add_ele':
                counter = float(value)
            elif code == '17':  # DPS 17 - добавленное потребление энергии
                add_ele = float(value)
                device_data['add_ele'] = add_ele
            elif code == 'cur_power':
                cur_power = value
            elif code == 'cur_voltage':
                cur_voltage = value
            elif code == 'cur_current':
                cur_current = value

        # Если есть DPS 17, используем его как более точный счетчик
        if add_ele > 0:
            counter = add_ele

        # Корректировка значений согласно информации из GitHub issues
        if cur_power is not None:
            try:
                cur_power = float(cur_power)
                if cur_power > 100:
                    cur_power = cur_power / 10
                device_data['cur_power'] = cur_power
            except (ValueError, TypeError):
                cur_power = None

        if cur_voltage is not None:
            try:
                cur_voltage = float(cur_voltage)
                if cur_voltage > 1000:
                    cur_voltage = cur_voltage / 10
                device_data['cur_voltage'] = cur_voltage
            except (ValueError, TypeError):
                cur_voltage = None

        if cur_current is not None:
            try:
                cur_current = float(cur_current)
                cur_current = cur_current / 1000
                device_data['cur_current'] = cur_current
            except (ValueError, TypeError):
                cur_current = None

        # Дополнительная проверка: если есть мощность, устройство включено
        if cur_power is not None and cur_power > 0:
            is_on = True

        result_data = (is_on, counter, device_data)

        # Сохраняем в кэш
        data_cache.set(cache_key, result_data)

        logger.info(f"Устройство {device_id}: состояние={'ВКЛ' if is_on else 'ВЫКЛ'}, "
                    f"счетчик={counter:.3f} кВт·ч, мощность={cur_power} Вт")
        return result_data
    else:
        logger.error(f"Ошибка получения статуса устройства {device_id}: {status}")
        return False, 0.0, None


def get_device_energy_stats_cloud(device_id: str, start_time: datetime, end_time: datetime) -> Dict:
    """Получает статистику энергопотребления устройства через Tuya Cloud API"""
    logger.debug(f"Запрос статистики энергопотребления для устройства {device_id}")

    # Проверяем кэш
    cache_key = f"energy_stats_{device_id}_{start_time.strftime('%Y%m%d')}_{end_time.strftime('%Y%m%d')}"
    cached_data = data_cache.get(cache_key)
    if cached_data:
        logger.debug(f"Используются кэшированные данные статистики для устройства {device_id}")
        return cached_data

    @rate_limit
    def _make_request():
        try:
            # Используем правильный метод API - getdevicelog
            start_ms = int(start_time.timestamp() * 1000)
            end_ms = int(end_time.timestamp() * 1000)

            # Пробуем разные варианты вызова getdevicelog
            try:
                # Вариант 1: device_id как первый аргумент (позиционный)
                response = tuya_cloud.getdevicelog(
                    device_id,  # Первый аргумент - device_id
                    start=start_ms,
                    end=end_ms,
                    type="7"  # type=7 для отчетов о данных
                )
                logger.debug(f"Ответ статистики для устройства {device_id} (вариант 1): {response}")
                return response
            except Exception as e1:
                logger.debug(f"Вариант 1 не сработал: {e1}")
                try:
                    # Вариант 2: передача device_id как именованного аргумента device_id
                    response = tuya_cloud.getdevicelog(
                        device_id=device_id,
                        start=start_ms,
                        end=end_ms,
                        type="7"
                    )
                    logger.debug(f"Ответ статистики для устройства {device_id} (вариант 2): {response}")
                    return response
                except Exception as e2:
                    logger.debug(f"Вариант 2 не сработал: {e2}")
                    raise Exception("Все варианты вызова getdevicelog не сработали") from e2
        except Exception as e:
            logger.error(f"Ошибка запроса статистики устройства {device_id}: {e}")
            return None

    try:
        response = _make_request()
        if response and response.get('success'):
            result = response.get('result', [])
            energy_wh = 0

            # Анализируем логи для извлечения данных о потреблении
            for log_entry in result:
                # Проверяем формат записи
                if not isinstance(log_entry, dict):
                    continue

                # Ищем записи с данными о мощности (DPS 20) и общем потреблении (DPS 17)
                if 'dps' in log_entry and isinstance(log_entry['dps'], dict):
                    dps = log_entry['dps']

                    # Если есть данные о общем потреблении энергии (DPS 17)
                    if '17' in dps:
                        try:
                            energy_wh += float(dps['17'])  # DPS 17 обычно в ватт-часах
                        except (ValueError, TypeError):
                            continue

            energy_kwh = energy_wh / 1000  # Преобразование в кВт·ч

            stats_data = {
                'device_id': device_id,
                'energy_kwh': energy_kwh,
                'start_time': start_time.isoformat(),
                'end_time': end_time.isoformat(),
                'success': True,
                'raw_logs': len(result)
            }

            # Сохраняем в кэш
            data_cache.set(cache_key, stats_data)
            return stats_data
        else:
            # Если основной метод не сработал, используем альтернативный
            logger.warning(
                f"Основной метод получения статистики не сработал для устройства {device_id}, используем альтернативный")
            return get_device_energy_stats_cloud_alternative(device_id, start_time, end_time)
    except Exception as e:
        logger.error(f"Ошибка при получении статистики устройства {device_id}: {e}")
        # В случае ошибки используем альтернативный метод
        return get_device_energy_stats_cloud_alternative(device_id, start_time, end_time)


def get_device_energy_stats_cloud_alternative(device_id: str, start_time: datetime, end_time: datetime) -> Dict:
    """Альтернативный метод получения статистики через базовые статусы"""
    logger.debug(f"Альтернативный запрос статистики для устройства {device_id}")

    # Проверяем кэш
    cache_key = f"energy_stats_alt_{device_id}_{start_time.strftime('%Y%m%d')}_{end_time.strftime('%Y%m%d')}"
    cached_data = data_cache.get(cache_key)
    if cached_data:
        logger.debug(f"Используются кэшированные альтернативные данные для устройства {device_id}")
        return cached_data

    try:
        # Получаем текущий статус устройства
        is_on, counter, device_data = get_device_status_cloud_enhanced(device_id)

        # Получаем исторические данные из базы данных за указанный период
        response = supabase.table("miner_energy_sessions").select("*").eq(
            "miner_device_id", device_id).gte(
            "session_start_time", start_time.isoformat()).lt(
            "session_start_time", end_time.isoformat()).execute()

        # Суммируем энергопотребление из сессий
        energy_kwh = sum(session["energy_kwh"] for session in response.data)

        stats_data = {
            'device_id': device_id,
            'energy_kwh': energy_kwh,
            'start_time': start_time.isoformat(),
            'end_time': end_time.isoformat(),
            'success': True,
            'source': 'database',
            'current_counter': counter
        }

        # Сохраняем в кэш
        data_cache.set(cache_key, stats_data)
        return stats_data
    except Exception as e:
        logger.error(f"Ошибка альтернативного запроса статистики устройства {device_id}: {e}")
        return {
            'device_id': device_id,
            'energy_kwh': 0,
            'start_time': start_time.isoformat(),
            'end_time': end_time.isoformat(),
            'success': False,
            'error': str(e)
        }


def safe_get_device_data(device_id: str) -> Tuple[bool, float, Optional[dict]]:
    """Безопасное получение данных устройства с обработкой всех возможных ошибок"""
    try:
        # Пробуем получить статус через расширенную функцию
        return get_device_status_cloud_enhanced(device_id)
    except Exception as e:
        logger.error(f"Критическая ошибка при получении данных устройства {device_id}: {e}")
        # Возвращаем значения по умолчанию
        return False, 0.0, None


def get_daily_energy_consumption(device_id: str, date: datetime = None) -> Dict:
    """Получить дневное потребление электроэнергии"""
    if date is None:
        date = datetime.now().date()
    start_date = datetime.combine(date, datetime.min.time())
    end_date = start_date + timedelta(days=1)
    return get_device_energy_stats_cloud(device_id, start_date, end_date)


def get_monthly_energy_consumption(device_id: str, year: int = None, month: int = None) -> Dict:
    """Получить месячное потребление электроэнергии"""
    if year is None:
        year = datetime.now().year
    if month is None:
        month = datetime.now().month
    start_date = datetime(year, month, 1)
    if month == 12:
        end_date = datetime(year + 1, 1, 1)
    else:
        end_date = datetime(year, month + 1, 1)
    return get_device_energy_stats_cloud(device_id, start_date, end_date)


def get_historical_consumption_pattern(device_id: str, days: int = 7) -> Dict:
    """Получает исторический паттерн потребления устройства"""
    logger.debug(f"Анализ исторического паттерна для устройства {device_id} за {days} дней")

    patterns = {
        'hourly_avg': [0] * 24,  # Среднее потребление по часам
        'daily_total': 0,  # Среднее дневное потребление
        'peak_hours': [],  # Пиковые часы потребления
        'efficiency': 1.0,  # Коэффициент эффективности
        'day_ratio': 0.67,  # Доля дневного потребления
        'night_ratio': 0.33  # Доля ночного потребления
    }

    try:
        # Получаем данные за последние N дней
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        # Собираем почасовые данные
        hourly_data = {}
        day_energy = 0
        night_energy = 0

        for day in range(days):
            day_date = start_date + timedelta(days=day)
            day_start = datetime.combine(day_date.date(), datetime.min.time())
            day_end = day_start + timedelta(days=1)

            # Получаем статистику за день с использованием альтернативного метода при необходимости
            daily_stats = get_device_energy_stats_cloud(device_id, day_start, day_end)
            if daily_stats['success']:
                daily_consumption = daily_stats['energy_kwh']

                # Распределяем потребление по часам (пропорционально)
                for hour in range(24):
                    if hour not in hourly_data:
                        hourly_data[hour] = []

                    # Учитываем тарифные зоны
                    if 7 <= hour < 23:  # Дневной тариф
                        hour_consumption = (daily_consumption * patterns['day_ratio']) / 16
                        day_energy += hour_consumption
                    else:  # Ночной тариф
                        hour_consumption = (daily_consumption * patterns['night_ratio']) / 8
                        night_energy += hour_consumption

                    hourly_data[hour].append(hour_consumption)

        # Вычисляем средние значения по часам
        for hour in range(24):
            if hour in hourly_data and hourly_data[hour]:
                patterns['hourly_avg'][hour] = sum(hourly_data[hour]) / len(hourly_data[hour])

        # Находим пиковые часы
        avg_consumption = sum(patterns['hourly_avg']) / 24
        patterns['peak_hours'] = [i for i, val in enumerate(patterns['hourly_avg']) if val > avg_consumption * 1.5]
        patterns['daily_total'] = sum(patterns['hourly_avg'])

        # Уточняем соотношение день/ночь на основе реальных данных
        if day_energy + night_energy > 0:
            patterns['day_ratio'] = day_energy / (day_energy + night_energy)
            patterns['night_ratio'] = night_energy / (day_energy + night_energy)

        logger.debug(f"Исторический паттерн для {device_id}: {patterns}")
        return patterns
    except Exception as e:
        logger.error(f"Ошибка анализа исторического паттерна: {e}")
        return patterns


def enhanced_estimate_24h_consumption(current_power_w: float, location: str, device_id: str = None) -> Dict[str, float]:
    """Улучшенный расчет прогнозного потребления за 24 часа с учетом исторических данных"""
    logger.debug(f"Расчет 24-часового потребления для {location}: {current_power_w} Вт")

    # Базовый расчет на текущей мощности
    hours_24 = 24
    estimated_kwh = (current_power_w / 1000) * hours_24

    # Если есть device_id, получаем исторические паттерны
    if device_id:
        historical_pattern = get_historical_consumption_pattern(device_id)

        # Корректируем прогноз на основе исторических данных
        if historical_pattern['daily_total'] > 0:
            # Вычисляем коэффициент коррекции на основе исторических данных
            current_daily_estimate = (current_power_w / 1000) * hours_24
            historical_avg = historical_pattern['daily_total']

            # Если историческое потребление значительно отличается от текущего
            if abs(current_daily_estimate - historical_avg) / historical_avg > 0.3:
                # Применяем корректировку с весом 70% к историческим данным и 30% к текущим
                estimated_kwh = (historical_avg * 0.7) + (current_daily_estimate * 0.3)
                logger.debug(f"Прогноз скорректирован на основе истории: {estimated_kwh:.3f} кВт·ч")

    # Получаем тарифы для локации
    location_tariff = TARIFF_SETTINGS.get(location, {})
    tariff_type = location_tariff.get("tariff_type", "single")

    # Рассчитываем примерное распределение по зонам с учетом исторических паттернов
    if device_id:
        day_ratio = historical_pattern.get('day_ratio', 0.67)
        night_ratio = historical_pattern.get('night_ratio', 0.33)
    else:
        day_ratio = 0.67
        night_ratio = 0.33

    day_energy = estimated_kwh * day_ratio
    night_energy = estimated_kwh * night_ratio

    # Для прогноза используем тарифы первого диапазона как наиболее вероятные
    first_range = location_tariff.get("ranges", [{}])[0] if location_tariff.get("ranges") else {}

    if tariff_type == "day_night":
        estimated_cost = (day_energy * first_range.get("day_rate", 4.82)) + \
                         (night_energy * first_range.get("night_rate", 3.39))
    else:
        estimated_cost = estimated_kwh * first_range.get("day_rate", 4.82)

    result = {
        "estimated_kwh": estimated_kwh,
        "estimated_cost": estimated_cost,
        "day_energy": day_energy,
        "night_energy": night_energy,
        "day_rate": first_range.get("day_rate", 4.82),
        "night_rate": first_range.get("night_rate", 3.39),
        "tariff_type": tariff_type,
        "confidence": "high" if device_id else "medium"
    }

    logger.debug(f"Прогноз для {location}: {result}")
    return result


def predict_consumption_based_on_sales(device_id: str, location: str, days: int = 1) -> Dict:
    """Прогноз потребления на основе данных о продажах и эффективности"""
    logger.debug(f"Прогноз потребления для {device_id} на основе продаж за {days} дней")

    try:
        # Получаем данные о продажах за указанный период
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        sales_data = get_sales_data(start_date, end_date)

        if not sales_data:
            return {}

        # Рассчитываем общий доход
        total_income_usdt = sum(float(sale.get("total_received", 0)) for sale in sales_data)

        # Получаем исторические данные о потреблении
        historical_pattern = get_historical_consumption_pattern(device_id, days)

        # Оцениваем эффективность (сколько кВт·ч нужно для получения 1 USDT)
        if historical_pattern['daily_total'] > 0 and total_income_usdt > 0:
            efficiency = historical_pattern['daily_total'] / total_income_usdt
        else:
            efficiency = 0.5  # Значение по умолчанию

        # Прогнозируем потребление на основе ожидаемого дохода
        # Предполагаем, что доход будет таким же, как в предыдущие дни
        predicted_consumption = total_income_usdt * efficiency

        # Получаем текущую мощность для корректировки
        _, _, device_data = get_device_status_cloud_enhanced(device_id)
        current_power = device_data.get('cur_power', 0) if device_data else 0

        # Корректируем прогноз на основе текущей мощности
        if current_power > 0:
            current_day_estimate = (current_power / 1000) * 24
            # Берем среднее между исторической эффективностью и текущей мощностью
            predicted_consumption = (predicted_consumption + current_day_estimate) / 2

        return {
            'predicted_consumption_kwh': predicted_consumption,
            'efficiency_kwh_per_usdt': efficiency,
            'based_on_sales_count': len(sales_data),
            'confidence': 'high' if len(sales_data) > 3 else 'medium'
        }
    except Exception as e:
        logger.error(f"Ошибка прогнозирования на основе продаж: {e}")
        return {}


def get_current_power_consumption() -> Dict[str, Dict]:
    """Получает текущее потребление мощности всех устройств"""
    logger.info("Запрос текущего потребления мощности")
    consumption_data = {}

    for device in DEVICES:
        device_id = device["device_id"]
        device_name = device["name"]
        location = device["location"]

        is_on, counter, device_data = get_device_status_cloud_enhanced(device_id)

        if location not in consumption_data:
            consumption_data[location] = {
                "total_power_w": 0,
                "devices": []
            }

        power_w = 0
        if is_on and device_data and 'cur_power' in device_data:
            power_w = device_data['cur_power']

        consumption_data[location]["total_power_w"] += power_w
        consumption_data[location]["devices"].append({
            "id": device_id,
            "name": device_name,
            "power_w": power_w,
            "is_on": is_on
        })

    logger.info(f"Текущее потребление: {sum(loc['total_power_w'] for loc in consumption_data.values())} Вт")
    return consumption_data


def get_month_consumption_from_api(location: str) -> float:
    """Получить потребление за текущий месяц через Tuya API"""
    current_date = datetime.now()
    total_consumption = 0

    # Получаем устройства для локации
    location_devices = [d for d in DEVICES if d["location"] == location]

    for device in location_devices:
        device_id = device["device_id"]
        # Пробуем получить данные через Cloud API
        monthly_data = get_monthly_energy_consumption(device_id)
        if monthly_data['success']:
            total_consumption += monthly_data['energy_kwh']
            logger.debug(f"Устройство {device_id}: месячное потребление {monthly_data['energy_kwh']:.3f} кВт·ч")
        else:
            logger.warning(
                f"Не удалось получить месячные данные для устройства {device_id}: {monthly_data.get('error', 'Unknown error')}")

    return total_consumption


def get_today_consumption_from_api(location: str) -> float:
    """Получить потребление за сегодня через Tuya API"""
    total_consumption = 0

    # Получаем устройства для локации
    location_devices = [d for d in DEVICES if d["location"] == location]

    for device in location_devices:
        device_id = device["device_id"]
        # Пробуем получить данные через API
        daily_data = get_daily_energy_consumption(device_id)
        if daily_data['success']:
            total_consumption += daily_data['energy_kwh']
            logger.debug(f"Устройство {device_id}: дневное потребление {daily_data['energy_kwh']:.3f} кВт·ч")
        else:
            logger.warning(
                f"Не удалось получить дневные данные для устройства {device_id}: {daily_data.get('error', 'Unknown error')}")

    return total_consumption


def estimate_profitability(current_power_w: float, location: str, device_id: str = None, days: int = 1) -> Dict[
    str, float]:
    """Рассчитывает прогнозную доходность на основе текущей мощности и исторических данных"""
    logger.debug(f"Расчет прогнозной доходности для {location}: {current_power_w} Вт за {days} дней")

    # Получаем улучшенный прогноз потребления
    consumption_forecast = enhanced_estimate_24h_consumption(current_power_w, location, device_id)

    # Рассчитываем на указанное количество дней
    total_energy = consumption_forecast["estimated_kwh"] * days
    total_cost = consumption_forecast["estimated_cost"] * days

    # Прогноз дохода на основе исторической эффективности
    if device_id:
        sales_prediction = predict_consumption_based_on_sales(device_id, location, days)
        if sales_prediction:
            efficiency = sales_prediction.get('efficiency_kwh_per_usdt', 0.5)
            estimated_income = total_energy / efficiency if efficiency > 0 else total_energy * 0.5
        else:
            # Если нет данных о продажах, используем стандартный коэффициент
            estimated_income = total_energy * 0.5  # 0.5 USDT за 1 кВт·ч
    else:
        estimated_income = total_energy * 0.5  # Значение по умолчанию

    # Рассчитываем чистую прибыль и рентабельность
    exchange_rate = ExchangeRateManager.get_usdt_rub_rate()
    if exchange_rate:
        estimated_income_rub = estimated_income * exchange_rate
    else:
        estimated_income_rub = estimated_income * 80  # Курс по умолчанию

    estimated_profit = estimated_income_rub - total_cost
    profitability_percentage = (estimated_profit / total_cost * 100) if total_cost > 0 else 0

    result = {
        "period_days": days,
        "estimated_energy_kwh": total_energy,
        "estimated_cost_rub": total_cost,
        "estimated_income_usdt": estimated_income,
        "estimated_income_rub": estimated_income_rub,
        "estimated_profit_rub": estimated_profit,
        "profitability_percentage": profitability_percentage,
        "day_energy": consumption_forecast["day_energy"] * days,
        "night_energy": consumption_forecast["night_energy"] * days,
        "day_rate": consumption_forecast["day_rate"],
        "night_rate": consumption_forecast["night_rate"],
        "tariff_type": consumption_forecast["tariff_type"],
        "confidence": consumption_forecast.get("confidence", "medium")
    }

    logger.debug(f"Прогноз доходности для {location}: {result}")
    return result


def get_tariff_ranges(location: str, use_fallback: bool = False) -> List[Dict]:
    """Получает диапазоны тарифов для локации"""
    try:
        if location not in TARIFF_SETTINGS:
            logger.error(f"Локация {location} не найдена в тарифных настройках")
            if use_fallback:
                # Используем диапазон 800 для всех локаций если нет информации за месяц
                return [
                    {"min_kwh": 0, "max_kwh": 800, "day_rate": 8.13, "night_rate": 5.69}
                ]
            else:
                return [
                    {"min_kwh": 0, "max_kwh": 150, "day_rate": 4.82, "night_rate": 3.39},
                    {"min_kwh": 150, "max_kwh": 800, "day_rate": 6.11, "night_rate": 4.28},
                    {"min_kwh": 800, "max_kwh": None, "day_rate": 8.13, "night_rate": 5.69}
                ]
        return TARIFF_SETTINGS[location]["ranges"]
    except Exception as e:
        logger.error(f"Ошибка получения тарифов для {location}: {e}", exc_info=True)
        if use_fallback:
            return [
                {"min_kwh": 0, "max_kwh": 800, "day_rate": 8.13, "night_rate": 5.69}
            ]
        return []


def split_session_by_zones(start_time: datetime, end_time: datetime) -> Tuple[float, float]:
    """Разделяет время сессии на дневные и ночные часы"""
    logger.debug(f"Разделение сессии на зоны: {start_time} - {end_time}")

    day_hours = 0.0
    night_hours = 0.0
    current_time = start_time

    while current_time < end_time:
        next_hour = current_time.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        if next_hour > end_time:
            next_hour = end_time

        hour = current_time.hour
        if 23 <= hour or hour < 7:  # Ночной тариф: 23:00 - 7:00
            night_hours += (next_hour - current_time).total_seconds() / 3600
        else:
            day_hours += (next_hour - current_time).total_seconds() / 3600

        current_time = next_hour

    logger.debug(f"Результат разделения: день={day_hours:.2f}ч, ночь={night_hours:.2f}ч")
    return day_hours, night_hours


def calculate_session_cost_with_ranges(
        device_id: str,
        location: str,
        start_time: datetime,
        end_time: datetime,
        energy_kwh: float,
        previous_monthly_kwh: float,
        use_fallback_tariff: bool = False
) -> Tuple[float, float, float, Dict]:
    """
    Рассчитывает стоимость сессии с правильным учетом диапазонов потребления
    """
    logger.info(f"Расчет стоимости сессии: устройство={device_id}, энергия={energy_kwh:.3f} кВт·ч")

    # Получаем тарифные диапазоны
    ranges = get_tariff_ranges(location, use_fallback=use_fallback_tariff)
    location_tariff = TARIFF_SETTINGS.get(location, {})
    tariff_type = location_tariff.get("tariff_type", "single")

    # Разделяем сессию на дневные и ночные часы
    day_hours, night_hours = split_session_by_zones(start_time, end_time)
    total_hours = (end_time - start_time).total_seconds() / 3600

    if total_hours == 0:
        logger.warning("Нулевая продолжительность сессии")
        return 0.0, 0.0, 0.0, {"tariff_type": tariff_type}

    # Распределяем потребление по зонам пропорционально времени
    day_energy = (day_hours / total_hours) * energy_kwh
    night_energy = (night_hours / total_hours) * energy_kwh

    # Рассчитываем стоимость с учетом диапазонов
    total_cost = 0.0
    remaining_day_energy = day_energy
    remaining_night_energy = night_energy
    remaining_total_energy = energy_kwh
    current_monthly_kwh = previous_monthly_kwh
    cost_details = {
        "ranges": [],
        "tariff_type": tariff_type
    }

    for range_data in ranges:
        range_min = range_data["min_kwh"]
        range_max = range_data["max_kwh"]

        # Определяем, сколько энергии попадает в текущий диапазон
        if current_monthly_kwh < range_min:
            # Начинаем заполнять диапазон
            range_available = (range_max - range_min) if range_max else float('inf')
            energy_in_range = min(remaining_total_energy, range_available)

            if energy_in_range > 0:
                # Распределяем энергию в диапазоне пропорционально между днем и ночью
                day_ratio = remaining_day_energy / remaining_total_energy if remaining_total_energy > 0 else 0
                night_ratio = remaining_night_energy / remaining_total_energy if remaining_total_energy > 0 else 0

                day_in_range = energy_in_range * day_ratio
                night_in_range = energy_in_range * night_ratio

                if tariff_type == "day_night":
                    range_cost = (day_in_range * range_data["day_rate"]) + \
                                 (night_in_range * range_data["night_rate"])
                else:
                    range_cost = energy_in_range * range_data["day_rate"]

                total_cost += range_cost
                cost_details["ranges"].append({
                    "range_name": range_data.get("name", f"{range_min}-{range_max}"),
                    "energy_kwh": energy_in_range,
                    "day_energy_kwh": day_in_range,
                    "night_energy_kwh": night_in_range,
                    "day_rate": range_data["day_rate"],
                    "night_rate": range_data["night_rate"],
                    "cost": range_cost
                })

                remaining_total_energy -= energy_in_range
                remaining_day_energy -= day_in_range
                remaining_night_energy -= night_in_range
                current_monthly_kwh += energy_in_range

        if remaining_total_energy <= 0:
            break

    logger.info(
        f"Стоимость сессии: {total_cost:.2f} руб. (день: {day_energy:.3f} кВт·ч, ночь: {night_energy:.3f} кВт·ч)")
    return total_cost, day_energy, night_energy, cost_details


def calculate_session_cost(
        device_id: str,
        location: str,
        start_time: datetime,
        end_time: datetime,
        energy_kwh: float
) -> Tuple[float, float, float, Dict]:
    """
    Рассчитывает стоимость сессии с учетом тарифов и диапазонов
    """
    logger.info(f"Расчет стоимости сессии: устройство={device_id}, энергия={energy_kwh:.3f} кВт·ч")

    # Сначала пробуем получить месячное потребление через API
    month_start = start_time.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    try:
        # Пробуем получить данные через API
        location_devices = [d for d in DEVICES if d["location"] == location and d["device_id"] == device_id]
        if location_devices:
            previous_monthly_kwh = 0
            # Получаем потребление за месяц до начала сессии
            monthly_data = get_monthly_energy_consumption(device_id, month_start.year, month_start.month)
            if monthly_data['success']:
                previous_monthly_kwh = monthly_data['energy_kwh']
                use_fallback = False
            else:
                # Если API недоступен, используем данные из базы
                response = supabase.table("miner_energy_sessions").select("energy_kwh").eq(
                    "miner_device_id", device_id).gte(
                    "session_start_time", month_start.isoformat()).lt(
                    "session_start_time", start_time.isoformat()).execute()
                previous_monthly_kwh = sum(session["energy_kwh"] for session in response.data)
                use_fallback = previous_monthly_kwh == 0  # Используем запасной тариф если нет данных

            logger.debug(f"Потребление за месяц до сессии: {previous_monthly_kwh:.3f} кВт·ч")
        else:
            previous_monthly_kwh = 0.0
            use_fallback = True
    except Exception as e:
        logger.error(f"Ошибка получения месячного потребления: {e}")
        previous_monthly_kwh = 0.0
        use_fallback = True

    return calculate_session_cost_with_ranges(
        device_id, location, start_time, end_time, energy_kwh, previous_monthly_kwh, use_fallback
    )


def save_session(
        device_id: str,
        location: str,
        start_time: datetime,
        end_time: datetime,
        energy_kwh: float,
        cost_rub: float,
        tariff_type: str,
        day_energy: float,
        night_energy: float,
        cost_details: Dict
):
    """Сохраняет сессию в базу данных"""
    logger.info(f"Сохранение сессии в базу данных")

    try:
        session_data = {
            "miner_device_id": device_id,
            "miner_location": location,
            "session_start_time": start_time.isoformat(),
            "session_end_time": end_time.isoformat(),
            "energy_kwh": energy_kwh,
            "cost_rub": cost_rub,
            "tariff_type": tariff_type,
            "day_energy_kwh": day_energy,
            "night_energy_kwh": night_energy
        }

        # Try to include cost_details if column exists
        try:
            session_data["cost_details"] = json.dumps(cost_details)
        except Exception as e:
            logger.warning(f"Could not include cost_details: {e}")

        response = supabase.table("miner_energy_sessions").insert(session_data).execute()
        logger.info(
            f"Сессия успешно сохранена: {device_id}, энергия: {energy_kwh:.3f} кВт·ч, стоимость: {cost_rub:.2f} руб.")
        return response.data[0] if response.data else None
    except Exception as e:
        logger.error(f"Ошибка сохранения сессии: {e}", exc_info=True)
        return None


def get_sales_data(start_date: datetime, end_date: datetime) -> List[Dict]:
    """Получает данные о продажах за указанный период из Supabase"""
    try:
        response = supabase.table("miner_sales").select("*").gte(
            "executed_at", start_date.isoformat()).lt(
            "executed_at", end_date.isoformat()).execute()
        return response.data if response.data else []
    except Exception as e:
        logger.error(f"Ошибка получения данных о продажах: {e}", exc_info=True)
        return []


def get_energy_data(start_date: datetime, end_date: datetime) -> List[Dict]:
    """Получает данные о потреблении электроэнергии за указанный период"""
    try:
        response = supabase.table("miner_energy_sessions").select("*").gte(
            "session_start_time", start_date.isoformat()).lt(
            "session_start_time", end_date.isoformat()).execute()
        return response.data if response.data else []
    except Exception as e:
        logger.error(f"Ошибка получения данных о потреблении: {e}", exc_info=True)
        return []


def calculate_profitability_for_period(
        start_date: datetime,
        end_date: datetime,
        period_name: str
) -> Dict:
    """Рассчитывает доходность за указанный период с учетом курса валют"""
    logger.info(f"Расчет доходности за период {period_name}: {start_date} - {end_date}")

    try:
        # Получаем текущий курс валют
        exchange_rate = ExchangeRateManager.get_usdt_rub_rate()
        rate_info = ExchangeRateManager.get_rate_info()

        # Получаем данные о продажах за период
        sales_data = get_sales_data(start_date, end_date)

        # Получаем данные о потреблении электроэнергии за период
        energy_data = get_energy_data(start_date, end_date)

        # Рассчитываем общий доход от продаж в RUB
        total_income_usdt = 0.0
        total_income_rub = 0.0
        sales_by_currency = {}

        for sale in sales_data:
            currency = sale.get("currency_bought", "USDT")
            amount = float(sale.get("total_received", 0))
            total_income_usdt += amount

            # Конвертируем в RUB
            if currency == "USDT" and exchange_rate:
                amount_rub = amount * exchange_rate
            else:
                amount_rub = amount  # Предполагаем, что уже в RUB

            total_income_rub += amount_rub

            if currency not in sales_by_currency:
                sales_by_currency[currency] = {
                    "total_amount": 0.0,
                    "total_amount_rub": 0.0,
                    "sales_count": 0,
                    "sales": []
                }

            sales_by_currency[currency]["total_amount"] += amount
            sales_by_currency[currency]["total_amount_rub"] += amount_rub
            sales_by_currency[currency]["sales_count"] += 1
            sales_by_currency[currency]["sales"].append({
                "order_id": sale.get("order_id"),
                "amount_sold": float(sale.get("amount_sold", 0)),
                "total_received": amount,
                "total_received_rub": amount_rub,
                "avg_price": float(sale.get("avg_price", 0)),
                "executed_at": sale.get("executed_at")
            })

        # Рассчитываем общие затраты на электроэнергию
        total_cost = 0.0
        location_stats = {}

        for session in energy_data:
            location = session["miner_location"]
            if location not in location_stats:
                location_stats[location] = {
                    "total_energy": 0.0,
                    "total_cost": 0.0,
                    "day_energy": 0.0,
                    "night_energy": 0.0,
                    "devices": set()
                }

            location_stats[location]["total_energy"] += session["energy_kwh"]
            location_stats[location]["total_cost"] += session["cost_rub"]
            location_stats[location]["day_energy"] += session["day_energy_kwh"]
            location_stats[location]["night_energy"] += session["night_energy_kwh"]
            location_stats[location]["devices"].add(session["miner_device_id"])
            total_cost += session["cost_rub"]

        # Рассчитываем чистую прибыль и рентабельность
        net_profit = total_income_rub - total_cost
        profitability_percentage = (net_profit / total_cost * 100) if total_cost > 0 else 0

        # Рассчитываем среднесуточные показатели
        days_count = max(1, (end_date - start_date).days)
        avg_daily_income = total_income_rub / days_count
        avg_daily_cost = total_cost / days_count
        avg_daily_profit = net_profit / days_count

        # Формируем результат
        result = {
            "period_name": period_name,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "days_count": days_count,
            "total_income_usdt": total_income_usdt,
            "total_income_rub": total_income_rub,
            "total_cost": total_cost,
            "net_profit": net_profit,
            "profitability_percentage": profitability_percentage,
            "avg_daily_income": avg_daily_income,
            "avg_daily_cost": avg_daily_cost,
            "avg_daily_profit": avg_daily_profit,
            "exchange_rate": exchange_rate,
            "exchange_rate_source": rate_info.get('source', 'CoinGecko'),
            "sales_by_currency": sales_by_currency,
            "location_stats": location_stats,
            "sales_count": len(sales_data),
            "energy_sessions_count": len(energy_data)
        }

        # Сохраняем результат в Supabase для истории
        try:
            profit_data = {
                "period_name": period_name,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "total_income_rub": total_income_rub,
                "total_cost_rub": total_cost,
                "net_profit_rub": net_profit,
                "profitability_percentage": profitability_percentage,
                "avg_daily_income": avg_daily_income,
                "avg_daily_cost": avg_daily_cost,
                "avg_daily_profit": avg_daily_profit,
                "sales_count": len(sales_data),
                "energy_sessions_count": len(energy_data)
            }
            supabase.table("miner_profitability_history").insert(profit_data).execute()
        except Exception as e:
            logger.error(f"Ошибка сохранения данных о доходности: {e}")

        return result
    except Exception as e:
        logger.error(f"Ошибка расчета доходности за период {period_name}: {e}", exc_info=True)
        return {}


def calculate_daily_profitability(date: datetime = None):
    """Рассчитывает дневную доходность майнинга на основе реальных продаж"""
    if date is None:
        date = datetime.now().date()
    logger.info(f"Расчет дневной доходности за {date}")

    try:
        start_date = datetime.combine(date, datetime.min.time())
        end_date = start_date + timedelta(days=1)

        # Рассчитываем доходность за день
        profitability_data = calculate_profitability_for_period(start_date, end_date,
                                                                f"День {date.strftime('%d.%m.%Y')}")

        if profitability_data:
            # Сохраняем в таблицу дневной доходности с использованием UPSERT
            daily_profit_data = {
                "calculation_date": date.isoformat(),
                "total_income_rub": profitability_data["total_income_rub"],
                "total_cost_rub": profitability_data["total_cost"],
                "net_profit_rub": profitability_data["net_profit"],
                "profitability_percentage": profitability_data["profitability_percentage"],
                "sales_count": profitability_data["sales_count"],
                "energy_sessions_count": profitability_data["energy_sessions_count"]
            }
            supabase.table("miner_daily_profitability").upsert(
                daily_profit_data,
                on_conflict="calculation_date"
            ).execute()

            logger.info(f"Дневная доходность за {date}:")
            logger.info(
                f"  Доход: {profitability_data['total_income_usdt']:.2f} USDT ({profitability_data['total_income_rub']:.2f} RUB)")
            logger.info(
                f"  Курс: {profitability_data['exchange_rate_source']}: {profitability_data['exchange_rate']:.2f} руб")
            logger.info(f"  Затраты: {profitability_data['total_cost']:.2f} RUB")
            logger.info(f"  Прибыль: {profitability_data['net_profit']:.2f} RUB")
            logger.info(f"  Рентабельность: {profitability_data['profitability_percentage']:.2f}%")
    except Exception as e:
        logger.error(f"Ошибка расчета дневной доходности: {e}", exc_info=True)


def calculate_weekly_profitability(end_date: datetime = None):
    """Рассчитывает недельную доходность и среднесуточные показатели"""
    if end_date is None:
        end_date = datetime.now()
    start_date = end_date - timedelta(days=7)
    logger.info(f"Расчет недельной доходности: {start_date} - {end_date}")

    try:
        # Рассчитываем доходность за неделю
        weekly_data = calculate_profitability_for_period(start_date, end_date,
                                                         f"Неделя {start_date.strftime('%d.%m')} - {end_date.strftime('%d.%m.%Y')}")

        if weekly_data:
            # Рассчитываем среднесуточную доходность за неделю
            avg_daily_profitability = {
                "period_name": "Среднесуточная за неделю",
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "total_income": weekly_data["avg_daily_income"],
                "total_cost": weekly_data["avg_daily_cost"],
                "net_profit": weekly_data["avg_daily_profit"],
                "profitability_percentage": weekly_data["profitability_percentage"],
                "days_count": 7,
                "exchange_rate": weekly_data["exchange_rate"],
                "exchange_rate_source": weekly_data["exchange_rate_source"]
            }

            # Сохраняем в таблицу недельной доходности с использованием UPSERT
            weekly_profit_data = {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "total_income_rub": weekly_data["total_income_rub"],
                "total_cost_rub": weekly_data["total_cost"],
                "net_profit_rub": weekly_data["net_profit"],
                "profitability_percentage": weekly_data["profitability_percentage"],
                "avg_daily_income": weekly_data["avg_daily_income"],
                "avg_daily_cost": weekly_data["avg_daily_cost"],
                "avg_daily_profit": weekly_data["avg_daily_profit"],
                "sales_count": weekly_data["sales_count"],
                "energy_sessions_count": weekly_data["energy_sessions_count"]
            }

            # Используем insert вместо upsert для избежания ошибки с ограничением
            try:
                # Сначала проверяем, существует ли уже запись за эту неделю
                existing_record = supabase.table("miner_weekly_profitability").select("*").eq(
                    "start_date", start_date.isoformat()).execute()
                if existing_record.data:
                    # Если запись существует, обновляем ее
                    supabase.table("miner_weekly_profitability").update(
                        weekly_profit_data
                    ).eq("start_date", start_date.isoformat()).execute()
                else:
                    # Если записи нет, вставляем новую
                    supabase.table("miner_weekly_profitability").insert(
                        weekly_profit_data
                    ).execute()
            except Exception as e:
                logger.error(f"Ошибка сохранения недельной доходности: {e}")

            logger.info(f"Недельная доходность:")
            logger.info(
                f"  Общий доход: {weekly_data['total_income_usdt']:.2f} USDT ({weekly_data['total_income_rub']:.2f} RUB)")
            logger.info(f"  Общие затраты: {weekly_data['total_cost']:.2f} RUB")
            logger.info(f"  Общая прибыль: {weekly_data['net_profit']:.2f} RUB")
            logger.info(f"  Рентабельность: {weekly_data['profitability_percentage']:.2f}%")
            logger.info(f"  Среднесуточная прибыль: {weekly_data['avg_daily_profit']:.2f} RUB")
            return weekly_data, avg_daily_profitability
    except Exception as e:
        logger.error(f"Ошибка расчета недельной доходности: {e}", exc_info=True)
        return None, None


def calculate_monthly_profitability(end_date: datetime = None):
    """Рассчитывает месячную доходность"""
    if end_date is None:
        end_date = datetime.now()
    start_date = end_date - timedelta(days=30)
    logger.info(f"Расчет месячной доходности: {start_date} - {end_date}")

    try:
        # Рассчитываем доходность за месяц
        monthly_data = calculate_profitability_for_period(start_date, end_date,
                                                          f"Месяц {start_date.strftime('%d.%m')} - {end_date.strftime('%d.%m.%Y')}")

        if monthly_data:
            # Сохраняем в таблицу месячной доходности с использованием UPSERT
            monthly_profit_data = {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "total_income_rub": monthly_data["total_income_rub"],
                "total_cost_rub": monthly_data["total_cost"],
                "net_profit_rub": monthly_data["net_profit"],
                "profitability_percentage": monthly_data["profitability_percentage"],
                "avg_daily_income": monthly_data["avg_daily_income"],
                "avg_daily_cost": monthly_data["avg_daily_cost"],
                "avg_daily_profit": monthly_data["avg_daily_profit"],
                "sales_count": monthly_data["sales_count"],
                "energy_sessions_count": monthly_data["energy_sessions_count"]
            }
            supabase.table("miner_monthly_profitability").upsert(
                monthly_profit_data,
                on_conflict="start_date"
            ).execute()

            logger.info(f"Месячная доходность:")
            logger.info(
                f"  Общий доход: {monthly_data['total_income_usdt']:.2f} USDT ({monthly_data['total_income_rub']:.2f} RUB)")
            logger.info(f"  Общие затраты: {monthly_data['total_cost']:.2f} RUB")
            logger.info(f"  Общая прибыль: {monthly_data['net_profit']:.2f} RUB")
            logger.info(f"  Рентабельность: {monthly_data['profitability_percentage']:.2f}%")
            logger.info(f"  Среднесуточная прибыль: {monthly_data['avg_daily_profit']:.2f} RUB")
            return monthly_data
    except Exception as e:
        logger.error(f"Ошибка расчета месячной доходности: {e}", exc_info=True)
        return None


def calculate_3day_profitability(end_date: datetime = None):
    """Рассчитывает доходность за последние 3 дня"""
    if end_date is None:
        end_date = datetime.now()
    start_date = end_date - timedelta(days=3)
    logger.info(f"Расчет 3-дневной доходности: {start_date} - {end_date}")

    try:
        # Рассчитываем доходность за 3 дня
        data_3d = calculate_profitability_for_period(start_date, end_date,
                                                     f"3 дня {start_date.strftime('%d.%m')} - {end_date.strftime('%d.%m.%Y')}")

        if data_3d:
            # Рассчитываем среднесуточную доходность за 3 дня
            avg_daily_profitability = {
                "period_name": "Среднесуточная за 3 дня",
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "total_income": data_3d["avg_daily_income"],
                "total_cost": data_3d["avg_daily_cost"],
                "net_profit": data_3d["avg_daily_profit"],
                "profitability_percentage": data_3d["profitability_percentage"],
                "days_count": 3,
                "exchange_rate": data_3d["exchange_rate"],
                "exchange_rate_source": data_3d["exchange_rate_source"]
            }

            # Сохраняем в таблицу 3-дневной доходности
            profit_data = {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "total_income_rub": data_3d["total_income_rub"],
                "total_cost_rub": data_3d["total_cost"],
                "net_profit_rub": data_3d["net_profit"],
                "profitability_percentage": data_3d["profitability_percentage"],
                "avg_daily_income": data_3d["avg_daily_income"],
                "avg_daily_cost": data_3d["avg_daily_cost"],
                "avg_daily_profit": data_3d["avg_daily_profit"],
                "sales_count": data_3d["sales_count"],
                "energy_sessions_count": data_3d["energy_sessions_count"]
            }

            # Пытаемся сохранить данные, но продолжаем работу даже если не получится
            try:
                response = supabase.table("miner_3day_profitability").upsert(
                    profit_data,
                    on_conflict="start_date"
                ).execute()
                if response.data:
                    logger.info(f"3-дневная доходность успешно сохранена")
                else:
                    logger.warning(f"Не удалось сохранить 3-дневную доходность: пустой ответ")
            except Exception as e:
                error_msg = str(e).lower()
                if "404" in error_msg or "not found" in error_msg:
                    logger.warning(f"Таблица miner_3day_profitability не найдена. Пропуск сохранения в базу данных.")
                    logger.info("Для создания таблицы выполните SQL скрипт: create_3day_profitability_table.sql")
                else:
                    logger.warning(f"Не удалось сохранить 3-дневную доходность в базу данных: {e}")
                logger.info("Продолжаем работу без сохранения в базу данных")

            logger.info(f"3-дневная доходность:")
            logger.info(
                f"  Общий доход: {data_3d['total_income_usdt']:.2f} USDT ({data_3d['total_income_rub']:.2f} RUB)")
            logger.info(f"  Общие затраты: {data_3d['total_cost']:.2f} RUB")
            logger.info(f"  Общая прибыль: {data_3d['net_profit']:.2f} RUB")
            logger.info(f"  Рентабельность: {data_3d['profitability_percentage']:.2f}%")
            logger.info(f"  Среднесуточная прибыль: {data_3d['avg_daily_profit']:.2f} RUB")
            return data_3d, avg_daily_profitability
        else:
            logger.error("Не удалось рассчитать 3-дневную доходность: пустые данные")
            return None, None
    except Exception as e:
        logger.error(f"Ошибка расчета 3-дневной доходности: {e}", exc_info=True)
        return None, None


def get_today_spending() -> Dict[str, Dict]:
    """Получает статистику потребления за сегодня"""
    logger.info("Запрос статистики за сегодня")

    today = datetime.now().date()
    start_date = datetime.combine(today, datetime.min.time())
    end_date = start_date + timedelta(days=1)

    try:
        # Сначала пробуем получить данные через API
        api_stats = {}
        for location in set(device["location"] for device in DEVICES):
            api_consumption = get_today_consumption_from_api(location)
            if api_consumption > 0:
                api_stats[location] = {
                    "total_energy": api_consumption,
                    "total_cost": 0,  # Будет рассчитано ниже
                    "day_energy": api_consumption * 0.67,  # Примерное распределение
                    "night_energy": api_consumption * 0.33,
                    "devices": {},
                    "source": "API"
                }

        # Если API не дал данных, используем базу данных
        if not api_stats:
            response = supabase.table("miner_energy_sessions").select("*").gte(
                "session_start_time", start_date.isoformat()).lt(
                "session_start_time", end_date.isoformat()).execute()
            sessions = response.data
        else:
            sessions = []

        location_stats = {}

        # Обрабатываем данные из API
        for location, stats in api_stats.items():
            location_stats[location] = stats

        # Обрабатываем данные из базы (если есть)
        for session in sessions:
            location = session["miner_location"]
            device_id = session["miner_device_id"]

            # Находим имя устройства
            device_name = "Unknown"
            for device in DEVICES:
                if device["device_id"] == device_id:
                    device_name = device["name"]
                    break

            if location not in location_stats:
                location_stats[location] = {
                    "total_energy": 0.0,
                    "total_cost": 0.0,
                    "day_energy": 0.0,
                    "night_energy": 0.0,
                    "devices": {},
                    "source": "Database"
                }

            location_stats[location]["total_energy"] += session["energy_kwh"]
            location_stats[location]["total_cost"] += session["cost_rub"]
            location_stats[location]["day_energy"] += session["day_energy_kwh"]
            location_stats[location]["night_energy"] += session["night_energy_kwh"]

            if device_id not in location_stats[location]["devices"]:
                location_stats[location]["devices"][device_id] = {
                    "name": device_name,
                    "energy": 0.0,
                    "cost": 0.0
                }

            location_stats[location]["devices"][device_id]["energy"] += session["energy_kwh"]
            location_stats[location]["devices"][device_id]["cost"] += session["cost_rub"]

        # Рассчитываем стоимость для данных из API
        for location, stats in location_stats.items():
            if stats.get("source") == "API" and stats["total_cost"] == 0:
                # Получаем тарифы для расчета стоимости
                location_tariff = TARIFF_SETTINGS.get(location, {})
                tariff_type = location_tariff.get("tariff_type", "single")
                ranges = location_tariff.get("ranges", [{}])[0] if location_tariff.get("ranges") else {}

                if tariff_type == "day_night":
                    stats["total_cost"] = (
                            stats["day_energy"] * ranges.get("day_rate", 4.82) +
                            stats["night_energy"] * ranges.get("night_rate", 3.39)
                    )
                else:
                    stats["total_cost"] = stats["total_energy"] * ranges.get("day_rate", 4.82)

        logger.info(f"Получена статистика за сегодня по {len(location_stats)} локациям")
        return location_stats
    except Exception as e:
        logger.error(f"Ошибка получения статистики за сегодня: {e}", exc_info=True)
        return {}


def format_profitability_message(profitability_data: Dict, show_details: bool = True) -> str:
    """Форматирует данные о доходности для отправки в Telegram"""
    if not profitability_data:
        return "❌ Не удалось рассчитать доходность"

    period_name = profitability_data["period_name"]
    total_income_usdt = profitability_data.get("total_income_usdt", 0)
    total_income_rub = profitability_data.get("total_income_rub", 0)
    total_cost = profitability_data.get("total_cost", 0)
    net_profit = profitability_data.get("net_profit", 0)
    profitability_percentage = profitability_data.get("profitability_percentage", 0)
    sales_count = profitability_data.get("sales_count", 0)
    days_count = profitability_data.get("days_count", 1)
    exchange_rate = profitability_data.get("exchange_rate")
    exchange_rate_source = profitability_data.get("exchange_rate_source", "CoinGecko")

    message = f"📊 <b>{period_name}:</b>\n\n"

    # Информация о курсе
    if exchange_rate:
        message += f"💱 <b>Курс валюты:</b> {exchange_rate_source}: {exchange_rate:.2f} руб/USDT\n\n"

    # Общая информация
    profit_emoji = "🟢" if net_profit >= 0 else "🔴"
    message += f"{profit_emoji} <b>Общая доходность:</b>\n"
    message += f"💰 Доход от продаж: {total_income_usdt:.2f} USDT ({total_income_rub:.2f} RUB)\n"
    message += f"💸 Затраты на электричество: {total_cost:.2f} RUB\n"
    message += f"📈 Чистая прибыль: {net_profit:.2f} RUB\n"
    message += f"📊 Рентабельность: {profitability_percentage:.2f}%\n"

    # Среднесуточные показатели
    if days_count > 1:
        avg_daily_income = profitability_data.get("avg_daily_income", 0)
        avg_daily_cost = profitability_data.get("avg_daily_cost", 0)
        avg_daily_profit = profitability_data.get("avg_daily_profit", 0)
        message += f"\n<b>📈 Среднесуточные показатели:</b>\n"
        message += f"💰 Средний доход: {avg_daily_income:.2f} RUB\n"
        message += f"💸 Средние затраты: {avg_daily_cost:.2f} RUB\n"
        message += f"📊 Средняя прибыль: {avg_daily_profit:.2f} RUB\n"

    message += f"\n🛒 <b>Продажи:</b> {sales_count} шт.\n"

    if show_details and profitability_data.get("sales_by_currency"):
        message += "\n<b>💱 Детализация по валютам:</b>\n"
        for currency, data in profitability_data["sales_by_currency"].items():
            message += f"• {currency}: {data['total_amount']:.2f} ({data['total_amount_rub']:.2f} RUB, {data['sales_count']} сделок)\n"

    if show_details and profitability_data.get("location_stats"):
        message += "\n<b>⚡ Потребление по локациям:</b>\n"
        for location, stats in profitability_data["location_stats"].items():
            message += f"• {location}: {stats['total_energy']:.3f} кВт·ч ({stats['total_cost']:.2f} RUB)\n"

    return message


def format_profitability_forecast_message(forecast_data: Dict) -> str:
    """Форматирует данные о прогнозной доходности для отправки в Telegram"""
    if not forecast_data:
        return "❌ Не удалось рассчитать прогноз доходности"

    period_days = forecast_data.get("period_days", 1)
    estimated_energy = forecast_data.get("estimated_energy_kwh", 0)
    estimated_cost = forecast_data.get("estimated_cost_rub", 0)
    estimated_income = forecast_data.get("estimated_income_usdt", 0)
    estimated_profit = forecast_data.get("estimated_profit_rub", 0)
    profitability_percentage = forecast_data.get("profitability_percentage", 0)
    confidence = forecast_data.get("confidence", "medium")

    period_text = "24 часа" if period_days == 1 else f"{period_days} дней"
    confidence_emoji = "🟢" if confidence == "high" else "🟡" if confidence == "medium" else "🔴"

    message = f"🔮 <b>Прогноз доходности на {period_text}:</b> {confidence_emoji}\n\n"

    # Общая информация
    profit_emoji = "🟢" if estimated_profit >= 0 else "🔴"
    message += f"{profit_emoji} <b>Прогнозная доходность:</b>\n"
    message += f"⚡ Прогноз потребления: {estimated_energy:.3f} кВт·ч\n"
    message += f"💰 Прогноз дохода: {estimated_income:.2f} USDT\n"
    message += f"💸 Прогноз затрат: {estimated_cost:.2f} RUB\n"
    message += f"📈 Прогноз прибыли: {estimated_profit:.2f} RUB\n"
    message += f"📊 Прогноз рентабельности: {profitability_percentage:.2f}%\n"

    # Детализация по тарифам
    day_energy = forecast_data.get("day_energy", 0)
    night_energy = forecast_data.get("night_energy", 0)
    day_rate = forecast_data.get("day_rate", 4.82)
    night_rate = forecast_data.get("night_rate", 3.39)

    message += f"\n<b>💡 Детализация по тарифам:</b>\n"
    message += f"☀️ День: {day_energy:.3f} кВт·ч ({day_rate} руб/кВт·ч)\n"
    message += f"🌙 Ночь: {night_energy:.3f} кВт·ч ({night_rate} руб/кВт·ч)\n"

    return message


# Function to sanitize AI responses for Telegram
def sanitize_for_telegram_html(text):
    """Sanitize AI response to prevent Telegram parsing errors"""
    if not text:
        return ""

    # First, clean reasoning tags
    text = parse_ai_thinking_tags(text)

    # Remove problematic HTML tags that might cause parsing issues
    # Keep only basic formatting tags that Telegram supports
    allowed_tags = ['b', 'i', 'u', 's', 'a', 'code', 'pre']

    # Pattern to match HTML tags
    tag_pattern = re.compile(r'</?([a-zA-Z0-9]+)(?:\s+[^>]*)?>')

    def replace_tag(match):
        tag_name = match.group(1).lower()
        if tag_name in allowed_tags:
            return match.group(0)  # Keep allowed tags
        return ""  # Remove disallowed tags

    # Replace disallowed tags
    sanitized = tag_pattern.sub(replace_tag, text)

    # Fix common HTML issues
    sanitized = sanitized.replace("&nbsp;", " ")  # Replace non-breaking spaces
    sanitized = sanitized.replace("&amp;", "&")  # Fix ampersands
    sanitized = sanitized.replace("&lt;", "<")  # Fix less than
    sanitized = sanitized.replace("&gt;", ">")  # Fix greater than

    # Remove any remaining HTML entities that might cause issues
    sanitized = re.sub(r'&[a-zA-Z0-9#]+;', '', sanitized)

    # Final validation: ensure all opened tags are closed
    tag_stack = []
    for match in re.finditer(r'<([a-zA-Z0-9]+)(?:\s+[^>]*)?>', sanitized):
        tag = match.group(1)
        if tag in allowed_tags:
            tag_stack.append(tag)

    # Close any unclosed tags
    for tag in reversed(tag_stack):
        if tag not in ['img', 'br', 'hr']:  # Self-closing tags
            sanitized += f"</{tag}>"

    return sanitized


# Function to split long messages for Telegram
def split_message_for_telegram(text, max_length=4096):
    """Split a long message into multiple parts for Telegram"""
    if len(text) <= max_length:
        return [text]

    parts = []
    current_part = ""

    # Split by paragraphs first
    paragraphs = text.split('\n\n')

    for paragraph in paragraphs:
        # If adding this paragraph would exceed the limit, start a new part
        if len(current_part) + len(paragraph) + 2 > max_length:
            if current_part:  # Save current part if not empty
                parts.append(current_part)
                current_part = ""

            # If a single paragraph is too long, split it by lines
            if len(paragraph) > max_length:
                lines = paragraph.split('\n')
                for line in lines:
                    if len(current_part) + len(line) + 1 > max_length:
                        if current_part:
                            parts.append(current_part)
                            current_part = line
                        else:
                            # If a single line is too long, split it by words
                            words = line.split(' ')
                            for word in words:
                                if len(current_part) + len(word) + 1 > max_length:
                                    if current_part:
                                        parts.append(current_part)
                                        current_part = word
                                    else:
                                        # If a single word is too long, split it
                                        while len(word) > max_length:
                                            parts.append(word[:max_length])
                                            word = word[max_length:]
                                        current_part = word
                                else:
                                    if current_part:
                                        current_part += " " + word
                                    else:
                                        current_part = word
                    else:
                        if current_part:
                            current_part += "\n" + line
                        else:
                            current_part = line
            else:
                current_part = paragraph
        else:
            if current_part:
                current_part += "\n\n" + paragraph
            else:
                current_part = paragraph

    # Add the last part if not empty
    if current_part:
        parts.append(current_part)

    return parts


# Function to parse AI thinking tags
def parse_ai_thinking_tags(response_text: str) -> str:
    """
    Enhanced function to remove reasoning content from AI responses.
    Supports all major tag formats from different providers.
    """
    if not response_text:
        return ""

    # Compile all patterns for optimization
    patterns = [
        # Cerebras and DeepSeek formats
        (r'', re.DOTALL),
        (r'<thinking>.*?</thinking>', re.DOTALL),
        (r'<answer>.*?</answer>', re.DOTALL),
        # OpenRouter and other formats
        (r'<details>.*?</details>', re.DOTALL),
        (r'<div[^>]*class=["\'][^"\']*thinking[^"\']*["\'][^>]*>.*?</div>', re.DOTALL),
        # Handle incomplete/damaged tags
        (r'<thinking>.*?$', re.DOTALL),  # Unclosed thinking tag
        (r'<details>.*?$', re.DOTALL),  # Unclosed details tag
        (r'<div[^>]*class=["\'][^"\']*thinking[^"\']*["\'][^>]*>.*?$', re.DOTALL),  # Unclosed thinking div
        # Handle nested tags
        (r'<thinking>.*?<thinking>.*?</thinking>.*?</thinking>', re.DOTALL),
        (r'<details>.*?<details>.*?</details>.*?</details>', re.DOTALL),
    ]

    cleaned_text = response_text

    # Apply each pattern to remove thinking sections
    for pattern, flags in patterns:
        try:
            think_pattern = re.compile(pattern, flags)
            cleaned_text = think_pattern.sub('', cleaned_text)
        except Exception as e:
            logger.warning(f"Error applying pattern {pattern}: {e}")

    # Clean up extra whitespace and newlines
    cleaned_text = re.sub(r'\n\s*\n', '\n\n', cleaned_text.strip())

    # Remove any remaining HTML entities that might cause issues
    cleaned_text = re.sub(r'&[a-zA-Z0-9#]+;', '', cleaned_text)

    # Final validation: ensure no broken HTML remains
    if '<' in cleaned_text and '>' in cleaned_text:
        # Additional safety check for malformed HTML
        html_tags = re.findall(r'<[^>]+>', cleaned_text)
        allowed_tags = ['b', 'i', 'u', 's', 'a', 'code', 'pre']
        for tag in html_tags:
            tag_name = re.findall(r'^</?([a-zA-Z0-9]+)', tag)
            if tag_name and tag_name[0].lower() not in allowed_tags:
                # Remove disallowed tag
                cleaned_text = cleaned_text.replace(tag, '')

    return cleaned_text.strip()


# Function to execute AI requests with proper error handling
async def make_ai_request(system_prompt, user_prompt, temperature=0.7, max_tokens=1500):
    """Execute AI request with proper rate limiting handling and enhanced thinking tag parsing"""
    # Try OpenRouter first
    if openai_client:
        try:
            response = openai_client.chat.completions.create(
                model=REASONING_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                extra_headers={
                    "HTTP-Referer": OPENROUTER_SITE_URL,
                    "X-Title": OPENROUTER_SITE_NAME,
                },
                timeout=10  # Add timeout to prevent hanging
            )
            # Enhanced parsing of thinking tags from the response
            raw_response = response.choices[0].message.content
            logger.debug(f"Raw AI response: {raw_response[:200]}...")

            # Apply enhanced cleaning
            cleaned_response = parse_ai_thinking_tags(raw_response)
            logger.debug(f"Cleaned AI response: {cleaned_response[:200]}...")

            return cleaned_response, "OpenRouter"
        except Exception as e:
            error_msg = str(e)
            logger.warning(f"OpenRouter request failed: {error_msg}")
            # Check for rate limiting errors
            if "429" in error_msg or "rate limit" in error_msg.lower():
                logger.info("Rate limit exceeded on OpenRouter, switching to Cerebras")
            # Continue to Cerebras below
    # Fallback to Cerebras
    if cerebras_client:
        try:
            response = cerebras_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                model=CEREBRAS_MODEL,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=10  # Add timeout
            )
            # Enhanced parsing of thinking tags from the response
            raw_response = response.choices[0].message.content
            logger.debug(f"Raw AI response: {raw_response[:200]}...")

            # Apply enhanced cleaning
            cleaned_response = parse_ai_thinking_tags(raw_response)
            logger.debug(f"Cleaned AI response: {cleaned_response[:200]}...")

            return cleaned_response, "Cerebras"
        except Exception as e:
            logger.warning(f"Cerebras request failed: {e}")
    # Both providers failed
    return None, None


# Chat session management
class ChatSession:
    """Manage chat sessions with history"""

    def __init__(self):
        self.sessions = {}  # user_id: {'history': [], 'context': {}}
        self.max_history = 10  # Maximum messages to keep in history
        self.auto_clear_after = 3600  # Auto-clear after 1 hour (in seconds)

    def get_session(self, user_id: int):
        """Get or create user session"""
        if user_id not in self.sessions:
            self.sessions[user_id] = {
                'history': [],
                'context': {},
                'last_activity': datetime.now()
            }
        return self.sessions[user_id]

    def add_message(self, user_id: int, role: str, content: str):
        """Add message to session history"""
        session = self.get_session(user_id)
        session['history'].append({
            'role': role,
            'content': content,
            'timestamp': datetime.now()
        })
        session['last_activity'] = datetime.now()

        # Keep only recent messages
        if len(session['history']) > self.max_history:
            session['history'] = session['history'][-self.max_history:]

    def clear_session(self, user_id: int):
        """Clear user session"""
        if user_id in self.sessions:
            del self.sessions[user_id]

    def auto_clear_inactive(self):
        """Clear inactive sessions"""
        current_time = datetime.now()
        inactive_users = [
            user_id for user_id, session in self.sessions.items()
            if (current_time - session['last_activity']).total_seconds() > self.auto_clear_after
        ]
        for user_id in inactive_users:
            self.clear_session(user_id)


# Global chat session manager
chat_sessions = ChatSession()


# Natural Language to SQL converter
class NaturalLanguageToSQL:
    """Convert natural language queries to SQL"""

    def __init__(self):
        self.table_schemas = {
            'miner_energy_sessions': {
                'columns': ['id', 'miner_device_id', 'miner_location', 'session_start_time',
                            'session_end_time', 'energy_kwh', 'cost_rub', 'tariff_type',
                            'day_energy_kwh', 'night_energy_kwh', 'created_at'],
                'description': 'Сессии потребления электроэнергии для майнинговых устройств'
            },
            'miner_sales': {
                'columns': ['id', 'order_id', 'currency_bought', 'amount_sold',
                            'total_received', 'avg_price', 'executed_at', 'created_at'],
                'description': 'Записи о продажах от майнинговой деятельности'
            },
            'miner_daily_profitability': {
                'columns': ['id', 'calculation_date', 'total_income_rub', 'total_cost_rub',
                            'net_profit_rub', 'profitability_percentage', 'sales_count',
                            'energy_sessions_count', 'created_at'],
                'description': 'Расчеты дневной доходности'
            }
        }

    async def generate_sql_query(self, question: str, context: dict = None) -> dict:
        """
        Convert natural language question to SQL query
        Args:
            question: Natural language question
            context: Additional context from previous messages
        Returns:
            Dictionary with sql_query, explanation, and parameters
        """
        # Create prompt for AI
        schema_info = "\n".join([
            f"Таблица: {table}\nКолонки: {', '.join(schema['columns'])}\nОписание: {schema['description']}"
            for table, schema in self.table_schemas.items()
        ])

        prompt = f"""
        Преобразуй следующий вопрос на естественном языке в SQL-запрос на основе схемы базы данных:
        Схема базы данных:
        {schema_info}
        Вопрос: {question}
        Контекст: {context or 'Нет'}
        Правила:
        1. Используй правильный синтаксис SQL для PostgreSQL (Supabase)
        2. Всегда используй параметризованные запросы для предотвращения SQL-инъекций
        3. Включи правильную фильтрацию по датам при запросах о временных периодах
        4. Используй соответствующие агрегатные функции (SUM, AVG, COUNT) при необходимости
        5. Возвращай только SQL-запрос без каких-либо объяснений
        Верни ответ в формате JSON:
        {{
            "sql_query": "SELECT ...",
            "explanation": "Краткое объяснение того, что делает запрос",
            "parameters": []
        }}
        """

        # Get AI response
        ai_response, _ = await make_ai_request(
            system_prompt="Ты - эксперт по разработке SQL. Преобразовывай вопросы на естественном языке в SQL-запросы.",
            user_prompt=prompt,
            temperature=0.1,
            max_tokens=1000
        )

        if ai_response:
            try:
                # Parse JSON response
                result = json.loads(ai_response)
                return result
            except json.JSONDecodeError:
                # Fallback: try to extract SQL from text
                sql_match = re.search(r'SELECT.*?(?=;|$)', ai_response, re.IGNORECASE | re.DOTALL)
                if sql_match:
                    return {
                        'sql_query': sql_match.group(0),
                        'explanation': 'Сгенерированный SQL-запрос',
                        'parameters': []
                    }
        return None

    async def execute_query(self, sql_query: str, parameters: list = None) -> list:
        """Execute SQL query against Supabase"""
        try:
            # Note: This is a simplified implementation. In production, you should
            # use proper SQL execution through Supabase's RPC or direct SQL
            response = supabase.rpc('exec_sql', {'query': sql_query, 'params': parameters or []}).execute()
            return response.data if response.data else []
        except Exception as e:
            logger.error(f"Ошибка выполнения SQL: {e}")
            # Return empty list instead of None to avoid further errors
            return []


# Global NL-to-SQL converter
nl_to_sql = NaturalLanguageToSQL()


# Setup bot commands
async def setup_bot_commands():
    """Setup bot command menu"""
    commands = [
        types.BotCommand(command="start", description="Запустить бота"),
        types.BotCommand(command="help", description="Показать справку"),
        types.BotCommand(command="today", description="Статистика за сегодня и прогноз"),
        types.BotCommand(command="last", description="Доходность за последние 3 дня"),
        types.BotCommand(command="profit24h", description="24-часовая доходность"),
        types.BotCommand(command="profit7d", description="Недельная доходность"),
        types.BotCommand(command="profit30d", description="Месячная доходность"),
        types.BotCommand(command="profitall", description="Доходность за все периоды"),
        types.BotCommand(command="devices", description="Статус устройств"),
        types.BotCommand(command="api_status", description="Статус API"),
        types.BotCommand(command="ai_analyze", description="AI-анализ ситуации"),
        types.BotCommand(command="ai_forecast", description="AI-прогноз потребления"),
        types.BotCommand(command="ai_optimize", description="AI-оптимизация доходности"),
        types.BotCommand(command="ai_health", description="AI-проверка системы"),
        types.BotCommand(command="clear", description="Очистить историю чата"),
        types.BotCommand(command="chat", description="Общение с AI-помощником")
    ]
    await bot.set_my_commands(commands)


# Telegram Bot Handlers
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Обработчик команды /start"""
    logger.info(f"Пользователь {message.from_user.id} запустил бота")
    await message.reply(
        "👋 Привет! Я бот для мониторинга потребления электроэнергии майнинг-фермы и расчета реальной доходности.\n\n"
        "Доступные команды:\n"
        "/today - Показать статистику за сегодня и реальную доходность\n"
        "/last - Показать расчет и прогноз за последние 3 дня\n"
        "/profit24h - Показать детальную 24-часовую доходность\n"
        "/profit7d - Показать недельную доходность и среднесуточные показатели\n"
        "/profit30d - Показать месячную доходность\n"
        "/profitall - Показать доходность за все периоды\n"
        "/devices - Показать статус устройств\n"
        "/api_status - Показать статус использования API\n"
        "/ai_analyze - AI-анализ текущей ситуации\n"
        "/ai_forecast - AI-прогноз энергопотребления\n"
        "/ai_optimize - AI-оптимизация доходности\n"
        "/ai_health - AI-проверка здоровья системы\n"
        "/chat - Начать диалог с AI-помощником\n"
        "/clear - Очистить историю чата\n"
        "/help - Помощь"
    )


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    """Обработчик команды /help"""
    help_text = """
📚 <b>Доступные команды:</b>
/today - Показать статистику потребления за сегодня, реальную доходность и прогноз на 24 часа
/last - Показать расчет и прогноз за последние 3 дня
/profit24h - Показать детальную 24-часовую доходность на основе реальных продаж
/profit7d - Показать недельную доходность и среднесуточные показатели
/profit30d - Показать месячную доходность и среднесуточные показатели
/profitall - Показать сводную доходность за все периоды (24ч, 7д, 30д)
/devices - Показать текущий статус всех устройств
/list_devices - Показать список всех устройств в базе данных
/add_device - Добавить новое устройство (только для админа)
/update_device - Обновить устройство (только для админа)
/delete_device - Удалить устройство (только для админа)
/api_status - Показать статус использования Tuya AI
/ai_analyze - AI-анализ текущей ситуации майнинга
/ai_forecast [период] - AI-прогноз энергопотребления (24h, 7d, 30d)
/ai_optimize - AI-оптимизация доходности майнинга
/ai_health - AI-проверка здоровья системы
/chat - Начать диалог с AI-помощником на естественном языке
/clear - Очистить историю чата с AI-помощником
/help - Показать эту справку

📊 <b>Формат вывода:</b>
• Реальная доходность на основе данных о продажах из таблицы miner_sales
• Фактическое потребление за сегодня (из AI или базы данных)
• Прогноз на 24 часа при текущей мощности с учетом исторических данных
• Стоимость в рублях с учетом курса USDT/RUB
• Разделение на дневное/ночное потребление
• Статистика по каждому устройству

⚠️ <b>Ограничения AI:</b>
• 500,000 запросов в день
• 500 запросов в секунду
• Данные кэшируются на 1 час

💰 <b>Расчет доходности:</b>
• Доход рассчитывается на основе реальных продаж из таблицы miner_sales
• Курс валюты автоматически обновляется с CoinGecko
• Затраты рассчитываются на основе фактического потребления электроэнергии
• Если нет информации за месяц, используется тарифный диапазон 800 кВт·ч
• Чистая прибыль = Доход от продаж - Затраты на электричество
• Рентабельность = (Чистая прибыль / Затраты) * 100%
• Среднесуточные показатели рассчитываются для периодов больше 1 дня

🔮 <b>AI-функции:</b>
• Анализ текущей ситуации с учетом рыночных условий
• Прогнозирование энергопотребления на основе исторических данных
• Оптимизация доходности с учетом тарифов и эффективности
• Обнаружение аномалий и проблем в системе

💬 <b>Диалог с AI:</b>
• Задавайте вопросы на естественном русском языке
• Примеры: "расходы на электричество за 7 дней", "сколько мы заработали за месяц"
• AI преобразует ваши вопросы в SQL-запросы и вернет ответы
    """
    await message.reply(help_text, parse_mode=ParseMode.HTML)


@dp.message(Command("api_status"))
async def cmd_api_status(message: types.Message):
    """Обработчик команды /api_status"""
    logger.info(f"Пользователь {message.from_user.id} запросил статус AI")
    status = api_limiter.get_status()
    cache_size = len(data_cache.cache)
    rate_info = ExchangeRateManager.get_rate_info()

    status_text = f"📊 <b>Статус Tuya AI:</b>\n\n"
    status_text += f"📈 Запросов сегодня: {status['requests_today']}/{status['daily_limit']}\n"
    status_text += f"⚡ Запросов в секунду: {status['requests_per_second']}/{status['second_limit']}\n"
    status_text += f"💾 Кэшированных записей: {cache_size}\n\n"

    status_text += f"💱 <b>Курс валюты:</b>\n"
    if rate_info['rate']:
        status_text += f"Источник: {rate_info['source']}\n"
        status_text += f"Курс: 1 USDT = {rate_info['rate']:.2f} RUB\n"
        if rate_info['timestamp']:
            status_text += f"Обновлен: {rate_info['timestamp'].strftime('%H:%M:%S')}\n"
    else:
        status_text += "❌ Курс недоступен\n"

    if status['requests_today'] > status['daily_limit'] * 0.8:
        status_text += "\n⚠️ <b>Внимание!</b> Вы приближаетесь к дневному лимиту AI!\n"
    if status['requests_per_second'] > status['second_limit'] * 0.8:
        status_text += "⚠️ <b>Внимание!</b> Высокая нагрузка на AI!\n"

    await message.reply(status_text, parse_mode=ParseMode.HTML)


@dp.message(Command("last"))
async def cmd_last(message: types.Message):
    """Обработчик команды /last - показывает расчет и прогноз за последние 3 дня"""
    logger.info(f"Пользователь {message.from_user.id} запросил 3-дневную доходность")

    # Рассчитываем доходность за последние 3 дня
    data_3d, avg_daily_data = calculate_3day_profitability()

    if data_3d and avg_daily_data:
        response_text = format_profitability_message(data_3d, show_details=False)

        # Fix for average daily data - use the actual values from data_3d
        fixed_avg_daily_data = {
            "period_name": "Среднесуточная за 3 дня",
            "total_income_usdt": data_3d.get("total_income_usdt", 0) / 3,
            "total_income_rub": data_3d.get("total_income_rub", 0) / 3,
            "total_cost": data_3d.get("total_cost", 0) / 3,
            "net_profit": data_3d.get("net_profit", 0) / 3,
            "profitability_percentage": data_3d.get("profitability_percentage", 0),
            "exchange_rate": data_3d.get("exchange_rate"),
            "exchange_rate_source": data_3d.get("exchange_rate_source", "CoinGecko"),
            "sales_count": max(1, data_3d.get("sales_count", 0) // 3),  # Avoid division by zero
            "location_stats": data_3d.get("location_stats", {})
        }

        response_text += f"\n\n{format_profitability_message(fixed_avg_daily_data, show_details=False)}"

        # Добавляем прогноз на следующие 3 дня на основе текущей мощности
        current_consumption = get_current_power_consumption()
        total_current_power = sum(loc['total_power_w'] for loc in current_consumption.values())

        if total_current_power > 0:
            # Получаем прогноз для каждой локации
            forecasts = {}
            for location, data in current_consumption.items():
                if data['total_power_w'] > 0:
                    # Находим device_id для локации
                    device_id = None
                    for device in DEVICES:
                        if device["location"] == location:
                            device_id = device["device_id"]
                            break

                    forecasts[location] = estimate_profitability(
                        data['total_power_w'], location, device_id, days=3
                    )

            # Суммируем прогнозы по всем локациям
            if forecasts:
                total_forecast_energy = sum(f['estimated_energy_kwh'] for f in forecasts.values())
                total_forecast_cost = sum(f['estimated_cost_rub'] for f in forecasts.values())
                total_forecast_income = sum(f['estimated_income_usdt'] for f in forecasts.values())
                total_forecast_profit = sum(f['estimated_profit_rub'] for f in forecasts.values())

                # Рассчитываем среднюю рентабельность
                if total_forecast_cost > 0:
                    avg_profitability = (total_forecast_profit / total_forecast_cost) * 100
                else:
                    avg_profitability = 0

                # Определяем общий уровень достоверности
                confidences = [f.get('confidence', 'medium') for f in forecasts.values()]
                overall_confidence = 'high' if 'high' in confidences else 'medium'

                # Формируем общий прогноз
                combined_forecast = {
                    "period_days": 3,
                    "estimated_energy_kwh": total_forecast_energy,
                    "estimated_cost_rub": total_forecast_cost,
                    "estimated_income_usdt": total_forecast_income,
                    "estimated_profit_rub": total_forecast_profit,
                    "profitability_percentage": avg_profitability,
                    "day_energy": sum(f['day_energy'] for f in forecasts.values()),
                    "night_energy": sum(f['night_energy'] for f in forecasts.values()),
                    "day_rate": forecasts[list(forecasts.keys())[0]]['day_rate'],
                    "night_rate": forecasts[list(forecasts.keys())[0]]['night_rate'],
                    "confidence": overall_confidence
                }

                response_text += f"\n\n{format_profitability_forecast_message(combined_forecast)}"
    else:
        response_text = "❌ Не удалось рассчитать 3-дневную доходность"

    await message.reply(response_text, parse_mode=ParseMode.HTML)


@dp.message(Command("profit24h"))
async def cmd_profit24h(message: types.Message):
    """Обработчик команды /profit24h - показывает 24-часовую доходность на основе реальных данных"""
    logger.info(f"Пользователь {message.from_user.id} запросил 24-часовую доходность")

    # Рассчитываем доходность за последние 24 часа
    end_date = datetime.now()
    start_date = end_date - timedelta(days=1)
    profitability_data = calculate_profitability_for_period(start_date, end_date, "24 часа")

    # Форматируем и отправляем сообщение
    response_text = format_profitability_message(profitability_data)
    await message.reply(response_text, parse_mode=ParseMode.HTML)


@dp.message(Command("profit7d"))
async def cmd_profit7d(message: types.Message):
    """Обработчик команды /profit7d - показывает недельную доходность"""
    logger.info(f"Пользователь {message.from_user.id} запросил недельную доходность")

    # Рассчитываем недельную доходность
    weekly_data, avg_daily_data = calculate_weekly_profitability()

    if weekly_data and avg_daily_data:
        response_text = format_profitability_message(weekly_data, show_details=False)
        response_text += f"\n\n{format_profitability_message(avg_daily_data, show_details=False)}"
    else:
        response_text = "❌ Не удалось рассчитать недельную доходность"

    await message.reply(response_text, parse_mode=ParseMode.HTML)


@dp.message(Command("profit30d"))
async def cmd_profit30d(message: types.Message):
    """Обработчик команды /profit30d - показывает месячную доходность"""
    logger.info(f"Пользователь {message.from_user.id} запросил месячную доходность")

    # Рассчитываем месячную доходность
    monthly_data = calculate_monthly_profitability()

    if monthly_data:
        response_text = format_profitability_message(monthly_data)
    else:
        response_text = "❌ Не удалось рассчитать месячную доходность"

    await message.reply(response_text, parse_mode=ParseMode.HTML)


@dp.message(Command("profitall"))
async def cmd_profitall(message: types.Message):
    """Обработчик команды /profitall - показывает доходность за все периоды"""
    logger.info(f"Пользователь {message.from_user.id} запросил сводную доходность")

    end_date = datetime.now()

    # Рассчитываем доходность за разные периоды
    data_24h = calculate_profitability_for_period(end_date - timedelta(days=1), end_date, "24 часа")
    data_3d = calculate_profitability_for_period(end_date - timedelta(days=3), end_date, "3 дня")
    data_7d = calculate_profitability_for_period(end_date - timedelta(days=7), end_date, "7 дней")
    data_30d = calculate_profitability_for_period(end_date - timedelta(days=30), end_date, "30 дней")

    response_text = "📊 <b>Сводная доходность за все периоды:</b>\n\n"

    for data in [data_24h, data_3d, data_7d, data_30d]:
        if data:
            period_name = data["period_name"]
            net_profit = data.get("net_profit", 0)
            profitability_percentage = data.get("profitability_percentage", 0)
            avg_daily_profit = data.get("avg_daily_profit", net_profit)

            profit_emoji = "🟢" if net_profit >= 0 else "🔴"
            response_text += f"{profit_emoji} <b>{period_name}:</b>\n"
            response_text += f"   💰 Прибыль: {net_profit:.2f} RUB\n"
            response_text += f"   📊 Рентабельность: {profitability_percentage:.2f}%\n"
            response_text += f"   📈 Среднесуточно: {avg_daily_profit:.2f} RUB\n\n"

    await message.reply(response_text, parse_mode=ParseMode.HTML)


@dp.message(Command("today"))
async def cmd_today(message: types.Message):
    """Обработчик команды /today с прогнозом на 24 часа и реальной доходностью"""
    logger.info(f"Пользователь {message.from_user.id} запросил статистику за сегодня")

    # Получаем фактическую статистику за сегодня
    stats = get_today_spending()

    # Получаем текущее потребление для прогноза
    current_consumption = get_current_power_consumption()

    # Рассчитываем реальную доходность за сегодня
    today = datetime.now().date()
    start_date = datetime.combine(today, datetime.min.time())
    end_date = start_date + timedelta(days=1)
    profitability_data = calculate_profitability_for_period(start_date, end_date,
                                                            f"Сегодня ({today.strftime('%d.%m.%Y')})")

    if not stats and not any(loc['total_power_w'] > 0 for loc in current_consumption.values()):
        await message.reply("📊 За сегодня еще нет данных о потреблении и устройства выключены.")
        return

    response_text = f"📊 <b>Статистика за сегодня ({datetime.now().strftime('%d.%m.%Y')}):</b>\n\n"

    # Добавляем информацию о реальной доходности
    if profitability_data:
        total_income_usdt = profitability_data.get("total_income_usdt", 0)
        total_income_rub = profitability_data.get("total_income_rub", 0)
        total_cost = profitability_data.get("total_cost", 0)
        net_profit = profitability_data.get("net_profit", 0)
        profitability_percentage = profitability_data.get("profitability_percentage", 0)
        sales_count = profitability_data.get("sales_count", 0)
        exchange_rate = profitability_data.get("exchange_rate")
        exchange_rate_source = profitability_data.get("exchange_rate_source", "CoinGecko")

        profit_emoji = "🟢" if net_profit >= 0 else "🔴"
        response_text += f"{profit_emoji} <b>Реальная доходность:</b>\n"
        response_text += f"💰 Доход от продаж: {total_income_usdt:.2f} USDT ({total_income_rub:.2f} RUB)\n"
        if exchange_rate:
            response_text += f"💱 Курс: {exchange_rate_source}: {exchange_rate:.2f} руб\n"
        response_text += f"💸 Затраты на электричество: {total_cost:.2f} RUB\n"
        response_text += f"📈 Чистая прибыль: {net_profit:.2f} RUB\n"
        response_text += f"📊 Рентабельность: {profitability_percentage:.2f}%\n"
        response_text += f"🛒 Продажи: {sales_count} шт.\n\n"

    # Если продаж сегодня не было, добавляем прогноз
    if not profitability_data or profitability_data.get("sales_count", 0) == 0:
        # Рассчитываем прогноз на основе текущей мощности
        total_current_power = sum(loc['total_power_w'] for loc in current_consumption.values())

        if total_current_power > 0:
            # Получаем прогноз для каждой локации
            forecasts = {}
            for location, data in current_consumption.items():
                if data['total_power_w'] > 0:
                    # Находим device_id для локации
                    device_id = None
                    for device in DEVICES:
                        if device["location"] == location:
                            device_id = device["device_id"]
                            break

                    forecasts[location] = estimate_profitability(
                        data['total_power_w'], location, device_id
                    )

            # Суммируем прогнозы по всем локациям
            if forecasts:
                total_forecast_energy = sum(f['estimated_energy_kwh'] for f in forecasts.values())
                total_forecast_cost = sum(f['estimated_cost_rub'] for f in forecasts.values())
                total_forecast_income = sum(f['estimated_income_usdt'] for f in forecasts.values())
                total_forecast_profit = sum(f['estimated_profit_rub'] for f in forecasts.values())

                # Рассчитываем среднюю рентабельность
                if total_forecast_cost > 0:
                    avg_profitability = (total_forecast_profit / total_forecast_cost) * 100
                else:
                    avg_profitability = 0

                # Определяем общий уровень достоверности
                confidences = [f.get('confidence', 'medium') for f in forecasts.values()]
                overall_confidence = 'high' if 'high' in confidences else 'medium'

                # Формируем общий прогноз
                combined_forecast = {
                    "period_days": 1,
                    "estimated_energy_kwh": total_forecast_energy,
                    "estimated_cost_rub": total_forecast_cost,
                    "estimated_income_usdt": total_forecast_income,
                    "estimated_profit_rub": total_forecast_profit,
                    "profitability_percentage": avg_profitability,
                    "day_energy": sum(f['day_energy'] for f in forecasts.values()),
                    "night_energy": sum(f['night_energy'] for f in forecasts.values()),
                    "day_rate": forecasts[list(forecasts.keys())[0]]['day_rate'],
                    "night_rate": forecasts[list(forecasts.keys())[0]]['night_rate'],
                    "confidence": overall_confidence
                }

                response_text += f"🔮 <b>Прогноз доходности на сегодня:</b>\n"
                response_text += f"⚡ Прогноз потребления: {total_forecast_energy:.3f} кВт·ч\n"
                response_text += f"💰 Прогноз дохода: {total_forecast_income:.2f} USDT\n"
                response_text += f"💸 Прогноз затрат: {total_forecast_cost:.2f} RUB\n"
                response_text += f"📈 Прогноз прибыли: {total_forecast_profit:.2f} RUB\n"
                response_text += f"📊 Прогноз рентабельности: {avg_profitability:.2f}%\n\n"

    # Обрабатываем все локации
    all_locations = set(stats.keys()).union(current_consumption.keys())

    for location in all_locations:
        response_text += f"📍 <b>{location}</b>\n"

        # Фактическое потребление за сегодня
        if location in stats:
            data = stats[location]
            source = data.get("source", "Database")
            response_text += f"<b>📈 Фактическое за сегодня ({source}):</b>\n"
            response_text += f"⚡ Потребление: {data['total_energy']:.3f} кВт·ч\n"
            response_text += f"💰 Стоимость: {data['total_cost']:.2f} руб.\n"
            response_text += f"☀️ День: {data['day_energy']:.3f} кВт·ч\n"
            response_text += f"🌙 Ночь: {data['night_energy']:.3f} кВт·ч\n\n"

            # Детализация по устройствам
            if data["devices"]:
                response_text += "<b>🔌 Устройства (факт):</b>\n"
                for device_id, device_data in data["devices"].items():
                    response_text += f"• {device_data['name']}: {device_data['energy']:.3f} кВт·ч ({device_data['cost']:.2f} руб.)\n"
                response_text += "\n"

        # Текущее потребление и прогноз
        if location in current_consumption:
            current_data = current_consumption[location]
            current_power = current_data['total_power_w']
            response_text += f"<b>⚡ Текущая мощность:</b> {current_power:.1f} Вт\n"

            if current_power > 0:
                # Находим device_id для локации
                device_id = None
                for device in DEVICES:
                    if device["location"] == location:
                        device_id = device["device_id"]
                        break

                # Рассчитываем прогноз
                forecast = enhanced_estimate_24h_consumption(current_power, location, device_id)
                response_text += f"<b>🔮 Прогноз на 24 часа:</b>\n"
                response_text += f"⚡ Потребление: {forecast['estimated_kwh']:.3f} кВт·ч\n"
                response_text += f"💰 Стоимость: {forecast['estimated_cost']:.2f} руб.\n"
                response_text += f"☀️ День: {forecast['day_energy']:.3f} кВт·ч ({forecast['day_rate']} руб/кВт·ч)\n"
                response_text += f"🌙 Ночь: {forecast['night_energy']:.3f} кВт·ч ({forecast['night_rate']} руб/кВт·ч)\n\n"

                # Детализация по устройствам
                response_text += "<b>🔌 Устройства (текущее):</b>\n"
                for device in current_data['devices']:
                    status_emoji = "🟢" if device['is_on'] else "🔴"
                    response_text += f"{status_emoji} {device['name']}: {device['power_w']:.1f} Вт\n"
            else:
                response_text += "\n<b>🔮 Прогноз на 24 часа:</b>\n"
                response_text += "Все устройства выключены\n"

        response_text += "\n" + "-" * 30 + "\n\n"

    # Добавляем общую сводку
    total_today_energy = sum(data['total_energy'] for data in stats.values())
    total_today_cost = sum(data['total_cost'] for data in stats.values())
    total_current_power = sum(loc['total_power_w'] for loc in current_consumption.values())

    if total_current_power > 0:
        total_forecast = enhanced_estimate_24h_consumption(total_current_power, "Общее")
        response_text += f"<b>📊 ОБЩАЯ СВОДКА:</b>\n"
        response_text += f"Факт за сегодня: {total_today_energy:.3f} кВт·ч ({total_today_cost:.2f} руб.)\n"
        response_text += f"Текущая мощность: {total_current_power:.1f} Вт\n"
        response_text += f"Прогноз на 24ч: {total_forecast['estimated_kwh']:.3f} кВт·ч ({total_forecast['estimated_cost']:.2f} руб.)\n"

        # Рассчитываем экономию/перерасход
        if total_today_energy > 0:
            hours_passed = (datetime.now() - datetime.now().replace(hour=0, minute=0, second=0,
                                                                    microsecond=0)).total_seconds() / 3600
            avg_power = (total_today_energy / hours_passed) * 1000 if hours_passed > 0 else 0
            response_text += f"Средняя мощность: {avg_power:.0f} Вт\n"

    await message.reply(response_text, parse_mode=ParseMode.HTML)


@dp.message(Command("devices"))
async def cmd_devices(message: types.Message):
    """Обработчик команды /devices"""
    logger.info(f"Пользователь {message.from_user.id} запросил статус устройств")

    response_text = "🔌 <b>Текущий статус устройств:</b>\n\n"
    total_power = 0
    active_devices = 0

    for device in DEVICES:
        device_id = device["device_id"]
        device_name = device["name"]
        location = device["location"]

        is_on, counter, device_data = get_device_status_cloud_enhanced(device_id)

        status_emoji = "🟢" if is_on else "🔴"
        response_text += f"{status_emoji} <b>{device_name}</b> ({location})\n"
        response_text += f"ID: {device_id}\n"
        response_text += f"Состояние: {'ВКЛ' if is_on else 'ВЫКЛ'}\n"
        response_text += f"Счетчик: {counter:.3f} кВт·ч\n"

        if device_data:
            if 'cur_power' in device_data:
                power = device_data['cur_power']
                response_text += f"Мощность: {power:.1f} Вт\n"
                if is_on:
                    total_power += power
                    active_devices += 1
            if 'cur_voltage' in device_data:
                response_text += f"Напряжение: {device_data['cur_voltage']:.1f} В\n"
            if 'cur_current' in device_data:
                response_text += f"Ток: {device_data['cur_current']:.2f} А\n"

        response_text += "\n"

    # Добавляем сводку
    response_text += f"<b>📊 СВОДКА:</b>\n"
    response_text += f"Всего устройств: {len(DEVICES)}\n"
    response_text += f"Активных: {active_devices}\n"
    response_text += f"Общая мощность: {total_power:.1f} Вт ({total_power / 1000:.2f} кВт)\n"

    if total_power > 0:
        daily_cost = (total_power / 1000) * 24 * 5.5  # Примерный расчет
        response_text += f"Примерная стоимость за сутки: {daily_cost:.2f} руб."

    await message.reply(response_text, parse_mode=ParseMode.HTML)


@dp.message(Command("add_device"))
async def cmd_add_device(message: types.Message):
    """Обработчик команды /add_device для добавления нового устройства"""
    logger.info(f"Пользователь {message.from_user.id} запросил добавление устройства")
    
    # Проверяем права администратора
    if str(message.from_user.id) != TELEGRAM_ADMIN_ID:
        await message.reply("❌ У вас нет прав для выполнения этой команды.")
        return
    
    # Парсим аргументы команды: /add_device device_id name location
    args = message.text.split()[1:]
    if len(args) < 3:
        await message.reply(
            "❌ Неправильный формат команды.\n"
            "Используйте: /add_device <device_id> <название> <локация>\n"
            "Пример: /add_device bf1234567890abcdef \"Мой риг\" pavlenko"
        )
        return
    
    device_id = args[0]
    name = args[1]
    location = args[2]
    
    # Добавляем устройство в базу данных
    if add_device_to_database(device_id, name, location):
        # Обновляем список устройств
        refresh_devices_from_database()
        await message.reply(
            f"✅ Устройство успешно добавлено!\n"
            f"ID: {device_id}\n"
            f"Название: {name}\n"
            f"Локация: {location}"
        )
    else:
        await message.reply("❌ Ошибка при добавлении устройства. Проверьте логи.")


@dp.message(Command("update_device"))
async def cmd_update_device(message: types.Message):
    """Обработчик команды /update_device для обновления устройства"""
    logger.info(f"Пользователь {message.from_user.id} запросил обновление устройства")
    
    # Проверяем права администратора
    if str(message.from_user.id) != TELEGRAM_ADMIN_ID:
        await message.reply("❌ У вас нет прав для выполнения этой команды.")
        return
    
    # Парсим аргументы команды: /update_device device_id [name] [location] [active]
    args = message.text.split()[1:]
    if len(args) < 2:
        await message.reply(
            "❌ Неправильный формат команды.\n"
            "Используйте: /update_device <device_id> [название] [локация] [active]\n"
            "Пример: /update_device bf1234567890abcdef \"Новое название\" pavlenko true"
        )
        return
    
    device_id = args[0]
    name = args[1] if len(args) > 1 and args[1] != "null" else None
    location = args[2] if len(args) > 2 and args[2] != "null" else None
    is_active = args[3].lower() == "true" if len(args) > 3 else None
    
    # Обновляем устройство в базе данных
    if update_device_in_database(device_id, name, location, is_active):
        # Обновляем список устройств
        refresh_devices_from_database()
        await message.reply(
            f"✅ Устройство {device_id} успешно обновлено!\n"
            f"Обновленные поля: {[k for k, v in [('name', name), ('location', location), ('is_active', is_active)] if v is not None]}"
        )
    else:
        await message.reply("❌ Ошибка при обновлении устройства. Проверьте логи.")


@dp.message(Command("delete_device"))
async def cmd_delete_device(message: types.Message):
    """Обработчик команды /delete_device для удаления устройства"""
    logger.info(f"Пользователь {message.from_user.id} запросил удаление устройства")
    
    # Проверяем права администратора
    if str(message.from_user.id) != TELEGRAM_ADMIN_ID:
        await message.reply("❌ У вас нет прав для выполнения этой команды.")
        return
    
    # Парсим аргументы команды: /delete_device device_id
    args = message.text.split()[1:]
    if len(args) < 1:
        await message.reply(
            "❌ Неправильный формат команды.\n"
            "Используйте: /delete_device <device_id>\n"
            "Пример: /delete_device bf1234567890abcdef"
        )
        return
    
    device_id = args[0]
    
    # Удаляем устройство из базы данных (деактивируем)
    if delete_device_from_database(device_id):
        # Обновляем список устройств
        refresh_devices_from_database()
        await message.reply(f"✅ Устройство {device_id} успешно деактивировано!")
    else:
        await message.reply("❌ Ошибка при удалении устройства. Проверьте логи.")


@dp.message(Command("list_devices"))
async def cmd_list_devices(message: types.Message):
    """Обработчик команды /list_devices для просмотра всех устройств"""
    logger.info(f"Пользователь {message.from_user.id} запросил список устройств")
    
    try:
        # Получаем все устройства из базы данных (включая неактивные)
        response = supabase.table('miner_devices_config').select('*').execute()
        
        if not response.data:
            await message.reply("📋 Устройства не найдены в базе данных.")
            return
        
        devices = response.data
        response_text = "📋 <b>Список всех устройств:</b>\n\n"
        
        for device in devices:
            status_emoji = "🟢" if device.get('is_active', True) else "🔴"
            response_text += f"{status_emoji} <b>{device['name']}</b>\n"
            response_text += f"ID: {device['device_id']}\n"
            response_text += f"Локация: {device['location']}\n"
            response_text += f"Статус: {'Активно' if device.get('is_active', True) else 'Неактивно'}\n"
            response_text += f"Создано: {device.get('created_at', 'N/A')}\n"
            response_text += f"Обновлено: {device.get('updated_at', 'N/A')}\n\n"
        
        await message.reply(response_text, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Ошибка при получении списка устройств: {e}")
        await message.reply("❌ Ошибка при получении списка устройств. Проверьте логи.")


# AI-команды
@dp.message(Command("ai_analyze"))
async def cmd_ai_analyze(message: types.Message):
    """AI-анализ текущей ситуации"""
    logger.info(f"Пользователь {message.from_user.id} запросил AI-анализ")

    # Проверяем, доступен ли хотя бы один AI-провайдер
    if not openai_client and not cerebras_client:
        await message.reply("❌ AI-сервисы недоступны. Проверьте настройки API ключей.")
        return

    try:
        # Получаем текущие данные
        current_consumption = get_current_power_consumption()
        total_power = sum(loc['total_power_w'] for loc in current_consumption.values())

        # Получаем данные о продажах за последние 24 часа
        end_date = datetime.now()
        start_date = end_date - timedelta(days=1)
        sales_data = get_sales_data(start_date, end_date)
        total_income_usdt = sum(float(sale.get("total_received", 0)) for sale in sales_data)

        # Получаем курс валюты
        exchange_rate = ExchangeRateManager.get_usdt_rub_rate()

        # Формируем промпт для AI
        prompt = f"""
        Проанализируй текущую ситуацию майнинг-фермы на основе следующих данных:
        Текущая мощность: {total_power} Вт
        Доход за последние 24 часа: {total_income_usdt} USDT
        Курс USDT/RUB: {exchange_rate} руб
        Локации и устройства:
        """

        for location, data in current_consumption.items():
            prompt += f"\n{location}: {data['total_power_w']} Вт, устройств: {len(data['devices'])}"
            for device in data['devices']:
                prompt += f"\n  - {device['name']}: {device['power_w']} Вт ({'ВКЛ' if device['is_on'] else 'ВЫКЛ'})"

        prompt += """
        Предоставь анализ на русском языке, включающий:
        1. Общую оценку текущей ситуации
        2. Эффективность работы фермы
        3. Потенциальные проблемы или риски
        4. Рекомендации по оптимизации
        5. Прогноз на ближайшие 24 часа
        Ответ структурируй по пунктам с использованием эмодзи.
        """

        # Запрос к AI с использованием резервных провайдеров
        ai_analysis, provider = await make_ai_request(
            system_prompt="Ты - эксперт по анализу криптомайнинга. Отвечай подробно и структурированно на русском языке.",
            user_prompt=prompt,
            temperature=0.7,
            max_tokens=1500
        )

        if ai_analysis:
            # Sanitize the AI response
            sanitized_analysis = sanitize_for_telegram_html(ai_analysis)

            # Format the response
            response_text = f"🤖 <b>AI-Анализ Текущей Ситуации</b> (через {provider})\n\n{sanitized_analysis}"

            # Split the message if it's too long
            message_parts = split_message_for_telegram(response_text)

            # Send each part
            for i, part in enumerate(message_parts):
                try:
                    # Add continuation indicator for multi-part messages
                    if len(message_parts) > 1:
                        part = f"📄 Часть {i + 1}/{len(message_parts)}\n\n{part}"
                    # Try sending with HTML formatting
                    await message.reply(part, parse_mode=ParseMode.HTML)
                except Exception as e:
                    logger.error(f"HTML parsing error in part {i + 1}: {e}")
                    # Fallback to plain text if HTML fails
                    clean_text = re.sub(r'<[^>]*>', '', part)
                    await message.reply(clean_text)
        else:
            await message.reply("❌ Не удалось получить ответ от AI-сервисов. Попробуйте позже.")
    except Exception as e:
        logger.error(f"Ошибка в AI-анализе: {e}")
        await message.reply("❌ Произошла ошибка при выполнении AI-анализа")


@dp.message(Command("ai_forecast"))
async def cmd_ai_forecast(message: types.Message):
    """AI-прогноз энергопотребления"""
    logger.info(f"Пользователь {message.from_user.id} запросил AI-прогноз")

    # Проверяем, доступен ли хотя бы один AI-провайдер
    if not openai_client and not cerebras_client:
        await message.reply("❌ AI-сервисы недоступны. Проверьте настройки API ключей.")
        return

    # Парсим период из команды
    parts = message.text.split()
    period = "24h"  # По умолчанию
    if len(parts) > 1:
        period = parts[1].lower()

    try:
        # Получаем текущие данные
        current_consumption = get_current_power_consumption()
        total_power = sum(loc['total_power_w'] for loc in current_consumption.values())

        # Получаем исторические данные
        historical_data = {}
        for device in DEVICES:
            device_id = device["device_id"]
            pattern = get_historical_consumption_pattern(device_id, 7)
            historical_data[device_id] = pattern

        # Формируем промпт для AI
        prompt = f"""
        Сделай прогноз энергопотребления майнинг-фермы на период {period} на основе следующих данных:
        Текущая общая мощность: {total_power} Вт
        Исторические паттерны потребления (за последние 7 дней):
        """

        for device_id, pattern in historical_data.items():
            device_name = next((d["name"] for d in DEVICES if d["device_id"] == device_id), device_id)
            prompt += f"\n{device_name}:"
            prompt += f"\n  - Среднесуточное потребление: {pattern['daily_total']:.3f} кВт·ч"
            prompt += f"\n  - Пиковые часы: {pattern['peak_hours']}"
            prompt += f"\n  - Эффективность: {pattern['efficiency']:.2f}"

        prompt += f"""
        Учитывай следующие факторы:
        - Текущие погодные условия (если известны)
        - Сезонные колебания
        - Исторические тренды
        - Эффективность устройств
        Предоставь прогноз на русском языке, включающий:
        1. Прогноз общего потребления на период {period}
        2. Ожидаемое распределение по часам
        3. Факторы, влияющие на прогноз
        4. Рекомендации по оптимизации потребления
        5. Уровень уверенности в прогнозе
        Ответ структурируй по пунктам с использованием эмодзи.
        """

        # Запрос к AI с использованием резервных провайдеров
        ai_forecast, provider = await make_ai_request(
            system_prompt="Ты - эксперт по прогнозированию энергопотребления. Отвечай точно и обоснованно на русском языке.",
            user_prompt=prompt,
            temperature=0.5,
            max_tokens=1500
        )

        if ai_forecast:
            # Sanitize the AI response
            sanitized_forecast = sanitize_for_telegram_html(ai_forecast)

            # Format the response
            period_text = {
                "24h": "24 часа",
                "7d": "7 дней",
                "30d": "30 дней"
            }.get(period, period)

            response_text = f"🔮 <b>AI-Прогноз на {period_text}</b> (через {provider})\n\n{sanitized_forecast}"

            # Split the message if it's too long
            message_parts = split_message_for_telegram(response_text)

            # Send each part
            for i, part in enumerate(message_parts):
                try:
                    # Add continuation indicator for multi-part messages
                    if len(message_parts) > 1:
                        part = f"📄 Часть {i + 1}/{len(message_parts)}\n\n{part}"
                    # Try sending with HTML formatting
                    await message.reply(part, parse_mode=ParseMode.HTML)
                except Exception as e:
                    logger.error(f"HTML parsing error in part {i + 1}: {e}")
                    # Fallback to plain text if HTML fails
                    clean_text = re.sub(r'<[^>]*>', '', part)
                    await message.reply(clean_text)
        else:
            await message.reply("❌ Не удалось получить ответ от AI-сервисов. Попробуйте позже.")
    except Exception as e:
        logger.error(f"Ошибка в AI-прогнозе: {e}")
        await message.reply("❌ Произошла ошибка при выполнении AI-прогноза")


@dp.message(Command("ai_optimize"))
async def cmd_ai_optimize(message: types.Message):
    """AI-оптимизация доходности"""
    logger.info(f"Пользователь {message.from_user.id} запросил AI-оптимизацию")

    # Проверяем, доступен ли хотя бы один AI-провайдер
    if not openai_client and not cerebras_client:
        await message.reply("❌ AI-сервисы недоступны. Проверьте настройки API ключей.")
        return

    try:
        # Получаем текущие данные
        current_consumption = get_current_power_consumption()
        total_power = sum(loc['total_power_w'] for loc in current_consumption.values())

        # Получаем данные о доходности за последние 7 дней
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)
        profitability_data = calculate_profitability_for_period(start_date, end_date, "7 дней")

        # Получаем тарифные данные
        tariff_info = {}
        for location in set(device["location"] for device in DEVICES):
            tariff_info[location] = TARIFF_SETTINGS.get(location, {})

        # Формируем промпт для AI
        prompt = f"""
        Проанализируй и предложи план оптимизации доходности майнинг-фермы на основе следующих данных:
        Текущая мощность: {total_power} Вт
        Доходность за последние 7 дней:
        - Общий доход: {profitability_data.get('total_income_usdt', 0):.2f} USDT
        - Общие затраты: {profitability_data.get('total_cost', 0):.2f} RUB
        - Чистая прибыль: {profitability_data.get('net_profit', 0):.2f} RUB
        - Рентабельность: {profitability_data.get('profitability_percentage', 0):.2f}%
        Тарифы по локациям:
        """

        for location, tariff in tariff_info.items():
            prompt += f"\n{location}:"
            if tariff.get("tariff_type") == "day_night":
                ranges = tariff.get("ranges", [])
                if ranges:
                    prompt += f"\n  - Дневной тариф: {ranges[0].get('day_rate', 0)} руб/кВт·ч"
                    prompt += f"\n  - Ночной тариф: {ranges[0].get('night_rate', 0)} руб/кВт·ч"
            else:
                ranges = tariff.get("ranges", [])
                if ranges:
                    prompt += f"\n  - Единый тариф: {ranges[0].get('day_rate', 0)} руб/кВт·ч"

        prompt += """
        Предоставь план оптимизации на русском языке, включающий:
        1. Анализ текущей эффективности
        2. Конкретные рекомендации по:
           - Оптимизации расписания работы устройств
           - Использованию тарифных зон (день/ночь)
           - Повышению эффективности майнинга
           - Снижению затрат на электричество
        3. Оценку потенциального улучшения доходности
        4. Пошаговый план внедрения рекомендаций
        5. Сроки окупаемости предлагаемых мер
        Ответ структурируй по пунктам с использованием эмодзи.
        """

        # Запрос к AI с использованием резервных провайдеров
        ai_optimization, provider = await make_ai_request(
            system_prompt="Ты - эксперт по оптимизации криптомайнинга. Отвечай практично и конкретно на русском языке.",
            user_prompt=prompt,
            temperature=0.7,
            max_tokens=1500
        )

        if ai_optimization:
            # Sanitize the AI response
            sanitized_optimization = sanitize_for_telegram_html(ai_optimization)

            # Format the response
            response_text = f"⚡ <b>AI-Оптимизация Доходности</b> (через {provider})\n\n{sanitized_optimization}"

            # Split the message if it's too long
            message_parts = split_message_for_telegram(response_text)

            # Send each part
            for i, part in enumerate(message_parts):
                try:
                    # Add continuation indicator for multi-part messages
                    if len(message_parts) > 1:
                        part = f"📄 Часть {i + 1}/{len(message_parts)}\n\n{part}"
                    # Try sending with HTML formatting
                    await message.reply(part, parse_mode=ParseMode.HTML)
                except Exception as e:
                    logger.error(f"HTML parsing error in part {i + 1}: {e}")
                    # Fallback to plain text if HTML fails
                    clean_text = re.sub(r'<[^>]*>', '', part)
                    await message.reply(clean_text)
        else:
            await message.reply("❌ Не удалось получить ответ от AI-сервисов. Попробуйте позже.")
    except Exception as e:
        logger.error(f"Ошибка в AI-оптимизации: {e}")
        await message.reply("❌ Произошла ошибка при выполнении AI-оптимизации")


@dp.message(Command("ai_health"))
async def cmd_ai_health(message: types.Message):
    """AI-проверка здоровья системы"""
    logger.info(f"Пользователь {message.from_user.id} запросил AI-проверку здоровья")

    # Проверяем, доступен ли хотя бы один AI-провайдер
    if not openai_client and not cerebras_client:
        await message.reply("❌ AI-сервисы недоступны. Проверьте настройки API ключей.")
        return

    try:
        # Получаем текущие данные по устройствам
        device_status = []
        for device in DEVICES:
            device_id = device["device_id"]
            device_name = device["name"]
            location = device["location"]

            is_on, counter, device_data = get_device_status_cloud_enhanced(device_id)

            status_info = {
                "name": device_name,
                "location": location,
                "is_on": is_on,
                "power": device_data.get('cur_power', 0) if device_data else 0,
                "temperature": device_data.get('cur_voltage', 0) if device_data else 0,
                # Используем напряжение как индикатор
                "counter": counter
            }
            device_status.append(status_info)

        # Формируем промпт для AI
        prompt = """
        Проанализируй здоровье майнинг-фермы на основе статусов устройств:
        """

        for device in device_status:
            status_emoji = "🟢" if device["is_on"] else "🔴"
            prompt += f"\n{status_emoji} {device['name']} ({device['location']}):"
            prompt += f"\n  - Состояние: {'ВКЛ' if device['is_on'] else 'ВЫКЛ'}"
            prompt += f"\n  - Мощность: {device['power']} Вт"
            prompt += f"\n  - Напряжение: {device['temperature']} В"
            prompt += f"\n  - Счетчик: {device['counter']:.3f} кВт·ч"

        prompt += """
        Проверь наличие аномалий и проблем:
        - Устройства с необычно высокой/низкой мощностью
        - Устройства с отклонениями напряжения
        - Резкие изменения в показаниях счетчиков
        - Неработающие устройства
        Предоставь анализ здоровья системы на русском языке, включающий:
        1. Общую оценку состояния системы
        2. Выявленные аномалии или проблемы
        3. Рекомендации по устранению проблем
        4. Профилактические меры
        5. Оценку критичности выявленных проблем
        Ответ структурируй по пунктам с использованием эмодзи.
        """

        # Запрос к AI с использованием резервных провайдеров
        ai_health, provider = await make_ai_request(
            system_prompt="Ты - эксперт по диагностике майнингового оборудования. Отвечай внимательно и профессионально на русском языке.",
            user_prompt=prompt,
            temperature=0.5,
            max_tokens=1500
        )

        if ai_health:
            # Sanitize the AI response
            sanitized_health = sanitize_for_telegram_html(ai_health)

            # Format the response
            response_text = f"🏥 <b>AI-Проверка Здоровья Системы</b> (через {provider})\n\n{sanitized_health}"

            # Split the message if it's too long
            message_parts = split_message_for_telegram(response_text)

            # Send each part
            for i, part in enumerate(message_parts):
                try:
                    # Add continuation indicator for multi-part messages
                    if len(message_parts) > 1:
                        part = f"📄 Часть {i + 1}/{len(message_parts)}\n\n{part}"
                    # Try sending with HTML formatting
                    await message.reply(part, parse_mode=ParseMode.HTML)
                except Exception as e:
                    logger.error(f"HTML parsing error in part {i + 1}: {e}")
                    # Fallback to plain text if HTML fails
                    clean_text = re.sub(r'<[^>]*>', '', part)
                    await message.reply(clean_text)
        else:
            await message.reply("❌ Не удалось получить ответ от AI-сервисов. Попробуйте позже.")
    except Exception as e:
        logger.error(f"Ошибка в AI-проверке здоровья: {e}")
        await message.reply("❌ Произошла ошибка при выполнении AI-проверки здоровья")


# Chat commands
@dp.message(Command("chat"))
async def cmd_chat(message: types.Message):
    """Start a chat session with AI assistant"""
    chat_sessions.clear_session(message.from_user.id)
    await message.reply(
        "🤖 <b>Режим AI-помощника</b>\n\n"
        "Теперь вы можете задавать мне вопросы о вашей майнинг-ферме на естественном русском языке. "
        "Я могу помочь вам со следующей информацией:\n"
        "• Статистика потребления электроэнергии\n"
        "• Анализ доходности\n"
        "• Информация о статусе устройств\n"
        "• Данные о продажах\n\n"
        "Просто напишите ваш вопрос или используйте /clear для сброса диалога.",
        parse_mode=ParseMode.HTML
    )


@dp.message(Command("clear"))
async def cmd_clear(message: types.Message):
    """Clear chat history"""
    chat_sessions.clear_session(message.from_user.id)
    await message.reply("🗑️ История чата очищена. Начните диалог с ваших вопросов!")


@dp.message()
async def handle_natural_chat(message: types.Message):
    """Handle natural language chat messages"""
    # Skip commands
    if message.text.startswith('/'):
        return

    user_id = message.from_user.id
    question = message.text

    # Add user message to history
    chat_sessions.add_message(user_id, 'user', question)

    # Get session context
    session = chat_sessions.get_session(user_id)
    context = session['context']

    # Generate SQL query (now with await)
    sql_result = await nl_to_sql.generate_sql_query(question, context)

    if sql_result:
        # Execute query
        query_result = await nl_to_sql.execute_query(sql_result['sql_query'], sql_result['parameters'])

        # Create response prompt for AI
        response_prompt = f"""
        Пользователь спросил: {question}
        Выполненный SQL-запрос: {sql_result['sql_query']}
        Объяснение запроса: {sql_result['explanation']}
        Результаты запроса: {json.dumps(query_result, indent=2, default=str, ensure_ascii=False)}
        Пожалуйста, предоставь ответ пользователю на естественном русском языке на основе этих результатов.
        Будь полезен, лаконичен и включай релевантные цифры и инсайты.
        """

        # Get AI response
        ai_response, provider = await make_ai_request(
            system_prompt="Ты - полезный помощник по майнинг-ферме. Предоставляй четкие, краткие ответы на основе предоставленных данных.",
            user_prompt=response_prompt,
            temperature=0.5,
            max_tokens=1000
        )

        if ai_response:
            # Add AI response to history
            chat_sessions.add_message(user_id, 'assistant', ai_response)

            # Send response (handle long messages)
            response_text = f"🤖 <b>AI-помощник</b> (via {provider})\n\n{ai_response}"
            message_parts = split_message_for_telegram(response_text)

            # Send each part
            for i, part in enumerate(message_parts):
                try:
                    # Add continuation indicator for multi-part messages
                    if len(message_parts) > 1:
                        part_with_indicator = f"📄 Часть {i + 1}/{len(message_parts)}\n\n{part}"
                    else:
                        part_with_indicator = part
                    # Try sending with HTML formatting
                    await message.reply(part_with_indicator, parse_mode=ParseMode.HTML)
                except Exception as e:
                    logger.error(f"Error sending message part: {e}")
                    clean_text = re.sub(r'<[^>]*>', '', part)
                    await message.reply(clean_text)
        else:
            await message.reply(
                "❌ Извините, я не смог обработать ваш вопрос. Пожалуйста, попробуйте переформулировать.")
    else:
        await message.reply("❌ Я не понял ваш вопрос. Пожалуйста, попробуйте задать его по-другому.")


async def send_admin_notification(text: str):
    """Отправить уведомление администратору"""
    if bot and TELEGRAM_ADMIN_ID:
        try:
            await bot.send_message(TELEGRAM_ADMIN_ID, text)
            logger.info("Уведомление отправлено администратору")
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления: {e}")


async def process_notifications():
    """Обрабатывает очередь уведомлений"""
    while True:
        try:
            if not notification_queue.empty():
                text = await notification_queue.get()
                await send_admin_notification(text)
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"Ошибка обработки уведомлений: {e}")
            await asyncio.sleep(5)


def queue_notification(text: str):
    """Добавляет уведомление в очередь с обработкой ошибки отсутствия event loop"""
    if bot and TELEGRAM_ADMIN_ID:
        try:
            # Проверяем, есть ли event loop
            try:
                loop = asyncio.get_running_loop()
                # Если event loop запущен, используем call_soon_threadsafe
                loop.call_soon_threadsafe(notification_queue.put_nowait, text)
            except RuntimeError:
                # Если нет event loop в текущем потоке, пробуем создать задачу
                try:
                    # Проверяем, запущен ли event loop в основном потоке
                    if asyncio.get_event_loop().is_running():
                        # Если запущен, используем call_soon_threadsafe
                        asyncio.get_event_loop().call_soon_threadsafe(notification_queue.put_nowait, text)
                    else:
                        # Если не запущен, создаем задачу
                        asyncio.create_task(notification_queue.put(text))
                except:
                    # Если и это не сработало, просто логируем без эмодзи
                    clean_text = text.encode('ascii', 'ignore').decode('ascii')
                    logger.warning(f"Не удалось отправить уведомление (нет event loop): {clean_text}")
        except Exception as e:
            # В случае ошибки, логируем без эмодзи
            clean_text = text.encode('ascii', 'ignore').decode('ascii')
            logger.error(f"Ошибка добавления уведомления в очередь: {e}")


def safe_log(message: str, level: str = "info"):
    """Безопасное логирование с поддержкой эмодзи"""
    try:
        if level == "info":
            logger.info(message)
        elif level == "warning":
            logger.warning(message)
        elif level == "error":
            logger.error(message)
        elif level == "debug":
            logger.debug(message)
    except UnicodeEncodeError:
        # Если возникает ошибка кодировки, удаляем эмодзи
        clean_message = message.encode('ascii', 'ignore').decode('ascii')
        if level == "info":
            logger.info(clean_message)
        elif level == "warning":
            logger.warning(clean_message)
        elif level == "error":
            logger.error(clean_message)
        elif level == "debug":
            logger.debug(clean_message)


def monitor_devices():
    """Основная функция мониторинга устройств"""
    global device_states, last_counters, monitoring_active
    safe_log("Запуск мониторинга устройств (облачный режим)...")

    # Инициализация состояний
    for device in DEVICES:
        device_id = device["device_id"]
        device_name = device["name"]
        location = device["location"]

        safe_log(f"Инициализация устройства: {device_name} ({device_id})")
        is_on, counter, device_data = safe_get_device_data(device_id)

        device_states[device_id] = {
            "name": device_name,
            "location": location,
            "last_state": is_on,
            "last_counter": counter,
            "session_start": datetime.now() if is_on else None
        }
        last_counters[device_id] = counter

        safe_log(f"Устройство {device_name} инициализировано: состояние={'ВКЛ' if is_on else 'ВЫКЛ'}, "
                 f"счетчик={counter:.3f} кВт·ч")

    # Отправляем уведомление о запуске
    queue_notification("Мониторинг устройств запущен")

    # Основной цикл мониторинга
    while monitoring_active:
        try:
            logger.debug("Цикл мониторинга...")

            # Проверяем статус API
            api_status = api_limiter.get_status()
            if api_status['requests_today'] >= api_status['daily_limit'] * 0.9:
                logger.warning(
                    f"Достигнут 90% лимит API запросов: {api_status['requests_today']}/{api_status['daily_limit']}")
                queue_notification(
                    f"Внимание! Достигнут 90% лимит API запросов: {api_status['requests_today']}/{api_status['daily_limit']}")

            for device in DEVICES:
                device_id = device["device_id"]
                device_name = device["name"]
                location = device["location"]

                is_on, counter, device_data = safe_get_device_data(device_id)

                if device_id not in device_states:
                    logger.warning(f"Устройство {device_id} не найдено в состояниях, инициализация...")
                    device_states[device_id] = {
                        "name": device_name,
                        "location": location,
                        "last_state": is_on,
                        "last_counter": counter,
                        "session_start": datetime.now() if is_on else None
                    }
                    last_counters[device_id] = counter
                    continue

                state = device_states[device_id]

                # Проверка изменения состояния (включение/выключение)
                if is_on != state["last_state"]:
                    if is_on:
                        # Устройство включилось
                        state["session_start"] = datetime.now()
                        state["last_state"] = True
                        safe_log(f"{device_name} включился в {state['session_start']}")
                        queue_notification(f"{device_name} включился")
                    else:
                        # Устройство выключилось
                        if state["session_start"]:
                            end_time = datetime.now()
                            energy_kwh = counter - state["last_counter"]

                            safe_log(f"{device_name} выключился в {end_time}")
                            safe_log(f"Сессия: энергия={energy_kwh:.3f} кВт·ч, "
                                     f"длительность={end_time - state['session_start']}")

                            if energy_kwh > 0:
                                try:
                                    cost, day_energy, night_energy, cost_details = calculate_session_cost(
                                        device_id, location, state["session_start"], end_time, energy_kwh
                                    )

                                    save_session(
                                        device_id,
                                        location,
                                        state["session_start"],
                                        end_time,
                                        energy_kwh,
                                        cost,
                                        cost_details["tariff_type"],
                                        day_energy,
                                        night_energy,
                                        cost_details
                                    )

                                    # Отправляем уведомление о сессии
                                    notification = (
                                        f"{device_name} выключился\n"
                                        f"Энергия: {energy_kwh:.3f} кВт·ч\n"
                                        f"Стоимость: {cost:.2f} руб.\n"
                                        f"Длительность: {end_time - state['session_start']}"
                                    )
                                    queue_notification(notification)
                                except Exception as e:
                                    logger.error(f"Ошибка при обработке сессии устройства {device_name}: {e}")
                            else:
                                logger.warning(f"{device_name}: нулевое потребление за сессии")

                        state["last_state"] = False
                        state["session_start"] = None

                # Обновляем счетчик, если он изменился
                if abs(counter - last_counters.get(device_id,
                                                   0)) > 0.001:  # Добавляем небольшую дельту для избежания проблем с плавающей запятой
                    logger.debug(
                        f"Счетчик устройства {device_name} обновлен: {last_counters.get(device_id, 0)} -> {counter}")
                    last_counters[device_id] = counter

            # Расчет дневной доходности (каждый час в начале минуты)
            current_time = datetime.now()
            if current_time.minute == 0 and current_time.second < 30:
                logger.info("Запуск расчета дневной доходности...")
                try:
                    calculate_daily_profitability(current_time.date())
                except Exception as e:
                    logger.error(f"Ошибка расчета дневной доходности: {e}")

            # Расчет недельной доходности (каждый день в 00:01)
            if current_time.hour == 0 and current_time.minute == 1 and current_time.second < 30:
                logger.info("Запуск расчета недельной доходности...")
                try:
                    calculate_weekly_profitability()
                except Exception as e:
                    logger.error(f"Ошибка расчета недельной доходности: {e}")

            # Расчет месячной доходности (каждый день в 00:02)
            if current_time.hour == 0 and current_time.minute == 2 and current_time.second < 30:
                logger.info("Запуск расчета месячной доходности...")
                try:
                    calculate_monthly_profitability()
                except Exception as e:
                    logger.error(f"Ошибка расчета месячной доходности: {e}")

            time.sleep(30)  # Проверяем каждые 30 секунд
        except KeyboardInterrupt:
            logger.info("Мониторинг остановлен пользователем")
            monitoring_active = False
            queue_notification("Мониторинг остановлен")
            break
        except Exception as e:
            logger.error(f"Ошибка в цикле мониторинга: {e}", exc_info=True)
            time.sleep(60)  # Ждем минуту перед повторной попыткой


def test_tuya_api_methods():
    """Тестирование различных методов Tuya API для определения правильной сигнатуры"""
    logger.info("Тестирование методов Tuya API...")

    # Берем первое устройство для тестов
    if not DEVICES:
        logger.error("Нет устройств для тестирования")
        return

    device_id = DEVICES[0]["device_id"]

    # Тестируем разные варианты вызова getdevicelog
    start_ms = int((datetime.now() - timedelta(days=1)).timestamp() * 1000)
    end_ms = int(datetime.now().timestamp() * 1000)

    try:
        # Вариант 1: device_id как первый аргумент
        logger.info("Тестирование варианта 1: device_id как первый аргумент")
        response = tuya_cloud.getdevicelog(device_id, start=start_ms, end=end_ms, type="7")
        logger.info(f"Результат варианта 1: {response}")
    except Exception as e:
        logger.error(f"Ошибка варианта 1: {e}")

    try:
        # Вариант 2: id как именованный аргумент
        logger.info("Тестирование варианта 2: id как именованный аргумент")
        response = tuya_cloud.getdevicelog(id=device_id, start=start_ms, end=end_ms, type="7")
        logger.info(f"Результат варианта 2: {response}")
    except Exception as e:
        logger.error(f"Ошибка варианта 2: {e}")

    try:
        # Вариант 3: device_id как именованный аргумент
        logger.info("Тестирование варианта 3: device_id как именованный аргумент")
        response = tuya_cloud.getdevicelog(device_id=device_id, start=start_ms, end=end_ms, type="7")
        logger.info(f"Результат варианта 3: {response}")
    except Exception as e:
        logger.error(f"Ошибка варианта 3: {e}")


async def session_cleanup_task():
    """Background task to clean up inactive chat sessions"""
    while True:
        try:
            chat_sessions.auto_clear_inactive()
            await asyncio.sleep(300)  # Check every 5 minutes
        except Exception as e:
            logger.error(f"Error in session cleanup: {e}")
            await asyncio.sleep(60)


async def main():
    """Основная асинхронная функция"""
    # Setup bot commands
    await setup_bot_commands()

    # Start background tasks
    cleanup_task = asyncio.create_task(session_cleanup_task())

    # Запускаем обработчик уведомлений
    notification_task = asyncio.create_task(process_notifications())

    # Запускаем мониторинг в отдельном потоке
    import threading
    monitor_thread = threading.Thread(target=monitor_devices)
    monitor_thread.daemon = True
    monitor_thread.start()

    # Запускаем бота
    if bot:
        logger.info("Запуск Telegram бота...")
        await dp.start_polling(bot)
    else:
        logger.info("Telegram бот не настроен, ожидание...")
        while True:
            await asyncio.sleep(60)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
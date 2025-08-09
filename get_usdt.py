import os
import logging
from pycoingecko import CoinGeckoAPI

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_usdt_rub_rate_from_coingecko():
    """Получение курса USDT/RUB с CoinGecko (рыночный курс, не P2P)"""
    try:
        cg = CoinGeckoAPI()
        # Получение цены USDT в RUB
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

def get_usdt_rub_rate():
    """Основная функция для получения курса USDT/RUB"""
    logger.info("Получение курса USDT/RUB с CoinGecko...")
    return get_usdt_rub_rate_from_coingecko()

if __name__ == "__main__":
    # Получение и вывод курса
    rate = get_usdt_rub_rate()
    if rate is not None:
        print(f"\nТекущий курс продажи USDT за RUB: {rate}")
    else:
        print("\nНе удалось получить курс USDT/RUB")
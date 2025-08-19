# Настройка конфигурации устройств в Supabase

## Обзор

Проект `minerRealCalculator` теперь использует базу данных Supabase для хранения конфигурации устройств вместо JSON файла. Это обеспечивает:

- Централизованное управление устройствами
- Возможность добавления/удаления устройств без перезапуска приложения
- Аудит изменений с временными метками
- Безопасность через права доступа

## Установка

### 1. Создание таблицы в Supabase

Выполните SQL скрипт `miner_devices_config.sql` в вашей базе данных Supabase:

```sql
-- Выполните этот скрипт в SQL Editor Supabase
-- Файл: miner_devices_config.sql
```

### 2. Проверка переменных окружения

Убедитесь, что в вашем `.env` файле настроены следующие переменные:

```env
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_anon_key
TUYA_ACCESS_ID=your_tuya_access_id
TUYA_ACCESS_SECRET=your_tuya_access_secret
TUYA_API_REGION=eu
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_ADMIN_ID=your_telegram_user_id
```

**Важно:** Переменная `DEVICES_CONFIG_PATH` больше не требуется.

## Структура таблицы

Таблица `miner_devices_config` содержит следующие поля:

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | BIGINT | Автоинкрементный первичный ключ |
| `device_id` | VARCHAR(255) | Уникальный ID устройства из Tuya Cloud |
| `name` | VARCHAR(255) | Человекочитаемое название устройства |
| `location` | VARCHAR(255) | Локация устройства (например, "pavlenko") |
| `is_active` | BOOLEAN | Статус активности устройства |
| `created_at` | TIMESTAMP | Время создания записи |
| `updated_at` | TIMESTAMP | Время последнего обновления |

## Управление устройствами

### Через Telegram бот

#### Добавление устройства
```
/add_device <device_id> <название> <локация>
```
Пример:
```
/add_device bf1234567890abcdef "Мой риг" pavlenko
```

#### Обновление устройства
```
/update_device <device_id> [название] [локация] [active]
```
Примеры:
```
/update_device bf1234567890abcdef "Новое название"
/update_device bf1234567890abcdef null "sevastopolskaya" true
```

#### Удаление устройства
```
/delete_device <device_id>
```
**Примечание:** Устройство не удаляется физически, а помечается как неактивное.

#### Просмотр всех устройств
```
/list_devices
```

### Через базу данных

#### Добавление устройства
```sql
INSERT INTO miner_devices_config (device_id, name, location) 
VALUES ('bf1234567890abcdef', 'Название устройства', 'локация');
```

#### Обновление устройства
```sql
UPDATE miner_devices_config 
SET name = 'Новое название', location = 'новая_локация' 
WHERE device_id = 'bf1234567890abcdef';
```

#### Деактивация устройства
```sql
UPDATE miner_devices_config 
SET is_active = false 
WHERE device_id = 'bf1234567890abcdef';
```

## Миграция с JSON

Если у вас уже есть файл `devices_config.json`, данные автоматически импортируются при выполнении SQL скрипта. Если нужно добавить дополнительные устройства, используйте команды бота или SQL.

## Безопасность

- Команды управления устройствами доступны только администратору (проверяется `TELEGRAM_ADMIN_ID`)
- Все изменения логируются
- Устройства не удаляются физически, а помечаются как неактивные

## Мониторинг

### Логи
Все операции с устройствами логируются в `mining_calculator.log`:
- Загрузка конфигурации
- Добавление/обновление/удаление устройств
- Ошибки подключения к базе данных

### Статус
Команда `/devices` показывает текущий статус всех активных устройств.

## Устранение неполадок

### Ошибка подключения к Supabase
1. Проверьте `SUPABASE_URL` и `SUPABASE_KEY` в `.env`
2. Убедитесь, что база данных доступна
3. Проверьте права доступа к таблице `miner_devices_config`

### Устройства не загружаются
1. Проверьте, что таблица создана
2. Убедитесь, что есть активные устройства (`is_active = true`)
3. Проверьте логи на наличие ошибок

### Команды бота не работают
1. Проверьте `TELEGRAM_ADMIN_ID` в `.env`
2. Убедитесь, что бот запущен
3. Проверьте права доступа к базе данных

## Примеры использования

### Добавление нового майнинг-рига
```
/add_device bf9876543210fedcba "RTX 4090 Rig" pavlenko
```

### Перемещение устройства
```
/update_device bf9876543210fedcba null "sevastopolskaya"
```

### Временное отключение устройства
```
/update_device bf9876543210fedcba null null false
```

### Восстановление устройства
```
/update_device bf9876543210fedcba null null true
```

# Guacamole Lab Portal (MVP)

MVP-портал для учебного стенда с Eltex-роутерами:
- администратор загружает конфиги на выбранные устройства;
- администратор создает/включает/выключает лабораторные;
- студент выбирает лабораторную и отправляет работу на проверку;
- сервер выгружает конфиг устройства, проверяет по правилам и выдает балл.

## Запуск

1. Установить зависимости:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Запустить:

```bash
export APP_SESSION_SECRET='replace-with-strong-random-secret'
export GUACAMOLE_BASE_URL='http://<server-ip>:8080/guacamole'
export TFTP_ROOT_PATH='/srv/tftp'
export SER2NET_TELNET_TIMEOUT_SEC='3'
export ELTEX_USERNAME='admin'
export ELTEX_PASSWORD='admin_password'
# optional (if device requires enable)
export ELTEX_ENABLE_PASSWORD='enable_password'
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

3. Открыть:
- <http://localhost:8000>

## Тестовые пользователи

- admin / admin123
- student1 / student123

## Что реализовано

- RBAC по ролям `admin` и `student`.
- 36 устройств создаются автоматически при первом старте.
- Админ:
  - массовая загрузка конфига на выбранные устройства;
  - назначение устройства студенту;
  - создание и переключение активности лабораторных.
- Студент:
  - выбор лабораторной и сдача;
  - просмотр последних результатов.
- Проверка:
  - правила в формате regex по строкам;
  - подсчет процента выполнения;
  - хранение результатов в БД.

## Интеграция с ser2net

В `fetch_running_config()` включена реальная попытка подключения к устройству через `ser2net` (telnet на `device.host:device.port`) и выполнение:
- `terminal length 0`
- `show running-config`

Если устройство недоступно или не удалось пройти логин, включается fallback на тестовый конфиг с предупреждением в тексте.

## Важно для продакшена

Сейчас заливка в `apply_config_to_device()` по-прежнему сохраняет файл как TFTP-артефакт (без отправки команд на устройство).  
Для полного продакшена стоит добавить реальную push-логику (через CLI-команды или `copy tftp running-config`).

Дополнительно уже учтено:
- URL Guacamole вынесен в `GUACAMOLE_BASE_URL`, чтобы портал работал с внешним адресом;
- секрет сессий вынесен в `APP_SESSION_SECRET`;
- путь TFTP артефактов вынесен в `TFTP_ROOT_PATH`;
- при переназначении устройства студенту автоматически снимается старая привязка (1 студент -> 1 устройство).

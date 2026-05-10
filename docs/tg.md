# 📱 Telegram Bot

**BEN Fraud Monitor** — Telegram-бот для мониторинга мошенничества в банке BEN.
Получает уведомления о новых кейсах, позволяет расследовать жалобы
и просматривать профили мошенников прямо в мессенджере.

---

## 🏗 Архитектура

Бот построен на **aiogram 3.x** с FSM, роутерами и dependency injection через `dp["key"]`.
Параллельно с ботом запускается `FraudPoller` — фоновая задача на `asyncio.TaskGroup`,
которая каждые 60 секунд проверяет новые жалобы и рассылает уведомления операторам.

```
main.py  ──►  Dispatcher (aiogram)  ──►  handlers: auth / cases / admin
          └►  FraudPoller           ──►  services: api_client / db / poller / formatter
```

### Ключевые решения

| Проблема | Решение |
|---|---|
| TG недоступен в РФ | `socks5://127.0.0.1:10808` (v2rayN) |
| VPN перехватывал localhost | `AsyncHTTPTransport(retries=1)` без системных прокси |
| bcrypt не собирается на Python 3.14 | SHA-256 + соль |
| Подчёркивания в именах ломали Markdown | `parse_mode=None` + `_escape_md()` |
| FSM перехватывал кнопки меню | Проверка `_MENU_BUTTONS` перед обработкой ввода |

---

## 🔐 Хэндлеры

### Авторизация

`/start`, вход по логину/паролю, выход. FSM-состояния: `LoginFSM.login` → `LoginFSM.password`.
После успешного входа `telegram_id` привязывается в `bot_users.db` — с этого момента оператор получает уведомления.

::: auth
    options:
      show_root_heading: true
      show_source: true

---

### Жалобы и расследования

Три точки входа для расследования: кнопка меню → FSM, инлайн-кнопка из списка жалоб, команда `/case <ID>`.

::: cases
    options:
      show_root_heading: true
      show_source: true

---

### Администрирование

Управление пользователями: добавление, удаление, привязка Telegram ID вручную.

::: admin
    options:
      show_root_heading: true
      show_source: true

---

## 🛠 Сервисы

### Клиент BEN API

Асинхронная обёртка над всеми эндпоинтами BEN API. Авторизация через Bearer-токен.

::: api_client
    options:
      show_root_heading: true
      show_source: true

---

### База пользователей

Работа с `bot_users.db`: авторизация, привязка Telegram ID, управление пользователями.

::: db
    options:
      show_root_heading: true
      show_source: true

---

### Поллер новых жалоб

Фоновая задача: каждые 60 секунд проверяет новые жалобы и рассылает сводку операторам.

::: poller
    options:
      show_root_heading: true
      show_source: true

---

### Форматирование сообщений

Все Telegram-сообщения бота. Только форматирование — никакой бизнес-логики.

::: formatter
    options:
      show_root_heading: true
      show_source: true
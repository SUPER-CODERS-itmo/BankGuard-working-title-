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

---

## 🚀 Точка входа

::: main
    options:
      show_root_heading: true
      show_source: false

---

## ⚙️ Конфигурация

::: config
    options:
      show_root_heading: true
      show_source: false

---

## 🔐 Хэндлеры

### Авторизация
::: auth
    options:
      show_root_heading: true
      show_source: true

### Жалобы и расследования
::: cases
    options:
      show_root_heading: true
      show_source: true

### Администрирование
::: admin
    options:
      show_root_heading: true
      show_source: true

---

## 🛠 Сервисы

### Клиент BEN API
::: api_client
    options:
      show_root_heading: true
      show_source: true

### База пользователей
::: db
    options:
      show_root_heading: true
      show_source: true

### Поллер новых жалоб
::: poller
    options:
      show_root_heading: true
      show_source: true

### Форматирование сообщений
::: formatter
    options:
      show_root_heading: true
      show_source: true
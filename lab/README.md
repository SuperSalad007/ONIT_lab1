# Трекер задач для ВКР — подробное описание проекта

## 1. Зачем этот проект

Это учебный (лабораторный) **веб-трекер задач** для выпускной работы. Вы открываете сайт в браузере, добавляете задачи по ВКР, отмечаете выполнение, видите просроченные дедлайны. Данные **не пропадают** после перезапуска — они лежат в **PostgreSQL** в Docker-volume.

Параллельно показана **продакшен-подобная** схема: приложение в контейнере, БД отдельно, **мониторинг** (Prometheus, Grafana, cAdvisor, postgres-exporter).

---

## 2. Структура папок

```text
lab/
  docker-compose.yml      — «дирижёр»: поднимает все контейнеры сразу
  app/
    main.py               — логика сайта и API (FastAPI)
    requirements.txt      — список Python-библиотек
    Dockerfile            — рецепт сборки образа приложения
  prometheus/
    prometheus.yml        — откуда Prometheus забирает метрики
    docker-compose.yml    — ссылка на основной compose (можно не трогать)
```

Корень репозитория (`pythonProjectLabOnit`) — проект PyCharm; **рабочая часть лабораторной** — папка `lab/`.

---

## 3. Общая схема: как всё связано

- **Браузер** общается с **app** (порт 8000 на вашем компьютере).
- **app** внутри Docker-сети обращается к **db** по имени хоста `db` (не `localhost`).
- **Prometheus** опрашивает app, cAdvisor и postgres-exporter по внутренним именам сервисов.
- **Grafana** строит графики по данным Prometheus (источник данных настраивается в UI).

---

## 4. Docker Compose: шесть сервисов

Файл: `docker-compose.yml`.

| Сервис | Контейнер | Порт в браузере | Назначение |
|--------|-----------|-----------------|------------|
| **app** | task-tracker-app | **8000** | Сайт + `/health` + `/metrics` |
| **db** | task-tracker-db | не открыт наружу | PostgreSQL, таблица `tasks` |
| **prometheus** | task-tracker-prometheus | **9090** | Хранение и сбор метрик |
| **grafana** | task-tracker-grafana | **3000** | Дашборды и графики |
| **cadvisor** | task-tracker-cadvisor | **8080** | CPU/RAM контейнеров |
| **postgres-exporter** | task-tracker-pg-exporter | не открыт | Метрики PostgreSQL для Prometheus |

### Настройки (важно для защиты лабы)

- **`networks: app-network`** — сервисы видят друг друга по имени (`db`, `app`, …).
- **`restart: unless-stopped`** — контейнеры поднимаются после перезагрузки ПК, если их не останавливали вручную.
- **`depends_on` + `condition: service_healthy`** — app ждёт готовности PostgreSQL; prometheus ждёт здоровый app.
- **Volumes**:
  - `pg` — файлы БД на диске → задачи сохраняются при `docker compose restart`.
  - `prometheus-data`, `grafana-data` — история и настройки мониторинга.

### Переменные окружения БД

- В **db**: `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`.
- В **app**: `DATABASE_URL=postgresql://taskuser:taskpassword@db:5432/taskdb` — хост **`db`** = имя сервиса в compose.

---

## 5. Приложение FastAPI (`app/main.py`)

### Технологии

- **FastAPI** — маршруты и формы.
- **Uvicorn** — HTTP-сервер (запуск в Dockerfile).
- **psycopg** — работа с PostgreSQL.
- **prometheus-fastapi-instrumentator** — эндпоинт **`/metrics`**.
- **python-multipart** — приём HTML-форм (POST).

### Старт (`lifespan` + `init_db`)

При запуске контейнера вызывается `init_db()` и создаётся таблица **`tasks`**, если её ещё нет:

| Поле | Тип | Смысл |
|------|-----|--------|
| id | SERIAL | Уникальный номер |
| title | VARCHAR(255) | Название (обязательно) |
| deadline | TIMESTAMP | Дедлайн (может быть пустым) |
| comment | TEXT | Комментарий |
| is_completed | BOOLEAN | Выполнена или нет |
| created_at | TIMESTAMP | Дата создания (сортировка «новые сверху») |

Если БД недоступна — приложение не стартует (`docker compose logs app`).

### Главная страница

Функция `get_html_page()` собирает HTML в Python (CSS в `<style>`).

**Блоки на http://localhost:8000/**:

1. Шапка — заголовок проекта.
2. Статистика — всего / выполнено / просрочено.
3. Форма «Добавить задачу» — название*, дедлайн, комментарий.
4. Список задач — чекбокс, метаданные, удаление (корзина).
5. Подвал — ссылки `/metrics`, `/health`.

**Визуальные правила:**

- **completed** — зачёркнуто, серый стиль.
- **overdue** — красная подсветка, если дедлайн прошёл и задача не выполнена.
- `_ensure_aware()` — корректное сравнение дат с текущим временем (UTC).

Сортировка: `ORDER BY created_at DESC`.

### Маршруты сервера

| Метод | URL | Действие |
|-------|-----|----------|
| GET | `/` | Форма + список |
| POST | `/tasks` | Создать задачу |
| POST | `/tasks/{id}/toggle` | Переключить выполнение |
| POST | `/tasks/{id}/delete` | Удалить задачу |
| GET | `/health` | JSON: сервис и БД |
| GET | `/metrics` | Метрики для Prometheus |

Формы: чекбокс отправляет POST на toggle; после POST — редирект 303 на `/` (POST-Redirect-GET). Текст задач экранируется через `html.escape()`.

### Healthcheck

- `/health` выполняет `SELECT 1` в БД; при ошибке — HTTP **503**.
- Docker каждые 30 с проверяет `/health` через Python (в образе нет `curl`).

---

## 6. Dockerfile приложения

1. Образ `python:3.12-slim`.
2. Установка зависимостей из `requirements.txt`.
3. Копирование кода.
4. Запуск: `uvicorn main:app --host 0.0.0.0 --port 8000` (`0.0.0.0` нужен для доступа из Docker).

---

## 7. Адреса в браузере

| URL | Назначение |
|-----|------------|
| http://localhost:8000/ | Трекер задач (основной интерфейс) |
| http://localhost:8000/docs | Swagger — документация API |
| http://localhost:8000/redoc | ReDoc — альтернативная документация |
| http://localhost:8000/metrics | Метрики приложения |
| http://localhost:8000/health | Проверка здоровья |
| http://localhost:9090 | Prometheus (Graph, Status → Targets) |
| http://localhost:3000 | Grafana (admin / admin по умолчанию) |
| http://localhost:8080 | cAdvisor — нагрузка контейнеров |

**Prometheus Targets** (должны быть UP): `fastapi-app`, `cadvisor`, `postgres`, `prometheus`.

**Grafana:** Connections → Data sources → Prometheus → URL `http://prometheus:9090`.

---

## 8. Зависимости Python

См. `app/requirements.txt`: fastapi, uvicorn, psycopg, prometheus-fastapi-instrumentator, python-multipart.

---

## 9. Сценарий «от клика до диска»

1. POST `/tasks` из формы.
2. `create_task` → INSERT в `tasks` → commit.
3. Redirect на GET `/`.
4. SELECT с сортировкой по `created_at DESC`.
5. Данные в volume `pg` переживают перезапуск контейнера **db**.

---

## 10. Команды

Из папки `lab/`:

```powershell
docker compose up -d --build   # запуск
docker compose ps                # статус
docker compose logs app          # логи приложения
docker compose down              # остановка (данные БД остаются)
docker compose down -v           # остановка + удаление volumes
```

---

## 11. Кратко для защиты

Контейнеризованный трекер на FastAPI с PostgreSQL (volume), HTML-формы, мониторинг через Prometheus (app, cAdvisor, postgres-exporter) и Grafana, healthcheck `/health` и `depends_on: service_healthy`.

---

## 12. Чего нет в проекте

- Нет логина и отдельных пользователей.
- Нет отдельного фронтенда (React) — всё в `main.py`.
- Нет JSON REST API для клиентов (кроме `/health`, `/metrics`).
- Готовые дашборды Grafana в репозитории не хранятся — настраиваются в UI.

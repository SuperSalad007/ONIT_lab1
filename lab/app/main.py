"""
Трекер задач для ВКР - FastAPI приложение
==========================================
Это основное приложение, которое:
- Подключается к PostgreSQL
- Показывает HTML-страницу с задачами
- Позволяет добавлять, отмечать и удалять задачи
- Отдаёт метрики для Prometheus
"""

import os
import html
import logging
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator

# psycopg - библиотека для работы с PostgreSQL
import psycopg

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Параметры подключения к базе данных из переменных окружения
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://taskuser:taskpassword@db:5432/taskdb"
)


# ============================================================
# ФУНКЦИЯ ИНИЦИАЛИЗАЦИИ БАЗЫ ДАННЫХ
# ============================================================
def _ensure_aware(dt: datetime | None) -> datetime | None:
    """Приводит datetime из БД к UTC для сравнения с «сейчас»."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def init_db():
    """
    Создаёт таблицу tasks в базе данных, если её ещё нет.
    Вызывается при запуске приложения.
    """
    logger.info("Инициализация базы данных...")
    try:
        conn = psycopg.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id SERIAL PRIMARY KEY,
                title VARCHAR(255) NOT NULL,
                deadline TIMESTAMP,
                comment TEXT,
                is_completed BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        cursor.close()
        conn.close()
        logger.info("База данных успешно инициализирована!")
    except Exception as e:
        logger.error(f"Ошибка инициализации БД: {e}")
        raise


# ============================================================
# LIFESPAN - ЖИЗНЕННЫЙ ЦИКЛ ПРИЛОЖЕНИЯ
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Выполняется при старте приложения.
    Здесь мы инициализируем базу данных.
    """
    init_db()
    yield
    # Код здесь выполнится при остановке приложения


# ============================================================
# СОЗДАНИЕ FASTAPI ПРИЛОЖЕНИЯ
# ============================================================
app = FastAPI(
    title="Трекер задач для ВКР",
    description="Приложение для управления задачами выпускной квалификационной работы",
    version="1.0.0",
    lifespan=lifespan
)

# Подключаем Prometheus-метрики
Instrumentator().instrument(app).expose(app)


# ============================================================
# ФУНКЦИЯ ПОЛУЧЕНИЯ ВСЕХ ЗАДАЧ
# ============================================================
def get_all_tasks():
    """Получает все задачи из базы данных, новые сверху."""
    conn = psycopg.connect(DATABASE_URL)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, title, deadline, comment, is_completed, created_at
        FROM tasks
        ORDER BY created_at DESC
    """)
    tasks = cursor.fetchall()
    cursor.close()
    conn.close()
    return tasks


# ============================================================
# HTML-ШАБЛОН СТРАНИЦЫ
# ============================================================
def get_html_page(tasks: list) -> str:
    """
    Генерирует HTML-страницу со списком задач и формой добавления.
    """
    now = datetime.now(timezone.utc)

    # Формируем HTML для каждой задачи
    tasks_html = ""
    for task in tasks:
        task_id, title, deadline, comment, is_completed, created_at = task

        # Определяем CSS-классы
        css_classes = "task-item"
        if is_completed:
            css_classes += " completed"
        elif _ensure_aware(deadline) and _ensure_aware(deadline) < now:
            css_classes += " overdue"

        # Экранируем HTML-символы для безопасности
        safe_title = html.escape(title)
        safe_comment = html.escape(comment) if comment else ""

        # Форматируем дедлайн
        deadline_str = ""
        if deadline:
            deadline_str = deadline.strftime("%d.%m.%Y %H:%M")

        # Форматируем дату создания
        created_str = created_at.strftime("%d.%m.%Y %H:%M") if created_at else ""

        # Статус выполнения
        checked = "checked" if is_completed else ""

        tasks_html += f"""
        <div class="{css_classes}">
            <div class="task-header">
                <form method="POST" action="/tasks/{task_id}/toggle" class="toggle-form">
                    <input type="checkbox" class="task-checkbox" {checked}
                           onchange="this.form.submit()">
                </form>
                <div class="task-content">
                    <span class="task-title">{safe_title}</span>
                    <div class="task-meta">
                        <span class="task-date">📅 Создано: {created_str}</span>
                        {"<span class='task-deadline'>⏰ Дедлайн: " + deadline_str + "</span>" if deadline_str else ""}
                    </div>
                    {"<div class='task-comment'>💬 " + safe_comment + "</div>" if safe_comment else ""}
                </div>
                <form method="POST" action="/tasks/{task_id}/delete" class="delete-form">
                    <button type="submit" class="delete-btn" title="Удалить задачу">🗑️</button>
                </form>
            </div>
        </div>
        """

    # Если задач нет
    if not tasks:
        tasks_html = """
        <div class="empty-state">
            <p>📋 Задач пока нет. Добавьте первую задачу!</p>
        </div>
        """

    # Статистика
    total = len(tasks)
    completed = sum(1 for t in tasks if t[4])
    overdue = sum(
        1
        for t in tasks
        if not t[4] and _ensure_aware(t[2]) and _ensure_aware(t[2]) < now
    )

    # Полный HTML
    page = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Трекер задач для ВКР</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }}

        .container {{
            max-width: 800px;
            margin: 0 auto;
        }}

        header {{
            text-align: center;
            color: white;
            margin-bottom: 30px;
        }}

        header h1 {{
            font-size: 2.5em;
            margin-bottom: 10px;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }}

        header p {{
            font-size: 1.1em;
            opacity: 0.9;
        }}

        .stats {{
            display: flex;
            justify-content: center;
            gap: 20px;
            margin-bottom: 25px;
            flex-wrap: wrap;
        }}

        .stat-badge {{
            background: rgba(255,255,255,0.2);
            backdrop-filter: blur(10px);
            padding: 10px 20px;
            border-radius: 25px;
            color: white;
            font-weight: 500;
        }}

        .stat-badge.overdue {{
            background: rgba(239, 68, 68, 0.8);
        }}

        .card {{
            background: white;
            border-radius: 16px;
            padding: 30px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.15);
            margin-bottom: 25px;
        }}

        .card h2 {{
            color: #333;
            margin-bottom: 20px;
            font-size: 1.4em;
        }}

        .form-group {{
            margin-bottom: 15px;
        }}

        .form-group label {{
            display: block;
            margin-bottom: 5px;
            color: #555;
            font-weight: 500;
            font-size: 0.9em;
        }}

        .form-group input,
        .form-group textarea {{
            width: 100%;
            padding: 12px 16px;
            border: 2px solid #e2e8f0;
            border-radius: 10px;
            font-size: 1em;
            transition: border-color 0.3s;
            font-family: inherit;
        }}

        .form-group input:focus,
        .form-group textarea:focus {{
            outline: none;
            border-color: #667eea;
        }}

        .form-group textarea {{
            resize: vertical;
            min-height: 80px;
        }}

        .submit-btn {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            padding: 14px 30px;
            border-radius: 10px;
            font-size: 1.05em;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
            width: 100%;
        }}

        .submit-btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 8px 25px rgba(102, 126, 234, 0.4);
        }}

        .task-item {{
            border: 2px solid #e2e8f0;
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 12px;
            transition: all 0.3s;
        }}

        .task-item:hover {{
            border-color: #667eea;
            box-shadow: 0 4px 12px rgba(0,0,0,0.05);
        }}

        .task-item.completed {{
            background: #f8fafc;
            border-color: #e2e8f0;
            opacity: 0.7;
        }}

        .task-item.completed .task-title {{
            text-decoration: line-through;
            color: #94a3b8;
        }}

        .task-item.overdue {{
            border-color: #fca5a5;
            background: #fef2f2;
        }}

        .task-header {{
            display: flex;
            align-items: flex-start;
            gap: 12px;
        }}

        .toggle-form {{
            flex-shrink: 0;
            padding-top: 2px;
        }}

        .task-checkbox {{
            width: 22px;
            height: 22px;
            cursor: pointer;
            accent-color: #667eea;
        }}

        .task-content {{
            flex-grow: 1;
        }}

        .task-title {{
            font-size: 1.1em;
            font-weight: 600;
            color: #1e293b;
            display: block;
            margin-bottom: 6px;
        }}

        .task-meta {{
            display: flex;
            gap: 15px;
            flex-wrap: wrap;
            font-size: 0.85em;
            color: #64748b;
        }}

        .task-deadline {{
            color: #dc2626;
            font-weight: 500;
        }}

        .task-comment {{
            margin-top: 8px;
            padding: 8px 12px;
            background: #f1f5f9;
            border-radius: 8px;
            font-size: 0.9em;
            color: #475569;
        }}

        .delete-form {{
            flex-shrink: 0;
        }}

        .delete-btn {{
            background: none;
            border: none;
            font-size: 1.2em;
            cursor: pointer;
            opacity: 0.5;
            transition: opacity 0.2s;
            padding: 4px;
        }}

        .delete-btn:hover {{
            opacity: 1;
        }}

        .empty-state {{
            text-align: center;
            padding: 40px;
            color: #94a3b8;
            font-size: 1.1em;
        }}

        footer {{
            text-align: center;
            color: rgba(255,255,255,0.7);
            margin-top: 30px;
            font-size: 0.9em;
        }}

        footer a {{
            color: white;
            text-decoration: none;
        }}

        @media (max-width: 600px) {{
            header h1 {{
                font-size: 1.8em;
            }}
            .card {{
                padding: 20px;
            }}
            .task-meta {{
                flex-direction: column;
                gap: 5px;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>📋 Трекер задач для ВКР</h1>
            <p>Управляйте задачами вашей выпускной квалификационной работы</p>
        </header>

        <div class="stats">
            <div class="stat-badge">📊 Всего: {total}</div>
            <div class="stat-badge">✅ Выполнено: {completed}</div>
            {"<div class='stat-badge overdue'>⚠️ Просрочено: " + str(overdue) + "</div>" if overdue > 0 else ""}
        </div>

        <div class="card">
            <h2>➕ Добавить задачу</h2>
            <form method="POST" action="/tasks">
                <div class="form-group">
                    <label for="title">Название задачи *</label>
                    <input type="text" id="title" name="title" required
                           placeholder="Например: Написать главу 2">
                </div>
                <div class="form-group">
                    <label for="deadline">Дедлайн (необязательно)</label>
                    <input type="datetime-local" id="deadline" name="deadline">
                </div>
                <div class="form-group">
                    <label for="comment">Комментарий (необязательно)</label>
                    <textarea id="comment" name="comment"
                              placeholder="Дополнительная информация о задаче..."></textarea>
                </div>
                <button type="submit" class="submit-btn">Добавить задачу</button>
            </form>
        </div>

        <div class="card">
            <h2>📝 Список задач</h2>
            {tasks_html}
        </div>

        <footer>
            <p>Трекер задач для ВКР | FastAPI + PostgreSQL + Docker + Prometheus</p>
            <p>Метрики: <a href="/metrics">/metrics</a> | Здоровье: <a href="/health">/health</a></p>
        </footer>
    </div>
</body>
</html>"""

    return page


# ============================================================
# ЭНДПОИНТЫ (маршруты) ПРИЛОЖЕНИЯ
# ============================================================

@app.get("/", response_class=HTMLResponse)
async def index():
    """
    Главная страница - показывает форму и список задач.
    """
    tasks = get_all_tasks()
    return get_html_page(tasks)


@app.post("/tasks")
async def create_task(
    title: str = Form(...),
    deadline: str = Form(None),
    comment: str = Form(None)
):
    """
    Добавляет новую задачу в базу данных.
    """
    conn = psycopg.connect(DATABASE_URL)
    cursor = conn.cursor()

    # Обрабатываем дедлайн
    deadline_value = None
    if deadline:
        try:
            deadline_value = datetime.fromisoformat(deadline)
        except ValueError:
            deadline_value = None

    # Вставляем задачу в БД
    cursor.execute("""
        INSERT INTO tasks (title, deadline, comment)
        VALUES (%s, %s, %s)
    """, (title, deadline_value, comment))

    conn.commit()
    cursor.close()
    conn.close()

    # Возвращаемся на главную страницу
    return RedirectResponse(url="/", status_code=303)


@app.post("/tasks/{task_id}/toggle")
async def toggle_task(task_id: int):
    """
    Переключает статус выполнения задачи.
    """
    conn = psycopg.connect(DATABASE_URL)
    cursor = conn.cursor()

    # Получаем текущий статус
    cursor.execute("SELECT is_completed FROM tasks WHERE id = %s", (task_id,))
    result = cursor.fetchone()

    if result:
        new_status = not result[0]
        cursor.execute("""
            UPDATE tasks SET is_completed = %s WHERE id = %s
        """, (new_status, task_id))
        conn.commit()

    cursor.close()
    conn.close()

    return RedirectResponse(url="/", status_code=303)


@app.post("/tasks/{task_id}/delete")
async def delete_task(task_id: int):
    """
    Удаляет задачу из базы данных.
    """
    conn = psycopg.connect(DATABASE_URL)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
    conn.commit()
    cursor.close()
    conn.close()

    return RedirectResponse(url="/", status_code=303)


@app.get("/health")
async def health_check():
    """
    Проверка здоровья приложения (для Docker healthcheck).
    Также проверяет подключение к базе данных.
    """
    try:
        conn = psycopg.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.close()
        conn.close()
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "database": str(e)},
        )

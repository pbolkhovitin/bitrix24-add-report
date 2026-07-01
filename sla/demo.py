"""Demo data generation for SLA dashboard.

Generates ~40 realistic support tasks spanning the last 30 days
with varied priorities, statuses, and SLA outcomes.
"""

import json
import random
from datetime import datetime, timedelta, date
from typing import List, Dict, Any, Optional

from sla.config import Settings, WorkingHoursConfig

random.seed(42)

# Config weekday (0=Sun) -> Python weekday (0=Mon)
_PY_WDAY_TO_CONFIG = {0: 1, 1: 2, 2: 3, 3: 4, 4: 5, 5: 6, 6: 0}


def _is_workday_demo(d: date, wh_config: WorkingHoursConfig) -> bool:
    config_wday = _PY_WDAY_TO_CONFIG[d.weekday()]
    return config_wday in wh_config.workdays and d not in wh_config.holidays


def _random_business_datetime(days_ago: int, wh_config: WorkingHoursConfig, now: datetime) -> datetime:
    d = now - timedelta(days=days_ago)
    for _ in range(10):
        if _is_workday_demo(d.date(), wh_config):
            break
        d -= timedelta(days=1)
    start_h = wh_config.start.hour
    end_h = wh_config.end.hour - 1
    hour = random.randint(start_h, max(start_h, end_h))
    minute = random.randint(0, 59)
    return d.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _add_business_hours(dt: datetime, hours: float, wh_config: WorkingHoursConfig) -> datetime:
    remaining = hours * 3600
    current = dt
    max_iter = 200
    while remaining > 0 and max_iter > 0:
        max_iter -= 1
        if not _is_workday_demo(current.date(), wh_config):
            current += timedelta(days=1)
            current = current.replace(hour=wh_config.start.hour, minute=0, second=0)
            continue
        day_end = current.replace(hour=wh_config.end.hour, minute=0, second=0)
        available = (day_end - current).total_seconds()
        if available <= 0:
            current += timedelta(days=1)
            current = current.replace(hour=wh_config.start.hour, minute=0, second=0)
            continue
        if remaining <= available:
            current += timedelta(seconds=remaining)
            remaining = 0
        else:
            remaining -= available
            current += timedelta(days=1)
            current = current.replace(hour=wh_config.start.hour, minute=0, second=0)
    return current


TITLES = [
    "Не отправляются email-уведомления",
    "Ошибка 500 при входе в CRM",
    "Не загружается файл отчёта",
    "Некорректный расчёт цены в заказе",
    "Проблема с авторизацией через LDAP",
    "Зависает импорт контактов из Excel",
    "Не приходят push-уведомления",
    "Отчёт по лидам не формируется",
    "Ошибка синхронизации с 1С",
    "Некорректное отображение в мобильной версии",
    "Медленная работа раздела Задачи",
    "Не обновляется статус сделки",
    "Проблема с правами доступа к разделу",
    "Ошибка при создании счета",
    "Не работает поиск по контактам",
    "Сбросились настройки виджетов",
    "Дублируются записи в журнале звонков",
    "Не отображается воронка продаж",
    "Проблема с интеграцией телефонии",
    "Ошибка экспорта в PDF",
    "Не приходят письма из почтового ящика",
    "Критическая ошибка индексации",
    "Проблема с кодировкой в CSV",
    "Запрос на обновление модуля ТП",
    "Неверный формат даты в отчётах",
    "Ошибка при назначении задачи",
    "Проблема с вложенными комментариями",
    "Замедление при загрузке списков",
    "Не работает кнопка «Сохранить»",
    "Ошибка вебхука при интеграции",
    "Слетели настройки бизнес-процессов",
    "Проблема с часовым поясом в календаре",
    "Не отображаются названия полей",
    "Ошибка при массовой конвертации лидов",
    "Проблема с печатью документов",
    "Зависает панель уведомлений",
    "Неверный подсчёт голосов в опросах",
    "Ошибка подключения к LDAP",
    "Не загружаются изображения в новости",
    "Проблема с историей изменений в задачах",
]


def seed_demo(store, settings: Settings) -> None:
    """Seed SQLite store with ~40 demo support tasks."""
    now = datetime.now()
    wh_config = settings.working_hours

    store.clear_all_data()

    # Users
    users = [
        (1, "Техподдержка", "Очередь", "Техподдержка Очередь", 1),
        (2, "Иванов", "Иван", "Иванов Иван", 1),
        (3, "Петров", "Петр", "Петров Петр", 1),
        (4, "Сидорова", "Анна", "Сидорова Анна", 1),
    ]
    for uid, nm, ln, fn, act in users:
        store.upsert_user(uid, nm, ln, fn, act)

    status_options = [2, 3, 5]
    status_weights = [0.2, 0.2, 0.6]

    for i in range(40):
        title = TITLES[i] if i < len(TITLES) else f"Обращение #{i + 1}"
        days_ago = random.randint(1, 28)
        priority = random.choices([1, 2, 3, 4], weights=[1, 4, 3, 2])[0]
        responsible = random.choices([2, 3, 4], weights=[2, 2, 2])[0]
        final_status = random.choices(status_options, weights=status_weights)[0]

        thr_fr_min, thr_res_min = settings.sla.get_threshold(priority)

        # First response timing
        if random.random() < 0.6:
            fr_offset_hours = random.uniform(0.15, thr_fr_min / 60 * 0.85)
        else:
            fr_offset_hours = random.uniform(thr_fr_min / 60 * 1.1, thr_fr_min / 60 * 3)

        # Resolution timing
        if final_status == 5:
            if random.random() < 0.55:
                res_offset_hours = random.uniform(1, thr_res_min / 60 * 0.85)
            else:
                res_offset_hours = random.uniform(thr_res_min / 60 * 1.1, thr_res_min / 60 * 2.5)
        else:
            res_offset_hours = None

        created = _random_business_datetime(days_ago, wh_config, now)
        fr_dt = _add_business_hours(created, fr_offset_hours, wh_config)

        res_dt: Optional[datetime] = None
        if final_status == 5 and res_offset_hours is not None:
            res_dt = _add_business_hours(created, res_offset_hours, wh_config)

        deadline = created + timedelta(days=random.randint(2, 7), hours=random.randint(0, 12))

        # History: status change (agent picks up)
        store.add_history(
            task_id=i + 1,
            user_id=responsible,
            field="STATUS",
            old_value="2",
            new_value="3",
            created_date=fr_dt.isoformat(),
        )

        # Comment (maybe)
        if random.random() < 0.7:
            store.upsert_comment(
                comment_id=i * 10 + 1,
                task_id=i + 1,
                author_id=responsible,
                created_date=fr_dt.isoformat(),
                content="Принял в работу, разбираюсь.",
            )

        # Elapsed (maybe)
        if random.random() < 0.5:
            store.upsert_elapsed(
                elapsed_id=i * 10 + 1,
                task_id=i + 1,
                user_id=responsible,
                seconds=random.randint(1800, 7200),
                created_date=fr_dt.isoformat(),
                comment="Диагностика проблемы",
            )

        # Resolution history
        if res_dt:
            store.add_history(
                task_id=i + 1,
                user_id=responsible,
                field="STATUS",
                old_value="3",
                new_value="5",
                created_date=res_dt.isoformat(),
            )
            if random.random() < 0.6:
                store.upsert_comment(
                    comment_id=i * 10 + 2,
                    task_id=i + 1,
                    author_id=responsible,
                    created_date=res_dt.isoformat(),
                    content="Проблема решена, закрываю.",
                )
            if random.random() < 0.5:
                store.upsert_elapsed(
                    elapsed_id=i * 10 + 2,
                    task_id=i + 1,
                    user_id=responsible,
                    seconds=random.randint(3600, 14400),
                    created_date=res_dt.isoformat(),
                    comment="Работа над задачей",
                )

        # Main task record
        raw = json.dumps({
            "ID": str(i + 1),
            "TITLE": title,
            "STATUS": str(final_status),
            "PRIORITY": str(priority),
            "RESPONSIBLE_ID": str(responsible),
            "CREATED_BY": "1",
            "GROUP_ID": "0",
            "DEADLINE": deadline.isoformat(),
            "CREATED_DATE": created.isoformat(),
            "CLOSED_DATE": res_dt.isoformat() if res_dt else None,
            "CHANGED_DATE": (res_dt or fr_dt).isoformat(),
            "CLOSED_BY": str(responsible) if res_dt else "0",
            "TAGS": "",
        }, ensure_ascii=False)

        store.upsert_task(
            task_id=i + 1,
            title=title,
            status=final_status,
            priority=priority,
            responsible_id=responsible,
            created_by=1,
            group_id=0,
            deadline=deadline.isoformat(),
            created_date=created.isoformat(),
            closed_date=res_dt.isoformat() if res_dt else None,
            changed_date=(res_dt or fr_dt).isoformat(),
            closed_by=responsible if res_dt else 0,
            tags="",
            raw=raw,
        )
        store.adopt_task(i + 1)

    store.set_sync_state("last_sync", now.isoformat())

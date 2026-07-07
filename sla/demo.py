"""Demo data generation for SLA dashboard.

Generates ~40 realistic support tasks spanning the last 30 days
with varied priorities, statuses, and SLA outcomes.
Includes enriched data for deviation detection demonstrations.
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

# Realistic descriptions for ~35 tasks (tasks 0-34 have descriptions, 35-39 are empty)
DESCRIPTIONS = [
    "После обновления модуля почты перестали приходить уведомления пользователям. "
    "Проверил настройки SMTP, всё корректно. Нужна диагностика.",
    "При попытке открыть CRM через веб-интерфейс возникает ошибка 500. "
    "В логах указана проблема с подключением к БД. Сброс кеша не помог.",
    "Отчёт за прошлый месяц не загружается в формате Excel. "
    "На других ПК такая же проблема. Файл больше 10 МБ.",
    "В заказе №3425 цена рассчитана неверно — скидка применена дважды. "
    "Перепроверил формулы в калькуляторе, ошибка воспроизводится.",
    "Пользователи из AD не могут войти в систему после смены пароля. "
    "LDAP-соединение теряется через 5 минут после перезапуска службы.",
    "При импорте 5000 контактов из Excel процесс зависает на 85%. "
    "Файл содержит специальные символы в названиях компаний.",
    "Push-уведомления на iOS перестали приходить после обновления приложения. "
    "Сертификаты APNS валидны, проблема на стороне клиента.",
    "Отчёт по лидам не формируется, ошибка деления на ноль в сводной таблице. "
    "Один из лидов имеет нулевую сумму.",
    "Синхронизация заказов с 1С прерывается на этапе выгрузки. "
    "Ошибка в поле ИНН — несоответствие формату.",
    "В мобильной версии сайта некорректно отображается шапка. "
    "На iPhone 15 и Android одинаково — съезжают элементы.",
    "Раздел Задачи работает медленно при открытии списка более 100 задач. "
    "Индексы БД перестроены, но проблема осталась.",
    "Статус сделки не обновляется после выполнения всех этапов. "
    "Бизнес-процесс зависает на последнем шаге.",
    "Сотрудник не может открыть раздел с финансовыми отчётами. "
    "Права перепроверены, доступ должен быть.",
    "При создании счёта из сделки не подтягиваются контактные данные. "
    "Шаблон счёта настроен корректно.",
    "Поиск по контактам выдаёт пустой результат для существующих записей. "
    "Переиндексация поиска не помогла.",
    "После установки обновления сбросились все пользовательские виджеты. "
    "Настройки не сохраняются после перезагрузки.",
    "В журнале звонков появились дублирующиеся записи с разницей в 1 минуту. "
    "Проблема проявляется при параллельных звонках.",
    "Воронка продаж не отображается в отчёте руководителя. "
    "Фильтры настроены, данные в сделках есть.",
    "Телефония работает с перебоями — прерывается звонок через 2 минуты. "
    "Провайдер утверждает, что проблема на нашей стороне.",
    "Экспорт отчёта в PDF завершается с ошибкой 'Недостаточно памяти'. "
    "Даже для небольших отчётов.",
    "Почтовый ящик не принимает письма с вложенными файлами. "
    "Размер письма не превышает 5 МБ. Лимиты увеличены.",
    "Индексация поиска падает с критической ошибкой на таблице задач. "
    "В логах: duplicate key violation.",
    "CSV-файлы с кириллицей открываются с неправильной кодировкой. "
    "Настройки UTF-8 в системе выставлены.",
    "Требуется обновить модуль техподдержки до версии 24.0. "
    "Текущая версия 22.5 не поддерживает новые API.",
    "Дата в отчётах отображается в американском формате. "
    "Настройки локали ru-RU, но формат не применяется.",
    "При назначении задачи через email возникает ошибка 400. "
    "Парсинг входящего письма некорректно определяет ID проекта.",
    "Вложенные комментарии не отображаются в веб-интерфейсе. "
    "В мобильном приложении всё видно.",
    "Загрузка списка сущностей занимает более 30 секунд. "
    "Количество записей не превышает 5000.",
    "Кнопка «Сохранить» неактивна в форме редактирования сделки. "
    "Валидация JS не проходит из-за скрытого поля.",
    "Вебхук при интеграции с сервисом возвращает error 403. "
    "Проверены права доступа и токены.",
    "Слетели настройки бизнес-процессов после миграции. "
    "Все шаги сброшены на стандартные.",
    "В календаре событие отображается на час раньше. "
    "Часовой пояс сервера Europe/Moscow.",
    "В форме редактирования поля называются по-английски. "
    "Языковой файл не подгружается.",
    "Массовая конвертация лидов в контакты останавливается на 50%. "
    "Ошибка в обработке дубликатов.",
    "Печать документов не работает в Chrome. "
    "В Firefox всё корректно. Проблема с CSS.",
    "",  # task 35 — empty description
    "",  # task 36 — empty description
    "",  # task 37 — empty description
    "",  # task 38 — empty description
    "",  # task 39 — empty description
]


def seed_demo(store, settings: Settings) -> None:
    """Seed SQLite store with ~40 demo support tasks with deviation examples."""
    now = datetime.now()
    now_aware = now
    wh_config = settings.working_hours

    store.clear_all_data()

    # Users with work positions
    users = [
        (1, "Техподдержка", "Очередь", "Техподдержка Очередь", 1, "Очередь ТП", ""),
        (2, "Иванов", "Иван", "Иванов Иван", 1, "Инженер 1 линии", ""),
        (3, "Петров", "Петр", "Петров Петр", 1, "Диспетчер", ""),
        (4, "Сидорова", "Анна", "Сидорова Анна", 1, "Руководитель отдела", ""),
    ]
    for uid, nm, ln, fn, act, wp, dep in users:
        store.upsert_user(uid, nm, ln, fn, act, work_position=wp, department=dep)

    status_options = [2, 3, 5]
    status_weights = [0.2, 0.2, 0.6]

    # Track which tasks get which deviations (for adding extra history later)
    has_accomplices = set()
    stuck_task_ids = set()
    created_by_responsible = set()

    for i in range(40):
        title = TITLES[i] if i < len(TITLES) else f"Обращение #{i + 1}"
        days_ago = random.randint(1, 28)
        priority = random.choices([1, 2, 3, 4], weights=[1, 4, 3, 2])[0]
        responsible = random.choices([2, 3, 4], weights=[2, 2, 2])[0]

        # Tasks 36-38: force responsible_id == created_by (deviation: no_executor_assigned)
        if i in (36, 37, 38):
            responsible = 1

        final_status = random.choices(status_options, weights=status_weights)[0]

        # Tasks 34-37: keep non-closed for stuck deviation
        if i in (34, 35):
            final_status = 3
            stuck_task_ids.add(i)
        if i in (36, 37):
            final_status = 2
            stuck_task_ids.add(i)

        # Task 38: keep non-closed, status 3, but also has responsible=1 (no_executor_assigned)
        if i == 38:
            final_status = 3
            stuck_task_ids.add(i)

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

        # Elapsed (maybe) — only for tasks that should have time logged
        # Tasks 0-5 have no elapsed (deviation for no_time_logged if closed)
        should_have_elapsed = i >= 6
        if should_have_elapsed and random.random() < 0.5:
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
            # Tasks 0-4: no result comment (deviation) — no closing comment
            # Tasks 5-9: short "ок" comment (< 20 chars, deviation)
            if i >= 5 and i < 10:
                store.upsert_comment(
                    comment_id=i * 10 + 2,
                    task_id=i + 1,
                    author_id=responsible,
                    created_date=res_dt.isoformat(),
                    content="ок",
                )
            elif i >= 10 and random.random() < 0.6:
                store.upsert_comment(
                    comment_id=i * 10 + 2,
                    task_id=i + 1,
                    author_id=responsible,
                    created_date=res_dt.isoformat(),
                    content="Проблема решена, закрываю.",
                )
            if should_have_elapsed and random.random() < 0.5:
                store.upsert_elapsed(
                    elapsed_id=i * 10 + 2,
                    task_id=i + 1,
                    user_id=responsible,
                    seconds=random.randint(3600, 14400),
                    created_date=res_dt.isoformat(),
                    comment="Работа над задачей",
                )
        else:
            # For stuck tasks, add a late STATUS event to set the "last change" far enough back
            if i in stuck_task_ids:
                # Create a status event that's > stuck_days_threshold days ago
                stuck_days_ago = settings.process.deviations.stuck_days_threshold + 3
                last_change = now - timedelta(days=stuck_days_ago)
                store.add_history(
                    task_id=i + 1,
                    user_id=responsible,
                    field="STATUS",
                    old_value="2",
                    new_value="3",
                    created_date=last_change.isoformat(),
                )

        # ========== ACCOMPLICES for tasks 3, 7, 11 ==========
        accomplices_list = []
        if i in (3, 7, 11):
            accomplices_list = [3, 4]
            has_accomplices.add(i)

        # ========== PARENT_ID for tasks 20, 25 ==========
        parent_id = 0
        if i == 20:
            parent_id = 15
        if i == 25:
            parent_id = 10

        # Build description
        description = DESCRIPTIONS[i] if i < len(DESCRIPTIONS) else ""

        # ========== Extra history events ==========
        # DEADLINE changes: tasks 3, 8, 13, 18, 23, 28, 33 (7 tasks)
        if i in (3, 8, 13, 18, 23, 28, 33):
            # New deadline moved 1-2 days earlier
            old_deadline = deadline.isoformat()
            new_deadline = (deadline - timedelta(days=1)).isoformat() if i % 2 == 0 else (deadline + timedelta(days=1)).isoformat()
            changed_dt = fr_dt + timedelta(hours=1)
            store.add_history(
                task_id=i + 1,
                user_id=responsible,
                field="DEADLINE",
                old_value=old_deadline,
                new_value=new_deadline,
                created_date=changed_dt.isoformat(),
            )
            # Tasks 23, 33: no comment within ±1h of this change (deviation)
            # Tasks 3, 8, 13, 18, 28: add comment within window
            if i not in (23, 33):
                store.upsert_comment(
                    comment_id=i * 10 + 3,
                    task_id=i + 1,
                    author_id=responsible,
                    created_date=(changed_dt + timedelta(minutes=15)).isoformat(),
                    content="Сдвинул дедлайн, так как требуется дополнительная диагностика.",
                )

        # RESPONSIBLE_ID changes: tasks 2, 7, 12, 17, 22, 27, 32, 37, 38, 39 (10 tasks)
        if i in (2, 7, 12, 17, 22, 27, 32):
            old_resp = responsible
            new_resp = 4 if responsible != 4 else 3
            changed_dt = fr_dt + timedelta(minutes=random.randint(30, 180))
            store.add_history(
                task_id=i + 1,
                user_id=1,
                field="RESPONSIBLE_ID",
                old_value=str(old_resp),
                new_value=str(new_resp),
                created_date=changed_dt.isoformat(),
            )

        # GROUP_ID changes: tasks 5, 15, 25 (3 tasks)
        if i in (5, 15, 25):
            changed_dt = fr_dt + timedelta(minutes=random.randint(60, 240))
            store.add_history(
                task_id=i + 1,
                user_id=1,
                field="GROUP_ID",
                old_value="0",
                new_value="1",
                created_date=changed_dt.isoformat(),
            )
            # Task 25 gets a second change (for multi_department_without_parent)
            if i == 25:
                store.add_history(
                    task_id=i + 1,
                    user_id=1,
                    field="GROUP_ID",
                    old_value="1",
                    new_value="2",
                    created_date=(changed_dt + timedelta(hours=2)).isoformat(),
                )

        # PRIORITY changes (escalation): tasks 9, 19
        if i in (9, 19):
            old_prio = priority
            new_prio = min(priority + 1, 4)
            changed_dt = fr_dt + timedelta(hours=random.randint(2, 8))
            store.add_history(
                task_id=i + 1,
                user_id=1,
                field="PRIORITY",
                old_value=str(old_prio),
                new_value=str(new_prio),
                created_date=changed_dt.isoformat(),
            )

        # Build raw JSON with all fields
        raw_obj = {
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
            "PARENT_ID": str(parent_id),
            "DESCRIPTION": description,
            "ACCOMPLICES": accomplices_list,
            "AUDITORS": [],
            "DURATION_FACT_SECONDS": str(random.randint(3600, 28800) if should_have_elapsed else 0),
            "DURATION_PLAN_SECONDS": str(random.randint(7200, 43200)),
            "TIME_ESTIMATE": "0",
            "MARK": str(final_status if final_status == 5 else -1),
            "ADD_IN_REPORTS": "1",
            "UF_AUTO_672314578963": "Да" if i % 3 == 0 else "",
            "UF_CRM_TASK": f"L_{i+100}" if i % 2 == 0 else "",
        }

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
            raw=json.dumps(raw_obj, ensure_ascii=False),
            parent_id=parent_id,
            accomplices=json.dumps(accomplices_list) if accomplices_list else "[]",
            auditors="[]",
            description=description,
            duration_fact_seconds=random.randint(3600, 28800) if should_have_elapsed else 0,
            duration_plan_seconds=random.randint(7200, 43200),
            time_estimate=0,
            mark=final_status if final_status == 5 else -1,
            add_in_reports=1,
        )
        store.adopt_task(i + 1)

    store.set_sync_state("last_sync", now.isoformat())

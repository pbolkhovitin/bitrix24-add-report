"""Deviation detection and process control for SLA dashboard."""

import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from sla.store import Store
from sla.config import Settings
from sla.metrics import parse_bitrix_datetime, get_status_labels


DEVIATION_LABELS: Dict[str, str] = {
    "deadline_moved_without_comment": "Сдвиг дедлайна без комментария",
    "no_time_logged": "Нет учёта времени",
    "no_result_description": "Нет описания результата",
    "stuck_task": "Зависшая задача",
    "no_executor_assigned": "Не назначен исполнитель",
    "unnecessary_accomplices": "Избыточные соисполнители",
    "missing_mandatory_fields": "Отсутствуют обязательные поля",
    "multi_department_without_parent": "Множественные отделы без родительской задачи",
}


def _get_responsible_name(store: Store, user_id: int) -> str:
    umap = store.users_map()
    if user_id in umap:
        u = umap[user_id]
        return u.get("full_name", u.get("name", f"#{user_id}"))
    return f"#{user_id}"


def _get_comments_within(
    store: Store, task_id: int, center: datetime, window_minutes: int
) -> List[Dict[str, Any]]:
    """Return comments within ±window_minutes of center datetime."""
    comments = store.get_comments(task_id)
    result = []
    window = timedelta(minutes=window_minutes)
    for c in comments:
        c_dt = parse_bitrix_datetime(c.get("created_date"))
        if c_dt and abs(c_dt - center) <= window:
            result.append(c)
    return result


def detect_deviations(store: Store, settings: Settings) -> List[Dict]:
    """Detect all process deviations across tracked tasks."""
    tasks = store.get_tasks()
    deviations: List[Dict] = []
    now = datetime.now()
    cfg = settings.process.deviations
    mandatory = settings.process.mandatory_fields
    stuck_days = timedelta(days=cfg.stuck_days_threshold)

    for t in tasks:
        task_id = t.get("id", 0)
        title = t.get("title", "")
        history = store.get_history(task_id)
        comments = store.get_comments(task_id)
        elapsed = store.get_elapsed(task_id)
        responsible_id = t.get("responsible_id", 0)
        created_by = t.get("created_by", 0)
        status = t.get("status", 0)
        closed_date_raw = t.get("closed_date")

        # Helper
        def _add_dev(dtype: str, severity: str, detail: str, rid: Optional[int] = None) -> None:
            deviations.append({
                "task_id": task_id,
                "title": title,
                "type": dtype,
                "type_label": DEVIATION_LABELS.get(dtype, dtype),
                "severity": severity,
                "detail": detail,
                "responsible_id": rid or responsible_id or 0,
                "responsible_name": _get_responsible_name(store, rid or responsible_id or 0),
            })

        # 1. deadline_moved_without_comment
        deadline_events = [h for h in history if h.get("field") == "DEADLINE"]
        for de in deadline_events:
            de_dt = parse_bitrix_datetime(de.get("created_date"))
            if de_dt:
                nearby = _get_comments_within(store, task_id, de_dt, cfg.comment_window_minutes)
                if not nearby:
                    _add_dev(
                        "deadline_moved_without_comment",
                        "medium",
                        f"Дедлайн изменён {de_dt.strftime('%d.%m.%Y %H:%M')} без комментария",
                        rid=int(de.get("user_id", 0)),
                    )

        # 2. no_time_logged
        if status == 5:
            total_sec = sum(int(e.get("seconds", 0)) for e in elapsed)
            if total_sec == 0:
                _add_dev("no_time_logged", "high", "Задача закрыта, но учёт времени отсутствует")

        # 3. no_result_description
        if status == 5:
            closed_at = parse_bitrix_datetime(closed_date_raw)
            has_result_comment = False
            if closed_at:
                window = timedelta(hours=1)
                for c in comments:
                    c_dt = parse_bitrix_datetime(c.get("created_date"))
                    if c_dt and closed_at - c_dt <= window and c_dt <= closed_at:
                        content = c.get("content", "")
                        if len(content.strip()) >= cfg.min_result_comment_length:
                            has_result_comment = True
                            break
            if not has_result_comment:
                _add_dev("no_result_description", "high", "Нет описания результата закрытия задачи")

        # 4. stuck_task
        if status not in (5, 7):
            status_events = [h for h in history if h.get("field") == "STATUS"]
            if status_events:
                last_status_dt = parse_bitrix_datetime(status_events[-1].get("created_date"))
                if last_status_dt and (now - last_status_dt) > stuck_days:
                    _add_dev(
                        "stuck_task",
                        "medium",
                        f"Последнее изменение статуса: {last_status_dt.strftime('%d.%m.%Y %H:%M')}"
                        f" (более {cfg.stuck_days_threshold} дн. назад)",
                    )
            else:
                # No status changes at all — stuck if created > threshold ago
                created_dt = parse_bitrix_datetime(t.get("created_date"))
                if created_dt and (now - created_dt) > stuck_days:
                    _add_dev("stuck_task", "medium", "Нет изменений статуса с момента создания")

        # 5. no_executor_assigned
        if responsible_id == created_by:
            _add_dev("no_executor_assigned", "high", "Исполнитель совпадает с постановщиком")
        else:
            resp_changes = [h for h in history if h.get("field") == "RESPONSIBLE_ID"]
            if not resp_changes:
                _add_dev("no_executor_assigned", "high",
                         f"Ответственный не менялся (всегда #{responsible_id})")

        # 6. unnecessary_accomplices
        accomplices_raw = t.get("accomplices", "[]") or "[]"
        try:
            accomplices_list = json.loads(accomplices_raw) if isinstance(accomplices_raw, str) else accomplices_raw
            if isinstance(accomplices_list, list) and len(accomplices_list) > 0:
                _add_dev("unnecessary_accomplices", "low",
                         f"Назначены соисполнители: {accomplices_list}")
        except (ValueError, TypeError):
            pass

        # 7. missing_mandatory_fields
        missing_fields = []
        for fname in mandatory.std_fields:
            fname_lower = fname.lower()
            if fname_lower == "description":
                val = t.get("description", t.get("DESCRIPTION", ""))
            else:
                val = t.get(fname, t.get(fname_lower, ""))
            if not val or (isinstance(val, str) and val.strip() == ""):
                missing_fields.append(fname)

        # Check UF_* fields from raw JSON
        raw_str = t.get("raw", "{}")
        if raw_str:
            try:
                raw_data = json.loads(raw_str) if isinstance(raw_str, str) else raw_str
                for uf_name in mandatory.uf_fields:
                    uf_val = raw_data.get(uf_name)
                    if not uf_val or (isinstance(uf_val, str) and uf_val.strip() == ""):
                        missing_fields.append(uf_name)
            except (ValueError, TypeError):
                pass

        if missing_fields:
            _add_dev("missing_mandatory_fields", "medium",
                     f"Отсутствуют поля: {', '.join(missing_fields)}")

        # 8. multi_department_without_parent
        parent_id = t.get("parent_id", 0)
        group_changes = sum(1 for h in history if h.get("field") == "GROUP_ID")
        if parent_id == 0 and group_changes > 2:
            _add_dev("multi_department_without_parent", "low",
                     f"Группа менялась {group_changes} раз, родительская задача не указана")

    return deviations


def daily_control(store: Store, settings: Settings) -> Dict:
    """Dispatcher's daily checklist."""
    tasks = store.get_tasks()
    today = datetime.now()
    yesterday = today - timedelta(days=1)
    cfg = settings.process.deviations

    new_without_processing = []
    without_mandatory_fields = []
    without_owner = []
    deadline_moved_list = []
    without_result = []
    without_time = []
    stuck_list = []

    for t in tasks:
        task_id = t.get("id", 0)
        status = t.get("status", 0)
        created_date_raw = t.get("created_date")
        created_dt = parse_bitrix_datetime(created_date_raw)
        responsible_id = t.get("responsible_id", 0)
        created_by = t.get("created_by", 0)
        history = store.get_history(task_id)
        comments = store.get_comments(task_id)
        elapsed = store.get_elapsed(task_id)

        # New tasks without processing (status 1 or 2, created today/yesterday)
        if status in (1, 2) and created_dt and created_dt >= yesterday.replace(hour=0, minute=0, second=0):
            new_without_processing.append({
                "task_id": task_id,
                "title": t.get("title", ""),
                "created_date": created_date_raw,
                "responsible_name": _get_responsible_name(store, responsible_id),
            })

        # Without mandatory fields
        desc = t.get("description", "")
        if not desc or desc.strip() == "":
            without_mandatory_fields.append({
                "task_id": task_id,
                "title": t.get("title", ""),
                "responsible_name": _get_responsible_name(store, responsible_id),
            })

        # Without owner
        if responsible_id == created_by:
            without_owner.append({
                "task_id": task_id,
                "title": t.get("title", ""),
                "created_date": created_date_raw,
            })

        # Deadline moved without comment
        for h in history:
            if h.get("field") == "DEADLINE":
                de_dt = parse_bitrix_datetime(h.get("created_date"))
                if de_dt:
                    nearby = _get_comments_within(store, task_id, de_dt, cfg.comment_window_minutes)
                    if not nearby:
                        deadline_moved_list.append({
                            "task_id": task_id,
                            "title": t.get("title", ""),
                            "changed_at": de_dt.isoformat(),
                            "responsible_name": _get_responsible_name(store, responsible_id),
                        })

        # Without result description (closed, no proper comment)
        if status == 5:
            closed_at = parse_bitrix_datetime(t.get("closed_date"))
            has_result = False
            if closed_at:
                window = timedelta(hours=1)
                for c in comments:
                    c_dt = parse_bitrix_datetime(c.get("created_date"))
                    if c_dt and closed_at - c_dt <= window and c_dt <= closed_at:
                        if len(c.get("content", "").strip()) >= cfg.min_result_comment_length:
                            has_result = True
                            break
            if not has_result:
                without_result.append({
                    "task_id": task_id,
                    "title": t.get("title", ""),
                    "responsible_name": _get_responsible_name(store, responsible_id),
                })

            # Without time logged
            total_sec = sum(int(e.get("seconds", 0)) for e in elapsed)
            if total_sec == 0:
                without_time.append({
                    "task_id": task_id,
                    "title": t.get("title", ""),
                    "responsible_name": _get_responsible_name(store, responsible_id),
                })

        # Stuck tasks
        if status not in (5, 7):
            status_events = [h for h in history if h.get("field") == "STATUS"]
            if status_events:
                last_status_dt = parse_bitrix_datetime(status_events[-1].get("created_date"))
                if last_status_dt and (today - last_status_dt) > timedelta(days=cfg.stuck_days_threshold):
                    stuck_list.append({
                        "task_id": task_id,
                        "title": t.get("title", ""),
                        "last_status_change": last_status_dt.isoformat(),
                        "days_stuck": (today - last_status_dt).days,
                        "responsible_name": _get_responsible_name(store, responsible_id),
                    })

    total_issues = (
        len(new_without_processing)
        + len(without_mandatory_fields)
        + len(without_owner)
        + len(deadline_moved_list)
        + len(without_result)
        + len(without_time)
        + len(stuck_list)
    )

    return {
        "new_without_processing": new_without_processing,
        "without_mandatory_fields": without_mandatory_fields,
        "without_owner": without_owner,
        "deadline_moved_without_comment": deadline_moved_list,
        "without_result_description": without_result,
        "without_time_logged": without_time,
        "stuck_tasks": stuck_list,
        "summary": {
            "total_issues": total_issues,
            "by_severity": {
                "high": len(without_owner) + len(without_result) + len(without_time),
                "medium": len(new_without_processing) + len(without_mandatory_fields) + len(deadline_moved_list) + len(stuck_list),
                "low": 0,
            },
        },
    }


def weekly_review(store: Store, settings: Settings) -> Dict:
    """Weekly review of outstanding issues."""
    tasks = store.get_tasks()
    now = datetime.now()
    seven_days_ago = now - timedelta(days=7)
    cfg = settings.process.deviations

    old_tasks = []
    overdue_tasks = []
    without_time = []
    without_result = []
    deadline_changes = []

    oldest_task_days = 0

    for t in tasks:
        task_id = t.get("id", 0)
        created_dt = parse_bitrix_datetime(t.get("created_date"))
        deadline_dt = parse_bitrix_datetime(t.get("deadline"))
        status = t.get("status", 0)
        history = store.get_history(task_id)
        comments = store.get_comments(task_id)
        elapsed = store.get_elapsed(task_id)
        responsible_id = t.get("responsible_id", 0)

        title = t.get("title", "")
        rname = _get_responsible_name(store, responsible_id)

        # Old tasks (> 7 days, not closed)
        if created_dt and status not in (5, 7):
            age_days = (now - created_dt).days
            oldest_task_days = max(oldest_task_days, age_days)
            if created_dt < seven_days_ago:
                old_tasks.append({
                    "task_id": task_id,
                    "title": title,
                    "created_date": created_dt.isoformat(),
                    "days_open": age_days,
                    "responsible_name": rname,
                })

        # Overdue tasks (deadline < now, not closed)
        if deadline_dt and status not in (5, 7) and deadline_dt < now:
            overdue_tasks.append({
                "task_id": task_id,
                "title": title,
                "deadline": deadline_dt.isoformat(),
                "responsible_name": rname,
            })

        # Without time logged (closed)
        if status == 5:
            total_sec = sum(int(e.get("seconds", 0)) for e in elapsed)
            if total_sec == 0:
                without_time.append({
                    "task_id": task_id,
                    "title": title,
                    "responsible_name": rname,
                })

            # Without result comment
            closed_at = parse_bitrix_datetime(t.get("closed_date"))
            has_result = False
            if closed_at:
                window = timedelta(hours=1)
                for c in comments:
                    c_dt = parse_bitrix_datetime(c.get("created_date"))
                    if c_dt and closed_at - c_dt <= window and c_dt <= closed_at:
                        if len(c.get("content", "").strip()) >= cfg.min_result_comment_length:
                            has_result = True
                            break
            if not has_result:
                without_result.append({
                    "task_id": task_id,
                    "title": title,
                    "responsible_name": rname,
                })

        # Deadline changes without comment
        for h in history:
            if h.get("field") == "DEADLINE":
                de_dt = parse_bitrix_datetime(h.get("created_date"))
                if de_dt:
                    nearby = _get_comments_within(store, task_id, de_dt, cfg.comment_window_minutes)
                    if not nearby:
                        deadline_changes.append({
                            "task_id": task_id,
                            "title": title,
                            "changed_at": de_dt.isoformat(),
                            "responsible_name": rname,
                        })

    return {
        "old_tasks": old_tasks,
        "overdue_tasks": overdue_tasks,
        "without_time": without_time,
        "without_result": without_result,
        "deadline_changes_without_comment": deadline_changes,
        "summary": {
            "total_review_items": len(old_tasks) + len(overdue_tasks) + len(without_time)
                                 + len(without_result) + len(deadline_changes),
            "oldest_task_days": oldest_task_days,
        },
    }


def routing_analysis(store: Store, settings: Settings) -> Dict:
    """Analyze task routing history."""
    tasks = store.get_tasks()
    result_tasks = []

    total_routing = 0
    total_resp_changes = 0
    total_group_changes = 0
    total_time_to_assign = 0
    tasks_with_time = 0
    escalation_count = 0
    returned_count = 0

    for t in tasks:
        task_id = t.get("id", 0)
        history = store.get_history(task_id)
        created_dt = parse_bitrix_datetime(t.get("created_date"))

        # Count changes
        resp_changes = sum(1 for h in history if h.get("field") == "RESPONSIBLE_ID")
        group_changes = sum(1 for h in history if h.get("field") == "GROUP_ID")
        priority_changes = sum(1 for h in history if h.get("field") == "PRIORITY")
        routing_count = resp_changes + group_changes

        # Time to assignment (from creation to last RESPONSIBLE_ID change)
        time_to_assignment_min = None
        if created_dt and resp_changes > 0:
            last_resp_change = None
            for h in history:
                if h.get("field") == "RESPONSIBLE_ID":
                    dt = parse_bitrix_datetime(h.get("created_date"))
                    if dt:
                        last_resp_change = dt
            if last_resp_change:
                delta = last_resp_change - created_dt
                time_to_assignment_min = int(delta.total_seconds() / 60)
                total_time_to_assign += time_to_assignment_min
                tasks_with_time += 1

        # Escalation = priority increase
        escalated = False
        for h in history:
            if h.get("field") == "PRIORITY":
                try:
                    old_p = int(h.get("old_value", 0))
                    new_p = int(h.get("new_value", 0))
                    if new_p > old_p:
                        escalated = True
                        break
                except (ValueError, TypeError):
                    pass

        # Returned for refinement = STATUS went back to 4 or 2 after being in 3
        returned = False
        was_in_progress = False
        for h in sorted(history, key=lambda x: x.get("created_date", "")):
            if h.get("field") == "STATUS":
                try:
                    new_st = int(h.get("new_value", 0))
                    if new_st == 3:
                        was_in_progress = True
                    elif was_in_progress and new_st in (2, 4):
                        returned = True
                except (ValueError, TypeError):
                    pass

        if escalated:
            escalation_count += 1
        if routing_count > 0 or resp_changes > 0 or group_changes > 0:
            result_tasks.append({
                "task_id": task_id,
                "title": t.get("title", ""),
                "routing_count": routing_count,
                "responsible_changes": resp_changes,
                "group_changes": group_changes,
                "priority_changes": priority_changes,
                "time_to_assignment_min": time_to_assignment_min,
                "escalated": escalated,
                "returned_for_refinement": returned,
            })

        total_routing += routing_count
        total_resp_changes += resp_changes
        total_group_changes += group_changes

    n = len(result_tasks)
    avg_routing = round(total_routing / n, 1) if n else 0
    avg_time_to_assign = round(total_time_to_assign / tasks_with_time, 1) if tasks_with_time else 0

    return {
        "by_task": result_tasks,
        "summary": {
            "avg_routing_count": avg_routing,
            "avg_time_to_assignment_min": avg_time_to_assign,
            "tasks_with_escalation": escalation_count,
            "tasks_returned_for_refinement": returned_count,
            "total_tasks_analyzed": n,
        },
    }

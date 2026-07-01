"""SLA metrics computation engine."""

from datetime import datetime, date
from typing import Any, Dict, List, Optional, Tuple

from sla.business_hours import WorkingHours, business_seconds, format_duration

STATUS_LABELS: Dict[str, str] = {
    "1": "Новая",
    "2": "Ждет выполнения",
    "3": "В работе",
    "4": "Ожидает",
    "5": "Завершена",
    "6": "Отложена",
    "7": "Отклонена",
}

PRIORITY_LABELS: Dict[str, str] = {
    "1": "Низкий",
    "2": "Нормальный",
    "3": "Высокий",
    "4": "Критический",
}


def parse_bitrix_datetime(s: Optional[str]) -> Optional[datetime]:
    """Parse Bitrix24 ISO datetime, return naive datetime (local time)."""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt
    except (ValueError, TypeError):
        return None


def _build_wh(settings: Any) -> WorkingHours:
    """Build WorkingHours from app Settings object."""
    return WorkingHours(
        work_start=settings.working_hours.start,
        work_end=settings.working_hours.end,
        workdays=settings.working_hours.workdays,
        holidays=settings.working_hours.holidays,
    )


def _find_first_response(
    history: List[Dict[str, Any]],
    comments: List[Dict[str, Any]],
    elapsed: List[Dict[str, Any]],
    task: Dict[str, Any],
    signal: str,
) -> Tuple[Optional[datetime], Optional[str]]:
    """Find first response time based on chosen signal with fallback chain.

    Returns (datetime, signal_used) or (None, None).
    Fallback chain: chosen -> status -> comment -> elapsed.
    """
    # Gather candidates
    candidates: Dict[str, Optional[datetime]] = {}

    # Status-based: first STATUS change by someone other than creator
    status_events = [
        h for h in history
        if h["field"] == "STATUS" and h["user_id"] != task.get("created_by", 0)
    ]
    if not status_events:
        status_events = [h for h in history if h["field"] == "STATUS"]
    status_dates = [parse_bitrix_datetime(h["created_date"]) for h in status_events]
    status_dates = [d for d in status_dates if d is not None]
    if status_dates:
        candidates["status"] = status_dates[0]

    # Comment-based: first comment by someone other than creator
    comment_dates = [
        parse_bitrix_datetime(c["created_date"])
        for c in comments
        if c.get("author_id", 0) != task.get("created_by", 0)
    ]
    comment_dates = [d for d in comment_dates if d is not None]
    if comment_dates:
        candidates["comment"] = comment_dates[0]

    # Elapsed-based: first elapsed entry
    elapsed_dates = [
        parse_bitrix_datetime(e["created_date"]) for e in elapsed
    ]
    elapsed_dates = [d for d in elapsed_dates if d is not None]
    if elapsed_dates:
        candidates["elapsed"] = elapsed_dates[0]

    # Build order: chosen first, then the rest in fixed order
    fallback_order = ["status", "comment", "elapsed"]
    order = [signal] + [s for s in fallback_order if s != signal]

    for s in order:
        if s in candidates and candidates[s] is not None:
            return candidates[s], s

    return None, None


def _compute_time_in_status(
    history: List[Dict[str, Any]],
    created_at: datetime,
    closed_at: Optional[datetime],
    wh: WorkingHours,
) -> Dict[str, int]:
    """Compute business seconds spent in each status.

    Returns dict mapping status label -> seconds.
    """
    # Collect STATUS events, sorted by created_date
    status_events = []
    for h in history:
        if h["field"] == "STATUS":
            dt = parse_bitrix_datetime(h["created_date"])
            if dt:
                status_events.append((dt, h.get("old_value", ""), h.get("new_value", "")))

    status_events.sort(key=lambda x: x[0])

    end_time = closed_at if closed_at else datetime.now()

    # Build timeline segments
    segments: List[Tuple[datetime, str]] = []

    if status_events:
        # Initial status is OLD_VALUE of first event, or default "2"
        initial_status = status_events[0][1] or "2"
        segments.append((created_at, initial_status))
        for dt, _old_val, new_val in status_events:
            # Only add if timestamp >= previous
            if dt >= segments[-1][0]:
                segments.append((dt, new_val))
    else:
        # No history — single segment from creation to end with current status
        return {}

    # Compute durations
    result: Dict[str, int] = {}
    for i in range(len(segments) - 1):
        seg_start = segments[i][0]
        seg_end = segments[i + 1][0]
        status_val = segments[i][1]

        if seg_end <= seg_start:
            continue

        sec = business_seconds(seg_start, seg_end, wh)
        label = STATUS_LABELS.get(str(status_val), str(status_val))
        result[label] = result.get(label, 0) + sec

    # Last segment from last event to end_time
    if segments:
        last_status = segments[-1][1]
        last_time = segments[-1][0]
        if end_time > last_time:
            sec = business_seconds(last_time, end_time, wh)
            label = STATUS_LABELS.get(str(last_status), str(last_status))
            result[label] = result.get(label, 0) + sec

    return result


def compute_task_metrics(
    task: Dict[str, Any],
    history: List[Dict[str, Any]],
    comments: List[Dict[str, Any]],
    elapsed: List[Dict[str, Any]],
    settings: Any,
    signal: str = "status",
) -> Dict[str, Any]:
    """Compute all SLA metrics for a single task.

    Returns a flat dict with computed values.
    """
    created_at = parse_bitrix_datetime(task.get("created_date"))
    closed_at = parse_bitrix_datetime(task.get("closed_date"))
    deadline = parse_bitrix_datetime(task.get("deadline"))

    wh = _build_wh(settings)
    priority = int(task.get("priority", 2))
    status_val = str(task.get("status", "2"))

    # SLA thresholds
    thr_min_fr, thr_min_res = settings.sla.get_threshold(priority)

    # First response
    first_response_at, fr_signal_used = _find_first_response(
        history, comments, elapsed, task, signal
    )

    first_response_biz_sec: Optional[int] = None
    if first_response_at and created_at:
        first_response_biz_sec = business_seconds(created_at, first_response_at, wh)

    sla_first_response_met: Optional[bool] = None
    if first_response_biz_sec is not None:
        sla_first_response_met = first_response_biz_sec <= thr_min_fr * 60

    # Resolution
    resolution_biz_sec: Optional[int] = None
    if created_at and closed_at:
        resolution_biz_sec = business_seconds(created_at, closed_at, wh)

    sla_resolution_met: Optional[bool] = None
    if resolution_biz_sec is not None:
        sla_resolution_met = resolution_biz_sec <= thr_min_res * 60

    # Deadline
    deadline_met: Optional[bool] = None
    if closed_at and deadline:
        deadline_met = closed_at <= deadline

    # Time in status
    if created_at:
        time_in_status = _compute_time_in_status(history, created_at, closed_at, wh)
    else:
        time_in_status = {}

    return {
        "task_id": task.get("id"),
        "title": task.get("title", ""),
        "priority": priority,
        "priority_label": PRIORITY_LABELS.get(str(priority), str(priority)),
        "status": task.get("status"),
        "status_label": STATUS_LABELS.get(status_val, status_val),
        "responsible_id": task.get("responsible_id"),
        "created_by": task.get("created_by"),
        "group_id": task.get("group_id"),
        "created_at": created_at,
        "closed_at": closed_at,
        "deadline": deadline,
        "first_response_at": first_response_at,
        "first_response_signal": fr_signal_used,
        "first_response_biz_sec": first_response_biz_sec,
        "first_response_str": format_duration(first_response_biz_sec) if first_response_biz_sec is not None else "—",
        "resolution_biz_sec": resolution_biz_sec,
        "resolution_str": format_duration(resolution_biz_sec) if resolution_biz_sec is not None else "—",
        "deadline_met": deadline_met,
        "sla_first_response_met": sla_first_response_met,
        "sla_resolution_met": sla_resolution_met,
        "sla_first_response_threshold": thr_min_fr,
        "sla_resolution_threshold": thr_min_res,
        "time_in_status": {k: format_duration(v) for k, v in time_in_status.items()},
        "time_in_status_sec": time_in_status,
    }


def aggregate(metrics_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate per-task metrics into summary statistics.

    Returns dict with kpis, by_priority, by_assignee.
    """
    total = len(metrics_list)

    # KPI calculations
    fr_met = sum(
        1 for m in metrics_list if m.get("sla_first_response_met") is True
    )
    fr_total = sum(
        1 for m in metrics_list if m.get("sla_first_response_met") is not None
    )
    res_met = sum(
        1 for m in metrics_list if m.get("sla_resolution_met") is True
    )
    res_total = sum(
        1 for m in metrics_list if m.get("sla_resolution_met") is not None
    )
    dl_met = sum(1 for m in metrics_list if m.get("deadline_met") is True)
    dl_total = sum(1 for m in metrics_list if m.get("deadline_met") is not None)

    fr_values = [m["first_response_biz_sec"] for m in metrics_list if m.get("first_response_biz_sec") is not None]
    res_values = [m["resolution_biz_sec"] for m in metrics_list if m.get("resolution_biz_sec") is not None]

    # Breached: negative SLA status for either first_response or resolution
    breached = sum(
        1 for m in metrics_list
        if m.get("sla_first_response_met") is False
        or m.get("sla_resolution_met") is False
    )

    # Unique SLA met: where we have an opinion and all opinions agree
    sla_fully_met = sum(
        1 for m in metrics_list
        if (
            (m.get("sla_first_response_met") is True or m.get("sla_first_response_met") is None)
            and (m.get("sla_resolution_met") is True or m.get("sla_resolution_met") is None)
            and (m.get("sla_first_response_met") is not None or m.get("sla_resolution_met") is not None)
            and not (m.get("sla_first_response_met") is False or m.get("sla_resolution_met") is False)
        )
    )

    kpis = {
        "total": total,
        "sla_first_response_pct": round(fr_met / fr_total * 100, 1) if fr_total > 0 else None,
        "sla_resolution_pct": round(res_met / res_total * 100, 1) if res_total > 0 else None,
        "deadline_met_pct": round(dl_met / dl_total * 100, 1) if dl_total > 0 else None,
        "avg_first_response_min": round(sum(fr_values) / len(fr_values) / 60, 1) if fr_values else None,
        "avg_resolution_min": round(sum(res_values) / len(res_values) / 60, 1) if res_values else None,
        "breached_count": breached,
        "sla_fully_met": sla_fully_met,
    }

    # By priority
    prio_groups: Dict[int, List[Dict]] = {}
    for m in metrics_list:
        p = m["priority"]
        prio_groups.setdefault(p, []).append(m)

    by_priority = []
    for p in sorted(prio_groups):
        group = prio_groups[p]
        g_fr_met = sum(1 for m in group if m.get("sla_first_response_met") is True)
        g_fr_tot = sum(1 for m in group if m.get("sla_first_response_met") is not None)
        g_res_met = sum(1 for m in group if m.get("sla_resolution_met") is True)
        g_res_tot = sum(1 for m in group if m.get("sla_resolution_met") is not None)
        g_fr_v = [m["first_response_biz_sec"] for m in group if m.get("first_response_biz_sec") is not None]
        g_res_v = [m["resolution_biz_sec"] for m in group if m.get("resolution_biz_sec") is not None]
        by_priority.append({
            "priority": p,
            "label": PRIORITY_LABELS.get(str(p), str(p)),
            "total": len(group),
            "sla_first_response_pct": round(g_fr_met / g_fr_tot * 100, 1) if g_fr_tot > 0 else None,
            "sla_resolution_pct": round(g_res_met / g_res_tot * 100, 1) if g_res_tot > 0 else None,
            "avg_first_response_min": round(sum(g_fr_v) / len(g_fr_v) / 60, 1) if g_fr_v else None,
            "avg_resolution_min": round(sum(g_res_v) / len(g_res_v) / 60, 1) if g_res_v else None,
        })

    # By assignee (by final responsible_id)
    assignee_groups: Dict[int, List[Dict]] = {}
    for m in metrics_list:
        rid = m.get("responsible_id") or 0
        assignee_groups.setdefault(rid, []).append(m)

    by_assignee = []
    for rid, group in sorted(assignee_groups.items(), key=lambda x: -len(x[1])):
        g_fr_met = sum(1 for m in group if m.get("sla_first_response_met") is True)
        g_fr_tot = sum(1 for m in group if m.get("sla_first_response_met") is not None)
        g_res_met = sum(1 for m in group if m.get("sla_resolution_met") is True)
        g_res_tot = sum(1 for m in group if m.get("sla_resolution_met") is not None)
        g_fr_v = [m["first_response_biz_sec"] for m in group if m.get("first_response_biz_sec") is not None]
        g_res_v = [m["resolution_biz_sec"] for m in group if m.get("resolution_biz_sec") is not None]
        by_assignee.append({
            "id": rid,
            "name": f"Сотрудник #{rid}" if rid else "Не назначен",
            "total": len(group),
            "sla_first_response_pct": round(g_fr_met / g_fr_tot * 100, 1) if g_fr_tot > 0 else None,
            "sla_resolution_pct": round(g_res_met / g_res_tot * 100, 1) if g_res_tot > 0 else None,
            "avg_first_response_min": round(sum(g_fr_v) / len(g_fr_v) / 60, 1) if g_fr_v else None,
            "avg_resolution_min": round(sum(g_res_v) / len(g_res_v) / 60, 1) if g_res_v else None,
        })

    return {
        "kpis": kpis,
        "by_priority": by_priority,
        "by_assignee": by_assignee,
    }

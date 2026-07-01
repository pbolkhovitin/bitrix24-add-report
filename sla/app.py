"""FastAPI web application for Bitrix24 SLA reporting dashboard."""

import argparse
import json
import os
import threading
import logging
from contextlib import asynccontextmanager
from datetime import date, time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from apscheduler.schedulers.background import BackgroundScheduler

from sla.config import load_settings, Settings
from sla.store import Store
from sla.bitrix import BitrixClient, BitrixNotConfigured
from sla.sync import SyncService
from sla.metrics import compute_task_metrics, aggregate, STATUS_LABELS, PRIORITY_LABELS
from sla.demo import seed_demo

logger = logging.getLogger(__name__)

# ---- CLI argument parsing ----

_cli_args = None


def _parse_cli():
    global _cli_args
    if _cli_args is None:
        parser = argparse.ArgumentParser(description="Bitrix24 SLA Reporting Dashboard")
        parser.add_argument("--demo", action="store_true", help="Run in demo mode")
        parser.add_argument("--port", type=int, default=0, help="Port override")
        _cli_args, _ = parser.parse_known_args()
    return _cli_args


# ---- Module-level globals ----

settings: Settings = None  # type: ignore[assignment]
store: Store = None  # type: ignore[assignment]
sync_service: Optional[SyncService] = None
scheduler: Optional[BackgroundScheduler] = None


def _build_wh_kwargs():
    """Return working hours dict for API consumption."""
    return {
        "start": settings.working_hours.start.strftime("%H:%M"),
        "end": settings.working_hours.end.strftime("%H:%M"),
        "workdays": sorted(settings.working_hours.workdays),
        "holidays": [str(h) for h in sorted(settings.working_hours.holidays)],
    }


def _get_sla_thresholds():
    """Return SLA thresholds dict for API consumption."""
    result = {}
    for k, v in settings.sla.thresholds.items():
        result[str(k)] = v
    return result


def _build_filters_from_query(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    responsible_id: Optional[int] = None,
    priority: Optional[int] = None,
    group_id: Optional[int] = None,
) -> Dict[str, Any]:
    filters: Dict[str, Any] = {}
    if from_date:
        filters["date_from"] = from_date
    if to_date:
        filters["date_to"] = to_date
    if responsible_id is not None:
        filters["responsible_id"] = responsible_id
    if priority is not None:
        filters["priority"] = priority
    if group_id is not None:
        filters["group_id"] = group_id
    return filters


def _compute_all_metrics(
    filters: Dict[str, Any], signal: str = "status"
) -> List[Dict[str, Any]]:
    """Fetch tasks from store and compute metrics for all of them."""
    tasks = store.get_tasks(filters) if store else []
    results = []
    for t in tasks:
        history = store.get_history(t["id"])
        comments = store.get_comments(t["id"])
        elapsed = store.get_elapsed(t["id"])
        m = compute_task_metrics(t, history, comments, elapsed, settings, signal)
        results.append(m)
    return results


def _enrich_assignee_names(agg_result: Dict[str, Any]) -> None:
    """Replace placeholder assignee names with real names from the store."""
    if not store:
        return
    users_map = store.users_map()
    for item in agg_result.get("by_assignee", []):
        uid = item.get("id", 0)
        if uid in users_map:
            u = users_map[uid]
            item["name"] = u.get("full_name", u.get("name", f"Сотрудник #{uid}"))
        elif uid == 0:
            item["name"] = "Не назначен"


# ---- Lifespan ----

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize services on startup, clean up on shutdown."""
    global settings, store, sync_service, scheduler

    if settings is None:
        # Not pre-set by __main__, load now
        args = _parse_cli()
        s = load_settings()
        if args.demo:
            s.demo = True
        if args.port:
            s.server.port = args.port
        settings = s

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    store = Store()

    if settings.demo:
        logger.info("Demo mode: seeding sample data...")
        seed_demo(store, settings)
        logger.info("Demo data seeded.")
    else:
        client = BitrixClient(
            portal_url=settings.bitrix.portal_url,
            webhook_user=settings.bitrix.webhook_user,
            webhook_token=settings.bitrix.webhook_token,
            timeout=settings.bitrix.request_timeout,
            batch_size=settings.bitrix.batch_size,
        )
        sync_service = SyncService(client, store, settings)

        # One-shot initial sync
        try:
            sync_service.sync_all()
        except Exception as e:
            logger.warning("Initial sync failed: %s", e)

        # Periodic sync
        scheduler = BackgroundScheduler()
        scheduler.add_job(
            sync_service.sync_all,
            "interval",
            minutes=settings.sync.interval_minutes,
            id="sla_sync",
        )
        scheduler.start()
        logger.info("Scheduler started (interval=%d min)", settings.sync.interval_minutes)

    yield

    if scheduler:
        scheduler.shutdown(wait=False)
    if store:
        store.close()


# ---- FastAPI app ----

base_dir = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(base_dir / "templates"))

app = FastAPI(
    title="SLA отчёт техподдержки Bitrix24",
    version="1.0.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=str(base_dir / "static")), name="static")


# ---- Routes ----

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "demo_mode": settings.demo if settings else False,
            "config_loaded": settings.config_loaded if settings else False,
        },
    )


@app.get("/api/summary")
def get_summary(
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    responsible_id: Optional[int] = Query(None),
    priority: Optional[int] = Query(None),
    group_id: Optional[int] = Query(None),
    signal: str = Query("status"),
):
    filters = _build_filters_from_query(from_date, to_date, responsible_id, priority, group_id)
    metrics_list = _compute_all_metrics(filters, signal)
    result = aggregate(metrics_list)
    _enrich_assignee_names(result)
    return result


@app.get("/api/tasks")
def get_tasks(
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    responsible_id: Optional[int] = Query(None),
    priority: Optional[int] = Query(None),
    group_id: Optional[int] = Query(None),
    signal: str = Query("status"),
    limit: int = Query(500, le=1000),
):
    filters = _build_filters_from_query(from_date, to_date, responsible_id, priority, group_id)
    metrics_list = _compute_all_metrics(filters, signal)

    # Enrich with assignee names
    users_map = store.users_map() if store else {}
    for m in metrics_list:
        rid = m.get("responsible_id")
        if rid and rid in users_map:
            m["responsible_name"] = users_map[rid].get("full_name", f"#{rid}")
        else:
            m["responsible_name"] = f"#{rid}" if rid else "—"

    return metrics_list[:limit]


@app.get("/api/timeline")
def get_timeline(
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    responsible_id: Optional[int] = Query(None),
    priority: Optional[int] = Query(None),
    group_id: Optional[int] = Query(None),
    signal: str = Query("status"),
    bucket: str = Query("day"),
):
    filters = _build_filters_from_query(from_date, to_date, responsible_id, priority, group_id)
    metrics_list = _compute_all_metrics(filters, signal)

    buckets: Dict[str, Dict] = {}
    for m in metrics_list:
        created = m.get("created_at")
        if not created:
            continue
        if isinstance(created, str):
            from datetime import datetime
            created = datetime.fromisoformat(created)

        if bucket == "week":
            iso_year, iso_week, _ = created.isocalendar()
            key = f"{iso_year}-W{iso_week:02d}"
        else:
            key = created.strftime("%Y-%m-%d")

        if key not in buckets:
            buckets[key] = {"bucket": key, "total": 0, "breached": 0}
        buckets[key]["total"] += 1
        if m.get("sla_first_response_met") is False or m.get("sla_resolution_met") is False:
            buckets[key]["breached"] += 1

    return sorted(buckets.values(), key=lambda x: x["bucket"])


@app.get("/api/status_distribution")
def get_status_distribution(
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    responsible_id: Optional[int] = Query(None),
    priority: Optional[int] = Query(None),
    group_id: Optional[int] = Query(None),
    signal: str = Query("status"),
):
    filters = _build_filters_from_query(from_date, to_date, responsible_id, priority, group_id)
    metrics_list = _compute_all_metrics(filters, signal)

    counts: Dict[str, int] = {}
    avg_sec: Dict[str, float] = {}
    for m in metrics_list:
        label = m.get("status_label", "Неизвестно")
        counts[label] = counts.get(label, 0) + 1
        if m.get("resolution_biz_sec") is not None:
            if label not in avg_sec:
                avg_sec[label] = 0.0
            avg_sec[label] += m["resolution_biz_sec"]
    for label in avg_sec:
        if counts.get(label, 0) > 0:
            avg_sec[label] = round(avg_sec[label] / counts[label], 1)

    return {"counts": counts, "avg_resolution_sec": avg_sec}


@app.get("/api/filters")
def get_filters():
    if not store:
        return {"responsibles": [], "priorities": [], "groups": []}

    users_map = store.users_map()
    # Only include users that appear as responsible_id in tasks
    tasks = store.get_tasks()
    used_ids = set()
    for t in tasks:
        rid = t.get("responsible_id")
        if rid:
            used_ids.add(rid)

    responsibles = []
    for uid in sorted(used_ids):
        if uid in users_map:
            responsibles.append({
                "id": uid,
                "name": users_map[uid].get("full_name", f"Сотрудник #{uid}"),
            })
        else:
            responsibles.append({"id": uid, "name": f"Сотрудник #{uid}"})

    priorities = [
        {"id": p, "label": PRIORITY_LABELS.get(str(p), str(p))}
        for p in [1, 2, 3, 4]
    ]
    groups = store.get_groups()

    return {"responsibles": responsibles, "priorities": priorities, "groups": groups}


@app.post("/api/sync")
def trigger_sync():
    if settings.demo:
        raise HTTPException(400, "Sync not available in demo mode")
    if not sync_service:
        raise HTTPException(503, "Sync service not initialized")

    thread = threading.Thread(target=sync_service.sync_all, daemon=True)
    thread.start()
    return {"started": True}


@app.get("/api/config")
def get_config():
    if not settings:
        return {}
    return {
        "working_hours": _build_wh_kwargs(),
        "sla_thresholds": _get_sla_thresholds(),
        "demo_mode": settings.demo,
        "status_labels": STATUS_LABELS,
        "priority_labels": PRIORITY_LABELS,
    }


@app.post("/api/config")
def update_config(data: dict):
    global settings

    if not settings:
        raise HTTPException(503, "Settings not initialized")

    # Merge with existing overrides
    overrides: Dict[str, Any] = {}
    override_path = "sla_config_override.json"
    if os.path.exists(override_path):
        try:
            with open(override_path, "r") as f:
                overrides = json.load(f)
        except Exception:
            overrides = {}

    if "thresholds" in data:
        thr = data["thresholds"]
        overrides["thresholds"] = thr
        for k, v in thr.items():
            settings.sla.thresholds[str(k)] = v

    if "working_hours" in data:
        wh = data["working_hours"]
        overrides["working_hours"] = wh
        if "start" in wh:
            parts = wh["start"].split(":")
            settings.working_hours.start = time(int(parts[0]), int(parts[1]))
        if "end" in wh:
            parts = wh["end"].split(":")
            settings.working_hours.end = time(int(parts[0]), int(parts[1]))
        if "workdays" in wh:
            settings.working_hours.workdays = {int(d) for d in wh["workdays"]}
        if "holidays" in wh:
            settings.working_hours.holidays = {date.fromisoformat(d) for d in wh["holidays"]}

    try:
        with open(override_path, "w") as f:
            json.dump(overrides, f, indent=2, ensure_ascii=False, default=str)
    except Exception as e:
        logger.error("Failed to save config overrides: %s", e)

    return {"ok": True}


# ---- Main entry point ----

if __name__ == "__main__":
    import uvicorn

    args = _parse_cli()
    s = load_settings()
    if args.demo:
        s.demo = True
    if args.port:
        s.server.port = args.port

    # Set module-level settings before server starts so lifespan can use them
    import sla.app as app_module
    app_module.settings = s

    print(f"Starting SLA dashboard on http://{s.server.host}:{s.server.port}")
    if s.demo:
        print(" DEMO MODE — using sample data")

    uvicorn.run(
        "sla.app:app",
        host=s.server.host,
        port=s.server.port,
        reload=False,
    )

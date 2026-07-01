"""Synchronization service between Bitrix24 API and local SQLite store."""

import json
import logging
from datetime import datetime

from sla.bitrix import BitrixClient, BitrixNotConfigured, BitrixError
from sla.store import Store
from sla.config import Settings

logger = logging.getLogger(__name__)


def _normalize_dt(dt_str: str) -> str:
    """Strip timezone info from ISO datetime."""
    if not dt_str:
        return dt_str
    try:
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt.isoformat()
    except (ValueError, TypeError):
        return dt_str


class SyncService:
    """Periodic sync service for tracking Bitrix24 support tasks."""

    def __init__(self, client: BitrixClient, store: Store, settings: Settings):
        self.client = client
        self.store = store
        self.settings = settings

    def sync_all(self) -> None:
        """Full sync: discover TP queue tasks and refresh all tracked tasks."""
        try:
            self._discover_and_refresh()
        except BitrixNotConfigured:
            logger.info("Sync skipped: Bitrix24 not configured (demo mode)")
        except Exception as e:
            logger.error("Sync failed: %s", e, exc_info=True)

    def _discover_and_refresh(self) -> None:
        """Discover new tasks from TP queue and refresh all tracked data."""
        logger.info("Starting sync cycle...")

        # Step 1: fetch tasks assigned to the TP user
        if self.settings.bitrix.tp_user_id:
            try:
                tp_tasks = self.client.list_all_tasks(
                    filter={"RESPONSIBLE_ID": self.settings.bitrix.tp_user_id},
                    select=["ID", "TITLE", "STATUS", "PRIORITY", "RESPONSIBLE_ID",
                            "CREATED_BY", "GROUP_ID", "DEADLINE", "CREATED_DATE",
                            "CLOSED_DATE", "CHANGED_DATE", "CLOSED_BY", "TAGS"],
                )
                for t in tp_tasks:
                    self.store.adopt_task(int(t.get("ID", 0)))
                logger.info("Discovered %d tasks in TP queue", len(tp_tasks))
            except BitrixError as e:
                logger.warning("Failed to discover TP tasks: %s", e)

        # Step 2: refresh all tracked tasks
        tracked_ids = self.store.all_tracked_ids()
        logger.info("Refreshing %d tracked tasks...", len(tracked_ids))

        for tid in tracked_ids:
            self._refresh_task(tid)

        # Step 3: sync users
        self._sync_users()

        self.store.set_sync_state("last_sync", datetime.now().isoformat())
        logger.info("Sync cycle complete.")

    def _refresh_task(self, task_id: int) -> None:
        """Refresh all data for a single task."""
        # Task data
        try:
            task_data = self.client.task_get(task_id)
            if task_data:
                self._upsert_task_from_api(task_data)
        except Exception as e:
            logger.error("Error refreshing task %d: %s", task_id, e)

        # History
        try:
            history = self.client.task_history(task_id)
            self.store.delete_history_for_task(task_id)
            for h in history:
                self.store.add_history(
                    task_id=task_id,
                    user_id=int(h.get("USER_ID", 0)),
                    field=h.get("FIELD", ""),
                    old_value=h.get("OLD_VALUE", ""),
                    new_value=h.get("NEW_VALUE", ""),
                    created_date=_normalize_dt(h.get("CREATED_DATE", "")),
                )
        except Exception as e:
            logger.error("Error refreshing history for task %d: %s", task_id, e)

        # Comments (best-effort, may be deprecated on new portals)
        try:
            comments = self.client.task_comments(task_id)
            for c in comments:
                self.store.upsert_comment(
                    comment_id=int(c.get("ID", 0)),
                    task_id=task_id,
                    author_id=int(c.get("AUTHOR_ID", 0)),
                    created_date=_normalize_dt(c.get("POST_DATE", c.get("CREATED_DATE", ""))),
                    content=c.get("POST_MESSAGE", c.get("COMMENT", "")),
                )
        except Exception as e:
            logger.warning("Error refreshing comments for task %d: %s", task_id, e)

        # Elapsed time
        try:
            elapsed = self.client.task_elapsed(task_id)
            for e in elapsed:
                self.store.upsert_elapsed(
                    elapsed_id=int(e.get("ID", 0)),
                    task_id=task_id,
                    user_id=int(e.get("USER_ID", 0)),
                    seconds=int(e.get("SECONDS", 0)),
                    created_date=_normalize_dt(e.get("CREATED_DATE", "")),
                    comment=e.get("COMMENT", ""),
                )
        except Exception as e:
            logger.warning("Error refreshing elapsed for task %d: %s", task_id, e)

    def _sync_users(self) -> None:
        """Fetch and store user data."""
        try:
            users = self.client.user_get()
            for u in users:
                self.store.upsert_user(
                    user_id=int(u.get("ID", 0)),
                    name=u.get("NAME", ""),
                    last_name=u.get("LAST_NAME", ""),
                    full_name=u.get("FULL_NAME", ""),
                    active=int(u.get("ACTIVE", True)),
                )
        except Exception as e:
            logger.warning("Error syncing users: %s", e)

    def _upsert_task_from_api(self, task_data: dict) -> None:
        """Convert Bitrix24 API task dict to store format."""
        self.store.upsert_task(
            task_id=int(task_data.get("ID", 0)),
            title=task_data.get("TITLE", ""),
            status=int(task_data.get("STATUS", 0)),
            priority=int(task_data.get("PRIORITY", 2)),
            responsible_id=int(task_data.get("RESPONSIBLE_ID", 0)),
            created_by=int(task_data.get("CREATED_BY", 0)),
            group_id=int(task_data.get("GROUP_ID", 0)),
            deadline=_normalize_dt(task_data.get("DEADLINE", "")),
            created_date=_normalize_dt(task_data.get("CREATED_DATE", "")),
            closed_date=_normalize_dt(task_data.get("CLOSED_DATE", "")),
            changed_date=_normalize_dt(task_data.get("CHANGED_DATE", "")),
            closed_by=int(task_data.get("CLOSED_BY", 0)),
            tags=task_data.get("TAGS", ""),
            raw=json.dumps(task_data, ensure_ascii=False),
        )

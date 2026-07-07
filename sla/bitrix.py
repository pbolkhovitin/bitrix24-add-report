"""Bitrix24 REST API client with webhook authentication."""

import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class BitrixError(Exception):
    """Bitrix24 API returned an error response."""


class BitrixNotConfigured(BitrixError):
    """Bitrix24 is not configured (demo mode or missing token)."""


def _build_url(portal_url: str, webhook_user: str, webhook_token: str, method: str) -> str:
    base = portal_url.rstrip("/")
    return f"{base}/rest/{webhook_user}/{webhook_token}/{method}/"


class BitrixClient:
    """Client for Bitrix24 REST API via incoming webhook."""

    def __init__(
        self,
        portal_url: str,
        webhook_user: str,
        webhook_token: str,
        timeout: int = 30,
        batch_size: int = 50,
        demo: bool = False,
    ):
        self.demo = demo
        self.timeout = timeout
        self.batch_size = batch_size
        self.base_url = _build_url(portal_url, webhook_user, webhook_token, "")

    def call(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute a single REST API call."""
        if self.demo:
            raise BitrixNotConfigured("Demo mode — Bitrix24 API not available")

        url = self.base_url + method
        params = params or {}

        for attempt in range(2):
            try:
                resp = httpx.post(url, json=params, timeout=self.timeout)
                resp.raise_for_status()
                data = resp.json()
                if "error" in data:
                    raise BitrixError(
                        f"{data['error']}: {data.get('error_description', '')}"
                    )
                return data
            except httpx.HTTPStatusError as e:
                if attempt == 0:
                    logger.warning("Retrying %s after HTTP error: %s", method, e)
                    continue
                raise BitrixError(f"HTTP error after retry: {e}") from e
            except httpx.TimeoutException as e:
                if attempt == 0:
                    logger.warning("Retrying %s after timeout: %s", method, e)
                    continue
                raise BitrixError(f"Timeout after retry: {e}") from e

        raise BitrixError(f"Unexpected error calling {method}")  # pragma: no cover

    def list_all_tasks(
        self,
        filter: Optional[Dict[str, Any]] = None,
        select: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Paginate tasks.task.list, handling nested result shape.

        tasks.task.list returns: {"result": {"tasks": [...], "total": N}}
        Default select includes all standard fields + all custom UF_* fields.
        """
        params: Dict[str, Any] = {}
        if filter:
            params["filter"] = filter
        if select is None:
            select = ["*", "UF_*"]
        params["select"] = select

        all_tasks: List[Dict[str, Any]] = []
        start = 0
        while True:
            params["start"] = start
            data = self.call("tasks.task.list", params)
            result = data.get("result", {})
            tasks = result.get("tasks", [])
            total = result.get("total", 0)
            all_tasks.extend(tasks)
            start += self.batch_size
            if start >= total:
                break
        return all_tasks

    # ---- Thin wrappers ----

    def task_get(self, task_id: int) -> Optional[Dict[str, Any]]:
        try:
            data = self.call("tasks.task.get", {"taskId": task_id})
            return data.get("result", {}).get("task")
        except BitrixError as e:
            logger.error("task_get(%s) failed: %s", task_id, e)
            return None

    def task_history(self, task_id: int) -> List[Dict[str, Any]]:
        try:
            data = self.call("tasks.task.history.list", {"taskId": task_id})
            return data.get("result", [])
        except BitrixError as e:
            logger.error("task_history(%s) failed: %s", task_id, e)
            return []

    def task_comments(self, task_id: int) -> List[Dict[str, Any]]:
        """Get comments for a task.

        May be deprecated on very new portals (comments moved to Stream).
        Wrap in try/except — failures are non-fatal.
        """
        try:
            data = self.call("task.commentitem.getlist", {"TASKID": task_id})
            return data.get("result", [])
        except BitrixError as e:
            logger.warning("task_comments(%s) unavailable: %s", task_id, e)
            return []

    def task_elapsed(self, task_id: int) -> List[Dict[str, Any]]:
        try:
            data = self.call("task.elapseditem.getlist", {"TASKID": task_id})
            return data.get("result", [])
        except BitrixError as e:
            logger.warning("task_elapsed(%s) unavailable: %s", task_id, e)
            return []

    def user_get(self, ids: Optional[List[int]] = None) -> List[Dict[str, Any]]:
        try:
            params: Dict[str, Any] = {}
            if ids:
                params["ID"] = ",".join(str(i) for i in ids)
            params["SELECT"] = ["WORK_POSITION", "UF_DEPARTMENT"]
            data = self.call("user.get", params)
            return data.get("result", [])
        except BitrixError as e:
            logger.error("user_get failed: %s", e)
            return []

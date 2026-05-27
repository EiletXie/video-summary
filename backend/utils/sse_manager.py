import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class TaskStore:
    """Thread-safe in-memory task store."""

    def __init__(self):
        self._tasks: dict = {}

    def create(self, task_id: str):
        self._tasks[task_id] = {
            "status": "queued",
            "stage": "",
            "progress": 0,
            "message": "等待处理...",
            "result_id": None,
        }

    def update(self, task_id: str, stage: str, progress: int, message: str,
               result_id: Optional[str] = None, status: Optional[str] = None):
        """Safe to call from any thread — only does plain dict mutation."""
        t = self._tasks.get(task_id)
        if t is None:
            return
        t["stage"] = stage
        t["progress"] = progress
        t["message"] = message
        if result_id:
            t["result_id"] = result_id
        if status:
            t["status"] = status

    def get(self, task_id: str) -> Optional[dict]:
        return self._tasks.get(task_id)

    def cleanup(self, task_id: str):
        self._tasks.pop(task_id, None)


store = TaskStore()

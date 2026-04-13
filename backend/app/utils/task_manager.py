"""
Thread-safe singleton TaskManager.
Tracks long-running background tasks (graph build, simulation, report).
"""

import uuid
import threading
from datetime import datetime, timedelta
from typing import Dict, Optional, Any, List


TASK_PENDING = "PENDING"
TASK_PROCESSING = "PROCESSING"
TASK_COMPLETED = "COMPLETED"
TASK_FAILED = "FAILED"


class TaskManager:
    """Singleton task registry with thread-safe access."""

    _instance: Optional["TaskManager"] = None
    _init_lock = threading.Lock()

    def __new__(cls) -> "TaskManager":
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._tasks: Dict[str, Dict[str, Any]] = {}
                    inst._lock = threading.Lock()
                    cls._instance = inst
        return cls._instance

    # -- public API --

    def create_task(
        self, task_type: str, metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Create a new task, return its UUID."""
        task_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        task = {
            "task_id": task_id,
            "task_type": task_type,
            "status": TASK_PENDING,
            "progress": 0,
            "message": "",
            "result": None,
            "error": None,
            "metadata": metadata or {},
            "created_at": now,
            "updated_at": now,
        }
        with self._lock:
            self._tasks[task_id] = task
        return task_id

    def update_task(
        self,
        task_id: str,
        status: Optional[str] = None,
        progress: Optional[int] = None,
        message: Optional[str] = None,
        result: Optional[Any] = None,
        error: Optional[str] = None,
    ) -> None:
        """Partially update task fields (immutable-style copy)."""
        with self._lock:
            existing = self._tasks.get(task_id)
            if existing is None:
                return
            updates: Dict[str, Any] = {"updated_at": datetime.utcnow().isoformat()}
            if status is not None:
                updates["status"] = status
            if progress is not None:
                updates["progress"] = progress
            if message is not None:
                updates["message"] = message
            if result is not None:
                updates["result"] = result
            if error is not None:
                updates["error"] = error
            self._tasks[task_id] = {**existing, **updates}

    def complete_task(self, task_id: str, result: Any) -> None:
        """Mark task completed."""
        self.update_task(
            task_id,
            status=TASK_COMPLETED,
            progress=100,
            message="Task completed",
            result=result,
        )

    def fail_task(self, task_id: str, error: str) -> None:
        """Mark task failed."""
        self.update_task(
            task_id,
            status=TASK_FAILED,
            message="Task failed",
            error=error,
        )

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Return a copy of the task dict, or None."""
        with self._lock:
            task = self._tasks.get(task_id)
            return {**task} if task else None

    def list_tasks(self) -> List[Dict[str, Any]]:
        """Return all tasks sorted by created_at descending."""
        with self._lock:
            items = [{**t} for t in self._tasks.values()]
        return sorted(items, key=lambda t: t["created_at"], reverse=True)

    def cleanup_old_tasks(self, max_age_hours: int = 24) -> int:
        """Remove completed/failed tasks older than max_age_hours. Return count."""
        cutoff = (datetime.utcnow() - timedelta(hours=max_age_hours)).isoformat()
        with self._lock:
            stale_ids = [
                tid
                for tid, t in self._tasks.items()
                if t["status"] in (TASK_COMPLETED, TASK_FAILED)
                and t["created_at"] < cutoff
            ]
            for tid in stale_ids:
                del self._tasks[tid]
        return len(stale_ids)

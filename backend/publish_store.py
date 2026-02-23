"""
Publish queue and history storage — JSON-file based, matching project patterns.
"""

import json
import uuid
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = BASE_DIR / "runtime"
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

QUEUE_STORE_PATH = RUNTIME_DIR / "publish_queue.json"
HISTORY_STORE_PATH = RUNTIME_DIR / "publish_history.json"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Low-level I/O (mirrors proxy_store.py conventions)
# ---------------------------------------------------------------------------

def _read_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    except Exception:
        return []
    return []


def _write_list_atomic(path: Path, payload: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f".{uuid.uuid4().hex[:8]}.tmp")
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        temp_path.replace(path)
    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise


_file_locks: dict[str, threading.Lock] = {}
_meta_lock = threading.Lock()


def _get_file_lock(path: Path) -> threading.Lock:
    key = str(path)
    with _meta_lock:
        if key not in _file_locks:
            _file_locks[key] = threading.Lock()
        return _file_locks[key]


def _read_and_write_locked(path: Path, mutator: Any) -> Any:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = _get_file_lock(path)
    lock.acquire()
    try:
        records = _read_list(path)
        result = mutator(records)
        if isinstance(result, tuple) and len(result) == 2:
            new_records, return_value = result
        else:
            new_records = records
            return_value = result
        _write_list_atomic(path, new_records)
        return return_value
    finally:
        lock.release()


# ---------------------------------------------------------------------------
# Queue CRUD
# ---------------------------------------------------------------------------

ALLOWED_QUEUE_STATUS = {
    "pending", "scheduled", "publishing", "success", "failed", "paused", "cancelled"
}


def create_queue_item(
    *,
    account_id: str,
    tweet_type: str = "text",
    content: dict[str, Any],
    strategy: dict[str, Any] | None = None,
    priority: int = 0,
    max_retries: int = 3,
) -> dict[str, Any]:
    now = now_iso()
    default_strategy = {
        "type": "immediate",
        "scheduled_time": None,
        "interval_minutes": None,
        "daily_limit": None,
        "randomize_offset_minutes": 0,
    }
    if strategy:
        default_strategy.update(strategy)

    initial_status = "pending"
    if default_strategy["type"] == "scheduled" and default_strategy.get("scheduled_time"):
        initial_status = "scheduled"

    record = {
        "id": uuid.uuid4().hex,
        "account_id": str(account_id).strip(),
        "tweet_type": tweet_type,
        "content": content,
        "strategy": default_strategy,
        "status": initial_status,
        "priority": priority,
        "retry_count": 0,
        "max_retries": max_retries,
        "result": {
            "tweet_id": None,
            "tweet_url": None,
            "error": None,
            "published_at": None,
        },
        "created_at": now,
        "updated_at": now,
    }

    def _mutator(records: list[dict]) -> tuple[list[dict], dict]:
        records.append(record)
        return records, record

    return _read_and_write_locked(QUEUE_STORE_PATH, _mutator)


def list_queue_items(
    account_id: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    items = _read_list(QUEUE_STORE_PATH)
    if account_id:
        items = [i for i in items if i.get("account_id") == account_id]
    if status:
        items = [i for i in items if i.get("status") == status]
    items.sort(key=lambda x: (x.get("priority", 0), x.get("created_at", "")))
    return items


def get_queue_item(item_id: str) -> dict[str, Any] | None:
    for item in _read_list(QUEUE_STORE_PATH):
        if item.get("id") == item_id:
            return item
    return None


def update_queue_item(item_id: str, **fields: Any) -> dict[str, Any] | None:
    def _mutator(records: list[dict]) -> tuple[list[dict], dict | None]:
        for i, rec in enumerate(records):
            if rec.get("id") == item_id:
                rec.update(fields)
                rec["updated_at"] = now_iso()
                records[i] = rec
                return records, rec
        return records, None

    return _read_and_write_locked(QUEUE_STORE_PATH, _mutator)


def delete_queue_item(item_id: str) -> bool:
    def _mutator(records: list[dict]) -> tuple[list[dict], bool]:
        filtered = [r for r in records if r.get("id") != item_id]
        return filtered, len(filtered) < len(records)

    return _read_and_write_locked(QUEUE_STORE_PATH, _mutator)


def reorder_queue_item(item_id: str, new_priority: int) -> dict[str, Any] | None:
    return update_queue_item(item_id, priority=new_priority)


def pause_account_queue(account_id: str) -> int:
    """Pause all pending/scheduled items for an account. Returns count."""
    def _mutator(records: list[dict]) -> tuple[list[dict], int]:
        count = 0
        for rec in records:
            if (rec.get("account_id") == account_id
                    and rec.get("status") in ("pending", "scheduled")):
                rec["status"] = "paused"
                rec["updated_at"] = now_iso()
                count += 1
        return records, count

    return _read_and_write_locked(QUEUE_STORE_PATH, _mutator)


def resume_account_queue(account_id: str) -> int:
    """Resume all paused items for an account. Returns count."""
    def _mutator(records: list[dict]) -> tuple[list[dict], int]:
        count = 0
        for rec in records:
            if rec.get("account_id") == account_id and rec.get("status") == "paused":
                strategy_type = (rec.get("strategy") or {}).get("type", "immediate")
                if strategy_type == "scheduled":
                    rec["status"] = "scheduled"
                else:
                    rec["status"] = "pending"
                rec["updated_at"] = now_iso()
                count += 1
        return records, count

    return _read_and_write_locked(QUEUE_STORE_PATH, _mutator)


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

def create_history_record(
    *,
    account_id: str,
    tweet_type: str,
    content: dict[str, Any],
    status: str = "success",
    tweet_id: str | None = None,
    tweet_url: str | None = None,
    error_message: str | None = None,
    queue_item_id: str | None = None,
) -> dict[str, Any]:
    now = now_iso()
    record = {
        "id": uuid.uuid4().hex,
        "account_id": account_id,
        "tweet_type": tweet_type,
        "content": content,
        "status": status,
        "tweet_id": tweet_id,
        "tweet_url": tweet_url,
        "error_message": error_message,
        "queue_item_id": queue_item_id,
        "published_at": now,
    }

    def _mutator(records: list[dict]) -> tuple[list[dict], dict]:
        records.append(record)
        return records, record

    return _read_and_write_locked(HISTORY_STORE_PATH, _mutator)


def list_history(
    account_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    items = _read_list(HISTORY_STORE_PATH)
    if account_id:
        items = [i for i in items if i.get("account_id") == account_id]
    if status:
        items = [i for i in items if i.get("status") == status]
    items.sort(key=lambda x: x.get("published_at", ""), reverse=True)
    return items[:limit]


def count_today_success(account_id: str) -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    return sum(
        1 for h in _read_list(HISTORY_STORE_PATH)
        if h.get("account_id") == account_id
        and h.get("status") == "success"
        and (h.get("published_at") or "").startswith(today)
    )


def get_last_publish_time(account_id: str) -> str | None:
    items = [
        h for h in _read_list(HISTORY_STORE_PATH)
        if h.get("account_id") == account_id and h.get("status") == "success"
    ]
    if not items:
        return None
    items.sort(key=lambda x: x.get("published_at", ""), reverse=True)
    return items[0].get("published_at")

import json
import uuid
import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

BASE_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = BASE_DIR / "runtime"
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

PROXY_STORE_PATH = RUNTIME_DIR / "proxy_ips.json"
BINDING_STORE_PATH = RUNTIME_DIR / "account_proxy_bindings.json"

ALLOWED_PROTOCOLS = {"http", "https", "socks5"}
ALLOWED_PROXY_TYPES = {"publish", "monitor"}
ALLOWED_PROXY_STATUS = {"active", "dead", "slow", "disabled"}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


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
    # 用唯一临时文件名避免并发写冲突
    temp_path = path.with_suffix(f".{uuid.uuid4().hex[:8]}.tmp")
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        temp_path.replace(path)
    except Exception:
        # 清理残留临时文件
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


def _read_and_write_locked(
    path: Path,
    mutator: Any,
) -> Any:
    """带线程锁的读-改-写，防止并发写入冲突。"""
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


def _normalize_protocol(value: str | None) -> str:
    protocol = str(value or "http").strip().lower()
    if protocol not in ALLOWED_PROTOCOLS:
        raise ValueError(f"不支持的代理协议: {protocol}")
    return protocol


def _normalize_proxy_type(value: str | None) -> str:
    proxy_type = str(value or "publish").strip().lower()
    if proxy_type not in ALLOWED_PROXY_TYPES:
        raise ValueError(f"不支持的代理类型: {proxy_type}")
    return proxy_type


def _normalize_proxy_status(value: str | None) -> str:
    status = str(value or "active").strip().lower()
    if status not in ALLOWED_PROXY_STATUS:
        raise ValueError(f"不支持的代理状态: {status}")
    return status


def _normalize_port(port: int | str) -> int:
    parsed = int(port)
    if parsed <= 0 or parsed > 65535:
        raise ValueError("端口范围必须在 1-65535")
    return parsed


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def parse_proxy_input(raw: str) -> dict[str, Any]:
    """
    支持两种输入：
    1) host:port:user:pass
    2) http://user:pass@host:port
    """
    value = str(raw or "").strip()
    if not value:
        raise ValueError("代理输入不能为空")

    if "://" in value:
        parsed = urlparse(value)
        if not parsed.hostname or not parsed.port:
            raise ValueError("代理 URL 缺少 host 或 port")
        if parsed.username is None or parsed.password is None:
            raise ValueError("代理 URL 缺少用户名或密码")
        return {
            "ip": parsed.hostname,
            "port": parsed.port,
            "protocol": _normalize_protocol(parsed.scheme or "http"),
            "username": unquote(parsed.username),
            "password": unquote(parsed.password),
        }

    parts = value.split(":")
    if len(parts) == 2:
        # host:port（无认证）
        host, port = parts
        if not host or not port:
            raise ValueError("代理字段不能为空")
        return {
            "ip": host.strip(),
            "port": _normalize_port(port),
            "protocol": "http",
            "username": None,
            "password": None,
        }
    elif len(parts) == 4:
        host, port, username, password = parts
        if not host or not port or not username or not password:
            raise ValueError("代理字段不能为空")
        return {
            "ip": host.strip(),
            "port": _normalize_port(port),
            "protocol": "http",
            "username": username.strip(),
            "password": password.strip(),
        }
    else:
        raise ValueError("非 URL 代理格式必须是 host:port 或 host:port:user:pass")


def list_proxy_records(
    *, proxy_type: str | None = None, status: str | None = None
) -> list[dict[str, Any]]:
    records = _read_list(PROXY_STORE_PATH)
    if proxy_type:
        normalized_type = _normalize_proxy_type(proxy_type)
        records = [item for item in records if item.get("type") == normalized_type]
    if status:
        normalized_status = _normalize_proxy_status(status)
        records = [item for item in records if item.get("status") == normalized_status]
    return records


def get_proxy_record(proxy_id: str) -> dict[str, Any] | None:
    target_id = str(proxy_id).strip()
    if not target_id:
        return None
    for item in _read_list(PROXY_STORE_PATH):
        if str(item.get("id")) == target_id:
            return item
    return None


def create_proxy_record(
    *,
    ip: str,
    port: int | str,
    protocol: str = "http",
    username: str | None = None,
    password: str | None = None,
    region: str | None = None,
    proxy_type: str = "publish",
    status: str = "active",
) -> dict[str, Any]:
    normalized_ip = str(ip or "").strip()
    if not normalized_ip:
        raise ValueError("ip 不能为空")
    normalized_port = _normalize_port(port)
    normalized_protocol = _normalize_protocol(protocol)
    normalized_proxy_type = _normalize_proxy_type(proxy_type)
    normalized_status = _normalize_proxy_status(status)
    normalized_username = _clean_text(username)
    normalized_password = _clean_text(password)
    normalized_region = _clean_text(region)

    records = _read_list(PROXY_STORE_PATH)
    for item in records:
        if (
            str(item.get("ip", "")).strip().lower() == normalized_ip.lower()
            and int(item.get("port", 0) or 0) == normalized_port
            and str(item.get("protocol", "")).strip().lower() == normalized_protocol
            and str(item.get("username") or "") == (normalized_username or "")
            and str(item.get("type", "")).strip().lower() == normalized_proxy_type
        ):
            raise ValueError("代理记录已存在（ip/port/protocol/username/type 重复）")

    now = now_iso()
    record = {
        "id": uuid.uuid4().hex,
        "ip": normalized_ip,
        "port": normalized_port,
        "protocol": normalized_protocol,
        "username": normalized_username,
        "password": normalized_password,
        "region": normalized_region,
        "type": normalized_proxy_type,
        "status": normalized_status,
        "last_checked_at": None,
        "last_latency_ms": None,
        "last_error": None,
        "last_check_result": None,
        "created_at": now,
        "updated_at": now,
    }
    records.append(record)
    _write_list_atomic(PROXY_STORE_PATH, records)
    return record


def update_proxy_record(proxy_id: str, **fields: Any) -> dict[str, Any] | None:
    target_id = str(proxy_id).strip()
    if not target_id:
        return None

    def _mutator(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        target_index = -1
        for index, item in enumerate(records):
            if str(item.get("id")) == target_id:
                target_index = index
                break
        if target_index < 0:
            return records, None

        target = dict(records[target_index])
        if "ip" in fields:
            normalized_ip = str(fields["ip"] or "").strip()
            if not normalized_ip:
                raise ValueError("ip 不能为空")
            target["ip"] = normalized_ip
        if "port" in fields:
            target["port"] = _normalize_port(fields["port"])
        if "protocol" in fields:
            target["protocol"] = _normalize_protocol(fields["protocol"])
        if "username" in fields:
            target["username"] = _clean_text(fields["username"])
        if "password" in fields:
            target["password"] = _clean_text(fields["password"])
        if "region" in fields:
            target["region"] = _clean_text(fields["region"])
        if "type" in fields:
            target["type"] = _normalize_proxy_type(fields["type"])
        if "status" in fields:
            target["status"] = _normalize_proxy_status(fields["status"])
        if "last_checked_at" in fields:
            target["last_checked_at"] = _clean_text(fields["last_checked_at"])
        if "last_latency_ms" in fields:
            target["last_latency_ms"] = fields["last_latency_ms"]
        if "last_error" in fields:
            target["last_error"] = _clean_text(fields["last_error"])
        if "last_check_result" in fields:
            value = fields["last_check_result"]
            target["last_check_result"] = value if isinstance(value, dict) else None

        target["updated_at"] = now_iso()
        records[target_index] = target
        return records, target

    return _read_and_write_locked(PROXY_STORE_PATH, _mutator)


def delete_proxy_record(proxy_id: str) -> bool:
    target_id = str(proxy_id).strip()
    if not target_id:
        return False

    records = _read_list(PROXY_STORE_PATH)
    filtered_records = [item for item in records if str(item.get("id")) != target_id]
    deleted = len(filtered_records) != len(records)
    if not deleted:
        return False
    _write_list_atomic(PROXY_STORE_PATH, filtered_records)

    # 代理被删除后，自动清理绑定关系，避免悬挂引用。
    bindings = _read_list(BINDING_STORE_PATH)
    filtered_bindings = [item for item in bindings if str(item.get("proxy_id")) != target_id]
    if len(filtered_bindings) != len(bindings):
        _write_list_atomic(BINDING_STORE_PATH, filtered_bindings)
    return True


def list_account_bindings() -> list[dict[str, Any]]:
    return _read_list(BINDING_STORE_PATH)


def upsert_account_binding(
    *,
    platform: str,
    account_uid: str,
    account_name: str | None,
    proxy_id: str,
) -> dict[str, Any]:
    normalized_platform = str(platform or "").strip().lower()
    normalized_uid = str(account_uid or "").strip()
    normalized_proxy_id = str(proxy_id or "").strip()
    normalized_name = _clean_text(account_name)

    if not normalized_platform:
        raise ValueError("platform 不能为空")
    if not normalized_uid:
        raise ValueError("account_uid 不能为空")
    if not normalized_proxy_id:
        raise ValueError("proxy_id 不能为空")

    proxy = get_proxy_record(normalized_proxy_id)
    if proxy is None:
        raise ValueError("proxy_id 不存在")

    bindings = _read_list(BINDING_STORE_PATH)

    # 一对一约束：一个 proxy_id 只能绑定一个账号。
    for item in bindings:
        if (
            str(item.get("proxy_id")) == normalized_proxy_id
            and (
                str(item.get("platform", "")).lower() != normalized_platform
                or str(item.get("account_uid", "")) != normalized_uid
            )
        ):
            raise ValueError("该代理已绑定其他账号，请先解绑")

    target_index = -1
    for index, item in enumerate(bindings):
        if (
            str(item.get("platform", "")).lower() == normalized_platform
            and str(item.get("account_uid", "")) == normalized_uid
        ):
            target_index = index
            break

    now = now_iso()
    if target_index >= 0:
        record = dict(bindings[target_index])
        record["account_name"] = normalized_name
        record["proxy_id"] = normalized_proxy_id
        record["updated_at"] = now
        bindings[target_index] = record
    else:
        record = {
            "id": uuid.uuid4().hex,
            "platform": normalized_platform,
            "account_uid": normalized_uid,
            "account_name": normalized_name,
            "proxy_id": normalized_proxy_id,
            "created_at": now,
            "updated_at": now,
        }
        bindings.append(record)

    _write_list_atomic(BINDING_STORE_PATH, bindings)
    return record


def remove_account_binding(*, platform: str, account_uid: str) -> bool:
    normalized_platform = str(platform or "").strip().lower()
    normalized_uid = str(account_uid or "").strip()
    if not normalized_platform or not normalized_uid:
        return False

    bindings = _read_list(BINDING_STORE_PATH)
    filtered_bindings = [
        item
        for item in bindings
        if not (
            str(item.get("platform", "")).lower() == normalized_platform
            and str(item.get("account_uid", "")) == normalized_uid
        )
    ]
    deleted = len(filtered_bindings) != len(bindings)
    if deleted:
        _write_list_atomic(BINDING_STORE_PATH, filtered_bindings)
    return deleted


def detect_ip_reuse_conflicts() -> list[dict[str, Any]]:
    """
    检测同一出口 IP 下是否绑定多个账号（防关联告警）。
    即便 proxy_id 不同，只要落到同一 ip，也会告警。
    """
    proxies = _read_list(PROXY_STORE_PATH)
    bindings = _read_list(BINDING_STORE_PATH)
    proxies_by_id = {str(item.get("id")): item for item in proxies}

    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in bindings:
        proxy_id = str(item.get("proxy_id") or "")
        proxy = proxies_by_id.get(proxy_id)
        if not proxy:
            continue
        ip = str(proxy.get("ip") or "").strip()
        if not ip:
            continue
        grouped.setdefault(ip, []).append(
            {
                "platform": item.get("platform"),
                "account_uid": item.get("account_uid"),
                "account_name": item.get("account_name"),
                "proxy_id": proxy_id,
                "proxy_region": proxy.get("region"),
                "proxy_type": proxy.get("type"),
            }
        )

    conflicts: list[dict[str, Any]] = []
    for ip, accounts in grouped.items():
        if len(accounts) > 1:
            conflicts.append(
                {
                    "ip": ip,
                    "account_count": len(accounts),
                    "accounts": accounts,
                }
            )
    return conflicts

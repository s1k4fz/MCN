import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = BASE_DIR / "runtime"
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

ACCOUNT_STORE_PATH = RUNTIME_DIR / "accounts.json"
ALLOWED_ACCOUNT_STATUS = {"active", "abnormal", "unverified"}


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
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    temp_path.replace(path)


def _clean_text(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _normalize_status(value: str | None) -> str:
    status = str(value or "unverified").strip().lower()
    # 兼容旧数据：suspended → abnormal, disabled → abnormal
    if status == "suspended":
        status = "abnormal"
    elif status == "disabled":
        status = "abnormal"
    if status not in ALLOWED_ACCOUNT_STATUS:
        raise ValueError(f"不支持的账号状态: {status}")
    return status


def _normalize_platform(value: str | None) -> str:
    platform = str(value or "twitter").strip().lower()
    return platform or "twitter"


def _normalize_key(raw_key: str) -> str:
    key = str(raw_key or "").strip().lower()
    key = re.sub(r"[\s_\-]+", "", key)
    return key


def canonical_field_name(raw_key: str) -> str:
    """
    将用户自定义字段名映射为标准字段，便于自由导入格式。
    """
    normalized = _normalize_key(raw_key)

    account_aliases = {"账号", "账户", "用户名", "user", "username", "account", "handle", "账号名"}
    password_aliases = {"密码", "pass", "pwd", "password"}
    twofa_aliases = {"2fa", "twofa", "totp", "otp", "googleauth", "验证器", "二步验证", "双重验证"}
    token_aliases = {"token", "authtoken", "auth", "session", "会话"}
    cookies_aliases = {"cookie", "cookies", "完整cookie", "浏览器cookie", "fullcookie"}
    email_aliases = {"email", "mail", "邮箱"}
    email_password_aliases = {"mailpass", "mailpassword", "邮箱密码", "emailpassword", "emailpass"}

    if normalized in {_normalize_key(item) for item in account_aliases}:
        return "account"
    if normalized in {_normalize_key(item) for item in password_aliases}:
        return "password"
    if normalized in {_normalize_key(item) for item in twofa_aliases}:
        return "twofa"
    if normalized in {_normalize_key(item) for item in token_aliases}:
        return "token"
    if normalized in {_normalize_key(item) for item in cookies_aliases}:
        return "cookies"
    if normalized in {_normalize_key(item) for item in email_aliases}:
        return "email"
    if normalized in {_normalize_key(item) for item in email_password_aliases}:
        return "email_password"
    return normalized


def list_account_records(
    platform: str | None = None,
    pool: str | None = None,
) -> list[dict[str, Any]]:
    records = _read_list(ACCOUNT_STORE_PATH)
    if platform:
        normalized_platform = _normalize_platform(platform)
        records = [
            item
            for item in records
            if str(item.get("platform", "")).strip().lower() == normalized_platform
        ]
    if pool:
        normalized_pool = pool.strip().lower()
        records = [
            item
            for item in records
            if str(item.get("pool", "")).strip().lower() == normalized_pool
        ]
    return records


def get_account_record(account_id: str) -> dict[str, Any] | None:
    target_id = str(account_id).strip()
    if not target_id:
        return None
    for item in _read_list(ACCOUNT_STORE_PATH):
        if str(item.get("id")) == target_id:
            return item
    return None


def create_account_record(
    *,
    platform: str,
    account: str,
    password: str | None = None,
    twofa: str | None = None,
    token: str | None = None,
    cookies: str | None = None,
    email: str | None = None,
    email_password: str | None = None,
    status: str = "unverified",
    pool: str | None = None,
    extra_fields: dict[str, str] | None = None,
    raw_line: str | None = None,
) -> dict[str, Any]:
    normalized_platform = _normalize_platform(platform)
    normalized_account = _clean_text(account)
    if not normalized_account:
        raise ValueError("account 不能为空")

    normalized_status = _normalize_status(status)
    normalized_password = _clean_text(password)
    normalized_twofa = _clean_text(twofa)
    normalized_token = _clean_text(token)
    normalized_cookies = _clean_text(cookies)
    normalized_email = _clean_text(email)
    normalized_email_password = _clean_text(email_password)
    normalized_pool = (pool or "").strip().lower() or None

    records = _read_list(ACCOUNT_STORE_PATH)
    for item in records:
        if (
            str(item.get("platform", "")).strip().lower() == normalized_platform
            and str(item.get("account", "")).strip().lower() == normalized_account.lower()
            and str(item.get("pool", "")).strip().lower() == (normalized_pool or "")
        ):
            raise ValueError("账号已存在（platform + account + pool 重复）")

    now = now_iso()
    record = {
        "id": uuid.uuid4().hex,
        "platform": normalized_platform,
        "account": normalized_account,
        "password": normalized_password,
        "twofa": normalized_twofa,
        "token": normalized_token,
        "cookies": normalized_cookies,
        "email": normalized_email,
        "email_password": normalized_email_password,
        "status": normalized_status,
        "pool": normalized_pool,
        "extra_fields": extra_fields or {},
        "raw_line": _clean_text(raw_line),
        "created_at": now,
        "updated_at": now,
    }
    records.append(record)
    _write_list_atomic(ACCOUNT_STORE_PATH, records)
    return record


def delete_account_record(account_id: str) -> bool:
    target_id = str(account_id).strip()
    if not target_id:
        return False

    records = _read_list(ACCOUNT_STORE_PATH)
    filtered = [item for item in records if str(item.get("id")) != target_id]
    deleted = len(filtered) != len(records)
    if deleted:
        _write_list_atomic(ACCOUNT_STORE_PATH, filtered)
    return deleted


def update_account_record(account_id: str, **fields: Any) -> dict[str, Any] | None:
    target_id = str(account_id).strip()
    if not target_id:
        return None

    records = _read_list(ACCOUNT_STORE_PATH)
    target_index = -1
    for index, item in enumerate(records):
        if str(item.get("id")) == target_id:
            target_index = index
            break
    if target_index < 0:
        return None

    target = dict(records[target_index])

    if "status" in fields:
        target["status"] = _normalize_status(fields.get("status"))
    if "password" in fields:
        target["password"] = _clean_text(fields.get("password"))
    if "twofa" in fields:
        target["twofa"] = _clean_text(fields.get("twofa"))
    if "token" in fields:
        target["token"] = _clean_text(fields.get("token"))
    if "cookies" in fields:
        target["cookies"] = _clean_text(fields.get("cookies"))
    if "email" in fields:
        target["email"] = _clean_text(fields.get("email"))
    if "email_password" in fields:
        target["email_password"] = _clean_text(fields.get("email_password"))

    if "verify_status" in fields:
        target["verify_status"] = _clean_text(fields.get("verify_status"))
    if "verify_message" in fields:
        target["verify_message"] = _clean_text(fields.get("verify_message"))
    if "verify_checked_at" in fields:
        target["verify_checked_at"] = _clean_text(fields.get("verify_checked_at"))
    if "verify_http_status" in fields:
        target["verify_http_status"] = fields.get("verify_http_status")
    if "verify_latency_ms" in fields:
        target["verify_latency_ms"] = fields.get("verify_latency_ms")

    target["updated_at"] = now_iso()
    records[target_index] = target
    _write_list_atomic(ACCOUNT_STORE_PATH, records)
    return target


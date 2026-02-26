import csv
import json
import logging
import os
import re
import signal
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# Windows 控制台默认 GBK，遇到 emoji 会崩；强制 UTF-8
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.INFO)

import requests
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from account_store import (
    canonical_field_name,
    create_account_record,
    delete_account_record,
    get_account_record,
    list_account_records,
    update_account_record,
)
from bilibili_crawler import BilibiliCrawler
from checkerproxy_health import run_checkerproxy_health_check
from longmao_parser import normalize_platform_type, parse_content_data
from main import (
    read_author_meta,
)
from proxy_store import (
    create_proxy_record,
    delete_proxy_record,
    detect_ip_reuse_conflicts,
    get_proxy_record,
    list_account_bindings,
    list_proxy_records,
    parse_proxy_input,
    remove_account_binding,
    update_proxy_record,
    upsert_account_binding,
)
from monitoring_store import (
    add_monitored_account,
    get_account_snapshots,
    get_latest_snapshot,
    get_monitored_account,
    get_tweet_metrics,
    get_tweet_metrics_by_source,
    list_monitored_accounts,
    remove_monitored_account,
    save_account_snapshot,
    save_tweet_metrics,
    update_monitored_account,
)
from task_store import (
    append_task_log,
    create_task_record,
    delete_task_record,
    list_task_records,
    read_task_record,
    update_task_record,
)
from twitter_account_verifier import (
    TwitterAccountVerifierSession,
    map_verification_to_account_status,
    parse_auth_token,
)

import asyncio as _asyncio

import publish_scheduler
import publish_store
import publish_task_store
from twitter_publisher import publish_single_tweet

BASE_DIR = Path(__file__).resolve().parent
MATERIALS_ROOT = BASE_DIR / "materials"
TASK_WORKER_SCRIPT = BASE_DIR / "task_worker.py"
TASK_WORKER_LOG_DIR = BASE_DIR / "runtime" / "worker-logs"
TASK_WORKER_LOG_DIR.mkdir(parents=True, exist_ok=True)

USER_UPLOAD_PLATFORM_KEY = "user-upload"
USER_UPLOAD_PLATFORM_NAME = "用户上传"

PLATFORM_DIRS = {
    "bilibili": "哔哩哔哩",
    "xiaohongshu": "小红书",
    "douyin": "抖音",
    USER_UPLOAD_PLATFORM_KEY: USER_UPLOAD_PLATFORM_NAME,
}
DEFAULT_SECOND_LEVEL_DIRS = ("单个作品", "指定作者")
UNDOWNLOADED_AUTHOR_DIR = "已采集未下载作者"
EXTRA_AUTHOR_SECOND_LEVEL_DIRS = (UNDOWNLOADED_AUTHOR_DIR,)
PLATFORMS_WITH_AUTHOR_TREE = {"bilibili", "douyin", "xiaohongshu"}
AUTHOR_TREE_DIRS = {"指定作者", UNDOWNLOADED_AUTHOR_DIR}
# 向后兼容旧引用
BILIBILI_UNDOWNLOADED_AUTHOR_DIR = UNDOWNLOADED_AUTHOR_DIR
BILIBILI_EXTRA_SECOND_LEVEL_DIRS = EXTRA_AUTHOR_SECOND_LEVEL_DIRS
BILIBILI_AUTHOR_TREE_DIRS = AUTHOR_TREE_DIRS
INTERNAL_MATERIAL_FILE_NAMES = {".ds_store", "_author_meta.json"}
_BILIBILI_CRAWLER: BilibiliCrawler | None = None
DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class SingleWorkCollectRequest(BaseModel):
    links: list[str] = Field(..., min_length=1)
    title: str | None = None
    description: str | None = None


class AuthorCollectRequest(BaseModel):
    platform: str = "bilibili"
    collect_action: str = "data-only"  # data-only | collect-download
    uids: list[str] = Field(..., min_length=1)
    title: str | None = None
    description: str | None = None


class AuthorSelectiveDownloadRequest(BaseModel):
    platform: str = "bilibili"
    author_uid: str
    selected_video_folders: list[str] = Field(..., min_length=1)


class MaterialsDeleteRequest(BaseModel):
    paths: list[str] = Field(..., min_length=1)


class UserUploadFolderCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    parent_path: str | None = None


class ProxyCreateRequest(BaseModel):
    ip: str | None = None
    port: int | None = None
    username: str | None = None
    password: str | None = None
    protocol: str = "http"  # http | https | socks5
    region: str | None = None
    type: str = "publish"  # publish | monitor
    raw: str | None = None


class ProxyBatchCreateRequest(BaseModel):
    items: list[str] = Field(..., min_length=1)
    protocol: str = "http"  # http | https | socks5
    region: str | None = None
    type: str = "publish"  # publish | monitor


class ProxyTestRequest(BaseModel):
    timeout: int = 15
    check_type: str = "soft"
    services: list[str] | None = None


class AccountCreateRequest(BaseModel):
    platform: str = "twitter"
    account: str
    password: str | None = None
    twofa: str | None = None
    token: str | None = None
    cookies: str | None = None
    email: str | None = None
    email_password: str | None = None
    status: str = "unverified"
    pool: str | None = None


class AccountBatchCreateRequest(BaseModel):
    platform: str = "twitter"
    raw_text: str = Field(..., min_length=1)
    delimiter: str = "----"
    field_order: list[str] = Field(..., min_length=1)
    status: str = "unverified"
    pool: str | None = None


class AccountVerifyRequest(BaseModel):
    account_ids: list[str] = Field(..., min_length=1)


# ---------- 账号-代理绑定 请求模型 ----------

class BindingUpsertRequest(BaseModel):
    """绑定/更新 账号与代理的一对一关系"""
    account_id: str = Field(..., min_length=1)
    proxy_id: str = Field(..., min_length=1)


class BindingRemoveRequest(BaseModel):
    """解除绑定"""
    account_id: str = Field(..., min_length=1)


app = FastAPI(title="MCN Backend API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _startup_publish_scheduler():
    _asyncio.create_task(publish_scheduler.run_scheduler_loop())


def ensure_material_tree() -> None:
    for platform_key, platform_name in PLATFORM_DIRS.items():
        root_dir = MATERIALS_ROOT / platform_name
        root_dir.mkdir(parents=True, exist_ok=True)
        for second in get_second_level_dirs(platform_key):
            (root_dir / second).mkdir(parents=True, exist_ok=True)


def get_second_level_dirs(platform_key: str) -> tuple[str, ...]:
    if platform_key == USER_UPLOAD_PLATFORM_KEY:
        return ()
    if platform_key in PLATFORMS_WITH_AUTHOR_TREE:
        return (*DEFAULT_SECOND_LEVEL_DIRS, *EXTRA_AUTHOR_SECOND_LEVEL_DIRS)
    return DEFAULT_SECOND_LEVEL_DIRS


def is_bilibili_author_tree(platform_key: str, second_dir_name: str) -> bool:
    return platform_key in PLATFORMS_WITH_AUTHOR_TREE and second_dir_name in AUTHOR_TREE_DIRS


def infer_author_name_from_video_csv(author_dir: Path) -> str | None:
    """
    兼容旧目录：从作者目录下任意作品的 video_data.csv 反推出作者名。
    """
    try:
        csv_candidates = sorted(
            list(author_dir.glob("*/video_data.csv")) + list(author_dir.glob("*.csv")),
            key=lambda item: item.name.lower(),
        )
        for csv_path in csv_candidates:
            with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    author_name = str(row.get("author_name") or "").strip()
                    if author_name:
                        return author_name
                    break
    except Exception:
        return None
    return None


def to_base_relative_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(BASE_DIR))
    except Exception:
        return str(path)


def build_entry_nodes(parent_dir: Path, id_prefix: str, depth: int) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    entries = sorted(
        [
            entry
            for entry in parent_dir.iterdir()
            if entry.name
            and entry.name.lower() not in INTERNAL_MATERIAL_FILE_NAMES
            and not entry.name.startswith(".")
        ],
        key=lambda entry: entry.name.lower(),
    )
    for entry in entries:
        node_id = f"{id_prefix}-{entry.name}"
        node: dict[str, Any] = {
            "id": node_id,
            "name": entry.name,
            "children": [],
            "relative_path": to_base_relative_path(entry),
            "is_dir": entry.is_dir(),
        }
        if depth > 0 and entry.is_dir():
            node["children"] = build_entry_nodes(entry, node_id, depth - 1)
        nodes.append(node)
    return nodes


def normalize_material_delete_path(path: str) -> str:
    normalized = str(path or "").strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized.lstrip("/")
    return normalized


def resolve_material_delete_target(relative_path: str) -> Path | None:
    normalized = normalize_material_delete_path(relative_path)
    if not normalized:
        return None
    try:
        target = (BASE_DIR / normalized).resolve()
        target.relative_to(MATERIALS_ROOT.resolve())
        return target
    except Exception:
        return None


def validate_material_delete_target(target: Path) -> tuple[bool, str]:
    if not target.exists():
        return False, "目标不存在"

    try:
        relative_to_materials = target.resolve().relative_to(MATERIALS_ROOT.resolve())
    except Exception:
        return False, "目标不在素材目录内"

    parts = list(relative_to_materials.parts)
    depth = len(parts)
    platform_name = parts[0] if len(parts) > 0 else ""
    second_name = parts[1] if len(parts) > 1 else ""

    if target.name.lower() in INTERNAL_MATERIAL_FILE_NAMES:
        return False, "系统内部文件不允许删除"

    # materials/<用户上传>/<二级目录> 为用户创建目录，允许删除。
    if depth == 2 and target.is_dir() and platform_name == USER_UPLOAD_PLATFORM_NAME:
        return True, ""

    # "用户上传"下任意深度的文件夹和文件均允许删除（depth >= 2）。
    if platform_name == USER_UPLOAD_PLATFORM_NAME and depth >= 2:
        return True, ""

    # materials/<一级目录>/<二级目录> 为系统默认目录，禁止删除。
    if depth <= 2:
        return False, "禁止删除系统默认目录（一级目录和二级目录）"

    # 允许删除三级目录（包括“作者目录”与“特定作品目录”）。
    if depth == 3 and target.is_dir():
        return True, ""

    # 允许删除普通三级目录下文件。
    if depth == 4 and target.is_file():
        return True, ""

    # 允许删除“用户上传”二级目录下文件（第3层文件）。
    if depth == 3 and target.is_file() and platform_name == USER_UPLOAD_PLATFORM_NAME:
        return True, ""

    # 允许删除作者目录下的作品目录（第4层目录）。
    if (
        depth == 4
        and target.is_dir()
        and platform_name in {v for k, v in PLATFORM_DIRS.items() if k in PLATFORMS_WITH_AUTHOR_TREE}
        and second_name in AUTHOR_TREE_DIRS
    ):
        return True, ""

    # 允许删除作者作品目录下文件（第5层文件）。
    if (
        depth == 5
        and target.is_file()
        and platform_name in {v for k, v in PLATFORM_DIRS.items() if k in PLATFORMS_WITH_AUTHOR_TREE}
        and second_name in AUTHOR_TREE_DIRS
    ):
        return True, ""

    return False, "仅允许删除作者目录、作品目录及作品目录内文件"


def detect_platform(url: str) -> str:
    normalized = url.lower()
    if "bilibili.com" in normalized or "b23.tv" in normalized:
        return "bilibili"
    if "douyin.com" in normalized or "iesdouyin.com" in normalized:
        return "douyin"
    if (
        "xiaohongshu.com" in normalized
        or "xhslink.com" in normalized
        or "xiao-hong-shu.com" in normalized
    ):
        return "xiaohongshu"
    return "bilibili"


def sanitize_folder_name(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]', "_", name).strip().strip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        cleaned = "未命名作品"
    return cleaned[:80]


def sanitize_file_name(name: str) -> str:
    basename = Path(str(name or "").strip()).name
    cleaned = re.sub(r'[\\/:*?"<>|]', "_", basename).strip().strip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        cleaned = f"upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    return cleaned[:120]


def make_unique_dir(base_dir: Path, folder_name: str) -> Path:
    candidate = base_dir / folder_name
    if not candidate.exists():
        return candidate
    index = 2
    while True:
        next_candidate = base_dir / f"{folder_name}_{index}"
        if not next_candidate.exists():
            return next_candidate
        index += 1


def make_unique_file_path(base_dir: Path, file_name: str) -> Path:
    candidate = base_dir / file_name
    if not candidate.exists():
        return candidate

    stem = Path(file_name).stem or "upload"
    suffix = Path(file_name).suffix
    index = 2
    while True:
        next_candidate = base_dir / f"{stem}_{index}{suffix}"
        if not next_candidate.exists():
            return next_candidate
        index += 1


def guess_extension(url: str, fallback: str) -> str:
    try:
        path = urlparse(url).path
        suffix = Path(path).suffix.lower()
        if suffix and len(suffix) <= 8:
            return suffix
    except Exception:
        pass
    return fallback


def build_download_headers(url: str) -> dict[str, str]:
    headers: dict[str, str] = {"User-Agent": DEFAULT_UA}
    lower = url.lower()
    if "bilivideo.com" in lower or "bilibili.com" in lower:
        headers["Referer"] = "https://www.bilibili.com/"
    elif "douyin" in lower:
        headers["Referer"] = "https://www.douyin.com/"
    elif "xiaohongshu" in lower or "xhscdn.com" in lower:
        headers["Referer"] = "https://www.xiaohongshu.com/"
    return headers


def launch_task_worker(task_id: str) -> int:
    if not TASK_WORKER_SCRIPT.exists():
        raise RuntimeError(f"任务 worker 脚本不存在: {TASK_WORKER_SCRIPT}")

    stdout_path = TASK_WORKER_LOG_DIR / f"{task_id}.log"
    log_file = open(stdout_path, "a", encoding="utf-8")
    try:
        worker_env = dict(os.environ)
        worker_env["PYTHONUNBUFFERED"] = "1"
        process = subprocess.Popen(
            [sys.executable, "-u", str(TASK_WORKER_SCRIPT), task_id],
            cwd=str(BASE_DIR),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=worker_env,
            start_new_session=True,
            close_fds=True,
        )
    finally:
        log_file.close()
    return int(process.pid)


def read_worker_log_lines(task_id: str) -> list[str]:
    log_path = TASK_WORKER_LOG_DIR / f"{task_id}.log"
    if not log_path.exists():
        return []
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            lines = [line.rstrip("\r\n") for line in f.readlines()]
            return [line for line in lines if line.strip()]
    except Exception:
        return []


def build_task_full_logs(task: dict[str, Any]) -> list[str]:
    task_id = str(task.get("id") or "").strip()
    task_logs = task.get("logs") if isinstance(task.get("logs"), list) else []
    normalized_task_logs = [str(item) for item in task_logs if str(item).strip()]
    worker_logs = read_worker_log_lines(task_id) if task_id else []
    # 不做去重，确保任何日志都不丢失。
    return [*normalized_task_logs, *worker_logs]


def download_to_file(url: str, output_path: Path, purpose: str = "unknown") -> dict[str, Any]:
    headers = build_download_headers(url)
    print(f"   ⬇️ 下载[{purpose}] -> {output_path.name}")
    try:
        with requests.get(url, timeout=45, stream=True, headers=headers) as response:
            status_code = response.status_code
            response.raise_for_status()
            bytes_written = 0
            with open(output_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        bytes_written += len(chunk)
        print(
            f"   ✅ 下载成功[{purpose}] status={status_code} bytes={bytes_written} file={output_path.name}"
        )
        return {
            "ok": True,
            "path": str(output_path),
            "status_code": status_code,
            "bytes_written": bytes_written,
        }
    except Exception as e:
        status_code = None
        response_text_preview = None
        if isinstance(e, requests.HTTPError) and e.response is not None:
            status_code = e.response.status_code
            try:
                response_text_preview = e.response.text[:300]
            except Exception:
                response_text_preview = None
        print(
            f"   ❌ 下载失败[{purpose}] status={status_code} file={output_path.name} error={e}"
        )
        if response_text_preview:
            print(f"      - response_preview: {response_text_preview}")
        return {
            "ok": False,
            "error": str(e),
            "status_code": status_code,
            "response_preview": response_text_preview,
            "path": str(output_path),
        }


def merge_dash_streams_to_mp4(
    video_path: Path, audio_path: Path, output_path: Path
) -> dict[str, Any]:
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        return {"ok": False, "error": "未检测到 ffmpeg，无法合并 m4s 为 mp4"}

    command = [
        ffmpeg_path,
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(audio_path),
        "-c:v",
        "copy",
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    print(
        f"   🎬 合并 DASH 流: video={video_path.name} + audio={audio_path.name} -> {output_path.name}"
    )
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    except Exception as e:
        return {"ok": False, "error": f"ffmpeg 执行异常: {e}"}

    if result.returncode != 0:
        stderr_preview = (result.stderr or "")[-800:]
        return {
            "ok": False,
            "error": "ffmpeg 合并失败",
            "returncode": result.returncode,
            "stderr_preview": stderr_preview,
        }

    if not output_path.exists():
        return {"ok": False, "error": "ffmpeg 返回成功但未生成 mp4 文件"}

    print(f"   ✅ 合并成功: {output_path.name}")
    return {
        "ok": True,
        "path": str(output_path),
        "size_bytes": output_path.stat().st_size,
    }


def get_bilibili_crawler() -> BilibiliCrawler:
    global _BILIBILI_CRAWLER
    if _BILIBILI_CRAWLER is None:
        _BILIBILI_CRAWLER = BilibiliCrawler()
    return _BILIBILI_CRAWLER


def save_single_row_csv(row: dict[str, Any], output_path: Path) -> None:
    headers = list(row.keys())
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerow(row)


def collect_bilibili_detail_csv(source_url: str, output_dir: Path) -> dict[str, Any]:
    """
    针对单条 B 站视频，补充抓取详细数据并落盘 CSV。
    失败时返回错误信息，不抛异常，以免影响原有采集链路。
    """
    try:
        crawler = get_bilibili_crawler()
        detail = crawler.get_single_video_detail_by_url(source_url)
        if not detail:
            return {"ok": False, "error": "B站视频详细数据获取失败"}

        csv_name = "bilibili_video_detail.csv"
        save_single_row_csv(detail, output_dir / csv_name)
        return {"ok": True, "csv_file": csv_name}
    except Exception as e:
        return {"ok": False, "error": f"B站详情CSV生成异常: {e}"}


def collect_single_work(url: str, task_title: str | None, task_desc: str | None) -> dict[str, Any]:
    parsed = parse_content_data(url)
    if not parsed.get("ok"):
        return {
            "url": url,
            "success": False,
            "error": parsed.get("error", "解析失败"),
        }

    extracted = parsed["extracted"]
    parsed_platform_type = normalize_platform_type(parsed.get("platform_type"))
    platform_key = parsed_platform_type if parsed_platform_type in PLATFORM_DIRS else detect_platform(url)
    platform_dir_name = PLATFORM_DIRS.get(platform_key, "哔哩哔哩")
    single_work_dir = MATERIALS_ROOT / platform_dir_name / "单个作品"

    title = sanitize_folder_name(extracted.get("title") or "未命名作品")
    work_dir = make_unique_dir(single_work_dir, title)
    work_dir.mkdir(parents=True, exist_ok=True)

    downloaded_files: dict[str, Any] = {
        "cover": None,
        "videos": [],
        "images": [],
        "audio": None,
    }
    downloaded_video_paths: list[Path] = []
    downloaded_audio_path: Path | None = None
    bilibili_media_plan: dict[str, Any] | None = None
    bilibili_detail_csv: str | None = None
    bilibili_detail_warning: str | None = None

    if platform_key == "bilibili":
        crawler = get_bilibili_crawler()
        best_media = crawler.get_best_media_urls_by_url(url)
        if best_media.get("ok") and best_media.get("video_url"):
            best_video_url = str(best_media.get("video_url"))
            best_audio_url = best_media.get("audio_url")
            extracted["videos"] = [best_video_url]
            if isinstance(best_audio_url, str) and best_audio_url.strip():
                extracted["audio"] = best_audio_url.strip()

            bilibili_media_plan = {
                "strategy": "highest-quality",
                "source": best_media.get("source"),
                "quality_id": best_media.get("quality_id"),
                "quality_label": best_media.get("quality_label"),
                "width": best_media.get("width"),
                "height": best_media.get("height"),
                "accept_quality": best_media.get("accept_quality"),
                "accept_description": best_media.get("accept_description"),
                "quality_warning": best_media.get("quality_warning"),
                "is_logged_in": best_media.get("is_logged_in"),
                "login_user": best_media.get("login_user"),
            }
            print(
                "🎯 [B站单作品] 使用最高画质下载:"
                f" qn={best_media.get('quality_id')}"
                f" label={best_media.get('quality_label') or '-'}"
                f" resolution={best_media.get('width')}x{best_media.get('height')}"
                f" source={best_media.get('source')}"
            )
            if best_media.get("quality_warning"):
                print(f"⚠️ [B站单作品] 清晰度提示: {best_media.get('quality_warning')}")
        else:
            print("⚠️ [B站单作品] 最高画质解析失败，回退到解析器直链")
            if isinstance(getattr(crawler, "last_error", None), dict):
                print(f"   - crawler_error: {crawler.last_error}")

    cover_url = extracted.get("cover")
    if cover_url:
        cover_ext = guess_extension(cover_url, ".jpg")
        cover_result = download_to_file(
            cover_url, work_dir / f"cover{cover_ext}", purpose="cover"
        )
        if cover_result["ok"]:
            downloaded_files["cover"] = Path(cover_result["path"]).name

    for index, video_url in enumerate(extracted.get("videos", []), start=1):
        video_ext = guess_extension(video_url, ".mp4")
        video_result = download_to_file(
            video_url, work_dir / f"video_{index}{video_ext}", purpose=f"video_{index}"
        )
        if video_result["ok"]:
            video_path = Path(video_result["path"])
            downloaded_video_paths.append(video_path)
            downloaded_files["videos"].append(video_path.name)

    for index, image_url in enumerate(extracted.get("images", []), start=1):
        image_ext = guess_extension(image_url, ".jpg")
        image_result = download_to_file(
            image_url, work_dir / f"image_{index}{image_ext}", purpose=f"image_{index}"
        )
        if image_result["ok"]:
            downloaded_files["images"].append(Path(image_result["path"]).name)

    audio_url = extracted.get("audio")
    if audio_url:
        audio_ext = guess_extension(audio_url, ".mp3")
        audio_result = download_to_file(
            audio_url, work_dir / f"audio{audio_ext}", purpose="audio"
        )
        if audio_result["ok"]:
            downloaded_audio_path = Path(audio_result["path"])
            downloaded_files["audio"] = downloaded_audio_path.name

    # B站高画质通常是 DASH 分离流（m4s），自动封装为 mp4 便于直接使用。
    if (
        platform_key == "bilibili"
        and downloaded_video_paths
        and downloaded_audio_path is not None
    ):
        first_video_path = downloaded_video_paths[0]
        if (
            first_video_path.suffix.lower() == ".m4s"
            and downloaded_audio_path.suffix.lower() == ".m4s"
        ):
            merged_path = work_dir / "video_1.mp4"
            merge_result = merge_dash_streams_to_mp4(
                first_video_path, downloaded_audio_path, merged_path
            )
            if merge_result.get("ok"):
                downloaded_files["videos"][0] = merged_path.name
                downloaded_files["merged_video"] = merged_path.name
            else:
                warning = (
                    f"DASH 合并失败: {merge_result.get('error')}; "
                    f"video={first_video_path.name}, audio={downloaded_audio_path.name}"
                )
                if merge_result.get("stderr_preview"):
                    warning += f"; stderr={merge_result.get('stderr_preview')}"
                print(f"⚠️ [B站单作品] {warning}")
                bilibili_detail_warning = (
                    (bilibili_detail_warning + " | ") if bilibili_detail_warning else ""
                ) + warning

    if platform_key == "bilibili":
        bilibili_result = collect_bilibili_detail_csv(url, work_dir)
        if bilibili_result.get("ok"):
            bilibili_detail_csv = str(bilibili_result.get("csv_file"))
            downloaded_files["bilibili_detail_csv"] = bilibili_detail_csv
        else:
            bilibili_detail_warning = str(
                bilibili_result.get("error") or "B站视频详细数据CSV生成失败"
            )

    metadata = {
        "task_title": task_title,
        "task_description": task_desc,
        "source_url": url,
        "platform": platform_key,
        "platform_display_name": platform_dir_name,
        "parser_platform_type": parsed.get("platform_type"),
        "parser_platform_type_raw": parsed.get("platform_type_raw"),
        "collected_at": datetime.now().isoformat(timespec="seconds"),
        "content": extracted,
        "raw_info": parsed.get("raw_info"),
        "downloaded_files": downloaded_files,
        "bilibili_detail_csv": bilibili_detail_csv,
        "bilibili_detail_warning": bilibili_detail_warning,
        "bilibili_media_plan": bilibili_media_plan,
    }
    with open(work_dir / "data.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    return {
        "url": url,
        "success": True,
        "platform": platform_key,
        "platform_display_name": platform_dir_name,
        "folder_name": work_dir.name,
        "folder_path": str(work_dir.relative_to(BASE_DIR)),
        "title": extracted.get("title"),
        "bilibili_detail_csv": bilibili_detail_csv,
        "warning": bilibili_detail_warning,
    }


def mask_secret(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    if len(normalized) <= 2:
        return "*" * len(normalized)
    return f"{normalized[0]}{'*' * (len(normalized) - 2)}{normalized[-1]}"


def serialize_proxy_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": record.get("id"),
        "ip": record.get("ip"),
        "port": record.get("port"),
        "protocol": record.get("protocol"),
        "username": record.get("username"),
        "password_masked": mask_secret(record.get("password")),
        "region": record.get("region"),
        "type": record.get("type"),
        "status": record.get("status"),
        "last_checked_at": record.get("last_checked_at"),
        "last_latency_ms": record.get("last_latency_ms"),
        "last_error": record.get("last_error"),
        "last_check_result": record.get("last_check_result"),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
    }


def serialize_account_record(record: dict[str, Any]) -> dict[str, Any]:
    raw_status = record.get("status")
    # 兼容旧数据：suspended/disabled 映射为 abnormal
    status = str(raw_status or "unverified").strip().lower()
    if status in ("suspended", "disabled"):
        status = "abnormal"

    return {
        "id": record.get("id"),
        "platform": record.get("platform"),
        "account": record.get("account"),
        "password_masked": mask_secret(record.get("password")),
        "twofa_masked": mask_secret(record.get("twofa")),
        "token_masked": mask_secret(record.get("token")),
        "cookies_masked": mask_secret(record.get("cookies")),
        "email": record.get("email"),
        "email_password_masked": mask_secret(record.get("email_password")),
        "status": status,
        "verify_status": record.get("verify_status"),
        "verify_message": record.get("verify_message"),
        "verify_checked_at": record.get("verify_checked_at"),
        "verify_http_status": record.get("verify_http_status"),
        "verify_latency_ms": record.get("verify_latency_ms"),
        "pool": record.get("pool"),
        "extra_fields": record.get("extra_fields") or {},
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
    }


def normalize_delimiter(value: str | None) -> str:
    delimiter = str(value or "").strip()
    if delimiter == r"\t":
        return "\t"
    return delimiter


def parse_account_line(
    *, line: str, delimiter: str, field_order: list[str]
) -> tuple[dict[str, str], dict[str, str]]:
    if not delimiter:
        raise ValueError("分隔符不能为空")
    parts = [segment.strip() for segment in str(line).split(delimiter)]
    if len(parts) != len(field_order):
        raise ValueError(
            f"字段数量不匹配，期望 {len(field_order)} 列，实际 {len(parts)} 列"
        )

    original_fields: dict[str, str] = {}
    canonical_fields: dict[str, str] = {}
    for index, field_name in enumerate(field_order):
        raw_name = str(field_name or "").strip()
        if not raw_name:
            raise ValueError(f"字段模板第 {index + 1} 个名称为空")
        value = parts[index]
        original_fields[raw_name] = value

        canonical_name = canonical_field_name(raw_name)
        if canonical_name and canonical_name not in canonical_fields and value:
            canonical_fields[canonical_name] = value

    return original_fields, canonical_fields


@app.get("/api/proxies")
def get_proxies(type: str | None = None, status: str | None = None) -> dict[str, Any]:
    try:
        records = list_proxy_records(proxy_type=type, status=status)
    except ValueError as e:
        return {"success": False, "message": str(e), "proxies": [], "count": 0}

    # 新记录通常在列表尾部，这里倒序返回，前端可直接展示最近添加项。
    serialized = [serialize_proxy_record(item) for item in reversed(records)]
    return {"success": True, "proxies": serialized, "count": len(serialized)}


@app.post("/api/proxies")
def create_proxy(payload: ProxyCreateRequest) -> dict[str, Any]:
    try:
        if payload.raw and payload.raw.strip():
            parsed = parse_proxy_input(payload.raw.strip())
            record = create_proxy_record(
                ip=str(parsed.get("ip") or ""),
                port=int(parsed.get("port") or 0),
                protocol=(payload.protocol or parsed.get("protocol") or "http"),
                username=payload.username if payload.username is not None else parsed.get("username"),
                password=payload.password if payload.password is not None else parsed.get("password"),
                region=payload.region,
                proxy_type=payload.type,
            )
        else:
            if payload.ip is None or payload.port is None:
                return {"success": False, "message": "ip 和 port 不能为空"}
            record = create_proxy_record(
                ip=payload.ip,
                port=payload.port,
                protocol=payload.protocol,
                username=payload.username,
                password=payload.password,
                region=payload.region,
                proxy_type=payload.type,
            )
    except ValueError as e:
        return {"success": False, "message": str(e)}
    except Exception as e:
        return {"success": False, "message": f"创建代理失败: {e}"}

    return {
        "success": True,
        "message": "代理已添加",
        "proxy": serialize_proxy_record(record),
    }


@app.post("/api/proxies/batch")
def create_proxy_batch(payload: ProxyBatchCreateRequest) -> dict[str, Any]:
    normalized_items = [str(item).strip() for item in payload.items if str(item).strip()]
    if not normalized_items:
        return {
            "success": False,
            "message": "未提供有效代理输入",
            "success_count": 0,
            "failure_count": 0,
            "proxies": [],
            "failures": [],
        }

    created: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for raw in normalized_items:
        try:
            parsed = parse_proxy_input(raw)
            record = create_proxy_record(
                ip=str(parsed.get("ip") or ""),
                port=int(parsed.get("port") or 0),
                protocol=payload.protocol or str(parsed.get("protocol") or "http"),
                username=parsed.get("username"),
                password=parsed.get("password"),
                region=payload.region,
                proxy_type=payload.type,
            )
            created.append(record)
        except Exception as e:
            failures.append({"raw": raw, "reason": str(e)})

    success_count = len(created)
    failure_count = len(failures)
    message = "批量添加完成"
    if success_count == 0:
        message = "批量添加失败"
    elif failure_count > 0:
        message = "批量添加完成（部分失败）"

    return {
        "success": success_count > 0,
        "partial_success": success_count > 0 and failure_count > 0,
        "message": message,
        "success_count": success_count,
        "failure_count": failure_count,
        "proxies": [serialize_proxy_record(item) for item in created],
        "failures": failures,
    }


@app.delete("/api/proxies/{proxy_id}")
def delete_proxy(proxy_id: str) -> dict[str, Any]:
    deleted = delete_proxy_record(proxy_id)
    if not deleted:
        return {"success": False, "message": "代理不存在或删除失败"}
    return {"success": True, "message": "代理已删除"}


@app.post("/api/proxies/{proxy_id}/test")
def test_proxy(proxy_id: str, payload: ProxyTestRequest) -> dict[str, Any]:
    record = get_proxy_record(proxy_id)
    if record is None:
        return {"success": False, "message": "代理不存在"}

    timeout_seconds = max(5, min(int(payload.timeout or 15), 60))
    check_type = str(payload.check_type or "soft").strip() or "soft"
    services = payload.services

    try:
        checker_result = run_checkerproxy_health_check(
            proxy_record=record,
            timeout_seconds=timeout_seconds,
            services=services,
            check_type=check_type,
        )
        status = str(checker_result.get("status") or "dead").strip().lower()
        if status not in {"active", "slow", "dead"}:
            status = "dead"
        latency_ms = checker_result.get("latency_ms")
        message = str(checker_result.get("message") or "代理检测失败")
        success = bool(checker_result.get("success")) and status in {"active", "slow"}

        updated = update_proxy_record(
            proxy_id,
            status=status,
            last_checked_at=datetime.now().isoformat(timespec="seconds"),
            last_latency_ms=latency_ms,
            last_error=None if success else message,
            last_check_result=checker_result,
        )
        return {
            "success": success,
            "message": message,
            "proxy": serialize_proxy_record(updated or record),
            "result": checker_result,
        }
    except Exception as e:
        updated = update_proxy_record(
            proxy_id,
            status="dead",
            last_checked_at=datetime.now().isoformat(timespec="seconds"),
            last_latency_ms=None,
            last_error=str(e),
            last_check_result={
                "success": False,
                "status": "dead",
                "message": str(e),
            },
        )
        return {
            "success": False,
            "message": f"代理健康检测异常: {e}",
            "proxy": serialize_proxy_record(updated or record),
            "result": {
                "success": False,
                "status": "dead",
                "message": str(e),
            },
        }


@app.get("/api/accounts")
def get_accounts(platform: str = "twitter", pool: str | None = None) -> dict[str, Any]:
    records = list_account_records(platform=platform, pool=pool)
    serialized = [serialize_account_record(item) for item in reversed(records)]
    return {"success": True, "accounts": serialized, "count": len(serialized)}


@app.post("/api/accounts")
def create_account(payload: AccountCreateRequest) -> dict[str, Any]:
    try:
        record = create_account_record(
            platform=payload.platform,
            account=payload.account,
            password=payload.password,
            twofa=payload.twofa,
            token=payload.token,
            cookies=payload.cookies,
            email=payload.email,
            email_password=payload.email_password,
            status=payload.status,
            pool=payload.pool,
        )
    except ValueError as e:
        return {"success": False, "message": str(e)}
    except Exception as e:
        return {"success": False, "message": f"创建账号失败: {e}"}

    return {
        "success": True,
        "message": "账号已添加",
        "account": serialize_account_record(record),
    }


@app.post("/api/accounts/batch")
def create_account_batch(payload: AccountBatchCreateRequest) -> dict[str, Any]:
    delimiter = normalize_delimiter(payload.delimiter)
    if not delimiter:
        return {
            "success": False,
            "message": "分隔符不能为空",
            "success_count": 0,
            "failure_count": 0,
            "accounts": [],
            "failures": [],
        }

    field_order = [str(item).strip() for item in payload.field_order if str(item).strip()]
    if not field_order:
        return {
            "success": False,
            "message": "字段模板不能为空",
            "success_count": 0,
            "failure_count": 0,
            "accounts": [],
            "failures": [],
        }

    lines = [
        line.strip()
        for line in str(payload.raw_text or "").splitlines()
        if str(line).strip()
    ]
    if not lines:
        return {
            "success": False,
            "message": "未提供可导入账号行",
            "success_count": 0,
            "failure_count": 0,
            "accounts": [],
            "failures": [],
        }

    created: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for index, line in enumerate(lines, start=1):
        try:
            original_fields, canonical_fields = parse_account_line(
                line=line, delimiter=delimiter, field_order=field_order
            )
            account_value = str(
                canonical_fields.get("account")
                or (line.split(delimiter)[0].strip() if delimiter in line else "")
            ).strip()
            if not account_value:
                raise ValueError("无法识别账号字段，请在字段模板中包含 account/账号")

            record = create_account_record(
                platform=payload.platform,
                account=account_value,
                password=canonical_fields.get("password"),
                twofa=canonical_fields.get("twofa"),
                token=canonical_fields.get("token"),
                cookies=canonical_fields.get("cookies"),
                email=canonical_fields.get("email"),
                email_password=canonical_fields.get("email_password"),
                status=payload.status,
                pool=payload.pool,
                extra_fields=original_fields,
                raw_line=line,
            )
            created.append(record)
        except Exception as e:
            failures.append({"line_number": index, "line": line, "reason": str(e)})

    success_count = len(created)
    failure_count = len(failures)
    message = "批量导入完成"
    if success_count == 0:
        message = "批量导入失败"
    elif failure_count > 0:
        message = "批量导入完成（部分失败）"

    return {
        "success": success_count > 0,
        "partial_success": success_count > 0 and failure_count > 0,
        "message": message,
        "success_count": success_count,
        "failure_count": failure_count,
        "accounts": [serialize_account_record(item) for item in created],
        "failures": failures,
    }


@app.delete("/api/accounts/{account_id}")
def delete_account(account_id: str) -> dict[str, Any]:
    record = get_account_record(account_id)
    if record is None:
        return {"success": False, "message": "账号不存在"}

    deleted = delete_account_record(account_id)
    if not deleted:
        return {"success": False, "message": "账号删除失败"}

    try:
        remove_account_binding(
            platform=str(record.get("platform") or "twitter"),
            account_uid=account_id,
        )
    except Exception:
        pass

    return {"success": True, "message": "账号已删除"}


@app.post("/api/accounts/verify")
def verify_accounts(payload: AccountVerifyRequest) -> dict[str, Any]:
    def _mask_token_for_log(token: str | None) -> str:
        normalized = str(token or "").strip()
        if not normalized:
            return "(empty)"
        if len(normalized) <= 8:
            return f"{normalized[:2]}***{normalized[-1:]}"
        return f"{normalized[:4]}***{normalized[-4:]}"

    requested_ids = [str(item).strip() for item in payload.account_ids if str(item).strip()]
    unique_ids = list(dict.fromkeys(requested_ids))
    if not unique_ids:
        return {
            "success": False,
            "message": "未提供可验证账号",
            "results": [],
            "success_count": 0,
            "failure_count": 0,
            "missing_ids": [],
        }

    all_accounts = list_account_records(platform="twitter")
    account_by_id = {str(item.get("id")): item for item in all_accounts}
    missing_ids = [account_id for account_id in unique_ids if account_id not in account_by_id]
    target_accounts = [account_by_id[account_id] for account_id in unique_ids if account_id in account_by_id]

    if not target_accounts:
        return {
            "success": False,
            "message": "待验证账号不存在",
            "results": [],
            "success_count": 0,
            "failure_count": 0,
            "missing_ids": missing_ids,
        }

    verifiers: dict[str, TwitterAccountVerifierSession] = {}
    results: list[dict[str, Any]] = []
    failure_details: list[dict[str, Any]] = []
    success_count = 0
    failure_count = 0

    print(
        f"[verify_accounts] start total_requested={len(unique_ids)} "
        f"existing={len(target_accounts)} missing={len(missing_ids)}"
    )
    if missing_ids:
        print(f"[verify_accounts] missing_account_ids={missing_ids}")

    try:
        for account in target_accounts:
            account_id = str(account.get("id") or "")
            account_name = str(account.get("account") or "")
            previous_status = str(account.get("status") or "unverified")
            auth_token = parse_auth_token(str(account.get("token") or ""))
            print(
                f"[verify_accounts] checking account_id={account_id} "
                f"account=@{account_name} has_token={bool(auth_token)} "
                f"token_mask={_mask_token_for_log(auth_token)}"
            )

            if not auth_token:
                verify_result = {
                    "status": "token_missing",
                    "message": "账号缺少 auth_token，无法验证",
                    "http_status": None,
                    "latency_ms": None,
                    "debug": {
                        "hint": "请在账号 token 字段中填入 auth_token 或包含 auth_token=... 的 cookie 字符串"
                    },
                }
            else:
                verifier = verifiers.get(auth_token)
                if verifier is None:
                    verifier = TwitterAccountVerifierSession(auth_token=auth_token)
                    verifiers[auth_token] = verifier
                verify_result = verifier.verify_screen_name(account_name)

            verify_status = str(verify_result.get("status") or "unknown")
            mapped_status = map_verification_to_account_status(verify_status, previous_status)
            verify_message = str(verify_result.get("message") or "").strip() or None
            verify_http_status = verify_result.get("http_status")
            verify_latency_ms = verify_result.get("latency_ms")
            verify_debug = verify_result.get("debug")
            verify_checked_at = datetime.now().isoformat(timespec="seconds")

            updated_record = update_account_record(
                account_id,
                status=mapped_status,
                verify_status=verify_status,
                verify_message=verify_message,
                verify_checked_at=verify_checked_at,
                verify_http_status=verify_http_status,
                verify_latency_ms=verify_latency_ms,
            )

            is_definitive_status = (
                verify_status in {"active", "protected", "suspended", "locked", "not_found"}
                or verify_status.startswith("unavailable_")
            )
            if is_definitive_status:
                success_count += 1
            else:
                failure_count += 1
                failure_detail = {
                    "account_id": account_id,
                    "account": account_name,
                    "verify_status": verify_status,
                    "verify_message": verify_message,
                    "verify_http_status": verify_http_status,
                    "verify_latency_ms": verify_latency_ms,
                    "debug": verify_debug,
                }
                failure_details.append(failure_detail)
                print(
                    "[verify_accounts][failed] "
                    f"account_id={account_id} account=@{account_name} "
                    f"verify_status={verify_status} message={verify_message} "
                    f"http_status={verify_http_status} latency_ms={verify_latency_ms}"
                )
                if verify_debug:
                    try:
                        print(
                            "[verify_accounts][failed][debug] "
                            + json.dumps(verify_debug, ensure_ascii=False)
                        )
                    except Exception:
                        print(f"[verify_accounts][failed][debug] {verify_debug}")

            if is_definitive_status:
                print(
                    "[verify_accounts][ok] "
                    f"account_id={account_id} account=@{account_name} "
                    f"verify_status={verify_status} mapped_status={mapped_status} "
                    f"http_status={verify_http_status} latency_ms={verify_latency_ms}"
                )

            results.append(
                {
                    "account_id": account_id,
                    "account": account_name,
                    "status_before": previous_status,
                    "status_after": mapped_status,
                    "verify_status": verify_status,
                    "verify_message": verify_message,
                    "verify_http_status": verify_http_status,
                    "verify_latency_ms": verify_latency_ms,
                    "verify_debug": verify_debug,
                    "checked_at": verify_checked_at,
                    "record": serialize_account_record(updated_record or account),
                }
            )
    finally:
        for verifier in verifiers.values():
            try:
                verifier.close()
            except Exception:
                pass

    message = "账号验证完成"
    if success_count == 0:
        message = "账号验证失败"
    elif failure_count > 0:
        message = "账号验证完成（部分失败）"

    print(
        f"[verify_accounts] done success_count={success_count} "
        f"failure_count={failure_count} partial_success={success_count > 0 and failure_count > 0}"
    )

    return {
        "success": success_count > 0,
        "partial_success": success_count > 0 and failure_count > 0,
        "message": message,
        "results": results,
        "failure_details": failure_details,
        "success_count": success_count,
        "failure_count": failure_count,
        "missing_ids": missing_ids,
    }


# =============================================
# 账号-代理 绑定管理 API
# =============================================

BIND_LOG = "[bindings]"


@app.get("/api/bindings")
def api_list_bindings():
    """查询所有账号-代理绑定关系，并附带账号名和代理地址方便前端展示"""
    print(f"{BIND_LOG} GET /api/bindings 查询所有绑定关系", flush=True)
    bindings = list_account_bindings()
    print(f"{BIND_LOG}   当前绑定数量: {len(bindings)}", flush=True)
    enriched = []
    for b in bindings:
        proxy = get_proxy_record(b.get("proxy_id", ""))
        proxy_label = None
        if proxy:
            proxy_label = f"{proxy['protocol']}://{proxy['ip']}:{proxy['port']}"
        enriched.append({
            **b,
            "proxy_label": proxy_label,
            "proxy_status": proxy.get("status") if proxy else None,
        })
    print(f"{BIND_LOG}   返回 {len(enriched)} 条绑定记录", flush=True)
    return {"success": True, "bindings": enriched}


@app.post("/api/bindings")
def api_upsert_binding(req: BindingUpsertRequest):
    """绑定账号到代理（一对一，重复调用会更新绑定）"""
    print(f"{BIND_LOG} POST /api/bindings account_id={req.account_id} proxy_id={req.proxy_id}", flush=True)

    # 1. 校验账号存在
    account = get_account_record(req.account_id)
    if account is None:
        print(f"{BIND_LOG}   ❌ 账号不存在: {req.account_id}", flush=True)
        return {"success": False, "message": f"账号不存在: {req.account_id}"}
    print(f"{BIND_LOG}   账号: {account.get('account')} (platform={account.get('platform')})", flush=True)

    # 2. 校验代理存在
    proxy = get_proxy_record(req.proxy_id)
    if proxy is None:
        print(f"{BIND_LOG}   ❌ 代理不存在: {req.proxy_id}", flush=True)
        return {"success": False, "message": f"代理不存在: {req.proxy_id}"}
    proxy_label = f"{proxy['protocol']}://{proxy['ip']}:{proxy['port']}"
    print(f"{BIND_LOG}   代理: {proxy_label} (type={proxy.get('type')}, status={proxy.get('status')})", flush=True)

    # 3. 校验代理必须是 publish 类型
    if proxy.get("type") != "publish":
        print(f"{BIND_LOG}   ❌ 代理类型不是 publish: {proxy.get('type')}", flush=True)
        return {
            "success": False,
            "message": f"只能绑定「发布用」代理，当前代理类型为: {proxy.get('type')}",
        }

    # 4. 执行绑定
    try:
        binding = upsert_account_binding(
            platform=account.get("platform", "twitter"),
            account_uid=req.account_id,
            account_name=account.get("account"),
            proxy_id=req.proxy_id,
        )
        print(f"{BIND_LOG}   ✅ 绑定成功: {account.get('account')} → {proxy_label}", flush=True)
    except ValueError as e:
        print(f"{BIND_LOG}   ❌ 绑定失败: {e}", flush=True)
        return {"success": False, "message": str(e)}
    except Exception as e:
        print(f"{BIND_LOG}   ❌ 绑定失败 (未知错误): {e}", flush=True)
        return {"success": False, "message": f"绑定失败: {e}"}

    return {
        "success": True,
        "message": f"已将 {account.get('account')} 绑定到 {proxy_label}",
        "binding": binding,
    }


@app.delete("/api/bindings/{account_id}")
def api_remove_binding(account_id: str):
    """解除账号的代理绑定"""
    print(f"{BIND_LOG} DELETE /api/bindings/{account_id}", flush=True)
    account = get_account_record(account_id)
    account_name = account.get("account", account_id) if account else account_id
    platform = account.get("platform", "twitter") if account else "twitter"

    removed = remove_account_binding(platform=platform, account_uid=account_id)
    if not removed:
        print(f"{BIND_LOG}   ⚠️ 账号 {account_name} 没有绑定任何代理", flush=True)
        return {"success": False, "message": f"账号 {account_name} 没有绑定任何代理"}

    print(f"{BIND_LOG}   ✅ 已解除 {account_name} 的代理绑定", flush=True)
    return {"success": True, "message": f"已解除 {account_name} 的代理绑定"}


@app.get("/api/bindings/conflicts")
def api_detect_binding_conflicts():
    """检测同一出口 IP 下是否绑定了多个账号（防关联告警）"""
    print(f"{BIND_LOG} GET /api/bindings/conflicts 检测IP复用冲突", flush=True)
    conflicts = detect_ip_reuse_conflicts()
    print(f"{BIND_LOG}   冲突数量: {len(conflicts)}", flush=True)
    if not conflicts:
        return {
            "success": True,
            "has_conflicts": False,
            "message": "未检测到 IP 复用冲突，所有账号 IP 隔离正常",
            "conflicts": [],
        }
    return {
        "success": True,
        "has_conflicts": True,
        "message": f"检测到 {len(conflicts)} 个 IP 存在多账号复用风险",
        "conflicts": conflicts,
    }


@app.post("/api/bindings/verify")
def api_verify_binding(req: BindingUpsertRequest):
    """验证账号与代理的绑定是否真正生效（手动指定 account_id + proxy_id）"""
    from binding_verifier import verify_binding as do_verify

    print(f"{BIND_LOG} POST /api/bindings/verify account_id={req.account_id} proxy_id={req.proxy_id}", flush=True)

    account = get_account_record(req.account_id)
    if account is None:
        print(f"{BIND_LOG}   ❌ 账号不存在: {req.account_id}", flush=True)
        return {"success": False, "message": f"账号不存在: {req.account_id}"}

    proxy = get_proxy_record(req.proxy_id)
    if proxy is None:
        print(f"{BIND_LOG}   ❌ 代理不存在: {req.proxy_id}", flush=True)
        return {"success": False, "message": f"代理不存在: {req.proxy_id}"}

    print(f"{BIND_LOG}   开始验证: {account.get('account')} ↔ {proxy.get('ip')}:{proxy.get('port')}", flush=True)
    result = do_verify(account=account, proxy=proxy)
    print(f"{BIND_LOG}   验证结果: success={result['success']} summary={result['summary']}", flush=True)

    return {"success": True, "verification": result}


@app.post("/api/bindings/verify-by-account/{account_id}")
def api_verify_binding_by_account(account_id: str):
    """根据账号 ID 验证其已绑定的代理是否生效"""
    from binding_verifier import verify_binding as do_verify

    print(f"{BIND_LOG} POST /api/bindings/verify-by-account/{account_id}", flush=True)

    account = get_account_record(account_id)
    if account is None:
        print(f"{BIND_LOG}   ❌ 账号不存在: {account_id}", flush=True)
        return {"success": False, "message": f"账号不存在: {account_id}"}
    print(f"{BIND_LOG}   账号: {account.get('account')}", flush=True)

    bindings = list_account_bindings()
    binding = next(
        (b for b in bindings if b.get("account_uid") == account_id),
        None,
    )
    if binding is None:
        print(f"{BIND_LOG}   ❌ 账号未绑定代理", flush=True)
        return {
            "success": False,
            "message": f"账号 {account.get('account')} 尚未绑定任何代理",
        }
    print(f"{BIND_LOG}   绑定的 proxy_id={binding.get('proxy_id')}", flush=True)

    proxy = get_proxy_record(binding.get("proxy_id", ""))
    if proxy is None:
        print(f"{BIND_LOG}   ❌ 绑定的代理已被删除", flush=True)
        return {
            "success": False,
            "message": f"绑定的代理已被删除 (proxy_id={binding.get('proxy_id')})",
        }
    print(f"{BIND_LOG}   代理: {proxy.get('ip')}:{proxy.get('port')} (status={proxy.get('status')})", flush=True)

    print(f"{BIND_LOG}   开始两层验证...", flush=True)
    result = do_verify(account=account, proxy=proxy)
    print(f"{BIND_LOG}   验证结果: success={result['success']}", flush=True)

    return {"success": True, "verification": result}


# ---------- 批量绑定 + 批量验证 ----------


class BatchBindRequest(BaseModel):
    """批量自动绑定：将选中的账号自动分配空闲代理"""
    account_ids: list[str] = Field(..., min_length=1)
    proxy_type: str = "publish"


class BatchVerifyRequest(BaseModel):
    """批量验证绑定状态"""
    account_ids: list[str] = Field(..., min_length=1)


@app.post("/api/bindings/batch-auto-bind")
def api_batch_auto_bind(req: BatchBindRequest):
    """
    批量自动绑定：为选中的账号自动分配空闲的发布代理。
    空闲代理 = publish 类型 + active/slow 状态 + 未被任何账号绑定。
    """
    proxy_type = req.proxy_type or "publish"
    print(f"{BIND_LOG} POST /api/bindings/batch-auto-bind 账号数={len(req.account_ids)} proxy_type={proxy_type}", flush=True)

    # 1. 获取对应类型的代理
    all_proxies = list_proxy_records()
    publish_proxies = [
        p for p in all_proxies
        if p.get("type") == proxy_type and p.get("status") in ("active", "slow")
    ]
    print(f"{BIND_LOG}   可用{proxy_type}代理总数: {len(publish_proxies)}", flush=True)

    # 2. 获取已绑定的 proxy_id 集合
    existing_bindings = list_account_bindings()
    bound_proxy_ids = {b.get("proxy_id") for b in existing_bindings}
    print(f"{BIND_LOG}   已被绑定的代理数: {len(bound_proxy_ids)}", flush=True)

    # 3. 筛选空闲代理
    free_proxies = [p for p in publish_proxies if p["id"] not in bound_proxy_ids]
    print(f"{BIND_LOG}   空闲代理数: {len(free_proxies)}", flush=True)

    # 4. 筛选需要绑定的账号（排除已绑定的）
    bound_account_ids = {b.get("account_uid") for b in existing_bindings}
    accounts_to_bind = []
    for aid in req.account_ids:
        if aid in bound_account_ids:
            print(f"{BIND_LOG}   跳过已绑定账号: {aid}", flush=True)
            continue
        acc = get_account_record(aid)
        if acc is None:
            print(f"{BIND_LOG}   跳过不存在的账号: {aid}", flush=True)
            continue
        accounts_to_bind.append(acc)
    print(f"{BIND_LOG}   需要绑定的账号数: {len(accounts_to_bind)}", flush=True)

    if not accounts_to_bind:
        return {
            "success": True,
            "message": "所有选中的账号已经绑定了代理，无需操作",
            "bound_count": 0,
            "skipped_count": len(req.account_ids),
            "results": [],
        }

    if len(free_proxies) < len(accounts_to_bind):
        print(f"{BIND_LOG}   ⚠️ 空闲代理不足: 需要{len(accounts_to_bind)}个，只有{len(free_proxies)}个", flush=True)

    # 5. 逐个绑定
    results = []
    bound_count = 0
    for i, acc in enumerate(accounts_to_bind):
        if i >= len(free_proxies):
            results.append({
                "account_id": acc["id"],
                "account_name": acc.get("account"),
                "success": False,
                "message": "空闲代理已用完",
            })
            print(f"{BIND_LOG}   [{i+1}/{len(accounts_to_bind)}] {acc.get('account')} → ❌ 无空闲代理", flush=True)
            continue

        proxy = free_proxies[i]
        proxy_label = f"{proxy['protocol']}://{proxy['ip']}:{proxy['port']}"
        try:
            upsert_account_binding(
                platform=acc.get("platform", "twitter"),
                account_uid=acc["id"],
                account_name=acc.get("account"),
                proxy_id=proxy["id"],
            )
            results.append({
                "account_id": acc["id"],
                "account_name": acc.get("account"),
                "proxy_id": proxy["id"],
                "proxy_label": proxy_label,
                "success": True,
                "message": f"已绑定到 {proxy_label}",
            })
            bound_count += 1
            print(f"{BIND_LOG}   [{i+1}/{len(accounts_to_bind)}] {acc.get('account')} → ✅ {proxy_label}", flush=True)
        except ValueError as e:
            results.append({
                "account_id": acc["id"],
                "account_name": acc.get("account"),
                "success": False,
                "message": str(e),
            })
            print(f"{BIND_LOG}   [{i+1}/{len(accounts_to_bind)}] {acc.get('account')} → ❌ {e}", flush=True)

    msg = f"批量绑定完成: 成功 {bound_count}/{len(accounts_to_bind)}"
    if len(free_proxies) < len(accounts_to_bind):
        msg += f"（空闲代理不足，缺少 {len(accounts_to_bind) - len(free_proxies)} 个）"
    print(f"{BIND_LOG}   {msg}", flush=True)

    return {
        "success": bound_count > 0,
        "message": msg,
        "bound_count": bound_count,
        "skipped_count": len(req.account_ids) - len(accounts_to_bind),
        "failed_count": len(accounts_to_bind) - bound_count,
        "results": results,
    }


@app.post("/api/bindings/batch-verify")
def api_batch_verify(req: BatchVerifyRequest):
    """批量验证选中账号的绑定状态（两层验证）"""
    from binding_verifier import verify_binding as do_verify

    print(f"{BIND_LOG} POST /api/bindings/batch-verify 账号数={len(req.account_ids)}", flush=True)

    all_bindings = list_account_bindings()
    binding_map = {b.get("account_uid"): b for b in all_bindings}

    results = []
    for i, account_id in enumerate(req.account_ids):
        print(f"{BIND_LOG}   [{i+1}/{len(req.account_ids)}] 验证账号 {account_id}", flush=True)

        account = get_account_record(account_id)
        if account is None:
            print(f"{BIND_LOG}     ❌ 账号不存在", flush=True)
            results.append({
                "account_id": account_id,
                "account_name": None,
                "success": False,
                "summary": "账号不存在",
            })
            continue

        binding = binding_map.get(account_id)
        if binding is None:
            print(f"{BIND_LOG}     ❌ 未绑定代理", flush=True)
            results.append({
                "account_id": account_id,
                "account_name": account.get("account"),
                "success": False,
                "summary": "未绑定代理",
            })
            continue

        proxy = get_proxy_record(binding.get("proxy_id", ""))
        if proxy is None:
            print(f"{BIND_LOG}     ❌ 绑定的代理已被删除", flush=True)
            results.append({
                "account_id": account_id,
                "account_name": account.get("account"),
                "success": False,
                "summary": "绑定的代理已被删除",
            })
            continue

        print(f"{BIND_LOG}     开始验证 {account.get('account')} ↔ {proxy.get('ip')}:{proxy.get('port')}", flush=True)
        verification = do_verify(account=account, proxy=proxy)
        print(f"{BIND_LOG}     结果: success={verification['success']}", flush=True)

        results.append({
            "account_id": account_id,
            "account_name": account.get("account"),
            "success": verification["success"],
            "summary": verification["summary"],
            "verification": verification,
        })

    success_count = sum(1 for r in results if r["success"])
    fail_count = len(results) - success_count
    msg = f"批量验证完成: {success_count} 通过, {fail_count} 失败 (共 {len(results)})"
    print(f"{BIND_LOG}   {msg}", flush=True)

    return {
        "success": True,
        "message": msg,
        "success_count": success_count,
        "fail_count": fail_count,
        "results": results,
    }


@app.get("/api/health")
def health_check() -> dict[str, str]:
    ensure_material_tree()
    return {"status": "ok"}


@app.post("/api/tasks/collect/single-work")
def create_single_work_collect_task(payload: SingleWorkCollectRequest) -> dict[str, Any]:
    ensure_material_tree()
    normalized_links = [link.strip() for link in payload.links if link.strip()]
    if not normalized_links:
        return {
            "success": False,
            "message": "至少提供一个有效作品链接",
            "results": [],
            "success_count": 0,
            "failure_count": 0,
        }

    task_title = (payload.title or "").strip() or "指定作品采集任务"
    task_description = (payload.description or "").strip() or "按作品链接执行批量采集。"
    task_record = create_task_record(
        kind="collect-single-work",
        task_type="collect",
        collect_mode="single-work",
        title=task_title,
        description=task_description,
        payload={
            "links": normalized_links,
            "title": task_title,
            "description": task_description,
        },
        total_steps=max(len(normalized_links) * 2, 1),
    )

    try:
        worker_pid = launch_task_worker(task_record["id"])
        task_record = update_task_record(task_record["id"], worker_pid=worker_pid) or task_record
        append_task_log(
            task_record["id"],
            f"任务已加入后台队列，待处理链接数: {len(normalized_links)}",
        )
    except Exception as e:
        task_record = (
            update_task_record(
                task_record["id"],
                status="failed",
                error=f"后台任务启动失败: {e}",
                ended_at=datetime.now().isoformat(timespec="seconds"),
            )
            or task_record
        )
        return {
            "success": False,
            "queued": False,
            "message": f"后台任务启动失败: {e}",
            "task_id": task_record["id"],
            "task": task_record,
        }

    return {
        "success": True,
        "queued": True,
        "message": "采集任务已创建，正在后台执行",
        "task_id": task_record["id"],
        "task": task_record,
    }


@app.post("/api/tasks/collect/author")
def create_author_collect_task(payload: AuthorCollectRequest) -> dict[str, Any]:
    ensure_material_tree()

    platform = normalize_platform_type(payload.platform)
    if platform not in PLATFORMS_WITH_AUTHOR_TREE:
        return {
            "success": False,
            "message": f"不支持的平台: {platform}，支持: B站、抖音、小红书",
            "results": [],
            "success_count": 0,
            "failure_count": 0,
        }

    collect_action = payload.collect_action.strip().lower()
    if collect_action not in {"data-only", "collect-download"}:
        return {
            "success": False,
            "message": "collect_action 仅支持 data-only 或 collect-download",
            "results": [],
            "success_count": 0,
            "failure_count": 0,
        }

    normalized_uids = [uid.strip() for uid in payload.uids if uid.strip()]
    if not normalized_uids:
        return {
            "success": False,
            "message": "至少提供一个有效作者 UID",
            "results": [],
            "success_count": 0,
            "failure_count": 0,
        }

    task_title = (payload.title or "").strip() or "指定作者采集任务"
    task_description = (payload.description or "").strip() or "按作者 UID 执行采集流程。"
    task_record = create_task_record(
        kind="collect-author",
        task_type="collect",
        collect_mode="author",
        title=task_title,
        description=task_description,
        payload={
            "platform": platform,
            "collect_action": collect_action,
            "uids": normalized_uids,
            "title": task_title,
            "description": task_description,
        },
        total_steps=max(len(normalized_uids) * 2, 1),
    )

    try:
        worker_pid = launch_task_worker(task_record["id"])
        task_record = update_task_record(task_record["id"], worker_pid=worker_pid) or task_record
        append_task_log(
            task_record["id"],
            f"任务已加入后台队列，待处理 UID 数: {len(normalized_uids)}",
        )
    except Exception as e:
        task_record = (
            update_task_record(
                task_record["id"],
                status="failed",
                error=f"后台任务启动失败: {e}",
                ended_at=datetime.now().isoformat(timespec="seconds"),
            )
            or task_record
        )
        return {
            "success": False,
            "queued": False,
            "message": f"后台任务启动失败: {e}",
            "task_id": task_record["id"],
            "task": task_record,
        }

    return {
        "success": True,
        "queued": True,
        "message": "指定作者采集任务已创建，正在后台执行",
        "task_id": task_record["id"],
        "task": task_record,
    }


@app.post("/api/tasks/collect/author/selective-download")
def selective_download_author_videos(payload: AuthorSelectiveDownloadRequest) -> dict[str, Any]:
    ensure_material_tree()

    platform = normalize_platform_type(payload.platform)
    if platform != "bilibili":
        return {
            "success": False,
            "message": "当前仅支持 B站 选择性下载",
            "results": [],
            "success_count": 0,
            "failure_count": 0,
        }

    author_uid = payload.author_uid.strip()
    selected_video_folders = [
        folder.strip() for folder in payload.selected_video_folders if folder.strip()
    ]
    if not author_uid or not selected_video_folders:
        return {
            "success": False,
            "message": "author_uid 和 selected_video_folders 均不能为空",
            "results": [],
            "success_count": 0,
            "failure_count": 0,
        }

    task_record = create_task_record(
        kind="collect-author-selective-download",
        task_type="collect",
        collect_mode="author",
        title=f"{author_uid} 选择性下载",
        description=f"按勾选清单下载作者 {author_uid} 的视频源文件。",
        payload={
            "platform": platform,
            "author_uid": author_uid,
            "selected_video_folders": selected_video_folders,
        },
        total_steps=max(len(selected_video_folders) * 2, 1),
    )

    try:
        worker_pid = launch_task_worker(task_record["id"])
        task_record = update_task_record(task_record["id"], worker_pid=worker_pid) or task_record
        append_task_log(
            task_record["id"],
            f"任务已加入后台队列，待下载作品数: {len(selected_video_folders)}",
        )
    except Exception as e:
        task_record = (
            update_task_record(
                task_record["id"],
                status="failed",
                error=f"后台任务启动失败: {e}",
                ended_at=datetime.now().isoformat(timespec="seconds"),
            )
            or task_record
        )
        return {
            "success": False,
            "queued": False,
            "message": f"后台任务启动失败: {e}",
            "task_id": task_record["id"],
            "task": task_record,
        }

    return {
        "success": True,
        "queued": True,
        "message": "选择性下载任务已创建，正在后台执行",
        "task_id": task_record["id"],
        "task": task_record,
    }


@app.get("/api/tasks")
def get_tasks(limit: int = 200) -> dict[str, Any]:
    safe_limit = max(min(int(limit), 1000), 1)
    tasks = list_task_records(limit=safe_limit)
    return {
        "success": True,
        "tasks": tasks,
        "count": len(tasks),
    }


@app.get("/api/tasks/{task_id}")
def get_task_detail(task_id: str) -> dict[str, Any]:
    task = read_task_record(task_id)
    if task is None:
        return {
            "success": False,
            "message": "任务不存在",
            "task": None,
        }
    enriched_task = dict(task)
    enriched_task["logs"] = build_task_full_logs(task)
    return {
        "success": True,
        "task": enriched_task,
    }


@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: str) -> dict[str, Any]:
    task = read_task_record(task_id)
    if task is None:
        return {
            "success": False,
            "message": "任务不存在",
        }

    worker_pid = task.get("worker_pid")
    status = str(task.get("status") or "")
    terminated_worker = False

    if status in {"pending", "running"} and worker_pid is not None:
        try:
            os.kill(int(worker_pid), signal.SIGTERM)
            terminated_worker = True
        except ProcessLookupError:
            terminated_worker = False
        except Exception:
            terminated_worker = False

    deleted = delete_task_record(task_id)
    if not deleted:
        return {
            "success": False,
            "message": "任务删除失败",
        }

    log_path = TASK_WORKER_LOG_DIR / f"{task_id}.log"
    if log_path.exists():
        try:
            log_path.unlink()
        except Exception:
            pass

    return {
        "success": True,
        "message": "任务已删除",
        "terminated_worker": terminated_worker,
    }


@app.post("/api/materials/delete")
def delete_material_entries(payload: MaterialsDeleteRequest) -> dict[str, Any]:
    ensure_material_tree()
    normalized_paths = [
        normalize_material_delete_path(path) for path in payload.paths if str(path).strip()
    ]
    unique_paths = list(dict.fromkeys(normalized_paths))

    if not unique_paths:
        return {
            "success": False,
            "message": "未提供可删除的路径",
            "deleted_paths": [],
            "failures": [],
            "success_count": 0,
            "failure_count": 0,
        }

    deleted_paths: list[str] = []
    failures: list[dict[str, str]] = []

    # 先删更深层路径，避免先删父目录导致子项误报不存在。
    unique_paths.sort(key=lambda path: len(Path(path).parts), reverse=True)

    for relative_path in unique_paths:
        target = resolve_material_delete_target(relative_path)
        if target is None:
            failures.append({"path": relative_path, "reason": "非法路径"})
            continue

        allowed, reason = validate_material_delete_target(target)
        if not allowed:
            failures.append({"path": relative_path, "reason": reason})
            continue

        try:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            deleted_paths.append(relative_path)
        except Exception as e:
            failures.append({"path": relative_path, "reason": f"删除失败: {e}"})

    success_count = len(deleted_paths)
    failure_count = len(failures)
    return {
        "success": failure_count == 0,
        "message": "删除完成" if failure_count == 0 else "部分路径删除失败",
        "deleted_paths": deleted_paths,
        "failures": failures,
        "success_count": success_count,
        "failure_count": failure_count,
    }


@app.post("/api/materials/user-upload/folders")
def create_user_upload_folder(payload: UserUploadFolderCreateRequest) -> dict[str, Any]:
    ensure_material_tree()

    folder_name = sanitize_folder_name(payload.name)
    if not folder_name:
        return {"success": False, "message": "目录名不能为空"}

    upload_root = MATERIALS_ROOT / USER_UPLOAD_PLATFORM_NAME

    # 支持在任意深度的父目录下创建子目录
    parent_relative = getattr(payload, "parent_path", None) or ""
    if parent_relative:
        parent_target = resolve_material_delete_target(parent_relative)
        if parent_target is None or not parent_target.exists() or not parent_target.is_dir():
            return {"success": False, "message": "父目录不存在"}
        try:
            parent_target.resolve().relative_to(upload_root.resolve())
        except Exception:
            return {"success": False, "message": "仅允许在用户上传目录下创建子目录"}
        target_dir = parent_target / folder_name
    else:
        target_dir = upload_root / folder_name

    if target_dir.exists():
        return {"success": False, "message": "同名目录已存在"}

    try:
        target_dir.mkdir(parents=True, exist_ok=False)
    except Exception as e:
        return {"success": False, "message": f"创建目录失败: {e}"}

    return {
        "success": True,
        "message": "目录创建成功",
        "folder": {
            "name": folder_name,
            "relative_path": to_base_relative_path(target_dir),
        },
    }


@app.post("/api/materials/user-upload/files")
def upload_user_material_file(
    folder_path: str = Form(...),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    ensure_material_tree()

    target_dir = resolve_material_delete_target(folder_path)
    if target_dir is None or not target_dir.exists() or not target_dir.is_dir():
        return {"success": False, "message": "上传目录不存在"}

    try:
        relative_to_materials = target_dir.resolve().relative_to(MATERIALS_ROOT.resolve())
    except Exception:
        return {"success": False, "message": "上传目录非法"}

    parts = list(relative_to_materials.parts)
    if len(parts) < 1 or parts[0] != USER_UPLOAD_PLATFORM_NAME:
        return {"success": False, "message": "仅允许上传到用户上传目录下"}

    original_name = str(file.filename or "").strip()
    if not original_name:
        return {"success": False, "message": "文件名不能为空"}

    safe_name = sanitize_file_name(original_name)
    target_file = make_unique_file_path(target_dir, safe_name)

    try:
        with open(target_file, "wb") as out:
            shutil.copyfileobj(file.file, out)
    except Exception as e:
        return {"success": False, "message": f"文件上传失败: {e}"}
    finally:
        try:
            file.file.close()
        except Exception:
            pass

    return {
        "success": True,
        "message": "文件上传成功",
        "file": {
            "name": target_file.name,
            "relative_path": to_base_relative_path(target_file),
            "size": target_file.stat().st_size,
        },
    }


PREVIEWABLE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".ico",
    ".mp4", ".webm", ".mov", ".avi", ".mkv",
    ".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a",
    ".pdf", ".txt", ".csv", ".json", ".md", ".log",
    ".m4s",
}


@app.get("/api/materials/preview")
def preview_material_file(path: str = "") -> Any:
    target = resolve_material_delete_target(path)
    if target is None or not target.exists() or not target.is_file():
        return {"success": False, "message": "文件不存在"}

    try:
        target.resolve().relative_to(MATERIALS_ROOT.resolve())
    except Exception:
        return {"success": False, "message": "文件路径非法"}

    ext = target.suffix.lower()
    if ext not in PREVIEWABLE_EXTENSIONS:
        return {"success": False, "message": f"不支持预览此文件类型 ({ext})"}

    return FileResponse(
        path=str(target),
        filename=target.name,
        media_type=None,
    )


@app.get("/api/materials/tree")
def get_material_tree() -> dict[str, Any]:
    ensure_material_tree()
    roots = []

    for platform_key, platform_display_name in PLATFORM_DIRS.items():
        root_dir = MATERIALS_ROOT / platform_display_name
        second_children = []
        if platform_key == USER_UPLOAD_PLATFORM_KEY:
            second_dirs = sorted(
                [
                    item
                    for item in root_dir.iterdir()
                    if item.is_dir() and not item.name.startswith(".")
                ],
                key=lambda item: item.name.lower(),
            )
            for second_dir in second_dirs:
                second_id = f"{platform_key}-{second_dir.name}"
                second_children.append(
                    {
                        "id": second_id,
                        "name": second_dir.name,
                        "children": build_entry_nodes(second_dir, second_id, depth=4),
                        "relative_path": to_base_relative_path(second_dir),
                        "is_dir": True,
                    }
                )
        else:
            for second in get_second_level_dirs(platform_key):
                second_dir = root_dir / second
                third_folders = sorted(
                    [item for item in second_dir.iterdir() if item.is_dir()],
                    key=lambda item: item.name.lower(),
                )
                third_nodes: list[dict[str, Any]] = []
                for folder in third_folders:
                    third_id = f"{platform_key}-{second}-{folder.name}"
                    display_name = folder.name
                    author_uid: str | None = None

                    if is_bilibili_author_tree(platform_key, second):
                        meta = read_author_meta(folder)
                        if isinstance(meta, dict):
                            author_uid = str(meta.get("uid") or "").strip() or None
                            author_name = str(meta.get("author_name") or "").strip()
                            if author_name:
                                display_name = author_name
                        if author_uid is None and folder.name.isdigit():
                            # 兼容旧数据目录（目录名直接是 uid）
                            author_uid = folder.name
                        if display_name == folder.name:
                            inferred_author_name = infer_author_name_from_video_csv(folder)
                            if inferred_author_name:
                                display_name = inferred_author_name

                    third_node: dict[str, Any] = {
                        "id": third_id,
                        "name": display_name,
                        "children": build_entry_nodes(folder, third_id, depth=1),
                        "relative_path": to_base_relative_path(folder),
                        "is_dir": True,
                    }
                    if author_uid:
                        third_node["author_uid"] = author_uid
                    third_nodes.append(third_node)

                second_children.append(
                    {
                        "id": f"{platform_key}-{second}",
                        "name": second,
                        "children": third_nodes,
                        "relative_path": to_base_relative_path(second_dir),
                        "is_dir": True,
                    }
                )

        roots.append(
            {
                "id": platform_key,
                "name": platform_display_name,
                "children": second_children,
                "relative_path": to_base_relative_path(root_dir),
                "is_dir": True,
            }
        )

    return {"roots": roots}


class MaterialResolvePathRequest(BaseModel):
    relative_path: str = Field(..., min_length=1)


@app.post("/api/materials/resolve-path")
def resolve_material_path(payload: MaterialResolvePathRequest) -> dict[str, Any]:
    """Return the absolute path on disk for a material file (for the publisher)."""
    target = resolve_material_delete_target(payload.relative_path)
    if target is None:
        return {"success": False, "message": "非法路径"}
    if not target.exists():
        return {"success": False, "message": "文件不存在"}
    if not target.is_file():
        return {"success": False, "message": "路径不是文件"}
    try:
        target.resolve().relative_to(MATERIALS_ROOT.resolve())
    except Exception:
        return {"success": False, "message": "文件路径非法"}
    return {"success": True, "local_path": str(target)}


# ==========================================================================
# Bilibili Cookie API
# ==========================================================================

@app.post("/api/bilibili/cookie/auto-detect")
def bilibili_cookie_auto_detect() -> dict[str, Any]:
    """从本地 Chrome 浏览器自动提取 B 站 Cookie，并验证有效性"""
    import logging
    log = logging.getLogger("bilibili_cookie")

    log.info("━━━ [Cookie Auto-Detect] 开始 ━━━")

    try:
        import browser_cookie3
        log.info("[1/5] browser_cookie3 已导入")
    except ImportError:
        log.error("[1/5] browser_cookie3 未安装")
        return {"success": False, "message": "缺少 browser_cookie3 依赖，请运行 pip install browser-cookie3"}

    try:
        cj = browser_cookie3.chrome(domain_name=".bilibili.com")
        log.info("[2/5] Chrome Cookie 数据库读取成功")
    except Exception as exc:
        log.error(f"[2/5] Chrome Cookie 数据库读取失败: {exc}")
        return {
            "success": False,
            "message": f"读取 Chrome Cookie 失败: {exc}. 请确认已在 Chrome 中登录 B 站，且 Chrome 已完全关闭。",
        }

    # 解析 cookie
    cookies = {c.name: c.value for c in cj if c.value}
    keys = list(cookies.keys())
    has_sessdata = "SESSDATA" in cookies
    has_buvid = any(k.startswith("buvid") for k in keys)
    sessdata_preview = cookies.get("SESSDATA", "")[:12] + "..." if has_sessdata else "(无)"
    log.info(f"[3/5] 解析完成: 共 {len(keys)} 个字段, SESSDATA={sessdata_preview}, has_buvid={has_buvid}")
    log.info(f"[3/5] 全部 key: {keys}")

    if not cookies:
        log.warning("[3/5] 未找到任何 cookie")
        return {"success": False, "message": "未找到 bilibili.com 的 Cookie，请确认已在 Chrome 中登录 B 站"}

    if not has_sessdata and not has_buvid:
        log.warning(f"[3/5] 缺少关键字段, 找到的 key: {keys}")
        return {
            "success": False,
            "message": "找到的 Cookie 中缺少关键字段 (SESSDATA / buvid)，可能未登录",
            "keys_found": keys,
        }

    # 验证 cookie 是否真的有效（调用 B 站导航接口）
    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
    verify_result = {"is_login": False, "uname": None, "mid": None}
    try:
        import requests as _req
        resp = _req.get(
            "https://api.bilibili.com/x/web-interface/nav",
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Cookie": cookie_str,
            },
            timeout=10,
        )
        nav = resp.json()
        is_login = nav.get("data", {}).get("isLogin", False)
        uname = nav.get("data", {}).get("uname", "")
        mid = nav.get("data", {}).get("mid", "")
        verify_result = {"is_login": is_login, "uname": uname, "mid": mid}
        log.info(f"[4/5] B站登录验证: isLogin={is_login}, uname={uname}, mid={mid}, http={resp.status_code}")
    except Exception as exc:
        log.warning(f"[4/5] B站登录验证请求失败 (不影响更新): {exc}")

    # 更新 cookie
    from bilibili_crawler import update_cookie
    update_cookie(cookie_str)
    log.info(f"[5/5] Cookie 已更新并持久化到 runtime/bilibili_cookie.txt")
    log.info("━━━ [Cookie Auto-Detect] 完成 ━━━")

    return {
        "success": True,
        "message": f"已更新，包含 {len(keys)} 个字段" + (f"，当前登录: {verify_result['uname']}" if verify_result["is_login"] else "（⚠️ 未登录状态，Cookie 可能已失效）"),
        "keys_found": keys,
        "key_count": len(keys),
        "has_sessdata": has_sessdata,
        "has_buvid": has_buvid,
        "verify": verify_result,
    }


@app.get("/api/bilibili/cookie/status")
def bilibili_cookie_status() -> dict[str, Any]:
    """返回当前 B 站 Cookie 状态"""
    from bilibili_crawler import get_cookie_info
    return get_cookie_info()


class CookieSetRequest(BaseModel):
    cookie: str = Field(..., min_length=1)


@app.post("/api/bilibili/cookie/set")
def bilibili_cookie_set(payload: CookieSetRequest) -> dict[str, Any]:
    """手动设置 B 站 Cookie"""
    from bilibili_crawler import update_cookie
    cookie_str = payload.cookie.strip()
    if not cookie_str:
        return {"success": False, "message": "Cookie 不能为空"}
    update_cookie(cookie_str)
    keys = [k.strip().split("=")[0] for k in cookie_str.split(";") if "=" in k]
    return {
        "success": True,
        "message": f"已保存，包含 {len(keys)} 个字段",
        "key_count": len(keys),
        "keys_found": keys,
    }


@app.get("/api/bilibili/cookie/get")
def bilibili_cookie_get() -> dict[str, Any]:
    """返回当前 B 站 Cookie 原文"""
    from bilibili_crawler import _load_cookie
    return {"cookie": _load_cookie()}


@app.get("/api/douyin/cookie/get")
def douyin_cookie_get() -> dict[str, Any]:
    """返回当前抖音 Cookie 原文"""
    return {"cookie": _load_douyin_cookie()}


@app.get("/api/xiaohongshu/cookie/get")
def xhs_cookie_get() -> dict[str, Any]:
    """返回当前小红书 Cookie 原文"""
    return {"cookie": _load_xhs_cookie()}


# ==========================================================================
# Longmao Token API
# ==========================================================================

_LONGMAO_TOKEN_FILE = MATERIALS_ROOT.parent / "backend" / "runtime" / "longmao_token.txt"


def _load_longmao_token() -> str:
    if _LONGMAO_TOKEN_FILE.exists():
        try:
            text = _LONGMAO_TOKEN_FILE.read_text(encoding="utf-8").strip()
            if text:
                return text
        except Exception:
            pass
    return ""


@app.post("/api/longmao/token/set")
def longmao_token_set(payload: CookieSetRequest) -> dict[str, Any]:
    """手动设置 Longmao Token"""
    token_str = payload.cookie.strip()
    if not token_str:
        return {"success": False, "message": "Token 不能为空"}
    _LONGMAO_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    _LONGMAO_TOKEN_FILE.write_text(token_str, encoding="utf-8")
    return {
        "success": True,
        "message": "Token 已保存",
        "key_count": 1,
    }


@app.get("/api/longmao/token/status")
def longmao_token_status() -> dict[str, Any]:
    """返回当前 Longmao Token 状态"""
    token = _load_longmao_token()
    return {
        "is_set": bool(token),
        "source": "file" if _LONGMAO_TOKEN_FILE.exists() and token else "none",
        "key_count": 1 if token else 0,
    }


@app.get("/api/longmao/token/get")
def longmao_token_get() -> dict[str, Any]:
    """返回当前 Longmao Token 原文"""
    return {"cookie": _load_longmao_token()}


# ==========================================================================
# Douyin Cookie API
# ==========================================================================

_DOUYIN_COOKIE_FILE = MATERIALS_ROOT.parent / "backend" / "runtime" / "douyin_cookie.txt"


def _load_douyin_cookie() -> str:
    if _DOUYIN_COOKIE_FILE.exists():
        try:
            text = _DOUYIN_COOKIE_FILE.read_text(encoding="utf-8").strip()
            if text:
                return text
        except Exception:
            pass
    return os.getenv("DOUYIN_COOKIE", "").strip()



@app.post("/api/douyin/cookie/set")
def douyin_cookie_set(payload: CookieSetRequest) -> dict[str, Any]:
    """手动设置抖音 Cookie"""
    cookie_str = payload.cookie.strip()
    if not cookie_str:
        return {"success": False, "message": "Cookie 不能为空"}
    _DOUYIN_COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _DOUYIN_COOKIE_FILE.write_text(cookie_str, encoding="utf-8")
    keys = [k.strip().split("=")[0] for k in cookie_str.split(";") if "=" in k]
    return {
        "success": True,
        "message": f"已保存，包含 {len(keys)} 个字段",
        "key_count": len(keys),
        "keys_found": keys,
    }


@app.get("/api/douyin/cookie/status")
def douyin_cookie_status() -> dict[str, Any]:
    """返回当前抖音 Cookie 状态"""
    cookie = _load_douyin_cookie()
    keys = [k.strip().split("=")[0] for k in cookie.split(";") if "=" in k] if cookie else []
    return {
        "is_set": bool(cookie),
        "source": "file" if _DOUYIN_COOKIE_FILE.exists() and cookie else ("env" if cookie else "none"),
        "keys": keys,
        "key_count": len(keys),
    }


# ==========================================================================
# Xiaohongshu Cookie API
# ==========================================================================

_XHS_COOKIE_FILE = MATERIALS_ROOT.parent / "backend" / "runtime" / "xhs_cookie.txt"


def _load_xhs_cookie() -> str:
    if _XHS_COOKIE_FILE.exists():
        try:
            text = _XHS_COOKIE_FILE.read_text(encoding="utf-8").strip()
            if text:
                return text
        except Exception:
            pass
    return os.getenv("XHS_COOKIE", "").strip()


@app.post("/api/xiaohongshu/cookie/set")
def xhs_cookie_set(payload: CookieSetRequest) -> dict[str, Any]:
    """手动设置小红书 Cookie"""
    cookie_str = payload.cookie.strip()
    if not cookie_str:
        return {"success": False, "message": "Cookie 不能为空"}
    _XHS_COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _XHS_COOKIE_FILE.write_text(cookie_str, encoding="utf-8")
    keys = [k.strip().split("=")[0] for k in cookie_str.split(";") if "=" in k]
    return {
        "success": True,
        "message": f"已保存，包含 {len(keys)} 个字段",
        "key_count": len(keys),
        "keys_found": keys,
    }


@app.get("/api/xiaohongshu/cookie/status")
def xhs_cookie_status() -> dict[str, Any]:
    """返回当前小红书 Cookie 状态"""
    cookie = _load_xhs_cookie()
    keys = [k.strip().split("=")[0] for k in cookie.split(";") if "=" in k] if cookie else []
    return {
        "is_set": bool(cookie),
        "source": "file" if _XHS_COOKIE_FILE.exists() and cookie else ("env" if cookie else "none"),
        "keys": keys,
        "key_count": len(keys),
    }


# ==========================================================================
# Twitter Publish API
# ==========================================================================

class TweetPublishRequest(BaseModel):
    account_id: str = Field(..., min_length=1)
    text: str = ""
    media_paths: list[str] | None = None
    is_sensitive: bool = False


class QueueAddRequest(BaseModel):
    account_id: str = Field(..., min_length=1)
    tweet_type: str = "text"
    content: dict
    strategy: dict | None = None
    priority: int = 0


class QueueReorderRequest(BaseModel):
    item_id: str = Field(..., min_length=1)
    new_priority: int


# ---- Immediate publish ----------------------------------------------------

@app.post("/api/publish/tweet")
async def publish_tweet_now(req: TweetPublishRequest):
    content = {
        "text": req.text,
        "media_paths": req.media_paths,
        "is_sensitive": req.is_sensitive,
    }
    result = await publish_single_tweet(req.account_id, content)

    # Record in history regardless of outcome
    tweet_type = "text"
    if req.media_paths:
        first = (req.media_paths[0] or "").lower()
        if first.endswith((".mp4", ".mov", ".avi", ".webm")):
            tweet_type = "video"
        elif first.endswith(".gif"):
            tweet_type = "gif"
        else:
            tweet_type = "image"

    publish_store.create_history_record(
        account_id=req.account_id,
        tweet_type=tweet_type,
        content=content,
        status="success" if result.get("success") else "failed",
        tweet_id=result.get("tweet_id"),
        tweet_url=result.get("tweet_url"),
        error_message=result.get("message") if not result.get("success") else None,
    )

    return result


# ---- Media upload ---------------------------------------------------------

MEDIA_UPLOAD_DIR = BASE_DIR / "runtime" / "media-uploads"
MEDIA_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@app.post("/api/publish/upload-media")
async def publish_upload_media(
    account_id: str = Form(...),
    file: UploadFile = File(...),
):
    import uuid as _uuid
    safe_name = f"{_uuid.uuid4().hex}_{file.filename or 'upload'}"
    file_path = MEDIA_UPLOAD_DIR / safe_name
    data = await file.read()
    with open(file_path, "wb") as f:
        f.write(data)

    try:
        from twitter_publisher import get_or_create_session
        session = await get_or_create_session(account_id)
        media_id = await session.upload_media_file(str(file_path))
        return {
            "success": True,
            "media_id": media_id,
            "local_path": str(file_path),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ---- Queue management -----------------------------------------------------

@app.get("/api/publish/queue")
async def list_publish_queue(
    account_id: str | None = None,
    status: str | None = None,
):
    items = publish_store.list_queue_items(account_id=account_id, status=status)
    return {"success": True, "items": items, "total": len(items)}


@app.post("/api/publish/queue")
async def add_to_publish_queue(req: QueueAddRequest):
    item = publish_store.create_queue_item(
        account_id=req.account_id,
        tweet_type=req.tweet_type,
        content=req.content,
        strategy=req.strategy,
        priority=req.priority,
    )
    return {"success": True, "item": item}


@app.put("/api/publish/queue/{item_id}")
async def update_publish_queue_item(item_id: str, body: dict):
    allowed = {"content", "strategy", "priority", "status", "tweet_type"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        return {"success": False, "error": "无有效更新字段"}
    result = publish_store.update_queue_item(item_id, **updates)
    if result is None:
        return {"success": False, "error": "队列项不存在"}
    return {"success": True, "item": result}


@app.delete("/api/publish/queue/{item_id}")
async def delete_publish_queue_item(item_id: str):
    ok = publish_store.delete_queue_item(item_id)
    return {"success": ok}


@app.post("/api/publish/queue/reorder")
async def reorder_publish_queue(req: QueueReorderRequest):
    result = publish_store.reorder_queue_item(req.item_id, req.new_priority)
    if result is None:
        return {"success": False, "error": "队列项不存在"}
    return {"success": True, "item": result}


@app.post("/api/publish/queue/pause/{account_id}")
async def pause_publish_queue(account_id: str):
    count = publish_store.pause_account_queue(account_id)
    return {"success": True, "paused_count": count}


@app.post("/api/publish/queue/resume/{account_id}")
async def resume_publish_queue(account_id: str):
    count = publish_store.resume_account_queue(account_id)
    return {"success": True, "resumed_count": count}


# ---- History ---------------------------------------------------------------

@app.get("/api/publish/history")
async def list_publish_history(
    account_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
):
    items = publish_store.list_history(account_id=account_id, status=status, limit=limit)
    return {"success": True, "items": items, "total": len(items)}


# ---- Scheduler control -----------------------------------------------------

@app.get("/api/publish/scheduler/status")
async def get_publish_scheduler_status():
    return publish_scheduler.get_scheduler_status()


@app.post("/api/publish/scheduler/trigger")
async def trigger_publish_scheduler():
    publish_scheduler.trigger_immediate_scan()
    return {"success": True, "message": "已触发立即扫描"}


# ==========================================================================
# Publish Tasks (task-based, stored in runtime/publish-tasks/)
# ==========================================================================

class PublishTweetTaskRequest(BaseModel):
    account_id: str = Field(..., min_length=1)
    publish_mode: str = "single-tweet"
    text: str = ""
    media_paths: list[str] | None = None
    is_sensitive: bool = False
    strategy_type: str = "immediate"
    scheduled_time: str | None = None
    title: str | None = None
    description: str | None = None


@app.post("/api/media/upload")
async def upload_media_temp(file: UploadFile = File(...)):
    """Save uploaded media file locally and return the path (no Twitter upload)."""
    import uuid as _uuid
    safe_name = f"{_uuid.uuid4().hex}_{file.filename or 'upload'}"
    file_path = MEDIA_UPLOAD_DIR / safe_name
    data = await file.read()
    with open(file_path, "wb") as f:
        f.write(data)
    return {"success": True, "local_path": str(file_path), "filename": file.filename}


async def _execute_publish_task(task_id: str) -> None:
    """Background coroutine that executes a single publish task."""
    import logging
    import traceback as _tb
    import time as _time

    logger = logging.getLogger("publish_task_executor")
    logger.setLevel(logging.DEBUG)

    logger.info("=" * 60)
    logger.info("[task:%s] ====== 开始执行发布任务 ======", task_id[:8])

    task = publish_task_store.read_task_record(task_id)
    if task is None:
        logger.error("[task:%s] 任务记录不存在!", task_id[:8])
        return

    logger.debug("[task:%s] 任务记录: kind=%s, publish_mode=%s, status=%s",
                 task_id[:8], task.get("kind"), task.get("publish_mode"), task.get("status"))

    publish_task_store.update_task_record(
        task_id,
        status="running",
        started_at=publish_task_store.now_iso(),
    )
    publish_task_store.set_task_progress(task_id, 1, 2)
    logger.debug("[task:%s] 状态已更新为 running", task_id[:8])

    payload = task.get("payload") or {}
    account_id = payload.get("account_id", "")
    content = payload.get("content") or {}

    logger.debug("[task:%s] payload.account_id=%s", task_id[:8], account_id)
    logger.debug("[task:%s] payload.content keys=%s", task_id[:8], list(content.keys()))

    account = get_account_record(account_id)
    if not account:
        err_msg = f"账号不存在: {account_id}"
        logger.error("[task:%s] %s", task_id[:8], err_msg)
        publish_task_store.append_task_log(task_id, f"错误: {err_msg}")
        publish_task_store.update_task_record(
            task_id, status="failed", error=err_msg,
            ended_at=publish_task_store.now_iso(),
        )
        publish_task_store.set_task_progress(task_id, 2, 2)
        return

    account_label = account.get("account") or account_id
    logger.info("[task:%s] 账号: @%s (id=%s, status=%s, platform=%s)",
                task_id[:8], account_label, account_id,
                account.get("status"), account.get("platform"))

    publish_task_store.append_task_log(task_id, f"开始发布推文 → 账号: @{account_label}")

    text_preview = (content.get("text") or "")[:60]
    if text_preview:
        publish_task_store.append_task_log(task_id, f"推文内容: {text_preview}...")
    media_paths = content.get("media_paths") or []
    if media_paths:
        publish_task_store.append_task_log(task_id, f"附带媒体文件: {len(media_paths)} 个")
        for i, mp in enumerate(media_paths):
            logger.debug("[task:%s] 媒体[%d]: %s", task_id[:8], i, mp)
            publish_task_store.append_task_log(task_id, f"  媒体[{i}]: {mp}")

    publish_task_store.append_task_log(task_id, "正在初始化发布会话 (获取ct0, 验证auth_token)...")
    t0 = _time.time()

    try:
        result = await publish_single_tweet(account_id, content)
    except Exception as exc:
        elapsed = _time.time() - t0
        tb_text = _tb.format_exc()
        logger.error("[task:%s] publish_single_tweet 抛出异常 (耗时=%.1fs): %s\n%s",
                     task_id[:8], elapsed, exc, tb_text)
        publish_task_store.append_task_log(task_id, f"发布异常 ({type(exc).__name__}): {exc}")
        publish_task_store.append_task_log(task_id, f"耗时: {elapsed:.1f}s")
        publish_task_store.update_task_record(
            task_id,
            status="failed",
            error=str(exc),
            ended_at=publish_task_store.now_iso(),
        )
        publish_task_store.set_task_progress(task_id, 2, 2)
        return

    elapsed = _time.time() - t0
    logger.info("[task:%s] publish_single_tweet 返回 (耗时=%.1fs): success=%s",
                task_id[:8], elapsed, result.get("success"))

    if result.get("success"):
        tweet_url = result.get("tweet_url", "")
        tweet_id = result.get("tweet_id", "")
        publish_task_store.append_task_log(task_id, f"发布成功! 耗时: {elapsed:.1f}s")
        publish_task_store.append_task_log(task_id, f"推文链接: {tweet_url}")
        publish_task_store.append_task_log(task_id, f"推文ID: {tweet_id}")
        logger.info("[task:%s] 发布成功: tweet_id=%s, url=%s",
                    task_id[:8], tweet_id, tweet_url)
        publish_task_store.update_task_record(
            task_id,
            status="completed",
            ended_at=publish_task_store.now_iso(),
            result_summary={
                "total_count": 1,
                "success_count": 1,
                "failure_count": 0,
                "tweet_id": tweet_id,
                "tweet_url": tweet_url,
            },
        )
        publish_store.create_history_record(
            account_id=account_id,
            tweet_type=task.get("publish_mode", "text"),
            content=content,
            status="success",
            tweet_id=tweet_id,
            tweet_url=tweet_url,
        )
    else:
        error_code = result.get("code", "unknown")
        error_msg = result.get("message", "发布失败")
        retryable = result.get("retryable", False)
        raw_error = result.get("raw_error", "")
        publish_task_store.append_task_log(
            task_id,
            f"发布失败 (耗时: {elapsed:.1f}s, 错误码: {error_code}, 可重试: {retryable})"
        )
        publish_task_store.append_task_log(task_id, f"错误详情: {error_msg}")
        if raw_error and raw_error != error_msg:
            publish_task_store.append_task_log(task_id, f"原始错误: {raw_error[:2000]}")
        tb_text = result.get("traceback", "")
        if tb_text:
            publish_task_store.append_task_log(task_id, f"堆栈: {tb_text[:2000]}")
        # Log the full result dict for maximum diagnostics
        logger.warning("[task:%s] 发布失败完整结果: %s",
                       task_id[:8], json.dumps(result, ensure_ascii=False, default=str)[:3000])
        publish_task_store.update_task_record(
            task_id,
            status="failed",
            error=error_msg,
            ended_at=publish_task_store.now_iso(),
            result_summary={
                "total_count": 1,
                "success_count": 0,
                "failure_count": 1,
                "tweet_id": None,
                "tweet_url": None,
            },
        )
        publish_store.create_history_record(
            account_id=account_id,
            tweet_type=task.get("publish_mode", "text"),
            content=content,
            status="failed",
            error_message=error_msg,
        )

    logger.info("[task:%s] ====== 发布任务执行完毕 ======", task_id[:8])

    publish_task_store.set_task_progress(task_id, 2, 2)
    logger.info("Publish task %s finished", task_id)


@app.post("/api/publish-tasks")
async def create_publish_task(req: PublishTweetTaskRequest):
    tweet_type = "text"
    if req.media_paths:
        first = (req.media_paths[0] or "").lower()
        if first.endswith((".mp4", ".mov", ".avi", ".webm")):
            tweet_type = "video"
        elif first.endswith(".gif"):
            tweet_type = "gif"
        else:
            tweet_type = "image"

    title = (req.title or "").strip() or f"发布推文 — {tweet_type}"
    description = (req.description or "").strip() or "执行 Twitter 推文发布。"

    task = publish_task_store.create_task_record(
        kind=f"publish-{tweet_type}",
        publish_mode="single-tweet",
        title=title,
        description=description,
        payload={
            "account_id": req.account_id,
            "content": {
                "text": req.text,
                "media_paths": req.media_paths,
                "is_sensitive": req.is_sensitive,
            },
            "strategy": {
                "type": req.strategy_type,
                "scheduled_time": req.scheduled_time,
            },
        },
    )

    publish_task_store.append_task_log(task["id"], "任务已创建")

    if req.strategy_type == "immediate":
        _asyncio.create_task(_execute_publish_task(task["id"]))
        publish_task_store.append_task_log(task["id"], "已提交立即执行")
    else:
        publish_task_store.update_task_record(task["id"], status="scheduled")
        publish_task_store.append_task_log(
            task["id"],
            f"已设为定时发布: {req.scheduled_time or '未指定时间'}",
        )

    return {"success": True, "task_id": task["id"], "task": task}


@app.get("/api/publish-tasks")
def list_publish_tasks(limit: int = 200):
    safe_limit = max(min(int(limit), 1000), 1)
    tasks = publish_task_store.list_task_records(limit=safe_limit)
    return {"success": True, "tasks": tasks, "count": len(tasks)}


@app.get("/api/publish-tasks/{task_id}")
def get_publish_task_detail(task_id: str):
    task = publish_task_store.read_task_record(task_id)
    if task is None:
        return {"success": False, "message": "任务不存在", "task": None}
    return {"success": True, "task": task}


@app.delete("/api/publish-tasks/{task_id}")
def delete_publish_task(task_id: str):
    deleted = publish_task_store.delete_task_record(task_id)
    if not deleted:
        return {"success": False, "message": "任务不存在或删除失败"}
    return {"success": True, "message": "任务已删除"}


# ────────────────────────────────────────────
# 数据监控 API
# ────────────────────────────────────────────


@app.get("/api/monitoring/accounts")
def get_monitoring_accounts():
    accounts = list_monitored_accounts()
    items = []
    for acct in accounts:
        acct_id = acct.get("id", "")
        latest = get_latest_snapshot(acct_id)
        items.append({
            **acct,
            "latest_snapshot": latest,
        })
    return {"success": True, "accounts": items, "count": len(items)}


class MonitorAddRequest(BaseModel):
    username: str
    note: str | None = None
    refresh_interval_hours: int = 24
    collect_scope: dict | None = None


@app.post("/api/monitoring/accounts")
def add_monitoring_account(req: MonitorAddRequest):
    username = req.username.strip().lstrip("@")
    if not username:
        return {"success": False, "message": "用户名不能为空"}
    record = add_monitored_account(
        username,
        note=req.note,
        refresh_interval_hours=req.refresh_interval_hours,
        collect_scope=req.collect_scope,
    )
    if record is None:
        return {"success": False, "message": f"@{username} 已在监控列表中"}
    return {"success": True, "account": record, "message": f"已添加 @{username} 到监控列表"}


class MonitorBatchAccountItem(BaseModel):
    username: str
    collect_scope: dict | None = None


class MonitorBatchAddRequest(BaseModel):
    accounts: list[MonitorBatchAccountItem] = []
    usernames: list[str] = []  # legacy compat
    refresh_interval_hours: int = 24
    collect_scope: dict | None = None  # legacy default


@app.post("/api/monitoring/accounts/batch")
def batch_add_monitoring_accounts(req: MonitorBatchAddRequest):
    added = 0
    skipped = 0
    # new format: per-account items
    if req.accounts:
        for item in req.accounts:
            username = item.username.strip().lstrip("@")
            if not username:
                continue
            record = add_monitored_account(
                username,
                refresh_interval_hours=req.refresh_interval_hours,
                collect_scope=item.collect_scope or req.collect_scope,
            )
            if record:
                added += 1
            else:
                skipped += 1
    else:
        # legacy format: flat username list
        for raw in req.usernames:
            username = raw.strip().lstrip("@")
            if not username:
                continue
            record = add_monitored_account(
                username,
                refresh_interval_hours=req.refresh_interval_hours,
                collect_scope=req.collect_scope,
            )
            if record:
                added += 1
            else:
                skipped += 1
    return {
        "success": True,
        "added": added,
        "skipped": skipped,
        "message": f"已添加 {added} 个账号" + (f"，{skipped} 个重复已跳过" if skipped else ""),
    }


@app.delete("/api/monitoring/accounts/{account_id}")
def delete_monitoring_account(account_id: str):
    removed = remove_monitored_account(account_id)
    if not removed:
        return {"success": False, "message": "账号不在监控列表中"}
    return {"success": True, "message": "已从监控列表移除"}


class MonitorUpdateRequest(BaseModel):
    collect_scope: dict | None = None
    refresh_interval_hours: int | None = None


@app.patch("/api/monitoring/accounts/{account_id}")
def update_monitoring_account_settings(account_id: str, req: MonitorUpdateRequest):
    acct = get_monitored_account(account_id)
    if not acct:
        return {"success": False, "message": "账号不在监控列表中"}
    fields: dict = {}
    if req.collect_scope is not None:
        fields["collect_scope"] = req.collect_scope
    if req.refresh_interval_hours is not None:
        fields["refresh_interval_hours"] = max(1, req.refresh_interval_hours)
    if not fields:
        return {"success": True, "message": "无变更"}
    update_monitored_account(account_id, **fields)
    return {"success": True, "message": "设置已更新"}


class MonitorBatchRemoveRequest(BaseModel):
    account_ids: list[str]


@app.post("/api/monitoring/accounts/batch-remove")
def batch_remove_monitoring_accounts(req: MonitorBatchRemoveRequest):
    removed = 0
    for aid in req.account_ids:
        if remove_monitored_account(aid):
            removed += 1
    return {"success": True, "removed": removed, "message": f"已移除 {removed} 个账号"}


@app.get("/api/monitoring/accounts/{account_id}/dashboard")
def get_monitoring_dashboard(account_id: str, source: str = "regular"):
    acct = get_monitored_account(account_id)
    if not acct:
        return {"success": False, "message": "账号不在监控列表中"}

    snapshots = get_account_snapshots(account_id, limit=90)
    if source in ("regular", "highlights"):
        tweets = get_tweet_metrics_by_source(account_id, source, limit=50)
    else:
        tweets = get_tweet_metrics(account_id, limit=50)
    latest = snapshots[-1] if snapshots else None

    followers_history = [
        {"date": s.get("captured_at", ""), "followers": s.get("followers_count", 0)}
        for s in snapshots
    ]

    return {
        "success": True,
        "account": {
            "id": acct.get("id"),
            "username": acct.get("username"),
        },
        "overview": latest or {},
        "followers_history": followers_history,
        "tweets": tweets,
        "source": source,
    }


# ── Scrape endpoints ──

class MonitorScrapeRequest(BaseModel):
    account_ids: list[str]


@app.post("/api/monitoring/accounts/{account_id}/scrape")
def scrape_single_monitoring_account(account_id: str):
    from twitter_monitor_scraper import scrape_account as _scrape

    acct = get_monitored_account(account_id)
    if not acct:
        return {"success": False, "message": "账号不在监控列表中"}

    result = _scrape(acct)

    if result.get("success") and result.get("profile"):
        save_account_snapshot(account_id, result["profile"])
        if result.get("regular_tweets"):
            save_tweet_metrics(account_id, result["regular_tweets"], source="regular")
        if result.get("highlight_tweets"):
            save_tweet_metrics(account_id, result["highlight_tweets"], source="highlights")
        update_monitored_account(
            account_id,
            last_scraped_at=__import__("datetime").datetime.now().isoformat(timespec="seconds"),
        )

    return {
        "success": result.get("success", False),
        "error": result.get("error"),
        "stats": result.get("stats", {}),
    }


@app.post("/api/monitoring/scrape-batch")
def scrape_batch_monitoring_accounts(req: MonitorScrapeRequest):
    from twitter_monitor_scraper import scrape_account as _scrape

    results = []
    for aid in req.account_ids:
        acct = get_monitored_account(aid)
        if not acct:
            results.append({"account_id": aid, "success": False, "error": "not_found"})
            continue

        result = _scrape(acct)
        if result.get("success") and result.get("profile"):
            save_account_snapshot(aid, result["profile"])
            if result.get("regular_tweets"):
                save_tweet_metrics(aid, result["regular_tweets"], source="regular")
            if result.get("highlight_tweets"):
                save_tweet_metrics(aid, result["highlight_tweets"], source="highlights")
            update_monitored_account(
                aid,
                last_scraped_at=__import__("datetime").datetime.now().isoformat(timespec="seconds"),
            )

        results.append({
            "account_id": aid,
            "username": acct.get("username", ""),
            "success": result.get("success", False),
            "error": result.get("error"),
            "stats": result.get("stats", {}),
        })

    succeeded = sum(1 for r in results if r["success"])
    return {
        "success": True,
        "results": results,
        "summary": f"成功 {succeeded}/{len(req.account_ids)}",
    }

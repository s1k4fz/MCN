import csv
import json
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

import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from bilibili_crawler import BilibiliCrawler
from longmao_parser import normalize_platform_type, parse_content_data
from main import (
    read_author_meta,
)
from task_store import (
    append_task_log,
    create_task_record,
    delete_task_record,
    list_task_records,
    read_task_record,
    update_task_record,
)

BASE_DIR = Path(__file__).resolve().parent
MATERIALS_ROOT = BASE_DIR / "materials"
TASK_WORKER_SCRIPT = BASE_DIR / "task_worker.py"
TASK_WORKER_LOG_DIR = BASE_DIR / "runtime" / "worker-logs"
TASK_WORKER_LOG_DIR.mkdir(parents=True, exist_ok=True)

PLATFORM_DIRS = {
    "bilibili": "哔哩哔哩",
    "xiaohongshu": "小红书",
    "douyin": "抖音",
}
DEFAULT_SECOND_LEVEL_DIRS = ("单个作品", "指定作者")
BILIBILI_UNDOWNLOADED_AUTHOR_DIR = "已采集未下载作者"
BILIBILI_EXTRA_SECOND_LEVEL_DIRS = (BILIBILI_UNDOWNLOADED_AUTHOR_DIR,)
BILIBILI_AUTHOR_TREE_DIRS = {"指定作者", BILIBILI_UNDOWNLOADED_AUTHOR_DIR}
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


def ensure_material_tree() -> None:
    for platform_key, platform_name in PLATFORM_DIRS.items():
        for second in get_second_level_dirs(platform_key):
            (MATERIALS_ROOT / platform_name / second).mkdir(parents=True, exist_ok=True)


def get_second_level_dirs(platform_key: str) -> tuple[str, ...]:
    if platform_key == "bilibili":
        return (*DEFAULT_SECOND_LEVEL_DIRS, *BILIBILI_EXTRA_SECOND_LEVEL_DIRS)
    return DEFAULT_SECOND_LEVEL_DIRS


def is_bilibili_author_tree(platform_key: str, second_dir_name: str) -> bool:
    return platform_key == "bilibili" and second_dir_name in BILIBILI_AUTHOR_TREE_DIRS


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

    # materials/<一级目录>/<二级目录> 为系统默认目录，禁止删除。
    if depth <= 2:
        return False, "禁止删除系统默认目录（一级目录和二级目录）"

    # 允许删除三级目录（包括“作者目录”与“特定作品目录”）。
    if depth == 3 and target.is_dir():
        return True, ""

    # 允许删除普通三级目录下文件。
    if depth == 4 and target.is_file():
        return True, ""

    # 允许删除 B站作者目录下的作品目录（第4层目录）。
    if (
        depth == 4
        and target.is_dir()
        and platform_name == PLATFORM_DIRS["bilibili"]
        and second_name in BILIBILI_AUTHOR_TREE_DIRS
    ):
        return True, ""

    # 允许删除 B站作者作品目录下文件（第5层文件）。
    if (
        depth == 5
        and target.is_file()
        and platform_name == PLATFORM_DIRS["bilibili"]
        and second_name in BILIBILI_AUTHOR_TREE_DIRS
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
    task_logs = task.get("logs", []) if isinstance(task.get("logs"), list) else []
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
    if platform != "bilibili":
        return {
            "success": False,
            "message": "当前仅支持 B站 指定作者采集",
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


@app.get("/api/materials/tree")
def get_material_tree() -> dict[str, Any]:
    ensure_material_tree()
    roots = []

    for platform_key, platform_display_name in PLATFORM_DIRS.items():
        root_dir = MATERIALS_ROOT / platform_display_name
        second_children = []
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

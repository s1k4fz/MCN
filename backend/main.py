import csv
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import requests

from bilibili_crawler import BilibiliCrawler
from longmao_parser import parse_content_data


CollectMode = Literal["data-only", "collect-download"]
AUTHOR_META_FILENAME = "_author_meta.json"
DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


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


def save_to_csv(data_list: list[dict[str, Any]], filename: Path) -> None:
    """
    通用保存函数：将字典列表保存为 CSV 文件 (Excel 可打开)
    """
    if not data_list:
        return

    clean_data: list[dict[str, Any]] = []
    for item in data_list:
        row = dict(item)
        if "files" in row:
            del row["files"]
        if "stats" in row and isinstance(row["stats"], dict):
            for k, v in row["stats"].items():
                row[f"数据_{k}"] = v
            del row["stats"]
        if "author" in row and isinstance(row["author"], dict):
            row["作者名"] = row["author"].get("name")
            del row["author"]
        clean_data.append(row)

    headers = list(clean_data[0].keys())
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(clean_data)


def save_single_row_csv(row: dict[str, Any], output_path: Path) -> None:
    headers = list(row.keys())
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerow(row)


def read_single_row_csv(csv_path: Path) -> dict[str, str]:
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            return {str(k): str(v) for k, v in row.items() if k is not None}
    return {}


def read_author_meta(author_dir: Path) -> dict[str, Any] | None:
    meta_file = author_dir / AUTHOR_META_FILENAME
    if not meta_file.exists():
        return None
    try:
        with open(meta_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        return None
    return None


def write_author_meta(author_dir: Path, uid: str, author_name: str) -> None:
    meta_file = author_dir / AUTHOR_META_FILENAME
    payload = {
        "uid": str(uid),
        "author_name": str(author_name),
    }
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def find_author_dir_by_uid(root_dir: Path, uid: str) -> tuple[Path | None, dict[str, Any] | None]:
    uid = str(uid).strip()
    if not root_dir.exists():
        return None, None

    # 1) 优先通过 meta 匹配
    for entry in root_dir.iterdir():
        if not entry.is_dir():
            continue
        meta = read_author_meta(entry)
        if isinstance(meta, dict) and str(meta.get("uid", "")).strip() == uid:
            return entry, meta

    # 2) 兼容旧目录：目录名直接是 uid
    legacy_dir = root_dir / uid
    if legacy_dir.exists() and legacy_dir.is_dir():
        meta = {"uid": uid, "author_name": uid}
        return legacy_dir, meta

    return None, None


def resolve_author_dir(root_dir: Path, uid: str, author_name: str) -> tuple[Path, dict[str, Any]]:
    root_dir.mkdir(parents=True, exist_ok=True)
    existing_dir, existing_meta = find_author_dir_by_uid(root_dir, uid)
    if existing_dir is not None:
        normalized_name = str(author_name).strip() or str(uid)
        write_author_meta(existing_dir, uid, normalized_name)
        return existing_dir, {
            "uid": str(uid),
            "author_name": normalized_name,
        }

    folder_name = sanitize_folder_name(author_name or uid)
    target_dir = make_unique_dir(root_dir, folder_name)
    target_dir.mkdir(parents=True, exist_ok=True)
    write_author_meta(target_dir, uid, author_name or uid)
    return target_dir, {
        "uid": str(uid),
        "author_name": str(author_name or uid),
    }


def collect_single_video_media(
    video_url: str,
    output_dir: Path,
    bilibili_crawler: BilibiliCrawler | None = None,
) -> dict[str, Any]:
    print(f"[*] 开始下载视频媒体: {video_url}")
    parsed = parse_content_data(video_url)
    if not parsed.get("ok"):
        print(f"❌ 解析失败: {parsed.get('error')}")
        return {
            "ok": False,
            "error": parsed.get("error", "解析失败"),
            "downloaded_files": {},
        }

    extracted = parsed.get("extracted") or {}
    bilibili_media_plan: dict[str, Any] | None = None
    if parsed.get("platform_type") == "bilibili":
        crawler = bilibili_crawler or BilibiliCrawler()
        best_media = crawler.get_best_media_urls_by_url(video_url)
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
                "   🎯 [B站] 已切换为最高画质下载:"
                f" source={best_media.get('source')}"
                f" qn={best_media.get('quality_id')}"
                f" label={best_media.get('quality_label') or '-'}"
                f" resolution={best_media.get('width')}x{best_media.get('height')}"
            )
            if best_media.get("quality_warning"):
                print(f"   ⚠️ [B站] 清晰度提示: {best_media.get('quality_warning')}")
        else:
            print("   ⚠️ [B站] 最高画质解析失败，回退到解析器返回直链")
            if isinstance(getattr(crawler, "last_error", None), dict):
                print(f"      - crawler_error: {crawler.last_error}")

    print(
        "   ✅ 解析成功:"
        f" type={extracted.get('type')}"
        f" videos={len(extracted.get('videos') or [])}"
        f" images={len(extracted.get('images') or [])}"
        f" cover={'yes' if extracted.get('cover') else 'no'}"
        f" audio={'yes' if extracted.get('audio') else 'no'}"
    )
    downloaded_files: dict[str, Any] = {
        "cover": None,
        "videos": [],
        "images": [],
        "audio": None,
    }
    download_failures: list[dict[str, Any]] = []
    downloaded_video_paths: list[Path] = []
    downloaded_audio_path: Path | None = None

    cover_url = extracted.get("cover")
    if isinstance(cover_url, str) and cover_url.strip():
        cover_ext = guess_extension(cover_url, ".jpg")
        cover_result = download_to_file(
            cover_url, output_dir / f"cover{cover_ext}", purpose="cover"
        )
        if cover_result["ok"]:
            downloaded_files["cover"] = Path(cover_result["path"]).name
        else:
            download_failures.append(
                {
                    "kind": "cover",
                    "url": cover_url,
                    "error": cover_result.get("error"),
                    "status_code": cover_result.get("status_code"),
                }
            )

    videos = extracted.get("videos", []) if isinstance(extracted.get("videos"), list) else []
    for index, media_url in enumerate(videos, start=1):
        if not isinstance(media_url, str) or not media_url.strip():
            continue
        video_ext = guess_extension(media_url, ".mp4")
        video_result = download_to_file(
            media_url, output_dir / f"video_{index}{video_ext}", purpose=f"video_{index}"
        )
        if video_result["ok"]:
            video_path = Path(video_result["path"])
            downloaded_video_paths.append(video_path)
            downloaded_files["videos"].append(video_path.name)
        else:
            download_failures.append(
                {
                    "kind": "video",
                    "url": media_url,
                    "index": index,
                    "error": video_result.get("error"),
                    "status_code": video_result.get("status_code"),
                }
            )

    images = extracted.get("images", []) if isinstance(extracted.get("images"), list) else []
    for index, image_url in enumerate(images, start=1):
        if not isinstance(image_url, str) or not image_url.strip():
            continue
        image_ext = guess_extension(image_url, ".jpg")
        image_result = download_to_file(
            image_url, output_dir / f"image_{index}{image_ext}", purpose=f"image_{index}"
        )
        if image_result["ok"]:
            downloaded_files["images"].append(Path(image_result["path"]).name)
        else:
            download_failures.append(
                {
                    "kind": "image",
                    "url": image_url,
                    "index": index,
                    "error": image_result.get("error"),
                    "status_code": image_result.get("status_code"),
                }
            )

    audio_url = extracted.get("audio")
    if isinstance(audio_url, str) and audio_url.strip():
        audio_ext = guess_extension(audio_url, ".mp3")
        audio_result = download_to_file(
            audio_url, output_dir / f"audio{audio_ext}", purpose="audio"
        )
        if audio_result["ok"]:
            downloaded_audio_path = Path(audio_result["path"])
            downloaded_files["audio"] = downloaded_audio_path.name
        else:
            download_failures.append(
                {
                    "kind": "audio",
                    "url": audio_url,
                    "error": audio_result.get("error"),
                    "status_code": audio_result.get("status_code"),
                }
            )

    # B站高画质通常是 DASH 分离流（m4s），这里自动封装为 mp4 便于直接使用。
    if (
        parsed.get("platform_type") == "bilibili"
        and downloaded_video_paths
        and downloaded_audio_path is not None
    ):
        first_video_path = downloaded_video_paths[0]
        if (
            first_video_path.suffix.lower() == ".m4s"
            and downloaded_audio_path.suffix.lower() == ".m4s"
        ):
            merged_path = output_dir / "video_1.mp4"
            merge_result = merge_dash_streams_to_mp4(
                first_video_path, downloaded_audio_path, merged_path
            )
            if merge_result.get("ok"):
                downloaded_files["videos"][0] = merged_path.name
                downloaded_files["merged_video"] = merged_path.name
            else:
                print(f"   ❌ DASH 合并失败: {merge_result.get('error')}")
                if merge_result.get("stderr_preview"):
                    print(f"      - ffmpeg stderr: {merge_result.get('stderr_preview')}")
                download_failures.append(
                    {
                        "kind": "merge",
                        "error": merge_result.get("error"),
                        "stderr_preview": merge_result.get("stderr_preview"),
                        "video_file": first_video_path.name,
                        "audio_file": downloaded_audio_path.name,
                    }
                )

    metadata = {
        "source_url": video_url,
        "collected_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "content": extracted,
        "raw_info": parsed.get("raw_info"),
        "downloaded_files": downloaded_files,
        "download_failures": download_failures,
        "bilibili_media_plan": bilibili_media_plan,
    }
    with open(output_dir / "data.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    expected_video_count = len(videos)
    downloaded_video_count = len(downloaded_files["videos"])
    if expected_video_count > 0 and downloaded_video_count == 0:
        print(
            f"❌ 视频下载失败: 解析到 {expected_video_count} 个视频直链，但下载成功 0 个"
        )
        return {
            "ok": False,
            "error": "解析到视频直链，但视频下载全部失败",
            "downloaded_files": downloaded_files,
            "download_failures": download_failures,
        }

    if download_failures:
        print(f"⚠️ 存在部分资源下载失败: failures={len(download_failures)}")

    return {
        "ok": True,
        "downloaded_files": downloaded_files,
        "download_failures": download_failures,
    }


def collect_bili_author_materials(
    uid: str,
    undownloaded_root: Path,
    collect_mode: CollectMode = "collect-download",
    downloaded_root: Path | None = None,
) -> dict[str, Any]:
    """
    作者采集入口（可复用于 API）：
    - data-only: 仅采集并保存每条视频 CSV 到 `undownloaded_root/<uid>/<video>/`
    - collect-download: 采集并下载视频源文件到 `downloaded_root/<uid>/<video>/`
    """
    uid = str(uid).strip()
    if not uid:
        return {"ok": False, "uid": uid, "error": "UID 不能为空", "results": []}

    print(f"\n📺 [B站模式] 初始化作者采集，UID={uid}，模式={collect_mode}")
    crawler = BilibiliCrawler()
    videos = crawler.get_all_videos(uid)
    if not videos:
        crawler_error = getattr(crawler, "last_error", None)
        detailed_error = "未找到视频或 UID 错误"
        if isinstance(crawler_error, dict):
            message = crawler_error.get("message")
            stage = crawler_error.get("stage")
            code = crawler_error.get("code")
            if code is not None:
                detailed_error = f"{message} (stage={stage}, code={code})"
            else:
                detailed_error = f"{message} (stage={stage})"
            print(f"❌ 作者采集失败详情: {detailed_error}")
            print(f"   - 调试信息: {crawler_error}")
        return {
            "ok": False,
            "uid": uid,
            "error": detailed_error,
            "crawler_error": crawler_error,
            "results": [],
        }

    author_name = str(videos[0].get("author_name") or uid).strip() or uid

    pending_author_dir, author_meta = resolve_author_dir(
        undownloaded_root, uid, author_name
    )

    downloaded_author_dir: Path | None = None
    if collect_mode == "collect-download":
        if downloaded_root is None:
            return {
                "ok": False,
                "uid": uid,
                "error": "collect-download 模式需要 downloaded_root",
                "results": [],
            }
        downloaded_author_dir, _ = resolve_author_dir(
            downloaded_root, uid, author_name
        )

    all_results: list[dict[str, Any]] = []

    for index, video in enumerate(videos, start=1):
        raw_title = str(video.get("title") or f"视频_{index}")
        safe_title = sanitize_folder_name(raw_title)
        video_link = str(video.get("link") or "")

        if collect_mode == "data-only":
            video_dir = make_unique_dir(pending_author_dir, safe_title)
            video_dir.mkdir(parents=True, exist_ok=True)
            csv_path = video_dir / "video_data.csv"
            save_single_row_csv(video, csv_path)
            all_results.append(
                {
                    "success": True,
                    "mode": collect_mode,
                    "uid": uid,
                    "title": raw_title,
                    "video_folder": video_dir.name,
                    "csv_file": csv_path.name,
                }
            )
            continue

        # collect-download
        if downloaded_author_dir is None:
            all_results.append(
                {
                    "success": False,
                    "mode": collect_mode,
                    "uid": uid,
                    "title": raw_title,
                    "error": "下载目录未初始化",
                }
            )
            continue

        video_dir = make_unique_dir(downloaded_author_dir, safe_title)
        video_dir.mkdir(parents=True, exist_ok=True)
        csv_path = video_dir / "video_data.csv"
        save_single_row_csv(video, csv_path)

        media_result = collect_single_video_media(
            video_link,
            video_dir,
            bilibili_crawler=crawler,
        )
        if media_result.get("ok"):
            all_results.append(
                {
                    "success": True,
                    "mode": collect_mode,
                    "uid": uid,
                    "title": raw_title,
                    "video_folder": video_dir.name,
                    "csv_file": csv_path.name,
                    "downloaded_files": media_result.get("downloaded_files", {}),
                }
            )
        else:
            all_results.append(
                {
                    "success": False,
                    "mode": collect_mode,
                    "uid": uid,
                    "title": raw_title,
                    "video_folder": video_dir.name,
                    "csv_file": csv_path.name,
                    "error": media_result.get("error", "视频源文件下载失败"),
                }
            )

    success_count = sum(1 for item in all_results if item.get("success"))
    return {
        "ok": success_count > 0,
        "uid": uid,
        "author_name": author_meta.get("author_name"),
        "collect_mode": collect_mode,
        "total_count": len(all_results),
        "success_count": success_count,
        "failure_count": len(all_results) - success_count,
        "results": all_results,
    }


def selective_download_bili_author_videos(
    uid: str,
    undownloaded_root: Path,
    downloaded_root: Path,
    selected_video_folders: list[str],
) -> dict[str, Any]:
    uid = str(uid).strip()
    print(f"\n📥 [选择性下载] 开始处理作者 UID={uid}")
    crawler = BilibiliCrawler()
    pending_author_dir, pending_meta = find_author_dir_by_uid(undownloaded_root, uid)
    if pending_author_dir is None:
        print("❌ 未找到对应作者的待下载目录")
        return {
            "ok": False,
            "uid": uid,
            "total_count": 0,
            "success_count": 0,
            "failure_count": 0,
            "results": [],
            "error": "未找到对应作者的待下载目录",
        }

    author_name = str(
        (pending_meta or {}).get("author_name")
        or (pending_meta or {}).get("uid")
        or uid
    )
    print(f"   - 作者名称: {author_name}")
    print(f"   - 待下载目录: {pending_author_dir}")
    downloaded_author_dir, _ = resolve_author_dir(downloaded_root, uid, author_name)
    print(f"   - 下载输出目录: {downloaded_author_dir}")

    results: list[dict[str, Any]] = []
    selected = [name.strip() for name in selected_video_folders if name.strip()]
    print(f"   - 本次勾选作品数量: {len(selected)}")

    for folder_name in selected:
        print(f"\n   ▶️ 处理勾选作品: {folder_name}")
        source_video_dir = pending_author_dir / folder_name
        if not source_video_dir.exists() or not source_video_dir.is_dir():
            print("      ❌ 源目录不存在")
            results.append(
                {
                    "success": False,
                    "uid": uid,
                    "video_folder": folder_name,
                    "error": "源目录不存在",
                }
            )
            continue

        csv_files = sorted(source_video_dir.glob("*.csv"))
        if not csv_files:
            print("      ❌ 未找到视频数据 CSV")
            results.append(
                {
                    "success": False,
                    "uid": uid,
                    "video_folder": folder_name,
                    "error": "未找到视频数据 CSV",
                }
            )
            continue

        csv_file = csv_files[0]
        row = read_single_row_csv(csv_file)
        raw_title = row.get("title") or folder_name
        safe_title = sanitize_folder_name(raw_title)
        video_link = row.get("link", "").strip()
        print(f"      - CSV: {csv_file.name}")
        print(f"      - 视频标题: {raw_title}")
        print(f"      - 视频链接: {video_link}")

        target_video_dir = make_unique_dir(downloaded_author_dir, safe_title)
        target_video_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(csv_file, target_video_dir / csv_file.name)

        if not video_link:
            print("      ❌ CSV 中缺少 link 字段")
            results.append(
                {
                    "success": False,
                    "uid": uid,
                    "video_folder": folder_name,
                    "target_folder": target_video_dir.name,
                    "error": "CSV 中缺少视频链接(link)",
                }
            )
            continue

        media_result = collect_single_video_media(
            video_link,
            target_video_dir,
            bilibili_crawler=crawler,
        )
        if media_result.get("ok"):
            print("      ✅ 媒体下载成功")
            results.append(
                {
                    "success": True,
                    "uid": uid,
                    "video_folder": folder_name,
                    "target_folder": target_video_dir.name,
                    "downloaded_files": media_result.get("downloaded_files", {}),
                }
            )
        else:
            print(f"      ❌ 媒体下载失败: {media_result.get('error')}")
            results.append(
                {
                    "success": False,
                    "uid": uid,
                    "video_folder": folder_name,
                    "target_folder": target_video_dir.name,
                    "error": media_result.get("error", "下载失败"),
                }
            )

    success_count = sum(1 for item in results if item.get("success"))
    print(
        f"\n📦 [选择性下载] 结束: 总计 {len(results)}，"
        f"成功 {success_count}，失败 {len(results) - success_count}"
    )
    return {
        "ok": success_count > 0,
        "uid": uid,
        "author_name": author_name,
        "total_count": len(results),
        "success_count": success_count,
        "failure_count": len(results) - success_count,
        "results": results,
    }


def run_bili_task(uid: str, collect_mode: CollectMode = "collect-download") -> None:
    """
    兼容原入口：
    默认仍为“采集并下载”。
    """
    timestamp = int(time.time())
    workspace_dir = Path.cwd() / f"B站作者任务_{uid}_{timestamp}"
    undownloaded_root = workspace_dir / "已采集未下载作者"
    downloaded_root = workspace_dir / "指定作者"

    result = collect_bili_author_materials(
        uid=uid,
        undownloaded_root=undownloaded_root,
        collect_mode=collect_mode,
        downloaded_root=downloaded_root,
    )
    if not result.get("ok"):
        print(f"❌ 任务失败: {result.get('error', '未知错误')}")
        return

    print(
        f"✅ 任务完成：总计 {result.get('total_count')}，"
        f"成功 {result.get('success_count')}，失败 {result.get('failure_count')}"
    )
    print(f"📁 输出目录: {workspace_dir}")


if __name__ == "__main__":
    print("=" * 50)
    print("      🔥 全能媒体采集下载器 (稳定版) 🔥")
    print("=" * 50)
    print("1. Bilibili (下载UP主所有视频)")
    print("2. 小红书   (暂未开放/维护中)")
    print("=" * 50)

    choice = input("请选择平台 (输入 1): ").strip()

    if choice == "1":
        user_id = input("请输入 B站用户 UID: ").strip()
        if user_id:
            run_bili_task(user_id, collect_mode="collect-download")
        else:
            print("❌ UID 不能为空")
    elif choice == "2":
        print("🚧 小红书模块正在进行加密算法攻坚，暂时关闭。")
        print("   (X-s 签名更新频繁，为了程序稳定性暂移除)")
    else:
        print("❌ 输入无效，程序退出。")
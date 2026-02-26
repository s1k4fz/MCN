import sys
import traceback
from typing import Any

from app import (
    BILIBILI_UNDOWNLOADED_AUTHOR_DIR,
    MATERIALS_ROOT,
    PLATFORM_DIRS,
    collect_single_work,
    ensure_material_tree,
)
from longmao_parser import normalize_platform_type
from main import collect_bili_author_materials, collect_douyin_author_materials, collect_xhs_author_materials, selective_download_bili_author_videos
from task_store import (
    append_task_log,
    now_iso,
    read_task_record,
    set_task_progress,
    update_task_record,
)


def _normalize_links(raw_links: Any) -> list[str]:
    if not isinstance(raw_links, list):
        return []
    return [str(item).strip() for item in raw_links if str(item).strip()]


def _run_collect_single_work_task(task_id: str, task: dict[str, Any]) -> None:
    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
    links = _normalize_links(payload.get("links"))
    title = str(payload.get("title") or "").strip() or None
    description = str(payload.get("description") or "").strip() or None
    total = max(len(links) * 2, 1)
    set_task_progress(task_id, 0, total)

    if not links:
        append_task_log(task_id, "未提供有效作品链接，任务终止")
        update_task_record(
            task_id,
            status="failed",
            error="至少提供一个有效作品链接",
            ended_at=now_iso(),
        )
        set_task_progress(task_id, total, total)
        return

    append_task_log(task_id, f"开始执行指定作品采集，链接数: {len(links)}")
    results: list[dict[str, Any]] = []

    for index, link in enumerate(links, start=1):
        set_task_progress(task_id, (index - 1) * 2 + 1, total)
        append_task_log(task_id, f"正在采集第 {index}/{len(links)} 条链接")
        try:
            result = collect_single_work(link, title, description)
        except Exception as e:
            append_task_log(task_id, f"第 {index} 条采集异常: {e}")
            append_task_log(task_id, traceback.format_exc(limit=2))
            result = {
                "url": link,
                "success": False,
                "error": f"采集异常: {e}",
            }

        results.append(result)
        if result.get("success"):
            append_task_log(
                task_id,
                f"第 {index} 条采集成功: {result.get('title') or result.get('folder_name') or link}",
            )
        else:
            append_task_log(task_id, f"第 {index} 条采集失败: {result.get('error') or '未知错误'}")

        set_task_progress(task_id, index * 2, total)

    success_count = sum(1 for item in results if item.get("success"))
    failure_count = len(results) - success_count
    final_status = "completed" if failure_count == 0 else "failed"
    final_error = None
    if failure_count > 0:
        final_error = f"部分链接采集失败（成功 {success_count} / 失败 {failure_count}）"

    append_task_log(
        task_id,
        f"任务结束: 成功 {success_count} / 失败 {failure_count}",
    )
    update_task_record(
        task_id,
        status=final_status,
        error=final_error,
        ended_at=now_iso(),
        results=results,
        result_summary={
            "total_count": len(results),
            "success_count": success_count,
            "failure_count": failure_count,
        },
    )
    set_task_progress(task_id, total, total)


def _run_collect_author_task(task_id: str, task: dict[str, Any]) -> None:
    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
    platform = normalize_platform_type(payload.get("platform"))
    collect_action = str(payload.get("collect_action") or "").strip().lower()
    uids = _normalize_links(payload.get("uids"))
    total = max(len(uids) * 2, 1)
    set_task_progress(task_id, 0, total)

    if platform not in {"bilibili", "douyin", "xiaohongshu"}:
        append_task_log(task_id, f"不支持的平台: {platform}")
        update_task_record(
            task_id,
            status="failed",
            error=f"不支持的平台: {platform}",
            ended_at=now_iso(),
        )
        set_task_progress(task_id, total, total)
        return

    if collect_action not in {"data-only", "collect-download"}:
        append_task_log(task_id, "collect_action 非法")
        update_task_record(
            task_id,
            status="failed",
            error="collect_action 仅支持 data-only 或 collect-download",
            ended_at=now_iso(),
        )
        set_task_progress(task_id, total, total)
        return

    if not uids:
        append_task_log(task_id, "未提供有效作者 UID")
        update_task_record(
            task_id,
            status="failed",
            error="至少提供一个有效作者 UID",
            ended_at=now_iso(),
        )
        set_task_progress(task_id, total, total)
        return

    ensure_material_tree()
    platform_display = PLATFORM_DIRS.get(platform, platform)
    platform_root = MATERIALS_ROOT / platform_display
    undownloaded_root = platform_root / "已采集未下载作者"
    downloaded_root = platform_root / "指定作者"
    append_task_log(task_id, f"开始执行指定作者采集，UID 数: {len(uids)}")

    uid_results: list[dict[str, Any]] = []
    for index, uid in enumerate(uids, start=1):
        set_task_progress(task_id, (index - 1) * 2 + 1, total)
        append_task_log(task_id, f"正在处理 UID {uid} ({index}/{len(uids)})")
        try:
            if platform == "bilibili":
                author_result = collect_bili_author_materials(
                    uid=uid,
                    undownloaded_root=undownloaded_root,
                    collect_mode=collect_action,  # type: ignore[arg-type]
                    downloaded_root=downloaded_root,
                )
            elif platform == "douyin":
                author_result = collect_douyin_author_materials(
                    author_input=uid,
                    undownloaded_root=undownloaded_root,
                    collect_mode=collect_action,  # type: ignore[arg-type]
                    downloaded_root=downloaded_root,
                )
            elif platform == "xiaohongshu":
                author_result = collect_xhs_author_materials(
                    author_input=uid,
                    undownloaded_root=undownloaded_root,
                    collect_mode=collect_action,  # type: ignore[arg-type]
                    downloaded_root=downloaded_root,
                )
            else:
                author_result = {"ok": False, "error": f"不支持的平台: {platform}"}

            normalized_item = {
                "success": bool(author_result.get("ok")),
                "uid": uid,
                "collect_action": collect_action,
                "platform": platform,
                "platform_display_name": platform_display,
                "error": author_result.get("error"),
                "crawler_error": author_result.get("crawler_error"),
                "total_count": author_result.get("total_count", 0),
                "success_count": author_result.get("success_count", 0),
                "failure_count": author_result.get("failure_count", 0),
                "details": author_result.get("results", []),
            }
            uid_results.append(normalized_item)
            if normalized_item["success"]:
                append_task_log(
                    task_id,
                    f"UID {uid} 处理成功（成功 {normalized_item['success_count']} 条）",
                )
            else:
                append_task_log(task_id, f"UID {uid} 处理失败: {normalized_item.get('error')}")
        except Exception as e:
            append_task_log(task_id, f"UID {uid} 处理异常: {e}")
            append_task_log(task_id, traceback.format_exc(limit=2))
            uid_results.append(
                {
                    "success": False,
                    "uid": uid,
                    "collect_action": collect_action,
                    "platform": platform,
                    "platform_display_name": platform_display,
                    "error": f"执行异常: {e}",
                    "total_count": 0,
                    "success_count": 0,
                    "failure_count": 0,
                    "details": [],
                }
            )

        set_task_progress(task_id, index * 2, total)

    success_count = sum(1 for item in uid_results if item.get("success"))
    failure_count = len(uid_results) - success_count
    final_status = "completed" if failure_count == 0 else "failed"
    final_error = None
    if failure_count > 0:
        final_error = f"部分作者采集失败（成功 {success_count} / 失败 {failure_count}）"

    append_task_log(task_id, f"任务结束: 成功 {success_count} / 失败 {failure_count}")
    update_task_record(
        task_id,
        status=final_status,
        error=final_error,
        ended_at=now_iso(),
        results=uid_results,
        result_summary={
            "total_count": len(uid_results),
            "success_count": success_count,
            "failure_count": failure_count,
        },
    )
    set_task_progress(task_id, total, total)


def _run_selective_download_task(task_id: str, task: dict[str, Any]) -> None:
    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
    platform = normalize_platform_type(payload.get("platform"))
    author_uid = str(payload.get("author_uid") or "").strip()
    selected_video_folders = _normalize_links(payload.get("selected_video_folders"))
    total = max(len(selected_video_folders) * 2, 1)
    set_task_progress(task_id, 0, total)

    if platform != "bilibili":
        append_task_log(task_id, "当前仅支持 B站 选择性下载")
        update_task_record(
            task_id,
            status="failed",
            error="当前仅支持 B站 选择性下载",
            ended_at=now_iso(),
        )
        set_task_progress(task_id, total, total)
        return

    if not author_uid or not selected_video_folders:
        append_task_log(task_id, "author_uid 或 selected_video_folders 为空")
        update_task_record(
            task_id,
            status="failed",
            error="author_uid 和 selected_video_folders 均不能为空",
            ended_at=now_iso(),
        )
        set_task_progress(task_id, total, total)
        return

    ensure_material_tree()
    bilibili_root = MATERIALS_ROOT / PLATFORM_DIRS["bilibili"]
    undownloaded_root = bilibili_root / BILIBILI_UNDOWNLOADED_AUTHOR_DIR
    downloaded_root = bilibili_root / "指定作者"

    append_task_log(
        task_id,
        f"开始执行选择性下载，作者 UID={author_uid}，作品数={len(selected_video_folders)}",
    )
    set_task_progress(task_id, 1, total)

    try:
        result = selective_download_bili_author_videos(
            uid=author_uid,
            undownloaded_root=undownloaded_root,
            downloaded_root=downloaded_root,
            selected_video_folders=selected_video_folders,
        )
    except Exception as e:
        append_task_log(task_id, f"选择性下载异常: {e}")
        append_task_log(task_id, traceback.format_exc(limit=3))
        update_task_record(
            task_id,
            status="failed",
            error=f"选择性下载异常: {e}",
            ended_at=now_iso(),
        )
        set_task_progress(task_id, total, total)
        return

    success_count = int(result.get("success_count", 0) or 0)
    failure_count = int(result.get("failure_count", 0) or 0)
    final_status = "completed" if failure_count == 0 and result.get("ok") else "failed"
    final_error = result.get("error")
    if final_status == "failed" and not final_error:
        final_error = f"部分下载失败（成功 {success_count} / 失败 {failure_count}）"

    append_task_log(
        task_id,
        f"选择性下载结束: 成功 {success_count} / 失败 {failure_count}",
    )
    update_task_record(
        task_id,
        status=final_status,
        error=final_error,
        ended_at=now_iso(),
        results=result.get("results", []),
        result_summary={
            "total_count": int(result.get("total_count", len(selected_video_folders)) or 0),
            "success_count": success_count,
            "failure_count": failure_count,
        },
    )
    set_task_progress(task_id, total, total)


def run_task(task_id: str) -> int:
    task = read_task_record(task_id)
    if task is None:
        return 1

    update_task_record(
        task_id,
        status="running",
        started_at=now_iso(),
        error=None,
    )
    append_task_log(task_id, "后台任务已启动")

    try:
        kind = str(task.get("kind") or "")
        if kind == "collect-single-work":
            _run_collect_single_work_task(task_id, task)
            return 0
        if kind == "collect-author":
            _run_collect_author_task(task_id, task)
            return 0
        if kind == "collect-author-selective-download":
            _run_selective_download_task(task_id, task)
            return 0

        update_task_record(
            task_id,
            status="failed",
            error=f"未知任务类型: {kind}",
            ended_at=now_iso(),
        )
        append_task_log(task_id, f"未知任务类型: {kind}")
        return 2
    except Exception as e:
        append_task_log(task_id, f"任务执行异常: {e}")
        append_task_log(task_id, traceback.format_exc(limit=3))
        update_task_record(
            task_id,
            status="failed",
            error=f"任务执行异常: {e}",
            ended_at=now_iso(),
        )
        return 3


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(1)
    task_id = str(sys.argv[1]).strip()
    raise SystemExit(run_task(task_id))

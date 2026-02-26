"""
抖音按作者采集模块 — 基于 f2 库
对外暴露同步接口，内部用 asyncio.run() 包装异步逻辑。
"""

import asyncio
import logging
import os
import re
import time
import random
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

log = logging.getLogger("douyin_crawler")

# ---------------------------------------------------------------------------
# Cookie 管理（与 bilibili_crawler 保持一致的模式）
# ---------------------------------------------------------------------------

_BASE_DIR = Path(__file__).resolve().parent
_RUNTIME_DIR = _BASE_DIR / "runtime"
_COOKIE_FILE = _RUNTIME_DIR / "douyin_cookie.txt"

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0"
)


def _load_cookie() -> str:
    if _COOKIE_FILE.exists():
        try:
            text = _COOKIE_FILE.read_text(encoding="utf-8").strip()
            if text:
                return text
        except Exception:
            pass
    return os.getenv("DOUYIN_COOKIE", "").strip()


def _cookie_source() -> str:
    if _COOKIE_FILE.exists():
        try:
            if _COOKIE_FILE.read_text(encoding="utf-8").strip():
                return "file"
        except Exception:
            pass
    if os.getenv("DOUYIN_COOKIE", "").strip():
        return "env"
    return "none"


MY_COOKIE = _load_cookie()


def update_cookie(new_cookie: str) -> None:
    global MY_COOKIE
    MY_COOKIE = new_cookie.strip()
    _RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    _COOKIE_FILE.write_text(MY_COOKIE, encoding="utf-8")


def get_cookie_info() -> dict:
    keys = [k.strip().split("=")[0] for k in MY_COOKIE.split(";") if "=" in k] if MY_COOKIE else []
    return {
        "is_set": bool(MY_COOKIE),
        "source": _cookie_source(),
        "keys": keys,
        "key_count": len(keys),
    }


# ---------------------------------------------------------------------------
# sec_user_id 解析（URL / 纯 ID 自动识别）
# ---------------------------------------------------------------------------

_DOUYIN_URL_PATTERN = re.compile(r"user/([^/?#]+)")
_SEC_UID_PATTERN = re.compile(r"sec_uid=([^&]+)")
_SEC_USER_ID_RE = re.compile(r"^MS4wLjAB[A-Za-z0-9_-]+$")


def _is_sec_user_id(text: str) -> bool:
    """判断是否已经是 sec_user_id（以 MS4wLjAB 开头的 base64 编码）"""
    return bool(_SEC_USER_ID_RE.match(text.strip()))


async def _resolve_sec_user_id_async(input_str: str) -> str:
    """从 URL 或纯 sec_user_id 中解析出 sec_user_id"""
    text = input_str.strip()

    # 已经是 sec_user_id
    if _is_sec_user_id(text):
        log.info(f"输入已是 sec_user_id: {text[:20]}...")
        return text

    # 尝试从 URL 中提取
    try:
        from f2.apps.douyin.utils import SecUserIdFetcher
        sec_user_id = await SecUserIdFetcher.get_sec_user_id(text)
        log.info(f"从 URL 解析出 sec_user_id: {sec_user_id[:20]}...")
        return sec_user_id
    except Exception as exc:
        log.error(f"解析 sec_user_id 失败: {exc}")
        raise ValueError(f"无法从输入中解析出抖音 sec_user_id: {exc}") from exc


def resolve_author_id(input_str: str) -> str:
    """同步接口：解析 sec_user_id"""
    return asyncio.run(_resolve_sec_user_id_async(input_str))


# ---------------------------------------------------------------------------
# DouyinCrawler 主类
# ---------------------------------------------------------------------------

class DouyinCrawler:
    """抖音按作者采集器，对外暴露同步接口"""

    def __init__(self, cookie: str | None = None, proxy: str | None = None):
        self.cookie = cookie or _load_cookie()
        self.proxy = proxy
        self.last_error: dict | None = None

        if not self.cookie:
            log.warning("抖音 Cookie 未设置，采集可能失败")

    def _build_kwargs(self) -> dict:
        """构造 f2 DouyinHandler 所需的 kwargs"""
        proxies = (
            {"http://": self.proxy, "https://": self.proxy}
            if self.proxy
            else {"http://": None, "https://": None}
        )
        return {
            "headers": {
                "User-Agent": DEFAULT_UA,
                "Referer": "https://www.douyin.com/",
            },
            "cookie": self.cookie,
            "proxies": proxies,
            "timeout": 10,
            "max_retries": 3,
            "max_connections": 5,
            "max_tasks": 5,
            "page_counts": 20,
            "naming": "{create}_{desc}",
            "path": "Download",
        }

    # ---- 获取作者信息 ----

    async def _fetch_author_info_async(self, sec_user_id: str) -> dict[str, Any]:
        from f2.apps.douyin.handler import DouyinHandler

        handler = DouyinHandler(kwargs=self._build_kwargs())
        profile = await handler.fetch_user_profile(sec_user_id)
        return {
            "sec_user_id": sec_user_id,
            "uid": profile.uid if hasattr(profile, "uid") else "",
            "nickname": profile.nickname if hasattr(profile, "nickname") else "",
            "signature": profile.signature if hasattr(profile, "signature") else "",
            "avatar": profile.avatar_larger if hasattr(profile, "avatar_larger") else "",
            "follower_count": profile.follower_count if hasattr(profile, "follower_count") else 0,
            "total_favorited": profile.total_favorited if hasattr(profile, "total_favorited") else 0,
            "aweme_count": profile.aweme_count if hasattr(profile, "aweme_count") else 0,
        }

    def get_author_info(self, sec_user_id: str) -> dict[str, Any]:
        """同步接口：获取作者信息"""
        try:
            return asyncio.run(self._fetch_author_info_async(sec_user_id))
        except Exception as exc:
            log.error(f"获取作者信息失败: {exc}")
            self.last_error = {"stage": "get_author_info", "error": str(exc)}
            return {}

    # ---- 分页采集所有作品 ----

    async def _fetch_all_videos_async(
        self, sec_user_id: str, max_counts: int | None = None
    ) -> list[dict[str, Any]]:
        from f2.apps.douyin.handler import DouyinHandler

        handler = DouyinHandler(kwargs=self._build_kwargs())
        all_videos: list[dict[str, Any]] = []
        page = 0

        async for video_filter in handler.fetch_user_post_videos(
            sec_user_id=sec_user_id,
            page_counts=20,
            max_counts=max_counts,
        ):
            page += 1
            raw = video_filter._to_raw()
            aweme_list = raw.get("aweme_list", [])

            if not aweme_list:
                log.info(f"第 {page} 页无作品，跳过")
                continue

            for aweme in aweme_list:
                stats = aweme.get("statistics", {})
                video_info = aweme.get("video", {})
                author = aweme.get("author", {})

                # 视频播放地址
                play_url = ""
                play_addr = video_info.get("play_addr", {})
                url_list = play_addr.get("url_list", [])
                if url_list:
                    play_url = url_list[0]

                # 封面
                cover_url = ""
                cover = video_info.get("cover", {})
                cover_list = cover.get("url_list", [])
                if cover_list:
                    cover_url = cover_list[0]

                # 图集地址（aweme_type == 68）
                images = []
                if aweme.get("aweme_type") == 68:
                    for img in aweme.get("images", []):
                        img_urls = img.get("url_list", [])
                        if img_urls:
                            images.append(img_urls[0])

                video_dict = {
                    "aweme_id": aweme.get("aweme_id", ""),
                    "desc": aweme.get("desc", ""),
                    "create_time": aweme.get("create_time", 0),
                    "aweme_type": aweme.get("aweme_type", 0),
                    "author_uid": author.get("uid", ""),
                    "author_nickname": author.get("nickname", ""),
                    "author_sec_uid": author.get("sec_uid", ""),
                    "digg_count": stats.get("digg_count", 0),
                    "comment_count": stats.get("comment_count", 0),
                    "share_count": stats.get("share_count", 0),
                    "collect_count": stats.get("collect_count", 0),
                    "play_count": stats.get("play_count", 0),
                    "cover_url": cover_url,
                    "play_url": play_url,
                    "images": images,
                    "video_link": f"https://www.douyin.com/video/{aweme.get('aweme_id', '')}",
                }
                all_videos.append(video_dict)

            log.info(f"第 {page} 页采集完成，本页 {len(aweme_list)} 个，累计 {len(all_videos)} 个")

            # 随机延迟，避免限流
            delay = random.uniform(1.0, 3.0)
            await asyncio.sleep(delay)

        log.info(f"采集完成，共 {len(all_videos)} 个作品")
        return all_videos

    def get_all_videos(self, sec_user_id: str, max_counts: int | None = None) -> list[dict[str, Any]]:
        """同步接口：获取指定作者的所有作品"""
        self.last_error = None
        try:
            return asyncio.run(self._fetch_all_videos_async(sec_user_id, max_counts))
        except Exception as exc:
            log.error(f"采集作品列表失败: {exc}")
            self.last_error = {"stage": "get_all_videos", "error": str(exc)}
            return []

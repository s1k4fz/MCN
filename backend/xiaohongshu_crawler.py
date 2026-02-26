"""
小红书按作者采集模块 — 基于 xhshow 签名 + httpx
对外暴露同步接口，内部用 asyncio.run() 包装异步逻辑。
"""

import asyncio
import logging
import os
import re
import random
import time
import urllib.parse
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

log = logging.getLogger("xiaohongshu_crawler")

# ---------------------------------------------------------------------------
# Cookie 管理
# ---------------------------------------------------------------------------

_BASE_DIR = Path(__file__).resolve().parent
_RUNTIME_DIR = _BASE_DIR / "runtime"
_COOKIE_FILE = _RUNTIME_DIR / "xhs_cookie.txt"

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0"
)

_API_BASE = "https://edith.xiaohongshu.com"
_USER_POSTED_URI = "/api/sns/web/v1/user_posted"


def _build_query_string(params: dict[str, str]) -> str:
    """构建 query string，逗号不编码，与 xhshow 签名一致"""
    parts = []
    for k, v in params.items():
        parts.append(f"{k}={urllib.parse.quote(str(v), safe=',')}")
    return "&".join(parts)


def _load_cookie() -> str:
    if _COOKIE_FILE.exists():
        try:
            text = _COOKIE_FILE.read_text(encoding="utf-8").strip()
            if text:
                return text
        except Exception:
            pass
    return os.getenv("XHS_COOKIE", "").strip()


def _cookie_source() -> str:
    if _COOKIE_FILE.exists():
        try:
            if _COOKIE_FILE.read_text(encoding="utf-8").strip():
                return "file"
        except Exception:
            pass
    if os.getenv("XHS_COOKIE", "").strip():
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
# user_id 解析
# ---------------------------------------------------------------------------

_XHS_USER_ID_RE = re.compile(r"^[0-9a-f]{24}$")
_XHS_URL_USER_RE = re.compile(r"/user/profile/([0-9a-f]{24})")


def _is_user_id(text: str) -> bool:
    return bool(_XHS_USER_ID_RE.match(text.strip()))


async def _resolve_user_id_async(input_str: str, cookie: str, proxy: str | None = None) -> str:
    """从 URL 或纯 user_id 中解析出 user_id"""
    import httpx

    text = input_str.strip()

    # 已经是 user_id
    if _is_user_id(text):
        log.info(f"输入已是 user_id: {text}")
        return text

    # 尝试从 URL 中正则提取
    m = _XHS_URL_USER_RE.search(text)
    if m:
        uid = m.group(1)
        log.info(f"从 URL 正则提取 user_id: {uid}")
        return uid

    # 跟随重定向解析
    try:
        headers = {
            "User-Agent": DEFAULT_UA,
            "Cookie": cookie,
        }
        async with httpx.AsyncClient(
            headers=headers, proxy=proxy, timeout=15, follow_redirects=True, verify=False
        ) as client:
            resp = await client.get(text)
            final_url = str(resp.url)
            m2 = _XHS_URL_USER_RE.search(final_url)
            if m2:
                uid = m2.group(1)
                log.info(f"从重定向 URL 解析 user_id: {uid}")
                return uid
    except Exception as exc:
        log.error(f"重定向解析失败: {exc}")

    raise ValueError(f"无法从输入中解析出小红书 user_id: {text}")


# ---------------------------------------------------------------------------
# XiaohongshuCrawler 主类
# ---------------------------------------------------------------------------

class XiaohongshuCrawler:
    """小红书按作者采集器，对外暴露同步接口"""

    def __init__(self, cookie: str | None = None, proxy: str | None = None):
        self.cookie = cookie or _load_cookie()
        self.proxy = proxy
        self.last_error: dict | None = None

        if not self.cookie:
            log.warning("小红书 Cookie 未设置，采集可能失败")

    def resolve_user_id(self, input_str: str) -> str:
        """同步接口：解析 user_id"""
        return asyncio.run(_resolve_user_id_async(input_str, self.cookie, self.proxy))

    # ---- 获取作者信息 ----

    async def _fetch_author_info_async(self, user_id: str) -> dict[str, Any]:
        """通过 user_posted 接口的第一页获取作者基本信息"""
        import httpx
        from xhshow import Xhshow

        encipher = Xhshow()
        params = {
            "num": "1",
            "cursor": "",
            "user_id": user_id,
            "image_formats": "jpg,webp,avif",
        }

        base_headers = {
            "User-Agent": DEFAULT_UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Content-Type": "application/json;charset=UTF-8",
            "Origin": "https://www.xiaohongshu.com",
            "Referer": "https://www.xiaohongshu.com/",
            "Cookie": self.cookie,
        }

        signed = encipher.sign_headers_get(
            uri=_USER_POSTED_URI,
            cookies=self.cookie,
            params=params,
        )
        headers = signed | base_headers

        full_url = f"{_API_BASE}{_USER_POSTED_URI}?{_build_query_string(params)}"
        async with httpx.AsyncClient(
            headers=headers, proxy=self.proxy, timeout=15, verify=False
        ) as client:
            resp = await client.get(full_url)
            data = resp.json()

        if data.get("success") and data.get("data", {}).get("notes"):
            first_note = data["data"]["notes"][0]
            user = first_note.get("user", {})
            return {
                "user_id": user_id,
                "nickname": user.get("nickname", ""),
                "avatar": user.get("avatar", ""),
                "user_link": f"https://www.xiaohongshu.com/user/profile/{user_id}",
            }

        return {"user_id": user_id, "nickname": "", "avatar": ""}

    def get_author_info(self, user_id: str) -> dict[str, Any]:
        """同步接口：获取作者信息"""
        try:
            return asyncio.run(self._fetch_author_info_async(user_id))
        except Exception as exc:
            log.error(f"获取作者信息失败: {exc}")
            self.last_error = {"stage": "get_author_info", "error": str(exc)}
            return {"user_id": user_id, "nickname": "", "avatar": ""}

    # ---- 分页采集所有笔记 ----

    async def _fetch_all_notes_async(
        self, user_id: str, max_counts: int | None = None
    ) -> list[dict[str, Any]]:
        import httpx
        from xhshow import Xhshow

        encipher = Xhshow()
        all_notes: list[dict[str, Any]] = []
        cursor = ""
        has_more = True
        page = 0
        max_counts = max_counts or float("inf")

        base_headers = {
            "User-Agent": DEFAULT_UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Content-Type": "application/json;charset=UTF-8",
            "Origin": "https://www.xiaohongshu.com",
            "Referer": "https://www.xiaohongshu.com/",
            "Cookie": self.cookie,
        }

        while has_more and len(all_notes) < max_counts:
            page += 1
            params = {
                "num": "30",
                "cursor": cursor,
                "user_id": user_id,
                "image_formats": "jpg,webp,avif",
            }

            signed = encipher.sign_headers_get(
                uri=_USER_POSTED_URI,
                cookies=self.cookie,
                params=params,
            )
            headers = signed | base_headers

            try:
                async with httpx.AsyncClient(
                    headers=headers, proxy=self.proxy, timeout=15, verify=False
                ) as client:
                    full_url = f"{_API_BASE}{_USER_POSTED_URI}?{_build_query_string(params)}"
                    resp = await client.get(full_url)
                    data = resp.json()
            except Exception as exc:
                log.error(f"第 {page} 页请求失败: {exc}")
                self.last_error = {"stage": "get_all_notes", "page": page, "error": str(exc)}
                break

            if not data.get("success"):
                code = data.get("code")
                msg = data.get("msg", "")
                log.error(f"第 {page} 页 API 返回失败: code={code}, msg={msg}")
                if code == -100:
                    self.last_error = {"stage": "get_all_notes", "error": "Cookie 已过期，请重新设置"}
                else:
                    self.last_error = {"stage": "get_all_notes", "error": f"API 错误: {msg}"}
                break

            notes_data = data.get("data", {})
            notes = notes_data.get("notes", [])
            has_more = notes_data.get("has_more", False)
            cursor = notes_data.get("cursor", "")

            if not notes:
                log.info(f"第 {page} 页无笔记，结束")
                break

            for note in notes:
                interact = note.get("interact_info", {})
                user = note.get("user", {})
                cover = note.get("cover", {})

                # 图片列表
                images = []
                for img in note.get("images_list", []):
                    img_url = img.get("url", "") or img.get("url_default", "")
                    if img_url:
                        images.append(img_url)

                # 构建笔记链接（带 xsec_token 供解析器使用）
                note_id = note.get("note_id", "")
                xsec_token = note.get("xsec_token", "")
                if xsec_token:
                    note_link = (
                        f"https://www.xiaohongshu.com/discovery/item/{note_id}"
                        f"?source=webshare&xsec_token={xsec_token}"
                        f"&xsec_source=pc_feed"
                    )
                else:
                    note_link = f"https://www.xiaohongshu.com/explore/{note_id}"

                note_dict = {
                    "note_id": note_id,
                    "display_title": note.get("display_title", ""),
                    "desc": note.get("desc", ""),
                    "type": note.get("type", ""),
                    "author_user_id": user.get("user_id", ""),
                    "author_nickname": user.get("nickname", ""),
                    "liked_count": interact.get("liked_count", "0"),
                    "collected_count": interact.get("collected_count", "0"),
                    "comment_count": interact.get("comment_count", "0"),
                    "share_count": interact.get("share_count", "0"),
                    "cover_url": cover.get("url", "") or cover.get("url_default", ""),
                    "images": images,
                    "xsec_token": xsec_token,
                    "note_link": note_link,
                }
                all_notes.append(note_dict)

            log.info(f"第 {page} 页采集完成，本页 {len(notes)} 个，累计 {len(all_notes)} 个")

            if not has_more:
                break

            # 随机延迟
            delay = random.uniform(1.5, 3.5)
            await asyncio.sleep(delay)

        log.info(f"采集完成，共 {len(all_notes)} 篇笔记")
        return all_notes

    def get_all_notes(self, user_id: str, max_counts: int | None = None) -> list[dict[str, Any]]:
        """同步接口：获取指定作者的所有笔记"""
        self.last_error = None
        try:
            return asyncio.run(self._fetch_all_notes_async(user_id, max_counts))
        except Exception as exc:
            log.error(f"采集笔记列表失败: {exc}")
            self.last_error = {"stage": "get_all_notes", "error": str(exc)}
            return []

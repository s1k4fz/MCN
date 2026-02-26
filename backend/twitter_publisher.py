"""
Twitter Publishing Engine — uses curl_cffi for Chrome TLS fingerprint.

Uses curl_cffi.requests.Session (with impersonate="chrome136") to mimic
real Chrome browser TLS fingerprints (JA3/JA4). This is CRITICAL because
Twitter/Cloudflare detects Python requests/httpx/aiohttp by their TLS
fingerprint and returns 226 (anti-automation) errors.
"""

import asyncio
import json
import logging
import math
import mimetypes
import random
import time
import traceback
from pathlib import Path
from typing import Any
from urllib.parse import quote

import importlib.util
import re
import sys

import bs4
from curl_cffi import requests as cffi_requests

from account_store import get_account_record
from proxy_store import (
    get_proxy_record,
    list_account_bindings,
    update_proxy_record,
)

# Import ClientTransaction directly from source to avoid twikit's heavy __init__
_twikit_base = Path(__file__).resolve().parent.parent / "twikit-main" / "twikit"
_ct_pkg = str(_twikit_base / "x_client_transaction")
if _ct_pkg not in sys.path:
    sys.path.insert(0, _ct_pkg)
    sys.path.insert(0, str(_twikit_base / "x_client_transaction"))
_spec = importlib.util.spec_from_file_location(
    "x_client_transaction_mod",
    str(_twikit_base / "x_client_transaction" / "transaction.py"),
    submodule_search_locations=[str(_twikit_base / "x_client_transaction")],
)
_ct_module = importlib.util.module_from_spec(_spec)
sys.modules["x_client_transaction_mod"] = _ct_module
# Also need the sub-modules to be importable
for submod in ("utils", "cubic_curve", "interpolate", "rotation"):
    sub_path = _twikit_base / "x_client_transaction" / f"{submod}.py"
    if sub_path.exists():
        sub_spec = importlib.util.spec_from_file_location(
            f"x_client_transaction_mod.{submod}", str(sub_path)
        )
        sub_module = importlib.util.module_from_spec(sub_spec)
        sys.modules[f"x_client_transaction_mod.{submod}"] = sub_module
# Import the package properly
sys.path.insert(0, str(_twikit_base.parent))
_x_ct_init = _twikit_base / "x_client_transaction" / "__init__.py"
if _x_ct_init.exists():
    _init_spec = importlib.util.spec_from_file_location(
        "twikit.x_client_transaction",
        str(_x_ct_init),
        submodule_search_locations=[str(_twikit_base / "x_client_transaction")],
    )
    _init_mod = importlib.util.module_from_spec(_init_spec)
    sys.modules["twikit.x_client_transaction"] = _init_mod
    _init_spec.loader.exec_module(_init_mod)
    ClientTransaction = _init_mod.ClientTransaction
else:
    ClientTransaction = None

logger = logging.getLogger("twitter_publisher")
logger.setLevel(logging.DEBUG)

TWITTER_BEARER_TOKEN = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D"
    "1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)
DOMAIN = "x.com"
CREATE_TWEET_ENDPOINT = f"https://{DOMAIN}/i/api/graphql/nk8sb5Uu0l6zePyGJI_uYQ/CreateTweet"
UPLOAD_MEDIA_ENDPOINT = f"https://upload.{DOMAIN}/i/media/upload.json"

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)

FEATURES = {
    "premium_content_api_read_enabled": False,
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
    "responsive_web_grok_analyze_post_followups_enabled": False,
    "responsive_web_jetfuel_frame": True,
    "responsive_web_grok_share_attachment_enabled": True,
    "responsive_web_grok_annotations_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "profile_label_improvements_pcf_label_in_post_enabled": True,
    "responsive_web_profile_redirect_enabled": False,
    "rweb_tipjar_consumption_enabled": False,
    "verified_phone_label_enabled": False,
    "articles_preview_enabled": True,
    "responsive_web_grok_community_note_auto_translation_is_enabled": False,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "responsive_web_grok_image_annotation_enabled": True,
    "responsive_web_grok_imagine_annotation_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
}

MEDIA_TIMEOUT = 60
API_TIMEOUT = 30

# ---------------------------------------------------------------------------
# Session pool
# ---------------------------------------------------------------------------

SESSION_TTL = 1800  # 30 minutes


class SessionEntry:
    def __init__(self, session: "TwitterPublisherSession"):
        self.session = session
        self.last_used = time.time()


_session_pool: dict[str, SessionEntry] = {}
_account_locks: dict[str, asyncio.Lock] = {}


def _get_account_lock(account_id: str) -> asyncio.Lock:
    if account_id not in _account_locks:
        _account_locks[account_id] = asyncio.Lock()
    return _account_locks[account_id]


async def get_or_create_session(account_id: str) -> "TwitterPublisherSession":
    entry = _session_pool.get(account_id)
    if entry and (time.time() - entry.last_used) < SESSION_TTL:
        age = int(time.time() - entry.last_used)
        logger.debug("[pool] 复用已有会话: account_id=%s, age=%ds", account_id, age)
        entry.last_used = time.time()
        return entry.session
    if entry:
        logger.debug("[pool] 会话已过期, 清理旧会话: account_id=%s", account_id)
        entry.session.close()
    logger.info("[pool] 创建新会话: account_id=%s", account_id)
    session = TwitterPublisherSession(account_id)
    await session.initialize()
    _session_pool[account_id] = SessionEntry(session)
    logger.info("[pool] 新会话已缓存: account_id=%s", account_id)
    return session


async def cleanup_expired_sessions() -> None:
    now = time.time()
    expired = [k for k, v in _session_pool.items() if now - v.last_used >= SESSION_TTL]
    for account_id in expired:
        entry = _session_pool.pop(account_id, None)
        if entry:
            entry.session.close()


# ---------------------------------------------------------------------------
# Error helpers
# ---------------------------------------------------------------------------

def classify_error(exc: Exception) -> dict[str, Any]:
    """Return a structured dict describing the error for API responses."""
    err_name = type(exc).__name__
    err_msg = str(exc)
    logger.debug("[classify] 分类异常: %s [%s]", err_msg[:200], err_name)

    if isinstance(exc, ValueError):
        if "没有绑定代理" in err_msg or "非 active" in err_msg or ("代理" in err_msg and "不存在" in err_msg):
            return {"code": "no_proxy", "message": err_msg, "retryable": False}
        if "ct0" in err_msg.lower() or "auth_token" in err_msg.lower():
            return {"code": "auth_error", "message": err_msg, "retryable": False}
        return {"code": "config_error", "message": err_msg, "retryable": False}

    if "(226)" in err_msg or "automated" in err_msg.lower():
        return {
            "code": "anti_automation",
            "message": (
                "Twitter 检测到自动化行为 (226). "
                "可能原因: 账号较新/信任度低、短时间内发推太频繁、内容触发风控。"
                "建议: 等待几分钟后重试，或换用更成熟的账号。"
            ),
            "retryable": True,
        }
    if "duplicate" in err_msg.lower():
        return {"code": "duplicate_tweet", "message": "推文内容重复", "retryable": False}
    if "proxy" in err_name.lower() or "proxy" in err_msg.lower():
        return {
            "code": "proxy_error",
            "message": f"代理服务器连接失败 ({err_msg}). 请检查代理是否过期或凭证是否有效。",
            "retryable": False,
        }
    if "timeout" in err_name.lower() or "timeout" in err_msg.lower():
        return {"code": "timeout", "message": f"请求超时: {err_msg}", "retryable": True}
    if "suspended" in err_msg.lower():
        return {"code": "account_suspended", "message": "账号已被封禁", "retryable": False}
    if "locked" in err_msg.lower():
        return {"code": "account_locked", "message": "账号已被锁定", "retryable": False}
    if "401" in err_msg or "unauthorized" in err_msg.lower():
        return {"code": "unauthorized", "message": "auth_token 已过期或无效", "retryable": False}
    if "403" in err_msg or "forbidden" in err_msg.lower():
        return {"code": "forbidden", "message": f"操作被拒绝: {err_msg}", "retryable": False}
    if "429" in err_msg or "rate" in err_msg.lower():
        return {"code": "rate_limited", "message": "触发速率限制，请稍后重试", "retryable": True}

    return {"code": "unknown", "message": err_msg, "retryable": True}


# ---------------------------------------------------------------------------
# Core session class — uses curl_cffi for Chrome TLS fingerprint
# ---------------------------------------------------------------------------

class TwitterPublisherSession:
    """Wraps a curl_cffi Session bound to one account + proxy."""

    ON_DEMAND_FILE_REGEX = re.compile(
        r"""['|"]{1}ondemand\.s['|"]{1}:\s*['|"]{1}([\w]*)['|"]{1}""",
        flags=(re.VERBOSE | re.MULTILINE),
    )
    INDICES_REGEX = re.compile(
        r"""(\(\w{1}\[(\d{1,2})\],\s*16\))+""",
        flags=(re.VERBOSE | re.MULTILINE),
    )

    def __init__(self, account_id: str) -> None:
        self.account_id = account_id
        self.account: dict[str, Any] | None = None
        self.proxy_url: str | None = None
        self.ct0: str | None = None
        self.auth_token: str | None = None
        self._full_cookies: dict[str, str] = {}
        self._http: cffi_requests.Session | None = None
        self._client_transaction: ClientTransaction | None = None

    # ---- cookie parsing ---------------------------------------------------

    @staticmethod
    def _parse_cookie_string(cookie_str: str) -> dict[str, str]:
        """Parse a browser cookie string like 'k1=v1; k2=v2' into a dict."""
        cookies: dict[str, str] = {}
        for pair in cookie_str.split(";"):
            pair = pair.strip()
            if not pair or "=" not in pair:
                continue
            key, _, value = pair.partition("=")
            key = key.strip()
            if key:
                cookies[key] = value.strip()
        return cookies

    # ---- lifecycle --------------------------------------------------------

    async def initialize(self) -> None:
        logger.debug("[init] 开始初始化会话, account_id=%s", self.account_id)

        self.account = get_account_record(self.account_id)
        if not self.account:
            raise ValueError(f"账号不存在: {self.account_id}")
        logger.debug("[init] 账号记录: account=%s, platform=%s, status=%s",
                     self.account.get("account"), self.account.get("platform"),
                     self.account.get("status"))

        if self.account.get("status") != "active":
            raise ValueError(f"账号状态异常 ({self.account.get('status')}), 无法发布")

        # Parse cookies: prefer full cookie string, fall back to token-only
        raw_cookies = (self.account.get("cookies") or "").strip()
        raw_token = (self.account.get("token") or "").strip()

        if raw_cookies:
            self._full_cookies = self._parse_cookie_string(raw_cookies)
            self.auth_token = self._full_cookies.get("auth_token", "")
            # If cookies string has ct0, pre-populate it (will be refreshed in bootstrap)
            if self._full_cookies.get("ct0"):
                self.ct0 = self._full_cookies["ct0"]
            logger.info("[init] 已解析完整 cookies (%d 个字段), auth_token=%s",
                        len(self._full_cookies),
                        "有" if self.auth_token else "无")
        elif raw_token:
            # Legacy: token field contains only auth_token
            self.auth_token = raw_token
            self._full_cookies = {"auth_token": raw_token}
            logger.info("[init] 使用 token 字段作为 auth_token (旧模式)")
        else:
            raise ValueError("账号缺少 cookies 或 token 字段，无法发布")

        if not self.auth_token:
            raise ValueError("cookies 中缺少 auth_token，请检查 cookie 是否完整")
        logger.debug("[init] auth_token 长度=%d, 前8字符=%s...",
                     len(self.auth_token), self.auth_token[:8])

        self.proxy_url = self._resolve_proxy()
        proxy_label = (self.proxy_url.split("@")[-1]
                       if "@" in self.proxy_url else self.proxy_url)
        logger.info("[init] 代理已解析: %s", proxy_label)

        # Build curl_cffi Session with Chrome TLS fingerprint
        self._http = cffi_requests.Session(impersonate="chrome136")
        self._http.headers.update({"User-Agent": DEFAULT_USER_AGENT})

        # Pre-load full cookies into session BEFORE any requests
        for cname, cvalue in self._full_cookies.items():
            self._http.cookies.set(cname, cvalue, domain=".x.com")
        logger.debug("[init] curl_cffi Session 已创建 (Chrome TLS), 预注入 %d 个 cookies",
                     len(self._full_cookies))

        # Test proxy connectivity, fall back to direct if proxy fails
        self._http.proxies = {
            "http": self.proxy_url,
            "https": self.proxy_url,
        }
        try:
            test_resp = self._http.get(
                f"https://{DOMAIN}", timeout=10, allow_redirects=True
            )
            logger.info("[init] 代理连接成功 (status=%d)", test_resp.status_code)
        except Exception as proxy_err:
            logger.warning("[init] 代理连接失败: %s — 回退到直连模式", proxy_err)
            self._http.proxies = {}
            self.proxy_url = "(direct)"

        # Bootstrap ct0 + client transaction (anti-automation)
        await asyncio.to_thread(self._bootstrap_ct0_and_transaction)
        logger.info("[init] ct0 已获取 (长度=%d, 前8字符=%s...)",
                    len(self.ct0), self.ct0[:8])
        logger.info("[init] ClientTransaction 已初始化 (反自动化 token 就绪)")

        # Verify session works
        logger.debug("[init] 正在验证会话...")
        await asyncio.to_thread(self._verify_session)
        logger.info("[init] 会话验证成功 — account=%s, proxy=%s",
                    self.account.get("account"), proxy_label)

    def close(self) -> None:
        if self._http:
            self._http.close()
            self._http = None

    # ---- ct0 bootstrap (synchronous, run via asyncio.to_thread) ----------

    def _bootstrap_ct0_and_transaction(self) -> None:
        """Fetch x.com via proxy to get ct0 and initialize ClientTransaction.
        Handles Twitter's x-migration redirects (matching twikit's handle_x_migration).
        """
        ct_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Sec-Ch-Ua": '"Chromium";v="136", "Not_A Brand";v="24"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": DEFAULT_USER_AGENT,
        }

        migration_redirection_regex = re.compile(
            r"""(http(?:s)?://(?:www\.)?(twitter|x){1}\.com(/x)?/migrate([/?])?tok=[a-zA-Z0-9%\-_]+)+""",
            re.VERBOSE,
        )

        # Step 1: fetch x.com home page (session already has full cookies pre-loaded)
        logger.debug("[ct0] 正在通过代理请求 https://x.com ...")
        t0 = time.time()
        resp = self._http.get(
            f"https://{DOMAIN}",
            headers=ct_headers,
            timeout=API_TIMEOUT,
            allow_redirects=True,
        )
        elapsed = int((time.time() - t0) * 1000)
        logger.debug("[ct0] x.com 响应: status=%d (%dms)", resp.status_code, elapsed)

        if resp.status_code != 200:
            raise ValueError(
                f"访问 x.com 失败 (HTTP {resp.status_code}). "
                f"auth_token 可能已过期，请重新导入账号。"
            )

        home_page = bs4.BeautifulSoup(resp.content, "lxml")

        # Step 1b: handle x-migration redirect (matching twikit handle_x_migration)
        migration_url_meta = home_page.select_one("meta[http-equiv='refresh']")
        migration_match = (
            re.search(migration_redirection_regex, str(migration_url_meta))
            or re.search(migration_redirection_regex, str(resp.content))
        )
        if migration_match:
            logger.debug("[ct0] 检测到 migration 重定向: %s", migration_match.group(0))
            resp = self._http.get(
                migration_match.group(0),
                headers=ct_headers,
                timeout=API_TIMEOUT,
                allow_redirects=True,
            )
            home_page = bs4.BeautifulSoup(resp.content, "lxml")

        migration_form = (
            home_page.select_one("form[name='f']")
            or home_page.select_one("form[action='https://x.com/x/migrate']")
        )
        if migration_form:
            form_url = migration_form.attrs.get("action", "https://x.com/x/migrate") + "/?mx=2"
            form_method = migration_form.attrs.get("method", "POST").upper()
            form_data = {
                inp.get("name"): inp.get("value")
                for inp in migration_form.select("input")
                if inp.get("name")
            }
            logger.debug("[ct0] 提交 migration 表单: %s %s", form_method, form_url)
            if form_method == "POST":
                resp = self._http.post(
                    form_url, data=form_data,
                    headers=ct_headers, timeout=API_TIMEOUT,
                    allow_redirects=True,
                )
            else:
                resp = self._http.get(
                    form_url, params=form_data,
                    headers=ct_headers, timeout=API_TIMEOUT,
                    allow_redirects=True,
                )
            home_page = bs4.BeautifulSoup(resp.content, "lxml")

        ct0 = resp.cookies.get("ct0") or self._http.cookies.get("ct0")
        if not ct0:
            raise ValueError(
                "无法获取 ct0 CSRF token. auth_token 可能已过期，请重新导入账号。"
            )
        self.ct0 = ct0

        # Step 2: initialize ClientTransaction from home page HTML
        ct = ClientTransaction()
        ct.home_page_response = ct.validate_response(home_page)

        # Get key and animation data
        ct.key = ct.get_key(response=home_page)
        ct.key_bytes = ct.get_key_bytes(key=ct.key)

        # Fetch on-demand JS to get indices
        on_demand_match = self.ON_DEMAND_FILE_REGEX.search(str(home_page))
        if on_demand_match:
            js_url = f"https://abs.twimg.com/responsive-web/client-web/ondemand.s.{on_demand_match.group(1)}a.js"
            logger.debug("[ct0] 获取 on-demand JS: %s", js_url)
            js_resp = self._http.get(js_url, headers=ct_headers, timeout=API_TIMEOUT)
            key_byte_indices = []
            for match in self.INDICES_REGEX.finditer(js_resp.text):
                key_byte_indices.append(int(match.group(2)))
            if key_byte_indices:
                ct.DEFAULT_ROW_INDEX = key_byte_indices[0]
                ct.DEFAULT_KEY_BYTES_INDICES = key_byte_indices[1:]
                logger.debug("[ct0] indices 已获取: row=%s, key_bytes=%s",
                             ct.DEFAULT_ROW_INDEX, ct.DEFAULT_KEY_BYTES_INDICES)
            else:
                logger.warning("[ct0] 未能从 on-demand JS 提取 indices")
        else:
            logger.warning("[ct0] 未找到 on-demand JS 引用")

        if ct.DEFAULT_ROW_INDEX is not None and ct.DEFAULT_KEY_BYTES_INDICES:
            ct.animation_key = ct.get_animation_key(
                key_bytes=ct.key_bytes, response=home_page
            )
            logger.debug("[ct0] animation_key 已生成")
        else:
            logger.warning("[ct0] 跳过 animation_key 生成 (indices 不完整)")

        self._client_transaction = ct

    def _verify_session(self) -> None:
        """Quick API call to verify the session is valid.
        Uses the same UserByScreenName endpoint that the account verifier uses.
        """
        from twitter_account_verifier import (
            USER_BY_SCREEN_NAME_FEATURES,
            USER_BY_SCREEN_NAME_QUERY_IDS,
            USER_BY_SCREEN_NAME_ENDPOINT_SUFFIX,
        )
        screen_name = self.account.get("account", "")
        if not screen_name:
            logger.debug("[verify] 无 screen_name，跳过验证")
            return

        query_id = USER_BY_SCREEN_NAME_QUERY_IDS[0]
        api_path = f"/i/api/graphql/{query_id}/{USER_BY_SCREEN_NAME_ENDPOINT_SUFFIX}"
        url = f"https://{DOMAIN}{api_path}"

        headers = self._build_api_headers(method="GET", path=api_path)
        headers.pop("content-type", None)
        cookies = self._api_cookies()

        params = {
            "variables": json.dumps(
                {"screen_name": screen_name, "withSafetyModeUserFields": True},
                separators=(",", ":"),
            ),
            "features": json.dumps(USER_BY_SCREEN_NAME_FEATURES, separators=(",", ":")),
        }

        t0 = time.time()
        resp = self._http.get(url, params=params, headers=headers, cookies=cookies, timeout=API_TIMEOUT)
        elapsed = int((time.time() - t0) * 1000)
        logger.debug("[verify] GraphQL 响应: status=%d (%dms)", resp.status_code, elapsed)

        if resp.status_code == 401:
            raise ValueError("auth_token 已过期或无效 (401)")
        if resp.status_code == 403:
            raise ValueError(f"账号被限制 (403): {resp.text[:200]}")
        if resp.status_code == 200:
            logger.debug("[verify] 响应预览: %.200s", resp.text[:200])
        else:
            logger.warning("[verify] 验证返回非 200 (status=%d)，但不影响发布", resp.status_code)

    # ---- proxy resolution -------------------------------------------------

    def _resolve_proxy(self) -> str:
        account_id = str(self.account.get("id", "")).strip()
        account_name = self.account.get("account") or account_id
        if not account_id:
            raise ValueError("账号缺少 id 字段，无法查找代理绑定")

        platform = str(self.account.get("platform", "")).strip().lower()
        logger.debug("[proxy] 查找代理绑定: account_id=%s, account=%s, platform=%s",
                     account_id, account_name, platform)

        bindings = list_account_bindings()
        logger.debug("[proxy] 当前绑定记录总数: %d", len(bindings))

        binding = next(
            (b for b in bindings
             if str(b.get("account_uid", "")).strip() == account_id
             and str(b.get("platform", "")).strip().lower() == platform),
            None,
        )
        if not binding:
            raise ValueError(
                f"账号 @{account_name} 没有绑定代理，为防止直连封号已拒绝发布。"
                f"请先在代理池中为该账号绑定代理。"
            )
        logger.debug("[proxy] 匹配到绑定: proxy_id=%s", binding["proxy_id"])

        proxy = get_proxy_record(binding["proxy_id"])
        if not proxy:
            raise ValueError(
                f"账号 @{account_name} 绑定的代理 {binding['proxy_id']} 不存在，请重新绑定代理。"
            )

        logger.debug("[proxy] 代理记录: ip=%s, port=%s, protocol=%s, status=%s",
                     proxy.get("ip"), proxy.get("port"),
                     proxy.get("protocol"), proxy.get("status"))

        if proxy.get("status") not in ("active", "slow"):
            logger.warning(
                "[proxy] 代理 %s 状态为 %s（非 active/slow），将尝试连接并可能回退到直连",
                binding["proxy_id"], proxy.get("status"),
            )

        return self._build_proxy_url(proxy)

    @staticmethod
    def _build_proxy_url(proxy: dict[str, Any]) -> str:
        protocol = proxy.get("protocol", "http")
        host = proxy["ip"]
        port = proxy["port"]
        username = str(proxy.get("username") or "").strip()
        password = str(proxy.get("password") or "").strip()
        if username and password:
            return f"{protocol}://{quote(username, safe='')}:{quote(password, safe='')}@{host}:{port}"
        return f"{protocol}://{host}:{port}"

    # ---- HTTP helpers -----------------------------------------------------

    def _build_api_headers(self, method: str = "POST", path: str = "") -> dict[str, str]:
        headers = {
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "en-US,en;q=0.9",
            "authorization": f"Bearer {TWITTER_BEARER_TOKEN}",
            "content-type": "application/json",
            "Origin": f"https://{DOMAIN}",
            "Referer": f"https://{DOMAIN}/",
            "Sec-Ch-Ua": '"Chromium";v="136", "Not_A Brand";v="24"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "User-Agent": DEFAULT_USER_AGENT,
            "x-csrf-token": self.ct0,
            "x-twitter-auth-type": "OAuth2Session",
            "x-twitter-active-user": "yes",
            "x-twitter-client-language": "en",
        }
        if self._client_transaction and self._client_transaction.home_page_response:
            try:
                tid = self._client_transaction.generate_transaction_id(
                    method=method, path=path
                )
                headers["X-Client-Transaction-Id"] = tid
                logger.debug("[headers] transaction_id=%s...", tid[:20])
            except Exception as e:
                logger.warning("[headers] 生成 transaction_id 失败: %s", e)
        return headers

    def _api_cookies(self) -> dict[str, str]:
        # Start with full cookies from account, then overlay session cookies
        base = dict(self._full_cookies)
        # Ensure auth_token and ct0 are always up-to-date
        base["auth_token"] = self.auth_token
        base["ct0"] = self.ct0
        # Merge session cookies (e.g. refreshed __cf_bm from Cloudflare)
        if self._http:
            for k, v in self._http.cookies.items():
                if k not in ("auth_token", "ct0"):
                    base[k] = v
        return base

    # ---- media upload (synchronous, run via asyncio.to_thread) -----------

    def _upload_media_sync(self, file_path: str) -> str:
        """Upload a media file using Twitter's chunked upload API."""
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"媒体文件不存在: {file_path}")

        file_size = path.stat().st_size
        mime_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        ext = path.suffix.lower()

        is_video = ext in (".mp4", ".mov", ".avi", ".webm")
        is_gif = ext == ".gif"
        media_category = "tweet_video" if is_video else ("tweet_gif" if is_gif else "tweet_image")

        logger.info("[media] 开始上传: file=%s, size=%d, mime=%s, category=%s",
                    path.name, file_size, mime_type, media_category)

        upload_path = "/i/media/upload.json"
        headers = self._build_api_headers(method="POST", path=upload_path)
        headers.pop("content-type", None)
        cookies = self._api_cookies()

        # INIT
        logger.debug("[media] INIT 请求...")
        init_params = {
            "command": "INIT",
            "total_bytes": str(file_size),
            "media_type": mime_type,
            "media_category": media_category,
        }
        resp = self._http.post(
            UPLOAD_MEDIA_ENDPOINT,
            params=init_params,
            headers=headers,
            cookies=cookies,
            timeout=MEDIA_TIMEOUT,
        )
        if resp.status_code != 200 and resp.status_code != 202:
            raise RuntimeError(f"媒体上传 INIT 失败 (HTTP {resp.status_code}): {resp.text[:300]}")
        media_id = resp.json()["media_id_string"]
        logger.debug("[media] INIT 成功: media_id=%s", media_id)

        # APPEND (chunked)
        chunk_size = 4 * 1024 * 1024  # 4MB
        segment = 0
        with open(path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                logger.debug("[media] APPEND segment=%d, chunk_size=%d", segment, len(chunk))
                append_resp = self._http.post(
                    UPLOAD_MEDIA_ENDPOINT,
                    params={
                        "command": "APPEND",
                        "media_id": media_id,
                        "segment_index": str(segment),
                    },
                    headers=headers,
                    cookies=cookies,
                    files={"media_data": chunk},
                    timeout=MEDIA_TIMEOUT,
                )
                if append_resp.status_code not in (200, 202, 204):
                    raise RuntimeError(
                        f"媒体上传 APPEND 失败 (segment={segment}, "
                        f"HTTP {append_resp.status_code}): {append_resp.text[:300]}"
                    )
                segment += 1

        # FINALIZE
        logger.debug("[media] FINALIZE 请求...")
        fin_resp = self._http.post(
            UPLOAD_MEDIA_ENDPOINT,
            params={"command": "FINALIZE", "media_id": media_id},
            headers=headers,
            cookies=cookies,
            timeout=MEDIA_TIMEOUT,
        )
        if fin_resp.status_code not in (200, 201):
            raise RuntimeError(f"媒体上传 FINALIZE 失败 (HTTP {fin_resp.status_code}): {fin_resp.text[:300]}")

        fin_data = fin_resp.json()
        processing_info = fin_data.get("processing_info")
        if processing_info:
            logger.debug("[media] 等待媒体处理: %s", processing_info)
            self._wait_for_processing(media_id, headers, cookies)

        logger.info("[media] 上传成功: %s -> media_id=%s", path.name, media_id)
        return media_id

    def _wait_for_processing(self, media_id: str, headers: dict, cookies: dict) -> None:
        """Poll media processing status until complete."""
        for attempt in range(60):
            resp = self._http.get(
                UPLOAD_MEDIA_ENDPOINT,
                params={"command": "STATUS", "media_id": media_id},
                headers=headers,
                cookies=cookies,
                timeout=MEDIA_TIMEOUT,
            )
            if resp.status_code != 200:
                logger.warning("[media] STATUS 查询失败: HTTP %d", resp.status_code)
                break
            info = resp.json().get("processing_info", {})
            state = info.get("state", "")
            logger.debug("[media] 处理状态: state=%s, progress=%s%%",
                         state, info.get("progress_percent", "?"))
            if state == "succeeded":
                return
            if state == "failed":
                error = info.get("error", {})
                raise RuntimeError(f"媒体处理失败: {error.get('message', state)}")
            wait = info.get("check_after_secs", 2)
            time.sleep(min(wait, 10))
        raise RuntimeError("媒体处理超时")

    # ---- tweet publishing (synchronous, run via asyncio.to_thread) -------

    def _publish_tweet_sync(
        self,
        text: str = "",
        media_ids: list[str] | None = None,
        is_sensitive: bool = False,
    ) -> dict[str, Any]:
        """Call the CreateTweet GraphQL endpoint."""
        account_name = self.account.get("account", "?")
        logger.info("[tweet] 开始发布推文 — account=%s, text_len=%d, media_count=%d",
                    account_name, len(text), len(media_ids or []))

        media_entities = []
        if media_ids:
            for mid in media_ids:
                media_entities.append({"media_id": mid, "tagged_users": []})

        variables = {
            "tweet_text": text,
            "dark_request": False,
            "media": {
                "media_entities": media_entities,
                "possibly_sensitive": is_sensitive,
            },
            "semantic_annotation_ids": [],
        }

        payload = {
            "variables": variables,
            "features": FEATURES,
            "queryId": "nk8sb5Uu0l6zePyGJI_uYQ",
        }

        api_path = "/i/api/graphql/nk8sb5Uu0l6zePyGJI_uYQ/CreateTweet"
        cookies = self._api_cookies()

        # Single attempt (no retry for 226 — surface full diagnostics instead)
        headers = self._build_api_headers(method="POST", path=api_path)
        cookies = self._api_cookies()

        logger.debug("[tweet] POST %s", CREATE_TWEET_ENDPOINT)
        logger.debug("[tweet] variables=%s", json.dumps(variables, ensure_ascii=False)[:500])

        # Log full request details for diagnostics
        safe_headers = {k: v for k, v in headers.items()}
        safe_cookies = {k: (v[:8] + "..." if len(v) > 12 else v) for k, v in cookies.items()
                        if k in ("auth_token", "ct0")}
        logger.info("[tweet] === 完整请求信息 ===")
        logger.info("[tweet] URL: %s", CREATE_TWEET_ENDPOINT)
        logger.info("[tweet] Headers: %s", json.dumps(safe_headers, indent=2))
        logger.info("[tweet] Cookies (摘要): %s", json.dumps(safe_cookies))
        logger.info("[tweet] Payload: %s", json.dumps(payload, ensure_ascii=False))

        # Anti-detection: random delay before posting (simulate human typing/review)
        delay = random.uniform(1.5, 4.0)
        logger.debug("[tweet] 发布前随机延迟 %.1fs (反检测)", delay)
        time.sleep(delay)

        t0 = time.time()
        resp = self._http.post(
            CREATE_TWEET_ENDPOINT,
            json=payload,
            headers=headers,
            cookies=cookies,
            timeout=API_TIMEOUT,
        )
        elapsed = int((time.time() - t0) * 1000)

        # Log full response details
        resp_headers = dict(resp.headers)
        logger.info("[tweet] === 完整响应信息 ===")
        logger.info("[tweet] Status: %d (%dms)", resp.status_code, elapsed)
        logger.info("[tweet] Response Headers: %s", json.dumps(resp_headers, indent=2))
        logger.info("[tweet] Response Body (完整): %s", resp.text)

        if resp.status_code != 200:
            raise RuntimeError(
                f"CreateTweet 失败 (HTTP {resp.status_code}): {resp.text[:500]}"
            )

        data = resp.json()

        if "errors" in data:
            errors = data["errors"]
            msg = errors[0].get("message", str(errors[0])) if errors else "Unknown error"
            error_detail = json.dumps(data, ensure_ascii=False)
            raise RuntimeError(f"Twitter GraphQL 错误: {msg} | 完整响应: {error_detail}")

        result = data.get("data", {}).get("create_tweet", {}).get("tweet_results", {}).get("result", {})
        tweet_id = result.get("rest_id")
        if not tweet_id:
            legacy = result.get("legacy", {})
            tweet_id = legacy.get("id_str") or result.get("rest_id")

        if not tweet_id:
            logger.warning("[tweet] 无法从响应中提取 tweet_id, 完整响应: %s", json.dumps(data)[:1000])
            raise RuntimeError("发布似乎成功但无法提取推文ID")

        screen_name = self.account.get("account", "i")
        tweet_url = f"https://x.com/{screen_name}/status/{tweet_id}"
        logger.info("[tweet] 发布成功! tweet_id=%s, url=%s", tweet_id, tweet_url)
        return {"tweet_id": str(tweet_id), "tweet_url": tweet_url}

    # ---- high-level async wrappers ----------------------------------------

    async def upload_media_file(self, file_path: str) -> str:
        return await asyncio.to_thread(self._upload_media_sync, file_path)

    async def publish_tweet(
        self,
        text: str = "",
        media_paths: list[str] | None = None,
        is_sensitive: bool = False,
    ) -> dict[str, Any]:
        media_ids: list[str] = []
        if media_paths:
            for i, mp in enumerate(media_paths):
                logger.debug("[tweet] 上传媒体 [%d/%d]: %s", i + 1, len(media_paths), mp)
                mid = await self.upload_media_file(mp)
                media_ids.append(mid)
            logger.info("[tweet] 全部媒体上传完成, media_ids=%s", media_ids)
        return await asyncio.to_thread(
            self._publish_tweet_sync, text, media_ids or None, is_sensitive
        )


# ---------------------------------------------------------------------------
# High-level convenience function (used by scheduler & API routes)
# ---------------------------------------------------------------------------

async def publish_single_tweet(account_id: str, content: dict[str, Any]) -> dict[str, Any]:
    logger.info("=" * 60)
    logger.info("[publish] 开始执行发布流程: account_id=%s", account_id)
    logger.debug("[publish] content: text=%.100s, media_paths=%s, is_sensitive=%s",
                 content.get("text", ""), content.get("media_paths"), content.get("is_sensitive"))

    lock = _get_account_lock(account_id)
    logger.debug("[publish] 等待账号锁...")
    async with lock:
        logger.debug("[publish] 已获取账号锁")
        t_start = time.time()
        try:
            session = await get_or_create_session(account_id)
            result = await session.publish_tweet(
                text=content.get("text", ""),
                media_paths=content.get("media_paths"),
                is_sensitive=content.get("is_sensitive", False),
            )
            elapsed = time.time() - t_start
            logger.info("[publish] 发布成功! 耗时=%.1fs, tweet_id=%s, url=%s",
                        elapsed, result.get("tweet_id"), result.get("tweet_url"))
            return {"success": True, **result}

        except Exception as exc:
            elapsed = time.time() - t_start
            tb_text = traceback.format_exc()
            logger.error("[publish] 发布流程异常 (耗时=%.1fs): %s [%s]\n%s",
                         elapsed, exc, type(exc).__name__, tb_text)

            entry = _session_pool.pop(account_id, None)
            if entry:
                logger.debug("[publish] 清理失败的会话缓存")
                entry.session.close()

            err = classify_error(exc)
            # Attach full error message (may contain raw response)
            err["raw_error"] = str(exc)
            err["traceback"] = tb_text
            logger.warning("[publish] 错误分类: code=%s, retryable=%s, message=%s",
                           err["code"], err.get("retryable"), err.get("message"))

            if err["code"] == "proxy_error":
                try:
                    account = get_account_record(account_id)
                    aid = str((account or {}).get("id", "")).strip()
                    platform = str((account or {}).get("platform", "")).lower()
                    bindings = list_account_bindings()
                    binding = next(
                        (b for b in bindings
                         if str(b.get("account_uid", "")).strip() == aid
                         and str(b.get("platform", "")).lower() == platform),
                        None,
                    )
                    if binding:
                        update_proxy_record(binding["proxy_id"], status="dead")
                        logger.warning("[publish] 代理 %s 已标记为 dead", binding["proxy_id"])
                except Exception as mark_exc:
                    logger.error("[publish] 标记代理 dead 失败: %s", mark_exc)

            if err["code"] in ("unauthorized", "account_suspended", "account_locked"):
                try:
                    from account_store import update_account_record
                    update_account_record(account_id, status="abnormal")
                    logger.warning("[publish] 账号 %s 已标记为 abnormal (reason=%s)",
                                   account_id, err["code"])
                except Exception as mark_exc:
                    logger.error("[publish] 标记账号 abnormal 失败: %s", mark_exc)

            logger.info("[publish] 返回失败结果: %s", err)
            return {"success": False, **err}

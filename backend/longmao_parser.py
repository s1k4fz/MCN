import base64
import json
import random
import struct
import time
from pathlib import Path
from typing import Any

import msgpack
import requests


# ---------------------------------------------------------------------------
# 纯 Python XXTEA（兼容任意长度 key，与 JS 版行为一致）
# ---------------------------------------------------------------------------

def _to_uint32_array(data: bytes, include_length: bool) -> list[int]:
    n = len(data)
    m = (n + 3) // 4
    result = list(struct.unpack(f"<{m}I", data.ljust(m * 4, b'\x00')))
    if include_length:
        result.append(n)
    return result


def _to_bytes(v: list[int], include_length: bool) -> bytes:
    n = len(v)
    raw = struct.pack(f"<{n}I", *v)
    if include_length:
        m = v[-1]
        if m < 0 or m > (n - 1) * 4 or m < (n - 2) * 4:
            return b""
        return raw[:m]
    return raw


def _xxtea_encrypt_raw(v: list[int], k: list[int]) -> list[int]:
    n = len(v)
    if n < 2:
        return v
    DELTA = 0x9E3779B9
    q = 6 + 52 // n
    z = v[n - 1]
    total = 0
    for _ in range(q):
        total = (total + DELTA) & 0xFFFFFFFF
        e = (total >> 2) & 3
        for p in range(n):
            y = v[(p + 1) % n]
            mx = (((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4))) ^ ((total ^ y) + (k[(p & 3) ^ e] ^ z))
            v[p] = (v[p] + mx) & 0xFFFFFFFF
            z = v[p]
    return v


def _xxtea_decrypt_raw(v: list[int], k: list[int]) -> list[int]:
    n = len(v)
    if n < 2:
        return v
    DELTA = 0x9E3779B9
    q = 6 + 52 // n
    total = (q * DELTA) & 0xFFFFFFFF
    y = v[0]
    for _ in range(q):
        e = (total >> 2) & 3
        for p in range(n - 1, -1, -1):
            z = v[(p - 1) % n]
            mx = (((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4))) ^ ((total ^ y) + (k[(p & 3) ^ e] ^ z))
            v[p] = (v[p] - mx) & 0xFFFFFFFF
            y = v[p]
        total = (total - DELTA) & 0xFFFFFFFF
    return v


def _prepare_key(key: bytes) -> list[int]:
    """将任意长度 key 转为 4 个 uint32（与 JS 版一致：截断或补零到 16 字节）"""
    if len(key) < 16:
        key = key.ljust(16, b'\x00')
    return list(struct.unpack("<4I", key[:16]))


def xxtea_encrypt(data: bytes, key: bytes) -> bytes:
    v = _to_uint32_array(data, True)
    k = _prepare_key(key)
    return _to_bytes(_xxtea_encrypt_raw(v, k), False)


def xxtea_decrypt(data: bytes, key: bytes) -> bytes:
    v = _to_uint32_array(data, False)
    k = _prepare_key(key)
    return _to_bytes(_xxtea_decrypt_raw(v, k), True)

# ==========================================
# Token 管理（优先从 runtime 文件加载）
# ==========================================

_BASE_DIR = Path(__file__).resolve().parent
_RUNTIME_DIR = _BASE_DIR / "runtime"
_TOKEN_FILE = _RUNTIME_DIR / "longmao_token.txt"

_HARDCODED_TOKEN = "oBp%2BUVvG1q6ZDpxmAWITPXUeseRtWag4ODC%2BDYybim79dDQhFfJqkhLE2c0fleF3y07zkOegpDxLHmx3%2Fe1AOAsXdM9qLpvx"


def _load_longmao_token() -> str:
    if _TOKEN_FILE.exists():
        try:
            text = _TOKEN_FILE.read_text(encoding="utf-8").strip()
            if text:
                return text
        except Exception:
            pass
    return _HARDCODED_TOKEN


MY_REAL_TOKEN = _load_longmao_token()

# 密钥配置
REQUEST_KEY = "H#ufB@O1G5Rxnkm#hd@k76"
RESPONSE_KEY = "0C9FEBHwd*qsd@k128l"
PARSE_URL = "https://api.xiaoxiaobite.com/api/v3/parse/web/single-source?app_key=web_token"


def get_parse_payload(video_url: str) -> dict[str, Any]:
    return {
        "lan": "zh_Hans",
        "platform": "web",
        "package": "longmao_web",
        "nonce": str(random.random()),
        "time_zone": -480,
        "time_stamp": int(time.time()),
        "logined": True,
        "token": _load_longmao_token(),
        "debug": False,
        "content": video_url,
    }


def encrypt_data(data: dict[str, Any]) -> str:
    packed = msgpack.packb(data)
    encrypted = xxtea_encrypt(packed, REQUEST_KEY.encode("utf-8"))
    return base64.b64encode(encrypted).decode("utf-8")


def decrypt_response(text_response: str) -> dict[str, Any] | None:
    try:
        binary = base64.b64decode(text_response)
        decrypted = xxtea_decrypt(binary, RESPONSE_KEY.encode("utf-8"))
        return msgpack.unpackb(decrypted, raw=False) if decrypted else None
    except Exception:
        return None


def normalize_platform_type(platform_type: Any) -> str:
    normalized = str(platform_type or "").strip().lower()
    if "bilibili" in normalized:
        return "bilibili"
    if "douyin" in normalized or "iesdouyin" in normalized or "aweme" in normalized:
        return "douyin"
    if "xiaohongshu" in normalized or "xhs" in normalized:
        return "xiaohongshu"
    return "unknown"


def _empty_extracted() -> dict[str, Any]:
    return {
        "type": "unknown",
        "title": "未命名作品",
        "cover": None,
        "videos": [],
        "images": [],
        "audio": None,
    }


def _clean_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split()).strip()


def _append_unique(values: list[str], value: Any) -> None:
    if not isinstance(value, str):
        return
    normalized = value.strip()
    if not normalized:
        return
    if normalized not in values:
        values.append(normalized)


def _extract_urls_from_section(section: Any) -> list[str]:
    urls: list[str] = []
    if not isinstance(section, dict):
        return urls

    _append_unique(urls, section.get("source_url"))

    source_list = section.get("source_list")
    if isinstance(source_list, list):
        for item in source_list:
            if isinstance(item, str):
                _append_unique(urls, item)
            elif isinstance(item, dict):
                _append_unique(urls, item.get("source_url"))

    return urls


def _extract_work_video_urls(section: Any) -> list[str]:
    urls: list[str] = []
    if not isinstance(section, dict):
        return urls

    items = section.get("list")
    if not isinstance(items, list):
        return urls

    for item in items:
        if not isinstance(item, dict):
            continue
        _append_unique(urls, item.get("video_url"))
    return urls


def extract_bilibili_info(raw_info: Any) -> dict[str, Any]:
    """
    仅处理 B 站字段映射：
    - 通过子结构中的 title 字段区分直链类型（视频/音频/封面）
    - 文案标题优先使用 text.text
    """
    extracted = _empty_extracted()
    if not isinstance(raw_info, dict):
        return extracted

    text_obj = raw_info.get("text")
    if isinstance(text_obj, dict):
        content_title = _clean_text(text_obj.get("text"))
        if content_title:
            extracted["title"] = content_title

    for section in raw_info.values():
        if not isinstance(section, dict):
            continue

        section_title = _clean_text(section.get("title"))
        source_url = section.get("source_url")
        if not isinstance(source_url, str) or not source_url.strip():
            continue

        source_url = source_url.strip()
        if "视频" in section_title:
            extracted["videos"].append(source_url)
        elif "音频" in section_title:
            if not extracted["audio"]:
                extracted["audio"] = source_url
        elif "封面" in section_title:
            if not extracted["cover"]:
                extracted["cover"] = source_url

    if not extracted["cover"]:
        cover_obj = raw_info.get("cover")
        if isinstance(cover_obj, dict):
            cover_url = cover_obj.get("source_url")
            if isinstance(cover_url, str) and cover_url.strip():
                extracted["cover"] = cover_url.strip()

    if not extracted["videos"]:
        video_obj = raw_info.get("video")
        if isinstance(video_obj, dict):
            video_url = video_obj.get("source_url")
            if isinstance(video_url, str) and video_url.strip():
                extracted["videos"].append(video_url.strip())

    if not extracted["audio"]:
        audio_obj = raw_info.get("audio")
        if isinstance(audio_obj, dict):
            audio_url = audio_obj.get("source_url")
            if isinstance(audio_url, str) and audio_url.strip():
                extracted["audio"] = audio_url.strip()

    # 去重，避免同一视频链重复入列
    deduped_videos: list[str] = []
    seen: set[str] = set()
    for url in extracted["videos"]:
        if url not in seen:
            seen.add(url)
            deduped_videos.append(url)
    extracted["videos"] = deduped_videos

    if extracted["videos"]:
        extracted["type"] = "video"

    return extracted


def extract_xiaohongshu_info(raw_info: Any) -> dict[str, Any]:
    """
    小红书字段映射：
    - 视频作品：video/audio/cover/text
    - 图文作品：album/cover/text
    - 通过子结构 title（例如：视频下载/音频下载/高清图集/高清封面）作为第一识别依据
    """
    extracted = _empty_extracted()
    if not isinstance(raw_info, dict):
        return extracted

    text_obj = raw_info.get("text")
    if isinstance(text_obj, dict):
        content_title = _clean_text(text_obj.get("text"))
        if content_title:
            extracted["title"] = content_title

    for section in raw_info.values():
        if not isinstance(section, dict):
            continue

        section_title = _clean_text(section.get("title"))
        section_urls = _extract_urls_from_section(section)
        if not section_urls:
            continue

        if "视频" in section_title:
            for media_url in section_urls:
                _append_unique(extracted["videos"], media_url)
        elif "音频" in section_title:
            if not extracted["audio"]:
                extracted["audio"] = section_urls[0]
        elif "封面" in section_title:
            if not extracted["cover"]:
                extracted["cover"] = section_urls[0]
        elif "图集" in section_title or "图片" in section_title:
            for image_url in section_urls:
                _append_unique(extracted["images"], image_url)

    # fallback: cover/video/audio/images
    if not extracted["cover"]:
        cover_obj = raw_info.get("cover")
        cover_urls = _extract_urls_from_section(cover_obj)
        if cover_urls:
            extracted["cover"] = cover_urls[0]

    if not extracted["videos"]:
        video_obj = raw_info.get("video")
        for video_url in _extract_urls_from_section(video_obj):
            _append_unique(extracted["videos"], video_url)

    if not extracted["audio"]:
        audio_obj = raw_info.get("audio")
        audio_urls = _extract_urls_from_section(audio_obj)
        if audio_urls:
            extracted["audio"] = audio_urls[0]

    if not extracted["images"]:
        album_obj = raw_info.get("album")
        for image_url in _extract_urls_from_section(album_obj):
            _append_unique(extracted["images"], image_url)

    if extracted["videos"]:
        extracted["type"] = "video"
    elif extracted["images"]:
        extracted["type"] = "images"

    return extracted


def extract_douyin_info(raw_info: Any) -> dict[str, Any]:
    """
    抖音字段映射（重点规则）：
    - title = 视频下载：普通视频
    - title = 高清图集：图片
    - title = 多视频下载：实况图片对应的小视频（来自 work.list[].video_url）
    """
    extracted = _empty_extracted()
    if not isinstance(raw_info, dict):
        return extracted

    text_obj = raw_info.get("text")
    if isinstance(text_obj, dict):
        content_title = _clean_text(text_obj.get("text"))
        if content_title:
            extracted["title"] = content_title

    normal_video_urls: list[str] = []
    live_photo_video_urls: list[str] = []

    for section in raw_info.values():
        if not isinstance(section, dict):
            continue

        section_title = _clean_text(section.get("title"))
        if not section_title:
            continue

        section_urls = _extract_urls_from_section(section)

        if "多视频下载" in section_title:
            # 多视频下载专指实况图片的小视频片段
            for media_url in section_urls:
                _append_unique(live_photo_video_urls, media_url)
            for media_url in _extract_work_video_urls(section):
                _append_unique(live_photo_video_urls, media_url)
            continue

        if "视频下载" in section_title:
            for media_url in section_urls:
                _append_unique(normal_video_urls, media_url)
        elif "图集" in section_title or "图片" in section_title:
            for image_url in section_urls:
                _append_unique(extracted["images"], image_url)
        elif "音频" in section_title:
            if not extracted["audio"] and section_urls:
                extracted["audio"] = section_urls[0]
        elif "封面" in section_title:
            if not extracted["cover"] and section_urls:
                extracted["cover"] = section_urls[0]

    # fallback
    if not normal_video_urls:
        for video_url in _extract_urls_from_section(raw_info.get("video")):
            _append_unique(normal_video_urls, video_url)

    if not extracted["images"]:
        for image_url in _extract_urls_from_section(raw_info.get("album")):
            _append_unique(extracted["images"], image_url)

    if not live_photo_video_urls:
        for video_url in _extract_work_video_urls(raw_info.get("work")):
            _append_unique(live_photo_video_urls, video_url)

    if not extracted["cover"]:
        cover_urls = _extract_urls_from_section(raw_info.get("cover"))
        if cover_urls:
            extracted["cover"] = cover_urls[0]

    if not extracted["audio"]:
        audio_urls = _extract_urls_from_section(raw_info.get("audio"))
        if audio_urls:
            extracted["audio"] = audio_urls[0]

    # 合并视频列表：普通视频 + 实况小视频
    for media_url in normal_video_urls:
        _append_unique(extracted["videos"], media_url)
    for media_url in live_photo_video_urls:
        _append_unique(extracted["videos"], media_url)

    # 类型优先级：实况 > 普通视频 > 图集
    if live_photo_video_urls:
        extracted["type"] = "live_photo"
    elif normal_video_urls:
        extracted["type"] = "video"
    elif extracted["images"]:
        extracted["type"] = "images"

    return extracted


def build_extracted_from_raw(raw_data: Any) -> tuple[str, dict[str, Any]]:
    platform_type_raw = raw_data.get("platform_type") if isinstance(raw_data, dict) else None
    platform_type = normalize_platform_type(platform_type_raw)
    raw_info = raw_data.get("info") if isinstance(raw_data, dict) else None

    if platform_type == "bilibili":
        return platform_type, extract_bilibili_info(raw_info)
    if platform_type == "xiaohongshu":
        return platform_type, extract_xiaohongshu_info(raw_info)
    if platform_type == "douyin":
        return platform_type, extract_douyin_info(raw_info)

    return platform_type, _empty_extracted()


def parse_content_data(url: str) -> dict[str, Any]:
    """
    纯原始解析接口（不做任何平台字段提取）：
    - 仅负责请求 + 解密 + 返回原始 JSON
    - 供后续按平台单独适配字段
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Content-Type": "text/plain;charset=UTF-8",
    }
    try:
        payload = get_parse_payload(url)
        encrypted_body = encrypt_data(payload)
        response = requests.post(
            PARSE_URL,
            data=encrypted_body,
            headers=headers,
            timeout=45,
        )

        if response.status_code != 200:
            return {
                "ok": False,
                "error": f"网络错误: {response.status_code}",
                "url": url,
            }

        res_json = decrypt_response(response.text)
        if not res_json:
            return {
                "ok": False,
                "error": "响应解密失败",
                "url": url,
            }

        if res_json.get("code") != 200:
            return {
                "ok": False,
                "error": f"业务报错: {res_json.get('msg')}",
                "url": url,
                "raw_response": res_json,
            }

        raw_data = res_json.get("data")
        raw_info = raw_data.get("info") if isinstance(raw_data, dict) else None
        platform_type, extracted = build_extracted_from_raw(raw_data)

        return {
            "ok": True,
            "url": url,
            "raw_response": res_json,
            "raw_data": raw_data,
            "raw_info": raw_info,
            "platform_type": platform_type,
            "platform_type_raw": raw_data.get("platform_type") if isinstance(raw_data, dict) else None,
            "extracted": extracted,
        }
    except requests.RequestException as e:
        return {
            "ok": False,
            "error": f"请求异常: {e}",
            "url": url,
        }
    except Exception as e:
        return {
            "ok": False,
            "error": f"代码异常: {e}",
            "url": url,
        }


def parse_content(url: str) -> None:
    print(f"[*] 正在解析: {url}")
    parsed = parse_content_data(url)
    if not parsed.get("ok"):
        print(f"❌ {parsed.get('error')}")
        return

    print("\n✅ === 原始响应 JSON（未做字段提取）===\n")
    print(json.dumps(parsed.get("raw_response", {}), ensure_ascii=False, indent=2))
    print("\n✅ === 当前提取结果（B站 + 小红书 + 抖音已适配）===\n")
    print(json.dumps(parsed.get("extracted", {}), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    test_url = "6.48 她是个十七岁的小女孩 再不用我就18了# 08 # 萌妹子 # 女高中生  https://v.douyin.com/gjUDCr8qFtQ/ 复制此链接，打开抖音搜索，直接观看视频！ sre:/ N@J.vf 07/31 "
    parse_content(test_url)
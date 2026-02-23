import requests
import time
import hashlib
import urllib.parse
import os
from functools import reduce
import random
import datetime
import re
import json
from pathlib import Path

# ==========================================
# Cookie 加载: runtime 文件 → 环境变量（无硬编码）
# ==========================================

_BASE_DIR = Path(__file__).resolve().parent
_RUNTIME_DIR = _BASE_DIR / "runtime"
_COOKIE_FILE = _RUNTIME_DIR / "bilibili_cookie.txt"


def _load_cookie() -> str:
    """优先 runtime 文件 → 环境变量，未配置则返回空字符串"""
    if _COOKIE_FILE.exists():
        try:
            text = _COOKIE_FILE.read_text(encoding="utf-8").strip()
            if text:
                return text
        except Exception:
            pass
    return os.getenv("BILIBILI_COOKIE", "").strip()


def _cookie_source() -> str:
    """返回当前 cookie 来源标识"""
    if _COOKIE_FILE.exists():
        try:
            if _COOKIE_FILE.read_text(encoding="utf-8").strip():
                return "auto"
        except Exception:
            pass
    if os.getenv("BILIBILI_COOKIE", "").strip():
        return "env"
    return "none"


MY_COOKIE = _load_cookie()
# ==========================================

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.bilibili.com/",
    "Cookie": MY_COOKIE
}


def update_cookie(new_cookie: str) -> None:
    """运行时热更新 cookie（由 app.py 调用）"""
    global MY_COOKIE
    MY_COOKIE = new_cookie.strip()
    HEADERS["Cookie"] = MY_COOKIE
    _RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    _COOKIE_FILE.write_text(MY_COOKIE, encoding="utf-8")


def get_cookie_info() -> dict:
    """返回当前 cookie 状态信息"""
    keys = [k.strip().split("=")[0] for k in MY_COOKIE.split(";") if "=" in k]
    return {
        "is_set": bool(MY_COOKIE),
        "source": _cookie_source(),
        "keys": keys,
        "key_count": len(keys),
        "has_sessdata": any(k.upper() == "SESSDATA" for k in keys),
        "has_buvid": any(k.startswith("buvid") for k in keys),
    }

class BilibiliCrawler:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.last_error = None
        self.mixin_key = self.get_mixin_key()
        self.is_logged_in = None
        self.login_user = None
        self._checked_login_state = False

    def _trim_text(self, value, limit=800):
        text = str(value)
        if len(text) <= limit:
            return text
        return text[:limit] + "...(truncated)"

    def _set_last_error(self, stage, message, **extra):
        self.last_error = {
            "stage": stage,
            "message": message,
            "timestamp": int(time.time()),
            **extra,
        }

    def _ensure_login_state(self):
        if self._checked_login_state:
            return
        self._checked_login_state = True
        try:
            resp = self.session.get("https://api.bilibili.com/x/web-interface/nav", timeout=20)
            payload = resp.json()
            data = payload.get("data") if isinstance(payload, dict) else {}
            self.is_logged_in = bool(data.get("isLogin"))
            self.login_user = data.get("uname")
            if self.is_logged_in:
                print(f"🔐 B站会话已登录: {self.login_user or 'Unknown'}")
            else:
                print("⚠️ B站会话未登录，播放地址通常会被限制在 480P 左右。")
        except Exception as e:
            self.is_logged_in = False
            self.login_user = None
            print(f"⚠️ B站登录态检测失败: {e}")

    def get_mixin_key(self):
        try:
            resp = self.session.get("https://api.bilibili.com/x/web-interface/nav", timeout=20)
            res_json = resp.json()
            wbi_img = res_json['data']['wbi_img']
            img_key = wbi_img['img_url'].rsplit('/', 1)[1].split('.')[0]
            sub_key = wbi_img['sub_url'].rsplit('/', 1)[1].split('.')[0]
            
            mixin_key_enc_tab = [
                46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
                33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
                61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
                36, 20, 34, 44, 52
            ]
            raw_wbi_key = img_key + sub_key
            key = reduce(lambda s, i: s + raw_wbi_key[i], mixin_key_enc_tab, '')[:32]
            return key
        except Exception as e:
            self._set_last_error(
                stage="get_mixin_key",
                message=f"获取 wbi mixin_key 失败: {e}",
            )
            print(f"❌ 获取 wbi mixin_key 失败: {e}")
            return None

    def enc_wbi(self, params: dict):
        mixin_key = self.mixin_key
        if not mixin_key:
            self._set_last_error(
                stage="enc_wbi",
                message="mixin_key 为空，无法生成 w_rid 签名",
            )
            raise RuntimeError("mixin_key 为空，无法生成 w_rid 签名")
        curr_time = round(time.time())
        params['wts'] = curr_time
        params = dict(sorted(params.items()))
        params = {k: ''.join(filter(lambda chr: chr not in "!'()*", str(v))) for k, v in params.items()}
        query = urllib.parse.urlencode(params)
        wbi_sign = hashlib.md5((query + mixin_key).encode()).hexdigest()
        params['w_rid'] = wbi_sign
        return params

    def get_user_info(self, uid):
        """
        🎯 新增功能：获取UP主信息（包含粉丝数）
        接口：/x/web-interface/card
        """
        print(f"[*] 正在获取 UP主 (UID:{uid}) 的粉丝数信息...")
        try:
            url = "https://api.bilibili.com/x/web-interface/card"
            params = {"mid": uid, "photo": 1}
            resp = self.session.get(url, params=params, timeout=20)
            data = resp.json()
            if data['code'] == 0:
                card = data['data']['card']
                print(f"   ✅ 昵称: {card['name']} | 粉丝数: {card['fans']}")
                return {
                    "mid": card['mid'],
                    "name": card['name'],
                    "face": card['face'],
                    "fans": card['fans'], # 粉丝数在这里！
                    "sign": card['sign']
                }
            print(
                f"❌ 获取UP主信息失败: code={data.get('code')} "
                f"message={data.get('message') or data.get('msg')}"
            )
        except Exception as e:
            print(f"❌ 获取用户信息失败: {e}")
        return {"mid": uid, "name": "Unknown", "face": "", "fans": 0, "sign": ""}

    def get_video_detail(self, bvid, user_info):
        """
        获取单个视频详情，并合并UP主信息
        """
        url = "https://api.bilibili.com/x/web-interface/view"
        params = {"bvid": bvid}
        
        try:
            resp = self.session.get(url, params=params, timeout=20)
            data = resp.json()
            
            if data['code'] == 0:
                info = data['data']
                stat = info['stat']
                
                # 格式化时间
                pub_date = datetime.datetime.fromtimestamp(info['pubdate']).strftime('%Y-%m-%d %H:%M:%S')
                
                # 整理你要求的所有字段
                video_data = {
                    "bvid": bvid,
                    "link": f"https://www.bilibili.com/video/{bvid}",
                    "title": info['title'],
                    "desc": info['desc'], # 描述/正文
                    "pub_time": pub_date, # 发布时间
                    "cover": info['pic'], # 封面图
                    "tname": info['tname'], # 分区/标签类型
                    
                    # 标签/话题 (API返回的是dynamic字符串，或者需要单独接口，这里暂取分区名和简介)
                    # 如果需要精准tag，需要请求 /x/web-interface/view/detail/tag，这里为了速度暂略
                    
                    # 互动数据
                    "view": stat['view'],     # 播放
                    "danmaku": stat['danmaku'], # 弹幕
                    "reply": stat['reply'],   # 评论
                    "favorite": stat['favorite'], # 收藏
                    "coin": stat['coin'],     # 投币
                    "share": stat['share'],   # 转发
                    "like": stat['like'],      # 点赞
                    
                    # 创作者信息 (从外部传进来，因为粉丝数不在 view 接口里)
                    "author_name": user_info['name'],
                    "author_face": user_info['face'],
                    "author_fans": user_info['fans']
                }
                return video_data
            print(
                f"   ⚠️ 获取详情失败 {bvid}: code={data.get('code')} "
                f"message={data.get('message') or data.get('msg')}"
            )
            return None
        except Exception as e:
            print(f"   ⚠️ 获取详情失败 {bvid}: {e}")
            return None

    def extract_bvid(self, text):
        """
        从任意文本/链接中提取 BV 号
        """
        if not text:
            return None
        match = re.search(r"(BV[0-9A-Za-z]{10})", str(text))
        return match.group(1) if match else None

    def resolve_bvid_from_url(self, video_url):
        """
        支持 b23.tv 短链 / 常规链接，最终提取 BV 号
        """
        bvid = self.extract_bvid(video_url)
        if bvid:
            return bvid

        try:
            # 某些分享链接（如 b23）需要跟随重定向后才能拿到 BV
            resp = self.session.get(video_url, timeout=20, allow_redirects=True)
            bvid = self.extract_bvid(resp.url)
            if bvid:
                return bvid
        except Exception as e:
            print(f"⚠️ 解析分享链接失败: {e}")

        return None

    def get_single_video_detail_by_url(self, video_url):
        """
        单条视频详情入口：
        1) 解析 BV
        2) 先拿 owner mid
        3) 拉取 UP 主信息（含粉丝）
        4) 复用 get_video_detail 返回标准字段
        """
        bvid = self.resolve_bvid_from_url(video_url)
        if not bvid:
            print(f"❌ 无法从链接中提取 BV 号: {video_url}")
            return None

        owner_mid = None
        try:
            resp = self.session.get(
                "https://api.bilibili.com/x/web-interface/view",
                params={"bvid": bvid},
                timeout=20,
            )
            data = resp.json()
            if data.get("code") == 0:
                owner_mid = data.get("data", {}).get("owner", {}).get("mid")
        except Exception as e:
            print(f"⚠️ 获取视频 owner 信息失败 {bvid}: {e}")

        user_info = {"mid": owner_mid or 0, "name": "Unknown", "face": "", "fans": 0, "sign": ""}
        if owner_mid:
            user_info = self.get_user_info(owner_mid)

        return self.get_video_detail(bvid, user_info)

    def _safe_int(self, value):
        try:
            return int(value)
        except Exception:
            return 0

    def _stream_url_from_item(self, item):
        if not isinstance(item, dict):
            return None
        for key in ("baseUrl", "base_url", "url"):
            url = item.get(key)
            if isinstance(url, str) and url.strip():
                return url.strip()
        for key in ("backupUrl", "backup_url"):
            backup = item.get(key)
            if isinstance(backup, list) and backup:
                first = backup[0]
                if isinstance(first, str) and first.strip():
                    return first.strip()
        return None

    def _pick_best_dash_video(self, videos):
        if not isinstance(videos, list):
            return None

        candidates = []
        for item in videos:
            if not isinstance(item, dict):
                continue
            stream_url = self._stream_url_from_item(item)
            if not stream_url:
                continue

            width = self._safe_int(item.get("width"))
            height = self._safe_int(item.get("height"))
            quality_id = self._safe_int(item.get("id"))
            bandwidth = self._safe_int(item.get("bandwidth"))

            # 分辨率优先，再按 quality id / 码率兜底
            score = (width * height, height, width, quality_id, bandwidth)
            candidates.append((score, item))

        if not candidates:
            return None

        candidates.sort(key=lambda pair: pair[0], reverse=True)
        return candidates[0][1]

    def _pick_best_dash_audio(self, audios):
        if not isinstance(audios, list):
            return None

        candidates = []
        for item in audios:
            if not isinstance(item, dict):
                continue
            stream_url = self._stream_url_from_item(item)
            if not stream_url:
                continue

            bandwidth = self._safe_int(item.get("bandwidth"))
            quality_id = self._safe_int(item.get("id"))
            score = (bandwidth, quality_id)
            candidates.append((score, item))

        if not candidates:
            return None

        candidates.sort(key=lambda pair: pair[0], reverse=True)
        return candidates[0][1]

    def get_best_media_urls_by_bvid(self, bvid):
        """
        获取单个 B 站视频可用的最高画质直链（优先 dash，兜底 durl）。
        """
        self.last_error = None
        bvid = str(bvid or "").strip()
        if not bvid:
            error_msg = "bvid 为空，无法获取播放地址"
            self._set_last_error(stage="get_best_media_urls_by_bvid", message=error_msg)
            return {"ok": False, "error": error_msg}

        self._ensure_login_state()

        # 1) 先拿 cid
        view_url = "https://api.bilibili.com/x/web-interface/view"
        view_params = {"bvid": bvid}
        try:
            view_resp = self.session.get(view_url, params=view_params, timeout=25)
            view_resp.raise_for_status()
            view_data = view_resp.json()
        except Exception as e:
            error_msg = f"获取 view 信息失败: {e}"
            self._set_last_error(
                stage="get_best_media_urls_by_bvid",
                message=error_msg,
                bvid=bvid,
                request_url=view_url,
                request_params=view_params,
            )
            return {"ok": False, "error": error_msg}

        if view_data.get("code") != 0:
            message = view_data.get("message") or view_data.get("msg") or "未知错误"
            code = view_data.get("code")
            error_msg = f"view 接口报错: {message}"
            self._set_last_error(
                stage="get_best_media_urls_by_bvid",
                message=error_msg,
                code=code,
                bvid=bvid,
                request_url=view_url,
                request_params=view_params,
                response_data=view_data.get("data"),
            )
            return {"ok": False, "error": f"{error_msg} (code={code})"}

        view_body = view_data.get("data") or {}
        cid = view_body.get("cid")
        if not cid:
            pages = view_body.get("pages")
            if isinstance(pages, list) and pages:
                first = pages[0]
                if isinstance(first, dict):
                    cid = first.get("cid")
        if not cid:
            error_msg = "未找到 cid，无法获取播放地址"
            self._set_last_error(
                stage="get_best_media_urls_by_bvid",
                message=error_msg,
                bvid=bvid,
                response_data=view_body,
            )
            return {"ok": False, "error": error_msg}

        # 2) 请求播放地址（尽量要求最高画质）
        playurl_url = "https://api.bilibili.com/x/player/playurl"
        playurl_params = {
            "bvid": bvid,
            "cid": cid,
            "qn": 127,     # 请求高画质上限
            "fnver": 0,
            "fnval": 4048, # dash + 高编码能力
            "fourk": 1,
        }
        try:
            play_resp = self.session.get(playurl_url, params=playurl_params, timeout=25)
            play_resp.raise_for_status()
            play_json = play_resp.json()
        except Exception as e:
            error_msg = f"获取 playurl 失败: {e}"
            self._set_last_error(
                stage="get_best_media_urls_by_bvid",
                message=error_msg,
                bvid=bvid,
                cid=cid,
                request_url=playurl_url,
                request_params=playurl_params,
            )
            return {"ok": False, "error": error_msg}

        if play_json.get("code") != 0:
            message = play_json.get("message") or play_json.get("msg") or "未知错误"
            code = play_json.get("code")
            error_msg = f"playurl 接口报错: {message}"
            self._set_last_error(
                stage="get_best_media_urls_by_bvid",
                message=error_msg,
                code=code,
                bvid=bvid,
                cid=cid,
                request_url=playurl_url,
                request_params=playurl_params,
                response_data=play_json.get("data"),
            )
            return {"ok": False, "error": f"{error_msg} (code={code})"}

        play_data = play_json.get("data") or {}
        support_formats = play_data.get("support_formats") or []
        quality_label_map = {}
        if isinstance(support_formats, list):
            for fmt in support_formats:
                if not isinstance(fmt, dict):
                    continue
                qid = fmt.get("quality")
                label = (
                    fmt.get("new_description")
                    or fmt.get("display_desc")
                    or fmt.get("format")
                    or ""
                )
                if qid is not None and label:
                    quality_label_map[self._safe_int(qid)] = str(label)

        dash = play_data.get("dash") if isinstance(play_data.get("dash"), dict) else {}
        best_video = self._pick_best_dash_video(dash.get("video"))
        best_audio = self._pick_best_dash_audio(dash.get("audio"))

        if best_video:
            video_url = self._stream_url_from_item(best_video)
            audio_url = self._stream_url_from_item(best_audio)
            quality_id = self._safe_int(best_video.get("id"))
            width = self._safe_int(best_video.get("width"))
            height = self._safe_int(best_video.get("height"))
            bandwidth = self._safe_int(best_video.get("bandwidth"))
            quality_label = quality_label_map.get(quality_id, "")
            accept_quality = play_data.get("accept_quality") or []
            max_accept_quality = max(accept_quality) if accept_quality else quality_id
            quality_warning = None
            if quality_id < max_accept_quality:
                quality_warning = (
                    f"可请求上限 qn={max_accept_quality}，但接口实际返回最高 qn={quality_id}。"
                    "常见原因：Cookie 失效/未登录/账号无更高画质权限。"
                )
            return {
                "ok": True,
                "source": "dash",
                "bvid": bvid,
                "cid": cid,
                "video_url": video_url,
                "audio_url": audio_url,
                "quality_id": quality_id,
                "quality_label": quality_label,
                "width": width,
                "height": height,
                "video_bandwidth": bandwidth,
                "accept_quality": accept_quality,
                "accept_description": play_data.get("accept_description") or [],
                "quality_warning": quality_warning,
                "is_logged_in": self.is_logged_in,
                "login_user": self.login_user,
            }

        # dash 不可用时兜底 durl
        durl = play_data.get("durl")
        if isinstance(durl, list) and durl:
            first = durl[0]
            if isinstance(first, dict):
                video_url = first.get("url")
                if isinstance(video_url, str) and video_url.strip():
                    quality_id = self._safe_int(play_data.get("quality"))
                    quality_label = quality_label_map.get(quality_id, "")
                    return {
                        "ok": True,
                        "source": "durl",
                        "bvid": bvid,
                        "cid": cid,
                        "video_url": video_url.strip(),
                        "audio_url": None,
                        "quality_id": quality_id,
                        "quality_label": quality_label,
                        "width": 0,
                        "height": 0,
                        "video_bandwidth": 0,
                        "accept_quality": play_data.get("accept_quality") or [],
                        "accept_description": play_data.get("accept_description") or [],
                        "quality_warning": "当前使用 durl 回退链路，清晰度可能受限。",
                        "is_logged_in": self.is_logged_in,
                        "login_user": self.login_user,
                    }

        error_msg = "playurl 未返回可用视频直链（dash/durl 均为空）"
        self._set_last_error(
            stage="get_best_media_urls_by_bvid",
            message=error_msg,
            bvid=bvid,
            cid=cid,
            response_data=play_data,
        )
        return {"ok": False, "error": error_msg}

    def get_best_media_urls_by_url(self, video_url):
        bvid = self.resolve_bvid_from_url(video_url)
        if not bvid:
            error_msg = f"无法从链接中提取 BV 号: {video_url}"
            self._set_last_error(
                stage="get_best_media_urls_by_url",
                message=error_msg,
                source_url=video_url,
            )
            return {"ok": False, "error": error_msg}
        return self.get_best_media_urls_by_bvid(bvid)

    # 👇 我把名字改回 get_all_videos 了，这样你的 main.py 就不会报错了！
    def get_all_videos(self, uid):
        self.last_error = None
        # 1. 先获取UP主信息（粉丝数等）
        user_info = self.get_user_info(uid)
        
        print(f"[*] 正在扫描所有视频详情...")
        all_videos_detailed = []
        page = 1
        page_size = 30
        
        while True:
            # 搜索接口获取 BV 号列表
            url = "https://api.bilibili.com/x/space/wbi/arc/search"
            params = {
                "mid": uid, "ps": page_size, "tid": 0, "pn": page,
                "keyword": "", "order": "pubdate"
            }
            signed_params = self.enc_wbi(params)
            
            try:
                resp = self.session.get(url, params=signed_params, timeout=25)
                if resp.status_code != 200:
                    self._set_last_error(
                        stage="get_all_videos",
                        message=f"HTTP状态异常: {resp.status_code}",
                        uid=str(uid),
                        page=page,
                        request_url=url,
                    )
                    print(f"❌ API HTTP状态异常: {resp.status_code}")
                    print(f"   - UID: {uid} | 页码: {page}")
                    print(f"   - URL: {url}")
                    print(f"   - params: {self._trim_text(signed_params)}")
                    print(f"   - response: {self._trim_text(resp.text)}")
                    break
                data = resp.json()
                
                if data['code'] == 0:
                    vlist = data['data']['list']['vlist']
                    if not vlist: break
                        
                    print(f"   📄 第 {page} 页: 发现 {len(vlist)} 个视频，正在逐个获取详细数据...")
                    
                    for v in vlist:
                        bvid = v['bvid']
                        # 2. 调用详情接口，传入 UP主信息
                        detail = self.get_video_detail(bvid, user_info)
                        if detail:
                            all_videos_detailed.append(detail)
                        time.sleep(0.3) # 稍微快一点，0.3秒
                    
                    page += 1
                    time.sleep(1.5) 
                else:
                    message = data.get('message') or data.get('msg') or "未知错误"
                    code = data.get('code')
                    data_preview = self._trim_text(
                        json.dumps(data.get("data"), ensure_ascii=False)
                    )
                    self._set_last_error(
                        stage="get_all_videos",
                        message=f"API报错: {message}",
                        code=code,
                        uid=str(uid),
                        page=page,
                        request_url=url,
                        request_params=signed_params,
                        response_data=data.get("data"),
                    )
                    print(f"❌ API报错: {message}")
                    print(f"   - code: {code}")
                    print(f"   - uid: {uid}")
                    print(f"   - page: {page}")
                    print(f"   - request_url: {url}")
                    print(f"   - request_params: {self._trim_text(signed_params)}")
                    print(f"   - response.data: {data_preview}")
                    break
            except Exception as e:
                self._set_last_error(
                    stage="get_all_videos",
                    message=f"网络异常: {e}",
                    uid=str(uid),
                    page=page,
                    request_url=url,
                    request_params=signed_params,
                )
                print(f"❌ 网络异常: {e}")
                print(f"   - uid: {uid}")
                print(f"   - page: {page}")
                print(f"   - request_url: {url}")
                print(f"   - request_params: {self._trim_text(signed_params)}")
                break
                
        print(f"\n✅ 扫描完成！共获取 {len(all_videos_detailed)} 条详细数据。")
        return all_videos_detailed
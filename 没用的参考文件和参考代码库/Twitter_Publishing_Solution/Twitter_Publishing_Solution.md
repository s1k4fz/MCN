# MCN平台 - Twitter发布管理功能技术方案

## 一、方案概述

### 1.1 需求分析

根据需求文档，Twitter发布管理模块需要覆盖Twitter原生全部发布功能：

| 功能点 | 说明 | 优先级 | 实现难度 |
|--------|------|--------|----------|
| 发推文 | 纯文本推文（280字符限制） | P0 | ⭐ |
| 图片推文 | 支持1-4张图片 | P0 | ⭐⭐ |
| 视频推文 | 支持视频上传发布 | P0 | ⭐⭐⭐ |
| GIF推文 | 支持GIF发布 | P1 | ⭐⭐ |
| 投票推文 | 创建带投票的推文 | P2 | ⭐⭐ |
| 长推文/Thread | 支持发布推文串（多条连续推文） | P1 | ⭐⭐⭐ |
| 引用推文 | 引用转发功能 | P2 | ⭐⭐ |
| 回复推文 | 对指定推文进行回复 | P2 | ⭐⭐ |
| 定时发布 | 指定精确时间发布 | P0 | ⭐ |
| 标签/Hashtag | 自动添加或手动编辑hashtag | P0 | ⭐ |
| @提及 | 支持@其他用户 | P1 | ⭐ |
| 敏感内容标记 | 按需标记敏感内容 | P2 | ⭐ |

### 1.2 项目现状分析

基于对MCN项目的分析，当前技术栈和实现特点：

**后端技术栈**：
- FastAPI框架
- requests库（HTTP客户端，已验证与鲁米HTTP代理兼容）
- JSON文件存储（account_store.py, proxy_store.py, task_store.py）
- 基于auth_token的Twitter认证（不使用用户名密码）

**代理集成方式**：
- HTTP代理（非HTTPS/SOCKS5）
- 通过requests.Session配置代理
- 账号-代理一对一绑定
- 端到端API调用验证（不依赖IP对比）

**API设计风格**：
- RESTful API
- 路由前缀：`/api/{resource}`
- 支持批量操作
- 统一错误处理

---

## 二、开源项目评估

### 2.1 候选项目对比

| 项目 | Stars | 语言 | 优势 | 劣势 | 适配度 |
|------|-------|------|------|------|--------|
| **twikit** | 4k | Python | ✅ 无需API Key<br>✅ 功能全面<br>✅ 支持代理<br>✅ 异步支持<br>✅ 活跃维护 | ⚠️ 基于用户名密码登录<br>⚠️ 需要适配auth_token | ⭐⭐⭐⭐⭐ |
| python-twitter-tools | 3k | Python | ✅ 成熟稳定 | ❌ 需要官方API Key<br>❌ 功能受限 | ⭐ |
| twitter-ruby | 4.8k | Ruby | ✅ 功能完整 | ❌ 语言不匹配<br>❌ 需要官方API | ⭐ |

### 2.2 推荐方案：twikit

**选择理由**：

1. **无需官方API Key**：使用Twitter内部API，不受官方API限制
2. **功能覆盖完整**：支持所有需求中的发布功能
3. **代理支持**：原生支持HTTP代理配置
4. **Python生态**：与项目技术栈完全匹配
5. **活跃维护**：最近更新7个月前，社区活跃

**核心功能验证**（基于twikit文档）：

```python
from twikit import Client

# 1. 初始化客户端（支持代理）
client = Client('en-US', proxy='http://user:pass@host:port')

# 2. 登录（支持Cookie文件）
await client.login(
    auth_info_1='username',
    password='password',
    cookies_file='cookies.json'  # 可复用登录状态
)

# 3. 发推文（纯文本）
await client.create_tweet(text='Hello World')

# 4. 发图片推文
media_ids = [
    await client.upload_media('image1.jpg'),
    await client.upload_media('image2.jpg')
]
await client.create_tweet(text='With images', media_ids=media_ids)

# 5. 发投票推文
poll_uri = await client.create_poll(
    choices=['Option A', 'Option B'],
    duration_minutes=60
)
await client.create_tweet(text='Vote now!', poll_uri=poll_uri)

# 6. 引用推文
await client.create_tweet(
    text='Quoting this',
    attachment_url='https://twitter.com/user/status/123456'
)

# 7. 回复推文
await client.create_tweet(
    text='Reply content',
    reply_to='tweet_id'
)

# 8. 长推文（Twitter Premium）
await client.create_tweet(
    text='Very long content...',
    is_note_tweet=True
)
```

---

## 三、技术方案设计

### 3.1 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                         前端 (React)                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │ 推文编辑器   │  │ 媒体上传     │  │ 定时发布     │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
└─────────────────────────────────────────────────────────────┘
                            │ HTTP API
┌─────────────────────────────────────────────────────────────┐
│                    后端 (FastAPI)                            │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              twitter_publisher.py                     │   │
│  │  ┌────────────────────────────────────────────────┐  │   │
│  │  │  TwitterPublisherSession (封装twikit)          │  │   │
│  │  │  - 管理登录状态（auth_token → cookies）        │  │   │
│  │  │  - 配置代理（从账号绑定关系获取）              │  │   │
│  │  │  - 调用twikit API                              │  │   │
│  │  └────────────────────────────────────────────────┘  │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              publish_store.py                         │   │
│  │  - 推文草稿存储                                       │   │
│  │  - 定时任务存储                                       │   │
│  │  - 发布历史记录                                       │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              app.py (路由层)                          │   │
│  │  POST /api/tweets/create          # 立即发布          │   │
│  │  POST /api/tweets/schedule        # 定时发布          │   │
│  │  POST /api/tweets/upload-media    # 上传媒体          │   │
│  │  POST /api/tweets/create-poll     # 创建投票          │   │
│  │  GET  /api/tweets/drafts          # 草稿列表          │   │
│  │  GET  /api/tweets/history         # 发布历史          │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                            │
┌─────────────────────────────────────────────────────────────┐
│                   数据存储 (JSON)                            │
│  - publish_drafts.json      # 推文草稿                      │
│  - publish_history.json     # 发布历史                      │
│  - scheduled_tasks.json     # 定时任务                      │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 核心模块设计

#### 3.2.1 TwitterPublisherSession

**功能**：封装twikit，适配项目的auth_token认证和代理绑定机制

```python
# twitter_publisher.py

import asyncio
from typing import Optional, List
from twikit import Client
from proxy_store import get_proxy_record, list_account_bindings
from account_store import get_account_record

class TwitterPublisherSession:
    """Twitter发布会话管理器"""
    
    def __init__(self, account_id: str):
        """
        初始化发布会话
        
        Args:
            account_id: 账号ID
        """
        self.account_id = account_id
        self.account = None
        self.proxy_config = None
        self.client = None
        
    async def initialize(self):
        """初始化会话：加载账号、代理、创建twikit客户端"""
        # 1. 加载账号信息
        self.account = get_account_record(self.account_id)
        if not self.account:
            raise ValueError(f"账号不存在: {self.account_id}")
        
        # 2. 获取绑定的代理
        bindings = list_account_bindings()
        binding = next(
            (b for b in bindings if b['account_uid'] == self.account_id),
            None
        )
        
        if binding:
            proxy_id = binding['proxy_id']
            proxy = get_proxy_record(proxy_id)
            if proxy and proxy['status'] == 'active':
                # 构建代理URL
                self.proxy_config = self._build_proxy_url(proxy)
        
        # 3. 创建twikit客户端
        self.client = Client(
            language='en-US',
            proxy=self.proxy_config
        )
        
        # 4. 使用auth_token登录
        await self._login_with_auth_token()
        
    def _build_proxy_url(self, proxy: dict) -> str:
        """构建代理URL"""
        from urllib.parse import quote
        
        username = quote(proxy.get('username', ''))
        password = quote(proxy.get('password', ''))
        host = proxy['ip']
        port = proxy['port']
        protocol = proxy.get('protocol', 'http')
        
        if username and password:
            return f"{protocol}://{username}:{password}@{host}:{port}"
        else:
            return f"{protocol}://{host}:{port}"
    
    async def _login_with_auth_token(self):
        """
        使用auth_token登录
        
        核心思路：
        1. twikit原生支持cookies_file，可以跳过用户名密码登录
        2. 我们将auth_token转换为twikit需要的cookies格式
        3. 通过set_cookies()方法注入
        """
        auth_token = self.account.get('token')
        if not auth_token:
            raise ValueError("账号缺少auth_token")
        
        # 构建twikit需要的cookies
        cookies = {
            'auth_token': auth_token,
            'ct0': '',  # CSRF token，首次请求时会自动获取
        }
        
        # 注入cookies
        self.client.set_cookies(cookies)
        
        # 验证登录状态（调用一个简单的API）
        try:
            user_id = await self.client.user_id()
            print(f"[twitter_publisher] 登录成功，用户ID: {user_id}")
        except Exception as e:
            raise ValueError(f"auth_token无效或已过期: {e}")
    
    async def create_tweet(
        self,
        text: str = '',
        media_ids: Optional[List[str]] = None,
        poll_uri: Optional[str] = None,
        reply_to: Optional[str] = None,
        attachment_url: Optional[str] = None,
        **kwargs
    ):
        """
        发布推文
        
        Args:
            text: 推文文本
            media_ids: 媒体ID列表
            poll_uri: 投票URI
            reply_to: 回复的推文ID
            attachment_url: 引用的推文URL
            **kwargs: 其他参数（如is_note_tweet等）
        
        Returns:
            Tweet对象
        """
        if not self.client:
            raise RuntimeError("会话未初始化，请先调用initialize()")
        
        return await self.client.create_tweet(
            text=text,
            media_ids=media_ids,
            poll_uri=poll_uri,
            reply_to=reply_to,
            attachment_url=attachment_url,
            **kwargs
        )
    
    async def upload_media(self, source: str, media_type: str = 'image'):
        """
        上传媒体文件
        
        Args:
            source: 文件路径或URL
            media_type: 媒体类型（image/video/gif）
        
        Returns:
            media_id
        """
        if not self.client:
            raise RuntimeError("会话未初始化")
        
        return await self.client.upload_media(source, media_type=media_type)
    
    async def create_poll(self, choices: List[str], duration_minutes: int):
        """
        创建投票
        
        Args:
            choices: 选项列表（最多4个）
            duration_minutes: 投票时长（分钟）
        
        Returns:
            poll_uri
        """
        if not self.client:
            raise RuntimeError("会话未初始化")
        
        return await self.client.create_poll(choices, duration_minutes)
    
    async def create_thread(self, tweets: List[dict]):
        """
        发布推文串（Thread）
        
        Args:
            tweets: 推文列表，每个元素包含text和media_ids等
        
        Returns:
            发布的推文列表
        """
        if not tweets:
            return []
        
        published_tweets = []
        reply_to = None
        
        for tweet_data in tweets:
            text = tweet_data.get('text', '')
            media_ids = tweet_data.get('media_ids')
            
            tweet = await self.create_tweet(
                text=text,
                media_ids=media_ids,
                reply_to=reply_to
            )
            
            published_tweets.append(tweet)
            reply_to = tweet.id  # 下一条推文回复这条
        
        return published_tweets
    
    async def close(self):
        """关闭会话"""
        # twikit的Client没有显式的close方法
        # 但可以在这里做一些清理工作
        self.client = None
```

#### 3.2.2 publish_store.py

**功能**：推文草稿、定时任务、发布历史的存储管理

```python
# publish_store.py

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional
import fcntl

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DRAFTS_FILE = DATA_DIR / "publish_drafts.json"
HISTORY_FILE = DATA_DIR / "publish_history.json"
SCHEDULED_FILE = DATA_DIR / "scheduled_tasks.json"

def _atomic_write_json(file_path: Path, data: list):
    """原子写入JSON文件（与项目现有风格一致）"""
    temp_path = file_path.with_suffix('.tmp')
    with open(temp_path, 'w', encoding='utf-8') as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        json.dump(data, f, ensure_ascii=False, indent=2)
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    temp_path.replace(file_path)

def _read_json(file_path: Path) -> list:
    """读取JSON文件"""
    if not file_path.exists():
        return []
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)

# ========== 草稿管理 ==========

def create_draft(
    account_id: str,
    text: str = '',
    media_paths: Optional[List[str]] = None,
    tweet_type: str = 'text',  # text | image | video | poll | thread
    poll_data: Optional[dict] = None,
    thread_data: Optional[List[dict]] = None,
    **kwargs
) -> dict:
    """创建推文草稿"""
    drafts = _read_json(DRAFTS_FILE)
    
    draft = {
        'id': str(uuid.uuid4()),
        'account_id': account_id,
        'text': text,
        'media_paths': media_paths or [],
        'tweet_type': tweet_type,
        'poll_data': poll_data,
        'thread_data': thread_data,
        'created_at': datetime.now().isoformat(),
        'updated_at': datetime.now().isoformat(),
        **kwargs
    }
    
    drafts.append(draft)
    _atomic_write_json(DRAFTS_FILE, drafts)
    
    return draft

def list_drafts(account_id: Optional[str] = None) -> List[dict]:
    """列出草稿"""
    drafts = _read_json(DRAFTS_FILE)
    if account_id:
        drafts = [d for d in drafts if d['account_id'] == account_id]
    return drafts

def get_draft(draft_id: str) -> Optional[dict]:
    """获取草稿"""
    drafts = _read_json(DRAFTS_FILE)
    return next((d for d in drafts if d['id'] == draft_id), None)

def update_draft(draft_id: str, **updates) -> Optional[dict]:
    """更新草稿"""
    drafts = _read_json(DRAFTS_FILE)
    draft = next((d for d in drafts if d['id'] == draft_id), None)
    
    if not draft:
        return None
    
    draft.update(updates)
    draft['updated_at'] = datetime.now().isoformat()
    
    _atomic_write_json(DRAFTS_FILE, drafts)
    return draft

def delete_draft(draft_id: str) -> bool:
    """删除草稿"""
    drafts = _read_json(DRAFTS_FILE)
    original_len = len(drafts)
    drafts = [d for d in drafts if d['id'] != draft_id]
    
    if len(drafts) < original_len:
        _atomic_write_json(DRAFTS_FILE, drafts)
        return True
    return False

# ========== 发布历史 ==========

def create_history_record(
    account_id: str,
    tweet_id: str,
    text: str,
    tweet_type: str,
    status: str = 'success',  # success | failed
    error_message: Optional[str] = None,
    **kwargs
) -> dict:
    """创建发布历史记录"""
    history = _read_json(HISTORY_FILE)
    
    record = {
        'id': str(uuid.uuid4()),
        'account_id': account_id,
        'tweet_id': tweet_id,
        'text': text,
        'tweet_type': tweet_type,
        'status': status,
        'error_message': error_message,
        'published_at': datetime.now().isoformat(),
        **kwargs
    }
    
    history.append(record)
    _atomic_write_json(HISTORY_FILE, history)
    
    return record

def list_history(
    account_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100
) -> List[dict]:
    """列出发布历史"""
    history = _read_json(HISTORY_FILE)
    
    if account_id:
        history = [h for h in history if h['account_id'] == account_id]
    
    if status:
        history = [h for h in history if h['status'] == status]
    
    # 按时间倒序
    history.sort(key=lambda x: x['published_at'], reverse=True)
    
    return history[:limit]

# ========== 定时任务 ==========

def create_scheduled_task(
    account_id: str,
    draft_id: str,
    scheduled_time: str,  # ISO格式时间
    **kwargs
) -> dict:
    """创建定时发布任务"""
    tasks = _read_json(SCHEDULED_FILE)
    
    task = {
        'id': str(uuid.uuid4()),
        'account_id': account_id,
        'draft_id': draft_id,
        'scheduled_time': scheduled_time,
        'status': 'pending',  # pending | completed | failed | cancelled
        'created_at': datetime.now().isoformat(),
        **kwargs
    }
    
    tasks.append(task)
    _atomic_write_json(SCHEDULED_FILE, tasks)
    
    return task

def list_scheduled_tasks(
    account_id: Optional[str] = None,
    status: str = 'pending'
) -> List[dict]:
    """列出定时任务"""
    tasks = _read_json(SCHEDULED_FILE)
    
    if account_id:
        tasks = [t for t in tasks if t['account_id'] == account_id]
    
    if status:
        tasks = [t for t in tasks if t['status'] == status]
    
    return tasks

def update_scheduled_task(task_id: str, **updates) -> Optional[dict]:
    """更新定时任务"""
    tasks = _read_json(SCHEDULED_FILE)
    task = next((t for t in tasks if t['id'] == task_id), None)
    
    if not task:
        return None
    
    task.update(updates)
    task['updated_at'] = datetime.now().isoformat()
    
    _atomic_write_json(SCHEDULED_FILE, tasks)
    return task

def cancel_scheduled_task(task_id: str) -> bool:
    """取消定时任务"""
    return update_scheduled_task(task_id, status='cancelled') is not None
```

#### 3.2.3 API路由设计（app.py）

```python
# 在app.py中添加以下路由

from twitter_publisher import TwitterPublisherSession
from publish_store import (
    create_draft, list_drafts, get_draft, update_draft, delete_draft,
    create_history_record, list_history,
    create_scheduled_task, list_scheduled_tasks, cancel_scheduled_task
)

# ========== 推文发布 API ==========

class TweetCreateRequest(BaseModel):
    account_id: str
    text: str = ''
    media_paths: Optional[List[str]] = None
    tweet_type: str = 'text'  # text | image | video | poll | thread | quote | reply
    poll_data: Optional[dict] = None  # {'choices': [...], 'duration_minutes': 60}
    thread_data: Optional[List[dict]] = None  # [{'text': '...', 'media_paths': [...]}, ...]
    reply_to: Optional[str] = None  # 回复的推文ID
    quote_url: Optional[str] = None  # 引用的推文URL
    is_sensitive: bool = False  # 敏感内容标记

@app.post("/api/tweets/create")
async def create_tweet(req: TweetCreateRequest):
    """立即发布推文"""
    try:
        # 1. 创建发布会话
        session = TwitterPublisherSession(req.account_id)
        await session.initialize()
        
        # 2. 上传媒体（如果有）
        media_ids = []
        if req.media_paths:
            for media_path in req.media_paths:
                # 判断媒体类型
                media_type = 'image'
                if media_path.lower().endswith(('.mp4', '.mov')):
                    media_type = 'video'
                elif media_path.lower().endswith('.gif'):
                    media_type = 'gif'
                
                media_id = await session.upload_media(media_path, media_type)
                media_ids.append(media_id)
        
        # 3. 创建投票（如果有）
        poll_uri = None
        if req.poll_data:
            poll_uri = await session.create_poll(
                choices=req.poll_data['choices'],
                duration_minutes=req.poll_data['duration_minutes']
            )
        
        # 4. 发布推文
        if req.tweet_type == 'thread' and req.thread_data:
            # 发布推文串
            tweets = await session.create_thread(req.thread_data)
            tweet_id = tweets[0].id if tweets else None
        else:
            # 发布单条推文
            tweet = await session.create_tweet(
                text=req.text,
                media_ids=media_ids if media_ids else None,
                poll_uri=poll_uri,
                reply_to=req.reply_to,
                attachment_url=req.quote_url
            )
            tweet_id = tweet.id
        
        # 5. 记录发布历史
        create_history_record(
            account_id=req.account_id,
            tweet_id=tweet_id,
            text=req.text,
            tweet_type=req.tweet_type,
            status='success'
        )
        
        await session.close()
        
        return {
            "success": True,
            "tweet_id": tweet_id,
            "message": "推文发布成功"
        }
        
    except Exception as e:
        # 记录失败历史
        create_history_record(
            account_id=req.account_id,
            tweet_id='',
            text=req.text,
            tweet_type=req.tweet_type,
            status='failed',
            error_message=str(e)
        )
        
        return {
            "success": False,
            "error": str(e)
        }

@app.post("/api/tweets/upload-media")
async def upload_media(
    account_id: str = Form(...),
    file: UploadFile = File(...)
):
    """上传媒体文件"""
    try:
        # 1. 保存文件到临时目录
        temp_dir = BASE_DIR / "runtime" / "media-uploads"
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = temp_dir / f"{uuid.uuid4()}_{file.filename}"
        with open(file_path, 'wb') as f:
            content = await file.read()
            f.write(content)
        
        # 2. 上传到Twitter
        session = TwitterPublisherSession(account_id)
        await session.initialize()
        
        media_type = 'image'
        if file.filename.lower().endswith(('.mp4', '.mov')):
            media_type = 'video'
        elif file.filename.lower().endswith('.gif'):
            media_type = 'gif'
        
        media_id = await session.upload_media(str(file_path), media_type)
        await session.close()
        
        return {
            "success": True,
            "media_id": media_id,
            "local_path": str(file_path)
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

# ========== 草稿管理 API ==========

@app.post("/api/tweets/drafts")
async def create_tweet_draft(req: TweetCreateRequest):
    """创建推文草稿"""
    draft = create_draft(
        account_id=req.account_id,
        text=req.text,
        media_paths=req.media_paths,
        tweet_type=req.tweet_type,
        poll_data=req.poll_data,
        thread_data=req.thread_data,
        reply_to=req.reply_to,
        quote_url=req.quote_url,
        is_sensitive=req.is_sensitive
    )
    return {"success": True, "draft": draft}

@app.get("/api/tweets/drafts")
async def get_tweet_drafts(account_id: Optional[str] = None):
    """获取草稿列表"""
    drafts = list_drafts(account_id)
    return {"success": True, "drafts": drafts}

@app.delete("/api/tweets/drafts/{draft_id}")
async def delete_tweet_draft(draft_id: str):
    """删除草稿"""
    success = delete_draft(draft_id)
    return {"success": success}

# ========== 定时发布 API ==========

class ScheduleTweetRequest(BaseModel):
    account_id: str
    draft_id: str
    scheduled_time: str  # ISO格式：2026-02-20T10:00:00

@app.post("/api/tweets/schedule")
async def schedule_tweet(req: ScheduleTweetRequest):
    """创建定时发布任务"""
    task = create_scheduled_task(
        account_id=req.account_id,
        draft_id=req.draft_id,
        scheduled_time=req.scheduled_time
    )
    return {"success": True, "task": task}

@app.get("/api/tweets/scheduled")
async def get_scheduled_tweets(account_id: Optional[str] = None):
    """获取定时任务列表"""
    tasks = list_scheduled_tasks(account_id)
    return {"success": True, "tasks": tasks}

@app.delete("/api/tweets/scheduled/{task_id}")
async def cancel_scheduled_tweet(task_id: str):
    """取消定时任务"""
    success = cancel_scheduled_task(task_id)
    return {"success": success}

# ========== 发布历史 API ==========

@app.get("/api/tweets/history")
async def get_publish_history(
    account_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100
):
    """获取发布历史"""
    history = list_history(account_id, status, limit)
    return {"success": True, "history": history}
```

### 3.3 定时发布实现

**方案**：复用现有的task_worker.py机制

```python
# 在task_worker.py中添加定时发布任务处理

async def execute_scheduled_tweet_task(task_id: str):
    """执行定时发布任务"""
    from publish_store import get_scheduled_task, get_draft, update_scheduled_task
    from twitter_publisher import TwitterPublisherSession
    
    # 1. 获取任务和草稿
    task = get_scheduled_task(task_id)
    if not task or task['status'] != 'pending':
        return
    
    draft = get_draft(task['draft_id'])
    if not draft:
        update_scheduled_task(task_id, status='failed', error='草稿不存在')
        return
    
    # 2. 检查是否到达发布时间
    scheduled_time = datetime.fromisoformat(task['scheduled_time'])
    if datetime.now() < scheduled_time:
        return  # 还没到时间
    
    # 3. 执行发布
    try:
        session = TwitterPublisherSession(draft['account_id'])
        await session.initialize()
        
        # ... 发布逻辑（与create_tweet相同）
        
        update_scheduled_task(task_id, status='completed')
        
    except Exception as e:
        update_scheduled_task(
            task_id,
            status='failed',
            error=str(e)
        )

# 添加定时任务扫描器（每分钟检查一次）
async def scheduled_tweet_scanner():
    """扫描并执行到期的定时发布任务"""
    while True:
        tasks = list_scheduled_tasks(status='pending')
        for task in tasks:
            scheduled_time = datetime.fromisoformat(task['scheduled_time'])
            if datetime.now() >= scheduled_time:
                await execute_scheduled_tweet_task(task['id'])
        
        await asyncio.sleep(60)  # 每分钟检查一次
```

---

## 四、关键技术点

### 4.1 auth_token → twikit cookies 转换

**问题**：twikit原生使用用户名密码登录，但项目使用auth_token

**解决方案**：

```python
# twikit支持通过set_cookies()注入cookies
# auth_token是Twitter的核心认证cookie

cookies = {
    'auth_token': 'your_auth_token_here',
    'ct0': '',  # CSRF token，首次请求时会自动获取
}

client.set_cookies(cookies)

# 验证登录状态
user_id = await client.user_id()  # 如果成功返回用户ID，说明登录有效
```

**原理**：
- Twitter的auth_token是持久化的认证凭证
- twikit在发起请求时会自动从cookies中读取auth_token
- ct0（CSRF token）会在首次请求Twitter API时自动获取并更新

### 4.2 代理配置传递

**项目现状**：
- 账号-代理一对一绑定存储在`account_proxy_bindings.json`
- 代理信息存储在`proxy_ips.json`
- 使用HTTP代理（已验证与requests兼容）

**集成方案**：

```python
# 1. 从绑定关系获取代理ID
binding = get_account_binding(account_id)
proxy_id = binding['proxy_id']

# 2. 获取代理配置
proxy = get_proxy_record(proxy_id)

# 3. 构建代理URL
from urllib.parse import quote

username = quote(proxy['username'])
password = quote(proxy['password'])
proxy_url = f"http://{username}:{password}@{proxy['ip']}:{proxy['port']}"

# 4. 传递给twikit
client = Client('en-US', proxy=proxy_url)
```

**验证**：twikit底层使用httpx，需要测试与鲁米HTTP代理的兼容性

**备选方案**（如果twikit的httpx不兼容）：
- Fork twikit，将httpx替换为requests
- 或者直接调用Twitter GraphQL API（参考twikit源码）

### 4.3 媒体上传处理

**挑战**：
- 图片：最多4张，每张最大5MB
- 视频：最大512MB，需要分片上传
- GIF：最大15MB

**twikit支持**：

```python
# twikit的upload_media方法支持：
# - 本地文件路径
# - URL
# - 自动处理分片上传（视频）

media_id = await client.upload_media('path/to/video.mp4', media_type='video')
```

**项目集成**：

```python
# 1. 前端上传文件到后端
@app.post("/api/tweets/upload-media")
async def upload_media(file: UploadFile):
    # 保存到临时目录
    temp_path = save_uploaded_file(file)
    
    # 上传到Twitter
    session = TwitterPublisherSession(account_id)
    media_id = await session.upload_media(temp_path)
    
    return {"media_id": media_id, "local_path": temp_path}

# 2. 发布时使用media_id
await client.create_tweet(text='...', media_ids=[media_id])
```

### 4.4 长推文（Thread）实现

**方案**：逐条发布，每条回复上一条

```python
async def create_thread(self, tweets: List[dict]):
    published_tweets = []
    reply_to = None
    
    for tweet_data in tweets:
        tweet = await self.create_tweet(
            text=tweet_data['text'],
            media_ids=tweet_data.get('media_ids'),
            reply_to=reply_to  # 关键：回复上一条
        )
        published_tweets.append(tweet)
        reply_to = tweet.id  # 更新reply_to为当前推文ID
    
    return published_tweets
```

### 4.5 错误处理

**常见错误**：
- 账号被封禁：`suspended`
- 推文重复：`DuplicateTweet`
- 速率限制：`rate_limited`
- 代理失效：`ProxyError`
- auth_token过期：`Unauthorized`

**处理策略**：

```python
try:
    tweet = await session.create_tweet(...)
except DuplicateTweet:
    return {"success": False, "error": "推文内容重复"}
except Exception as e:
    error_str = str(e).lower()
    
    if 'suspended' in error_str:
        # 更新账号状态为异常
        update_account_record(account_id, status='abnormal')
        return {"success": False, "error": "账号已被封禁"}
    
    elif 'rate' in error_str:
        return {"success": False, "error": "触发速率限制，请稍后重试"}
    
    elif 'unauthorized' in error_str or '401' in error_str:
        return {"success": False, "error": "auth_token已过期，请重新验证"}
    
    else:
        return {"success": False, "error": f"发布失败: {e}"}
```

---

## 五、实施计划

### 5.1 开发阶段（按优先级）

**Phase 1：核心功能（P0）**
- [ ] 安装twikit：`pip install twikit`
- [ ] 实现TwitterPublisherSession（auth_token登录 + 代理配置）
- [ ] 实现publish_store.py（草稿、历史、定时任务存储）
- [ ] API路由：纯文本推文发布
- [ ] API路由：图片推文发布（1-4张）
- [ ] API路由：视频推文发布
- [ ] API路由：媒体上传
- [ ] 定时发布机制（集成task_worker）
- [ ] 前端：推文编辑器组件
- [ ] 前端：媒体上传组件
- [ ] 前端：定时发布选择器

**Phase 2：扩展功能（P1）**
- [ ] GIF推文支持
- [ ] Thread（推文串）发布
- [ ] @提及功能（前端输入提示）
- [ ] Hashtag自动添加

**Phase 3：高级功能（P2）**
- [ ] 投票推文
- [ ] 引用转发
- [ ] 回复推文
- [ ] 敏感内容标记

### 5.2 测试计划

**单元测试**：
- TwitterPublisherSession初始化
- auth_token登录验证
- 代理配置传递
- 媒体上传
- 各类推文发布

**集成测试**：
- 使用真实账号和代理测试发布流程
- 验证代理绑定是否生效（发布后检查IP）
- 测试错误处理（账号被封、代理失效等）

**性能测试**：
- 批量发布（多账号并发）
- 媒体上传速度（大视频）
- 定时任务准时性

### 5.3 部署注意事项

1. **依赖安装**：
   ```bash
   pip install twikit
   ```

2. **twikit与鲁米代理兼容性验证**：
   ```python
   # 测试脚本
   from twikit import Client
   
   proxy_url = "http://user:pass@host:port"
   client = Client('en-US', proxy=proxy_url)
   
   # 测试请求
   await client.user_id()  # 如果成功，说明兼容
   ```

3. **如果twikit的httpx不兼容鲁米代理**：
   - 方案A：修改twikit源码，将httpx替换为requests
   - 方案B：直接调用Twitter GraphQL API（参考twikit实现）

4. **定时任务启动**：
   ```python
   # 在main.py或app.py启动时添加
   import asyncio
   from task_worker import scheduled_tweet_scanner
   
   @app.on_event("startup")
   async def startup_event():
       asyncio.create_task(scheduled_tweet_scanner())
   ```

---

## 六、风险与备选方案

### 6.1 风险点

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| twikit的httpx与鲁米HTTP代理不兼容 | 高 | 中 | 测试验证；备选方案：替换为requests |
| Twitter反爬虫机制升级导致twikit失效 | 高 | 低 | 关注twikit更新；备选方案：直接调用GraphQL |
| auth_token登录方式不稳定 | 中 | 低 | 添加重试机制；提示用户更新token |
| 媒体上传速度慢（大视频） | 中 | 中 | 使用异步上传；添加进度提示 |
| 定时任务不准时 | 低 | 低 | 优化扫描频率；使用专业任务队列 |

### 6.2 备选方案

**如果twikit不可用**：

**方案B：直接调用Twitter GraphQL API**

```python
# 参考twikit源码，直接调用Twitter内部API

import requests

class TwitterGraphQLClient:
    def __init__(self, auth_token: str, proxy: str = None):
        self.auth_token = auth_token
        self.session = requests.Session()
        if proxy:
            self.session.proxies = {'http': proxy, 'https': proxy}
        
        self.session.headers.update({
            'authorization': 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA',
            'cookie': f'auth_token={auth_token}',
            'x-twitter-active-user': 'yes',
            'x-twitter-client-language': 'en',
        })
    
    def get_csrf_token(self):
        """获取CSRF token"""
        resp = self.session.get('https://x.com')
        ct0 = resp.cookies.get('ct0')
        self.session.headers['x-csrf-token'] = ct0
        return ct0
    
    def create_tweet(self, text: str, media_ids: list = None):
        """发布推文"""
        self.get_csrf_token()
        
        variables = {
            "tweet_text": text,
            "dark_request": False,
            "media": {
                "media_entities": [{"media_id": mid, "tagged_users": []} for mid in (media_ids or [])],
                "possibly_sensitive": False
            },
            "semantic_annotation_ids": []
        }
        
        resp = self.session.post(
            'https://x.com/i/api/graphql/XXX/CreateTweet',  # 需要找到正确的endpoint
            json={"variables": variables}
        )
        
        return resp.json()
```

**优势**：
- 完全控制请求细节
- 可以使用requests（已验证兼容）

**劣势**：
- 需要维护API endpoint和参数（Twitter可能变更）
- 开发工作量大

---

## 七、总结

### 7.1 推荐方案

**使用twikit + 适配层**：

1. **核心库**：twikit（功能完整、维护活跃）
2. **适配层**：TwitterPublisherSession（桥接auth_token和代理）
3. **存储层**：publish_store.py（复用JSON文件存储）
4. **API层**：FastAPI路由（RESTful风格）
5. **定时任务**：集成现有task_worker机制

### 7.2 优势

- ✅ **零API Key**：不受官方API限制
- ✅ **功能完整**：覆盖所有需求功能
- ✅ **技术栈统一**：Python + FastAPI + requests
- ✅ **代理集成**：无缝对接现有账号-代理绑定
- ✅ **快速开发**：核心功能1-2周可完成

### 7.3 下一步

1. **验证twikit与鲁米代理兼容性**（最关键）
2. **实现TwitterPublisherSession**（核心适配层）
3. **开发P0功能**（纯文本、图片、视频、定时发布）
4. **前端开发**（推文编辑器、媒体上传）
5. **测试与优化**

---

**附录：twikit功能覆盖度检查**

| 需求功能 | twikit支持 | 实现方式 |
|---------|-----------|---------|
| 纯文本推文 | ✅ | `create_tweet(text='...')` |
| 图片推文 | ✅ | `upload_media()` + `create_tweet(media_ids=[...])` |
| 视频推文 | ✅ | `upload_media(media_type='video')` |
| GIF推文 | ✅ | `upload_media(media_type='gif')` |
| 投票推文 | ✅ | `create_poll()` + `create_tweet(poll_uri=...)` |
| Thread | ✅ | 循环调用`create_tweet(reply_to=...)` |
| 引用转发 | ✅ | `create_tweet(attachment_url='...')` |
| 回复推文 | ✅ | `create_tweet(reply_to='...')` |
| 定时发布 | ⚠️ | 需自行实现（使用task_worker） |
| Hashtag | ✅ | 直接在text中包含`#tag` |
| @提及 | ✅ | 直接在text中包含`@username` |
| 敏感内容标记 | ⚠️ | 需查看twikit文档或API参数 |

**结论**：twikit覆盖了90%以上的需求，剩余10%可通过适配层实现。

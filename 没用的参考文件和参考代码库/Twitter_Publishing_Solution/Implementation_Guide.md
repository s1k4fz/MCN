# Twitter发布功能实施指南

## 一、快速开始

### 1.1 安装依赖

```bash
cd backend
pip install twikit
```

### 1.2 验证twikit与鲁米代理兼容性

**这是最关键的第一步！**

创建测试脚本 `test_twikit_proxy.py`：

```python
import asyncio
from twikit import Client

async def test_proxy_compatibility():
    """测试twikit与鲁米HTTP代理的兼容性"""
    
    # 使用你的真实代理配置
    proxy_url = "http://userID-2608-orderid-201875-region-us:59751a2451fa4c0a@usdata.lumidaili.com:10000"
    
    # 创建客户端
    client = Client('en-US', proxy=proxy_url)
    
    # 使用auth_token登录
    auth_token = "your_auth_token_here"  # 替换为真实的auth_token
    
    cookies = {
        'auth_token': auth_token,
        'ct0': '',
    }
    
    client.set_cookies(cookies)
    
    try:
        # 测试API调用
        user_id = await client.user_id()
        print(f"✅ 测试成功！用户ID: {user_id}")
        print("twikit与鲁米代理兼容")
        return True
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        print("twikit与鲁米代理可能不兼容，需要使用备选方案")
        return False

if __name__ == "__main__":
    asyncio.run(test_proxy_compatibility())
```

运行测试：

```bash
python test_twikit_proxy.py
```

**结果判断**：

- ✅ **如果成功**：继续使用twikit方案
- ❌ **如果失败**：
  - 检查错误信息是否包含`ProxyError`、`Tunnel connection failed`等
  - 如果是代理相关错误，需要使用备选方案（见第六章）

---

## 二、核心文件创建

### 2.1 创建 `twitter_publisher.py`

```bash
cd backend
touch twitter_publisher.py
```

将以下代码复制到文件中（完整代码见`twitter_publisher_core_example.py`）：

```python
# twitter_publisher.py

import asyncio
from typing import Optional, List
from twikit import Client
from proxy_store import get_proxy_record, list_account_bindings
from account_store import get_account_record
from urllib.parse import quote

class TwitterPublisherSession:
    """Twitter发布会话管理器"""
    
    def __init__(self, account_id: str):
        self.account_id = account_id
        self.account = None
        self.proxy_config = None
        self.client = None
    
    async def initialize(self):
        """初始化会话"""
        # 1. 加载账号
        self.account = get_account_record(self.account_id)
        if not self.account:
            raise ValueError(f"账号不存在: {self.account_id}")
        
        # 2. 获取代理
        bindings = list_account_bindings()
        binding = next(
            (b for b in bindings if b['account_uid'] == self.account_id),
            None
        )
        
        if binding:
            proxy = get_proxy_record(binding['proxy_id'])
            if proxy and proxy['status'] == 'active':
                self.proxy_config = self._build_proxy_url(proxy)
        
        # 3. 创建客户端
        self.client = Client('en-US', proxy=self.proxy_config)
        
        # 4. 登录
        await self._login_with_auth_token()
    
    def _build_proxy_url(self, proxy: dict) -> str:
        """构建代理URL"""
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
        """使用auth_token登录"""
        auth_token = self.account.get('token')
        if not auth_token:
            raise ValueError("账号缺少auth_token")
        
        cookies = {
            'auth_token': auth_token,
            'ct0': '',
        }
        
        self.client.set_cookies(cookies)
        
        try:
            user_id = await self.client.user_id()
            print(f"[publisher] 登录成功，用户ID: {user_id}")
        except Exception as e:
            raise ValueError(f"auth_token无效: {e}")
    
    async def create_tweet(self, text: str = '', media_ids: Optional[List[str]] = None, **kwargs):
        """发布推文"""
        if not self.client:
            raise RuntimeError("会话未初始化")
        
        return await self.client.create_tweet(
            text=text,
            media_ids=media_ids,
            **kwargs
        )
    
    async def upload_media(self, source: str, media_type: str = 'image'):
        """上传媒体"""
        if not self.client:
            raise RuntimeError("会话未初始化")
        
        return await self.client.upload_media(source, media_type=media_type)
    
    async def create_poll(self, choices: List[str], duration_minutes: int):
        """创建投票"""
        if not self.client:
            raise RuntimeError("会话未初始化")
        
        return await self.client.create_poll(choices, duration_minutes)
    
    async def create_thread(self, tweets: List[dict]):
        """发布推文串"""
        if not tweets:
            return []
        
        published_tweets = []
        reply_to = None
        
        for tweet_data in tweets:
            tweet = await self.create_tweet(
                text=tweet_data.get('text', ''),
                media_ids=tweet_data.get('media_ids'),
                reply_to=reply_to
            )
            published_tweets.append(tweet)
            reply_to = tweet.id
        
        return published_tweets
    
    async def close(self):
        """关闭会话"""
        self.client = None
```

### 2.2 创建 `publish_store.py`

```bash
touch publish_store.py
```

复制以下代码（完整代码见技术方案文档）：

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
    """原子写入JSON"""
    temp_path = file_path.with_suffix('.tmp')
    with open(temp_path, 'w', encoding='utf-8') as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        json.dump(data, f, ensure_ascii=False, indent=2)
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    temp_path.replace(file_path)

def _read_json(file_path: Path) -> list:
    """读取JSON"""
    if not file_path.exists():
        return []
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)

# 草稿管理
def create_draft(account_id: str, text: str = '', **kwargs) -> dict:
    """创建草稿"""
    drafts = _read_json(DRAFTS_FILE)
    draft = {
        'id': str(uuid.uuid4()),
        'account_id': account_id,
        'text': text,
        'created_at': datetime.now().isoformat(),
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

# 发布历史
def create_history_record(account_id: str, tweet_id: str, text: str, status: str = 'success', **kwargs) -> dict:
    """创建历史记录"""
    history = _read_json(HISTORY_FILE)
    record = {
        'id': str(uuid.uuid4()),
        'account_id': account_id,
        'tweet_id': tweet_id,
        'text': text,
        'status': status,
        'published_at': datetime.now().isoformat(),
        **kwargs
    }
    history.append(record)
    _atomic_write_json(HISTORY_FILE, history)
    return record

def list_history(account_id: Optional[str] = None, limit: int = 100) -> List[dict]:
    """列出历史"""
    history = _read_json(HISTORY_FILE)
    if account_id:
        history = [h for h in history if h['account_id'] == account_id]
    history.sort(key=lambda x: x['published_at'], reverse=True)
    return history[:limit]

# 定时任务
def create_scheduled_task(account_id: str, draft_id: str, scheduled_time: str, **kwargs) -> dict:
    """创建定时任务"""
    tasks = _read_json(SCHEDULED_FILE)
    task = {
        'id': str(uuid.uuid4()),
        'account_id': account_id,
        'draft_id': draft_id,
        'scheduled_time': scheduled_time,
        'status': 'pending',
        'created_at': datetime.now().isoformat(),
        **kwargs
    }
    tasks.append(task)
    _atomic_write_json(SCHEDULED_FILE, tasks)
    return task

def list_scheduled_tasks(status: str = 'pending') -> List[dict]:
    """列出定时任务"""
    tasks = _read_json(SCHEDULED_FILE)
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
```

### 2.3 在 `app.py` 中添加路由

在 `app.py` 文件末尾添加：

```python
# ========== Twitter发布功能 ==========

from twitter_publisher import TwitterPublisherSession
from publish_store import (
    create_draft, list_drafts,
    create_history_record, list_history,
    create_scheduled_task, list_scheduled_tasks
)

class TweetCreateRequest(BaseModel):
    account_id: str
    text: str = ''
    media_paths: Optional[List[str]] = None
    tweet_type: str = 'text'
    poll_data: Optional[dict] = None
    thread_data: Optional[List[dict]] = None
    reply_to: Optional[str] = None
    quote_url: Optional[str] = None

@app.post("/api/tweets/create")
async def create_tweet(req: TweetCreateRequest):
    """立即发布推文"""
    try:
        session = TwitterPublisherSession(req.account_id)
        await session.initialize()
        
        # 上传媒体
        media_ids = []
        if req.media_paths:
            for media_path in req.media_paths:
                media_type = 'image'
                if media_path.lower().endswith(('.mp4', '.mov')):
                    media_type = 'video'
                elif media_path.lower().endswith('.gif'):
                    media_type = 'gif'
                
                media_id = await session.upload_media(media_path, media_type)
                media_ids.append(media_id)
        
        # 创建投票
        poll_uri = None
        if req.poll_data:
            poll_uri = await session.create_poll(
                req.poll_data['choices'],
                req.poll_data['duration_minutes']
            )
        
        # 发布推文
        if req.tweet_type == 'thread' and req.thread_data:
            tweets = await session.create_thread(req.thread_data)
            tweet_id = tweets[0].id if tweets else None
        else:
            tweet = await session.create_tweet(
                text=req.text,
                media_ids=media_ids if media_ids else None,
                poll_uri=poll_uri,
                reply_to=req.reply_to,
                attachment_url=req.quote_url
            )
            tweet_id = tweet.id
        
        # 记录历史
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
            "url": f"https://twitter.com/user/status/{tweet_id}"
        }
    
    except Exception as e:
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
    """上传媒体"""
    try:
        # 保存文件
        temp_dir = BASE_DIR / "runtime" / "media-uploads"
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = temp_dir / f"{uuid.uuid4()}_{file.filename}"
        with open(file_path, 'wb') as f:
            content = await file.read()
            f.write(content)
        
        # 上传到Twitter
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

@app.get("/api/tweets/history")
async def get_publish_history(account_id: Optional[str] = None, limit: int = 100):
    """获取发布历史"""
    history = list_history(account_id, limit)
    return {"success": True, "history": history}

@app.post("/api/tweets/drafts")
async def create_tweet_draft(req: TweetCreateRequest):
    """创建草稿"""
    draft = create_draft(
        account_id=req.account_id,
        text=req.text,
        media_paths=req.media_paths,
        tweet_type=req.tweet_type,
        poll_data=req.poll_data,
        thread_data=req.thread_data
    )
    return {"success": True, "draft": draft}

@app.get("/api/tweets/drafts")
async def get_drafts(account_id: Optional[str] = None):
    """获取草稿列表"""
    drafts = list_drafts(account_id)
    return {"success": True, "drafts": drafts}
```

---

## 三、测试

### 3.1 测试纯文本推文

创建测试脚本 `test_publish.py`：

```python
import asyncio
from twitter_publisher import TwitterPublisherSession

async def test_text_tweet():
    """测试发布纯文本推文"""
    
    # 使用真实的账号ID
    account_id = "your_account_id_here"
    
    session = TwitterPublisherSession(account_id)
    await session.initialize()
    
    tweet = await session.create_tweet(
        text="测试推文 #test"
    )
    
    print(f"✅ 推文发布成功！")
    print(f"推文ID: {tweet.id}")
    print(f"链接: https://twitter.com/user/status/{tweet.id}")
    
    await session.close()

if __name__ == "__main__":
    asyncio.run(test_text_tweet())
```

运行测试：

```bash
python test_publish.py
```

### 3.2 测试API接口

启动后端：

```bash
python app.py
```

使用curl测试：

```bash
# 测试发布纯文本推文
curl -X POST http://localhost:8000/api/tweets/create \
  -H "Content-Type: application/json" \
  -d '{
    "account_id": "your_account_id",
    "text": "Hello from API!",
    "tweet_type": "text"
  }'
```

### 3.3 验证代理是否生效

发布推文后，检查推文是否通过绑定的代理发布：

```python
# 在TwitterPublisherSession中添加调试日志
async def initialize(self):
    # ... 现有代码 ...
    
    if self.proxy_config:
        print(f"[DEBUG] 使用代理: {self.proxy_config}")
    else:
        print(f"[DEBUG] 未配置代理")
    
    # ... 现有代码 ...
```

---

## 四、前端集成

### 4.1 推文编辑器组件

在 `web/src/components/` 创建 `TweetComposer.tsx`：

```typescript
import React, { useState } from 'react';

interface TweetComposerProps {
  accountId: string;
  onPublish: (tweet: any) => void;
}

export const TweetComposer: React.FC<TweetComposerProps> = ({ accountId, onPublish }) => {
  const [text, setText] = useState('');
  const [mediaFiles, setMediaFiles] = useState<File[]>([]);
  const [isPublishing, setIsPublishing] = useState(false);

  const handlePublish = async () => {
    setIsPublishing(true);
    
    try {
      // 1. 上传媒体
      const mediaPaths = [];
      for (const file of mediaFiles) {
        const formData = new FormData();
        formData.append('account_id', accountId);
        formData.append('file', file);
        
        const uploadResp = await fetch('/api/tweets/upload-media', {
          method: 'POST',
          body: formData
        });
        
        const uploadData = await uploadResp.json();
        if (uploadData.success) {
          mediaPaths.push(uploadData.local_path);
        }
      }
      
      // 2. 发布推文
      const resp = await fetch('/api/tweets/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          account_id: accountId,
          text: text,
          media_paths: mediaPaths,
          tweet_type: mediaPaths.length > 0 ? 'image' : 'text'
        })
      });
      
      const data = await resp.json();
      
      if (data.success) {
        alert('推文发布成功！');
        setText('');
        setMediaFiles([]);
        onPublish(data);
      } else {
        alert(`发布失败: ${data.error}`);
      }
    } catch (error) {
      alert(`发布失败: ${error}`);
    } finally {
      setIsPublishing(false);
    }
  };

  return (
    <div className="tweet-composer">
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="有什么新鲜事？"
        maxLength={280}
        rows={4}
      />
      
      <div className="char-count">
        {text.length} / 280
      </div>
      
      <input
        type="file"
        multiple
        accept="image/*,video/*,.gif"
        onChange={(e) => setMediaFiles(Array.from(e.target.files || []))}
      />
      
      <button
        onClick={handlePublish}
        disabled={isPublishing || (!text && mediaFiles.length === 0)}
      >
        {isPublishing ? '发布中...' : '发布'}
      </button>
    </div>
  );
};
```

### 4.2 集成到账号管理页面

在账号列表中添加"发推文"按钮：

```typescript
// 在AccountList组件中
const [showComposer, setShowComposer] = useState(false);
const [selectedAccount, setSelectedAccount] = useState(null);

return (
  <div>
    {accounts.map(account => (
      <div key={account.id}>
        <span>{account.account}</span>
        <button onClick={() => {
          setSelectedAccount(account);
          setShowComposer(true);
        }}>
          发推文
        </button>
      </div>
    ))}
    
    {showComposer && selectedAccount && (
      <Modal onClose={() => setShowComposer(false)}>
        <TweetComposer
          accountId={selectedAccount.id}
          onPublish={(tweet) => {
            console.log('推文已发布:', tweet);
            setShowComposer(false);
          }}
        />
      </Modal>
    )}
  </div>
);
```

---

## 五、定时发布实现

### 5.1 创建定时任务扫描器

在 `task_worker.py` 中添加：

```python
import asyncio
from datetime import datetime
from publish_store import list_scheduled_tasks, update_scheduled_task, get_draft
from twitter_publisher import TwitterPublisherSession

async def execute_scheduled_tweet(task_id: str):
    """执行定时发布任务"""
    from publish_store import create_history_record
    
    task = next((t for t in list_scheduled_tasks() if t['id'] == task_id), None)
    if not task or task['status'] != 'pending':
        return
    
    draft = get_draft(task['draft_id'])
    if not draft:
        update_scheduled_task(task_id, status='failed', error='草稿不存在')
        return
    
    try:
        session = TwitterPublisherSession(draft['account_id'])
        await session.initialize()
        
        tweet = await session.create_tweet(text=draft['text'])
        
        update_scheduled_task(task_id, status='completed', tweet_id=tweet.id)
        create_history_record(
            account_id=draft['account_id'],
            tweet_id=tweet.id,
            text=draft['text'],
            tweet_type=draft.get('tweet_type', 'text'),
            status='success'
        )
        
        await session.close()
        
    except Exception as e:
        update_scheduled_task(task_id, status='failed', error=str(e))

async def scheduled_tweet_scanner():
    """定时任务扫描器（每分钟检查一次）"""
    while True:
        try:
            tasks = list_scheduled_tasks(status='pending')
            now = datetime.now()
            
            for task in tasks:
                scheduled_time = datetime.fromisoformat(task['scheduled_time'])
                if now >= scheduled_time:
                    print(f"[scanner] 执行定时任务: {task['id']}")
                    await execute_scheduled_tweet(task['id'])
        
        except Exception as e:
            print(f"[scanner] 扫描错误: {e}")
        
        await asyncio.sleep(60)  # 每分钟检查一次

# 在app.py启动时添加
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(scheduled_tweet_scanner())
```

### 5.2 前端定时发布组件

```typescript
// ScheduleTweetForm.tsx

interface ScheduleTweetFormProps {
  accountId: string;
  draftId: string;
}

export const ScheduleTweetForm: React.FC<ScheduleTweetFormProps> = ({ accountId, draftId }) => {
  const [scheduledTime, setScheduledTime] = useState('');

  const handleSchedule = async () => {
    const resp = await fetch('/api/tweets/schedule', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        account_id: accountId,
        draft_id: draftId,
        scheduled_time: scheduledTime
      })
    });

    const data = await resp.json();
    if (data.success) {
      alert('定时任务已创建！');
    }
  };

  return (
    <div>
      <input
        type="datetime-local"
        value={scheduledTime}
        onChange={(e) => setScheduledTime(e.target.value)}
      />
      <button onClick={handleSchedule}>设置定时发布</button>
    </div>
  );
};
```

---

## 六、备选方案（如果twikit不兼容）

### 6.1 方案A：修改twikit源码

如果twikit的httpx与鲁米代理不兼容，可以fork twikit并替换为requests：

1. Fork twikit仓库
2. 找到httpx相关代码
3. 替换为requests
4. 在项目中使用修改后的版本

### 6.2 方案B：直接调用Twitter GraphQL API

如果twikit完全不可用，可以直接调用Twitter内部API：

```python
# twitter_graphql_client.py

import requests
from urllib.parse import quote

class TwitterGraphQLClient:
    """直接调用Twitter GraphQL API"""
    
    BEARER_TOKEN = "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
    
    def __init__(self, auth_token: str, proxy: str = None):
        self.auth_token = auth_token
        self.session = requests.Session()
        
        if proxy:
            self.session.proxies = {
                'http': proxy,
                'https': proxy
            }
        
        self.session.headers.update({
            'authorization': f'Bearer {self.BEARER_TOKEN}',
            'cookie': f'auth_token={auth_token}',
            'x-twitter-active-user': 'yes',
            'x-twitter-client-language': 'en',
            'content-type': 'application/json',
        })
        
        self.csrf_token = None
    
    def get_csrf_token(self):
        """获取CSRF token"""
        resp = self.session.get('https://x.com')
        self.csrf_token = resp.cookies.get('ct0')
        self.session.headers['x-csrf-token'] = self.csrf_token
        return self.csrf_token
    
    def create_tweet(self, text: str, media_ids: list = None):
        """发布推文"""
        if not self.csrf_token:
            self.get_csrf_token()
        
        variables = {
            "tweet_text": text,
            "dark_request": False,
            "media": {
                "media_entities": [
                    {"media_id": mid, "tagged_users": []}
                    for mid in (media_ids or [])
                ],
                "possibly_sensitive": False
            },
            "semantic_annotation_ids": []
        }
        
        # GraphQL endpoint（需要找到正确的endpoint ID）
        endpoint = "https://x.com/i/api/graphql/XXX/CreateTweet"
        
        resp = self.session.post(
            endpoint,
            json={"variables": variables}
        )
        
        return resp.json()
```

**注意**：这个方案需要：
1. 找到正确的GraphQL endpoint ID
2. 研究Twitter API的请求格式
3. 处理各种边界情况

---

## 七、常见问题

### Q1: twikit安装失败

**问题**：`pip install twikit` 失败

**解决**：
```bash
# 尝试使用国内镜像
pip install twikit -i https://pypi.tuna.tsinghua.edu.cn/simple

# 或者从GitHub安装
pip install git+https://github.com/d60/twikit.git
```

### Q2: auth_token在哪里获取？

**答案**：
1. 打开浏览器，登录Twitter
2. 打开开发者工具（F12）
3. 进入Application → Cookies → https://x.com
4. 找到`auth_token`字段，复制其值

### Q3: 如何判断代理是否生效？

**方法1**：在TwitterPublisherSession中添加日志
```python
async def initialize(self):
    # ... 现有代码 ...
    print(f"[DEBUG] 代理配置: {self.proxy_config}")
```

**方法2**：发布推文后，检查推文来源IP
- 如果有绑定代理，IP应该是代理的出口IP
- 可以在推文中@一个IP检测账号

### Q4: 视频上传很慢怎么办？

**原因**：视频文件大，上传需要时间

**优化**：
1. 前端显示上传进度
2. 使用异步上传
3. 提示用户耐心等待

### Q5: 推文发布失败怎么办？

**排查步骤**：
1. 检查auth_token是否有效
2. 检查代理是否正常
3. 查看错误信息：
   - `Unauthorized`: auth_token过期
   - `DuplicateTweet`: 推文内容重复
   - `rate_limited`: 触发速率限制
   - `ProxyError`: 代理连接失败

---

## 八、性能优化

### 8.1 批量发布优化

如果需要批量发布（多个账号），使用异步并发：

```python
async def batch_publish(accounts: List[str], text: str):
    """批量发布推文"""
    tasks = []
    
    for account_id in accounts:
        task = publish_single_tweet(account_id, text)
        tasks.append(task)
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    return results

async def publish_single_tweet(account_id: str, text: str):
    """发布单条推文"""
    try:
        session = TwitterPublisherSession(account_id)
        await session.initialize()
        tweet = await session.create_tweet(text=text)
        await session.close()
        return {"success": True, "tweet_id": tweet.id}
    except Exception as e:
        return {"success": False, "error": str(e)}
```

### 8.2 媒体上传优化

对于大视频，使用分片上传：

```python
# twikit已经内置了分片上传支持
# 只需要调用upload_media即可，它会自动处理

media_id = await client.upload_media('large_video.mp4', media_type='video')
```

---

## 九、部署清单

### 9.1 依赖安装

```bash
cd backend
pip install twikit
```

### 9.2 文件清单

- [x] `twitter_publisher.py` - 核心发布模块
- [x] `publish_store.py` - 存储模块
- [x] `app.py` - 添加API路由
- [x] `task_worker.py` - 添加定时任务扫描器

### 9.3 数据目录

```bash
mkdir -p backend/data
mkdir -p backend/runtime/media-uploads
```

### 9.4 测试

- [x] 测试twikit与代理兼容性
- [x] 测试auth_token登录
- [x] 测试纯文本推文发布
- [x] 测试图片推文发布
- [x] 测试API接口
- [x] 测试前端集成

### 9.5 启动服务

```bash
# 启动后端
cd backend
python app.py

# 启动前端
cd web
npm run dev
```

---

## 十、下一步

1. **完成P0功能**（1周）
   - 纯文本推文
   - 图片推文
   - 视频推文
   - 定时发布

2. **完成P1功能**（1周）
   - GIF推文
   - Thread推文串
   - @提及和Hashtag

3. **完成P2功能**（1周）
   - 投票推文
   - 引用转发
   - 回复推文

4. **测试和优化**（1周）
   - 批量发布测试
   - 性能优化
   - 错误处理完善

---

**总结**：按照这个指南，你可以在2-4周内完成Twitter发布管理功能的开发。关键是先验证twikit与鲁米代理的兼容性，然后按优先级逐步实现功能。

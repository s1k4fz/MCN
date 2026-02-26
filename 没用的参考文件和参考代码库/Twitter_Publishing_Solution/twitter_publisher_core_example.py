"""
Twitter发布功能核心代码示例
基于twikit库，适配MCN项目的auth_token认证和代理绑定机制
"""

import asyncio
import json
import uuid
from typing import Optional, List
from pathlib import Path
from datetime import datetime

# 需要安装：pip install twikit
from twikit import Client

# ============================================================================
# 核心类：TwitterPublisherSession
# ============================================================================

class TwitterPublisherSession:
    """
    Twitter发布会话管理器
    
    功能：
    1. 使用auth_token登录（而非用户名密码）
    2. 自动配置账号绑定的代理
    3. 封装twikit API，提供统一的发布接口
    """
    
    def __init__(self, account_id: str):
        """
        初始化发布会话
        
        Args:
            account_id: 账号ID（从accounts.json中获取）
        """
        self.account_id = account_id
        self.account = None
        self.proxy_config = None
        self.client = None
        
    async def initialize(self):
        """
        初始化会话
        
        步骤：
        1. 加载账号信息（从account_store获取）
        2. 获取绑定的代理（从proxy_store获取）
        3. 创建twikit客户端（配置代理）
        4. 使用auth_token登录
        """
        # 1. 加载账号信息
        self.account = self._get_account_record(self.account_id)
        if not self.account:
            raise ValueError(f"账号不存在: {self.account_id}")
        
        # 2. 获取绑定的代理
        binding = self._get_account_binding(self.account_id)
        if binding:
            proxy = self._get_proxy_record(binding['proxy_id'])
            if proxy and proxy['status'] == 'active':
                self.proxy_config = self._build_proxy_url(proxy)
                print(f"[publisher] 使用代理: {self.proxy_config}")
        
        # 3. 创建twikit客户端
        self.client = Client(
            language='en-US',
            proxy=self.proxy_config
        )
        
        # 4. 使用auth_token登录
        await self._login_with_auth_token()
        
        print(f"[publisher] 会话初始化成功，账号: {self.account.get('account')}")
    
    def _get_account_record(self, account_id: str) -> dict:
        """从account_store获取账号信息（示例实现）"""
        # 实际项目中：from account_store import get_account_record
        # return get_account_record(account_id)
        
        # 示例数据
        return {
            'id': account_id,
            'platform': 'twitter',
            'account': 'example_user',
            'token': 'your_auth_token_here',  # 这是关键
            'status': 'active'
        }
    
    def _get_account_binding(self, account_id: str) -> Optional[dict]:
        """获取账号-代理绑定关系（示例实现）"""
        # 实际项目中：from proxy_store import list_account_bindings
        # bindings = list_account_bindings()
        # return next((b for b in bindings if b['account_uid'] == account_id), None)
        
        # 示例数据
        return {
            'account_uid': account_id,
            'proxy_id': 'proxy_123'
        }
    
    def _get_proxy_record(self, proxy_id: str) -> Optional[dict]:
        """获取代理信息（示例实现）"""
        # 实际项目中：from proxy_store import get_proxy_record
        # return get_proxy_record(proxy_id)
        
        # 示例数据
        return {
            'id': proxy_id,
            'ip': 'proxy.example.com',
            'port': 10000,
            'username': 'user123',
            'password': 'pass123',
            'protocol': 'http',
            'status': 'active'
        }
    
    def _build_proxy_url(self, proxy: dict) -> str:
        """
        构建代理URL
        
        格式：protocol://username:password@host:port
        注意：用户名密码需要URL编码
        """
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
        1. twikit支持通过set_cookies()注入cookies
        2. auth_token是Twitter的核心认证cookie
        3. 注入后，twikit会自动在请求中携带auth_token
        4. ct0（CSRF token）会在首次请求时自动获取
        """
        auth_token = self.account.get('token')
        if not auth_token:
            raise ValueError("账号缺少auth_token")
        
        # 构建cookies
        cookies = {
            'auth_token': auth_token,
            'ct0': '',  # CSRF token，首次请求时会自动获取
        }
        
        # 注入cookies
        self.client.set_cookies(cookies)
        
        # 验证登录状态（调用一个简单的API）
        try:
            user_id = await self.client.user_id()
            print(f"[publisher] 登录成功，用户ID: {user_id}")
        except Exception as e:
            raise ValueError(f"auth_token无效或已过期: {e}")
    
    # ========================================================================
    # 发布功能
    # ========================================================================
    
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
            text: 推文文本（最多280字符）
            media_ids: 媒体ID列表（通过upload_media获取）
            poll_uri: 投票URI（通过create_poll获取）
            reply_to: 回复的推文ID
            attachment_url: 引用的推文URL
            **kwargs: 其他参数（如is_note_tweet用于长推文）
        
        Returns:
            Tweet对象
        """
        if not self.client:
            raise RuntimeError("会话未初始化，请先调用initialize()")
        
        print(f"[publisher] 发布推文: {text[:50]}...")
        
        tweet = await self.client.create_tweet(
            text=text,
            media_ids=media_ids,
            poll_uri=poll_uri,
            reply_to=reply_to,
            attachment_url=attachment_url,
            **kwargs
        )
        
        print(f"[publisher] 推文发布成功，ID: {tweet.id}")
        return tweet
    
    async def upload_media(self, source: str, media_type: str = 'image'):
        """
        上传媒体文件
        
        Args:
            source: 文件路径或URL
            media_type: 媒体类型
                - 'image': 图片（最多4张，每张最大5MB）
                - 'video': 视频（最大512MB）
                - 'gif': GIF（最大15MB）
        
        Returns:
            media_id: 媒体ID，用于create_tweet的media_ids参数
        """
        if not self.client:
            raise RuntimeError("会话未初始化")
        
        print(f"[publisher] 上传媒体: {source} (类型: {media_type})")
        
        media_id = await self.client.upload_media(source, media_type=media_type)
        
        print(f"[publisher] 媒体上传成功，ID: {media_id}")
        return media_id
    
    async def create_poll(self, choices: List[str], duration_minutes: int):
        """
        创建投票
        
        Args:
            choices: 选项列表（2-4个选项）
            duration_minutes: 投票时长（分钟）
        
        Returns:
            poll_uri: 投票URI，用于create_tweet的poll_uri参数
        """
        if not self.client:
            raise RuntimeError("会话未初始化")
        
        if len(choices) < 2 or len(choices) > 4:
            raise ValueError("投票选项必须在2-4个之间")
        
        print(f"[publisher] 创建投票: {choices}, 时长: {duration_minutes}分钟")
        
        poll_uri = await self.client.create_poll(choices, duration_minutes)
        
        print(f"[publisher] 投票创建成功，URI: {poll_uri}")
        return poll_uri
    
    async def create_thread(self, tweets: List[dict]):
        """
        发布推文串（Thread）
        
        原理：
        1. 发布第一条推文
        2. 后续每条推文都回复上一条（reply_to）
        3. 这样就形成了一个推文串
        
        Args:
            tweets: 推文列表，每个元素包含：
                - text: 推文文本
                - media_ids: 媒体ID列表（可选）
        
        Returns:
            发布的推文列表
        """
        if not tweets:
            return []
        
        print(f"[publisher] 发布推文串，共{len(tweets)}条")
        
        published_tweets = []
        reply_to = None
        
        for i, tweet_data in enumerate(tweets):
            text = tweet_data.get('text', '')
            media_ids = tweet_data.get('media_ids')
            
            print(f"[publisher] 发布第{i+1}条...")
            
            tweet = await self.create_tweet(
                text=text,
                media_ids=media_ids,
                reply_to=reply_to  # 关键：回复上一条
            )
            
            published_tweets.append(tweet)
            reply_to = tweet.id  # 更新reply_to为当前推文ID
        
        print(f"[publisher] 推文串发布完成")
        return published_tweets
    
    async def close(self):
        """关闭会话"""
        print("[publisher] 会话关闭")
        self.client = None


# ============================================================================
# 使用示例
# ============================================================================

async def example_text_tweet():
    """示例1：发布纯文本推文"""
    print("\n=== 示例1：发布纯文本推文 ===")
    
    session = TwitterPublisherSession(account_id='account_123')
    await session.initialize()
    
    tweet = await session.create_tweet(
        text="Hello World! 这是一条测试推文 #test"
    )
    
    print(f"推文链接: https://twitter.com/user/status/{tweet.id}")
    
    await session.close()


async def example_image_tweet():
    """示例2：发布图片推文"""
    print("\n=== 示例2：发布图片推文 ===")
    
    session = TwitterPublisherSession(account_id='account_123')
    await session.initialize()
    
    # 1. 上传图片
    media_ids = []
    for image_path in ['image1.jpg', 'image2.jpg']:
        media_id = await session.upload_media(image_path, media_type='image')
        media_ids.append(media_id)
    
    # 2. 发布推文
    tweet = await session.create_tweet(
        text="看看这些图片！",
        media_ids=media_ids
    )
    
    print(f"推文链接: https://twitter.com/user/status/{tweet.id}")
    
    await session.close()


async def example_video_tweet():
    """示例3：发布视频推文"""
    print("\n=== 示例3：发布视频推文 ===")
    
    session = TwitterPublisherSession(account_id='account_123')
    await session.initialize()
    
    # 1. 上传视频（twikit会自动处理分片上传）
    media_id = await session.upload_media('video.mp4', media_type='video')
    
    # 2. 发布推文
    tweet = await session.create_tweet(
        text="精彩视频分享",
        media_ids=[media_id]
    )
    
    print(f"推文链接: https://twitter.com/user/status/{tweet.id}")
    
    await session.close()


async def example_poll_tweet():
    """示例4：发布投票推文"""
    print("\n=== 示例4：发布投票推文 ===")
    
    session = TwitterPublisherSession(account_id='account_123')
    await session.initialize()
    
    # 1. 创建投票
    poll_uri = await session.create_poll(
        choices=['选项A', '选项B', '选项C'],
        duration_minutes=60
    )
    
    # 2. 发布推文
    tweet = await session.create_tweet(
        text="大家来投票吧！",
        poll_uri=poll_uri
    )
    
    print(f"推文链接: https://twitter.com/user/status/{tweet.id}")
    
    await session.close()


async def example_thread():
    """示例5：发布推文串（Thread）"""
    print("\n=== 示例5：发布推文串 ===")
    
    session = TwitterPublisherSession(account_id='account_123')
    await session.initialize()
    
    # 定义推文串
    tweets = [
        {'text': '1/ 这是一个关于Twitter发布功能的教程'},
        {'text': '2/ 首先，我们需要了解如何使用auth_token登录'},
        {'text': '3/ 然后，配置代理确保账号安全'},
        {'text': '4/ 最后，调用API发布推文'},
    ]
    
    # 发布推文串
    published_tweets = await session.create_thread(tweets)
    
    print(f"推文串链接: https://twitter.com/user/status/{published_tweets[0].id}")
    
    await session.close()


async def example_quote_tweet():
    """示例6：引用转发"""
    print("\n=== 示例6：引用转发 ===")
    
    session = TwitterPublisherSession(account_id='account_123')
    await session.initialize()
    
    tweet = await session.create_tweet(
        text="非常赞同这个观点！",
        attachment_url="https://twitter.com/user/status/1234567890"
    )
    
    print(f"推文链接: https://twitter.com/user/status/{tweet.id}")
    
    await session.close()


async def example_reply_tweet():
    """示例7：回复推文"""
    print("\n=== 示例7：回复推文 ===")
    
    session = TwitterPublisherSession(account_id='account_123')
    await session.initialize()
    
    tweet = await session.create_tweet(
        text="@username 感谢分享！",
        reply_to="1234567890"  # 要回复的推文ID
    )
    
    print(f"推文链接: https://twitter.com/user/status/{tweet.id}")
    
    await session.close()


# ============================================================================
# FastAPI集成示例
# ============================================================================

"""
在app.py中添加以下路由：

from fastapi import FastAPI, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional, List

app = FastAPI()

class TweetCreateRequest(BaseModel):
    account_id: str
    text: str = ''
    media_paths: Optional[List[str]] = None
    tweet_type: str = 'text'  # text | image | video | poll | thread | quote | reply
    poll_data: Optional[dict] = None
    thread_data: Optional[List[dict]] = None
    reply_to: Optional[str] = None
    quote_url: Optional[str] = None

@app.post("/api/tweets/create")
async def create_tweet(req: TweetCreateRequest):
    '''立即发布推文'''
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
        
        await session.close()
        
        return {
            "success": True,
            "tweet_id": tweet_id,
            "url": f"https://twitter.com/user/status/{tweet_id}"
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

@app.post("/api/tweets/upload-media")
async def upload_media(
    account_id: str = Form(...),
    file: UploadFile = File(...)
):
    '''上传媒体文件'''
    try:
        # 1. 保存文件到临时目录
        import tempfile
        temp_dir = Path(tempfile.gettempdir()) / "twitter_uploads"
        temp_dir.mkdir(exist_ok=True)
        
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
"""


# ============================================================================
# 主函数
# ============================================================================

async def main():
    """运行所有示例"""
    print("=" * 60)
    print("Twitter发布功能核心代码示例")
    print("=" * 60)
    
    # 注意：以下示例需要真实的账号和代理才能运行
    # 请根据实际情况修改_get_account_record等方法返回的数据
    
    print("\n提示：这些示例需要真实的账号和auth_token才能运行")
    print("请在TwitterPublisherSession中配置正确的账号信息")
    
    # 取消注释以运行示例
    # await example_text_tweet()
    # await example_image_tweet()
    # await example_video_tweet()
    # await example_poll_tweet()
    # await example_thread()
    # await example_quote_tweet()
    # await example_reply_tweet()


if __name__ == "__main__":
    asyncio.run(main())

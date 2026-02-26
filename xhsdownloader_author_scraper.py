import asyncio
import httpx
from urllib.parse import urlparse
from xhshow import Xhshow

# 模拟 XHS-Downloader 的核心组件
class SimpleManager:
    def __init__(self, cookie: str, proxy: str = None):
        self.cookie = cookie
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
            'Content-Type': 'application/json;charset=UTF-8',
            'Referer': 'https://www.xiaohongshu.com/',
            'Cookie': self.cookie
        }
        self.client = httpx.AsyncClient(
            headers=self.headers,
            proxies={"all://": proxy} if proxy else None,
            timeout=10,
            verify=False
        )

async def get_user_id_from_url(client: httpx.AsyncClient, url: str) -> str:
    """从作者主页URL获取user_id"""
    response = await client.get(url, follow_redirects=True)
    response.raise_for_status()
    path = urlparse(response.url.path).path
    return path.split('/')[-1]

async def main():
    # 1. 初始化 Manager 和签名工具
    # 请将你的 cookie 填入下方
    cookie = "YOUR_COOKIE_HERE"
    manager = SimpleManager(cookie=cookie)
    encipher = Xhshow()

    # 2. 定义作者主页URL
    author_url = "https://www.xiaohongshu.com/user/profile/5b489f4be8ac2b4b80067319"

    # 3. 获取 user_id
    try:
        user_id = await get_user_id_from_url(manager.client, author_url)
        print(f"成功获取到 user_id: {user_id}")
    except Exception as e:
        print(f"获取 user_id 失败: {e}")
        return

    # 4. 分页获取所有作品
    all_notes = []
    cursor = ""
    has_more = True
    page = 0

    while has_more:
        page += 1
        print(f"\n--- 正在采集第 {page} 页 ---")

        # a. 定义API接口和参数
        api_url = "/api/sns/web/v1/user_posted"
        params = {
            "user_id": user_id,
            "cursor": cursor,
            "num": 30, # 每页数量
            "image_formats": "jpg,webp,avif",
        }

        # b. 生成签名头
        signed_headers = encipher.sign_headers_get(uri=api_url, cookies=cookie, params=params)
        full_headers = manager.headers.copy()
        full_headers.update(signed_headers)

        # c. 发送请求
        try:
            full_api_url = f"https://edith.xiaohongshu.com{api_url}"
            response = await manager.client.get(full_api_url, params=params, headers=full_headers)
            response.raise_for_status()
            data = response.json()["data"]

            notes = data.get("notes", [])
            if notes:
                all_notes.extend(notes)
                print(f"已采集 {len(notes)} 篇笔记，总计 {len(all_notes)} 篇")
            
            # d. 更新分页信息
            cursor = data.get("cursor", "")
            has_more = data.get("has_more", False)

            if not has_more:
                print("所有页面采集完毕。")
            if not cursor:
                print("未找到下一页的 cursor，采集终止。")
                break

        except Exception as e:
            print(f"请求失败: {e}")
            break

    # 5. 打印第一个作品的部分信息作为示例
    if all_notes:
        first_note = all_notes[0]
        print("\n--- 采集完成，第一篇笔记信息示例 ---")
        print(f"笔记ID: {first_note.get('note_id')}")
        print(f"笔记类型: {first_note.get('type')}")
        print(f"标题: {first_note.get('display_title')}")
        print(f"点赞数: {first_note.get('interact_info', {}).get('liked_count')}")

if __name__ == "__main__":
    asyncio.run(main())

import asyncio
from f2.apps.douyin.handler import DouyinHandler

async def main():
    # 1. 初始化 DouyinHandler
    # 请将你的 cookie 填入下方
    handler = DouyinHandler(kwargs={
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0",
            "Cookie": "YOUR_COOKIE_HERE"
        },
        "proxies": {"all://": None},
        "timeout": 10
    })

    # 2. 定义作者主页URL
    # 可以是长链接或短链接
    author_url = "https://www.douyin.com/user/MS4wLjABAAAA-gq_jQp1vpl1xSj-4-lJ8W-t6c9g-b_2jXyPzJ4wY3o"

    # 3. 分页获取所有作品
    all_videos = []
    async for video_data in handler.fetch_user_post_videos(author_url):
        # video_data 是一个 UserPostFilter 对象
        # 你可以通过 ._to_list() 转换为字典列表
        video_list = video_data._to_list()
        if video_list:
            all_videos.extend(video_list)
            print(f"已采集 {len(video_list)} 个作品，总计 {len(all_videos)} 个")

    # 4. 打印第一个作品的部分信息作为示例
    if all_videos:
        first_video = all_videos[0]
        print("\n--- 采集完成，第一个作品信息示例 ---")
        print(f"作品ID: {first_video.get("aweme_id")}")
        print(f"作品描述: {first_video.get("desc")}")
        print(f"发布时间: {first_video.get("create_time")}")
        print(f"点赞数: {first_video.get("digg_count")}")
        # 注意：f2 的 filter 默认不直接提供 digg_count，需要自行从原始数据解析或修改 filter
        # 这里仅为示例，实际运行时 digg_count 可能为 None

if __name__ == "__main__":
    asyncio.run(main())

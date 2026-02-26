# F2 抖音 API 接口列表

本文档整理自 [f2 官方文档](https://f2.wiki/guide/apps/douyin/overview)，旨在提供一个清晰、易于查阅的抖音相关 API 接口列表。

**图例:**
- 🟢: 已实现
- 🟡: 正在实现或修改
- 🟤: 暂时不实现
- 🔵: 未来可能实现
- 🔴: 将会弃用

---

## `handler` 接口列表

`handler` 接口是 f2 库中用于处理具体业务逻辑的高层封装，通常组合了 `crawler` 和 `utils` 的功能。

| 功能描述 | 方法名 | 状态 |
| --- | --- | --- |
| 创建用户记录与目录 | `get_or_add_user_data` | 🟢 |
| 创建作品下载记录 | `get_or_add_video_data` | 🟢 |
| 获取用户信息 | `fetch_user_profile` | 🟢 |
| 单个作品数据 | `fetch_one_video` | 🟢 |
| 用户发布作品数据 | `fetch_user_post_videos` | 🟢 |
| 用户喜欢作品数据 | `fetch_user_like_videos` | 🟢 |
| 用户收藏原声数据 | `fetch_user_music_collection` | 🟢 |
| 用户收藏作品数据 | `fetch_user_collection_videos` | 🟢 |
| 用户收藏夹数据 | `fetch_user_collects` | 🟢 |
| 用户收藏夹作品数据 | `fetch_user_collects_videos` | 🟢 |
| 用户合集作品数据 | `fetch_user_mix_videos` | 🟢 |
| 用户直播流数据 | `fetch_user_live_videos` | 🟢 |
| 用户直播流数据 (by room_id) | `fetch_user_live_videos_by_room_id` | 🟢 |
| 用户首页推荐作品数据 | `fetch_user_feed_videos` | 🟢 |
| 相似作品数据 | `fetch_related_videos` | 🟢 |
| 好友作品数据 | `fetch_friend_feed_videos` | 🟢 |
| 关注用户数据 | `fetch_user_following` | 🟢 |
| 粉丝用户数据 | `fetch_user_follower` | 🟢 |
| 查询用户信息 | `fetch_query_user` | 🟢 |
| 查询作品的统计信息 | `fetch_post_stats` | 🟢 |
| 直播间WSS负载数据 | `fetch_live_im` | 🟢 |
| 直播间WSS弹幕 | `fetch_live_danmaku` | 🟢 |
| 关注用户的直播间信息 | `fetch_user_following_lives` | 🟢 |

## `utils` 接口列表

`utils` 提供了一系列工具类和方法，主要用于生成各种签名、ID、Token，以及处理 URL 和文件名等。

| 功能描述 | 类/方法名 | 状态 |
| --- | --- | --- |
| 管理客户端配置 | `ClientConfManager` | 🟢 |
| 生成真实 msToken | `TokenManager.gen_real_msToken` | 🟢 |
| 生成虚假 msToken | `TokenManager.gen_false_msToken` | 🟢 |
| 生成 ttwid | `TokenManager.gen_ttwid` | 🟢 |
| 生成 webid | `TokenManager.gen_webid` | 🟢 |
| 生成 verify_fp | `VerifyFpManager.gen_verify_fp` | 🟢 |
| 生成 s_v_web_id | `VerifyFpManager.gen_s_v_web_id` | 🟢 |
| 生成直播 signature | `DouyinWebcastSignature.get_signature` | 🟢 |
| 使用接口地址生成 X-Bogus | `XBogusManager.str_2_endpoint` | 🟢 |
| 使用接口模型生成 X-Bogus | `XBogusManager.model_2_endpoint` | 🟢 |
| 使用接口地址生成 A-Bogus | `ABogusManager.str_2_endpoint` | 🟢 |
| 使用接口模型生成 A-Bogus | `ABogusManager.model_2_endpoint` | 🟢 |
| 提取单个用户 sec_user_id | `SecUserIdFetcher.get_sec_user_id` | 🟢 |
| 提取列表用户 sec_user_id | `SecUserIdFetcher.get_all_sec_user_id` | 🟢 |
| 提取单个作品 aweme_id | `AwemeIdFetcher.get_aweme_id` | 🟢 |
| 提取列表作品 aweme_id | `AwemeIdFetcher.get_all_aweme_id` | 🟢 |
| 提取单个合集 mix_id | `MixIdFetcher.get_mix_id` | 🟢 |
| 提取列表合集 mix_id | `MixIdFetcher.get_all_mix_id` | 🟢 |
| 提取单个直播间 webcast_id | `WebCastIdFetcher.get_webcast_id` | 🟢 |
| 提取列表直播间 webcast_id | `WebCastIdFetcher.get_all_webcast_id` | 🟢 |
| 全局格式化文件名 | `format_file_name` | 🟢 |
| 创建用户目录 | `create_user_folder` | 🟢 |
| 重命名用户目录 | `rename_user_folder` | 🟢 |
| 创建或重命名用户目录 | `create_or_rename_user_folder` | 🟢 |
| JSON 歌词转 LRC 歌词 | `json_2_lrc` | 🟢 |

## `crawler` 接口列表

`crawler` 接口是底层的 API 请求封装，直接对应抖音的各个 Web/App 接口地址。

| 功能描述 | 方法名 | 状态 |
| --- | --- | --- |
| 用户信息接口 | `fetch_user_profile` | 🟢 |
| 主页作品接口 | `fetch_user_post` | 🟢 |
| 主页喜欢作品接口 | `fetch_user_like` | 🟢 |
| 主页收藏作品接口 | `fetch_user_collection` | 🟢 |
| 收藏夹接口 | `fetch_user_collects` | 🟢 |
| 收藏夹作品接口 | `fetch_user_collects_video` | 🟢 |
| 音乐收藏接口 | `fetch_user_music_collection` | 🟢 |
| 合集作品接口 | `fetch_user_mix` | 🟢 |
| 作品详情接口 | `fetch_post_detail` | 🟢 |
| 作品评论接口 | `fetch_post_comment` | 🟡 |
| 首页推荐作品接口 | `fetch_post_feed` | 🟡 |
| 关注作品接口 | `fetch_follow_feed` | 🟡 |
| 朋友作品接口 | `fetch_friend_feed` | 🟢 |
| 相关推荐作品接口 | `fetch_post_related` | 🟢 |
| 直播信息接口 | `fetch_live` | 🟢 |
| 直播接口地址 (by room_id) | `fetch_live_room_id` | 🟢 |
| 关注用户直播接口 | `fetch_following_live` | 🟢 |
| 定位上一次作品接口 | `fetch_locate_post` | 🟡 |
| 用户关注列表接口 | `fetch_user_following` | 🟢 |
| 用户粉丝列表接口 | `fetch_user_follower` | 🟢 |
| 直播弹幕初始化接口 | `fetch_live_im_fetch` | 🟢 |
| 查询用户接口 | `fetch_query_user` | 🟢 |
| 作品统计接口 | `fetch_post_stats` | 🟢 |

### `DouyinWebSocketCrawler` (直播弹幕)

| 功能描述 | 方法名 | 状态 |
| --- | --- | --- |
| 直播弹幕接口 | `fetch_live_danmaku` | 🟢 |
| 处理 WebSocket 消息 | `handle_wss_message` | 🟢 |
| 发送 ack 包 | `send_ack` | 🟢 |
| 发送 ping 包 | `send_ping` | 🟢 |

---

## `dl` 接口列表

`dl` 模块负责具体的下载任务处理。

| 功能描述 | 方法名 | 状态 |
| --- | --- | --- |
| 保存最后请求的作品ID | `save_last_aweme_id` | 🟢 |
| 筛选指定日期区间内的作品 | `filter_aweme_by_interval` | 🟢 |
| 创建下载任务 | `create_download_tasks` | 🟢 |
| 处理下载任务 | `process_download_tasks` | 🟢 |
| 下载原声 | `download_music` | 🟢 |
| 下载封面 | `download_cover` | 🟢 |
| 下载文案 | `download_desc` | 🟢 |
| 下载视频 | `download_video` | 🟢 |
| 下载图集 | `download_image` | 🟢 |
| 创建原声下载任务 | `create_music_download_tasks` | 🟢 |
| 处理原声下载任务 | `process_music_download_tasks` | 🟢 |
| 创建直播流下载任务 | `create_live_download_tasks` | 🟢 |
| 直播流下载 | `download_live_stream` | 🟢 |

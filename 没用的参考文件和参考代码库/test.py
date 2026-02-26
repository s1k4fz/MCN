import asyncio
import aiohttp
import json
import uuid
import requests
import ssl
import sys

# ================= ⚙️ 配置区 =================

# 你的 User-Id (保持不变)
USER_ID = "9f798c7806ee1ae795a70451352e5d1c"

# 你的代理列表 (支持 http/socks5)
# 格式: protocol://user:pass@ip:port
MY_PROXIES = ["http://userID-2608-orderid-201875-region-us:59751a2451fa4c0a@usdata.lumidaili.com:10000","http://userID-2608-orderid-18098-region-us:330d976b7d0c23e4@asdata.lumidaili.com:10000","http://userID-2608-orderid-202796-region-us:cb3cd1dbc6bef765@asdata.lumidaili.com:10000","http://userID-2608-orderid-202796-region-any:cb3cd1dbc6bef765@asdata.lumidaili.com:10000","http://userID-2608-orderid-18098-region-us:330d976b7d0c23e4@usdata.lumidaili.com:10000"]

# WebSocket 地址
WS_URL = "wss://ws.checkerproxy.net/connection/websocket"

# 伪装的 User-Agent
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"

# 生成本次任务的唯一 ID
TASK_UUID = str(uuid.uuid4())

# ================= 🧠 核心逻辑区 =================

async def start():
    # 构造完美伪装的 Headers
    headers = {
        "Origin": "https://checkerproxy.net",
        "User-Agent": USER_AGENT,
        "Accept-Language": "en,zh-CN;q=0.9,zh;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache"
    }

    print(f"⏳ [WS] 正在连接服务器...")
    
    # 禁用 SSL 验证以防止证书报错
    connector = aiohttp.TCPConnector(ssl=False)
    
    async with aiohttp.ClientSession(connector=connector) as session:
        try:
            async with session.ws_connect(WS_URL, headers=headers) as ws:
                print("📞 [WS] 连接成功！通道已建立。")
                
                # 1. 启动 HTTP 提交任务 (异步非阻塞)
                asyncio.create_task(trigger_http_check_async())

                # 2. 发送握手包 (Connect)
                await ws.send_json({"connect": {"name": "js"}, "id": 1})
                
                # 3. 发送订阅包 (Subscribe)
                await ws.send_json({
                    "subscribe": {
                        "channel": f"checker_results:{TASK_UUID}",
                        "recoverable": True
                    },
                    "id": 2
                })
                print(f"📡 [WS] 已订阅任务频道: {TASK_UUID}\n")
                print("="*60)

                # 4. 循环监听消息
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        await process_message(ws, msg.data)
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        print('❌ [WS] 连接发生错误:', ws.exception())
                        break

        except aiohttp.ClientResponseError as e:
            print(f"❌ [WS] 连接被拒绝 (Code: {e.status}): 请检查 IP 是否被封")
        except Exception as e:
            print(f"💥 [WS] 发生异常: {e}")

async def process_message(ws, message_text):
    if not message_text: return
    try:
        data = json.loads(message_text)
    except:
        return

    # 自动回复心跳 (保持连接不断)
    if data == {}:
        await ws.send_json({})
        return

    # 解析推送数据
    if "push" in data and "pub" in data["push"]:
        payload = data["push"]["pub"]["data"]
        items = payload if isinstance(payload, list) else [payload]
        
        for item in items:
            if "dsn" not in item: continue
            
            # 提取代理标识 (隐藏密码，只显示端口)
            proxy_dsn = item.get("dsn")
            try:
                proxy_short = proxy_dsn.split('@')[-1]
            except:
                proxy_short = proxy_dsn[:30] + "..."

            # === 核心解析逻辑 ===
            # 优先检查 http 协议，没有则检查 socks
            protocol_data = item.get("http") or item.get("socks") or {}
            
            # 如果协议层为空，说明还没开始测，跳过
            if not protocol_data: continue

            # 1. 判断代理是否存活
            # 's' 为 true 代表连接成功，false 代表连接失败
            is_alive = protocol_data.get("s", False)
            
            if not is_alive:
                # === 🔴 代理挂了 ===
                error_msg = protocol_data.get("err", "未知错误")
                print(f"🔴 [连接失败] {proxy_short}")
                print(f"   💀 死因: {error_msg}")
                # 常见错误：Unauthorized (密码错/白名单), Timeout (超时), EOF (中断)
                print("-" * 60)
            
            else:
                # === 🟢 代理活着，提取详细报告 ===
                real_ip = protocol_data.get("ip", "N/A")
                
                # 如果 IP 还没出来，说明是中间状态，跳过不显示
                if real_ip == "N/A" or not real_ip:
                    continue

                latency = protocol_data.get("t", 0)
                
                # 提取地理位置详情
                details = protocol_data.get("d", {})
                proxy_type = details.get("t", "Unknown") # Residential(住宅) / Corporate(机房)
                country = details.get("c", "Unknown")
                region = details.get("r", "")
                city = details.get("ct", "")
                
                # 提取评分 (sc)
                score = item.get("sc") or item.get("s", {}).get("sc", "N/A")

                # 提取服务解锁列表
                services_wrapper = item.get("s", {})
                services = services_wrapper.get("l", []) if isinstance(services_wrapper, dict) else []

                print(f"🟢 [检测成功] {proxy_short}")
                print(f"   🌐 落地IP: {real_ip}")
                print(f"   🏠 类型:   {proxy_type} (分数: {score})")
                print(f"   📍 位置:   {country} - {region} - {city}")
                print(f"   ⚡ 延迟:   {latency}s")
                
                if services:
                    print(f"   🔓 平台解锁:")
                    # 格式化打印服务状态
                    lines = []
                    for i, svc in enumerate(services):
                        status = "✅" if svc.get("s") else "❌"
                        name = svc.get("c", "未知")
                        s_lat = svc.get("t", 0)
                        lines.append(f"{status} {name:<9} {s_lat:.2f}s")
                        
                        # 每行打印 2 个服务，看起来整齐点
                        if len(lines) == 2:
                            print(f"      {'  '.join(lines)}")
                            lines = []
                    if lines: print(f"      {'  '.join(lines)}")
                else:
                    print("   ⏳ (正在检测平台解锁情况...)")
                
                print("-" * 60)

async def trigger_http_check_async():
    # 稍微等待 WebSocket 订阅生效
    await asyncio.sleep(2)
    print(f"🚀 [HTTP] 正在提交 {len(MY_PROXIES)} 个代理进行检测...")
    
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, run_requests_post)

def run_requests_post():
    url = f"https://api.checkerproxy.net/v1/landing/check/{TASK_UUID}"
    
    # 包含所有你想测的平台
    payload = {
        "archiveEnabled": True, 
        "checkType": "soft",
        "dsnList": MY_PROXIES,
        "services": ["google", "facebook", "tiktok", "twitter", "youtube", "instagram", "twitch", "spotify"],
        "timeout": 15
    }
    
    headers = {
        "User-Id": USER_ID, 
        "Content-Type": "application/json",
        "Origin": "https://checkerproxy.net", 
        "Referer": "https://checkerproxy.net/",
        "User-Agent": USER_AGENT
    }
    
    try:
        res = requests.post(url, json=payload, headers=headers)
        if res.status_code == 200:
            print("✅ [HTTP] 任务提交成功！请等待结果刷屏...\n")
        else:
            print(f"❌ [HTTP] 提交失败: {res.status_code} - {res.text}")
    except Exception as e:
        print(f"💥 [HTTP] 请求错误: {e}")

# ================= 程序入口 =================

if __name__ == "__main__":
    if not MY_PROXIES:
        print("⚠️ 请先在脚本顶部的 MY_PROXIES 列表里填入你要测的代理！")
        sys.exit()
        
    try:
        # Windows 用户可能需要取消下面这行的注释
        # asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(start())
    except KeyboardInterrupt:
        print("\n👋 检测结束，程序已退出。")
"""
推特自动化操作（基于Playwright）
"""
import asyncio
import logging
from typing import Optional
from playwright.async_api import async_playwright, Browser, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError
import pyotp
import json

from .models import TwitterAccount, ProxyConfig
from .proxy_utils import ProxyUtils

logger = logging.getLogger(__name__)


class TwitterAutomation:
    """推特自动化操作类"""
    
    def __init__(self, headless: bool = False):
        """
        初始化推特自动化
        
        Args:
            headless: 是否使用无头模式
        """
        self.headless = headless
        self.playwright = None
        self.browser: Optional[Browser] = None
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        self.playwright = await async_playwright().start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.close()
    
    async def launch_browser(self, proxy_config: Optional[ProxyConfig] = None) -> Browser:
        """
        启动浏览器
        
        Args:
            proxy_config: 代理配置（可选）
            
        Returns:
            浏览器实例
        """
        launch_options = {
            'headless': self.headless,
            'args': [
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-setuid-sandbox'
            ]
        }
        
        # 如果提供了代理配置，添加代理设置
        if proxy_config:
            proxy_settings = ProxyUtils.get_playwright_proxy_config(proxy_config)
            launch_options['proxy'] = proxy_settings
            logger.info(f"使用代理启动浏览器: {proxy_config.proxy_id}")
        
        self.browser = await self.playwright.chromium.launch(**launch_options)
        return self.browser
    
    async def create_context(self) -> BrowserContext:
        """
        创建浏览器上下文（带反检测设置）
        
        Returns:
            浏览器上下文
        """
        if not self.browser:
            raise RuntimeError("浏览器未启动，请先调用 launch_browser()")
        
        context = await self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            locale='en-US',
            timezone_id='America/New_York'
        )
        
        # 添加反检测脚本
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)
        
        return context
    
    async def login_twitter(self, page: Page, account: TwitterAccount) -> bool:
        """
        登录推特账号
        
        Args:
            page: 页面对象
            account: 推特账号信息
            
        Returns:
            登录是否成功
        """
        try:
            logger.info(f"开始登录推特账号: {account.username}")
            
            # 访问登录页面
            await page.goto('https://twitter.com/login', wait_until='domcontentloaded', timeout=60000)
            await asyncio.sleep(3)
            
            # 输入用户名
            logger.info("输入用户名...")
            username_input = await page.wait_for_selector('input[autocomplete="username"]', timeout=30000)
            await username_input.fill(account.username)
            await asyncio.sleep(1)
            
            # 点击下一步
            next_button = await page.wait_for_selector('button:has-text("Next")', timeout=10000)
            await next_button.click()
            await asyncio.sleep(2)
            
            # 检查是否需要额外验证（邮箱或用户名）
            try:
                unusual_activity = await page.wait_for_selector(
                    'input[data-testid="ocfEnterTextTextInput"]',
                    timeout=3000
                )
                logger.info("检测到额外验证，输入邮箱...")
                await unusual_activity.fill(account.email)
                await asyncio.sleep(1)
                
                next_button = await page.wait_for_selector('button:has-text("Next")', timeout=5000)
                await next_button.click()
                await asyncio.sleep(2)
            except PlaywrightTimeoutError:
                logger.info("无需额外验证")
            
            # 输入密码
            logger.info("输入密码...")
            password_input = await page.wait_for_selector('input[name="password"]', timeout=30000)
            await password_input.fill(account.password)
            await asyncio.sleep(1)
            
            # 点击登录按钮
            login_button = await page.wait_for_selector('button[data-testid="LoginForm_Login_Button"]', timeout=10000)
            await login_button.click()
            await asyncio.sleep(3)
            
            # 处理2FA（如果有）
            try:
                two_fa_input = await page.wait_for_selector(
                    'input[data-testid="ocfEnterTextTextInput"]',
                    timeout=5000
                )
                logger.info("检测到2FA验证...")
                
                if account.two_fa_secret:
                    totp = pyotp.TOTP(account.two_fa_secret)
                    code = totp.now()
                    logger.info(f"生成2FA代码: {code}")
                    
                    await two_fa_input.fill(code)
                    await asyncio.sleep(1)
                    
                    next_button = await page.wait_for_selector('button:has-text("Next")', timeout=5000)
                    await next_button.click()
                    await asyncio.sleep(3)
                else:
                    logger.error("需要2FA但未提供密钥")
                    return False
            except PlaywrightTimeoutError:
                logger.info("无需2FA验证")
            
            # 验证登录成功
            try:
                await page.wait_for_selector('[data-testid="SideNav_AccountSwitcher_Button"]', timeout=30000)
                logger.info("✓ 登录成功！")
                return True
            except PlaywrightTimeoutError:
                logger.error("登录失败：未找到主页元素")
                # 保存截图以便调试
                try:
                    await page.screenshot(path='/tmp/login_failed.png')
                    logger.info("登录失败截图已保存: /tmp/login_failed.png")
                except:
                    pass
                return False
                
        except Exception as e:
            logger.error(f"登录过程出错: {e}")
            return False
    
    async def get_current_ip_in_browser(self, page: Page) -> Optional[str]:
        """
        在浏览器环境中获取当前IP
        （这是验证的关键：在推特登录的浏览器环境中获取IP）
        
        Args:
            page: 页面对象
            
        Returns:
            当前IP地址，失败返回None
        """
        ip_check_services = [
            ('https://api.ipify.org?format=json', 'json'),
            ('https://ifconfig.me/ip', 'text'),
            ('https://icanhazip.com', 'text'),
        ]
        
        for service_url, response_type in ip_check_services:
            try:
                logger.info(f"尝试从 {service_url} 获取IP...")
                
                # 在新标签页中打开IP检测服务
                await page.goto(service_url, wait_until='networkidle', timeout=15000)
                await asyncio.sleep(1)
                
                if response_type == 'json':
                    # 获取JSON响应
                    content = await page.content()
                    if '<pre' in content:
                        pre_element = await page.query_selector('pre')
                        text = await pre_element.inner_text()
                        data = json.loads(text)
                        ip = data.get('ip', '').strip()
                    else:
                        # 尝试直接解析body
                        body = await page.query_selector('body')
                        text = await body.inner_text()
                        data = json.loads(text)
                        ip = data.get('ip', '').strip()
                else:
                    # 获取纯文本响应
                    body = await page.query_selector('body')
                    ip = (await body.inner_text()).strip()
                
                if ip and self._is_valid_ip(ip):
                    logger.info(f"✓ 成功获取IP: {ip}")
                    return ip
                else:
                    logger.warning(f"获取的IP格式无效: {ip}")
                    
            except Exception as e:
                logger.warning(f"从 {service_url} 获取IP失败: {e}")
                continue
        
        logger.error("所有IP检测服务均失败")
        return None
    
    @staticmethod
    def _is_valid_ip(ip: str) -> bool:
        """验证IP地址格式"""
        import re
        ipv4_pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
        ipv6_pattern = r'^([0-9a-fA-F]{0,4}:){7}[0-9a-fA-F]{0,4}$'
        return bool(re.match(ipv4_pattern, ip) or re.match(ipv6_pattern, ip))
    
    async def perform_twitter_action(self, page: Page, action: str = 'view_timeline') -> bool:
        """
        执行推特操作（用于进一步验证）
        
        Args:
            page: 页面对象
            action: 操作类型（view_timeline, view_profile等）
            
        Returns:
            操作是否成功
        """
        try:
            if action == 'view_timeline':
                await page.goto('https://twitter.com/home', wait_until='networkidle', timeout=15000)
                await asyncio.sleep(2)
                
                # 检查是否有timeline元素
                timeline = await page.wait_for_selector('[data-testid="primaryColumn"]', timeout=10000)
                if timeline:
                    logger.info("✓ 成功访问Timeline")
                    return True
                    
            elif action == 'view_profile':
                await page.goto('https://twitter.com/settings/account', wait_until='networkidle', timeout=15000)
                await asyncio.sleep(2)
                logger.info("✓ 成功访问个人设置")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"执行推特操作失败: {e}")
            return False
    
    async def close(self):
        """关闭浏览器"""
        if self.browser:
            await self.browser.close()
            logger.info("浏览器已关闭")
        
        if self.playwright:
            await self.playwright.stop()
            logger.info("Playwright已停止")

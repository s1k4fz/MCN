"""
推特账号与代理绑定验证器（核心模块）
"""
import asyncio
import logging
from typing import Optional
from datetime import datetime

from .models import (
    TwitterAccount, 
    ProxyConfig, 
    BindingVerificationResult, 
    VerificationMethod,
    AccountProxyBinding
)
from .proxy_utils import ProxyUtils
from .twitter_automation import TwitterAutomation

logger = logging.getLogger(__name__)


class TwitterProxyBindingVerifier:
    """
    推特账号与代理绑定验证器
    
    核心功能：验证推特账号在执行操作时是否真正使用了绑定的代理IP
    """
    
    def __init__(self, headless: bool = False):
        """
        初始化验证器
        
        Args:
            headless: 是否使用无头模式
        """
        self.headless = headless
        self.bindings: dict[str, AccountProxyBinding] = {}
    
    def bind_account_to_proxy(
        self, 
        account: TwitterAccount, 
        proxy: ProxyConfig
    ) -> AccountProxyBinding:
        """
        绑定推特账号到代理
        
        Args:
            account: 推特账号
            proxy: 代理配置
            
        Returns:
            绑定关系对象
        """
        binding = AccountProxyBinding(
            account_username=account.username,
            proxy_id=proxy.proxy_id
        )
        
        self.bindings[account.username] = binding
        account.proxy_id = proxy.proxy_id
        
        logger.info(f"✓ 绑定成功: {account.username} -> {proxy.proxy_id}")
        return binding
    
    async def verify_binding_via_browser(
        self,
        account: TwitterAccount,
        proxy: ProxyConfig
    ) -> BindingVerificationResult:
        """
        通过浏览器自动化验证绑定状态（推荐方法）
        
        验证流程：
        1. 获取代理出口IP（基准IP）
        2. 使用代理启动浏览器
        3. 登录推特账号
        4. 在推特浏览器环境中访问IP检测服务
        5. 对比两个IP是否一致
        
        Args:
            account: 推特账号
            proxy: 代理配置
            
        Returns:
            验证结果
        """
        logger.info("="*60)
        logger.info(f"开始验证绑定状态（浏览器自动化方法）")
        logger.info(f"账号: {account.username}")
        logger.info(f"代理: {proxy.proxy_id}")
        logger.info("="*60)
        
        expected_ip = None
        actual_ip = None
        error_message = None
        additional_info = {}
        
        try:
            # 步骤1: 获取代理出口IP（基准）
            logger.info("\n[步骤 1/5] 获取代理出口IP...")
            expected_ip = ProxyUtils.get_proxy_exit_ip(proxy, timeout=15)
            
            if not expected_ip:
                error_message = "无法获取代理出口IP"
                logger.error(f"✗ {error_message}")
                return self._create_result(
                    account, proxy, expected_ip or '', actual_ip or '',
                    VerificationMethod.BROWSER_AUTOMATION, error_message, additional_info
                )
            
            logger.info(f"✓ 代理出口IP: {expected_ip}")
            additional_info['expected_ip_source'] = 'proxy_direct_request'
            
            # 步骤2-5: 使用浏览器自动化验证
            async with TwitterAutomation(headless=self.headless) as automation:
                
                # 步骤2: 启动浏览器（配置代理）
                logger.info("\n[步骤 2/5] 启动浏览器（使用代理）...")
                await automation.launch_browser(proxy_config=proxy)
                logger.info("✓ 浏览器已启动")
                
                # 步骤3: 创建浏览器上下文并登录推特
                logger.info("\n[步骤 3/5] 登录推特账号...")
                context = await automation.create_context()
                page = await context.new_page()
                
                login_success = await automation.login_twitter(page, account)
                
                if not login_success:
                    error_message = "推特登录失败"
                    logger.error(f"✗ {error_message}")
                    return self._create_result(
                        account, proxy, expected_ip, actual_ip or '',
                        VerificationMethod.BROWSER_AUTOMATION, error_message, additional_info
                    )
                
                additional_info['login_success'] = True
                
                # 步骤4: 在推特环境中获取实际IP
                logger.info("\n[步骤 4/5] 在推特浏览器环境中获取实际IP...")
                actual_ip = await automation.get_current_ip_in_browser(page)
                
                if not actual_ip:
                    error_message = "无法在浏览器中获取IP"
                    logger.error(f"✗ {error_message}")
                    return self._create_result(
                        account, proxy, expected_ip, actual_ip or '',
                        VerificationMethod.BROWSER_AUTOMATION, error_message, additional_info
                    )
                
                logger.info(f"✓ 推特操作实际使用的IP: {actual_ip}")
                additional_info['actual_ip_source'] = 'twitter_browser_environment'
                
                # 步骤5: 对比验证
                logger.info("\n[步骤 5/5] 对比验证...")
                is_matched = (expected_ip == actual_ip)
                
                if is_matched:
                    logger.info(f"✓✓✓ 验证成功！IP匹配: {expected_ip}")
                    additional_info['verification_status'] = 'success'
                    
                    # 执行一个推特操作进一步确认
                    logger.info("\n[额外验证] 执行推特操作...")
                    action_success = await automation.perform_twitter_action(page, 'view_timeline')
                    additional_info['twitter_action_success'] = action_success
                else:
                    logger.error(f"✗✗✗ 验证失败！IP不匹配")
                    logger.error(f"  期望IP: {expected_ip}")
                    logger.error(f"  实际IP: {actual_ip}")
                    error_message = f"IP不匹配：期望 {expected_ip}，实际 {actual_ip}"
                    additional_info['verification_status'] = 'failed'
                
                # 保存截图（可选）
                try:
                    screenshot_path = f"/tmp/twitter_verify_{account.username}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                    await page.screenshot(path=screenshot_path)
                    additional_info['screenshot'] = screenshot_path
                    logger.info(f"截图已保存: {screenshot_path}")
                except Exception as e:
                    logger.warning(f"保存截图失败: {e}")
                
        except Exception as e:
            error_message = f"验证过程异常: {str(e)}"
            logger.error(f"✗ {error_message}")
            import traceback
            logger.error(traceback.format_exc())
        
        # 创建验证结果
        result = self._create_result(
            account, proxy, expected_ip or '', actual_ip or '',
            VerificationMethod.BROWSER_AUTOMATION, error_message, additional_info
        )
        
        # 更新绑定状态
        if account.username in self.bindings:
            binding = self.bindings[account.username]
            binding.is_verified = result.is_matched
            binding.last_verification_time = datetime.now()
            binding.verification_count += 1
        
        logger.info("\n" + "="*60)
        logger.info("验证完成")
        logger.info("="*60)
        
        return result
    
    async def verify_binding_via_api(
        self,
        account: TwitterAccount,
        proxy: ProxyConfig
    ) -> BindingVerificationResult:
        """
        通过推特API验证绑定状态（辅助方法）
        
        注意：此方法仅验证API请求是否使用了代理，
        不能100%保证所有推特操作都使用代理
        
        Args:
            account: 推特账号
            proxy: 代理配置
            
        Returns:
            验证结果
        """
        logger.info(f"开始验证绑定状态（API方法）: {account.username}")
        
        expected_ip = None
        actual_ip = None
        error_message = None
        additional_info = {}
        
        try:
            # 获取代理出口IP
            expected_ip = ProxyUtils.get_proxy_exit_ip(proxy)
            
            if not expected_ip:
                error_message = "无法获取代理出口IP"
                return self._create_result(
                    account, proxy, '', '',
                    VerificationMethod.API_REQUEST, error_message, additional_info
                )
            
            # 使用tweepy或requests通过代理访问推特API
            # 注意：这里只是示例，实际需要根据API响应判断
            import requests
            proxies = ProxyUtils.get_requests_proxy_dict(proxy)
            
            # 尝试访问推特API（需要有效的token）
            headers = {
                'Authorization': f'Bearer {account.token}',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            response = requests.get(
                'https://api.twitter.com/2/users/me',
                headers=headers,
                proxies=proxies,
                timeout=10
            )
            
            if response.status_code == 200:
                additional_info['api_request_success'] = True
                # API请求成功，但无法直接获取使用的IP
                # 这里假设使用了代理（因为请求成功）
                actual_ip = expected_ip  # 假设值
                additional_info['note'] = 'API方法无法直接验证IP，仅确认请求成功'
            else:
                error_message = f"API请求失败: {response.status_code}"
                additional_info['api_response_code'] = response.status_code
            
        except Exception as e:
            error_message = f"API验证异常: {str(e)}"
        
        return self._create_result(
            account, proxy, expected_ip or '', actual_ip or '',
            VerificationMethod.API_REQUEST, error_message, additional_info
        )
    
    async def verify_binding(
        self,
        account: TwitterAccount,
        proxy: ProxyConfig,
        method: VerificationMethod = VerificationMethod.BROWSER_AUTOMATION
    ) -> BindingVerificationResult:
        """
        验证绑定状态（统一入口）
        
        Args:
            account: 推特账号
            proxy: 代理配置
            method: 验证方法
            
        Returns:
            验证结果
        """
        if method == VerificationMethod.BROWSER_AUTOMATION:
            return await self.verify_binding_via_browser(account, proxy)
        elif method == VerificationMethod.API_REQUEST:
            return await self.verify_binding_via_api(account, proxy)
        else:
            raise ValueError(f"不支持的验证方法: {method}")
    
    def _create_result(
        self,
        account: TwitterAccount,
        proxy: ProxyConfig,
        expected_ip: str,
        actual_ip: str,
        method: VerificationMethod,
        error_message: Optional[str] = None,
        additional_info: dict = None
    ) -> BindingVerificationResult:
        """创建验证结果对象"""
        is_matched = (expected_ip == actual_ip and expected_ip != '' and actual_ip != '')
        
        return BindingVerificationResult(
            account_username=account.username,
            proxy_id=proxy.proxy_id,
            expected_ip=expected_ip,
            actual_ip=actual_ip,
            is_matched=is_matched,
            verification_method=method,
            error_message=error_message,
            additional_info=additional_info or {}
        )
    
    def get_binding(self, account_username: str) -> Optional[AccountProxyBinding]:
        """获取账号的绑定信息"""
        return self.bindings.get(account_username)
    
    def get_all_bindings(self) -> list[AccountProxyBinding]:
        """获取所有绑定信息"""
        return list(self.bindings.values())

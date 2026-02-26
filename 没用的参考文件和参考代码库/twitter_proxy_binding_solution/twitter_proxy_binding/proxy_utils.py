"""
代理相关的工具函数
"""
import requests
from typing import Dict, Optional
from .models import ProxyConfig, ProxyProtocol
import logging

logger = logging.getLogger(__name__)


class ProxyUtils:
    """代理工具类"""
    
    # IP检测服务列表（按优先级排序）
    IP_CHECK_SERVICES = [
        'https://api.ipify.org?format=json',
        'https://api64.ipify.org?format=json',
        'https://ifconfig.me/ip',
        'https://icanhazip.com',
        'https://ipinfo.io/ip',
    ]
    
    @staticmethod
    def get_requests_proxy_dict(proxy_config: ProxyConfig) -> Dict[str, str]:
        """
        获取requests库使用的代理字典
        
        Args:
            proxy_config: 代理配置
            
        Returns:
            代理字典，格式: {'http': 'http://...', 'https': 'http://...'}
        """
        proxy_url = proxy_config.get_full_url()
        return {
            'http': proxy_url,
            'https': proxy_url
        }
    
    @staticmethod
    def get_playwright_proxy_config(proxy_config: ProxyConfig) -> Dict[str, str]:
        """
        获取Playwright使用的代理配置
        
        Args:
            proxy_config: 代理配置
            
        Returns:
            Playwright代理配置字典
        """
        components = proxy_config.parse_components()
        return {
            'server': f"{proxy_config.protocol.value}://{components['host']}:{components['port']}",
            'username': components['username'],
            'password': components['password']
        }
    
    @staticmethod
    def get_selenium_proxy_config(proxy_config: ProxyConfig) -> str:
        """
        获取Selenium使用的代理配置
        
        Args:
            proxy_config: 代理配置
            
        Returns:
            代理字符串，格式: host:port
        """
        components = proxy_config.parse_components()
        return f"{components['host']}:{components['port']}"
    
    @staticmethod
    def get_proxy_exit_ip(proxy_config: ProxyConfig, timeout: int = 10) -> Optional[str]:
        """
        获取代理的出口IP（通过代理访问IP检测服务）
        
        Args:
            proxy_config: 代理配置
            timeout: 超时时间（秒）
            
        Returns:
            代理出口IP，如果获取失败返回None
        """
        proxies = ProxyUtils.get_requests_proxy_dict(proxy_config)
        
        # 尝试多个IP检测服务
        for service_url in ProxyUtils.IP_CHECK_SERVICES:
            try:
                logger.info(f"尝试通过 {service_url} 获取代理出口IP...")
                response = requests.get(
                    service_url,
                    proxies=proxies,
                    timeout=timeout,
                    headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                )
                response.raise_for_status()
                
                # 根据不同服务解析IP
                if 'ipify' in service_url:
                    ip = response.json()['ip']
                else:
                    ip = response.text.strip()
                
                logger.info(f"成功获取代理出口IP: {ip}")
                return ip
                
            except Exception as e:
                logger.warning(f"从 {service_url} 获取IP失败: {e}")
                continue
        
        logger.error("所有IP检测服务均失败")
        return None
    
    @staticmethod
    def test_proxy_connectivity(proxy_config: ProxyConfig, timeout: int = 10) -> bool:
        """
        测试代理连通性
        
        Args:
            proxy_config: 代理配置
            timeout: 超时时间（秒）
            
        Returns:
            代理是否可用
        """
        ip = ProxyUtils.get_proxy_exit_ip(proxy_config, timeout)
        return ip is not None
    
    @staticmethod
    def parse_proxy_from_url(proxy_url: str, proxy_id: Optional[str] = None) -> ProxyConfig:
        """
        从代理URL字符串解析ProxyConfig对象
        
        Args:
            proxy_url: 代理URL，格式: username:password@host:port
            proxy_id: 代理ID，如果不提供则自动生成
            
        Returns:
            ProxyConfig对象
        """
        import hashlib
        
        if not proxy_id:
            # 根据URL生成唯一ID
            proxy_id = hashlib.md5(proxy_url.encode()).hexdigest()[:12]
        
        # 尝试从URL中提取region信息
        region = None
        if 'region-' in proxy_url:
            import re
            match = re.search(r'region-(\w+)', proxy_url)
            if match:
                region = match.group(1)
        
        return ProxyConfig(
            proxy_id=proxy_id,
            proxy_url=proxy_url,
            protocol=ProxyProtocol.HTTP,
            region=region
        )
    
    @staticmethod
    def validate_proxy_format(proxy_url: str) -> bool:
        """
        验证代理URL格式是否正确
        
        Args:
            proxy_url: 代理URL
            
        Returns:
            格式是否正确
        """
        import re
        pattern = r'^.+:.+@.+:\d+$'
        return bool(re.match(pattern, proxy_url))


class ProxyPool:
    """代理池管理"""
    
    def __init__(self):
        self.proxies: Dict[str, ProxyConfig] = {}
        self.bindings: Dict[str, str] = {}  # account_username -> proxy_id
    
    def add_proxy(self, proxy_config: ProxyConfig) -> None:
        """添加代理到池中"""
        self.proxies[proxy_config.proxy_id] = proxy_config
        logger.info(f"添加代理: {proxy_config}")
    
    def remove_proxy(self, proxy_id: str) -> None:
        """从池中移除代理"""
        if proxy_id in self.proxies:
            del self.proxies[proxy_id]
            logger.info(f"移除代理: {proxy_id}")
    
    def get_proxy(self, proxy_id: str) -> Optional[ProxyConfig]:
        """获取指定代理"""
        return self.proxies.get(proxy_id)
    
    def get_available_proxy(self) -> Optional[ProxyConfig]:
        """获取一个可用的未绑定代理"""
        bound_proxy_ids = set(self.bindings.values())
        
        for proxy_id, proxy_config in self.proxies.items():
            if proxy_id not in bound_proxy_ids and proxy_config.is_healthy:
                return proxy_config
        
        return None
    
    def bind_account(self, account_username: str, proxy_id: str) -> bool:
        """绑定账号到代理"""
        if proxy_id not in self.proxies:
            logger.error(f"代理 {proxy_id} 不存在")
            return False
        
        self.bindings[account_username] = proxy_id
        logger.info(f"绑定账号 {account_username} 到代理 {proxy_id}")
        return True
    
    def unbind_account(self, account_username: str) -> None:
        """解绑账号"""
        if account_username in self.bindings:
            proxy_id = self.bindings[account_username]
            del self.bindings[account_username]
            logger.info(f"解绑账号 {account_username} 从代理 {proxy_id}")
    
    def get_account_proxy(self, account_username: str) -> Optional[ProxyConfig]:
        """获取账号绑定的代理"""
        proxy_id = self.bindings.get(account_username)
        if proxy_id:
            return self.proxies.get(proxy_id)
        return None
    
    def get_pool_status(self) -> dict:
        """获取代理池状态"""
        total = len(self.proxies)
        healthy = sum(1 for p in self.proxies.values() if p.is_healthy)
        bound = len(self.bindings)
        available = sum(1 for pid in self.proxies.keys() 
                       if pid not in self.bindings.values() and self.proxies[pid].is_healthy)
        
        return {
            'total': total,
            'healthy': healthy,
            'bound': bound,
            'available': available
        }

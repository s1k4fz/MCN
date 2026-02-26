"""
推特账号与代理绑定的数据模型
"""
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime
from enum import Enum


class ProxyProtocol(Enum):
    """代理协议类型"""
    HTTP = "http"
    HTTPS = "https"
    SOCKS5 = "socks5"


class VerificationMethod(Enum):
    """验证方法"""
    BROWSER_AUTOMATION = "browser_automation"  # 浏览器自动化（推荐）
    API_REQUEST = "api_request"  # API请求（辅助）
    COMBINED = "combined"  # 综合验证


@dataclass
class TwitterAccount:
    """推特账号信息"""
    username: str
    password: str
    email: str
    two_fa_secret: str  # 2FA密钥（TOTP）
    token: str  # API token
    auth_token: str  # Cookie中的auth_token
    proxy_id: Optional[str] = None  # 绑定的代理ID
    
    def __str__(self):
        return f"TwitterAccount({self.username})"
    
    @classmethod
    def from_string(cls, account_str: str) -> 'TwitterAccount':
        """
        从字符串解析账号信息
        格式: 账号----密码----邮箱----2FA----token----auth_token
        """
        parts = account_str.split('----')
        if len(parts) != 6:
            raise ValueError(f"账号格式错误，期望6个字段，实际{len(parts)}个")
        
        return cls(
            username=parts[0].strip(),
            password=parts[1].strip(),
            email=parts[2].strip(),
            two_fa_secret=parts[3].strip(),
            token=parts[4].strip(),
            auth_token=parts[5].strip()
        )


@dataclass
class ProxyConfig:
    """代理配置信息"""
    proxy_id: str
    proxy_url: str  # 格式: username:password@host:port
    protocol: ProxyProtocol = ProxyProtocol.HTTP
    expected_ip: Optional[str] = None  # 代理的出口IP（验证基准）
    region: Optional[str] = None  # 代理地区
    is_healthy: bool = True  # 代理健康状态
    last_check_time: Optional[datetime] = None
    
    def __str__(self):
        return f"ProxyConfig({self.proxy_id}, IP: {self.expected_ip or 'Unknown'})"
    
    def get_full_url(self) -> str:
        """获取完整的代理URL"""
        return f"{self.protocol.value}://{self.proxy_url}"
    
    def parse_components(self) -> dict:
        """解析代理URL的各个组成部分"""
        import re
        match = re.match(r'(.+):(.+)@(.+):(\d+)', self.proxy_url)
        if not match:
            raise ValueError(f"代理URL格式错误: {self.proxy_url}")
        
        return {
            'username': match.group(1),
            'password': match.group(2),
            'host': match.group(3),
            'port': int(match.group(4))
        }


@dataclass
class AccountProxyBinding:
    """账号与代理的绑定关系"""
    account_username: str
    proxy_id: str
    bind_time: datetime = field(default_factory=datetime.now)
    is_verified: bool = False
    last_verification_time: Optional[datetime] = None
    verification_count: int = 0
    
    def __str__(self):
        status = "已验证" if self.is_verified else "未验证"
        return f"Binding({self.account_username} -> {self.proxy_id}, {status})"


@dataclass
class BindingVerificationResult:
    """绑定验证结果"""
    account_username: str
    proxy_id: str
    expected_ip: str  # 代理出口IP（基准）
    actual_ip: str  # 推特操作实际使用的IP
    is_matched: bool  # IP是否匹配
    verification_method: VerificationMethod
    timestamp: datetime = field(default_factory=datetime.now)
    error_message: Optional[str] = None
    additional_info: dict = field(default_factory=dict)
    
    def __str__(self):
        status = "✓ 成功" if self.is_matched else "✗ 失败"
        return (f"VerificationResult({status})\n"
                f"  账号: {self.account_username}\n"
                f"  代理: {self.proxy_id}\n"
                f"  期望IP: {self.expected_ip}\n"
                f"  实际IP: {self.actual_ip}\n"
                f"  方法: {self.verification_method.value}\n"
                f"  时间: {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
    
    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            'account_username': self.account_username,
            'proxy_id': self.proxy_id,
            'expected_ip': self.expected_ip,
            'actual_ip': self.actual_ip,
            'is_matched': self.is_matched,
            'verification_method': self.verification_method.value,
            'timestamp': self.timestamp.isoformat(),
            'error_message': self.error_message,
            'additional_info': self.additional_info
        }
    
    @property
    def success(self) -> bool:
        """验证是否成功"""
        return self.is_matched and not self.error_message

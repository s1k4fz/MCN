"""
推特账号与代理一一绑定及验证模块
"""

from .models import (
    TwitterAccount,
    ProxyConfig,
    ProxyProtocol,
    AccountProxyBinding,
    BindingVerificationResult,
    VerificationMethod
)

from .proxy_utils import ProxyUtils, ProxyPool

from .twitter_automation import TwitterAutomation

from .binding_verifier import TwitterProxyBindingVerifier

__version__ = '1.0.0'

__all__ = [
    'TwitterAccount',
    'ProxyConfig',
    'ProxyProtocol',
    'AccountProxyBinding',
    'BindingVerificationResult',
    'VerificationMethod',
    'ProxyUtils',
    'ProxyPool',
    'TwitterAutomation',
    'TwitterProxyBindingVerifier',
]

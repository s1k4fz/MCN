"""
推特账号与代理绑定验证 - 实际应用示例
"""
import asyncio
import logging
import json
from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

from twitter_proxy_binding import (
    TwitterAccount,
    ProxyConfig,
    ProxyUtils,
    ProxyPool,
    TwitterProxyBindingVerifier,
    BindingVerificationResult
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


class TwitterProxyManager:
    """推特账号与代理管理器"""
    
    def __init__(self, accounts_file: str, proxies_file: str):
        """
        初始化管理器
        
        Args:
            accounts_file: 账号文件路径（每行一个账号，格式：账号----密码----邮箱----2FA----token----auth_token）
            proxies_file: 代理文件路径（每行一个代理，格式：username:password@host:port）
        """
        self.accounts_file = accounts_file
        self.proxies_file = proxies_file
        self.accounts = []
        self.proxy_pool = ProxyPool()
        self.verifier = TwitterProxyBindingVerifier(headless=True)
        self.results = []
    
    def load_accounts(self):
        """加载推特账号"""
        logger.info(f"从 {self.accounts_file} 加载账号...")
        
        try:
            with open(self.accounts_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        try:
                            account = TwitterAccount.from_string(line)
                            self.accounts.append(account)
                            logger.info(f"  ✓ 加载账号: {account.username}")
                        except Exception as e:
                            logger.error(f"  ✗ 解析账号失败: {line[:30]}... - {e}")
            
            logger.info(f"✓ 共加载 {len(self.accounts)} 个账号")
        except FileNotFoundError:
            logger.error(f"✗ 账号文件不存在: {self.accounts_file}")
    
    def load_proxies(self):
        """加载代理"""
        logger.info(f"从 {self.proxies_file} 加载代理...")
        
        try:
            with open(self.proxies_file, 'r', encoding='utf-8') as f:
                for idx, line in enumerate(f, 1):
                    line = line.strip()
                    if line and not line.startswith('#'):
                        try:
                            proxy_id = f"proxy_{idx:03d}"
                            proxy = ProxyUtils.parse_proxy_from_url(line, proxy_id)
                            
                            # 测试代理并获取出口IP
                            exit_ip = ProxyUtils.get_proxy_exit_ip(proxy, timeout=10)
                            if exit_ip:
                                proxy.expected_ip = exit_ip
                                proxy.is_healthy = True
                                self.proxy_pool.add_proxy(proxy)
                                logger.info(f"  ✓ 加载代理: {proxy_id} (IP: {exit_ip})")
                            else:
                                logger.warning(f"  ✗ 代理不可用: {proxy_id}")
                        except Exception as e:
                            logger.error(f"  ✗ 解析代理失败: {line[:30]}... - {e}")
            
            status = self.proxy_pool.get_pool_status()
            logger.info(f"✓ 共加载 {status['healthy']} 个可用代理")
        except FileNotFoundError:
            logger.error(f"✗ 代理文件不存在: {self.proxies_file}")
    
    def auto_bind_accounts(self):
        """自动绑定账号到代理（一一对应）"""
        logger.info("\n开始自动绑定账号到代理...")
        
        for account in self.accounts:
            # 获取一个可用的未绑定代理
            proxy = self.proxy_pool.get_available_proxy()
            
            if proxy:
                # 绑定
                self.proxy_pool.bind_account(account.username, proxy.proxy_id)
                self.verifier.bind_account_to_proxy(account, proxy)
                logger.info(f"  ✓ {account.username} -> {proxy.proxy_id} (IP: {proxy.expected_ip})")
            else:
                logger.warning(f"  ✗ {account.username} - 无可用代理")
        
        logger.info("✓ 自动绑定完成")
    
    async def verify_all_bindings(self):
        """验证所有绑定"""
        logger.info("\n开始验证所有绑定...")
        
        for account in self.accounts:
            # 获取账号绑定的代理
            proxy = self.proxy_pool.get_account_proxy(account.username)
            
            if not proxy:
                logger.warning(f"  ✗ {account.username} - 未绑定代理")
                continue
            
            logger.info(f"\n验证: {account.username} -> {proxy.proxy_id}")
            
            try:
                # 验证绑定
                result = await self.verifier.verify_binding(account, proxy)
                self.results.append(result)
                
                # 输出结果
                if result.success:
                    logger.info(f"  ✓ 验证成功！IP: {result.actual_ip}")
                else:
                    logger.error(f"  ✗ 验证失败！")
                    if result.error_message:
                        logger.error(f"    错误: {result.error_message}")
                    if result.expected_ip and result.actual_ip:
                        logger.error(f"    期望IP: {result.expected_ip}")
                        logger.error(f"    实际IP: {result.actual_ip}")
            
            except Exception as e:
                logger.error(f"  ✗ 验证异常: {e}")
        
        logger.info("\n✓ 所有验证完成")
    
    def save_results(self, output_file: str):
        """保存验证结果"""
        logger.info(f"\n保存验证结果到 {output_file}...")
        
        results_data = {
            'timestamp': datetime.now().isoformat(),
            'total_accounts': len(self.accounts),
            'total_proxies': self.proxy_pool.get_pool_status()['total'],
            'verified_count': len(self.results),
            'success_count': sum(1 for r in self.results if r.success),
            'failed_count': sum(1 for r in self.results if not r.success),
            'results': [r.to_dict() for r in self.results]
        }
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"✓ 结果已保存")
        logger.info(f"  总账号数: {results_data['total_accounts']}")
        logger.info(f"  总代理数: {results_data['total_proxies']}")
        logger.info(f"  验证成功: {results_data['success_count']}")
        logger.info(f"  验证失败: {results_data['failed_count']}")
    
    def print_summary(self):
        """打印摘要"""
        logger.info("\n" + "="*80)
        logger.info("验证摘要")
        logger.info("="*80)
        
        # 代理池状态
        pool_status = self.proxy_pool.get_pool_status()
        logger.info(f"\n代理池状态:")
        logger.info(f"  总代理数: {pool_status['total']}")
        logger.info(f"  健康代理: {pool_status['healthy']}")
        logger.info(f"  已绑定: {pool_status['bound']}")
        logger.info(f"  可用: {pool_status['available']}")
        
        # 验证结果统计
        if self.results:
            success_count = sum(1 for r in self.results if r.success)
            failed_count = len(self.results) - success_count
            success_rate = (success_count / len(self.results)) * 100
            
            logger.info(f"\n验证结果:")
            logger.info(f"  总验证数: {len(self.results)}")
            logger.info(f"  成功: {success_count}")
            logger.info(f"  失败: {failed_count}")
            logger.info(f"  成功率: {success_rate:.1f}%")
        
        logger.info("\n" + "="*80)


async def main():
    """主函数"""
    
    # 创建示例文件
    accounts_file = '/home/ubuntu/accounts.txt'
    proxies_file = '/home/ubuntu/proxies.txt'
    
    # 创建示例账号文件
    with open(accounts_file, 'w', encoding='utf-8') as f:
        f.write("# 推特账号列表\n")
        f.write("# 格式：账号----密码----邮箱----2FA----token----auth_token\n")
        f.write("JessicaFer20452----oC7rFGm9GT----stepanova.7pziv@rambler.ru----wSBrH0Bs42xDWD----RHW65QIADO2QBWMU----f5ee5a62f08ddc1080c06198ce1b5bded1810a20\n")
    
    # 创建示例代理文件
    with open(proxies_file, 'w', encoding='utf-8') as f:
        f.write("# 代理列表\n")
        f.write("# 格式：username:password@host:port\n")
        f.write("userID-2608-orderid-201875-region-us:59751a2451fa4c0a@usdata.lumidaili.com:10000\n")
    
    logger.info("="*80)
    logger.info("推特账号与代理绑定管理系统")
    logger.info("="*80)
    
    # 创建管理器
    manager = TwitterProxyManager(accounts_file, proxies_file)
    
    # 1. 加载账号和代理
    manager.load_accounts()
    manager.load_proxies()
    
    # 2. 自动绑定
    manager.auto_bind_accounts()
    
    # 3. 验证绑定（可选，因为推特登录可能失败）
    # 如果要实际验证，取消下面的注释
    # await manager.verify_all_bindings()
    
    # 4. 保存结果
    # manager.save_results('/home/ubuntu/verification_results.json')
    
    # 5. 打印摘要
    manager.print_summary()
    
    logger.info("\n✓ 完成！")


if __name__ == '__main__':
    asyncio.run(main())

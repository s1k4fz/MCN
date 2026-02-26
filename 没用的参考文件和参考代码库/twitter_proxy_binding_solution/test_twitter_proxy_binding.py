"""
推特账号与代理绑定验证 - 测试脚本
"""
import asyncio
import logging
import sys
from pathlib import Path

# 添加模块路径
sys.path.insert(0, str(Path(__file__).parent))

from twitter_proxy_binding import (
    TwitterAccount,
    ProxyConfig,
    ProxyUtils,
    TwitterProxyBindingVerifier,
    VerificationMethod
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('twitter_proxy_verification.log', encoding='utf-8')
    ]
)

logger = logging.getLogger(__name__)


async def test_single_binding():
    """测试单个账号的绑定验证"""
    
    # 测试数据
    account_str = "JessicaFer20452----oC7rFGm9GT----stepanova.7pziv@rambler.ru----wSBrH0Bs42xDWD----RHW65QIADO2QBWMU----f5ee5a62f08ddc1080c06198ce1b5bded1810a20"
    proxy_url = "userID-2608-orderid-201875-region-us:59751a2451fa4c0a@usdata.lumidaili.com:10000"
    
    logger.info("="*80)
    logger.info("推特账号与代理绑定验证测试")
    logger.info("="*80)
    
    # 1. 解析账号信息
    logger.info("\n[1] 解析推特账号信息...")
    try:
        account = TwitterAccount.from_string(account_str)
        logger.info(f"✓ 账号解析成功: {account.username}")
        logger.info(f"  - 邮箱: {account.email}")
        logger.info(f"  - 2FA: {'已配置' if account.two_fa_secret else '未配置'}")
    except Exception as e:
        logger.error(f"✗ 账号解析失败: {e}")
        return
    
    # 2. 解析代理配置
    logger.info("\n[2] 解析代理配置...")
    try:
        proxy = ProxyUtils.parse_proxy_from_url(proxy_url, proxy_id="test_proxy_001")
        logger.info(f"✓ 代理解析成功: {proxy.proxy_id}")
        logger.info(f"  - URL: {proxy.proxy_url}")
        logger.info(f"  - 地区: {proxy.region or '未知'}")
    except Exception as e:
        logger.error(f"✗ 代理解析失败: {e}")
        return
    
    # 3. 测试代理连通性（获取出口IP）
    logger.info("\n[3] 测试代理连通性...")
    try:
        exit_ip = ProxyUtils.get_proxy_exit_ip(proxy, timeout=15)
        if exit_ip:
            proxy.expected_ip = exit_ip
            logger.info(f"✓ 代理可用，出口IP: {exit_ip}")
        else:
            logger.error("✗ 代理不可用或无法获取出口IP")
            return
    except Exception as e:
        logger.error(f"✗ 代理测试失败: {e}")
        return
    
    # 4. 创建验证器并绑定
    logger.info("\n[4] 绑定账号到代理...")
    verifier = TwitterProxyBindingVerifier(headless=True)  # 无头模式（服务器环境）
    
    try:
        binding = verifier.bind_account_to_proxy(account, proxy)
        logger.info(f"✓ 绑定成功: {binding}")
    except Exception as e:
        logger.error(f"✗ 绑定失败: {e}")
        return
    
    # 5. 验证绑定状态（核心步骤）
    logger.info("\n[5] 验证绑定状态（浏览器自动化方法）...")
    logger.info("提示：浏览器将会打开，请观察自动化过程...")
    
    try:
        result = await verifier.verify_binding(
            account=account,
            proxy=proxy,
            method=VerificationMethod.BROWSER_AUTOMATION
        )
        
        # 6. 输出验证结果
        logger.info("\n" + "="*80)
        logger.info("验证结果")
        logger.info("="*80)
        print(result)
        logger.info("")
        
        if result.success:
            logger.info("🎉 验证成功！推特账号已正确绑定到代理")
            logger.info(f"✓ 推特操作使用的IP: {result.actual_ip}")
            logger.info(f"✓ 代理出口IP: {result.expected_ip}")
            logger.info(f"✓ IP匹配: 是")
        else:
            logger.error("❌ 验证失败！")
            if result.error_message:
                logger.error(f"错误信息: {result.error_message}")
            if result.expected_ip and result.actual_ip:
                logger.error(f"期望IP: {result.expected_ip}")
                logger.error(f"实际IP: {result.actual_ip}")
        
        # 输出额外信息
        if result.additional_info:
            logger.info("\n额外信息:")
            for key, value in result.additional_info.items():
                logger.info(f"  - {key}: {value}")
        
        return result
        
    except Exception as e:
        logger.error(f"✗ 验证过程异常: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None


async def test_proxy_only():
    """仅测试代理（不涉及推特登录）"""
    
    proxy_url = "userID-2608-orderid-201875-region-us:59751a2451fa4c0a@usdata.lumidaili.com:10000"
    
    logger.info("="*80)
    logger.info("代理连通性测试")
    logger.info("="*80)
    
    # 解析代理
    proxy = ProxyUtils.parse_proxy_from_url(proxy_url, proxy_id="test_proxy_001")
    logger.info(f"代理ID: {proxy.proxy_id}")
    logger.info(f"代理URL: {proxy.proxy_url}")
    
    # 测试连通性
    logger.info("\n测试代理连通性...")
    exit_ip = ProxyUtils.get_proxy_exit_ip(proxy, timeout=15)
    
    if exit_ip:
        logger.info(f"✓ 代理可用")
        logger.info(f"✓ 出口IP: {exit_ip}")
        logger.info(f"✓ 地区: {proxy.region or '未知'}")
        return True
    else:
        logger.error("✗ 代理不可用")
        return False


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='推特账号与代理绑定验证测试')
    parser.add_argument(
        '--mode',
        choices=['full', 'proxy_only'],
        default='full',
        help='测试模式：full=完整测试（包含推特登录），proxy_only=仅测试代理'
    )
    
    args = parser.parse_args()
    
    if args.mode == 'proxy_only':
        asyncio.run(test_proxy_only())
    else:
        asyncio.run(test_single_binding())


if __name__ == '__main__':
    main()

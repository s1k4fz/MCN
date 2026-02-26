"""
Proxy Health Checker v2.0 - Enhanced with ipinfo.io
Two-stage cascading detection: ipinfo.io (connectivity + geo) + Twitter (business accessibility)

Author: Manus AI
Date: 2026-02-16
Version: 2.0
"""

import httpx
import time
from typing import Dict, List, Optional
from datetime import datetime
import json


class ProxyHealthCheckerV2:
    """
    Enhanced proxy health checker with two-stage cascading detection.
    Stage 1: ipinfo.io for connectivity and geo information
    Stage 2: Twitter accessibility for business scenario validation
    """

    # Configuration
    MAX_LATENCY_MS = 5000
    TIMEOUT_SECONDS = 20
    IPINFO_URL = "https://ipinfo.io/json"
    TWITTER_LOGIN_URL = "https://x.com/login"

    def __init__(self, db_connection=None):
        """
        Initialize the enhanced health checker.
        
        Args:
            db_connection: Optional database connection for updating results
        """
        self.db = db_connection

    # ============================================================
    # Core Health Check Function
    # ============================================================

    def check_proxy(self, proxy_url: str, proxy_id: Optional[int] = None) -> Dict:
        """
        Perform comprehensive two-stage health check on a single proxy.
        
        Args:
            proxy_url: The proxy URL (e.g., "http://user:pass@host:port")
            proxy_id: Optional proxy ID for database updates
        
        Returns:
            Dictionary with detailed health check results
        """
        report = {
            "proxy_id": proxy_id,
            "proxy_url": proxy_url,
            "status": "unhealthy",
            "latency_ms": None,
            "ip_address": None,
            "country": None,
            "city": None,
            "isp": None,
            "reason": "",
            "checked_at": datetime.now().isoformat(),
            "stage_results": {}
        }

        try:
            with httpx.Client(
                proxy=proxy_url,
                timeout=self.TIMEOUT_SECONDS,
                follow_redirects=True,
                headers={
                    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                }
            ) as client:
                
                # ========== Stage 1: ipinfo.io Check ==========
                stage1_result = self._stage1_ipinfo_check(client)
                report["stage_results"]["stage1_ipinfo"] = stage1_result
                
                if not stage1_result["success"]:
                    report["status"] = "unhealthy"
                    report["reason"] = f"Stage 1 Failed: {stage1_result['reason']}"
                    return report
                
                # Extract ipinfo data
                report["latency_ms"] = stage1_result["latency_ms"]
                report["ip_address"] = stage1_result.get("ip")
                report["country"] = stage1_result.get("country")
                report["city"] = stage1_result.get("city")
                report["isp"] = stage1_result.get("org")
                
                # ========== Stage 2: Twitter Accessibility Check ==========
                stage2_result = self._stage2_twitter_check(client)
                report["stage_results"]["stage2_twitter"] = stage2_result
                
                if not stage2_result["success"]:
                    report["status"] = "banned"  # Proxy works but banned by Twitter
                    report["reason"] = f"Stage 2 Failed: {stage2_result['reason']}"
                    return report
                
                # All checks passed
                report["status"] = "healthy"
                report["reason"] = "All checks passed"

        except httpx.TimeoutException:
            report["reason"] = "Connection timeout"
        except httpx.ProxyError as e:
            report["reason"] = f"Proxy error: {str(e)[:100]}"
        except Exception as e:
            report["reason"] = f"Unknown error: {str(e)[:100]}"

        return report

    # ============================================================
    # Stage 1: ipinfo.io Check
    # ============================================================

    def _stage1_ipinfo_check(self, client: httpx.Client) -> Dict:
        """
        Stage 1: Check connectivity and retrieve geo information via ipinfo.io
        
        Returns:
            {
                "success": bool,
                "latency_ms": int,
                "ip": str,
                "country": str,
                "city": str,
                "org": str (ISP),
                "reason": str (if failed)
            }
        """
        try:
            start_time = time.time()
            response = client.get(self.IPINFO_URL)
            latency_ms = int((time.time() - start_time) * 1000)
            
            if response.status_code != 200:
                return {
                    "success": False,
                    "reason": f"ipinfo.io returned HTTP {response.status_code}"
                }
            
            if latency_ms > self.MAX_LATENCY_MS:
                return {
                    "success": False,
                    "latency_ms": latency_ms,
                    "reason": f"Latency too high: {latency_ms}ms (max: {self.MAX_LATENCY_MS}ms)"
                }
            
            # Parse ipinfo response
            try:
                data = response.json()
            except Exception:
                return {
                    "success": False,
                    "reason": "Failed to parse ipinfo.io JSON response"
                }
            
            # Validate essential fields
            if not data.get("ip"):
                return {
                    "success": False,
                    "reason": "ipinfo.io did not return IP address"
                }
            
            return {
                "success": True,
                "latency_ms": latency_ms,
                "ip": data.get("ip"),
                "country": data.get("country"),
                "city": data.get("city"),
                "region": data.get("region"),
                "org": data.get("org"),  # ISP information
                "loc": data.get("loc"),  # Latitude, Longitude
                "timezone": data.get("timezone")
            }
        
        except httpx.TimeoutException:
            return {
                "success": False,
                "reason": "ipinfo.io request timeout"
            }
        except Exception as e:
            return {
                "success": False,
                "reason": f"ipinfo.io check failed: {str(e)[:100]}"
            }

    # ============================================================
    # Stage 2: Twitter Accessibility Check
    # ============================================================

    def _stage2_twitter_check(self, client: httpx.Client) -> Dict:
        """
        Stage 2: Check if proxy can access Twitter without being blocked
        
        Returns:
            {
                "success": bool,
                "reason": str (if failed)
            }
        """
        try:
            response = client.get(self.TWITTER_LOGIN_URL)
            
            if response.status_code != 200:
                return {
                    "success": False,
                    "reason": f"Twitter returned HTTP {response.status_code}"
                }
            
            content = response.text.lower()
            
            # Check for blocking indicators
            blocking_patterns = [
                ("cloudflare challenge", "checking your browser"),
                ("cloudflare challenge", "just a moment"),
                ("twitter verification", "verify your identity"),
                ("arkose challenge", "arkose"),
                ("rate limit", "rate limit exceeded")
            ]
            
            for pattern_name, pattern_text in blocking_patterns:
                if pattern_text in content:
                    return {
                        "success": False,
                        "reason": f"Detected {pattern_name}"
                    }
            
            # Check if we're on a valid Twitter page
            valid_indicators = [
                "/i/flow/login" in str(response.url),
                "twitter" in content,
                "login" in content
            ]
            
            if not any(valid_indicators):
                return {
                    "success": False,
                    "reason": "Unexpected page content (not Twitter login)"
                }
            
            return {"success": True}
        
        except httpx.TimeoutException:
            return {
                "success": False,
                "reason": "Twitter request timeout"
            }
        except Exception as e:
            return {
                "success": False,
                "reason": f"Twitter check failed: {str(e)[:100]}"
            }

    # ============================================================
    # Batch Processing
    # ============================================================

    def check_all_proxies(self, status_filter: List[str] = None) -> List[Dict]:
        """
        Check all proxies in the database with specified statuses.
        
        Args:
            status_filter: List of statuses to check (e.g., ['available', 'in_use'])
        
        Returns:
            List of health check reports
        """
        if not self.db:
            raise ValueError("Database connection required for batch checking")
        
        cursor = self.db.cursor(dictionary=True)
        
        try:
            if status_filter:
                placeholders = ','.join(['%s'] * len(status_filter))
                query = f"SELECT id, proxy_url FROM proxies WHERE status IN ({placeholders})"
                cursor.execute(query, status_filter)
            else:
                cursor.execute("SELECT id, proxy_url FROM proxies")
            
            proxies = cursor.fetchall()
            print(f"📊 Found {len(proxies)} proxies to check")
            
            results = []
            for i, proxy in enumerate(proxies, 1):
                proxy_id = proxy['id']
                proxy_url = proxy['proxy_url']
                
                print(f"[{i}/{len(proxies)}] Checking proxy {proxy_id}...", end=" ")
                
                report = self.check_proxy(proxy_url, proxy_id)
                results.append(report)
                
                # Update database
                self._update_proxy_in_db(report)
                
                # Print result
                status_emoji = {
                    "healthy": "✅",
                    "banned": "🚫",
                    "unhealthy": "❌"
                }.get(report["status"], "❓")
                
                geo_info = f"{report.get('country', 'N/A')}/{report.get('city', 'N/A')}"
                print(f"{status_emoji} {report['status']} | {report.get('latency_ms', 'N/A')}ms | {geo_info} | {report['reason'][:40]}")
                
                time.sleep(0.5)
            
            return results
        
        finally:
            cursor.close()

    def _update_proxy_in_db(self, report: Dict):
        """Update proxy status and geo information in database"""
        if not self.db or not report.get("proxy_id"):
            return
        
        cursor = self.db.cursor()
        
        try:
            cursor.execute("""
                UPDATE proxies 
                SET 
                    status = %s,
                    last_health_check = NOW(),
                    latency_ms = %s,
                    ip_address = %s,
                    country = %s,
                    city = %s,
                    isp = %s
                WHERE id = %s
            """, (
                report["status"],
                report.get("latency_ms"),
                report.get("ip_address"),
                report.get("country"),
                report.get("city"),
                report.get("isp"),
                report["proxy_id"]
            ))
            
            self.db.commit()
        
        except Exception as e:
            print(f"⚠️  Failed to update proxy {report['proxy_id']}: {e}")
            self.db.rollback()
        
        finally:
            cursor.close()


# ============================================================
# Standalone Testing
# ============================================================

def test_single_proxy(proxy_url: str):
    """Test a single proxy without database (for manual testing)"""
    checker = ProxyHealthCheckerV2()
    
    print("=" * 70)
    print("Proxy Health Check v2.0 - Two-Stage Cascading Detection")
    print("=" * 70)
    print(f"Testing proxy: {proxy_url[:50]}...")
    print()
    
    report = checker.check_proxy(proxy_url)
    
    print("=" * 70)
    print("FINAL REPORT")
    print("=" * 70)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print("=" * 70)
    
    return report


# ============================================================
# Example Usage
# ============================================================

if __name__ == "__main__":
    print("=" * 70)
    print("Proxy Health Checker v2.0")
    print("=" * 70)
    print()
    print("This script uses a two-stage cascading detection model:")
    print("  Stage 1: ipinfo.io (connectivity + geo information)")
    print("  Stage 2: Twitter (business accessibility)")
    print()
    print("=" * 70)
    
    # Example: Test a single proxy
    # test_proxy = "http://user:pass@proxy.example.com:8080"
    # test_single_proxy(test_proxy)
    
    # Example: Batch check with database
    # import mysql.connector
    # db = mysql.connector.connect(...)
    # checker = ProxyHealthCheckerV2(db)
    # results = checker.check_all_proxies(['available', 'in_use'])

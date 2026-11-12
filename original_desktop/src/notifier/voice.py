"""
语音电话通知模块
支持阿里云语音服务 (Voice Messaging Service)
"""
import hmac
import base64
import hashlib
import urllib.parse
import time
import uuid
import requests
import json
import logging
import socket
from datetime import datetime


def _pre_resolve_dns(hostname: str, timeout: float = 5.0) -> bool:
    """预先解析DNS，确保域名可解析"""
    try:
        socket.setdefaulttimeout(timeout)
        socket.gethostbyname(hostname)
        return True
    except socket.gaierror:
        return False
    except Exception:
        return False


class AliyunVoiceNotifier:
    """阿里云语音通知"""
    
    API_ENDPOINT = "https://dyvmsapi.aliyuncs.com/"
    
    def __init__(self, access_key_id: str, access_key_secret: str, 
                 tts_code: str, called_show_number: str = ""):
        """
        初始化阿里云语音通知
        
        Args:
            access_key_id: AccessKey ID
            access_key_secret: AccessKey Secret
            tts_code: TTS模板ID (需要在控制台创建)
            called_show_number: 被叫显号 (可选，公共模式不需要填写)
        """
        self.access_key_id = access_key_id
        self.access_key_secret = access_key_secret
        self.called_show_number = called_show_number
        self.tts_code = tts_code
    
    def _sign(self, params: dict) -> str:
        """生成签名"""
        sorted_params = sorted(params.items())
        query_string = urllib.parse.urlencode(sorted_params, quote_via=urllib.parse.quote)
        string_to_sign = f"GET&%2F&{urllib.parse.quote(query_string, safe='')}"
        key = f"{self.access_key_secret}&"
        signature = base64.b64encode(
            hmac.new(key.encode(), string_to_sign.encode(), hashlib.sha1).digest()
        ).decode()
        return signature
    
    def call(self, phone: str, tts_param: dict = None) -> bool:
        """
        发起语音呼叫
        
        Args:
            phone: 被叫号码
            tts_param: TTS参数 (与模板变量对应)
        
        Returns:
            是否呼叫成功
        """
        max_retries = 5  # 增加到5次重试
        retry_delay = 5  # 增加间隔到5秒
        hostname = "dyvmsapi.aliyuncs.com"
        
        for attempt in range(max_retries):
            try:
                # 先尝试DNS解析，确保网络正常
                if not _pre_resolve_dns(hostname):
                    if attempt < max_retries - 1:
                        logging.warning(f"[阿里云语音] DNS解析失败，{retry_delay}秒后重试 ({attempt + 1}/{max_retries})")
                        time.sleep(retry_delay)
                        continue
                    else:
                        logging.error(f"[阿里云语音] DNS解析失败，已重试{max_retries}次")
                        return False
                
                # 公共参数 - 每次重试需要重新生成SignatureNonce和Timestamp
                params = {
                    "AccessKeyId": self.access_key_id,
                    "Action": "SingleCallByTts",
                    "Format": "JSON",
                    "RegionId": "cn-hangzhou",
                    "SignatureMethod": "HMAC-SHA1",
                    "SignatureNonce": str(uuid.uuid4()),
                    "SignatureVersion": "1.0",
                    "Timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "Version": "2017-05-25",
                    # 请求参数
                    "CalledNumber": phone,
                    "TtsCode": self.tts_code,
                }
                
                # 被叫显号（可选，公共模式不需要）
                if self.called_show_number:
                    params["CalledShowNumber"] = self.called_show_number
                
                if tts_param:
                    params["TtsParam"] = json.dumps(tts_param, ensure_ascii=False)
                
                # 签名
                params["Signature"] = self._sign(params)
                
                # 发送请求，增加超时时间
                response = requests.get(self.API_ENDPOINT, params=params, timeout=30)
                result = response.json()
                
                if result.get("Code") == "OK":
                    logging.info(f"[阿里云语音] 呼叫成功: {phone}")
                    return True
                else:
                    logging.error(f"[阿里云语音] 呼叫失败: {result.get('Message')}")
                    return False
                    
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                # 网络连接错误或超时，可以重试
                if attempt < max_retries - 1:
                    logging.warning(f"[阿里云语音] 网络异常，{retry_delay}秒后重试 ({attempt + 1}/{max_retries})")
                    time.sleep(retry_delay)
                else:
                    logging.error(f"[阿里云语音] 网络异常，已重试{max_retries}次仍失败: {e}")
                    return False
            except Exception as e:
                logging.error(f"[阿里云语音] 呼叫异常: {e}")
                return False
        
        return False


class VoiceNotifier:
    """语音通知统一接口"""
    
    def __init__(self, config: dict):
        """
        初始化语音通知器
        
        Args:
            config: {
                'provider': 'aliyun',
                'access_key_id': str,
                'access_key_secret': str,
                'tts_code': str,
                'called_show_number': str (可选，公共模式不需要)
            }
        """
        self.config = config
        self.provider = config.get('provider', 'aliyun')
        
        if self.provider == 'aliyun':
            self.client = AliyunVoiceNotifier(
                access_key_id=config.get('access_key_id', ''),
                access_key_secret=config.get('access_key_secret', ''),
                tts_code=config.get('tts_code', ''),
                called_show_number=config.get('called_show_number', '')
            )
        else:
            raise ValueError(f"Unsupported voice provider: {self.provider}")
    
    def call(self, phone: str, count: int = 0, source: str = "") -> bool:
        """
        发起语音呼叫通知
        
        Args:
            phone: 被叫号码
            count: 新招标数量
            source: 来源网站
        
        Returns:
            是否呼叫成功
        """
        tts_param = {
            "count": str(count),
            "source": source[:10] if source else "招标网站"  # 限制长度
        }
        return self.client.call(phone, tts_param)
    
    def send_test(self, phone: str) -> bool:
        """
        发送测试呼叫
        
        Args:
            phone: 测试号码
        
        Returns:
            是否成功
        """
        return self.call(phone, count=99, source="测试")

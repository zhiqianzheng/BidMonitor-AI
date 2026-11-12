"""
微信通知模块
支持：
1. PushPlus (个人微信)
2. 企业微信 Webhook (企业微信群)
"""
import requests
import json
import logging


class PushPlusNotifier:
    """PushPlus 微信推送 (https://www.pushplus.plus/)"""
    
    API_URL = "https://www.pushplus.plus/send"
    
    def __init__(self, token: str):
        """
        初始化 PushPlus
        
        Args:
            token: PushPlus 的 token (在官网获取)
        """
        self.token = token
    
    def send(self, title: str, content: str, template: str = "html") -> bool:
        """
        发送消息
        
        Args:
            title: 消息标题
            content: 消息内容 (支持 HTML)
            template: 模板类型 (html, txt, json, markdown)
        
        Returns:
            是否发送成功
        """
        try:
            data = {
                "token": self.token,
                "title": title,
                "content": content,
                "template": template
            }
            response = requests.post(self.API_URL, json=data, timeout=10)
            result = response.json()
            
            code = result.get("code")
            msg = result.get("msg", "未知错误")
            
            if code == 200:
                logging.info(f"[PushPlus] 发送成功: {title}")
                return True
            elif code == 999:
                # 999 通常表示：1)发送频率限制 2)token过期 3)账户异常
                logging.error(f"[PushPlus] 发送失败 (code=999): {msg}")
                logging.error(f"[PushPlus] 可能原因: token过期/频率限制/需要重新获取token")
                return False
            else:
                logging.error(f"[PushPlus] 发送失败 (code={code}): {msg}")
                return False
        except Exception as e:
            logging.error(f"[PushPlus] 发送异常: {e}")
            return False


class EnterpriseWeChatNotifier:
    """企业微信 Webhook 机器人"""
    
    def __init__(self, webhook_url: str):
        """
        初始化企业微信机器人
        
        Args:
            webhook_url: Webhook 地址 (在企业微信群中添加机器人获取)
        """
        self.webhook_url = webhook_url
    
    def send(self, content: str, mentioned_list: list = None) -> bool:
        """
        发送文本消息
        
        Args:
            content: 消息内容
            mentioned_list: @的人员列表 (手机号或 userid)
        
        Returns:
            是否发送成功
        """
        try:
            data = {
                "msgtype": "text",
                "text": {
                    "content": content
                }
            }
            if mentioned_list:
                data["text"]["mentioned_mobile_list"] = mentioned_list
            
            response = requests.post(self.webhook_url, json=data, timeout=10)
            result = response.json()
            
            if result.get("errcode") == 0:
                logging.info("[企业微信] 发送成功")
                return True
            else:
                logging.error(f"[企业微信] 发送失败: {result.get('errmsg')}")
                return False
        except Exception as e:
            logging.error(f"[企业微信] 发送异常: {e}")
            return False
    
    def send_markdown(self, content: str) -> bool:
        """
        发送 Markdown 消息
        
        Args:
            content: Markdown 格式内容
        
        Returns:
            是否发送成功
        """
        try:
            data = {
                "msgtype": "markdown",
                "markdown": {
                    "content": content
                }
            }
            response = requests.post(self.webhook_url, json=data, timeout=10)
            result = response.json()
            
            if result.get("errcode") == 0:
                logging.info("[企业微信] Markdown 发送成功")
                return True
            else:
                logging.error(f"[企业微信] Markdown 发送失败: {result.get('errmsg')}")
                return False
        except Exception as e:
            logging.error(f"[企业微信] Markdown 发送异常: {e}")
            return False


class WeChatNotifier:
    """微信通知统一接口"""
    
    def __init__(self, config: dict):
        """
        初始化微信通知器
        
        Args:
            config: {
                'provider': 'pushplus' | 'enterprise',
                'token': str (PushPlus token),
                'webhook_url': str (企业微信 Webhook)
            }
        """
        self.config = config
        self.provider = config.get('provider', 'pushplus')
        
        if self.provider == 'pushplus':
            self.client = PushPlusNotifier(config.get('token', ''))
        else:
            self.client = EnterpriseWeChatNotifier(config.get('webhook_url', ''))
    
    def send(self, bids: list, summary: dict = None) -> bool:
        """
        发送招标信息通知
        
        Args:
            bids: 招标信息列表
            summary: 摘要信息 {'count': int, 'source': str}
        
        Returns:
            是否发送成功
        """
        if not bids:
            return False
        
        # 自动生成摘要
        if summary is None:
            sources = list(set([b.source for b in bids]))
            source_str = "、".join(sources)
            if len(source_str) > 20:
                source_str = source_str[:18] + "..."
            summary = {
                'count': len(bids),
                'source': source_str
            }
        
        # 构建消息
        title = f"🔔 招标监控 - {summary['count']}条新信息"
        
        if self.provider == 'pushplus':
            # HTML 格式
            content = f"""
            <h3>招投标监控提醒</h3>
            <p>发现 <b>{summary['count']}</b> 条新信息</p>
            <p>来源: {summary['source']}</p>
            <hr>
            <ul>
            """
            for bid in bids[:10]:  # 最多显示10条
                content += f"<li><a href='{bid.url}'>{bid.title}</a> - {bid.source}</li>"
            if len(bids) > 10:
                content += f"<li>... 还有 {len(bids) - 10} 条，详情请查看邮件</li>"
            content += "</ul>"
            
            return self.client.send(title, content, "html")
        else:
            # Markdown 格式
            content = f"""## 🔔 招标监控提醒
> 发现 **{summary['count']}** 条新信息
> 来源: {summary['source']}

"""
            for bid in bids[:5]:
                content += f"- [{bid.title}]({bid.url})\n"
            if len(bids) > 5:
                content += f"\n... 还有 {len(bids) - 5} 条，详情请查看邮件"
            
            return self.client.send_markdown(content)
    
    def send_test(self) -> bool:
        """发送测试消息"""
        if self.provider == 'pushplus':
            return self.client.send(
                "✅ 测试成功",
                "<h3>微信通知测试</h3><p>如果您收到这条消息，说明配置正确！</p>",
                "html"
            )
        else:
            return self.client.send("✅ 企业微信通知测试成功！如果您看到这条消息，说明配置正确。")

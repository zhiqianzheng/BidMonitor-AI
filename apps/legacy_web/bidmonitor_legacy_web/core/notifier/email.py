"""
邮件通知模块 - 修复版
"""
import smtplib
import ssl
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from typing import List, Dict, Any
from datetime import datetime

import sys
import os
from apps.legacy_web.bidmonitor_legacy_web.core.database.storage import BidInfo


class EmailNotifier:
    """邮件通知器"""
    
    def __init__(self, config: Dict[str, Any]):
        self.smtp_server = config['smtp_server']
        self.smtp_port = config['smtp_port']
        self.sender = config['sender']
        self.password = config['password']
        self.receiver = config['receiver']
        self.use_ssl = config.get('use_ssl', True)
        self.logger = logging.getLogger("notifier.email")
    
    def _create_html_content(self, bids: List[BidInfo]) -> str:
        """创建HTML格式的邮件内容"""
        # 使用简单的HTML，避免特殊字符问题
        html_parts = [
            '<!DOCTYPE html>',
            '<html><head><meta charset="UTF-8"></head>',
            '<body style="font-family:Arial,sans-serif;margin:20px;">',
            '<h2>Bid Monitor Notification</h2>',
            f'<p><b>Found {len(bids)} new bid(s)</b></p>',
            f'<p>Time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>',
            '<hr>',
        ]
        
        for bid in bids:
            html_parts.append(f'''
            <div style="border:1px solid #ddd;padding:10px;margin:10px 0;">
                <p><b><a href="{bid.url}">{bid.title}</a></b></p>
                <p>Source: {bid.source} | Date: {bid.publish_date or "N/A"}</p>
            </div>
            ''')
        
        html_parts.append('</body></html>')
        return ''.join(html_parts)
    
    def send(self, bids: List[BidInfo], subject: str = None) -> bool:
        """发送邮件通知"""
        if not bids:
            self.logger.info("No bids to send")
            return True
        
        if subject is None:
            subject = f"Bid Monitor: {len(bids)} new bid(s) found"
        
        server = None
        try:
            # 创建邮件
            msg = MIMEMultipart('alternative')
            msg['Subject'] = Header(subject, 'utf-8')
            msg['From'] = self.sender
            msg['To'] = self.receiver
            
            # 纯文本版本
            text_lines = [f"Found {len(bids)} new bid(s):\n"]
            for bid in bids:
                text_lines.append(f"- {bid.title}\n  URL: {bid.url}\n  Source: {bid.source}\n")
            text_content = '\n'.join(text_lines)
            
            # HTML版本
            html_content = self._create_html_content(bids)
            
            msg.attach(MIMEText(text_content, 'plain', 'utf-8'))
            msg.attach(MIMEText(html_content, 'html', 'utf-8'))
            
            # 连接并发送
            if self.use_ssl:
                context = ssl.create_default_context()
                server = smtplib.SMTP_SSL(self.smtp_server, self.smtp_port, context=context, timeout=30)
            else:
                server = smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=30)
                server.starttls()
            
            server.login(self.sender, self.password)
            server.sendmail(self.sender, self.receiver, msg.as_string())
            
            self.logger.info(f"Email sent: {len(bids)} bids -> {self.receiver}")
            return True
            
        except smtplib.SMTPAuthenticationError as e:
            self.logger.error(f"Auth failed: {e}")
            return False
        except smtplib.SMTPException as e:
            self.logger.error(f"SMTP error: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Email failed: {e}")
            return False
        finally:
            if server:
                try:
                    server.quit()
                except:
                    pass
    
    def send_test(self) -> bool:
        """发送测试邮件"""
        test_bids = [
            BidInfo(
                title="Test Bid - Drone Procurement Project",
                url="https://example.com/bid/12345",
                publish_date=datetime.now().strftime('%Y-%m-%d'),
                source="Test Source",
                purchaser="Test Organization"
            )
        ]
        return self.send(test_bids, subject="Test Email - Bid Monitor System")

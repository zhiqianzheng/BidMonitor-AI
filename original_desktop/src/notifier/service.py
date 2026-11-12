"""Shared notification delivery and retry handling for desktop and server."""
import hashlib
from .email import EmailNotifier
from .sms import SMSNotifier
from .wechat import WeChatNotifier
from .voice import VoiceNotifier


SMTP_PROVIDERS = {
    "QQ邮箱": ("smtp.qq.com", 465, True),
    "163邮箱": ("smtp.163.com", 465, True),
    "126邮箱": ("smtp.126.com", 465, True),
    "Gmail": ("smtp.gmail.com", 587, False),
    "Outlook": ("smtp.office365.com", 587, False),
    "企业邮箱": ("smtp.exmail.qq.com", 465, True),
    "阿里邮箱": ("smtp.aliyun.com", 465, True),
}


class NotificationService:
    def __init__(self, storage, log_callback=None):
        self.storage = storage
        self.log = log_callback or (lambda message: None)

    def _targets(self, config):
        seen = set()
        for contact in config.get("contacts", []):
            if not contact.get("enabled", True):
                continue
            email = contact.get("email") or {}
            if isinstance(email, str):
                server, port, ssl = SMTP_PROVIDERS.get(
                    contact.get("email_type"), SMTP_PROVIDERS["QQ邮箱"])
                email = dict(address=email, password=contact.get("email_password", ""),
                             smtp_server=server, smtp_port=port, use_ssl=ssl)
            destinations = {
                "email": email.get("address"),
                "sms": contact.get("phone"),
                "voice": contact.get("phone"),
                "wechat": contact.get("wechat_token"),
            }
            for channel, address in destinations.items():
                if not config.get(channel + "_enabled") or not address:
                    continue
                # Tokens and addresses are never stored in the delivery ledger.
                recipient = hashlib.sha256(address.strip().encode()).hexdigest()
                key = (channel, recipient)
                if key not in seen:
                    seen.add(key)
                    yield channel, recipient, address, email, contact.get("name", "联系人")

    def _send(self, channel, address, email, config, bids):
        if channel == "email":
            return EmailNotifier({
                "smtp_server": email.get("smtp_server", "smtp.qq.com"),
                "smtp_port": email.get("smtp_port", 465),
                "use_ssl": email.get("use_ssl", True),
                "sender": address, "receiver": address,
                "password": email.get("password", ""),
            }).send(bids)
        if channel == "wechat":
            return WeChatNotifier({"provider": "pushplus", "token": address}).send(bids)
        summary = {"count": len(bids), "source": "招标网站"}
        if channel == "sms":
            return SMSNotifier(config.get("sms_config", {})).send(address, bids, summary)
        return VoiceNotifier(config.get("voice_config", {})).call(address, **summary)

    def send_pending(self, config, stop_event=None):
        bids = self.storage.get_unnotified()
        targets = list(self._targets(config))
        if not bids or not targets:
            return
        complete = {bid.unique_id for bid in bids}
        for channel, recipient, address, email, name in targets:
            if stop_event and stop_event.is_set():
                return
            sent = self.storage.delivered_ids(channel, recipient)
            pending = [b for b in bids if b.unique_id not in sent]
            batch_size = 10 if channel in ("email", "wechat") else max(1, len(pending))
            for start in range(0, len(pending), batch_size):
                if stop_event and stop_event.is_set():
                    return
                batch = pending[start:start + batch_size]
                try:
                    success = bool(self._send(channel, address, email, config, batch))
                except Exception:
                    success = False
                self.storage.record_delivery(batch, channel, recipient, success)
                if success:
                    self.log(f"✅ {channel} 通知成功: {name}，{len(batch)} 条")
                else:
                    self.log(f"❌ {channel} 通知失败: {name}，保留待重试")
                    # Back off until the next round instead of hammering a failing channel.
                    complete.difference_update(b.unique_id for b in pending[start:])
                    break
        self.storage.mark_notified([b.url for b in bids if b.unique_id in complete])

"""
GUI界面模块 V3 - 支持多邮箱配置
"""
import os
import sys
import json
import threading
import copy
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, simpledialog, colorchooser, filedialog
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
try:
    from PIL import Image, ImageTk, ImageEnhance
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# 添加src目录到路径
if getattr(sys, 'frozen', False):
    # 如果是打包后的exe，将工作目录切换到exe所在目录
    os.chdir(os.path.dirname(sys.executable))
    sys.path.insert(0, os.path.join(os.path.dirname(sys.executable), 'src'))
else:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    # 尝试相对导入 (当作为包运行时)
    from .monitor_core import MonitorCore, get_all_crawlers
    from .database.storage import BidInfo
    from .notifier.wechat import WeChatNotifier
    from .notifier.voice import VoiceNotifier
    from .utils.system import AutoStart, SystemTray, TRAY_AVAILABLE
except ImportError:
    try:
        # 尝试直接导入 (当直接运行或路径在sys.path中时)
        from monitor_core import MonitorCore, get_all_crawlers
        from database.storage import BidInfo
        from notifier.wechat import WeChatNotifier
        from notifier.voice import VoiceNotifier
        from utils.system import AutoStart, SystemTray, TRAY_AVAILABLE
    except ImportError:
        # 开发环境Fallback
        import sys
        sys.path.append(os.path.dirname(os.path.abspath(__file__)))
        from monitor_core import MonitorCore, get_all_crawlers
        from database.storage import BidInfo
        from notifier.wechat import WeChatNotifier
        from notifier.voice import VoiceNotifier
        from utils.system import AutoStart, SystemTray, TRAY_AVAILABLE

# 邮箱服务商配置
EMAIL_PROVIDERS = {
    "QQ邮箱": {"smtp_server": "smtp.qq.com", "smtp_port": 465},
    "163邮箱": {"smtp_server": "smtp.163.com", "smtp_port": 465},
    "126邮箱": {"smtp_server": "smtp.126.com", "smtp_port": 465},
    "阿里邮箱": {"smtp_server": "smtp.aliyun.com", "smtp_port": 465},
    "Gmail": {"smtp_server": "smtp.gmail.com", "smtp_port": 587},
    "Outlook": {"smtp_server": "smtp.office365.com", "smtp_port": 587},
}


class ToolTip:
    """悬停提示工具类"""
    
    def __init__(self, widget, text, delay=500):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.tip_window = None
        self.id = None
        self.x = self.y = 0
        
        self.widget.bind("<Enter>", self.enter)
        self.widget.bind("<Leave>", self.leave)
        self.widget.bind("<ButtonPress>", self.leave)
        
    def enter(self, event=None):
        self.schedule()
        
    def leave(self, event=None):
        self.unschedule()
        self.hidetip()
        
    def schedule(self):
        self.unschedule()
        self.id = self.widget.after(self.delay, self.showtip)
        
    def unschedule(self):
        id = self.id
        self.id = None
        if id:
            self.widget.after_cancel(id)
            
    def showtip(self, event=None):
        x = y = 0
        x, y, cx, cy = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 25
        
        # 创建浮窗
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True) # 去掉标题栏
        tw.wm_geometry(f"+{x}+{y}")
        
        label = tk.Label(tw, text=self.text, justify=tk.LEFT,
                       background="#ffffe0", relief=tk.SOLID, borderwidth=1,
                       font=("Microsoft YaHei", 9))
        label.pack(ipadx=1)
        
    def hidetip(self):
        tw = self.tip_window
        self.tip_window = None
        if tw:
            tw.destroy()


class EmailDialog:
    """添加/编辑单个邮箱对话框"""
    
    def __init__(self, parent, email_data=None):
        self.result = None
        
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("添加邮箱")
        self.dialog.geometry("450x280")
        self.dialog.resizable(False, False)
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        # 居中显示
        self.dialog.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - 450) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 280) // 2
        self.dialog.geometry(f"+{x}+{y}")
        
        self._create_widgets(email_data)
    
    def _create_widgets(self, email_data):
        frame = ttk.Frame(self.dialog, padding="15")
        frame.pack(fill=tk.BOTH, expand=True)
        
        # 邮箱类型
        ttk.Label(frame, text="邮箱类型:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.provider_var = tk.StringVar(value="QQ邮箱")
        provider_combo = ttk.Combobox(frame, textvariable=self.provider_var, 
                                      values=list(EMAIL_PROVIDERS.keys()), state="readonly", width=35)
        provider_combo.grid(row=0, column=1, sticky=tk.EW, pady=5)
        
        # 发件邮箱
        ttk.Label(frame, text="发件邮箱:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.sender_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.sender_var, width=38).grid(row=1, column=1, sticky=tk.EW, pady=5)
        
        # 授权码
        ttk.Label(frame, text="SMTP授权码:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.password_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.password_var, width=38, show="*").grid(row=2, column=1, sticky=tk.EW, pady=5)
        
        # 收件邮箱
        ttk.Label(frame, text="收件邮箱:").grid(row=3, column=0, sticky=tk.W, pady=5)
        self.receiver_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.receiver_var, width=38).grid(row=3, column=1, sticky=tk.EW, pady=5)
        
        ttk.Label(frame, text="提示: 可以和发件邮箱相同", foreground="gray").grid(row=4, column=1, sticky=tk.W)
        
        # 按钮
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=5, column=0, columnspan=2, pady=20)
        
        ttk.Button(btn_frame, text="确定", command=self._on_ok, width=12).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="取消", command=self._on_cancel, width=12).pack(side=tk.LEFT, padx=10)
        
        # 填充已有数据
        if email_data:
            self.provider_var.set(email_data.get('provider', 'QQ邮箱'))
            self.sender_var.set(email_data.get('sender', ''))
            self.password_var.set(email_data.get('password', ''))
            self.receiver_var.set(email_data.get('receiver', ''))
    
    def _on_ok(self):
        if not self.sender_var.get().strip():
            messagebox.showerror("错误", "请输入发件邮箱")
            return
        if not self.password_var.get().strip():
            messagebox.showerror("错误", "请输入SMTP授权码")
            return
        if not self.receiver_var.get().strip():
            messagebox.showerror("错误", "请输入收件邮箱")
            return
        
        provider = self.provider_var.get()
        provider_config = EMAIL_PROVIDERS.get(provider, EMAIL_PROVIDERS["QQ邮箱"])
        
        self.result = {
            'provider': provider,
            'nickname': provider,  # 使用邮箱类型作为昵称
            'smtp_server': provider_config['smtp_server'],
            'smtp_port': provider_config['smtp_port'],
            'sender': self.sender_var.get().strip(),
            'password': self.password_var.get(),
            'receiver': self.receiver_var.get().strip(),
            'use_ssl': True if provider_config['smtp_port'] == 465 else False,
        }
        self.dialog.destroy()
    
    def _on_cancel(self):
        self.dialog.destroy()
    
    def show(self):
        self.dialog.wait_window()
        return self.result


class CustomSiteDialog:
    """添加/编辑自定义网站对话框"""
    
    def __init__(self, parent, site_data=None):
        self.result = None
        
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("自定义网站")
        self.dialog.geometry("400x200")
        self.dialog.resizable(False, False)
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        # 居中
        self.dialog.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - 400) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 200) // 2
        self.dialog.geometry(f"+{x}+{y}")
        
        self._create_widgets(site_data)
        
    def _create_widgets(self, site_data):
        frame = ttk.Frame(self.dialog, padding="20")
        frame.pack(fill=tk.BOTH, expand=True)
        
        # 网站名称
        ttk.Label(frame, text="网站名称:").grid(row=0, column=0, sticky=tk.W, pady=10)
        self.name_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.name_var, width=30).grid(row=0, column=1, sticky=tk.EW, pady=10)
        
        # 网址
        ttk.Label(frame, text="列表页URL:").grid(row=1, column=0, sticky=tk.W, pady=10)
        self.url_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.url_var, width=30).grid(row=1, column=1, sticky=tk.EW, pady=10)
        
        # 按钮
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=2, column=0, columnspan=2, pady=20)
        ttk.Button(btn_frame, text="确定", command=self._on_ok).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="取消", command=self.dialog.destroy).pack(side=tk.LEFT, padx=10)
        
        if site_data:
            self.name_var.set(site_data.get('name', ''))
            self.url_var.set(site_data.get('url', ''))
            
    def _on_ok(self):
        name = self.name_var.get().strip()
        url = self.url_var.get().strip()
        
        if not name:
            messagebox.showerror("错误", "请输入网站名称")
            return
        if not url:
            messagebox.showerror("错误", "请输入网址")
            return
        if not url.startswith(('http://', 'https://')):
            messagebox.showerror("错误", "网址必须以 http:// 或 https:// 开头")
            return
            
        self.result = {'name': name, 'url': url}
        self.dialog.destroy()
        
    def show(self):
        self.dialog.wait_window()
        return self.result


class EmailConfigDialog(tk.Toplevel):
    """邮箱配置管理对话框 - 管理多个邮箱"""
    
    def __init__(self, parent, email_configs: List[Dict]):
        super().__init__(parent)
        self.title("📧 邮箱通知配置")
        self.geometry("550x500")
        self.resizable(False, True)
        self.transient(parent)
        self.grab_set()
        
        self.email_configs = [cfg.copy() for cfg in email_configs] if email_configs else []
        self.result = None
        
        x = parent.winfo_x() + (parent.winfo_width() - 550) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 500) // 2
        self.geometry(f"+{x}+{y}")
        
        self._create_widgets()
        self._update_listbox()
    
    def _create_widgets(self):
        main = ttk.Frame(self, padding=20)
        main.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(main, text="支持配置多个邮箱账户，发现新信息时会同时发送到所有邮箱", 
                  foreground="gray").pack(pady=5)
        
        # 邮箱列表
        list_frame = ttk.LabelFrame(main, text="已配置的邮箱", padding=10)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        self.email_listbox = tk.Listbox(list_frame, height=8, font=("Consolas", 10))
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.email_listbox.yview)
        self.email_listbox.config(yscrollcommand=scrollbar.set)
        self.email_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 操作按钮
        btn_row = ttk.Frame(main)
        btn_row.pack(fill=tk.X, pady=10)
        ttk.Button(btn_row, text="➕ 添加邮箱", command=self._add).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_row, text="✏️ 编辑", command=self._edit).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_row, text="❌ 删除", command=self._delete).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_row, text="📧 测试发送", command=self._test).pack(side=tk.LEFT, padx=5)
        
        # 底部按钮
        bottom_frame = ttk.Frame(main)
        bottom_frame.pack(pady=10)
        ttk.Button(bottom_frame, text="保存", command=self._save).pack(side=tk.LEFT, padx=10)
        ttk.Button(bottom_frame, text="取消", command=self.destroy).pack(side=tk.LEFT, padx=10)
    
    def _update_listbox(self):
        self.email_listbox.delete(0, tk.END)
        for cfg in self.email_configs:
            nickname = cfg.get('nickname', '未命名')
            receiver = cfg.get('receiver', cfg.get('username', ''))
            self.email_listbox.insert(tk.END, f"{nickname}: {receiver}")
    
    def _add(self):
        dialog = EmailDialog(self)
        result = dialog.show()
        if result:
            self.email_configs.append(result)
            self._update_listbox()
    
    def _edit(self):
        sel = self.email_listbox.curselection()
        if not sel:
            messagebox.showwarning("提示", "请先选择要编辑的邮箱")
            return
        idx = sel[0]
        dialog = EmailDialog(self, self.email_configs[idx])
        result = dialog.show()
        if result:
            self.email_configs[idx] = result
            self._update_listbox()
    
    def _delete(self):
        sel = self.email_listbox.curselection()
        if not sel:
            messagebox.showwarning("提示", "请先选择要删除的邮箱")
            return
        if messagebox.askyesno("确认", "确定要删除这个邮箱配置吗?"):
            del self.email_configs[sel[0]]
            self._update_listbox()
    
    def _test(self):
        sel = self.email_listbox.curselection()
        if not sel:
            messagebox.showwarning("提示", "请先选择要测试的邮箱")
            return
        cfg = self.email_configs[sel[0]]
        try:
            from notifier.email import EmailNotifier
            notifier = EmailNotifier(cfg)
            from database.storage import BidInfo
            from datetime import datetime
            test_bid = BidInfo(
                title="测试标题 - 招标监控系统",
                url="https://example.com/test",
                source="测试来源",
                publish_date=datetime.now().strftime("%Y-%m-%d"),
                content="这是一封测试邮件，用于验证邮箱配置是否正确。"
            )
            if notifier.send([test_bid]):
                messagebox.showinfo("成功", f"测试邮件已发送到 {cfg.get('receiver', '')}")
            else:
                messagebox.showerror("失败", "发送失败，请检查配置")
        except Exception as e:
            messagebox.showerror("错误", f"发送异常: {e}")
    
    def _save(self):
        self.result = self.email_configs
        self.destroy()

class SMSConfigDialog(tk.Toplevel):
    """短信配置对话框 - 仅API配置，手机号在联系人中配置"""
    def __init__(self, parent, config: Dict[str, Any]):
        super().__init__(parent)
        self.title("📱 短信API配置")
        self.geometry("500x450")
        self.resizable(False, True)
        self.config = config.copy() if config else {}
        self.result = None
        
        self._create_widgets()
        self._load_config()
        
        # 居中显示
        self.transient(parent)
        self.grab_set()
        
        # 居中
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - 500) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 450) // 2
        self.geometry(f"+{x}+{y}")
        
    def _create_widgets(self):
        # 使用Canvas实现滚动
        canvas = tk.Canvas(self, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        main_frame = ttk.Frame(canvas, padding="20")
        
        main_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=main_frame, anchor="nw", width=480)
        canvas.configure(yscrollcommand=scrollbar.set)
        
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # 服务商选择
        ttk.Label(main_frame, text="选择服务商:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.provider_var = tk.StringVar(value="aliyun")
        provider_cb = ttk.Combobox(main_frame, textvariable=self.provider_var, 
                                 values=["aliyun", "tencent"], state="readonly")
        provider_cb.grid(row=0, column=1, sticky=tk.EW, pady=5)
        provider_cb.bind("<<ComboboxSelected>>", self._on_provider_change)
        
        # 阿里云配置区域
        self.aliyun_frame = ttk.LabelFrame(main_frame, text="阿里云配置", padding="10")
        self.aliyun_frame.grid(row=1, column=0, columnspan=2, sticky=tk.EW, pady=10)
        
        ttk.Label(self.aliyun_frame, text="AccessKey ID:").grid(row=0, column=0, sticky=tk.W)
        self.aliyun_ak_var = tk.StringVar()
        ttk.Entry(self.aliyun_frame, textvariable=self.aliyun_ak_var, width=40).grid(row=0, column=1, pady=5)
        
        ttk.Label(self.aliyun_frame, text="AccessKey Secret:").grid(row=1, column=0, sticky=tk.W)
        self.aliyun_sk_var = tk.StringVar()
        ttk.Entry(self.aliyun_frame, textvariable=self.aliyun_sk_var, show="*", width=40).grid(row=1, column=1, pady=5)
        
        ttk.Label(self.aliyun_frame, text="短信签名:").grid(row=2, column=0, sticky=tk.W)
        self.aliyun_sign_var = tk.StringVar()
        ttk.Entry(self.aliyun_frame, textvariable=self.aliyun_sign_var, width=40).grid(row=2, column=1, pady=5)
        
        ttk.Label(self.aliyun_frame, text="模板CODE:").grid(row=3, column=0, sticky=tk.W)
        self.aliyun_tpl_var = tk.StringVar()
        ttk.Entry(self.aliyun_frame, textvariable=self.aliyun_tpl_var, width=40).grid(row=3, column=1, pady=5)
        
        # 腾讯云配置区域
        self.tencent_frame = ttk.LabelFrame(main_frame, text="腾讯云配置", padding="10")
        self.tencent_frame.grid(row=2, column=0, columnspan=2, sticky=tk.EW, pady=10)
        
        ttk.Label(self.tencent_frame, text="SecretId:").grid(row=0, column=0, sticky=tk.W)
        self.tencent_sid_var = tk.StringVar()
        ttk.Entry(self.tencent_frame, textvariable=self.tencent_sid_var, width=40).grid(row=0, column=1, pady=5)
        
        ttk.Label(self.tencent_frame, text="SecretKey:").grid(row=1, column=0, sticky=tk.W)
        self.tencent_skey_var = tk.StringVar()
        ttk.Entry(self.tencent_frame, textvariable=self.tencent_skey_var, show="*", width=40).grid(row=1, column=1, pady=5)
        
        ttk.Label(self.tencent_frame, text="应用ID (AppId):").grid(row=2, column=0, sticky=tk.W)
        self.tencent_appid_var = tk.StringVar()
        ttk.Entry(self.tencent_frame, textvariable=self.tencent_appid_var, width=40).grid(row=2, column=1, pady=5)
        
        ttk.Label(self.tencent_frame, text="短信签名:").grid(row=3, column=0, sticky=tk.W)
        self.tencent_sign_var = tk.StringVar()
        ttk.Entry(self.tencent_frame, textvariable=self.tencent_sign_var, width=40).grid(row=3, column=1, pady=5)
        
        ttk.Label(self.tencent_frame, text="模板ID:").grid(row=4, column=0, sticky=tk.W)
        self.tencent_tpl_var = tk.StringVar()
        ttk.Entry(self.tencent_frame, textvariable=self.tencent_tpl_var, width=40).grid(row=4, column=1, pady=5)
        
        # 按钮区域
        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=3, column=0, columnspan=2, pady=20)
        
        ttk.Button(btn_frame, text="💾 保存配置", command=self._save).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="📨 测试发送", command=self._test_send).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="取消", command=self.destroy).pack(side=tk.LEFT, padx=10)
        
        # 说明
        ttk.Label(main_frame, text="💡 手机号请在联系人设置中配置", foreground="gray").grid(row=4, column=0, columnspan=2, pady=5)
        
        self._on_provider_change(None)

    def _on_provider_change(self, event):
        provider = self.provider_var.get()
        if provider == "aliyun":
            self.aliyun_frame.grid()
            self.tencent_frame.grid_remove()
        else:
            self.aliyun_frame.grid_remove()
            self.tencent_frame.grid()
            
    def _load_config(self):
        self.provider_var.set(self.config.get('provider', 'aliyun'))
        
        self.aliyun_ak_var.set(self.config.get('access_key_id', ''))
        self.aliyun_sk_var.set(self.config.get('access_key_secret', ''))
        self.aliyun_sign_var.set(self.config.get('sign_name', ''))
        self.aliyun_tpl_var.set(self.config.get('template_code', ''))
        
        self.tencent_sid_var.set(self.config.get('secret_id', ''))
        self.tencent_skey_var.set(self.config.get('secret_key', ''))
        self.tencent_appid_var.set(self.config.get('app_id', ''))
        if self.config.get('provider') == 'tencent':
            self.tencent_sign_var.set(self.config.get('sign_name', ''))
            self.tencent_tpl_var.set(self.config.get('template_id', ''))
        
        self._on_provider_change(None)
            
    def _get_current_config(self):
        provider = self.provider_var.get()
        cfg = {'provider': provider}
        
        if provider == 'aliyun':
            cfg.update({
                'access_key_id': self.aliyun_ak_var.get().strip(),
                'access_key_secret': self.aliyun_sk_var.get().strip(),
                'sign_name': self.aliyun_sign_var.get().strip(),
                'template_code': self.aliyun_tpl_var.get().strip()
            })
        else:
            cfg.update({
                'secret_id': self.tencent_sid_var.get().strip(),
                'secret_key': self.tencent_skey_var.get().strip(),
                'app_id': self.tencent_appid_var.get().strip(),
                'sign_name': self.tencent_sign_var.get().strip(),
                'template_id': self.tencent_tpl_var.get().strip()
            })
        return cfg

    def _save(self):
        self.result = self._get_current_config()
        self.destroy()
        
    def _test_send(self):
        # 请求用户输入测试手机号
        test_phone = simpledialog.askstring("测试发送", "请输入接收测试短信的手机号:", parent=self)
        
        if not test_phone:
            return
            
        cfg = self._get_current_config()
        
        # 验证必填字段
        if cfg.get('provider') == 'aliyun':
            if not cfg.get('access_key_id') or not cfg.get('access_key_secret'):
                messagebox.showerror("错误", "请填写 AccessKey ID 和 Secret")
                return
            if not cfg.get('sign_name') or not cfg.get('template_code'):
                messagebox.showerror("错误", "请填写短信签名和模板CODE")
                return
        
        try:
            from notifier.sms import SMSNotifier
            import logging
            # 启用详细日志
            logging.basicConfig(level=logging.DEBUG)
            
            notifier = SMSNotifier(cfg)
            result = notifier.send_test(test_phone)
            if result:
                messagebox.showinfo("成功", f"测试短信已发送到 {test_phone}\n请查收手机短信。")
            else:
                messagebox.showerror("失败", f"发送失败，请检查控制台日志。\n可能原因:\n1. AccessKey 无权限\n2. 签名或模板未审核通过\n3. 手机号格式错误")
        except Exception as e:
            import traceback
            messagebox.showerror("错误", f"发送异常:\n{e}\n\n{traceback.format_exc()}")


class WeChatConfigDialog(tk.Toplevel):
    """微信配置对话框"""
    
    def __init__(self, parent, config: Dict[str, Any]):
        super().__init__(parent)
        self.title("💬 微信通知配置")
        self.geometry("480x380")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        
        self.config = config.copy() if config else {}
        self.result = None
        
        x = parent.winfo_x() + (parent.winfo_width() - 480) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 380) // 2
        self.geometry(f"+{x}+{y}")
        
        self._create_widgets()
        self._load_config()
    
    def _create_widgets(self):
        main = ttk.Frame(self, padding=20)
        main.pack(fill=tk.BOTH, expand=True)
        
        # 服务商选择
        ttk.Label(main, text="服务商:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.provider_var = tk.StringVar(value="pushplus")
        self.provider_combo = ttk.Combobox(main, textvariable=self.provider_var, 
                                            values=["pushplus", "enterprise"], state="readonly", width=20)
        self.provider_combo.grid(row=0, column=1, sticky=tk.W, pady=5)
        self.provider_combo.bind("<<ComboboxSelected>>", self._on_provider_change)
        
        # PushPlus
        self.pushplus_frame = ttk.LabelFrame(main, text="PushPlus 配置", padding=10)
        self.pushplus_frame.grid(row=1, column=0, columnspan=2, sticky=tk.EW, pady=10)
        
        ttk.Label(self.pushplus_frame, text="Token:").grid(row=0, column=0, sticky=tk.W)
        self.token_var = tk.StringVar()
        ttk.Entry(self.pushplus_frame, textvariable=self.token_var, width=40).grid(row=0, column=1, padx=5)
        ttk.Label(self.pushplus_frame, text="(在 pushplus.plus 获取)", foreground="gray").grid(row=1, column=1, sticky=tk.W)
        
        # 企业微信
        self.enterprise_frame = ttk.LabelFrame(main, text="企业微信 Webhook", padding=10)
        self.enterprise_frame.grid(row=2, column=0, columnspan=2, sticky=tk.EW, pady=10)
        
        ttk.Label(self.enterprise_frame, text="Webhook URL:").grid(row=0, column=0, sticky=tk.W)
        self.webhook_var = tk.StringVar()
        ttk.Entry(self.enterprise_frame, textvariable=self.webhook_var, width=40).grid(row=0, column=1, padx=5)
        
        # 按钮
        btn_frame = ttk.Frame(main)
        btn_frame.grid(row=3, column=0, columnspan=2, pady=20)
        ttk.Button(btn_frame, text="保存", command=self._save).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="测试发送", command=self._test_send).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="取消", command=self.destroy).pack(side=tk.LEFT, padx=10)
        
        self._on_provider_change(None)
    
    def _on_provider_change(self, event):
        if self.provider_var.get() == "pushplus":
            self.pushplus_frame.grid()
            self.enterprise_frame.grid_remove()
        else:
            self.pushplus_frame.grid_remove()
            self.enterprise_frame.grid()
    
    def _load_config(self):
        self.provider_var.set(self.config.get('provider', 'pushplus'))
        self.token_var.set(self.config.get('token', ''))
        self.webhook_var.set(self.config.get('webhook_url', ''))
        self._on_provider_change(None)
    
    def _save(self):
        self.result = {
            'provider': self.provider_var.get(),
            'token': self.token_var.get(),
            'webhook_url': self.webhook_var.get()
        }
        self.destroy()
    
    def _test_send(self):
        try:
            config = {
                'provider': self.provider_var.get(),
                'token': self.token_var.get(),
                'webhook_url': self.webhook_var.get()
            }
            notifier = WeChatNotifier(config)
            if notifier.send_test():
                messagebox.showinfo("成功", "测试消息已发送！请检查微信。")
            else:
                messagebox.showerror("失败", "发送失败，请检查配置。")
        except Exception as e:
            messagebox.showerror("错误", f"发送异常: {e}")


class VoiceConfigDialog(tk.Toplevel):
    """语音电话配置对话框 - 仅API配置，手机号在联系人中配置"""
    
    def __init__(self, parent, config: Dict[str, Any]):
        super().__init__(parent)
        self.title("📞 语音API配置")
        self.geometry("500x400")
        self.resizable(False, True)
        self.transient(parent)
        self.grab_set()
        
        self.config = config.copy() if config else {}
        self.result = None
        
        x = parent.winfo_x() + (parent.winfo_width() - 500) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 400) // 2
        self.geometry(f"+{x}+{y}")
        
        self._create_widgets()
        self._load_config()
    
    def _create_widgets(self):
        # 使用Canvas实现滚动
        canvas = tk.Canvas(self, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        main = ttk.Frame(canvas, padding=20)
        
        main.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=main, anchor="nw", width=480)
        canvas.configure(yscrollcommand=scrollbar.set)
        
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        ttk.Label(main, text="⚠️ 语音电话会产生费用，请确保阿里云账户有余额", 
                  foreground="orange").pack(pady=10)
        
        # 阿里云配置
        aliyun_frame = ttk.LabelFrame(main, text="阿里云语音服务", padding=10)
        aliyun_frame.pack(fill=tk.X, pady=10)
        
        row1 = ttk.Frame(aliyun_frame)
        row1.pack(fill=tk.X, pady=3)
        ttk.Label(row1, text="AccessKey ID:", width=15).pack(side=tk.LEFT)
        self.akid_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self.akid_var, width=30).pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        row2 = ttk.Frame(aliyun_frame)
        row2.pack(fill=tk.X, pady=3)
        ttk.Label(row2, text="AccessKey Secret:", width=15).pack(side=tk.LEFT)
        self.aksecret_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self.aksecret_var, width=30, show="*").pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        row3 = ttk.Frame(aliyun_frame)
        row3.pack(fill=tk.X, pady=3)
        ttk.Label(row3, text="被叫显号:", width=15).pack(side=tk.LEFT)
        self.show_number_var = tk.StringVar()
        ttk.Entry(row3, textvariable=self.show_number_var, width=30).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(aliyun_frame, text="(可选，公共模式留空；专属模式填阿里云分配的号码)", foreground="gray").pack(anchor=tk.W)
        
        row4 = ttk.Frame(aliyun_frame)
        row4.pack(fill=tk.X, pady=3)
        ttk.Label(row4, text="TTS模板ID:", width=15).pack(side=tk.LEFT)
        self.tts_code_var = tk.StringVar()
        ttk.Entry(row4, textvariable=self.tts_code_var, width=30).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(aliyun_frame, text="模板示例: 您有${count}条新招标信息，来源${source}", 
                  foreground="gray").pack(anchor=tk.W)
        
        # 说明
        ttk.Label(main, text="💡 手机号请在联系人设置中配置", foreground="gray").pack(pady=10)
        
        # 底部按钮
        btn_frame = ttk.Frame(main)
        btn_frame.pack(pady=20)
        ttk.Button(btn_frame, text="保存", command=self._save).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="测试呼叫", command=self._test_call).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="取消", command=self.destroy).pack(side=tk.LEFT, padx=10)
    
    def _load_config(self):
        self.akid_var.set(self.config.get('access_key_id', ''))
        self.aksecret_var.set(self.config.get('access_key_secret', ''))
        self.show_number_var.set(self.config.get('called_show_number', ''))
        self.tts_code_var.set(self.config.get('tts_code', 'TTS_328620027'))
    
    def _save(self):
        self.result = {
            'provider': 'aliyun',
            'access_key_id': self.akid_var.get(),
            'access_key_secret': self.aksecret_var.get(),
            'called_show_number': self.show_number_var.get(),
            'tts_code': self.tts_code_var.get()
        }
        self.destroy()
    
    def _test_call(self):
        test_phone = simpledialog.askstring("测试呼叫", "请输入测试手机号:", parent=self)
        if not test_phone:
            return
        try:
            config = {
                'provider': 'aliyun',
                'access_key_id': self.akid_var.get(),
                'access_key_secret': self.aksecret_var.get(),
                'called_show_number': self.show_number_var.get(),
                'tts_code': self.tts_code_var.get()
            }
            notifier = VoiceNotifier(config)
            if notifier.send_test(test_phone):
                messagebox.showinfo("成功", f"测试呼叫已发起！请接听 {test_phone}")
            else:
                messagebox.showerror("失败", "呼叫失败，请检查配置。")
        except Exception as e:
            messagebox.showerror("错误", f"呼叫异常: {e}")


class SiteManagerDialog:
    """网站管理对话框"""
    
    def __init__(self, parent, enabled_sites, custom_sites):
        self.result = None
        self.enabled_sites = set(enabled_sites)
        self.custom_sites = list(custom_sites) # copy
        
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("网站源管理")
        self.dialog.geometry("600x500")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        # 居中
        self.dialog.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - 600) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 500) // 2
        self.dialog.geometry(f"+{x}+{y}")
        
        self._create_widgets()
        
    def _create_widgets(self):
        notebook = ttk.Notebook(self.dialog)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Tab 1: 内置网站
        self._create_builtin_tab(notebook)
        
        # Tab 2: 自定义网站
        self._create_custom_tab(notebook)
        
        # 底部按钮
        btn_frame = ttk.Frame(self.dialog, padding="10")
        btn_frame.pack(fill=tk.X)
        
        ttk.Button(btn_frame, text="保存并关闭", command=self._on_save).pack(side=tk.RIGHT, padx=10)
        ttk.Button(btn_frame, text="取消", command=self.dialog.destroy).pack(side=tk.RIGHT, padx=10)
        
    def _create_builtin_tab(self, notebook):
        frame = ttk.Frame(notebook, padding="10")
        notebook.add(frame, text="内置网站")
        
        # 获取所有内置爬虫
        try:
            # from monitor_core import get_all_crawlers (Moved to top)
            all_crawlers = get_all_crawlers()
        except Exception as e:
            # 尝试在父窗口记录日志（如果父窗口有log方法）
            # 这里我们只能打印到控制台或者弹窗
            messagebox.showerror("错误", f"无法加载内置网站: {e}")
            all_crawlers = {}
            
        # 滚动区域
        canvas = tk.Canvas(frame)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # 网站列表
        self.builtin_vars = {}
        
        # 网站中文名映射 - 电力能源行业招标平台
        site_names = {
            'chinabidding': '中国采购与招标网',
            'dlzb': '中国电力招标网',
            'chinabiddingcc': '中国采购招标网',
            'gdtzb': '国电投招标网',
            'cpeinet': '中国电力设备信息网',
            'espic': '电能e招采',
            'chng': '华能集团电子商务平台',
            'powerchina': '中国电建采购电子商务平台',
            'powerchina_bid': '中国电建采购招标数智化平台',
            'powerchina_ec': '中国电建设备物资集中采购平台',
            'powerchina_scm': '中国电建供应链云服务平台',
            'powerchina_idx': '中国电建承包商管理系统',
            'powerchina_nw': '中国电建西北勘测设计研究院',
            'ceec': '中国能建电子采购平台',
            'chdtp': '中国华电电子商务平台',
            'chec_gys': '中国华电科工供应商填报系统',
            'chinazbcg': '中国招投标信息网',
            'cdt': '中国大唐电子商务平台',
            'ebidding': '国义招标',
            'neep': '国家能源e购',
            'ceic': '国家能源集团生态协作平台',
            'sgcc': '国家电网电子商务平台',
            'cecep': '中国节能环保电子采购平台',
            'gdg': '广州发展集团电子采购平台',
            'crpower': '华润电力',
            'crc': '华润集团守正电子招标采购平台',
            'longi': '隆基股份SRM系统',
            'cgnpc': '中广核电子商务平台',
            'dongfang': '东方电气',
            'zjycgzx': '浙江云采购中心',
            'ctg': '中国三峡电子采购平台',
            'sdicc': '国投集团电子采购平台',
            'csg': '中国南方电网供应链服务平台',
            'sgccetp': '国网电子商务平台电工交易专区',
            'powerbeijing': '北京京能电子商务平台',
            'ccccltd': '中交集团供应链管理系统',
            'jchc': '江苏交通控股',
            'minmetals': '中国五矿集团供应链管理平台',
            'sunwoda': '欣旺达SRM',
            'cnbm': '中国建材集团采购平台',
            'hghn': '华光环能数字化采购管理平台',
            'xcmg': '徐工全球数字化供应链系统平台',
            'xinecai': '安天智采',
            'ariba': '远景SAP系统',
            'faw': '中国一汽电子招标采购交易平台'
        }
        
        for key, name in site_names.items():
            var = tk.BooleanVar(value=key in self.enabled_sites)
            self.builtin_vars[key] = var
            
            cb = ttk.Checkbutton(scrollable_frame, text=f"{name}", variable=var)
            cb.pack(anchor=tk.W, pady=2)
        
        # 全选/取消全选按钮 (放在列表上方)
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=(0, 10))
        
        def select_all():
            for var in self.builtin_vars.values():
                var.set(True)
        
        def deselect_all():
            for var in self.builtin_vars.values():
                var.set(False)
        
        ttk.Button(btn_frame, text="✅ 全选", command=select_all).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="❌ 取消全选", command=deselect_all).pack(side=tk.LEFT, padx=5)
            
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
    def _create_custom_tab(self, notebook):
        frame = ttk.Frame(notebook, padding="10")
        notebook.add(frame, text="自定义网站")
        
        # 列表
        list_frame = ttk.Frame(frame)
        list_frame.pack(fill=tk.BOTH, expand=True)
        
        self.custom_listbox = tk.Listbox(list_frame, height=10)
        self.custom_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.custom_listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.custom_listbox.config(yscrollcommand=scrollbar.set)
        
        # 按钮
        btn_frame = ttk.Frame(frame, padding="5")
        btn_frame.pack(fill=tk.X)
        
        ttk.Button(btn_frame, text="➕ 添加", command=self._add_custom).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="✏️ 编辑", command=self._edit_custom).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="❌ 删除", command=self._del_custom).pack(side=tk.LEFT, padx=5)
        
        self._update_custom_list()
        
    def _update_custom_list(self):
        self.custom_listbox.delete(0, tk.END)
        for site in self.custom_sites:
            self.custom_listbox.insert(tk.END, f"{site['name']} - {site['url']}")
            
    def _add_custom(self):
        dialog = CustomSiteDialog(self.dialog)
        result = dialog.show()
        if result:
            self.custom_sites.append(result)
            self._update_custom_list()
            
    def _edit_custom(self):
        sel = self.custom_listbox.curselection()
        if not sel: return
        idx = sel[0]
        
        dialog = CustomSiteDialog(self.dialog, self.custom_sites[idx])
        result = dialog.show()
        if result:
            self.custom_sites[idx] = result
            self._update_custom_list()
            
    def _del_custom(self):
        sel = self.custom_listbox.curselection()
        if not sel: return
        if messagebox.askyesno("确认", "确定删除该网站？"):
            del self.custom_sites[sel[0]]
            self._update_custom_list()
            
    def _on_save(self):
        # 收集启用的内置网站
        new_enabled = []
        for key, var in self.builtin_vars.items():
            if var.get():
                new_enabled.append(key)
                
        self.result = {
            'enabled_sites': new_enabled,
            'custom_sites': self.custom_sites
        }
        self.dialog.destroy()
        
    def show(self):
        self.dialog.wait_window()
        return self.result


class ContactConfigDialog(tk.Toplevel):
    """联系人配置对话框 - 添加/编辑联系人"""
    
    def __init__(self, parent, contact_data=None):
        super().__init__(parent)
        self.result = None
        self.contact_data = contact_data or {}
        
        self.title("编辑联系人" if contact_data else "添加联系人")
        self.geometry("500x550")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        
        self._create_widgets()
        self._load_data()
        
        # 居中显示
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")
    
    def _create_widgets(self):
        main = ttk.Frame(self, padding="15")
        main.pack(fill=tk.BOTH, expand=True)
        
        # 基本信息
        ttk.Label(main, text="👤 基本信息", font=('微软雅黑', 10, 'bold')).pack(anchor=tk.W)
        basic_frame = ttk.Frame(main)
        basic_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(basic_frame, text="姓名*:").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.name_var = tk.StringVar()
        ttk.Entry(basic_frame, textvariable=self.name_var, width=30).grid(row=0, column=1, sticky=tk.W, pady=2)
        
        ttk.Separator(main, orient='horizontal').pack(fill=tk.X, pady=10)
        
        # 邮箱配置
        ttk.Label(main, text="📧 邮箱配置 (可选)", font=('微软雅黑', 10, 'bold')).pack(anchor=tk.W)
        email_frame = ttk.Frame(main)
        email_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(email_frame, text="邮箱地址:").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.email_var = tk.StringVar()
        ttk.Entry(email_frame, textvariable=self.email_var, width=35).grid(row=0, column=1, sticky=tk.W, pady=2)
        
        ttk.Label(email_frame, text="邮箱类型:").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.provider_var = tk.StringVar(value="QQ邮箱")
        provider_combo = ttk.Combobox(email_frame, textvariable=self.provider_var, 
                                       values=list(EMAIL_PROVIDERS.keys()), width=15, state='readonly')
        provider_combo.grid(row=1, column=1, sticky=tk.W, pady=2)
        
        ttk.Label(email_frame, text="授权码:").grid(row=2, column=0, sticky=tk.W, pady=2)
        self.password_var = tk.StringVar()
        ttk.Entry(email_frame, textvariable=self.password_var, show="*", width=35).grid(row=2, column=1, sticky=tk.W, pady=2)
        
        ttk.Separator(main, orient='horizontal').pack(fill=tk.X, pady=10)
        
        # 手机号配置
        ttk.Label(main, text="📱 手机号 (可选，用于短信和语音通知)", font=('微软雅黑', 10, 'bold')).pack(anchor=tk.W)
        phone_frame = ttk.Frame(main)
        phone_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(phone_frame, text="手机号:").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.phone_var = tk.StringVar()
        ttk.Entry(phone_frame, textvariable=self.phone_var, width=20).grid(row=0, column=1, sticky=tk.W, pady=2)
        
        ttk.Separator(main, orient='horizontal').pack(fill=tk.X, pady=10)
        
        # 微信配置
        ttk.Label(main, text="💬 微信通知 (可选，PushPlus)", font=('微软雅黑', 10, 'bold')).pack(anchor=tk.W)
        wechat_frame = ttk.Frame(main)
        wechat_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(wechat_frame, text="Token:").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.wechat_token_var = tk.StringVar()
        ttk.Entry(wechat_frame, textvariable=self.wechat_token_var, width=40).grid(row=0, column=1, sticky=tk.W, pady=2)
        
        ttk.Separator(main, orient='horizontal').pack(fill=tk.X, pady=10)
        
        # 启用状态
        self.enabled_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(main, text="启用此联系人的通知", variable=self.enabled_var).pack(anchor=tk.W, pady=5)
        
        # 按钮
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=15)
        ttk.Button(btn_frame, text="保存", command=self._on_save).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="取消", command=self.destroy).pack(side=tk.RIGHT)
    
    def _load_data(self):
        if self.contact_data:
            self.name_var.set(self.contact_data.get('name', ''))
            self.enabled_var.set(self.contact_data.get('enabled', True))
            self.phone_var.set(self.contact_data.get('phone', ''))
            self.wechat_token_var.set(self.contact_data.get('wechat_token', ''))
            
            email = self.contact_data.get('email', {})
            if email:
                self.email_var.set(email.get('address', ''))
                self.provider_var.set(email.get('provider', 'QQ邮箱'))
                self.password_var.set(email.get('password', ''))
    
    def _on_save(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showerror("错误", "请输入联系人姓名")
            return
        
        # 构建邮箱配置
        email_config = None
        email_addr = self.email_var.get().strip()
        if email_addr:
            provider = self.provider_var.get()
            provider_config = EMAIL_PROVIDERS.get(provider, {})
            email_config = {
                'address': email_addr,
                'provider': provider,
                'smtp_server': provider_config.get('smtp_server', ''),
                'smtp_port': provider_config.get('smtp_port', 465),
                'password': self.password_var.get(),
                'use_ssl': True
            }
        
        self.result = {
            'name': name,
            'enabled': self.enabled_var.get(),
            'phone': self.phone_var.get().strip(),
            'wechat_token': self.wechat_token_var.get().strip(),
            'email': email_config
        }
        self.destroy()


class ThemeConfigDialog(tk.Toplevel):
    """主题配置对话框"""
    def __init__(self, parent, current_theme):
        super().__init__(parent)
        self.title("🎨 主题设置")
        self.geometry("500x600")
        self.resizable(False, True)
        self.transient(parent)
        self.grab_set()
        
        self.current_theme = current_theme.copy()
        self.result = None
        
        # 居中
        x = parent.winfo_x() + (parent.winfo_width() - 500) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 600) // 2
        self.geometry(f"+{x}+{y}")
        
        self._create_widgets()
        
    def _create_widgets(self):
        main = ttk.Frame(self, padding="20")
        main.pack(fill=tk.BOTH, expand=True)
        
        # 模式选择
        ttk.Label(main, text="主题模式", font=("Microsoft YaHei", 12, "bold")).pack(anchor=tk.W, pady=(0, 10))
        
        self.mode_var = tk.StringVar(value=self.current_theme.get('mode', 'color'))
        
        mode_frame = ttk.Frame(main)
        mode_frame.pack(fill=tk.X, pady=5)
        
        ttk.Radiobutton(mode_frame, text="纯色模式", variable=self.mode_var, value="color", 
                       command=self._update_ui).pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(mode_frame, text="背景图模式", variable=self.mode_var, value="image", 
                       command=self._update_ui).pack(side=tk.LEFT, padx=10)
        
        ttk.Separator(main, orient='horizontal').pack(fill=tk.X, pady=15)
        
        # 颜色配置区域
        self.color_frame = ttk.LabelFrame(main, text="🎨 颜色自定义", padding="15")
        self.color_frame.pack(fill=tk.X, pady=5)
        
        self.colors = {
            'bg': tk.StringVar(value=self.current_theme.get('bg', '#1a1f2e')),
            'card': tk.StringVar(value=self.current_theme.get('card', '#242b3d')),
            'accent': tk.StringVar(value=self.current_theme.get('accent', '#4f8cff'))
        }
        
        self._create_color_picker(self.color_frame, "背景颜色:", 'bg', 0)
        self._create_color_picker(self.color_frame, "卡片颜色:", 'card', 1)
        self._create_color_picker(self.color_frame, "强调色:", 'accent', 2)
        
        # 图片配置区域
        self.image_frame = ttk.LabelFrame(main, text="🖼️ 背景图设置", padding="15")
        # 默认不显示，由 _update_ui 控制
        
        ttk.Label(self.image_frame, text="选择背景图片:").pack(anchor=tk.W)
        
        img_row = ttk.Frame(self.image_frame)
        img_row.pack(fill=tk.X, pady=5)
        
        self.image_path_var = tk.StringVar(value=self.current_theme.get('image_path', ''))
        ttk.Entry(img_row, textvariable=self.image_path_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(img_row, text="浏览...", command=self._browse_image).pack(side=tk.LEFT, padx=5)
        
        ttk.Label(self.image_frame, text="透明度 (0.1-1.0):").pack(anchor=tk.W, pady=(10, 0))
        self.opacity_var = tk.DoubleVar(value=self.current_theme.get('opacity', 0.9))
        ttk.Scale(self.image_frame, from_=0.1, to=1.0, variable=self.opacity_var).pack(fill=tk.X)
        
        # 按钮
        btn_frame = ttk.Frame(main)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=20)
        
        ttk.Button(btn_frame, text="保存并应用", command=self._save).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="取消", command=self.destroy).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="恢复默认", command=self._restore_default).pack(side=tk.LEFT, padx=5)
        
        self._update_ui()
        
    def _create_color_picker(self, parent, label, key, row):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky=tk.W, pady=5)
        
        preview = tk.Label(parent, width=5, bg=self.colors[key].get(), relief=tk.RIDGE)
        preview.grid(row=row, column=1, padx=5, pady=5)
        
        def pick_color():
            color = colorchooser.askcolor(color=self.colors[key].get(), title=f"选择{label}")[1]
            if color:
                self.colors[key].set(color)
                preview.config(bg=color)
                
        ttk.Button(parent, text="选择...", command=pick_color).grid(row=row, column=2, padx=5, pady=5)
        
    def _browse_image(self):
        path = filedialog.askopenfilename(
            title="选择背景图片",
            filetypes=[("图片文件", "*.png;*.jpg;*.jpeg;*.gif;*.bmp")]
        )
        if path:
            self.image_path_var.set(path)
            
    def _update_ui(self):
        if self.mode_var.get() == "color":
            self.image_frame.pack_forget()
            self.color_frame.pack(fill=tk.X, pady=5)
        else:
            self.color_frame.pack_forget()
            self.image_frame.pack(fill=tk.X, pady=5)
            
    def _restore_default(self):
        if messagebox.askyesno("确认", "确定要恢复默认主题吗？"):
            self.result = {
                'mode': 'color',
                'bg': '#1a1f2e',
                'card': '#242b3d',
                'accent': '#4f8cff',
                'image_path': '',
                'opacity': 0.9
            }
            self.destroy()

    def _save(self):
        self.result = {
            'mode': self.mode_var.get(),
            'bg': self.colors['bg'].get(),
            'card': self.colors['card'].get(),
            'accent': self.colors['accent'].get(),
            'image_path': self.image_path_var.get(),
            'opacity': self.opacity_var.get()
        }
        self.destroy()

class MonitorGUI:
    """招投标监控系统GUI - V3 多邮箱支持"""
    
    DEFAULT_KEYWORDS = "光伏,风电,风电场,风力发电,风叶,光伏巡检,风电巡检,无人机巡检,光伏无人机,风机巡检,风力发电巡检,光伏电站无人机,风电场无人机,光伏运维,风机运维,叶片巡检,红外巡检,新能源巡检"
    DEFAULT_EXCLUDE = "测绘无人机,航拍无人机,植保无人机,农业无人机,消防无人机,安防无人机,物流无人机,培训,清洗服务,清洁服务,监理,咨询服务,设计服务,工程施工,安装工程"
    DEFAULT_MUST_CONTAIN = "无人机"
    DEFAULT_INTERVAL = 20
    
    CONFIG_FILE = "user_config.json"
    LOG_FILE = "output_log.txt"
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("招标信息监控系统 · 原版修复版 1.7.2")
        self.root.geometry("720x920")
        self.root.resizable(True, True)
        
        # 设置主题样式 - 使用系统默认主题获得正确的复选框样式
        style = ttk.Style()
        try:
            # 使用 'winnative' 或 'vista' 主题以获得正确的复选框勾选显示
            if 'vista' in style.theme_names():
                style.theme_use('vista')
            elif 'winnative' in style.theme_names():
                style.theme_use('winnative')
            else:
                style.theme_use('clam')
        except:
            pass
        
        # 创建菜单栏
        self._create_menu_bar()
        
        # 默认主题配置 - 清爽白色主题
        self.theme_config = {
            'mode': 'color',
            'bg': '#f5f5f5',      # 浅灰色背景
            'card': '#ffffff',    # 白色卡片
            'accent': '#1976d2',  # 蓝色强调色
            'image_path': '',
            'opacity': 0.9
        }
        
        # 尝试从配置文件加载主题
        if os.path.exists(self.CONFIG_FILE):
            try:
                with open(self.CONFIG_FILE, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                    if 'theme' in cfg:
                        self.theme_config.update(cfg['theme'])
            except:
                pass
        
        # 颜色方案 - 白色主题
        BG_DARK = self.theme_config['bg']
        BG_CARD = self.theme_config['card']
        BG_LIGHT = '#e8e8e8'
        ACCENT = self.theme_config['accent']
        ACCENT_HOVER = '#1565c0'
        TEXT_PRIMARY = "#333333"
        TEXT_SECONDARY = "#666666"
        SUCCESS = "#4ade80"
        WARNING = "#fbbf24"
        DANGER = "#f87171"
        
        # 保存颜色供后续使用
        self.colors = {
            'bg': BG_DARK, 'card': BG_CARD, 'light': BG_LIGHT,
            'accent': ACCENT, 'text': TEXT_PRIMARY, 'text2': TEXT_SECONDARY,
            'success': SUCCESS, 'warning': WARNING, 'danger': DANGER
        }
        
        self.bg_image = None
        self.bg_photo = None
        
        # 自定义样式
        style.configure("TFrame", background=BG_DARK)
        style.configure("Card.TFrame", background=BG_CARD)
        
        style.configure("TLabel", background=BG_DARK, foreground=TEXT_PRIMARY, font=("Microsoft YaHei", 10))
        style.configure("Secondary.TLabel", background=BG_DARK, foreground=TEXT_SECONDARY, font=("Microsoft YaHei", 9))
        style.configure("Header.TLabel", font=("Microsoft YaHei", 20, "bold"), foreground=ACCENT, background=BG_DARK)
        style.configure("SubHeader.TLabel", font=("Microsoft YaHei", 11, "bold"), foreground=TEXT_PRIMARY, background=BG_CARD)
        
        style.configure("TLabelframe", background=BG_CARD, bordercolor=BG_LIGHT)
        style.configure("TLabelframe.Label", font=("Microsoft YaHei", 10, "bold"), background=BG_CARD, foreground=ACCENT)
        
        # 按钮样式
        style.configure("TButton", font=("Microsoft YaHei", 10), padding=8, background=BG_LIGHT, foreground=TEXT_PRIMARY)
        style.map("TButton", background=[('active', ACCENT), ('pressed', ACCENT)])
        
        style.configure("Action.TButton", font=("Microsoft YaHei", 11, "bold"), padding=10)
        style.map("Action.TButton", background=[('active', ACCENT_HOVER)])
        
        style.configure("Start.TButton", font=("Microsoft YaHei", 11, "bold"), foreground=SUCCESS)
        style.configure("Stop.TButton", font=("Microsoft YaHei", 11, "bold"), foreground=DANGER)
        
        # 输入框
        style.configure("TEntry", fieldbackground=BG_LIGHT, foreground=TEXT_PRIMARY, insertcolor=TEXT_PRIMARY)
        
        # 复选框 - 使用绿色勾选指示
        style.configure("TCheckbutton", 
                       background=BG_CARD, 
                       foreground=TEXT_PRIMARY, 
                       font=("Microsoft YaHei", 10),
                       indicatorcolor=BG_LIGHT,
                       indicatorrelief='flat')
        style.map("TCheckbutton", 
                 background=[('active', BG_CARD)],
                 indicatorcolor=[('selected', SUCCESS), ('!selected', BG_LIGHT)])
        
        # 分隔线
        style.configure("TSeparator", background=BG_LIGHT)
        
        self.root.configure(bg=BG_DARK)
        
        # 状态变量
        self.is_running = False
        self.monitor_thread = None
        self.stop_event = threading.Event()
        
        # 日志队列 (用于线程安全的日志显示)
        import queue
        self.log_queue = queue.Queue()
        
        # 邮箱列表 (默认空，需用户配置)
        self.email_configs: List[Dict] = []
        
        # 短信配置 (默认空，需用户配置阿里云AccessKey)
        self.sms_config = {
            'provider': 'aliyun',
            'sign_name': '',
            'template_code': '',
            'access_key_id': '',
            'access_key_secret': '',
            'phone_list': []
        }
        
        # 微信配置 (默认空，需用户配置PushPlus Token)
        self.wechat_config = {
            'provider': 'pushplus',
            'token': ''
        }
        
        # 语音电话配置 (默认空，需用户配置)
        self.voice_config = {
            'provider': 'aliyun',
            'access_key_id': '',
            'access_key_secret': '',
            'called_show_number': '',
            'tts_code': '',
            'phone_list': []
        }
        
        # 系统配置
        self.auto_start_enabled = False
        self.minimize_to_tray = True
        
        # 网站配置 - 默认启用所有内置网站
        self.enabled_sites = [
            'chinabidding', 'dlzb', 'chinabiddingcc', 'gdtzb', 'cpeinet', 'espic',
            'chng', 'powerchina', 'powerchina_bid', 'powerchina_ec', 'powerchina_scm',
            'powerchina_idx', 'powerchina_nw', 'ceec', 'chdtp', 'chec_gys', 'chinazbcg',
            'cdt', 'ebidding', 'neep', 'ceic', 'sgcc', 'cecep', 'gdg', 'crpower', 'crc',
            'longi', 'cgnpc', 'dongfang', 'zjycgzx', 'ctg', 'sdicc', 'csg', 'sgccetp',
            'powerbeijing', 'ccccltd', 'jchc', 'minmetals', 'sunwoda', 'cnbm', 'hghn',
            'xcmg', 'xinecai', 'ariba', 'faw'
        ]
        self.custom_sites = []
        
        # 联系人列表 (默认空，需用户配置)
        self.contacts: List[Dict] = []

        
        # 通知方式开关 (全局) - 默认全部开启
        self.notify_email = True
        self.notify_sms = True
        self.notify_wechat = True
        self.notify_voice = True
        
        # 系统托盘
        self.tray = None
        if TRAY_AVAILABLE:
            self.tray = SystemTray(
                app_name="招标监控",
                on_show=self._show_window,
                on_quit=self._quit_app
            )
        
        # 初始化日志文件
        self._init_log_file()
        
        # 创建界面
        self._create_widgets()
        
        # 设置日志系统
        self._setup_logging()
        
        # 加载配置
        self._load_config()
        
        # 设置窗口关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        
        # 启动时输出欢迎信息
        self.log("🚀 招投标监控系统启动成功")
        self.log(f"📧 邮箱: {len(self.email_configs)} 个已配置")
        self.log(f"📱 短信: {len(self.sms_config.get('phone_list', []))} 个号码")
        self.log(f"💬 微信: {'已配置' if self.wechat_config.get('token') else '未配置'}")
        
        # 强制更新 Selenium 状态（确保启动时检查）
        self._update_selenium_status()
        
        # 启动日志队列处理器
        self._process_log_queue()
    
    def _init_log_file(self):
        try:
            with open(self.LOG_FILE, 'a', encoding='utf-8') as f:
                f.write("\n" + "=" * 60 + "\n")
                f.write(f"=== 新会话启动: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
                f.write("=" * 60 + "\n")
        except:
            pass
    
    def _setup_logging(self):
        """设置日志系统，将所有日志输出到GUI和文件"""
        import logging
        
        class GUILogHandler(logging.Handler):
            def __init__(self, gui_instance):
                super().__init__()
                self.gui = gui_instance
            
            def emit(self, record):
                try:
                    msg = self.format(record)
                    # 使用 after 确保线程安全
                    self.gui.root.after(0, lambda m=msg: self.gui.log(m))
                except:
                    pass
        
        # 配置根日志
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        
        # 清除现有 handlers
        root_logger.handlers.clear()
        
        # 添加 GUI handler
        gui_handler = GUILogHandler(self)
        gui_handler.setFormatter(logging.Formatter('%(name)s: %(message)s'))
        root_logger.addHandler(gui_handler)
        
        # 添加文件 handler
        try:
            file_handler = logging.FileHandler(self.LOG_FILE, encoding='utf-8')
            file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s'))
            root_logger.addHandler(file_handler)
        except:
            pass

    def _configure_theme(self):
        """打开主题配置对话框"""
        dialog = ThemeConfigDialog(self.root, self.theme_config)
        self.root.wait_window(dialog)
        
        if dialog.result:
            self.theme_config.update(dialog.result)
            self._apply_theme()
            # 保存配置
            self._save_config()
            
    def _apply_theme(self):
        """应用当前主题配置"""
        # 更新颜色
        self.colors['bg'] = self.theme_config['bg']
        self.colors['card'] = self.theme_config['card']
        self.colors['light'] = self.theme_config['card']
        self.colors['accent'] = self.theme_config['accent']
        
        # 更新样式
        style = ttk.Style()
        
        # 透明样式配置
        if self.theme_config.get('mode') == 'image':
            style.layout('Transparent.TFrame', [('Frame.border', {'sticky': 'nswe'})])
        else:
            style.layout('Transparent.TFrame', [('Frame.border', {'sticky': 'nswe'}), ('Frame.fill', {'sticky': 'nswe'})])
            
        style.configure("Transparent.TFrame", background=self.colors['bg'])
        style.configure("TFrame", background=self.colors['bg'])
        style.configure("Card.TFrame", background=self.colors['card'])
        style.configure("TLabel", background=self.colors['bg'], foreground=self.colors['text'])
        style.configure("Header.TLabel", foreground=self.colors['accent'], background=self.colors['bg'])
        style.configure("SubHeader.TLabel", background=self.colors['card'])
        style.configure("TLabelframe", background=self.colors['card'], bordercolor=self.colors['light'])
        style.configure("TLabelframe.Label", background=self.colors['card'], foreground=self.colors['accent'])
        style.configure("TButton", background=self.colors['light'], foreground=self.colors['text'])
        style.map("TButton", background=[('active', self.colors['accent'])])
        style.configure("TCheckbutton", background=self.colors['card'], foreground=self.colors['text'])
        style.map("TCheckbutton", background=[('active', self.colors['card'])])
        
        self.root.configure(bg=self.colors['bg'])
        
        # 处理背景图片
        if self.theme_config['mode'] == 'image' and self.theme_config['image_path'] and PIL_AVAILABLE:
            try:
                image_path = self.theme_config['image_path']
                if os.path.exists(image_path):
                    # 加载图片
                    pil_image = Image.open(image_path)
                    
                    # 调整大小以适应窗口
                    w, h = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
                    pil_image = pil_image.resize((w, h), Image.Resampling.LANCZOS)
                    
                    # 应用透明度 (通过与黑色背景混合)
                    opacity = self.theme_config.get('opacity', 0.9)
                    if opacity < 1.0:
                        # 创建黑色背景
                        bg = Image.new('RGB', pil_image.size, (0, 0, 0))
                        pil_image = Image.blend(bg, pil_image, opacity)
                    
                    self.bg_photo = ImageTk.PhotoImage(pil_image)
                    self.bg_image = pil_image # keep ref
                    
                    # 尝试设置 Canvas 背景
                    for widget in self.root.winfo_children():
                        if isinstance(widget, tk.Canvas):
                            # 删除旧背景
                            widget.delete("bg_img")
                            # 创建新背景
                            widget.create_image(0, 0, image=self.bg_photo, anchor="nw", tags="bg_img")
                            widget.lower("bg_img")
                            break
            except Exception as e:
                print(f"Failed to load background image: {e}")
        else:
            # 清除背景图
            self.bg_photo = None
            for widget in self.root.winfo_children():
                if isinstance(widget, tk.Canvas):
                    widget.delete("bg_img")
                    widget.configure(bg=self.colors['bg'])
                    
        # 更新 Footer
        if hasattr(self, 'footer_frame'):
            self.footer_frame.config(bg=self.colors['bg'])
            self.status_label.config(bg=self.colors['bg'])
            self.clock_label.config(bg=self.colors['bg'])
            self.footer_sep.config(bg=self.colors['light'])
            self.author_label.config(bg=self.colors['bg'])

    def _create_widgets(self):
        # 创建Canvas和滚动条实现滚动
        canvas = tk.Canvas(self.root, bg=self.colors['bg'], highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=canvas.yview)
        
        # main_frame 放在 canvas 内
        main_frame = ttk.Frame(canvas, padding="20", style="Transparent.TFrame")
        
        # 配置滚动
        main_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=main_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # 鼠标滚轮绑定
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        
        # 布局
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # 动态调整 canvas 内 frame 宽度
        def _on_canvas_configure(event):
            canvas.itemconfig(canvas.find_withtag("all")[0], width=event.width - 10)
        canvas.bind("<Configure>", _on_canvas_configure)
        
        # ========== 头部横幅 (渐变效果) ==========
        header_canvas = tk.Canvas(main_frame, height=120, highlightthickness=0)
        header_canvas.pack(fill=tk.X, pady=(0, 15))
        
        def draw_header_gradient(event=None):
            w = event.width if event else 700
            header_canvas.delete("gradient")
            # 渐变从深蓝到紫色
            colors = [
                "#1e3a5f", "#1e4a6f", "#2a5a7f", "#3a6a8f", 
                "#4a7a9f", "#5a8aaf", "#4a6fbf", "#3a5fcf"
            ]
            step = w // len(colors)
            for i, color in enumerate(colors):
                header_canvas.create_rectangle(
                    i * step, 0, (i + 1) * step + 5, 120,
                    fill=color, outline="", tags="gradient"
                )
            # 装饰性元素 - 简洁的线条装饰
            header_canvas.create_line(20, 95, w - 20, 95, 
                                      fill="#5a9adf", width=1, tags="gradient")
            # 右侧小装饰
            header_canvas.create_rectangle(w - 80, 15, w - 20, 25, 
                                          fill="#5a9adf", outline="", tags="gradient")
        
        header_canvas.bind("<Configure>", draw_header_gradient)
        self.root.after(100, draw_header_gradient)
        
        # 头部文字 - 使用透明背景
        title_frame = tk.Frame(header_canvas)
        title_frame.place(relx=0.5, rely=0.5, anchor="center")
        
        # 主标题 - 透明背景
        title_label = tk.Label(title_frame, text="📊 招标监控系统", 
                               font=("Microsoft YaHei", 22, "bold"), 
                               fg="white")
        title_label.pack()
        # 设置透明背景
        title_label.configure(bg=header_canvas.cget('bg'))
        title_frame.configure(bg=header_canvas.cget('bg'))
        
        # 副标题 - 透明背景
        subtitle_label = tk.Label(title_frame, text="✨ 实时监控 · 智能筛选 · 多渠道通知 ✨", 
                                  font=("Microsoft YaHei", 11), 
                                  fg="#b8d4ff")
        subtitle_label.pack(pady=(5, 0))
        subtitle_label.configure(bg=header_canvas.cget('bg'))
        
        # 延迟更新背景色（等待渐变绘制后）
        def update_label_bg():
            try:
                # 使用渐变中间的颜色
                title_label.configure(bg="#3a6a8f")
                title_frame.configure(bg="#3a6a8f")
                subtitle_label.configure(bg="#3a6a8f")
            except:
                pass
        self.root.after(150, update_label_bg)
        
        # === 搜索配置 ===
        search_frame = ttk.LabelFrame(main_frame, text="🔍 搜索配置", padding="15")
        search_frame.pack(fill=tk.X, pady=10)
        
        # 关键字
        ttk.Label(search_frame, text="关注关键词 (逗号分隔):").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.keywords_var = tk.StringVar(value=self.DEFAULT_KEYWORDS)
        ttk.Entry(search_frame, textvariable=self.keywords_var, font=("Microsoft YaHei", 10), width=40).grid(row=0, column=1, sticky=tk.EW, padx=10, pady=5)
        
        # 排除词
        ttk.Label(search_frame, text="排除关键词 (逗号分隔):").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.exclude_var = tk.StringVar(value=self.DEFAULT_EXCLUDE)
        ttk.Entry(search_frame, textvariable=self.exclude_var, font=("Microsoft YaHei", 10), width=40).grid(row=1, column=1, sticky=tk.EW, padx=10, pady=5)
        
        # 必须包含（产品词 - AND组）
        ttk.Label(search_frame, text="必须包含 (产品词):").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.must_contain_var = tk.StringVar(value=self.DEFAULT_MUST_CONTAIN)
        ttk.Entry(search_frame, textvariable=self.must_contain_var, font=("Microsoft YaHei", 10), width=40).grid(row=2, column=1, sticky=tk.EW, padx=10, pady=5)
        
        # 提示说明
        hint_label = ttk.Label(search_frame, text="💡 提示：结果必须同时包含\"关注词\"中的任一个 + \"必须包含\"中的任一个", 
                              font=("Microsoft YaHei", 9), foreground="#888")
        hint_label.grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=(5, 0))
        
        search_frame.columnconfigure(1, weight=1)
        
        # === 网站源管理 ===
        site_frame = ttk.LabelFrame(main_frame, text="🌐 网站源配置", padding="15")
        site_frame.pack(fill=tk.X, pady=10)
        
        ttk.Button(site_frame, text="⚙️ 管理监控网站 (内置/自定义)", command=self._manage_sites, style="Action.TButton").pack(fill=tk.X)
        
        # Selenium模式开关
        selenium_frame = ttk.Frame(site_frame)
        selenium_frame.pack(fill=tk.X, pady=(10, 0))
        
        # 检测 Selenium 是否可用
        check_result = self._check_selenium_available()
        # 初始状态下，如果只是没安装Driver，也视为 False，需要点击按钮去修复
        # 但这里我们只记录状态，具体能不能勾选由 toggle 函数控制
        self.selenium_available = check_result['status']
        
        # 默认值: 如果环境OK且配置为Enabled，则True；否则False
        saved_selenium = True # 默认值，会被load_config覆盖
        self.use_selenium_var = tk.BooleanVar(value=True)  # 默认启用
        
        def on_selenium_toggle():
            # 只有在 checkbox 被点击时触发
            current_val = self.use_selenium_var.get()
            
            # 如果是试图启用 (从 False -> True)
            if current_val:
                # 检查环境
                check = self._check_selenium_available()
                if not check['status']:
                    # 环境不通，禁止勾选
                    self.use_selenium_var.set(False)
                    messagebox.showwarning(
                        "环境未就绪", 
                        "⚠️ 无法启用浏览器模式\n\n"
                        "检测到当前环境尚未准备就绪。\n"
                        "请点击右侧的【🛠️ 检测/安装环境】按钮，\n"
                        "让程序自动为您配置好环境后，再来开启此选项。"
                    )
                    return

            status = "启用" if self.use_selenium_var.get() else "禁用"
            self.log(f"✅ Selenium浏览器模式已{status}")
            self._save_config()
            self._update_selenium_status()
        
        self.selenium_cb = ttk.Checkbutton(
            selenium_frame, 
            text="🌐 启用浏览器模式 (Selenium) - 可绕过反爬虫机制",
            variable=self.use_selenium_var,
            command=on_selenium_toggle
        )
        self.selenium_cb.pack(side=tk.LEFT)
        
        # 统一的环境检测/状态按钮
        # 初始状态根据检查结果设置，在 _update_selenium_status 中会再次刷新
        self.selenium_env_btn = tk.Button(
            selenium_frame,
            text="🛠️ 检测/安装环境",
            command=self._diagnose_selenium_env,
            font=("Microsoft YaHei", 9),
            relief=tk.GROOVE,
            padx=10
        )
        self.selenium_env_btn.pack(side=tk.LEFT, padx=15)

        # 更新状态显示
        self._update_selenium_status()
        
        # === 通知配置 ===
        notify_frame = ttk.LabelFrame(main_frame, text="📨 通知配置", padding="15")
        notify_frame.pack(fill=tk.X, pady=10)
        
        # 联系人列表
        ttk.Label(notify_frame, text="👥 通知联系人:", font=('微软雅黑', 10, 'bold')).pack(anchor=tk.W)
        
        contact_list_frame = ttk.Frame(notify_frame)
        contact_list_frame.pack(fill=tk.X, pady=5)
        
        # 联系人列表容器（带滚动）
        self.contact_canvas = tk.Canvas(contact_list_frame, height=100, bg=self.colors['light'], highlightthickness=0)
        self.contact_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        self.contact_inner_frame = ttk.Frame(self.contact_canvas)
        self.contact_canvas.create_window((0, 0), window=self.contact_inner_frame, anchor="nw")
        
        # 保存联系人勾选状态的变量列表
        self.contact_vars = []
        
        # 隐藏的 Listbox 用于保持编辑/删除选中功能
        self.contact_listbox = tk.Listbox(contact_list_frame, height=0, width=0)
        
        # 联系人按钮
        contact_btn_frame = ttk.Frame(contact_list_frame)
        contact_btn_frame.pack(side=tk.LEFT, padx=5)
        ttk.Button(contact_btn_frame, text="➕ 添加", command=self._add_contact, width=8).pack(pady=2)
        ttk.Button(contact_btn_frame, text="✏️ 编辑", command=self._edit_contact, width=8).pack(pady=2)
        ttk.Button(contact_btn_frame, text="🗑️ 删除", command=self._delete_contact, width=8).pack(pady=2)
        
        # 联系人详情显示
        self.contact_detail = ttk.Label(notify_frame, text="", foreground="#666", font=('微软雅黑', 8))
        self.contact_detail.pack(fill=tk.X, pady=5)
        
        ttk.Separator(notify_frame, orient='horizontal').pack(fill=tk.X, pady=8)
        
        # 通知方式开关
        ttk.Label(notify_frame, text="📢 通知方式 (全局开关):", font=('微软雅黑', 9)).pack(anchor=tk.W)
        method_frame = ttk.Frame(notify_frame)
        method_frame.pack(fill=tk.X, pady=5)
        
        self.email_enabled = tk.BooleanVar(value=True)
        ttk.Checkbutton(method_frame, text="📧 邮箱", variable=self.email_enabled).pack(side=tk.LEFT, padx=10)
        
        self.sms_enabled = tk.BooleanVar(value=True)
        ttk.Checkbutton(method_frame, text="📱 短信", variable=self.sms_enabled).pack(side=tk.LEFT, padx=10)
        
        self.wechat_enabled = tk.BooleanVar(value=True)
        ttk.Checkbutton(method_frame, text="💬 微信", variable=self.wechat_enabled).pack(side=tk.LEFT, padx=10)
        
        self.voice_enabled = tk.BooleanVar(value=True)  # 默认启用
        ttk.Checkbutton(method_frame, text="📞 语音", variable=self.voice_enabled).pack(side=tk.LEFT, padx=10)
        
        # 短信/语音API配置按钮
        api_frame = ttk.Frame(notify_frame)
        api_frame.pack(fill=tk.X, pady=5)
        ttk.Button(api_frame, text="⚙️ 短信API配置", command=self._configure_sms).pack(side=tk.LEFT, padx=5)
        ttk.Button(api_frame, text="⚙️ 语音API配置", command=self._configure_voice).pack(side=tk.LEFT, padx=5)
        
        # === 系统设置 ===
        sys_frame = ttk.LabelFrame(main_frame, text="⚙️ 系统设置", padding="15")
        sys_frame.pack(fill=tk.X, pady=10)
        
        # 开机自启动
        self.autostart_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(sys_frame, text="开机自动启动", variable=self.autostart_var, 
                        command=self._toggle_autostart).pack(anchor=tk.W)
        
        # 最小化到托盘
        self.tray_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(sys_frame, text="关闭时最小化到系统托盘 (后台运行)", variable=self.tray_var,
                        command=self._toggle_tray).pack(anchor=tk.W)
                        
        # 主题设置
        ttk.Button(sys_frame, text="🎨 主题设置", command=self._configure_theme).pack(anchor=tk.W, pady=(5, 0))
        
        # === AI 智能过滤 ===
        ai_frame = ttk.LabelFrame(main_frame, text="🤖 AI 智能过滤", padding="15")
        ai_frame.pack(fill=tk.X, pady=10)
        
        # 预设的 API 配置（URL需包含完整API端点路径）- 开源版本不包含预设密钥
        self.ai_presets = {
            "https://api.deepseek.com/chat/completions": {
                "key": "",  # 请填入您的DeepSeek API Key
                "models": ["deepseek-chat"],
                "default_model": "deepseek-chat"
            },
            "https://api.openai.com/v1/chat/completions": {
                "key": "",  # 请填入您的OpenAI API Key
                "models": ["gpt-4", "gpt-3.5-turbo"],
                "default_model": "gpt-3.5-turbo"
            },
        }
        
        # 启用开关 - 开源版本默认关闭（需用户配置API Key后启用）
        self.ai_enable_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(ai_frame, text="启用 AI 智能分析 (二次筛选)", variable=self.ai_enable_var).pack(anchor=tk.W)
        
        # URL 行
        ai_url_row = ttk.Frame(ai_frame)
        ai_url_row.pack(fill=tk.X, pady=(5, 0))
        
        ttk.Label(ai_url_row, text="API URL:").pack(side=tk.LEFT)
        self.ai_url_var = tk.StringVar(value="https://api.deepseek.com/chat/completions")
        self.ai_url_combo = ttk.Combobox(ai_url_row, textvariable=self.ai_url_var, 
                                          values=list(self.ai_presets.keys()), width=35)
        self.ai_url_combo.pack(side=tk.LEFT, padx=5)
        self.ai_url_combo.bind("<<ComboboxSelected>>", self._on_ai_url_changed)
        self.ai_url_combo.bind("<FocusOut>", self._on_ai_url_changed)
        
        # Key 行
        ai_key_row = ttk.Frame(ai_frame)
        ai_key_row.pack(fill=tk.X, pady=(5, 0))
        
        ttk.Label(ai_key_row, text="API Key:").pack(side=tk.LEFT)
        self.ai_key_var = tk.StringVar(value="")  # 开源版本默认空
        all_keys = [p["key"] for p in self.ai_presets.values()]
        self.ai_key_combo = ttk.Combobox(ai_key_row, textvariable=self.ai_key_var, 
                                          values=all_keys, width=50)
        self.ai_key_combo.pack(side=tk.LEFT, padx=5)
        
        # 模型行
        ai_model_row = ttk.Frame(ai_frame)
        ai_model_row.pack(fill=tk.X, pady=(5, 0))
        
        ttk.Label(ai_model_row, text="模型:").pack(side=tk.LEFT)
        self.ai_model_var = tk.StringVar(value="deepseek-chat")
        # 收集所有模型
        all_models = []
        for p in self.ai_presets.values():
            all_models.extend(p["models"])
        self.ai_model_combo = ttk.Combobox(ai_model_row, textvariable=self.ai_model_var, 
                                            values=list(dict.fromkeys(all_models)), width=40)
        self.ai_model_combo.pack(side=tk.LEFT, padx=5)
        
        tk.Button(ai_model_row, text="🧪 测试连接", command=self._test_ai_connection,
                  bg="#6366f1", fg="white", relief=tk.GROOVE, padx=10).pack(side=tk.LEFT, padx=15)
        
        # 提示词说明
        ttk.Label(ai_frame, text="提示: 选择预设API或自由输入。切换URL会自动填充对应的Key和模型。",
                  foreground="#888").pack(anchor=tk.W, pady=(5, 0))
        
        # === 运行控制 ===
        ctrl_frame = ttk.LabelFrame(main_frame, text="🎮 运行控制", padding="15")
        ctrl_frame.pack(fill=tk.X, pady=10)
        
        # 间隔
        interval_inner = ttk.Frame(ctrl_frame)
        interval_inner.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(interval_inner, text="自动检索间隔:").pack(side=tk.LEFT)
        self.interval_var = tk.StringVar(value=str(self.DEFAULT_INTERVAL))
        ttk.Spinbox(interval_inner, from_=5, to=120, width=5, textvariable=self.interval_var).pack(side=tk.LEFT, padx=5)
        ttk.Label(interval_inner, text="分钟").pack(side=tk.LEFT)
        
        # 按钮 (使用自定义样式)
        btn_frame = tk.Frame(ctrl_frame, bg=self.colors['card'])
        btn_frame.pack(fill=tk.X, pady=(5, 0))
        
        # 启动按钮 - 绿色
        self.start_btn = tk.Button(
            btn_frame, text="▶ 启动监控", command=self._start_monitor,
            font=("Microsoft YaHei", 11, "bold"), 
            bg="#22c55e", fg="white", activebackground="#16a34a",
            relief=tk.FLAT, cursor="hand2", padx=20, pady=8
        )
        self.start_btn.pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)
        
        # 停止按钮 - 红色
        self.stop_btn = tk.Button(
            btn_frame, text="■ 停止", command=self._stop_monitor,
            font=("Microsoft YaHei", 11, "bold"), state=tk.DISABLED,
            bg="#ef4444", fg="white", activebackground="#dc2626",
            disabledforeground="#888", relief=tk.FLAT, cursor="hand2", padx=20, pady=8
        )
        self.stop_btn.pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)
        
        # 立即检索按钮 - 蓝色
        self.once_btn = tk.Button(
            btn_frame, text="🔍 立即检索", command=self._crawl_once,
            font=("Microsoft YaHei", 10, "bold"),
            bg="#3b82f6", fg="white", activebackground="#2563eb",
            relief=tk.FLAT, cursor="hand2", padx=15, pady=8
        )
        self.once_btn.pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)
        
        # 清除历史按钮 - 灰色
        self.clear_btn = tk.Button(
            btn_frame, text="🗑️ 清除历史", command=self._clear_history,
            font=("Microsoft YaHei", 10),
            bg="#6b7280", fg="white", activebackground="#4b5563",
            relief=tk.FLAT, cursor="hand2", padx=15, pady=8
        )
        self.clear_btn.pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)
        
        # === 日志 ===
        log_frame = ttk.LabelFrame(main_frame, text="📋 实时日志", padding="10")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        # 日志工具栏
        log_toolbar = tk.Frame(log_frame, bg=self.colors['card'])
        log_toolbar.pack(fill=tk.X, pady=(0, 5))
        
        # 弹出独立窗口按钮
        self.popout_btn = tk.Button(
            log_toolbar, text="📤 独立窗口", command=self._open_log_window,
            font=("Microsoft YaHei", 9),
            bg="#8b5cf6", fg="white", activebackground="#7c3aed",
            relief=tk.FLAT, cursor="hand2", padx=10, pady=3
        )
        self.popout_btn.pack(side=tk.LEFT, padx=2)
        
        # 清除日志按钮
        self.clear_log_btn = tk.Button(
            log_toolbar, text="🗑️ 清除日志", command=self._clear_log,
            font=("Microsoft YaHei", 9),
            bg="#6b7280", fg="white", activebackground="#4b5563",
            relief=tk.FLAT, cursor="hand2", padx=10, pady=3
        )
        self.clear_log_btn.pack(side=tk.LEFT, padx=2)
        
        self.log_text = scrolledtext.ScrolledText(
            log_frame, height=15, font=("Consolas", 10), 
            bg=self.colors['light'], fg=self.colors['text'],
            insertbackground=self.colors['accent'],
            selectbackground=self.colors['accent'],
            state='normal'
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        # 独立日志窗口引用（用于同步日志）
        self.log_window = None
        self.log_window_text = None
        
        # 处理鼠标滚轮事件 - 防止冒泡到主界面
        def on_log_mousewheel(event):
            self.log_text.yview_scroll(int(-1*(event.delta/120)), "units")
            return "break"  # 阻止事件继续传播
        
        # 直接绑定到log_text和其子组件
        self.log_text.bind("<MouseWheel>", on_log_mousewheel)
        # 同时绑定内部的text widget (ScrolledText包含一个内部Frame)
        for child in self.log_text.winfo_children():
            child.bind("<MouseWheel>", on_log_mousewheel)
        
        # === 底部状态栏 (带实时时钟) ===
        self.footer_frame = tk.Frame(main_frame, bg=self.colors['bg'], height=50)
        self.footer_frame.pack(fill=tk.X, side=tk.BOTTOM, pady=(10, 0))
        self.footer_frame.pack_propagate(False)
        
        # 左侧状态
        self.status_var = tk.StringVar(value="🟢 系统就绪")
        self.status_label = tk.Label(
            self.footer_frame, textvariable=self.status_var, 
            font=("Microsoft YaHei", 10, "bold"),
            bg=self.colors['bg'], fg="#4ade80", 
            padx=15
        )
        self.status_label.pack(side=tk.LEFT, pady=10)
        
        # 右侧时钟
        self.clock_var = tk.StringVar()
        self.clock_label = tk.Label(
            self.footer_frame, textvariable=self.clock_var,
            font=("Consolas", 11),
            bg=self.colors['bg'], fg="#8892a6"
        )
        self.clock_label.pack(side=tk.RIGHT, padx=15, pady=10)
        
        # 更新时钟
        def update_clock():
            self.clock_var.set(datetime.now().strftime("TIME: %Y-%m-%d %H:%M:%S"))
            self.root.after(1000, update_clock)
        update_clock()
        
        # 中间分隔符
        self.footer_sep = tk.Frame(self.footer_frame, bg=self.colors['light'], width=2)
        self.footer_sep.pack(side=tk.RIGHT, fill=tk.Y, pady=8)
        
        # === 添加悬停提示 ===
        ToolTip(self.start_btn, "启动后台自动监控：\n1. 定期爬取所有启用的网站\n2. 自动筛选新信息\n3. 发送邮件通知\n4. 循环执行")
        ToolTip(self.stop_btn, "停止后台监控任务")
        ToolTip(self.once_btn, "立即执行一次完整的爬取和筛选任务，\n不进入循环，适合测试或手动更新。")
        ToolTip(self.clear_btn, "清除数据库中的历史记录。\n清除后，下次检索会将所有信息视为'新信息'并重新发送通知。")
        
        # 初始化联系人列表显示
        self._update_contact_listbox()
    
    def log(self, message: str):
        """直接在主线程记录日志"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_line = f"[{timestamp}] {message}"
        try:
            # 判断用户是否在日志底部附近（只有在底部才自动滚动）
            try:
                yview = self.log_text.yview()
                is_near_bottom = yview[1] >= 0.95  # 如果滚动位置在95%以下，认为在底部
            except:
                is_near_bottom = True
            
            self.log_text.insert(tk.END, log_line + "\n")
            if is_near_bottom:
                self.log_text.see(tk.END)
            
            # 同步到独立窗口
            if hasattr(self, 'log_window_text') and self.log_window_text is not None:
                try:
                    # 独立窗口也检测滚动位置
                    try:
                        yview2 = self.log_window_text.yview()
                        is_near_bottom2 = yview2[1] >= 0.95
                    except:
                        is_near_bottom2 = True
                    
                    self.log_window_text.insert(tk.END, log_line + "\n")
                    if is_near_bottom2:
                        self.log_window_text.see(tk.END)
                except:
                    pass
            self.root.update_idletasks()
        except:
            pass
        try:
            with open(self.LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(log_line + "\n")
        except:
            pass
    
    def queue_log(self, message: str):
        """从后台线程安全地记录日志（加入队列）"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_line = f"[{timestamp}] {message}"
        self.log_queue.put(log_line)
        # 写入文件
        try:
            with open(self.LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(log_line + "\n")
        except:
            pass
    
    def _process_log_queue(self):
        """处理日志队列，在主线程中显示日志"""
        try:
            while True:
                try:
                    log_line = self.log_queue.get_nowait()
                    
                    # 判断用户是否在日志底部附近（只有在底部才自动滚动）
                    try:
                        yview = self.log_text.yview()
                        is_near_bottom = yview[1] >= 0.95
                    except:
                        is_near_bottom = True
                    
                    self.log_text.insert(tk.END, log_line + "\n")
                    if is_near_bottom:
                        self.log_text.see(tk.END)
                    
                    # 同步到独立窗口
                    if hasattr(self, 'log_window_text') and self.log_window_text is not None:
                        try:
                            # 独立窗口也检测滚动位置
                            try:
                                yview2 = self.log_window_text.yview()
                                is_near_bottom2 = yview2[1] >= 0.95
                            except:
                                is_near_bottom2 = True
                            
                            self.log_window_text.insert(tk.END, log_line + "\n")
                            if is_near_bottom2:
                                self.log_window_text.see(tk.END)
                        except:
                            pass
                except:
                    break
        except:
            pass
        # 每100ms检查一次队列
        self.root.after(100, self._process_log_queue)
    
    def _update_email_listbox(self):
        self.email_listbox.delete(0, tk.END)
        for i, cfg in enumerate(self.email_configs):
            display = f"{cfg['provider']}: {cfg['sender']} → {cfg['receiver']}"
            self.email_listbox.insert(tk.END, display)
    
    def _add_email(self):
        dialog = EmailConfigDialog(self.root)
        result = dialog.show()
        if result:
            self.email_configs.append(result)
            self._update_email_listbox()
            self.log(f"添加邮箱: {result['sender']}")
    
    def _edit_email(self):
        selection = self.email_listbox.curselection()
        if not selection:
            messagebox.showwarning("提示", "请先选择一个邮箱")
            return
        idx = selection[0]
        dialog = EmailConfigDialog(self.root, self.email_configs[idx])
        result = dialog.show()
        if result:
            self.email_configs[idx] = result
            self._update_email_listbox()
            self.log(f"更新邮箱: {result['sender']}")
    
    def _delete_email(self):
        selection = self.email_listbox.curselection()
        if not selection:
            messagebox.showwarning("提示", "请先选择一个邮箱")
            return
        idx = selection[0]
        email = self.email_configs[idx]['sender']
        if messagebox.askyesno("确认", f"确定删除邮箱 {email}?"):
            del self.email_configs[idx]
            self._update_email_listbox()
            self.log(f"删除邮箱: {email}")
    
    def _test_email(self):
        selection = self.email_listbox.curselection()
        if not selection:
            messagebox.showwarning("提示", "请先选择一个邮箱进行测试")
            return
        idx = selection[0]
        cfg = self.email_configs[idx]
        
        self.log(f"测试发送邮件到: {cfg['receiver']}")
        
        def test_thread():
            try:
                from notifier.email import EmailNotifier
                notifier = EmailNotifier(cfg)
                result = notifier.send_test()
                if result:
                    self.root.after(0, lambda: self.log("✅ 测试邮件发送成功！"))
                    self.root.after(0, lambda: messagebox.showinfo("成功", "测试邮件发送成功！请检查收件箱"))
                else:
                    self.root.after(0, lambda: self.log("❌ 测试邮件发送失败"))
            except Exception as e:
                self.root.after(0, lambda: self.log(f"❌ 发送失败: {e}"))
        
        threading.Thread(target=test_thread, daemon=True).start()
    
    def _manage_sites(self):
        """管理网站"""
        dialog = SiteManagerDialog(self.root, self.enabled_sites, self.custom_sites)
        result = dialog.show()
        if result:
            self.enabled_sites = result['enabled_sites']
            self.custom_sites = result['custom_sites']
            self._save_config()
            self.log(f"更新网站配置: 启用 {len(self.enabled_sites)} 个内置, {len(self.custom_sites)} 个自定义")

    def _update_contact_listbox(self):
        """更新联系人列表显示 - 使用Checkbutton"""
        # 清除旧的内容
        for widget in self.contact_inner_frame.winfo_children():
            widget.destroy()
        
        # 清除旧的listbox
        self.contact_listbox.delete(0, tk.END)
        self.contact_vars = []
        
        for idx, contact in enumerate(self.contacts):
            # 创建每行的框架
            row_frame = ttk.Frame(self.contact_inner_frame)
            row_frame.pack(fill=tk.X, pady=2)
            
            # 创建BooleanVar
            var = tk.BooleanVar(value=contact.get('enabled', True))
            self.contact_vars.append(var)
            
            # 配置方式图标
            methods = []
            if contact.get('email'):
                methods.append("📧")
            if contact.get('phone'):
                methods.append("📱")
            if contact.get('wechat_token'):
                methods.append("💬")
            method_str = " ".join(methods) if methods else "无配置"
            
            # 创建Checkbutton
            cb = ttk.Checkbutton(
                row_frame, 
                text=f"{contact['name']} ({method_str})",
                variable=var,
                command=lambda i=idx, v=var: self._toggle_contact_enabled(i, v)
            )
            cb.pack(side=tk.LEFT, padx=5)
            
            # 同时在隐藏的listbox中添加（用于编辑/删除选择）
            self.contact_listbox.insert(tk.END, contact['name'])
        
        # 更新canvas滚动区域
        self.contact_inner_frame.update_idletasks()
        self.contact_canvas.config(scrollregion=self.contact_canvas.bbox("all"))
    
    def _toggle_contact_enabled(self, idx, var):
        """切换联系人启用状态"""
        if idx < len(self.contacts):
            self.contacts[idx]['enabled'] = var.get()
            self._save_config()
            status = "启用" if var.get() else "禁用"
            self.log(f"联系人 {self.contacts[idx]['name']} 已{status}")
    
    def _on_contact_select(self, event=None):
        """联系人选中时显示详情"""
        selection = self.contact_listbox.curselection()
        if not selection:
            self.contact_detail.config(text="")
            return
        
        idx = selection[0]
        contact = self.contacts[idx]
        
        details = []
        if contact.get('email'):
            details.append(f"📧 {contact['email'].get('address', '')}")
        if contact.get('phone'):
            details.append(f"📱 {contact['phone']}")
        if contact.get('wechat_token'):
            token = contact['wechat_token']
            if len(token) > 8:
                token = token[:4] + "****" + token[-4:]
            details.append(f"💬 {token}")
        
        self.contact_detail.config(text="  |  ".join(details) if details else "暂无配置")
    
    def _add_contact(self):
        """添加联系人"""
        dialog = ContactConfigDialog(self.root)
        self.root.wait_window(dialog)
        if dialog.result:
            self.contacts.append(dialog.result)
            self._update_contact_listbox()
            self._save_config()
            self.log(f"添加联系人: {dialog.result['name']}")
    
    def _edit_contact(self):
        """编辑联系人"""
        if not self.contacts:
            messagebox.showwarning("提示", "暂无联系人")
            return
        
        # 如果只有一个联系人，直接编辑
        if len(self.contacts) == 1:
            idx = 0
        else:
            # 弹出选择对话框
            names = [c['name'] for c in self.contacts]
            idx = self._select_contact_dialog("选择要编辑的联系人", names)
            if idx is None:
                return
        
        contact = self.contacts[idx]
        dialog = ContactConfigDialog(self.root, contact)
        self.root.wait_window(dialog)
        if dialog.result:
            self.contacts[idx] = dialog.result
            self._update_contact_listbox()
            self._save_config()
            self.log(f"更新联系人: {dialog.result['name']}")
    
    def _delete_contact(self):
        """删除联系人"""
        if not self.contacts:
            messagebox.showwarning("提示", "暂无联系人")
            return
        
        # 如果只有一个联系人，直接选中
        if len(self.contacts) == 1:
            idx = 0
        else:
            # 弹出选择对话框
            names = [c['name'] for c in self.contacts]
            idx = self._select_contact_dialog("选择要删除的联系人", names)
            if idx is None:
                return
        
        contact = self.contacts[idx]
        if messagebox.askyesno("确认删除", f"确定要删除联系人 '{contact['name']}' 吗？"):
            del self.contacts[idx]
            self._update_contact_listbox()
            self._save_config()
            self.log(f"删除联系人: {contact['name']}")
    
    def _select_contact_dialog(self, title, names):
        """弹出选择联系人对话框，返回选中的索引"""
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.geometry("300x200")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        
        # 居中
        x = self.root.winfo_x() + (self.root.winfo_width() - 300) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 200) // 2
        dialog.geometry(f"+{x}+{y}")
        
        result = [None]
        
        ttk.Label(dialog, text=title, font=('微软雅黑', 10)).pack(pady=10)
        
        listbox = tk.Listbox(dialog, font=('微软雅黑', 10), height=5)
        listbox.pack(fill=tk.BOTH, expand=True, padx=20, pady=5)
        for name in names:
            listbox.insert(tk.END, name)
        
        def on_select():
            sel = listbox.curselection()
            if sel:
                result[0] = sel[0]
                dialog.destroy()
            else:
                messagebox.showwarning("提示", "请选择一个联系人")
        
        def on_cancel():
            dialog.destroy()
        
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="确定", command=on_select).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="取消", command=on_cancel).pack(side=tk.LEFT, padx=10)
        
        dialog.wait_window()
        return result[0]

    def _configure_email(self):
        """打开邮箱配置对话框"""
        dialog = EmailConfigDialog(self.root, self.email_configs)
        self.root.wait_window(dialog)
        if dialog.result is not None:
            self.email_configs = dialog.result
            self._save_config()
            self._update_notify_status()
            self.log(f"邮箱配置已保存 ({len(self.email_configs)} 个邮箱)")

    def _configure_sms(self):
        """打开短信配置对话框"""
        dialog = SMSConfigDialog(self.root, self.sms_config)
        self.root.wait_window(dialog)
        if dialog.result:
            self.sms_config = dialog.result
            self._save_config()
            self._update_notify_status()
            self.log("短信配置已保存")
    
    def _configure_wechat(self):
        """打开微信配置对话框"""
        dialog = WeChatConfigDialog(self.root, self.wechat_config)
        self.root.wait_window(dialog)
        if dialog.result:
            self.wechat_config = dialog.result
            self._save_config()
            self._update_notify_status()
            self.log("微信配置已保存")
    
    def _configure_voice(self):
        """打开语音电话配置对话框"""
        dialog = VoiceConfigDialog(self.root, self.voice_config)
        self.root.wait_window(dialog)
        if dialog.result:
            self.voice_config = dialog.result
            self._save_config()
            self._update_notify_status()
            self.log("语音电话配置已保存")
    
    def _toggle_autostart(self):
        """切换开机自启动"""
        enabled = self.autostart_var.get()
        self.auto_start_enabled = enabled
        if enabled:
            if AutoStart.enable():
                self.log("✅ 已启用开机自启动")
            else:
                self.log("❌ 启用开机自启动失败")
                self.autostart_var.set(False)
        else:
            if AutoStart.disable():
                self.log("✅ 已禁用开机自启动")
            else:
                self.log("❌ 禁用开机自启动失败")
        self._save_config()
    
    def _show_about_dialog(self):
        """显示关于对话框"""
        import webbrowser
        
        about_window = tk.Toplevel(self.root)
        about_window.title("关于")
        about_window.geometry("480x520")
        about_window.resizable(False, False)
        about_window.transient(self.root)
        about_window.grab_set()
        
        # 居中显示
        about_window.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - 480) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 520) // 2
        about_window.geometry(f"+{x}+{y}")
        
        # 主框架（带滚动）
        main_frame = ttk.Frame(about_window, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Logo/标题
        title_label = ttk.Label(main_frame, text="📊 招标监控系统", 
                                font=("Microsoft YaHei", 18, "bold"))
        title_label.pack(pady=(0, 5))
        
        # 版本信息
        version_label = ttk.Label(main_frame, text="版本: v1.0", 
                                  font=("Microsoft YaHei", 11))
        version_label.pack(pady=(0, 10))
        
        # 分隔线
        ttk.Separator(main_frame, orient='horizontal').pack(fill=tk.X, pady=10)
        
        # ===== 项目信息 =====
        project_frame = ttk.LabelFrame(main_frame, text="项目信息", padding=10)
        project_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(project_frame, text="GitHub: github.com/zhiqianzheng/BidMonitor", font=("Microsoft YaHei", 10)).pack(anchor=tk.W)
        ttk.Label(project_frame, text="许可证: MIT License", font=("Microsoft YaHei", 10)).pack(anchor=tk.W)
        
        # 版权信息
        copyright_label = ttk.Label(main_frame, text="© 2025 BidMonitor 开源项目", 
                                    font=("Microsoft YaHei", 9), foreground="#888")
        copyright_label.pack(pady=(5, 0))
        
        # 关闭按钮
        ttk.Button(main_frame, text="关闭", command=about_window.destroy, width=10).pack(pady=15)
    
    def _create_menu_bar(self):
        """创建菜单栏"""
        # 创建菜单栏
        self.menubar = tk.Menu(self.root)
        self.root.config(menu=self.menubar)
        
        # 直接添加三个独立的菜单项
        from .desktop_tools import show_history, show_rules
        self.menubar.add_command(label="历史结果", command=lambda: show_history(self))
        self.menubar.add_command(label="规则预览", command=lambda: show_rules(self))
        self.menubar.add_command(label="帮助", command=self._show_help)
        self.menubar.add_command(label="关于", command=self._show_about_dialog)
        self.menubar.add_command(label="检查更新", command=self._check_update)
    
    def _show_help(self):
        """打开帮助文档 (README.md)"""
        import os
        import subprocess
        
        # 查找 README.md 文件
        readme_paths = [
            "README.md",
            "README.md",
            "README.md",
            "../README.md",
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "README.md"),
        ]
        
        readme_file = None
        for path in readme_paths:
            if os.path.exists(path):
                readme_file = os.path.abspath(path)
                break
        
        if readme_file:
            try:
                # Windows 下用默认程序打开
                os.startfile(readme_file)
                self.log(f"📖 已打开帮助文档: {readme_file}")
            except Exception as e:
                messagebox.showerror("错误", f"无法打开帮助文档: {e}")
        else:
            # 如果没有找到，提示用户
            messagebox.showinfo(
                "帮助", 
                "帮助文档 (README.md) 不存在。\n\n"
                "请在程序目录下创建 README.md 文件。"
            )
    
    def _check_update(self):
        """检查更新（占位功能）"""
        messagebox.showinfo(
            "检查更新", 
            "当前版本: v1.0\n\n"
            "暂无新版本可用。\n\n"
            "该功能将在后续版本中完善。"
        )
    
    def _toggle_tray(self):
        """切换最小化到托盘"""
        self.minimize_to_tray = self.tray_var.get()
        self._save_config()
        if self.minimize_to_tray:
            self.log("✅ 关闭窗口将最小化到托盘")
        else:
            self.log("⚠️ 关闭窗口将直接退出程序")
    
    def _check_chrome_installed(self) -> bool:
        """检查谷歌浏览器是否安装"""
        import os
        chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe")
        ]
        # 也可以通过注册表检查，但文件路径覆盖了99%的情况
        return any(os.path.exists(p) for p in chrome_paths)

    def _check_selenium_available(self) -> dict:
        """
        检查 Selenium 环境
        返回: {'status': bool, 'code': str, 'msg': str}
        code: OK, NO_LIB, NO_CHROME
        """
        # 1. 检查库 (编译后通常都存在)
        try:
            from selenium import webdriver
            from webdriver_manager.chrome import ChromeDriverManager
            from selenium.webdriver.chrome.service import Service
        except ImportError:
            return {'status': False, 'code': 'NO_LIB', 'msg': '缺少 Python 依赖库'}
            
        # 2. 检查 Chrome 浏览器
        if not self._check_chrome_installed():
            return {'status': False, 'code': 'NO_CHROME', 'msg': '未检测到 Google Chrome 浏览器'}
            
        return {'status': True, 'code': 'OK', 'msg': '环境就绪'}
    
    def _update_selenium_status(self):
        """更新 Selenium 状态按钮样式"""
        if not hasattr(self, 'selenium_env_btn'):
            return
        
        check_result = self._check_selenium_available()
        is_available = check_result['status']
        
        if is_available:
            # 环境就绪 -> 绿色按钮，提示已就绪
            self.selenium_env_btn.config(
                text="✅ 浏览器环境就绪",
                fg="green",
                bg="#f0fdf4", # 浅绿背景
                state=tk.NORMAL # 允许再次点击测试
            )
        else:
            # 环境未就绪 -> 提示检测/安装
            self.selenium_env_btn.config(
                text="🛠️ 检测/安装环境",
                fg="black",
                bg="#f3f4f6", # 浅灰
                state=tk.NORMAL
            )
            
            # 强制禁用 Checkbox (再次确保)
            if self.use_selenium_var.get():
                self.use_selenium_var.set(False)

    def _open_chrome_download(self):
        """打开 Chrome 下载页"""
        import webbrowser
        webbrowser.open("https://www.google.cn/chrome/")
        
    def _diagnose_selenium_env(self):
        """运行真实的浏览器环境诊断与安装"""
        if hasattr(self, 'selenium_env_btn'):
            self.selenium_env_btn.config(state=tk.DISABLED, text="⏳ 正在安装/测试...", fg="blue")
            
        self.log("🛠️ 开始环境诊断与自动配置...")
        
        def run_diagnostic():
            try:
                # 1. 尝试导入 & 安装驱动
                from selenium import webdriver
                from selenium.webdriver.chrome.service import Service
                from selenium.webdriver.chrome.options import Options
                from selenium.webdriver.common.by import By
                from selenium.webdriver.support.ui import WebDriverWait
                from selenium.webdriver.support import expected_conditions as EC
                from webdriver_manager.chrome import ChromeDriverManager
                
                # 配置 Headless 模式
                chrome_options = Options()
                chrome_options.add_argument("--headless") 
                chrome_options.add_argument("--disable-gpu")
                chrome_options.add_argument("--no-sandbox")
                
                # 尝试安装驱动并启动
                self.log("DEBUG: 正在检查/下载 ChromeDriver (这可能需要几分钟)...")
                # 这一步会自动下载匹配的驱动
                driver_path = ChromeDriverManager().install()
                self.log(f"DEBUG: 驱动就绪: {driver_path}")
                
                service = Service(driver_path)
                
                self.log("DEBUG: 正在尝试启动浏览器...")
                driver = webdriver.Chrome(service=service, options=chrome_options)
                
                # 简单访问测试
                driver.get("data:text/html,<html><body><h1>OK</h1></body></html>")
                title = driver.title
                driver.quit()
                
                self.root.after(0, lambda: self._on_diagnostic_success("测试通过！环境配置成功。"))
                
            except Exception as e:
                error = str(e)
                self.root.after(0, lambda: self._on_diagnostic_fail(error))
                
        import threading
        threading.Thread(target=run_diagnostic, daemon=True).start()

    def _on_diagnostic_success(self, msg):
        self.log(f"✅ {msg}")
        
        # 按钮变绿
        if hasattr(self, 'selenium_env_btn'):
            self.selenium_env_btn.config(
                text="✅ 浏览器环境就绪", 
                fg="green", 
                bg="#f0fdf4",
                state=tk.NORMAL
            )
        
        # 自动启用
        self.use_selenium_var.set(True)
        self._save_config()
        self.log("✅ 已自动勾选'启用浏览器模式'")

    def _on_diagnostic_fail(self, error_msg):
        self.log(f"❌ 环境配置失败: {error_msg}")
        
        # 按钮变红
        if hasattr(self, 'selenium_env_btn'):
            self.selenium_env_btn.config(
                text="❌ 安装失败 (点击重试)", 
                fg="red", 
                bg="#fef2f2",
                state=tk.NORMAL
            )
            
        # 详细错误弹窗
        import tkinter.messagebox as messagebox
        
        # 分析错误类型给出建议
        suggestion = "请尝试手动下载 Chrome 浏览器。"
        if "google-chrome" in error_msg.lower() or "chrome not reached" in error_msg.lower():
            suggestion = "系统未检测到 Google Chrome 浏览器。\n请先安装 Chrome 浏览器再重试。"
        elif "connection" in error_msg.lower() or "timeout" in error_msg.lower():
            suggestion = "下载驱动连接超时。\n请检查您的网络连接是否通畅。"
            
        retry = messagebox.askretrycancel(
            "配置失败", 
            f"❌ 无法自动配置浏览器环境！\n\n"
            f"错误原因:\n{error_msg[:300]}...\n\n"
            f"💡 建议:\n{suggestion}\n\n"
            "是否要打开 Chrome 下载页面？"
        )
        
        if retry:
            self._open_chrome_download()
    
    def _on_install_success(self):
        """安装成功回调"""
        self.log("✅ Selenium 安装成功！")
        self.selenium_available = True
        
        # 更新状态
        self._update_selenium_status()
        
        # 隐藏安装按钮
        if hasattr(self, 'selenium_install_btn'):
            self.selenium_install_btn.pack_forget()
        
        # 自动启用 Selenium
        self.use_selenium_var.set(True)
        self._save_config()
        
        messagebox.showinfo(
            "安装成功", 
            "Selenium 已安装成功！\n\n"
            "浏览器模式已自动启用，现在可以使用了。"
        )
    
    def _on_install_failed(self, error_msg: str):
        """安装失败回调"""
        self.log(f"❌ Selenium 安装失败: {error_msg}")
        
        # 恢复按钮状态
        if hasattr(self, 'selenium_install_btn'):
            self.selenium_install_btn.config(state=tk.NORMAL, text="📦 一键安装")
        
        self._update_selenium_status()
        
        messagebox.showerror(
            "安装失败", 
            f"Selenium 安装失败！\n\n"
            f"错误信息: {error_msg[:200]}\n\n"
            f"请尝试手动安装：\n"
            f"1. 打开命令提示符 (Win+R 输入 cmd)\n"
            f"2. 运行: pip install selenium webdriver-manager"
        )
    
    def _open_log_window(self):
        """打开独立日志窗口"""
        if self.log_window is not None and self.log_window.winfo_exists():
            self.log_window.lift()
            return
        
        self.log_window = tk.Toplevel(self.root)
        self.log_window.title("📋 实时日志 - BidMonitor")
        self.log_window.geometry("900x600")
        self.log_window.configure(bg=self.colors['bg'])
        
        # 添加图标
        try:
            self.log_window.iconbitmap(self.root.iconbitmap())
        except:
            pass
        
        # 工具栏
        toolbar = tk.Frame(self.log_window, bg=self.colors['card'], pady=5)
        toolbar.pack(fill=tk.X, padx=10, pady=5)
        
        tk.Button(
            toolbar, text="🗑️ 清除日志", command=self._clear_log,
            font=("Microsoft YaHei", 9),
            bg="#6b7280", fg="white", relief=tk.FLAT, padx=10, pady=3
        ).pack(side=tk.LEFT, padx=5)
        
        tk.Label(toolbar, text="日志实时同步中...", 
                 bg=self.colors['card'], fg="#22c55e",
                 font=("Microsoft YaHei", 9)).pack(side=tk.RIGHT, padx=10)
        
        # 日志文本区
        self.log_window_text = scrolledtext.ScrolledText(
            self.log_window, font=("Consolas", 11),
            bg=self.colors['light'], fg=self.colors['text'],
            insertbackground=self.colors['accent'],
            selectbackground=self.colors['accent']
        )
        self.log_window_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        
        # 复制现有日志到新窗口
        current_log = self.log_text.get("1.0", tk.END)
        self.log_window_text.insert("1.0", current_log)
        self.log_window_text.see(tk.END)
        
        # 关闭时清理引用
        def on_close():
            self.log_window_text = None
            self.log_window.destroy()
            self.log_window = None
        
        self.log_window.protocol("WM_DELETE_WINDOW", on_close)
    
    def _clear_log(self):
        """清除日志"""
        self.log_text.delete("1.0", tk.END)
        if self.log_window_text is not None:
            try:
                self.log_window_text.delete("1.0", tk.END)
            except:
                pass
        self.log("📝 日志已清除")
    
    def _update_notify_status(self):
        """更新通知配置状态显示"""
        # 邮箱状态
        if hasattr(self, 'email_status'):
            if self.email_configs:
                self.email_status.config(text=f"已配置 {len(self.email_configs)} 个邮箱 ✓", foreground="green")
                # 显示详情
                details = []
                for cfg in self.email_configs[:3]:
                    details.append(f"→ {cfg.get('receiver', '未知')}")
                if len(self.email_configs) > 3:
                    details.append(f"...还有 {len(self.email_configs) - 3} 个")
                if hasattr(self, 'email_detail'):
                    self.email_detail.config(text="  ".join(details))
            else:
                self.email_status.config(text="未配置", foreground="gray")
                if hasattr(self, 'email_detail'):
                    self.email_detail.config(text="")
        
        # 短信状态
        if hasattr(self, 'sms_status'):
            phone_list = self.sms_config.get('phone_list', [])
            if phone_list:
                self.sms_status.config(text=f"已配置 {len(phone_list)} 个号码 ✓", foreground="green")
                # 显示详情
                phones = ", ".join(phone_list[:3])
                if len(phone_list) > 3:
                    phones += f" ...等{len(phone_list)}个"
                sign = self.sms_config.get('sign_name', '')
                detail = f"签名: {sign}  |  号码: {phones}"
                if hasattr(self, 'sms_detail'):
                    self.sms_detail.config(text=detail)
            else:
                self.sms_status.config(text="未配置", foreground="gray")
                if hasattr(self, 'sms_detail'):
                    self.sms_detail.config(text="")
        
        # 微信状态
        if hasattr(self, 'wechat_status'):
            if self.wechat_config and (self.wechat_config.get('token') or self.wechat_config.get('webhook_url')):
                self.wechat_status.config(text="已配置 ✓", foreground="green")
                provider = self.wechat_config.get('provider', 'pushplus')
                token = self.wechat_config.get('token', '')
                if token and len(token) > 8:
                    token = token[:4] + "****" + token[-4:]
                if hasattr(self, 'wechat_detail'):
                    self.wechat_detail.config(text=f"推送服务: {provider}  |  Token: {token}")
            else:
                self.wechat_status.config(text="未配置", foreground="gray")
                if hasattr(self, 'wechat_detail'):
                    self.wechat_detail.config(text="")
        
        # 语音状态
        if hasattr(self, 'voice_status'):
            phone_list = self.voice_config.get('phone_list', [])
            if phone_list and self.voice_config.get('tts_code'):
                self.voice_status.config(text=f"已配置 {len(phone_list)} 个号码 ✓", foreground="green")
                phones = ", ".join(phone_list[:3])
                if len(phone_list) > 3:
                    phones += f" ...等{len(phone_list)}个"
                if hasattr(self, 'voice_detail'):
                    self.voice_detail.config(text=f"呼叫号码: {phones}")
            else:
                self.voice_status.config(text="未配置", foreground="gray")
                if hasattr(self, 'voice_detail'):
                    self.voice_detail.config(text="")

    def _load_config(self):
        if os.path.exists(self.CONFIG_FILE):
            try:
                with open(self.CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.keywords_var.set(config.get('keywords', self.DEFAULT_KEYWORDS))
                    self.exclude_var.set(config.get('exclude', self.DEFAULT_EXCLUDE))
                    self.must_contain_var.set(config.get('must_contain', self.DEFAULT_MUST_CONTAIN))
                    self.interval_var.set(str(config.get('interval', self.DEFAULT_INTERVAL)))
                    self.email_configs = config.get('email_configs', self.email_configs)
                    self.sms_config = config.get('sms_config', self.sms_config)
                    self.wechat_config = config.get('wechat_config', self.wechat_config)
                    self.voice_config = config.get('voice_config', self.voice_config)
                    self.auto_start_enabled = config.get('auto_start', False)
                    self.minimize_to_tray = config.get('minimize_to_tray', True)
                    # 默认启用所有内置网站
                    from monitor_core import get_default_sites
                    all_site_keys = list(get_default_sites().keys())
                    self.enabled_sites = config.get('enabled_sites', all_site_keys)
                    self.custom_sites = config.get('custom_sites', [])
                    # 加载联系人列表
                    self.contacts = config.get('contacts', self.contacts)
                    # 加载 AI 配置
                    if 'ai' in config:
                        if hasattr(self, 'ai_enable_var'):
                            self.ai_enable_var.set(config['ai'].get('enable', False))
                        if hasattr(self, 'ai_url_var'):
                            self.ai_url_var.set(config['ai'].get('base_url', 'https://api.deepseek.com'))
                        if hasattr(self, 'ai_key_var'):
                            self.ai_key_var.set(config['ai'].get('api_key', ''))
                        if hasattr(self, 'ai_model_var'):
                            self.ai_model_var.set(config['ai'].get('model', 'deepseek-chat'))
                    # 加载Selenium设置（只有在Selenium可用时才根据配置启用）
                    if hasattr(self, 'use_selenium_var'):
                        saved_selenium = config.get('use_selenium', True)
                        # 只有 Selenium 可用时才使用保存的设置
                        if self._check_selenium_available():
                            self.use_selenium_var.set(saved_selenium)
                        else:
                            self.use_selenium_var.set(False)
                        # 更新状态显示
                        self._update_selenium_status()
                    # 加载通知启用状态
                    if hasattr(self, 'email_enabled'):
                        self.email_enabled.set(config.get('email_enabled', True))
                    if hasattr(self, 'sms_enabled'):
                        self.sms_enabled.set(config.get('sms_enabled', True))
                    if hasattr(self, 'wechat_enabled'):
                        self.wechat_enabled.set(config.get('wechat_enabled', True))
                    if hasattr(self, 'voice_enabled'):
                        self.voice_enabled.set(config.get('voice_enabled', False))
                    # 同步UI复选框
                    if hasattr(self, 'autostart_var'):
                        self.autostart_var.set(self.auto_start_enabled)
                    if hasattr(self, 'tray_var'):
                        self.tray_var.set(self.minimize_to_tray)
                    # 更新通知状态
                    self._update_notify_status()
                    # 更新联系人列表
                    if hasattr(self, 'contact_listbox'):
                        self._update_contact_listbox()
                    self.log("已加载上次的配置")
            except Exception as e:
                self.log(f"加载配置失败: {e}")
    
    def _save_config(self):
        config = {
            'keywords': self.keywords_var.get(),
            'exclude': self.exclude_var.get(),
            'must_contain': self.must_contain_var.get(),
            'interval': int(self.interval_var.get() or self.DEFAULT_INTERVAL),
            'email_configs': self.email_configs,
            'sms_config': self.sms_config,
            'wechat_config': self.wechat_config,
            'voice_config': self.voice_config,
            'auto_start': self.auto_start_enabled,
            'minimize_to_tray': self.minimize_to_tray,
            'enabled_sites': self.enabled_sites,
            'custom_sites': self.custom_sites,
            'email_enabled': self.email_enabled.get() if hasattr(self, 'email_enabled') else True,
            'sms_enabled': self.sms_enabled.get() if hasattr(self, 'sms_enabled') else True,
            'wechat_enabled': self.wechat_enabled.get() if hasattr(self, 'wechat_enabled') else True,
            'voice_enabled': self.voice_enabled.get() if hasattr(self, 'voice_enabled') else False,
            'contacts': self.contacts,
            'use_selenium': self.use_selenium_var.get() if hasattr(self, 'use_selenium_var') else False,
            'theme': self.theme_config,
            'ai': {
                'enable': self.ai_enable_var.get() if hasattr(self, 'ai_enable_var') else False,
                'base_url': self.ai_url_var.get() if hasattr(self, 'ai_url_var') else 'https://cc.honoursoft.cn/',
                'api_key': self.ai_key_var.get() if hasattr(self, 'ai_key_var') else '',
                'model': self.ai_model_var.get().strip() if hasattr(self, 'ai_model_var') else 'claude-sonnet-4-5-20250929-thinking',
            },
        }
        try:
            with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.log(f"保存配置失败: {e}")

    def _on_ai_url_changed(self, event=None):
        """当 AI URL 变更时，自动填充对应的 Key 和 Model"""
        url = self.ai_url_var.get().strip()
        
        # 检查是否是预设的 URL
        if url in self.ai_presets:
            preset = self.ai_presets[url]
            # 自动填充 API Key
            self.ai_key_var.set(preset["key"])
            # 自动填充默认模型
            self.ai_model_var.set(preset["default_model"])
            # 更新模型下拉列表为该 URL 支持的模型
            self.ai_model_combo['values'] = preset["models"]
            self.log(f"🔗 已切换到 {url.split('//')[1].split('/')[0]} API")

    def _test_ai_connection(self):
        """测试 AI API 连接"""
        key = self.ai_key_var.get().strip()
        url = self.ai_url_var.get().strip()
        # 获取模型名称
        model = self.ai_model_var.get().strip()
        
        if not key:
            messagebox.showwarning("提示", "请先输入 API Key")
            return
            
        self.log(f"🧪 正在测试 AI 连接 ({url})...")
        
        def run_test():
            try:
                from ai_guard import AIGuard
                guard = AIGuard({
                    'api_key': key,
                    'base_url': url,
                    'model': model,
                    'enable': True
                })
                is_rel, reason = guard.check_relevance(
                    "某省风力发电场无人机智能巡检服务采购项目", 
                    "本项目采购2025年度风电场无人机精细化巡检服务，包括可见光及红外检测...",
                    raise_on_error=True  # 测试时需要捕获真实错误
                )
                self.root.after(0, lambda: messagebox.showinfo(
                    "测试成功", 
                    f"✅ 连接成功！\n\nAI分析结果:\n判断: {'相关' if is_rel else '不相关'}\n理由: {reason}"
                ))
                self.log("✅ AI 连接测试通过")
            except Exception as e:
                self.root.after(0, lambda error=str(e): messagebox.showerror("测试失败", f"❌ 连接失败:\n{error}"))
                self.log(f"❌ AI 连接失败: {str(e)}")
                
        import threading
        threading.Thread(target=run_test, daemon=True).start()

    def _validate_input(self) -> bool:
        try:
            interval = int(self.interval_var.get())
            if not 1 <= interval <= 10080:
                raise ValueError()
        except (ValueError, TypeError):
            messagebox.showwarning("提示", "监控间隔请输入 1～10080 之间的整数（分钟）")
            return False
        # 配置在启动时读取，运行中修改需停止后重新启动。
        # 检查是否至少配置了一种通知方式 (通过联系人)
        has_notification = False
        for contact in self.contacts:
            if not contact.get('enabled', True):
                continue
            # 检查邮件
            email = contact.get('email') or {}
            address = email if isinstance(email, str) else email.get('address')
            if self.email_enabled.get() and address:
                has_notification = True
                break
            # 检查短信
            if self.sms_enabled.get() and contact.get('phone'):
                has_notification = True
                break
            if self.voice_enabled.get() and contact.get('phone'):
                has_notification = True
                break
            # 检查微信
            if self.wechat_enabled.get() and contact.get('wechat_token'):
                has_notification = True
                break
        
        if not has_notification:
            messagebox.showwarning("提示", "建议至少配置一个联系人的通知方式（邮箱/短信/微信）")
        return True
    
    def _capture_run_config(self):
        """Read Tk variables on the UI thread before starting a worker."""
        self.run_config = copy.deepcopy({
            'keywords': self.keywords_var.get(),
            'exclude': self.exclude_var.get(),
            'must_contain': self.must_contain_var.get(),
            'interval': int(self.interval_var.get()),
            'enabled_sites': self.enabled_sites,
            'custom_sites': self.custom_sites,
            'use_selenium': self.use_selenium_var.get(),
            'ai_config': {
                'enable': self.ai_enable_var.get(),
                'base_url': self.ai_url_var.get().strip(),
                'api_key': self.ai_key_var.get().strip(),
                'model': self.ai_model_var.get().strip(),
            },
            'contacts': self.contacts,
            'email_enabled': self.email_enabled.get(),
            'sms_enabled': self.sms_enabled.get(),
            'wechat_enabled': self.wechat_enabled.get(),
            'voice_enabled': self.voice_enabled.get(),
            'sms_config': self.sms_config,
            'voice_config': self.voice_config,
        })
        self.log("本次使用启动时的配置；修改规则、来源或通知设置后，请停止并重新启动。")

    def _finish_monitor(self):
        self.is_running = False
        self.once_btn.config(state=tk.NORMAL)
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        if self.stop_event.is_set():
            self.status_var.set("已停止")

    def _start_monitor(self):
        if self.monitor_thread and self.monitor_thread.is_alive():
            return
        if not self._validate_input():
            return
        self._save_config()
        self._capture_run_config()
        self.is_running = True
        self.stop_event = threading.Event()
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.once_btn.config(state=tk.DISABLED)
        self.log("开始监控...")
        self.status_var.set("监控中...")
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
    
    def _stop_monitor(self):
        self.is_running = False
        self.stop_event.set()
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.DISABLED)
        self.once_btn.config(state=tk.DISABLED)
        self.log("⏹️ 用户已手动停止检索/监控")
        self.status_var.set("正在停止，等待当前请求结束...")
    
    def _crawl_once(self):
        if self.monitor_thread and self.monitor_thread.is_alive():
            return
        if not self._validate_input():
            return
        self._save_config()
        self._capture_run_config()
        # 清除停止标志，确保可以正常执行
        self.stop_event = threading.Event()
        # 禁用按钮防止重复点击
        self.once_btn.config(state=tk.DISABLED)
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.log("开始立即检索...")
        self.monitor_thread = threading.Thread(target=self._do_crawl_with_cleanup, daemon=True)
        self.monitor_thread.start()
    
    def _do_crawl_with_cleanup(self):
        """执行爬取并在结束后恢复按钮状态"""
        try:
            self._do_crawl()
        finally:
            # 恢复按钮状态
            self.root.after(0, self._finish_monitor)
    
    def _monitor_loop(self):
        try:
            while self.is_running and not self.stop_event.is_set():
                self._do_crawl()
                if self.is_running and not self.stop_event.is_set():
                    interval = self.run_config['interval'] * 60
                    next_time = datetime.now() + timedelta(seconds=interval)
                    self._countdown_to_next(interval, next_time)
        finally:
            self.root.after(0, self._finish_monitor)
    
    def _countdown_to_next(self, total_seconds, next_time):
        """倒计时到下次检索"""
        remaining = total_seconds
        while remaining > 0 and self.is_running and not self.stop_event.is_set():
            minutes, seconds = divmod(remaining, 60)
            next_str = next_time.strftime('%H:%M:%S')
            self.root.after(0, lambda m=minutes, s=seconds, n=next_str: 
                self.status_var.set(f"⏳ 下次检索: {n} (剩余 {m}分{s}秒)")
            )
            self.stop_event.wait(1)
            remaining -= 1
    


    def _clear_history(self):
        """清除历史数据"""
        if self.monitor_thread and self.monitor_thread.is_alive():
            messagebox.showinfo("提示", "请先停止检索，等待当前任务结束后再清空历史。")
            return
        if messagebox.askyesno("确认", "确定要清除所有历史数据吗？\n清除后，下次检索将重新抓取所有信息并发送通知。"):
            try:
                # 直接使用 Storage 类清除数据，避免初始化不必要的组件
                from database.storage import Storage
                storage = Storage()
                try:
                    storage.clear_all()
                finally:
                    storage.close()
                self.log("历史数据已清除")
                messagebox.showinfo("成功", "历史数据已清除！\n请点击'立即检索'重新抓取。")
            except Exception as e:
                self.log(f"清除失败: {e}")
                messagebox.showerror("错误", f"清除失败: {e}")

    def _do_crawl(self):
        core = None
        try:
            # 检查是否已停止
            if self.stop_event.is_set():
                self.queue_log("检索已取消")
                return
            
            config = copy.deepcopy(self.run_config)
            keywords = [kw.strip() for kw in config['keywords'].replace('，', ',').split(',') if kw.strip()]
            exclude = [kw.strip() for kw in config['exclude'].replace('，', ',').split(',') if kw.strip()]
            must_contain = [kw.strip() for kw in config['must_contain'].replace('，', ',').split(',') if kw.strip()]
            
            if not keywords:
                keywords = [kw.strip() for kw in self.DEFAULT_KEYWORDS.split(',') if kw.strip()]
            
            # 显示正在初始化
            self.root.after(0, lambda: self.status_var.set("🔄 正在初始化爬虫..."))
            
            # 获取 Selenium 设置（在创建 MonitorCore 之前）
            use_selenium = config['use_selenium']
            self.queue_log(f"[配置] Selenium模式: {'✅ 启用' if use_selenium else '❌ 禁用'}")
            
            # 获取 AI 配置
            ai_config = None
            if config['ai_config']['enable']:
                ai_config = config['ai_config']
                self.queue_log(f"[配置] AI智能过滤: ✅ 启用")
            
            core = MonitorCore(
                keywords=keywords,
                exclude_keywords=exclude,
                must_contain_keywords=must_contain,
                notify_method=None,
                email="",
                phone="",
                log_callback=lambda msg: self.queue_log(msg),
                ai_config=ai_config
            )
            
            # 重要：在 _init_crawlers 之前设置好配置
            if 'crawler' not in core.config:
                core.config['crawler'] = {}
            core.config['crawler']['enabled_sites'] = config['enabled_sites']
            core.config['crawler']['use_selenium'] = use_selenium  # 使用已获取的值
            core.config['custom_sites'] = config['custom_sites']
            
            # 重新初始化爬虫（使用新配置）
            self.queue_log(f"[初始化] 正在加载爬虫，Selenium模式={'启用' if use_selenium else '禁用'}...")
            core.crawlers = core._init_crawlers()
            
            # 统计爬虫类型
            selenium_count = sum(1 for c in core.crawlers if c.__class__.__name__ == 'SeleniumCrawler')
            normal_count = len(core.crawlers) - selenium_count
            self.queue_log(f"[爬虫] 已加载: {selenium_count} 个Selenium爬虫, {normal_count} 个普通爬虫")
            
            # 如果启用了 Selenium 但没有加载 Selenium 爬虫，警告用户
            if use_selenium and selenium_count == 0:
                self.queue_log("[警告] Selenium已启用但未加载任何Selenium爬虫，请检查Selenium是否正确安装")
            
            # 显示检索进度
            total_sites = len(core.crawlers)
            self.root.after(0, lambda t=total_sites: self.status_var.set(f"🔍 正在检索 (0/{t})..."))
            
            # 设置进度回调
            def progress_callback(current, total, site_name):
                self.root.after(0, lambda c=current, t=total, n=site_name: 
                    self.status_var.set(f"🔍 正在检索 ({c}/{t}) - {n}")
                )
            
            result = core.run_once(progress_callback=progress_callback, stop_event=self.stop_event)
            new_count = result.get('new_count', 0)
            
            # 记录是否被停止
            was_stopped = self.stop_event.is_set()
            
            # 检查是否有新发现的数据
            new_count = result.get('new_count', 0)
            
            if was_stopped:
                self.queue_log(f"检索已停止，已保存 {new_count} 条新信息，待下次运行通知")
                return
            
            from notifier.service import NotificationService
            NotificationService(core.storage, self.queue_log).send_pending(config, self.stop_event)
            
            self.queue_log(f"检索完成，发现 {new_count} 条新信息")
            self.root.after(0, lambda: self.status_var.set(
                f"最后检索: {datetime.now().strftime('%H:%M')} | 发现 {new_count} 条新信息"
            ))
            
        except Exception as e:
            self.queue_log(f"检索出错: {e}")
        finally:
            if core:
                core.storage.close()
    
    def _send_to_all_emails(self, bids):
        if not bids:
            return
        
        from notifier.email import EmailNotifier
        
        for cfg in self.email_configs:
            try:
                notifier = EmailNotifier(cfg)
                result = notifier.send(list(bids))
                if result:
                    self.queue_log(f"✅ 邮件已发送到 {cfg['receiver']}")
                else:
                    self.queue_log(f"❌ 发送失败 {cfg['receiver']}")
            except Exception as e:
                self.queue_log(f"❌ 发送失败 {cfg['receiver']}: {e}")
    
    def _send_sms_to_phone(self, bids):
        """发送短信通知 (发送到配置中的所有手机号)"""
        phone_list = self.sms_config.get('phone_list', [])
        if not bids or not phone_list:
            return
        try:
            from notifier.sms import SMSNotifier
            notifier = SMSNotifier(self.sms_config)
            sources = list(set([b.source for b in bids]))
            source_str = "、".join(sources[:2])
            if len(sources) > 2:
                source_str += "等"
            summary = {'count': len(bids), 'source': source_str}
            
            for phone in phone_list[:5]:
                if notifier.send(phone, bids, summary):
                    self.queue_log(f"✅ 短信已发送: {phone}")
                else:
                    self.queue_log(f"❌ 短信发送失败: {phone}")
        except Exception as e:
            self.queue_log(f"❌ 短信发送异常: {e}")
    
    def _send_wechat_notification(self, bids):
        """发送微信通知"""
        if not bids or not self.wechat_config:
            return
        try:
            notifier = WeChatNotifier(self.wechat_config)
            if notifier.send(bids):
                self.queue_log("✅ 微信通知已发送")
            else:
                self.queue_log("❌ 微信通知发送失败")
        except Exception as e:
            self.queue_log(f"❌ 微信通知异常: {e}")
    
    def _send_voice_call(self, bids):
        """发送语音电话通知 (呼叫配置中的所有手机号)"""
        phone_list = self.voice_config.get('phone_list', [])
        if not bids or not phone_list or not self.voice_config.get('tts_code'):
            return
        try:
            # 等待3秒，让网络栈在爬虫完成后恢复
            import time
            time.sleep(3)
            
            notifier = VoiceNotifier(self.voice_config)
            sources = list(set([b.source for b in bids]))
            # 简化来源描述：只显示第一个网站名称 + "等X个网站"
            if len(sources) == 1:
                source_str = sources[0][:6]  # 单个来源取前6字符
            elif len(sources) > 1:
                source_str = f"{sources[0][:4]}等{len(sources)}个网站"
            else:
                source_str = "招标网站"
            
            for phone in phone_list[:5]:  # 最多5个
                if notifier.call(phone, count=len(bids), source=source_str):
                    self.queue_log(f"✅ 语音呼叫已发起: {phone}")
                else:
                    self.queue_log(f"❌ 语音呼叫失败: {phone}")
        except Exception as e:
            self.queue_log(f"❌ 语音呼叫异常: {e}")
    
    def _send_email_to_contact(self, contact, bids):
        """发送邮件给指定联系人 - 使用联系人自己的邮箱配置"""
        email_cfg = contact.get('email')
        if not email_cfg or not bids:
            return
        
        # 获取联系人邮箱地址
        email_addr = email_cfg.get('address')
        if not email_addr:
            return
        
        # 检查是否有发送配置（密码/授权码）
        password = email_cfg.get('password')
        if not password:
            self.queue_log(f"❌ 邮件发送失败: {contact['name']} 未配置授权码")
            return
        
        from notifier.email import EmailNotifier
        
        try:
            # 使用联系人自己的邮箱配置，发给自己
            cfg = {
                'smtp_server': email_cfg.get('smtp_server', 'smtp.qq.com'),
                'smtp_port': email_cfg.get('smtp_port', 465),
                'sender': email_addr,  # 发件人=联系人邮箱
                'password': password,
                'receiver': email_addr,  # 收件人=联系人邮箱（发给自己）
                'use_ssl': email_cfg.get('use_ssl', True)
            }
            notifier = EmailNotifier(cfg)
            if notifier.send(list(bids)):
                self.queue_log(f"✅ 邮件已发送: {contact['name']} ({email_addr})")
            else:
                self.queue_log(f"❌ 邮件发送失败: {contact['name']}")
        except Exception as e:
            self.queue_log(f"❌ 邮件发送异常 {contact['name']}: {e}")
    
    def _send_sms_to_contact(self, contact, bids):
        """发送短信给指定联系人"""
        phone = contact.get('phone')
        if not phone or not bids:
            return
        
        try:
            from notifier.sms import SMSNotifier
            notifier = SMSNotifier(self.sms_config)
            sources = list(set([b.source for b in bids]))
            source_str = "、".join(sources[:2])
            if len(sources) > 2:
                source_str += "等"
            summary = {'count': len(bids), 'source': source_str}
            
            if notifier.send(phone, bids, summary):
                self.queue_log(f"✅ 短信已发送: {contact['name']} ({phone})")
            else:
                self.queue_log(f"❌ 短信发送失败: {contact['name']}")
        except Exception as e:
            self.queue_log(f"❌ 短信发送异常 {contact['name']}: {e}")
    
    def _send_wechat_to_contact(self, contact, bids):
        """发送微信通知给指定联系人"""
        token = contact.get('wechat_token')
        if not token or not bids:
            return
        
        try:
            config = {'provider': 'pushplus', 'token': token}
            notifier = WeChatNotifier(config)
            if notifier.send(bids):
                self.queue_log(f"✅ 微信已发送: {contact['name']}")
            else:
                self.queue_log(f"❌ 微信发送失败: {contact['name']}")
        except Exception as e:
            self.queue_log(f"❌ 微信发送异常 {contact['name']}: {e}")
    
    def _send_voice_to_contact(self, contact, bids):
        """发送语音呼叫给指定联系人"""
        phone = contact.get('phone')
        if not phone or not bids or not self.voice_config.get('tts_code'):
            return
        
        try:
            # 等待3秒，让网络栈在爬虫完成后恢复
            import time
            time.sleep(3)
            
            notifier = VoiceNotifier(self.voice_config)
            sources = list(set([b.source for b in bids]))
            # 简化来源描述：只显示第一个网站名称 + "等X个网站"
            if len(sources) == 1:
                source_str = sources[0][:6]  # 单个来源取前6字符
            elif len(sources) > 1:
                source_str = f"{sources[0][:4]}等{len(sources)}个网站"
            else:
                source_str = "招标网站"
            
            if notifier.call(phone, count=len(bids), source=source_str):
                self.queue_log(f"✅ 语音呼叫: {contact['name']} ({phone})")
            else:
                self.queue_log(f"❌ 语音呼叫失败: {contact['name']}")
        except Exception as e:
            self.queue_log(f"❌ 语音呼叫异常 {contact['name']}: {e}")
    
    def _on_close(self):
        """窗口关闭事件处理"""
        if self.minimize_to_tray and self.tray and TRAY_AVAILABLE:
            # 最小化到托盘
            self.root.withdraw()
            if not hasattr(self, '_tray_started'):
                self.tray.start()
                self._tray_started = True
            self.log("程序已最小化到系统托盘")
        else:
            self._quit_app()
    
    def _show_window(self):
        """显示窗口"""
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
    
    def _quit_app(self):
        """退出应用"""
        if self.tray:
            self.tray.stop()
        self.is_running = False
        self.stop_event.set()
        self.root.destroy()
    
    def run(self):
        self.root.mainloop()


def main():
    app = MonitorGUI()
    app.run()


if __name__ == '__main__':
    main()

"""
系统工具模块
- 系统托盘
- 开机自启动
"""
import os
import sys
import threading
import logging

try:
    import winreg
except ImportError:
    winreg = None  # 非 Windows 平台

try:
    from pystray import Icon, MenuItem, Menu
    from PIL import Image, ImageDraw
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False


class AutoStart:
    """Windows 开机自启动管理"""
    
    REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
    APP_NAME = "BidMonitor"
    
    @classmethod
    def is_enabled(cls) -> bool:
        """检查是否已启用开机自启动"""
        if winreg is None:
            return False
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, cls.REG_PATH, 0, winreg.KEY_READ)
            winreg.QueryValueEx(key, cls.APP_NAME)
            winreg.CloseKey(key)
            return True
        except:
            return False
    
    @classmethod
    def enable(cls, exe_path: str = None) -> bool:
        """启用开机自启动"""
        if winreg is None:
            return False
        
        if exe_path is None:
            if getattr(sys, 'frozen', False):
                exe_path = sys.executable
            else:
                # 开发环境，使用 pythonw.exe 运行脚本
                exe_path = f'"{sys.executable}" "{os.path.abspath(sys.argv[0])}"'
        
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, cls.REG_PATH, 0, winreg.KEY_SET_VALUE)
            winreg.SetValueEx(key, cls.APP_NAME, 0, winreg.REG_SZ, exe_path)
            winreg.CloseKey(key)
            logging.info(f"[AutoStart] 已启用开机自启动: {exe_path}")
            return True
        except Exception as e:
            logging.error(f"[AutoStart] 启用失败: {e}")
            return False
    
    @classmethod
    def disable(cls) -> bool:
        """禁用开机自启动"""
        if winreg is None:
            return False
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, cls.REG_PATH, 0, winreg.KEY_SET_VALUE)
            winreg.DeleteValue(key, cls.APP_NAME)
            winreg.CloseKey(key)
            logging.info("[AutoStart] 已禁用开机自启动")
            return True
        except Exception as e:
            logging.error(f"[AutoStart] 禁用失败: {e}")
            return False


class SystemTray:
    """系统托盘图标管理"""
    
    def __init__(self, app_name: str = "招标监控", on_show=None, on_quit=None):
        """
        初始化系统托盘
        
        Args:
            app_name: 应用名称
            on_show: 显示窗口回调
            on_quit: 退出应用回调
        """
        self.app_name = app_name
        self.on_show = on_show
        self.on_quit = on_quit
        self.icon = None
        self._running = False
    
    def _create_icon_image(self):
        """创建简单的托盘图标"""
        # 创建一个简单的蓝色圆形图标
        size = 64
        image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        # 蓝色背景
        draw.ellipse([4, 4, size-4, size-4], fill=(66, 133, 244, 255))
        # 白色中心 (表示监控)
        draw.ellipse([20, 20, size-20, size-20], fill=(255, 255, 255, 255))
        return image
    
    def _on_show_click(self, icon, item):
        """点击显示"""
        if self.on_show:
            self.on_show()
    
    def _on_quit_click(self, icon, item):
        """点击退出"""
        self.stop()
        if self.on_quit:
            self.on_quit()
    
    def start(self):
        """启动托盘图标 (在后台线程)"""
        if not TRAY_AVAILABLE:
            logging.warning("[SystemTray] pystray 不可用")
            return
        
        menu = Menu(
            MenuItem("显示窗口", self._on_show_click, default=True),
            MenuItem("退出", self._on_quit_click)
        )
        
        self.icon = Icon(
            name=self.app_name,
            icon=self._create_icon_image(),
            title=self.app_name,
            menu=menu
        )
        
        self._running = True
        # 在新线程中运行
        self._tray_thread = threading.Thread(target=self.icon.run, daemon=True)
        self._tray_thread.start()
        logging.info("[SystemTray] 托盘图标已启动")
    
    def stop(self):
        """停止托盘图标"""
        self._running = False
        if self.icon:
            self.icon.stop()
            logging.info("[SystemTray] 托盘图标已停止")
    
    def update_title(self, title: str):
        """更新托盘提示文字"""
        if self.icon:
            self.icon.title = title

import os
import sys

# 获取 run.py 所在的目录作为项目根目录
if getattr(sys, 'frozen', False):
    # 打包后的可执行文件
    base_path = os.path.dirname(sys.executable)
else:
    # 普通 Python 脚本
    base_path = os.path.dirname(os.path.abspath(__file__))

# 切换工作目录到项目根目录，确保配置文件保存在正确位置
os.chdir(base_path)

# 将 src 目录添加到 Python 路径
src_path = os.path.join(base_path, 'src')
if src_path not in sys.path:
    sys.path.insert(0, src_path)

from src.gui import main

if __name__ == '__main__':
    main()

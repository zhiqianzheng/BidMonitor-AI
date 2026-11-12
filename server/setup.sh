#!/bin/bash
#
# BidMonitor 一键部署启动脚本
# 使用方法：
#   1. 将 bidmonitor_deploy.zip 上传到 /opt/bidmonitor/
#   2. cd /opt/bidmonitor
#   3. chmod +x server/setup.sh
#   4. ./server/setup.sh
#

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}   BidMonitor 一键部署脚本 v1.7${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# 目录定义
INSTALL_DIR="/opt/bidmonitor"
ZIP_FILE="$INSTALL_DIR/bidmonitor_deploy.zip"

# 检查是否在正确目录
cd "$INSTALL_DIR" || {
    echo -e "${RED}错误: 请将脚本放在 $INSTALL_DIR 目录下运行${NC}"
    exit 1
}

# 检查zip文件是否存在
if [ ! -f "$ZIP_FILE" ]; then
    echo -e "${RED}错误: 未找到 bidmonitor_deploy.zip 文件${NC}"
    echo "请将 bidmonitor_deploy.zip 上传到 $INSTALL_DIR 目录"
    exit 1
fi

echo -e "${YELLOW}[1/6] 停止旧服务...${NC}"
# 停止可能正在运行的旧进程
pkill -f "uvicorn app:app" 2>/dev/null || true
sleep 2

echo -e "${YELLOW}[2/6] 解压部署包...${NC}"
# 备份旧的server目录（如果存在）
if [ -d "server" ]; then
    mv server server.bak.$(date +%Y%m%d_%H%M%S)
    echo "  已备份旧的 server 目录"
fi
if [ -d "src" ]; then
    mv src src.bak.$(date +%Y%m%d_%H%M%S)
    echo "  已备份旧的 src 目录"
fi

# 备份重组后的应用源码，避免解压后遗留已移除的旧模块
if [ -d "apps" ]; then
    mv apps apps.bak.$(date +%Y%m%d_%H%M%S)
    echo "  已备份旧的 apps 目录"
fi

# 解压
unzip -o "$ZIP_FILE"
echo -e "${GREEN}  解压完成${NC}"

echo -e "${YELLOW}[3/6] 检查Python环境...${NC}"
# 检查Python版本
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
    echo -e "  Python版本: ${GREEN}$PYTHON_VERSION${NC}"
else
    echo -e "${RED}错误: 未安装Python3${NC}"
    echo "请先安装Python3: yum install python3 python3-pip -y"
    exit 1
fi

echo -e "${YELLOW}[4/6] 安装依赖包...${NC}"
cd "$INSTALL_DIR/server"
pip3 install -r requirements.txt -q 2>/dev/null || pip3 install -r requirements.txt
echo -e "${GREEN}  依赖安装完成${NC}"

echo -e "${YELLOW}[5/6] 创建数据目录...${NC}"
mkdir -p "$INSTALL_DIR/data"
mkdir -p "$INSTALL_DIR/server/logs"
echo -e "${GREEN}  目录创建完成${NC}"

echo -e "${YELLOW}[6/6] 启动服务...${NC}"
# 切换到server目录
cd "$INSTALL_DIR/server"

# 后台启动服务
nohup python3 -m uvicorn app:app --host 0.0.0.0 --port 8080 > logs/server.log 2>&1 &
sleep 3

# 检查是否启动成功
if pgrep -f "uvicorn app:app" > /dev/null; then
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}   ✅ BidMonitor 启动成功！${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
    echo -e "  访问地址: ${GREEN}http://YOUR_SERVER_IP:8080${NC}"
    echo ""
    echo "  常用命令："
    echo "    查看日志: tail -f $INSTALL_DIR/server/logs/server.log"
    echo "    停止服务: pkill -f 'uvicorn app:app'"
    echo "    重启服务: cd $INSTALL_DIR && ./server/setup.sh"
    echo ""
else
    echo -e "${RED}启动失败，请检查日志：${NC}"
    cat logs/server.log
    exit 1
fi

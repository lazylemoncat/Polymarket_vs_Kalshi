# -------------------------------
# Polymarket vs Kalshi Arbitrage Monitor
# -------------------------------

FROM python:3.11-slim

LABEL maintainer="ArbitrageBot <dev@arbmonitor.io>"
LABEL description="Polymarket-Kalshi arbitrage monitoring system"

# 环境变量
ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=UTC

# 创建工作目录
WORKDIR /app

# 复制项目文件
COPY . /app

# 安装依赖
RUN pip install --no-cache-dir -U pip setuptools wheel \
    && pip install --no-cache-dir aiohttp requests rich python-dotenv

# 创建数据和日志目录
RUN mkdir -p /app/data /app/logs

# 暴露默认端口（如未来添加 API 可复用）
EXPOSE 8080

# 启动命令
CMD ["python", "monitor.py"]

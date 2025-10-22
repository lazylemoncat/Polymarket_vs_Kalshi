FROM python:3.12.12-slim-bookworm

# 环境变量
ENV TZ=UTC

# 创建工作目录
WORKDIR /app

COPY pyproject.toml uv.lock ./


# 安装依赖
RUN pip install --no-cache-dir uv

RUN uv sync --frozen --no-dev

# 复制项目文件
COPY . /app

# 创建数据和日志目录
RUN mkdir -p /app/data /app/logs

# 暴露默认端口（如未来添加 API 可复用）
EXPOSE 8080

# 启动命令
CMD ["uv", "run", "src/monitor.py"]

# 多阶段构建 Dockerfile
# 阶段1: 构建依赖
FROM python:3.11-slim as builder

WORKDIR /app

# 安装构建依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# 阶段2: 运行时
FROM python:3.11-slim

WORKDIR /app

# 复制安装的依赖
COPY --from=builder /install /usr/local

# 复制应用代码
COPY src/ ./src/
COPY app/ ./app/
COPY config/ ./config/
COPY data/ ./data/
COPY scripts/ ./scripts/

# 创建必要的目录
RUN mkdir -p logs cache output

# 设置环境变量
ENV PYTHONPATH=/app/src:/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 暴露端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health')" || exit 1

# 启动命令：FastAPI 统一入口
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Playwright 官方镜像自带 Chromium 与系统依赖，版本必须与 backend/requirements.txt 中的 playwright 保持一致
# 网络访问不了 MCR 时，可用 --build-arg BASE_REGISTRY=mcr.m.daocloud.io 换成国内镜像源
ARG BASE_REGISTRY=mcr.microsoft.com
ARG PLAYWRIGHT_VERSION=1.63.0
FROM ${BASE_REGISTRY}/playwright/python:v${PLAYWRIGHT_VERSION}-noble

# 国内构建可用 --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_INDEX_URL=https://pypi.org/simple

LABEL org.opencontainers.image.title="wecom-trusted-ip" \
      org.opencontainers.image.description="自动把 iKuai 的公网 IP 覆盖到所有企业微信自建应用的可信 IP" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_DATA_DIR=/data \
    APP_FRONTEND_DIR=/app/frontend \
    PYTHONPATH=/app/backend

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" -r backend/requirements.txt

COPY backend/ ./backend/
COPY frontend/ ./frontend/

VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health').read()"

CMD ["python", "-m", "uvicorn", "app.main:app", "--app-dir", "/app/backend", "--host", "0.0.0.0", "--port", "8000"]


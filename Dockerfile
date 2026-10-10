# 轻量基础镜像 + 只装 Chromium：Playwright 官方镜像自带 Chromium/Firefox/WebKit，
# 解压后接近 4 GB，而本项目只用到 Chromium。
#
# 网络访问不了 Docker Hub 时，可用 --build-arg BASE_REGISTRY=docker.m.daocloud.io 换成国内镜像源
ARG BASE_REGISTRY=docker.io/library
FROM ${BASE_REGISTRY}/python:3.12-slim

# 国内构建可用 --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_INDEX_URL=https://pypi.org/simple

LABEL org.opencontainers.image.title="wecom-trusted-ip" \
      org.opencontainers.image.description="自动把 iKuai 的公网 IP 覆盖到所有企业微信自建应用的可信 IP" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_DATA_DIR=/data \
    APP_FRONTEND_DIR=/app/frontend \
    PYTHONPATH=/app/backend \
    # 浏览器装到固定路径，运行期靠同一个变量找到它
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
# --with-deps 会一起装好 Chromium 需要的系统库；装完清掉 apt 缓存，别把包管理器垃圾留在镜像里
RUN pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" -r backend/requirements.txt \
    && python -m playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

COPY backend/ ./backend/
COPY frontend/ ./frontend/

VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health').read()"

CMD ["python", "-m", "uvicorn", "app.main:app", "--app-dir", "/app/backend", "--host", "0.0.0.0", "--port", "8000"]

#!/usr/bin/env bash
# 构建并推送 Docker 镜像到 Docker Hub（Linux 服务器用）
#
# 用法：
#   docker login
#   ./scripts/build_and_push_image.sh <dockerhub用户名>/wecom-trusted-ip [tag]
set -euo pipefail

REPOSITORY="${1:?用法: $0 <dockerhub用户名/仓库名> [tag]}"
TAG="${2:-latest}"
PLATFORM="${PLATFORM:-linux/amd64}"
BASE_REGISTRY="${BASE_REGISTRY:-mcr.microsoft.com}"
PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.org/simple}"
IMAGE="${REPOSITORY}:${TAG}"

cd "$(dirname "$0")/.."

command -v docker >/dev/null || { echo "未找到 docker 命令" >&2; exit 1; }

echo "构建镜像 ${IMAGE}（平台 ${PLATFORM}，基础镜像源 ${BASE_REGISTRY}）..."
docker build --platform "${PLATFORM}" \
  --build-arg "BASE_REGISTRY=${BASE_REGISTRY}" \
  --build-arg "PIP_INDEX_URL=${PIP_INDEX_URL}" \
  -t "${IMAGE}" .

echo "推送镜像 ${IMAGE} ..."
docker push "${IMAGE}"

echo "完成：${IMAGE}"

# 企业微信可信 IP 自动维护 —— 部署指南

给别人（或换一台新机器）部署用的完整说明。**不需要源码，不需要装 Python/Node/Playwright**，只需要 Docker。

> **部署前必须改两处**：`IMAGE`（镜像地址，本文统一写成 `YOUR_DOCKERHUB/wxip:latest`，
> 换成自己的 Docker Hub 地址）和 `APP_SECRET_KEY`（面板会话密钥，随机生成）。

---

## 1. 这个东西做什么

定时从 iKuai 路由器读取当前公网 IP，然后用企业微信管理后台的登录态，把这个 IP **覆盖**写入你所有企业微信自建应用的「企业可信 IP」，只保留最新一条。适合家宽/动态公网 IP 又需要给企业微信 API 配白名单的场景。

面板里可以看到当前公网 IP、每个应用的覆盖结果、同步历史，并手动触发同步。

---

## 2. 部署前必须满足的条件

### 2.1 机器

| 项目 | 要求 |
| --- | --- |
| 系统 | Linux x86_64（Windows/macOS 装 Docker Desktop 也可以） |
| Docker | 20.10 以上，且带 **Docker Compose v2**（`docker compose version` 有输出） |
| 磁盘 | 至少留 6 GB（镜像解压后 3.73 GB，加上数据） |
| 内存 | 至少 1.5 GB 可用（容器内要跑 Chromium） |

### 2.2 网络（三条硬性要求，缺一不可）

| 要能访问 | 为什么 | 自检命令 |
| --- | --- | --- |
| iKuai 的 Web 管理地址（内网 IP，如 `http://192.168.1.1`） | 读取 WAN 公网 IP | `curl -s -o /dev/null -w '%{http_code}\n' http://192.168.1.1/` |
| `work.weixin.qq.com` | 扫码登录企业微信后台、写入可信 IP | `curl -s -o /dev/null -w '%{http_code}\n' https://work.weixin.qq.com/` |
| Docker Hub（或配置镜像加速） | 拉取镜像 | `docker pull hello-world` |

> 部署机器必须和 iKuai 在同一网络（或已通过 VPN/隧道打通）。放在云服务器上、又连不到那台 iKuai，是读不到公网 IP 的。

### 2.3 账号与权限

- **企业微信管理员账号**：能扫码登录管理后台（`work.weixin.qq.com/wework_admin`），并且能修改自建应用的可信 IP；
- **iKuai 的 Web 登录账号密码**。

---

## 3. 需要哪些文件

最少只需要 **2 个文件**：

| 文件 | 是否必需 | 说明 |
| --- | --- | --- |
| `compose.yaml` | ✅ 必需 | 定义容器、端口、数据卷、健康检查 |
| `.env` | ✅ 必需 | 放 `APP_SECRET_KEY` 等变量（可从 `.env.example` 复制改名） |
| `.env.example` | 可选 | 配置模板，方便复制 |
| `trusted-ip-template.json` | 可选 | 已经验证可用的可信 IP 请求模板，有了它可以跳过"录制 cURL"这一步 |
| 源码 | ❌ 不需要 | 镜像里已经包含后端与前端 |

如果目标机器能上网、你也不想拷文件，直接用第 4 节的一段命令块即可，连文件都不用手动创建。

---

## 4. 部署（在目标机器上执行）

### 4.1 一条命令块（推荐）

````bash
set -euo pipefail

APP_DIR=/opt/wecom-trusted-ip
mkdir -p "$APP_DIR/data"
cd "$APP_DIR"

if command -v openssl >/dev/null 2>&1; then
  SECRET=$(openssl rand -hex 32)
else
  SECRET=$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')
fi

cat > compose.yaml <<'YAML'
name: wecom-trusted-ip

services:
  trusted-ip:
    image: "${IMAGE:-YOUR_DOCKERHUB/wxip:latest}"
    container_name: wecom-trusted-ip
    restart: unless-stopped
    ports:
      - "${PANEL_BIND:-0.0.0.0}:8000:8000"
    environment:
      APP_SECRET_KEY: "${APP_SECRET_KEY:?请先在 .env 里设置 APP_SECRET_KEY}"
      APP_DATA_DIR: "/data"
      APP_AUTO_SYNC_ENABLED: "${APP_AUTO_SYNC_ENABLED:-true}"
      APP_SYNC_INTERVAL_SECONDS: "${APP_SYNC_INTERVAL_SECONDS:-300}"
      APP_BROWSER_HEADLESS: "${APP_BROWSER_HEADLESS:-true}"
      APP_BROWSER_CHANNEL: ""
      TZ: "${TZ:-Asia/Shanghai}"
    volumes:
      - "${DATA_DIR:-./data}:/data"
    shm_size: "512m"
YAML

cat > .env <<EOF
APP_SECRET_KEY=$SECRET
PANEL_BIND=0.0.0.0
DATA_DIR=$APP_DIR/data
TZ=Asia/Shanghai
APP_SYNC_INTERVAL_SECONDS=300
APP_AUTO_SYNC_ENABLED=true
EOF

docker compose config | grep -A2 "type: bind"   # 确认数据目录解析正确
docker compose up -d
docker compose ps
````

启动后打开 `http://<目标机器IP>:8000`，会进入「创建管理员账号」。

### 4.2 用拷贝文件的方式

把 `compose.yaml`、`.env.example`（可选 `trusted-ip-template.json`）拷到目标机器 `/opt/wecom-trusted-ip/`，然后：

```bash
cd /opt/wecom-trusted-ip
cp .env.example .env
sed -i "s/^APP_SECRET_KEY=.*/APP_SECRET_KEY=$(openssl rand -hex 32)/" .env
mkdir -p /opt/wecom-trusted-ip/data
sed -i "s#^DATA_DIR=.*#DATA_DIR=/opt/wecom-trusted-ip/data#" .env
docker compose up -d
```

### 4.2.1 群晖 Container Manager / 宝塔面板（粘贴 compose）

面板自带的 compose 编辑器用的是 Go 解析器，对缩进极其敏感：从聊天窗口复制粘贴时只要丢一行，就会报
`'services[trusted-ip].healthcheck' expected a map or struct, got "string"`。

这类环境请用 **`compose.panel.yaml`**：它不含 `${变量}`、不含 `healthcheck`/`logging` 嵌套块，所有值写死，粘贴最不容易出错。

**群晖 DSM 7.x 操作步骤**

1. File Station 里先建目录：`/volume1/docker/wecom-trusted-ip/data`
2. 打开 **Container Manager → 项目 → 新增**
   - 项目名称：`wecom-trusted-ip`
   - 路径：`/volume1/docker/wecom-trusted-ip`
   - 来源：选「创建 compose.yaml」
3. 把 `compose.panel.yaml` 的内容整段粘进去，改两处：
   - `APP_SECRET_KEY` → 换成随机字符串
   - `volumes` → `/volume1/docker/wecom-trusted-ip/data:/data`（按你的实际路径）
4. 下一步 → 完成，等待容器运行
5. 浏览器访问 `http://<群晖IP>:8000`

> 群晖如果拉不动 Docker Hub：Container Manager → 注册表 → 设置 → 新增镜像源 `https://docker.m.daocloud.io`，或者用 SSH 登录后 `sudo docker pull` 再建项目。
> 想用命令行：控制面板开启 SSH，`sudo -i` 后 `cd /volume1/docker/wecom-trusted-ip && docker compose up -d`。

### 4.3 拉不动 Docker Hub 时

**A. 配镜像加速（推荐）**

```bash
cat > /etc/docker/daemon.json <<'EOF'
{ "registry-mirrors": ["https://docker.m.daocloud.io"] }
EOF
systemctl daemon-reload && systemctl restart docker
docker compose pull
```

**B. 走镜像站再打回原标签**

```bash
docker pull docker.m.daocloud.io/YOUR_DOCKERHUB/wxip:latest
docker tag  docker.m.daocloud.io/YOUR_DOCKERHUB/wxip:latest YOUR_DOCKERHUB/wxip:latest
docker compose up -d
```

**C. 内网离线导入**

```bash
# 有网的机器
docker pull YOUR_DOCKERHUB/wxip:latest
docker save YOUR_DOCKERHUB/wxip:latest | gzip > wxip-image.tar.gz   # 约 1.0 GB

# 拷到目标机器后
gunzip -c wxip-image.tar.gz | docker load
docker compose up -d
```

### 4.4 配置项说明

| 变量 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- |
| `APP_SECRET_KEY` | ✅ | 无 | 面板会话签名密钥，**必须**换成随机串；没配会直接报错拒绝启动 |
| `PANEL_BIND` | | `0.0.0.0` | 监听地址。用 Nginx/宝塔反代 + HTTPS 时填 `127.0.0.1` |
| `DATA_DIR` | | `./data` | 数据目录（宿主机路径），建议固定绝对路径 |
| `APP_SYNC_INTERVAL_SECONDS` | | `300` | 自动检查间隔（秒） |
| `APP_AUTO_SYNC_ENABLED` | | `true` | 是否启用自动同步 |
| `TZ` | | `Asia/Shanghai` | 日志时区 |
| `APP_BROWSER_CHANNEL` | ❌ 不要改 | 空 | 必须留空，容器里用的是镜像自带的 Chromium |

### 4.5 关于 healthcheck 与日志轮转

`compose.yaml` 里**没有**写 `healthcheck` 和 `logging` 两个块，这是刻意为之：

- 健康检查由**镜像自带的 HEALTHCHECK**提供，`docker compose ps` 照样显示 `healthy`，不需要在 compose 里重复配置；
- 这两块是多层嵌套结构，从聊天窗口或某些面板编辑器复制粘贴时，只要丢一行（例如 `test:` 或 `driver:`），YAML 就会把它解析成字符串，报出类似
  `'services[trusted-ip].healthcheck' expected a map or struct, got "string"` 的错误；
- 需要限制日志占用时，把文件末尾那三行注释取消即可。

**建议用 scp 或文件管理器传文件，不要从聊天窗口复制粘贴**；粘贴后先执行 `docker compose config`，能正常打印配置再 `up -d`。

---

## 5. 首次配置（浏览器里 5 步）

1. **创建管理员账号**：自定义用户名 + 密码（至少 8 位）。这个账号只用于登录面板。
2. **iKuai 页**：填管理地址（如 `http://192.168.1.1`）、用户名、密码 → 点「测试并读取公网 IP」。读不到就点「探测原始响应」把结果发给维护者适配固件。
3. **企业微信页 → 重新扫码登录**：用企业微信管理员扫码。扫码只是拿"写可信 IP"的权限，和面板账号无关。
4. **自动发现应用**：会列出你所有的自建应用（系统内置应用会被自动排除）。失败时可以用「每行 `agentid,应用名,控制台应用编号`」手工导入。
5. **可信 IP 写入模板**：
   - **省事方式**：把 `trusted-ip-template.json` 的内容粘贴到面板的「模板 JSON」框，点「保存模板」；
   - **通用方式**（企业微信后台改版后用这个）：在管理后台手动改一次任意应用的可信 IP，用浏览器开发者工具对该请求 → 复制 → **Copy as cURL**，粘贴到面板「粘贴 cURL」→ 解析 → 保存。

   模板里必须出现两个占位符：`{ip}`（要写入的公网 IP）和 `{app_id}` 或 `{agent_id}`（应用编号）。保存时面板会校验，缺 `{ip}` 会直接报错。
6. **当前可信 IP 不用额外配置**：同步时会从企业微信「应用管理页」的列表响应里自动读取每个应用当前
   的可信 IP（写入后还会回读校验）。只有默认读取失败时，才需要在面板「企业微信」页的
   「备用读取模板（可选）」区块里录一个查询请求兜底。
7. 回仪表盘点「立即同步」，确认应用表格里的「当前可信 IP」已变成最新公网 IP，再按需保持自动同步开启。

---

## 6. 验证部署是否正常

```bash
docker compose ps                      # STATUS 应为 Up (healthy)
curl -s http://127.0.0.1:8000/api/health   # {"status":"ok"}
docker logs --tail 30 wecom-trusted-ip
```

面板「同步日志」里应能看到成功记录。最彻底的验证是等公网 IP 变化一次（家宽重拨），看是否自动出现一轮「已覆盖 N/N」。

---

## 7. 日常运维

```bash
docker compose pull && docker compose up -d     # 升级到最新镜像
docker compose logs -f                          # 看日志
docker compose restart                          # 重启（企业微信登录态会失效，需要重新扫码）
docker compose down                             # 停止并删除容器，数据保留在 DATA_DIR
```

### 7.1 忘记面板管理员账号/密码（容器环境）

容器里**没有宿主机上的 Python 环境**，所以不能直接在 NAS/服务器上敲 `python -m app.cli`，
要**进到容器里执行**——用 `docker exec`（它会带上容器的 `APP_DATA_DIR=/data`，操作的正是那个映射出来的数据库）：

```bash
# 看当前有哪些管理员用户名
docker exec -it wecom-trusted-ip python -m app.cli list-admins

# 忘记密码：直接重设（会交互式提示输入新密码）
docker exec -it wecom-trusted-ip python -m app.cli set-password --username admin
# 不想交互式，也可以一次写完（密码会出现在命令里）
docker exec wecom-trusted-ip python -m app.cli set-password --username admin --password '新密码至少8位'

# 用户名和密码都忘了：清空账号，重新打开面板会进「创建管理员账号」页面
docker exec -it wecom-trusted-ip python -m app.cli reset-admin
```

**群晖 Container Manager（不想开 SSH）**：容器 → 选中 `wecom-trusted-ip` → 详情 → 终端机 → 新增 `bash` → 在打开的终端里输入

```bash
python -m app.cli reset-admin
```

（在容器终端里不需要 `docker exec` 前缀，`-it` 也不用写。）

**容器已经停了**（不想为改密码启动它）：用一次性容器挂同一个数据卷执行，例如：

```bash
docker run --rm -v /volume1/docker/wecom-trusted-ip/data:/data -e APP_DATA_DIR=/data \
  --entrypoint python YOUR_DOCKERHUB/wxip:latest -m app.cli reset-admin
```

**两个常见误区**：

1. 在群晖/服务器宿主机上直接跑 `python -m app.cli ...` → 宿主机没有这套代码，只会报 command not found；必须在容器内执行。
2. 用一次性容器但**忘了挂数据卷**（或挂错路径）→ 它操作的是一份全新的空数据库，命令执行成功但完全没有效果；一定要把真实的 `DATA_DIR` 挂到 `/data`。

**备份**（数据全在宿主机 `DATA_DIR`）：

```bash
tar -czf wxip-data-$(date +%F).tar.gz -C /opt/wecom-trusted-ip data
```

**换机器**：新机器按本文部署好，把旧的 `data/` 目录内容拷到新机器的 `DATA_DIR` 即可保留配置与登录态（企业微信登录态本来也要重扫）。

---

## 8. 安全建议

1. **不要把 8000 端口直接暴露到公网**：面板登录是 HTTP 明文传密码。用 `PANEL_BIND=127.0.0.1` + Nginx/宝塔反向代理并配置 HTTPS。
2. `APP_SECRET_KEY` 必须是随机值，且每套部署各不相同。
3. `DATA_DIR` 里有 iKuai 密码、企业微信登录态和面板密码哈希，权限建议 `chmod 700`。
4. 不要把 `DATA_DIR` 放在 NFS/SMB 网络盘上（SQLite 的 WAL 在网络文件系统上不可靠）。

---

## 9. 常见问题

| 现象 | 原因与处理 |
| --- | --- |
| 校验报 `expected a map or struct, got "string"` | 复制过程中 YAML 缩进丢失。用 `compose.yaml` 原文件传输，或在目标机上按 4.1 的 heredoc 重新生成，然后用 `docker compose config` 校验 |
| `docker compose up` 报 `required variable APP_SECRET_KEY is missing` | 没有 `.env` 或里面没填 `APP_SECRET_KEY`，按 4.1 重新生成 |
| 拉镜像卡住/超时 | 国内网络问题，按 4.3 配镜像加速或离线导入 |
| 8000 端口起不来 | 端口被占用，改 `.env` 的 `PANEL_BIND` 或 compose 里的端口映射 |
| 面板提示「企业微信管理后台尚未登录」 | 需要重新扫码；**每次容器/服务重启后都要重扫一次**（企业微信登录态不落盘） |
| 自动发现应用失败 | 看 `DATA_DIR/wecom_discover_debug.json`，里面有页面信息和抓到的响应摘要；把它发给维护者适配 |
| 同步报「模板需要 {app_id}」 | 该应用缺少"控制台应用编号"，在企业微信页的应用表格里补填（16 位数字，取自后台地址栏 `#apps/modApiApp/<编号>`） |
| iKuai 报 `Post data error` | 老版本已修复；升级到最新镜像（v0.1.0 起支持 JSON 报文登录） |
| 同步显示「公网 IP 未变化，自动同步已跳过」 | 只在还没有应用清单时出现；正常配置下每轮都会核对真实状态 |
| 「当前可信 IP」一直显示未知 | 说明默认读取没成功。先在容器里跑 `docker exec -it wecom-trusted-ip python -m app.cli check-trusted-ips`，它会逐条打印每个应用读到什么，以及读不到的原因 |
| 同步报「企业微信返回了登录页，登录态已失效」 | 你（或同事）在企业微信官网/手机端重新扫码，把容器里的会话挤下线了；到面板「企业微信」页重新扫码登录即可 |
| 同步报「返回的是网页而不是接口 JSON」 | 该请求没有落到真正的后台接口上，通常是模板录错（比如复制成了页面请求）或企业微信改版，重新录制对应模板 |
| 同步报「写入已提交，但回读校验不通过」 | 后台接受了写入、但再读回来仍是旧值。先点一次「立即同步」重试；若持续出现，把该应用在企业微信后台的「企业可信IP」截图发给维护者 |
| 想看当前公网 IP | 面板仪表盘首页，或 iKuai 页点「测试并读取公网 IP」 |
| 想知道企业微信里现在配的是哪个可信 IP | 仪表盘点「获取当前可信 IP」（只读，不发写入请求）；开启自动同步后每轮也会自动读取一次，「当前可信 IP」列旁边会显示读取时间 |
| 关掉自动同步后还会发请求吗 | 会，但只发**只读**的读取请求（默认每 300 秒一轮），用来刷新面板上的「当前可信 IP」；不会自动修改企业微信里的配置 |

---

## 10. 镜像信息

| 项目 | 值 |
| --- | --- |
| 镜像地址 | 你自己构建并推送的地址，例如 `docker.io/YOUR_DOCKERHUB/wxip:latest` |
| Digest | `sha256:69715235ecd565b9f3c95141daa81481573b9a79e1cd304d144646cb3a540674` |
| 压缩体积 | 约 1028 MB |
| 解压体积 | 3.73 GB |
| 基础镜像 | `mcr.microsoft.com/playwright/python:v1.63.0-noble`（自带 Chromium 153） |
| 架构 | linux/amd64 |

---

## 11. 卸载

```bash
cd /opt/wecom-trusted-ip
docker compose down
docker rmi YOUR_DOCKERHUB/wxip:latest
rm -rf /opt/wecom-trusted-ip       # 注意：这会连同数据一起删除
```

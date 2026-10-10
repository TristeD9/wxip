# 企业微信可信 IP 自动维护

定时从 iKuai 路由器读取当前公网 IP，并用企业微信管理后台的登录态，把这个 IP **覆盖**写入
你所有的企业微信自建应用的「企业可信 IP」，只保留最新一条。

镜像自带 Chromium，部署机不需要装 Python / Node / Playwright。文中镜像地址统一写成
`YOUR_DOCKERHUB/wxip:latest`，请替换成你自己构建并推送的镜像（见 3.3 与 九）。

---

## 一、解决什么问题

企业微信的自建应用要调用服务端接口，必须把调用方的公网 IP 加进该应用的「企业可信 IP」白名单。
在家庭宽带 / 动态 IP 环境里这个地址会不定期变化，变了之后：

- 接口开始报 IP 不在白名单之类的错误，业务中断；
- 要登录管理后台，**逐个应用**手工改，应用多了很烦；
- 忘了改，就会在半夜出故障。

本项目把这件事自动化：每隔一段时间读一次 iKuai 的 WAN 公网 IP，只要发生变化，就把**所有自建应用**
的可信 IP 批量覆盖成新地址，并在面板里留下每个应用的处理结果。

> **为什么是"重放管理后台请求"而不是调接口？**
> 企业微信**没有**开放"修改自建应用可信 IP"的服务端接口。因此本项目用 Playwright 驱动管理后台
> 完成扫码登录，再把你手动录制一次的保存请求做成模板，同步时逐个应用重放。
> 这与后台页面结构有关，企业微信改版后需要重新录制一次模板（面板里点几下即可）。

## 二、主要功能

| 功能 | 说明 |
| --- | --- |
| 扫码登录企业微信 | 后端启动 Chromium 打开管理后台登录页，把二维码投到面板，手机扫码后登录态保存在服务端 |
| 读取 iKuai 公网 IP | 登录 iKuai Web 读取 WAN 口地址；兼容 JSON / 表单两种登录报文与多个 WAN 查询函数 |
| 公网 IP 兜底 | iKuai 读取失败时自动回退外部回显服务（api.ipify.org、ipv4.icanhazip.com、ifconfig.me） |
| 自动发现自建应用 | 从管理后台抓取应用清单，自动排除系统内置应用（通讯录同步助手、外部联系人等）与腾讯官方应用 |
| 双编号支持 | 同时保存 `agentid`（7 位）与管理后台内部应用编号 `app_id`（十几位），模板里分别用 `{agent_id}` / `{app_id}` |
| 请求模板解析 | 粘贴浏览器复制的 cURL（bash 或 cmd 格式）自动生成模板，也可直接粘贴现成模板 JSON |
| 覆盖式同步 | 把最新公网 IP 覆盖写入所有自建应用，只保留最新一条；逐应用记录成功/失败 |
| 定时自动同步 | 按配置间隔**全量重写**（默认 300 秒）：每次都用最新公网 IP 覆盖所有自建应用，不判断 IP 是否变化 |
| 同步历史 | 面板保留最近 100 次同步记录，含每个应用的明细 |
| 面板管理员账号 | 首次部署创建本地管理员账号，支持修改密码；连续登录失败 5 次锁定 5 分钟 |
| 忘记账号找回 | 提供运维命令 `list-admins` / `set-password` / `reset-admin`，容器内执行 |
| 凭据脱敏 | iKuai 的 WAN 响应里含 PPPoE 账号密码，探测接口返回前会递归替换为 `***` |

## 三、安装（Docker Compose）

### 3.1 前置条件

| 项目 | 要求 |
| --- | --- |
| 机器 | Linux x86_64（VPS / 群晖等 NAS 均可）；Windows/macOS 装 Docker Desktop 也行 |
| Docker | 20.10+ 且带 Compose v2（`docker compose version` 有输出） |
| 磁盘 | 2 GB 可用足够（镜像解压后约 1.25 GB） |
| 内存 | 至少 1.5 GB 可用（容器内要跑 Chromium） |
| 网络 | ① 能访问 iKuai 管理地址 ② 能访问 `work.weixin.qq.com` ③ 能拉 Docker Hub |
| 账号 | 企业微信管理员（能扫码进后台、能改可信 IP）+ iKuai Web 账号密码 |

网络自检：

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://192.168.1.1/            # iKuai 能通
curl -s -o /dev/null -w '%{http_code}\n' https://work.weixin.qq.com/    # 企业微信能通
docker compose version
```

> 部署机器必须与 iKuai 在同一网络（或已通过 VPN 打通），否则读不到公网 IP。

### 3.2 直接使用（推荐）

把下面这份 `compose.yaml` 存到目标机器，例如 `/opt/wecom-trusted-ip/compose.yaml`：

```yaml
name: wecom-trusted-ip

services:
  trusted-ip:
    image: tristed9/wxip:latest                 # 换成你自己的镜像地址
    container_name: wecom-trusted-ip
    restart: unless-stopped
    ports:
      - "8000:8000"                             # 宿主机端口冲突时改左边，例如 "8943:8000"
    environment:
      APP_SECRET_KEY: "你的自定义"                # 必改：随机字符串，例如 openssl rand -hex 32
      APP_DATA_DIR: "/data"                     # 容器内路径，默认即可
      APP_AUTO_SYNC_ENABLED: "true"
      APP_SYNC_INTERVAL_SECONDS: "300"
      APP_BROWSER_HEADLESS: "true"
      APP_BROWSER_CHANNEL: ""
      TZ: "Asia/Shanghai"
    volumes:
      - "/opt/wecom-trusted-ip/data:/data"      # 冒号左边是宿主机路径，改成你自己的
    shm_size: "512m"
```

启动后浏览器访问 `http://<机器IP>:8000`；端口冲突时改 compose 里的宿主机端口（例如 `8943:8000`），访问地址随之变化。

### 3.3 或者用现成文件

`outputs/deploy/` 里提供了直接可用的文件（项目根目录也有等价的 `compose.yaml` + `.env.example`）：

| 文件 | 用途 |
| --- | --- |
| `outputs/deploy/compose.yaml` | 通用版，用 `.env` 变量，`APP_SECRET_KEY` 未配置会直接报错 |
| `outputs/deploy/compose.panel.yaml` | 群晖 Container Manager / 宝塔等面板粘贴版，无变量、无嵌套块 |
| `outputs/deploy/.env.example` | 配置模板 |
| `outputs/deploy/trusted-ip-template.json` | 已验证可用的请求模板，粘贴即省掉录制步骤 |
| `outputs/deploy/README.md` | 更详细的部署指南（含群晖步骤、离线导入、FAQ） |

```bash
cd /opt/wecom-trusted-ip
cp .env.example .env
sed -i "s/^APP_SECRET_KEY=.*/APP_SECRET_KEY=$(openssl rand -hex 32)/" .env
sed -i "s#^IMAGE=.*#IMAGE=你的DockerHub用户名/wxip:latest#" .env   # 镜像地址改成你自己的
docker compose up -d
```

> 镜像地址在本文里统一写成 `YOUR_DOCKERHUB/wxip:latest`。你需要先把自己的镜像推到 Docker Hub
> （构建命令见第九节），再把 `IMAGE` 改成实际地址；`compose.yaml` 与 `compose.panel.yaml`
> 里也各有一处镜像地址需要替换。

### 3.4 群晖 Container Manager / 宝塔面板

面板的 compose 编辑器用 Go 解析 YAML，对缩进敏感，请用 **`compose.panel.yaml`** 粘贴：

1. File Station 建目录 `/volume1/docker/wecom-trusted-ip/data`
2. **Container Manager → 项目 → 新增**：名称 `wecom-trusted-ip`，路径 `/volume1/docker/wecom-trusted-ip`，来源选「创建 compose.yaml」
3. 粘贴 `compose.panel.yaml`，改两处：`APP_SECRET_KEY` 换成随机串、`volumes` 改成 `/volume1/docker/wecom-trusted-ip/data:/data`
4. 完成后访问 `http://<群晖IP>:8000`

> 注意：`APP_DATA_DIR: "/data"` 是**容器内**路径，保持不变；要改的是 `volumes` 冒号**左边**的宿主机路径。

### 3.5 拉不动 Docker Hub 时

```bash
# A. 配镜像加速（推荐）
cat > /etc/docker/daemon.json <<'EOF'
{ "registry-mirrors": ["https://docker.m.daocloud.io"] }
EOF
systemctl daemon-reload && systemctl restart docker
docker compose pull

# B. 走镜像站再打回原标签
docker pull docker.m.daocloud.io/YOUR_DOCKERHUB/wxip:latest
docker tag  docker.m.daocloud.io/YOUR_DOCKERHUB/wxip:latest YOUR_DOCKERHUB/wxip:latest

# C. 完全离线
docker save YOUR_DOCKERHUB/wxip:latest | gzip > wxip-image.tar.gz   # 约 0.4 GB
# 目标机器：gunzip -c wxip-image.tar.gz | docker load
```

### 3.6 容器环境变量

| 变量 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `APP_SECRET_KEY` | ✅ | 无 | 面板会话签名密钥，必须换成随机串（`openssl rand -hex 32`） |
| `PANEL_BIND` | | `0.0.0.0` | 面板监听地址；走反向代理加 HTTPS 时填 `127.0.0.1` |
| `DATA_DIR` | | `./data` | 宿主机数据目录（compose 变量，映射到容器 `/data`） |
| `APP_DATA_DIR` | | `/data` | **容器内**数据路径，不要改 |
| `APP_SYNC_INTERVAL_SECONDS` | | `300` | 自动同步间隔（秒） |
| `APP_AUTO_SYNC_ENABLED` | | `true` | 是否启用自动同步 |
| `APP_BROWSER_HEADLESS` | | `true` | 无头模式；容器内保持 true |
| `APP_BROWSER_CHANNEL` | | 空 | **必须留空**（容器用镜像自带的 Chromium；本机调试才填 `chrome`） |
| `TZ` | | `Asia/Shanghai` | 时区 |

### 3.7 验证安装

```bash
docker compose ps                              # STATUS 应为 Up (healthy)
curl -s http://127.0.0.1:8000/api/health       # {"status":"ok"}
docker exec -it wecom-trusted-ip python -m app.cli list-admins   # 首次应为空
```

## 四、使用方法

### 4.1 首次配置（浏览器里 5 步）

1. **创建管理员账号**：打开 `http://<机器IP>:8000`，第一次会进入「创建管理员账号」，设置用户名和
   密码（至少 8 位）。这个账号只用于登录面板，与企业微信无关。
2. **配置 iKuai**：进入「iKuai」页 → 填管理地址（如 `http://192.168.1.1`）、用户名、密码 →
   点「测试并读取公网 IP」。失败时点「探测原始响应」，把返回发给维护者按固件适配。
3. **扫码登录企业微信**：进入「企业微信」页 → 点「重新扫码登录」→ 用企业微信管理员手机扫码。
   （扫码是为了拿"写可信 IP"的权限，和面板账号无关。）
4. **自动发现应用**：点「自动发现应用」，会列出所有自建应用（系统内置应用自动排除），并自动带上
   AgentId 与控制台应用编号，不需要手工维护清单。
5. **配置「可信 IP 写入模板」**（两种方式任选其一）：
   - **省事**：把 `outputs/deploy/trusted-ip-template.json` 的内容粘到「模板 JSON」框 → 保存模板；
   - **通用**（企业微信改版后用）：在管理后台手动改一次任意应用的可信 IP，用开发者工具对该请求
     右键 → Copy → **Copy as cURL** → 粘到面板「粘贴 cURL」→ 解析 → 保存。

   模板里必须出现 `{ip}`（要写入的公网 IP）和 `{app_id}` 或 `{agent_id}`（应用编号），
   缺少 `{ip}` 时面板会直接拒绝保存。

6. 回仪表盘点「立即同步」，确认日志出现「已覆盖 N/N 个应用的可信 IP」，再按需保持自动同步开启。

### 4.2 日常使用

配置完成后基本不用管：默认每 5 分钟把最新公网 IP 覆盖写入所有自建应用一遍（不判断 IP 是否变化）；
想立刻重写就点一次「立即同步」。

| 页面 | 能做什么 |
| --- | --- |
| 仪表盘 | 当前公网 IP、应用覆盖情况、手动「立即同步」、开关自动同步与调整间隔 |
| 企业微信 | 扫码登录、自动发现应用（含 AgentId 与控制台应用编号）、配置可信 IP 写入模板 |
| iKuai | 连接配置、测试并读取公网 IP、探测原始响应 |
| 同步日志 | 最近 100 次同步记录，可展开查看每个应用的成功/失败与原因 |
| 账号 | 显示当前管理员、修改密码、忘记密码的找回说明 |

### 4.3 运维

```bash
docker compose pull && docker compose up -d     # 升级镜像
docker compose logs -f                          # 查看日志
docker compose restart                          # 重启（企业微信登录态失效，需重新扫码）
docker compose down                             # 停止（数据保留在 DATA_DIR）

# 忘记面板账号/密码（必须在容器内执行）
docker exec -it wecom-trusted-ip python -m app.cli list-admins
docker exec -it wecom-trusted-ip python -m app.cli set-password --username admin
docker exec -it wecom-trusted-ip python -m app.cli reset-admin    # 清空后重开初始化页

# 备份
tar -czf wxip-data-$(date +%F).tar.gz -C /opt/wecom-trusted-ip data
```

## 五、输入输出示例

### 5.1 输入

| 输入项 | 在哪里填 | 示例 |
| --- | --- | --- |
| 面板管理员 | 首次打开的创建页 | 用户名 `admin` / 密码 `MyPassw0rd!` |
| iKuai 连接 | 面板「iKuai」页 | 地址 `http://192.168.1.1`、用户名 `admin`、密码 `********` |
| 企业微信登录 | 面板「企业微信」页 | 手机扫码（二维码由服务端截图返回） |
| 应用清单 | 「企业微信」页点自动发现 | 自动读取，例如 `1230002,示例应用,5629500000000002` |
| 请求模板 | 粘贴 cURL 或模板 JSON | 见 5.3 |
| 同步策略 | 面板「仪表盘」 | 自动同步开、间隔 `300` 秒 |

### 5.2 输出

面板上会看到：

- 仪表盘：当前公网 IP（含来源与观测时间）、自建应用总数、已覆盖数量、最近一次同步状态；
- 应用表格：`应用名称` / `AgentId` / `最近覆盖 IP` / `状态` / `覆盖时间` / `最近错误`；
- 同步日志：`完成时间 / 公网 IP / 结果 / 说明`，可展开每个应用的明细。

接口返回示例（服务端真实返回；除健康检查与登录外，都需要 `Authorization: Bearer <token>`）：

```jsonc
// GET /api/health
{"status": "ok"}

// POST /api/ikuai/test —— 读取公网 IP
{"ok": true, "public_ip": "223.5.5.5"}

// POST /api/sync/run —— 同步结果
{
  "started_at": "2026-10-03T09:03:50.123456Z",
  "finished_at": "2026-10-03T09:03:52.987654Z",
  "public_ip": "223.5.5.5",
  "status": "ok",
  "message": "已覆盖 2/2 个应用的可信 IP",
  "results": [
    {
      "agent_id": "1230002",
      "name": "示例应用",
      "success": true,
      "message": "已覆盖为 223.5.5.5",
      "updated": true
    },
    {
      "agent_id": "1230003",
      "name": "报表系统",
      "success": true,
      "message": "已覆盖为 223.5.5.5",
      "updated": true
    }
  ]
}
// status 取值：ok（全部覆盖成功）/ failed（有失败或前置条件缺失）

// POST /api/ikuai/probe —— 探测原始响应（凭据已脱敏）
{
  "probes": [
    {
      "request_name": "wan(TYPE=total,data)",
      "ok": true,
      "payload": {
        "Result": 30000,
        "Data": {"data": [{"pppoe_ip_addr": "223.5.5.5", "username": "***", "passwd": "***"}]}
      }
    }
  ]
}
```

### 5.3 请求模板：输入 cURL → 输出模板

**输入**（浏览器复制，bash 与 cmd 格式都支持）：

```
curl 'https://work.weixin.qq.com/wework_admin/apps/saveIpConfig?lang=zh_CN' \
  -H 'content-type: application/x-www-form-urlencoded' \
  --data-raw 'app_id=5629500000000002&ipList%5B%5D=223.5.5.5'
```

**输出**（面板解析结果，确认后可保存为模板）：

```json
{
  "method": "POST",
  "url": "https://work.weixin.qq.com/wework_admin/apps/saveIpConfig?lang=zh_CN",
  "headers": {"content-type": "application/x-www-form-urlencoded"},
  "body": "app_id={app_id}&ipList%5B%5D={ip}"
}
```

同步时把 `{app_id}` 替换成该应用的控制台应用编号、`{ip}` 替换成最新公网 IP。
因为 `ipList%5B%5D`（即 `ipList[]`）里只放一个值，所以结果就是"只保留最新 IP"。

## 六、接口概览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查 |
| GET | `/api/auth/setup/status` | 是否已创建管理员 |
| POST | `/api/auth/setup` | 首次创建管理员 |
| POST | `/api/auth/login` | 管理员登录 |
| POST | `/api/auth/password` | 修改密码 |
| GET | `/api/auth/me` | 当前登录管理员 |
| POST / GET | `/api/auth/wecom/login` | 生成企业微信二维码 / 查询扫码状态 |
| GET | `/api/state` | 仪表盘聚合状态 |
| GET / PUT | `/api/ikuai/settings` | iKuai 连接配置 |
| POST | `/api/ikuai/test` | 测试连接并读取公网 IP |
| POST | `/api/ikuai/probe` | 各 WAN 查询方式的原始响应（脱敏） |
| GET | `/api/wecom/apps` | 已保存的应用清单 |
| POST | `/api/wecom/apps/discover` | 自动发现自建应用 |
| PUT | `/api/wecom/apps/manual` | 手工导入应用清单（API 兜底，界面已不再提供入口） |
| PUT | `/api/wecom/apps/{agent_id}/console-app-id` | 补录控制台应用编号（API 兜底） |
| GET / PUT | `/api/wecom/apps-url` | 应用管理页地址（后台改版时调整） |
| GET / PUT | `/api/wecom/template` | 可信 IP 写入模板 |
| POST | `/api/wecom/template/parse` | 解析 cURL 生成写入模板预览 |
| GET / PUT | `/api/sync/settings` | 自动同步设置 |
| POST | `/api/sync/run` | 立即同步（无需请求体）：用最新公网 IP 覆盖全部自建应用 |
| GET | `/api/sync/events` | 同步历史 |

## 七、已知限制

- **依赖管理后台页面结构**：写入靠重放录制的请求，企业微信改版后需重新录制模板；
- **"已覆盖"来自写入结果**：同步不读回企业微信里的真实值，判定依据是写入请求的返回（HTTP 状态 +
  `errcode`）；若企业微信改版导致返回体不再带 `errcode`，需要按新结构适配；
- **登录态会被挤下线**：登录态保存在 `DATA_DIR/wecom_state.json` 并会在重启后复用，但在企业微信
  官网/手机端重新登录会把容器里的会话挤掉；此时同步会明确报"登录态已失效"，重新扫码即可；
- **同一账号单会话**：在企业微信官网/手机端重新扫码登录，会把容器里的会话挤下线。此时同步会明确
  报"登录态已失效，请重新扫码登录"（不会静默成功），在面板「企业微信」页重新扫码即可恢复；
- **需要后台权限**：扫码的账号必须能修改自建应用的可信 IP；
- **公网 IP 来源**：iKuai 解析失败会回退外部回显服务，只有后端与 iKuai 同出口时两者才一致；
- **无头浏览器风控**：若企业微信对无头浏览器弹安全验证，把 `APP_BROWSER_HEADLESS` 设为 `false`
  并在有图形界面的环境运行；
- **镜像体积**：`python:3.12-slim` + 仅 Chromium，解压后约 1.25 GB（旧版用 Playwright 官方镜像，
  解压 3.73 GB、下载约 1.0 GB，现在下载约为旧版的三分之一）；
- **面板账号与企业微信登录互不影响**：改面板密码不影响扫码，反之亦然。

## 八、安全说明

- **不要把 8000 端口直接暴露到公网**：面板登录是 HTTP 明文传密码，建议 `PANEL_BIND=127.0.0.1`
  + Nginx/宝塔反代并配置 HTTPS；
- `APP_SECRET_KEY` 必须使用随机值，且每套部署各不相同；
- `DATA_DIR` 内含 iKuai 密码、企业微信登录态与面板密码哈希，建议 `chmod 700`，且**不要**放在
  NFS/SMB 网络盘上（SQLite 的 WAL 在网络文件系统上不可靠）；
- 面板密码用 PBKDF2-HMAC-SHA256（随机盐、20 万次迭代）存储；连续登录失败 5 次锁定 5 分钟；
- 探测 iKuai 响应时，`username` / `passwd` 等敏感字段会先替换为 `***` 再返回浏览器。

## 九、开发与测试

```powershell
# 后端依赖
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt

# 后端单元测试（当前 149 条）
.\scripts\run_tests.ps1

# 前端单元测试（vitest + jsdom，当前 15 条；首次会自动 npm ci）
.\scripts\run_frontend_tests.ps1

# 本机启动（8000 端口，同时托管前端）
.\scripts\run_backend.ps1

# 构建并推送镜像（国内可换基础镜像源与 PyPI 源）
.\scripts\build_and_push_image.ps1 -Repository <用户名>/<仓库名> -Tag latest `
    -BaseRegistry docker.m.daocloud.io -PipIndexUrl https://pypi.tuna.tsinghua.edu.cn/simple
```

推送代码到 `main`（或提 PR）时，GitHub Actions 会自动跑上面两套测试（`.github/workflows/tests.yml`）；
镜像构建是单独的工作流，只在打 `v*` 标签或手动触发时执行。

## 十、文档索引

| 文档 | 内容 |
| --- | --- |
| `docs/ARCHITECTURE.md` | 分层、数据流与关键设计决策 |
| `docs/PROJECT_STRUCTURE.md` | 目录结构与每个文件/目录的用途 |
| `docs/DEVELOPMENT_LOG.md` | 开发与联调过程记录、踩过的坑、Resume 入口 |
| `outputs/deploy/README.md` | 面向使用者的完整部署指南 |

## 十一、许可证

本项目使用 [MIT License](LICENSE)。

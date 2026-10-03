# 项目结构说明

下文所有路径都相对于项目根目录（也就是你 clone 或解压本项目后所在的目录）。

## 目录一览

```
.
├── backend/                    后端源码（FastAPI + Playwright），唯一的服务端代码
│   ├── app/
│   │   ├── main.py             FastAPI 装配与生命周期
│   │   ├── config.py           环境变量配置
│   │   ├── models.py           数据模型
│   │   ├── storage.py          SQLite 持久化
│   │   ├── security.py         会话令牌
│   │   ├── passwords.py        管理员密码哈希
│   │   ├── login_throttle.py   登录失败节流
│   │   ├── cli.py              运维命令（找回管理员账号）
│   │   ├── api/                REST 接口层
│   │   ├── ikuai/              iKuai 登录与 WAN 解析
│   │   ├── wecom/              企业微信后台自动化与模板处理
│   │   └── services/           IP 解析、同步编排、定时调度
│   ├── tests/                  单元测试（pytest）
│   ├── requirements.txt        运行依赖（锁版本）
│   ├── requirements-dev.txt    含测试依赖
│   ├── pytest.ini / conftest.py
│   └── .pytest-tmp/            测试临时目录（自动生成，可删）
├── frontend/                   前端源码（无构建的原生 ES Module SPA）
│   ├── index.html
│   ├── src/                    路由、页面、API 封装、图标
│   └── styles/main.css
├── scripts/                    脚本
│   ├── run_backend.ps1         本机启动后端
│   ├── run_frontend.ps1        本机单独起前端静态服务
│   ├── run_tests.ps1           跑单元测试
│   ├── install_browser.ps1     非 Docker 部署时安装 Chromium
│   ├── admin_cli.ps1           管理员账号运维（查看/改密/重置）
│   ├── build_and_push_image.ps1 / .sh    构建并推送镜像
├── outputs/
│   └── deploy/                 发给别人的部署包（见该目录 README.md）
│       ├── compose.yaml        通用版
│       ├── compose.panel.yaml  群晖/面板粘贴版（无变量、无嵌套块）
│       ├── .env.example
│       ├── trusted-ip-template.json   已验证可用的请求模板
│       └── README.md           完整部署指南
├── docs/
│   ├── ARCHITECTURE.md         架构与设计决策
│   ├── DEVELOPMENT_LOG.md      逐轮开发/联调记录 + Resume 入口
│   └── PROJECT_STRUCTURE.md    本文件
├── .github/workflows/docker-publish.yml   GitHub Actions 自动构建推送
├── Dockerfile                  镜像定义
├── compose.yaml                本机/服务器部署用 compose
├── README.md                   项目说明与使用文档
├── LICENSE                     MIT 许可证
├── .env                        本机运行配置（含密钥，已被 gitignore）
├── .env.example                配置模板
├── .dockerignore / .gitignore
├── data/                       运行数据（非源码，见下）
├── .venv/                      本机 Python 虚拟环境（非源码，可重建）
└── work/                       临时目录（当前只保留运维用的 SSH 密钥）
```

## 三类内容的区别

| 类别 | 路径 | 是否要保留 | 说明 |
| --- | --- | --- | --- |
| **源码** | `backend/`、`frontend/`、`scripts/`、`docs/`、`outputs/deploy/`、`.github/`、`Dockerfile`、`compose.yaml`、`README.md`、`.env.example` | ✅ 必须 | 项目本体，约 0.2 MB |
| **交付/部署件** | `outputs/deploy/` | ✅ 建议 | 给别人部署用，可直接打包发送 |
| **许可证** | `LICENSE` | ✅ 必须 | MIT License，发布到 GitHub 时一并保留 |
| **运行数据** | `data/` | ⚠️ 看情况 | 本机调试积累的真实数据：iKuai 密码、企业微信登录态、应用清单、请求模板。删掉不影响源码，但本机再跑要重新配置 |
| **本地环境** | `.venv/`（170 MB） | ⚠️ 可删 | 只有本机跑测试/开发才需要，重建命令见下 |
| **运维密钥** | `work/ssh/` | ⚠️ 敏感 | 免密登录部署服务器的私钥，不需要时应删除并吊销服务器上的公钥 |

## 常见操作

```powershell
# 跑单元测试（需要 .venv）
.\scripts\run_tests.ps1

# 本机启动（8000 端口，同时托管前端）
.\scripts\run_backend.ps1

# 重建虚拟环境
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt

# 构建并推送镜像到 Docker Hub
.\scripts\build_and_push_image.ps1 -Repository <用户名>/<仓库名> -Tag latest
```

## 交付给别人时只需要

`outputs/deploy/` 四个文件（`compose.yaml`、`compose.panel.yaml`、`.env.example`、`README.md`、`trusted-ip-template.json`）——对方不需要源码，也不需要 Python/Node/Playwright，只要装好 Docker。

镜像地址写成占位符 `YOUR_DOCKERHUB/wxip:latest`，请替换成你自己构建并推送的镜像；
`compose.yaml` 里通过 `IMAGE` 变量引用，也可以只在 `.env` 里改这一处。

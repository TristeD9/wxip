# 架构说明

## 分层

```text
frontend/                      无构建的原生 ES Module 单页应用
  index.html
  src/app.js                   路由与外壳
  src/pages/*.js               各页面
  src/api.js                   fetch 封装与令牌管理
  styles/main.css

backend/app/
  main.py                      FastAPI 装配与生命周期
  config.py                    环境变量配置
  models.py                    跨模块数据模型
  storage.py                   SQLite 持久化
  security.py                  HMAC 会话令牌
  api/                         REST 接口层
  ikuai/                       iKuai 登录与 WAN 解析
  wecom/                       企业微信后台自动化与模板处理
  services/                    IP 解析、同步编排、定时调度
```

## 数据流

```text
POST /api/sync/run
  SyncService.sync()
    PublicIpResolver.resolve()         # iKuai 优先，外部回显兜底
    storage.record_public_ip()
    storage.get_request_template()
    WeComAdminSession.ensure_logged_in()
    for app in storage.list_wecom_apps():
        WeComAdminSession.replay_request(template, agent_id, ip)
    storage.record_sync_summary()
```

自动同步由 `SyncScheduler` 单任务串行执行；前置条件（iKuai 配置、模板、应用清单）不满足时直接跳过，不会污染同步历史。

## 关键设计决策

### 为什么用管理后台自动化

企业微信服务端 API 没有提供「修改自建应用可信 IP」的公开接口。要在不依赖私有接口的前提下实现需求，只能复用管理后台自身的请求。

### 为什么需要录制一次 cURL

管理后台的内部接口地址、请求体结构会随版本变化。与其硬编码一个可能过期的路径，不如让管理员录制一次真实请求，项目据此生成模板。同步时只替换 `{agent_id}` 与 `{ip}` 两个占位符。

### 为什么把 IP 解析放进独立服务

iKuai 固件之间响应结构差异较大，解析逻辑（`ikuai/parser.py`）与网络请求（`ikuai/client.py`）分开后，解析规则可以单独测试；`PublicIpResolver` 再叠加外部回显兜底，避免单点失败。

### 覆盖策略

需求明确要求「覆盖为仅最新公网 IP」，因此模板渲染时不会保留历史 IP：录制的请求体里原本的 IP 会被替换成唯一的 `{ip}`，同步后可信 IP 列表只剩最新一条。

## 扩展点

- `PublicIpResolverProtocol` / `WeComSessionProtocol`：同步服务对外部依赖的最小接口，测试用假实现替换。
- `storage.get_wecom_apps_url()`：企业微信后台改版时可直接在面板里替换应用管理页地址。
- `curl_template.parse_curl_command()`：新增请求特征时只需扩展占位符识别规则。

## 未覆盖的测试层

Playwright 与真实企业微信后台的交互无法在 CI 里运行，单元测试只覆盖解析、模板、存储、同步编排与 REST 层。浏览器通道的验证需要在真实账号下手工执行一次扫码与同步。


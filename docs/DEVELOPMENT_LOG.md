# 开发日志

记录这个项目从零到可用过程中解决的问题。文中所有公网 IP、域名、服务器、
企业微信 corp_id / agentid / 应用编号 / 应用名称均为脱敏后的示例值。

## 一、项目搭建

需求：前后端分离，Python 后端；扫码登录企业微信；登录后自动把 iKuai 的公网 IP
覆盖写入所有企业微信自建应用的「企业可信 IP」；只保留最新一条。

技术选型：

- 后端 FastAPI + Playwright + SQLite，前端零构建原生 ES Module SPA；
- 镜像基于 `mcr.microsoft.com/playwright/python`，自带 Chromium。

关键结论：企业微信**没有**开放"修改自建应用可信 IP"的公开接口，只能复用管理后台
自身的请求。因此采用"手动录制一次真实请求 → 生成带占位符的模板 → 同步时逐应用重放"
的方案，而不是硬编码某个可能随时变更的内部接口。

## 二、企业微信扫码登录

最初按常规思路在主文档里找二维码元素，结果一直失败。抓取真实 DOM 后发现：

```
主文档   images=0 canvases=0
iframe  https://work.weixin.qq.com/wework_admin/wwqrlogin/mng/login_qrcode?...  images=1
```

二维码在一个 **跨域 iframe** 里，`page.locator()` 不会穿透 iframe。改为三级策略：
先用 `page.frame_locator("iframe[src*='login_qrcode']")` 取 iframe 内的图片，
再退到主文档候选元素，最后用容器元素整体截图兜底。

## 三、扫码登录态与标签页

出现过"同步能成功、自动发现却总失败"的怪现象。排查发现：

- 写可信 IP 走的是 `context.request`，依赖 Cookie，所以一直正常；
- 自动发现需要**导航页面**，而管理后台的登录态与完成扫码的那个标签页绑定，
  新开标签页会被重定向回登录页。

对策：新增 `select_authenticated_page()`，优先复用扫码成功那个标签页；找不到时才
新开，并负责关闭。同时把"登录态失效"和"抓不到列表"分成两种错误提示。

另外确认：**服务重启后企业微信登录态必然失效**（不落盘），需要重新扫码，这是企业
微信的机制。

## 四、iKuai 真实固件联调

第一版按社区常见写法用表单登录，设备返回：

```
{"ErrMsg":"Post data error","Result":10001}
```

不猜格式，直接探测。结论有三条：

1. **登录必须用 JSON 报文**（`Content-Type: application/json`），表单会被拒绝；
   登录改为"JSON 优先、表单回退"，兼容新旧固件。
2. **`sess_key` 通过 `Set-Cookie` 下发**，响应体只有 `{"Result":10000}`；
   改为先从响应体找、找不到再从 Cookie 取。
3. **WAN 查询函数名不是 `wan_status`**，而是 `wan`：

   ```
   POST /Action/call
   {"func_name": "wan", "action": "show", "param": {"TYPE": "total,data"}}
   → {"Result":30000,"Data":{"data":[{"pppoe_ip_addr":"203.0.113.10", ...}]}}
   ```

   公网 IP 在 `Data.data[].pppoe_ip_addr`，解析器改为按字段特征识别
   （`ip` / `*_ip_addr` 等），不再依赖固定键名列表。

**顺带发现一个安全问题**：该固件的 `wan` 接口会明文返回 PPPoE 账号与密码
（`username` / `passwd`）。原本"探测原始响应"会把这些直接回吐给浏览器，属于凭据
泄露。现在返回前会递归脱敏（替换为 `***`），公网 IP 等排障必需字段保持可见。

## 五、请求模板（cURL 解析）

管理后台改可信 IP 的请求形态举例（两个版本都支持）：

```
# JSON 体
{"method":"POST","url":"https://work.weixin.qq.com/wework_admin/apps/saveIpConfig?...",
 "body":"{\"app_id\":{app_id},\"trusted_ip_list\":[\"{ip}\"]}"}

# 表单体
app_id={app_id}&ipList%5B%5D={ip}
```

踩过的坑：

1. **cmd 版 cURL 的转义**：`Copy as cURL (cmd)` 会产生 `^&`、`^%^5B`、`^"` 这类转义，
   旧解析器只处理行尾续行，导致 URL/请求头/请求体里残留 `^`，解析结果不可用。
   现在会在分词前统一还原，并把 `Cookie`、`sec-ch-ua*`、`user-agent` 等浏览器特征头
   从模板里剔除（重放时由浏览器会话自己提供）。
2. **两套应用编号**：录制到的请求用的是管理后台内部的 `app_id`（十几位长数字），
   而企业微信 API 用的是 `agentid`（7 位，如 `1230002`）。二者不是一回事，必须分别
   用 `{app_id}` 与 `{agent_id}` 两个占位符；应用记录里同时保存这两个编号。
3. **缺少 `{ip}` 必须报错**：如果模板里没有 IP 占位符，同步会静默写不出最新 IP，
   因此在保存模板时就拒绝，而不是等到同步失败。

## 六、自建应用自动发现

抓取管理后台 `getCorpApplication` 的完整响应后，结构如下：

```
{"data": {"default_app": [102 条腾讯应用], "custom_app": [], "openapi_app": [10 条]}}
```

自建应用与系统应用、腾讯官方应用混在同一个 `openapi_app` 列表里。判别方式只有
`app_open_id` 可靠：

| 类型 | app_open_id | 说明 |
| --- | --- | --- |
| 自建应用 | `1230002` 这类 1 开头的编号 | 它就是 agentid |
| 系统内置（通讯录同步助手、外部联系人） | `2000002` / `2000003` | 必须排除 |
| 腾讯官方应用 | `3010001` | 必须排除 |

两个反直觉的点，都是靠**真实完整响应**才发现的：

1. 自建应用**同样带 `aes_app_id`**，不能拿它当排除条件（早期用截断过的调试样本推断，
   字段正好被截断，结论完全反了）；
2. `app_open_id` 的类型不统一，多数是字符串，个别是**数字**，读取函数必须两种都认，
   否则会漏掉个别应用。

## 七、面板本地管理员账号

加分项：面板自己的登录与微信登录解耦。

- 首次部署进入「创建管理员账号」，单账号；密码用 PBKDF2-HMAC-SHA256（随机盐、20 万次
  迭代）存储，只用标准库；
- 会话令牌带 `sub`（用户名），`require_session` 除了验签还会确认账号仍存在；
- 连续失败 5 次锁定 5 分钟；
- 忘记账号/密码用运维命令 `python -m app.cli list-admins | set-password | reset-admin`，
  Windows 另有 `scripts/admin_cli.ps1` 包装。

## 八、构建与发布镜像

- 本机没有 Docker，改为在部署服务器上构建；
- **从国内直连 `mcr.microsoft.com` 拉基础镜像会卡死**（15 分钟无进展），换
  DaoCloud 镜像源 `mcr.m.daocloud.io` 后 1 分 55 秒拉完；Dockerfile 因此加了
  `ARG BASE_REGISTRY` 与 `ARG PIP_INDEX_URL` 两个可切换的源参数；
- 推送前做了镜像自检：容器内 Chromium 能启动、`/api/health` 正常、HEALTHCHECK 生效；
- 镜像构成：解压后 3.73 GB，其中 2.13 GB 是 Playwright 基础镜像预装的浏览器
  （含用不到的 Firefox 306 MB 与 WebKit 294 MB），我们自己的代码只有约 0.4 MB。

## 九、对外部署件

`outputs/deploy/` 提供给"只想用镜像"的人，不需要源码：

- `compose.yaml`：用 `.env` 变量，`APP_SECRET_KEY` 用 `:?` 语法强校验；
- `compose.panel.yaml`：**群晖 Container Manager / 宝塔**等面板粘贴专用，不含变量、
  不含嵌套块；
- `trusted-ip-template.json`：已验证可用的请求模板，粘贴即省掉录制步骤；
- `README.md`：前置条件、两种部署路径、国内加速与离线导入、首次配置、运维与 FAQ。

### compose 在面板里解析失败

用户把 compose 粘进面板后报：

```
'services[trusted-ip].healthcheck' expected a map or struct, got "string"
'services[trusted-ip].logging'     expected a map or struct, got "string"
```

这是 Go 解析器的错误格式（群晖/宝塔等面板用 Go 解析 YAML）。排查后确认文件本身没问题
（无 BOM / Tab / 全角空格，同一文件在服务器上 `docker compose config` 与真实
`up -d` 都通过），根因是**粘贴过程中缩进丢失**——`test:` / `driver:` 这类下级行一掉，
两个键就从 map 退化成字符串。

处理：`compose.yaml` 去掉 `healthcheck`/`logging` 两个嵌套块（健康检查由镜像自带的
HEALTHCHECK 提供，实测 `docker inspect` 仍为 `healthy`），日志轮转移为注释备选；
并新增没有变量与嵌套块的 `compose.panel.yaml`。

## 十、容器环境下的运维

忘记面板账号时，容器里**仍然使用** `python -m app.cli`，但必须进容器执行：

```bash
docker exec -it <容器名> python -m app.cli list-admins
docker exec -it <容器名> python -m app.cli set-password --username <用户名>
docker exec -it <容器名> python -m app.cli reset-admin
```

镜像里已内置 `PYTHONPATH=/app/backend`，且 CLI 读取的是容器内 `APP_DATA_DIR=/data`
（即 volume 映射出来的同一份数据库）。实测覆盖四种情况：容器内执行、容器停止后用
一次性容器挂同一数据卷执行、群晖 Container Manager 的"终端机"入口、以及宿主机直接
执行（会失败，属预期）。

常见误区：用一次性容器却没挂数据卷 → 命令"成功"但操作的是全新空库。

## 十一、发布前脱敏

准备开源发布时做了一次全仓库扫描，处理三类内容：

1. **移出仓库的私密数据**：本机运行数据（含 iKuai 密码与企业微信登录态）、
   `.env`、部署用的 `.env`、以及部署服务器用的 SSH 私钥；
2. **替换为示例值**：公网 IP、内网地址、域名、服务器主机名、corp_id、agentid、
   管理后台应用编号、自建应用名称；
3. **测试数据**：单元测试里原本引用了真实编号与真实响应片段，全部换成语义等价的
   示例值（例如 `agentid` 用 `123000x`，后台编号用 `562950000000000x`，
   公网 IP 用可公网路由的示例地址），保证测试仍然通过。

## 十二、修复同步"假成功"

用户反馈（2026-10-10）：面板显示"已覆盖 N/N 个应用的可信 IP"，但企业微信里
各应用的可信 IP 并没有变。

排查结论 —— 失败被静默吞掉了：

- `backend/app/wecom/admin_browser.py` 的 `replay_request()` 只用
  `response.status >= 400` 判断成败。而企业微信管理后台在会话失效、参数被拒时
  **依然返回 HTTP 200**，真正的原因放在响应体的 `errcode` / `errmsg` 里。
  于是"请求发出去了"就等于"同步成功"，面板与日志都不报错。
- 同文件 `_ensure_logged_in_locked()` 在进程内状态为 `logged_in` 时直接 return，
  不再向企业微信确认。容器长期运行时企业微信侧会话过期，内存里的陈旧状态会继续
  骗过后续请求，所以症状表现为"一开始能用，跑一段时间后就不生效了"。

处理：

1. `backend/app/wecom/parsing.py` 新增 `describe_wecom_error(body)`：解析 JSON 响应，
   `errcode` 非 0 时返回 `errcode=.. msg=..`；成功、非 JSON、无 `errcode` 字段返回 `None`；
2. `replay_request()` 在 HTTP 状态校验之后调用它，被拒绝时抛 `WeComAdminError`，
   企业微信的原始错误码与说明会落到该应用的「最近错误」和同步日志；
3. `ensure_logged_in()` 改为强制访问一次后台核对登录态（`verify_session=True`），
   跳回登录页时把状态置为 `failed` 并提示重新扫码；
4. 补回归测试：`tests/test_wecom_parsing.py` 新增 8 条、新建
   `tests/test_wecom_replay_request.py` 5 条、`tests/test_sync_service.py` 增加
   "被 errcode 拒绝时不得记为成功" 用例 1 条。

本次未解决：企业微信**具体**拒绝原因（会话过期 / app_id 不匹配 / 页面改版）要看真实
返回。修复后「最近错误」会直接显示 `errcode=.. msg=..`，拿到真实错误码再按需处理。

## 十三、手动同步不再被"IP 未变化"挡住

用户反馈（2026-10-10）：企业微信里的可信 IP 已经失效，点面板「立即同步」却提示"已是最新"，
只有勾选"忽略 IP 未变化检查、强制覆盖"才真正写进去。

原因：`SyncService.sync()` 在 `force=False` 时用 `_is_already_synced()` 短路，而它**只读本地
数据库**——"本次观测 IP == 上次观测 IP"且"每个应用 `last_synced_ip` 等于该 IP 且无错误"就整体
跳过，一个请求都不发。`last_synced_ip` 恰好是第十二节那个假成功版本写下的，本地以为已同步、
企业微信里其实没有，于是把"我记得我写过"当成了"企业微信现在就是这个"，企业微信侧被改动后就
再也不会自动修正。

处理：

1. 面板「立即同步」固定按 `force: true` 调 `/api/sync/run`，手动操作一律真正重写全部应用；
   随之删掉已经失去意义的"忽略 IP 未变化检查、强制覆盖"复选框
   （`frontend/src/pages/dashboard.js`）；
2. 自动同步保留"IP 未变化就跳过"的省流行为，跳过文案改为
   "公网 IP 未变化，自动同步已跳过；需要重新写入请在面板点「立即同步」"；
3. 测试：`tests/test_sync_service.py` 新增"上次写入失败的应用不会被 IP 未变化永久跳过、必须
   重试"用例，并在跳过用例中断言文案包含「立即同步」；
4. 同步更新 `README.md` 与 `outputs/deploy/README.md` 中相关说明。

未做（可选项，用户未选）：自动同步在 IP 未变化时每隔 N 小时也强制覆盖一次，作为"企业微信侧
被清过"的安全网。

## Resume 入口

### 当前状态快照

- 代码、测试、镜像、部署件均已就绪；单元测试 **142 passed**；
- 同步成败判定已修正为解析企业微信响应体的 `errcode`（见十二），面板不会再把
  "被后台拒绝"显示成同步成功；
- 手动「立即同步」固定强制重写全部应用，自动同步仍按"IP 未变化跳过"省流（见十三）；
- 镜像已构建并推送（仓库里统一用 `YOUR_DOCKERHUB/wxip:latest` 占位，使用者替换成自己的地址）；
  压缩约 1.0 GB、解压 3.73 GB，自带 Chromium；
- 真实环境全链路验证通过：扫码登录 → 读取 iKuai 公网 IP → 覆盖全部自建应用的可信 IP
  → 定时自动同步；
- 面板已支持本地管理员账号（首次部署创建、可改密、可用 CLI 找回）。

### 下次进来先做的事（按优先级）

1. 若面板报 `errcode` 相关错误：会话类错误先重新扫码；`app_id` 类错误去「企业微信」
   页核对该应用的「控制台应用编号」；
2. 可选安全网（见十三）：自动同步在 IP 未变化时每隔 N 小时也强制覆盖一次，用于企业微信侧
   被清空/改动后能自动修回来；
3. 若要继续改进体积：可基于 `python:3.12-slim` + 只装 Chromium 做一版瘦身镜像
   （去掉用不到的 Firefox/WebKit），预计下载降到约 500 MB；
4. 企业微信后台若改版：先看 `data/wecom_discover_debug.json` 里的 `app_entry_samples`，
   再调整 `backend/app/wecom/parsing.py` 的判别规则；
5. iKuai 若换固件：用面板「iKuai → 探测原始响应」，按返回结构调整
   `backend/app/ikuai/parser.py` 的字段候选。

### 绝对不要做的事

- 不要把 `data/`、`.env`、`work/`（含 SSH 私钥）提交到版本库；
- 不要为了让同步通过而放宽模板对 `{ip}` 的校验，那会导致静默写不进最新 IP；
- 不要只看 HTTP 状态码判断企业微信接口是否成功——后台被拒时同样是 200，必须看
  `errcode`；
- 不要把"本地记录的 last_synced_ip"当成"企业微信当前的真实状态"——企业微信侧可以被
  人工改动，这正是手动「立即同步」必须强制写入的原因；
- 不要在未确认后台请求特征的情况下，把"覆盖为仅最新 IP"改成追加策略。

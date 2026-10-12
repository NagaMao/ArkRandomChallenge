# ArkRandomChallenge项目说明（手写）
访问链接 https://arkrandomchallenge.xyz/ 即可开始游玩

## 随机挑战
主要功能界面，可以设置队伍人数、干员星级、干员职业进行筛选，随机出挑战随机关卡的随机干员
登录时随机池为通过森空岛拉取的干员数据；未登录时随机池为全部已实装可获得干员
可以使用黑名单功能，让指定干员不再出现在随机池中
## 干员一览
可以查看随机池的干员（登录时此界面为该森空岛账号持有的干员）
## 账号登录
通过账号密码或手机号+验证码的方式登录，此项目只拉取干员数据，且数据仅保存在本地的对应浏览器上。
若对项目安全不放心请勿使用此功能

# ArkRandomChallenge — Cloudflare Workers 部署指南（DS生成的）

明日方舟随机干员 / 随机关卡工具，运行于 Cloudflare Workers。

## 项目结构

```
ArkRandomChallenge/
├── wrangler.jsonc          # Cloudflare Workers 配置（Cron Trigger、KV 绑定、vars）
├── pyproject.toml          # Python 依赖声明
├── src/
│   ├── worker.py           # Flask Worker 入口（API 路由 + 前端路由 + 数据刷新 + 定时任务）
│   └── data_fetcher.py     # 数据抓取与解析（从网络获取并写入 KV）
└── public/                 # 前端静态文件目录（Workers Static Assets）
    ├── index.html
    ├── script.js
    └── style.css
```

## 改动说明

### 1. `requests` → `workers.fetch`

原代码用 `requests` 库同步下载 JSON 数据。Workers 不支持 `requests`，已改用
Cloudflare Workers 的 `fetch()` API（异步）。

### 2. 本地文件缓存 → Cloudflare KV

原代码用本地文件系统缓存数据（`data_cache/` 目录）。Workers 无文件系统，已改用 KV：

- KV namespace 绑定名：`DATA_KV`（ID 见 `wrangler.jsonc`）
- 存储 keys：
  - `operators` —— 干员列表
  - `stages` —— 关卡列表
  - `exclude` —— 黑名单
  - `data_updated_at` —— 最近一次刷新时间（ISO 8601 UTC）

### 3. 前端静态文件 → Workers Static Assets

前端文件放在 `./public/`，通过 `ASSETS` binding 访问。
`wrangler.jsonc` 中 `run_worker_first: true` 确保 API 路由优先交给 Worker 处理。

### 4. 定时刷新：APScheduler → Cron Triggers

原代码用 `BackgroundScheduler` 每日 04:00（北京时间）刷新数据。Workers 不支持后台线程，
已改用 Cloudflare Cron Triggers：

- 配置在 `wrangler.jsonc` 的 `triggers.crons`：`0 20 * * *`
- **cron 表达式使用 UTC 时间**：`0 20 * * *` = UTC 20:00 = **北京时间次日 04:00**

> ⚠️ 重要：Cloudflare 规定 `scheduled` handler **必须定义在入口类 `Default` 中**。
> 若把 `scheduled` 放在另一个类里（例如 `ScheduledHandler`），它不会被注册，定时任务
> **永远不会触发**，KV 里的 `operators` 会一直停留在旧快照。
>
> 因此 `worker.py` 中通过继承 WSGI 入口类并补上 `scheduled` 方法来保证二者共处于
> 同一个 `Default` 类：

```python
_WsgiDefault = wsgi.entrypoint(app)

class Default(_WsgiDefault):
    async def fetch(self, request, *args, **kwargs):   # 方式 B：拦截 POST /api/refresh
        ...
        return await super().fetch(request, *args, **kwargs)

    async def scheduled(self, controller, env, ctx):   # 方式 A：每日定时刷新
        ...
```

> ⚠️ 另一个坑（方式 B 的实现方式）：刷新需要从网络拉取数据（`await fetch(...)`），
> 必须运行在**真正的异步上下文**里。如果把 `/api/refresh` 写成 Flask 视图、在同步栈里
> 用 `run_sync(refresh_all_data(env))` 调用，线上会直接报
> **HTTP 503 / `error code: 1102`**（Worker 运行时异常）。
> 因此方式 B 由入口类 `Default.fetch` 直接拦截处理，其余请求再交给 Flask(WSGI)。

## 数据刷新策略（方式 A / A+B）

刷新开关默认值定义在 `worker.py` 顶部，也可通过环境变量覆盖：

```python
# True  = 方式 A + B 同时启用
# False = 只启用方式 A
ENABLE_DEPLOY_REFRESH_DEFAULT = True
```

对应 `wrangler.jsonc` 中的：

```jsonc
"vars": {
  "ENABLE_DEPLOY_REFRESH": "true"
}
```

- 开关为 `true`：方式 A + B 同时启用
- 开关为 `false`：**只启用方式 A**，`POST /api/refresh` 返回 404

### 方式 A —— 每日定时刷新（始终启用）

- 由 Cloudflare Cron Triggers 触发 `Default.scheduled`
- 每日北京时间 04:00（UTC 20:00）强制从网络重新拉取干员与关卡数据并写入 KV
- 无论 `ENABLE_DEPLOY_REFRESH` 开关如何，方式 A 始终生效

### 方式 B —— 部署时刷新（由 `ENABLE_DEPLOY_REFRESH` 控制）

- 开关为 `true` 时，提供 `POST /api/refresh` 接口
- 在 Cloudflare Build 的 **Deploy command** 中，部署完成后调用该接口，
  实现"每次部署即刷新最新数据"
- 开关为 `false` 时，该接口返回 404，等同于只保留方式 A

#### 使用步骤

1. 配置鉴权 token（Secret）：

```bash
wrangler secret put REFRESH_TOKEN
```

      接口同时接受 `X-Refresh-Token` 请求头（推荐，安全性高于 URL 查询参数）
   与 `?token=` 查询参数。

2. 在 Cloudflare Dashboard → 你的 Worker → Settings → Builds → **Deploy command** 填写：

```bash
uv run pywrangler deploy && curl -fsS -X POST "https://arkrandomchallenge.xyz/api/refresh?token=你的token"
```

   或使用请求头方式：

```bash
uv run pywrangler deploy && curl -fsS -X POST -H "X-Refresh-Token: 你的token" "https://arkrandomchallenge.xyz/api/refresh"
```

> ⚠️ 未配置 `REFRESH_TOKEN` 时，`/api/refresh` 会拒绝所有请求（返回 403），
> 避免接口被公开滥用。因此 Deploy command 中的 `curl` **必须携带正确的 token**，
> 否则会因为 403（`curl -f` 判定失败）而中断 `&&` 链路。

## 部署步骤

### 前提条件

- 安装 [uv](https://docs.astral.sh/uv/)（Python 包管理器）
- 安装 Node.js（wrangler 需要）

### 1. 准备前端文件

确保前端文件位于 `public/` 目录（`index.html` / `script.js` / `style.css`）。

### 2. 本地开发测试

```bash
uv run pywrangler dev
```

### 3. 部署到 Cloudflare

```bash
uv run pywrangler deploy
```

### 4. 连接 GitHub 自动部署

1. 打开 Cloudflare Dashboard → Workers & Pages → arkrandomchallenge → Settings → Builds
2. 点击 Connect，连接你的 GitHub 仓库
3. 设置 Deploy command（如需方式 B，请按上文附带 `/api/refresh` 调用）
4. 推送代码到 main 分支即可自动部署

## 注意事项

- **首次部署**：KV 中没有数据，第一次请求 API 时会从网络拉取并缓存到 KV；或等待方式 A
  定时刷新、或手动调用方式 B 刷新。首次请求可能较慢。
- **定时刷新**：每天 UTC 20:00（北京时间 04:00）自动刷新数据。
- **黑名单**：存储在 KV 的 `exclude` key 中，跨请求持久化。
- **数据版本**：`/api/version` 返回最近一次刷新时间（来自 KV 的 `data_updated_at`）。
- **内存快照**：Python Workers 在部署时生成内存快照，冷启动约 1 秒。

# ArkRandomChallenge — Cloudflare Workers 部署指南

## 项目结构

```
ArkRandomChallenge/
├── wrangler.jsonc          # Cloudflare Workers 配置
├── pyproject.toml          # Python 依赖声明
├── src/
│   ├── worker.py           # Flask Worker 入口（API + 前端路由）
│   └── data_fetcher.py     # 数据抓取与解析（改写为 async）
└── public/                 # 前端静态文件目录
    ├── index.html
    ├── css/
    ├── js/
    └── ...（你原来的 frontend 目录内容）
```

## 改动说明

### 1. `requests` → `workers.fetch`
原代码用 `requests` 库同步下载 JSON 数据。Workers 不支持 `requests`，已改用 Cloudflare Workers 的 `fetch()` API（异步）。

### 2. `APScheduler` → `Cron Triggers`
原代码用 `BackgroundScheduler` 每日 04:00（北京时间）刷新数据。Workers 不支持后台线程，已改用 Cloudflare Cron Triggers：
- 配置在 `wrangler.jsonc` 的 `triggers.crons` 中
- cron 表达式 `0 20 * * *` = UTC 20:00 = 北京时间 04:00
- 在 `worker.py` 的 `ScheduledHandler` 类中处理定时任务

### 3. 文件缓存 → KV
原代码用本地文件系统缓存数据（`data_cache/` 目录）。Workers 无文件系统，已改用 Cloudflare KV：
- KV namespace: `arkrandomchallenge-data`（ID: `24b360df48144bb2bd9a7c906bd147a6`）
- 存储 keys: `operators`、`stages`、`exclude`

### 4. 前端静态文件
原代码用 Flask 的 `send_from_directory` 托管前端。已改用 Workers Static Assets：
- 前端文件放在 `./public/` 目录
- 通过 `ASSETS` binding 访问
- `run_worker_first: true` 确保 API 路由优先

### 5. `urllib3` 移除
Workers 的 `fetch()` 不需要 `urllib3`，已移除。

### 6. `pytz` 移除
Cron Triggers 使用 UTC 时间，不需要 `pytz`。

## 部署步骤

### 前提条件
- 安装 [uv](https://docs.astral.sh/uv/)（Python 包管理器）
- 安装 Node.js（wrangler 需要）

### 1. 准备前端文件
将你原来的 `ark/frontend/` 目录下的所有文件复制到 `public/` 目录：
```bash
mkdir -p public
cp -r ark/frontend/* public/
```

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
2. 点击 Connect，连接你的 GitHub 仓库 NagaMao/ArkRandomChallenge
3. 设置 Deploy command 为 `uv run pywrangler deploy`
4. 推送代码到 main 分支即可自动部署

## 注意事项

- **首次部署**：KV 中没有数据，第一次请求 API 时会从网络拉取并缓存到 KV。首次请求可能较慢。
- **定时刷新**：每天 UTC 20:00（北京时间 04:00）自动刷新数据。
- **黑名单**：存储在 KV 的 `exclude` key 中，跨请求持久化。
- **内存快照**：Python Workers 在部署时生成内存快照，冷启动约 1 秒。

from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from pyodide.ffi import run_sync
from workers import wsgi
import json
import random
from datetime import datetime, timezone
from data_fetcher import fetch_operators, fetch_stages, get_data_version

# ===== 配置开关 =====
# 方式A（每日定时）始终启用；
# 方式B（部署时刷新）由 Worker 环境变量 ENABLE_DEPLOY_REFRESH 控制：
#   "true"/"1"/"yes"/"on"  → 方式A + 方式B 同时启用
#   "false"/"0"/"no"/"off" → 只启用方式A
# 可通过 wrangler.jsonc 的 vars 或 `wrangler secret put` 配置。
ENABLE_DEPLOY_REFRESH_DEFAULT = True


def _env_str(env, name):
    """从 Worker env 读取字符串变量。

    Cloudflare Python Workers 的 vars / secrets 都通过 env 对象暴露
    （而不是 Python 的 os.environ）。未设置时返回 None。
    """
    try:
        raw = getattr(env, name, None)
    except Exception:
        return None
    if raw is None:
        return None
    text = str(raw).strip()
    if text in ("", "undefined", "null"):
        return None
    return text


def _deploy_refresh_enabled(env):
    """读取部署时刷新开关（方式B）。未配置时回退到默认值。"""
    text = _env_str(env, "ENABLE_DEPLOY_REFRESH")
    if text is None:
        return ENABLE_DEPLOY_REFRESH_DEFAULT
    return text.lower() in ("1", "true", "yes", "on")


def _get_refresh_token(env):
    """读取方式B的鉴权 token。未配置返回 None（表示不校验）。"""
    return _env_str(env, "REFRESH_TOKEN")


app = Flask(__name__)
CORS(app)

# ===== 工具函数 =====

def kv_get(env, key):
    """从 KV 读取数据，返回 dict 或 None"""
    raw = run_sync(env.DATA_KV.get(key))
    if raw is None:
        return None
    return json.loads(str(raw))

def kv_put(env, key, value):
    """写入 KV"""
    run_sync(env.DATA_KV.put(key, json.dumps(value, ensure_ascii=False)))

def load_exclude(env):
    """加载黑名单"""
    return kv_get(env, "exclude") or {"operators": [], "stages": []}

def save_exclude(env, exclude_data):
    """保存黑名单"""
    kv_put(env, "exclude", exclude_data)

# ===== 前端路由 =====

@app.get("/")
@app.get("/<path:path>")
def frontend(path=""):
    assets = request.environ["workers.env"].ASSETS
    asset_response = run_sync(assets.fetch(f"https://assets.local/{path}"))
    body = run_sync(asset_response.bytes())
    return Response(
        body,
        status=asset_response.status,
        headers=asset_response.headers,
    )

# ===== API 路由 =====

@app.route("/api/operators", methods=["GET"])
def get_operators():
    """获取干员列表，支持筛选"""
    env = request.environ["workers.env"]
    stars_param = request.args.get("stars", "")
    professions_param = request.args.get("professions", "")
    exclude = load_exclude(env)

    operators_data = kv_get(env, "operators") or []

    result = operators_data

    # 过滤黑名单
    result = [op for op in result if op["id"] not in exclude["operators"]]

    # 星级筛选
    if stars_param:
        stars = [int(s) for s in stars_param.split(",") if s]
        result = [op for op in result if op["star"] in stars]

    # 职业筛选
    if professions_param:
        professions = [p for p in professions_param.split(",") if p]
        result = [op for op in result if op["profession"] in professions]

    return jsonify({
        "code": 0,
        "data": result,
        "total": len(result)
    })

@app.route("/api/stages", methods=["GET"])
def get_stages():
    """获取关卡列表"""
    env = request.environ["workers.env"]
    exclude = load_exclude(env)
    stages_data = kv_get(env, "stages") or []
    result = [s for s in stages_data if s["id"] not in exclude["stages"]]
    return jsonify({
        "code": 0,
        "data": result,
        "total": len(result)
    })

@app.route("/api/random-team", methods=["POST"])
def random_team():
    """生成随机队伍"""
    env = request.environ["workers.env"]
    data = request.json
    team_size = data.get("teamSize", 4)
    stars = data.get("stars", [1, 2, 3, 4, 5, 6])
    professions = data.get("professions", [])
    random_skill = data.get("randomSkill", True)

    exclude = load_exclude(env)

    operators_data = kv_get(env, "operators") or []
    stages_data = kv_get(env, "stages") or []

    # 获取可用干员
    available = [op for op in operators_data if op["id"] not in exclude["operators"]]

    # 星级筛选
    if stars:
        available = [op for op in available if op["star"] in stars]

    # 职业筛选
    if professions:
        available = [op for op in available if op["profession"] in professions]

    # 检查可用干员数量
    if len(available) < team_size:
        return jsonify({
            "code": 1,
            "msg": f"可用干员不足，当前只有 {len(available)} 位，请调整筛选条件或减少队伍人数"
        })

    # 随机选择
    selected = random.sample(available, team_size)

    # 处理技能
    for op in selected:
        if random_skill and op["skills"]:
            skill_idx = random.randint(0, len(op["skills"]) - 1)
            op["selected_skill"] = op["skills"][skill_idx]
        else:
            op["selected_skill"] = op["skills"][0] if op["skills"] else None

    # 随机关卡
    available_stages = [s for s in stages_data if s["id"] not in exclude["stages"]]
    if not available_stages:
        return jsonify({
            "code": 1,
            "msg": "没有可用的关卡，请检查黑名单"
        })

    random_stage = random.choice(available_stages)

    return jsonify({
        "code": 0,
        "data": {
            "team": selected,
            "stage": random_stage,
            "team_size": team_size
        }
    })

@app.route("/api/exclude", methods=["POST"])
def update_exclude():
    """更新黑名单"""
    env = request.environ["workers.env"]
    data = request.json
    action = data.get("action")
    target_type = data.get("type")
    target_id = data.get("id")

    if not target_id:
        return jsonify({
            "code": 1,
            "msg": "缺少目标 ID"
        })

    exclude = load_exclude(env)
    key = "operators" if target_type == "operator" else "stages"

    if action == "add":
        if target_id not in exclude[key]:
            exclude[key].append(target_id)
    elif action == "remove":
        if target_id in exclude[key]:
            exclude[key].remove(target_id)
    else:
        return jsonify({
            "code": 1,
            "msg": "无效的操作类型，请使用 add 或 remove"
        })

    save_exclude(env, exclude)

    return jsonify({
        "code": 0,
        "msg": "更新成功",
        "data": exclude
    })

@app.route("/api/exclude/list", methods=["GET"])
def get_exclude():
    """获取黑名单列表"""
    env = request.environ["workers.env"]
    return jsonify({
        "code": 0,
        "data": load_exclude(env)
    })

@app.route("/api/version", methods=["GET"])
def version():
    """获取数据版本"""
    env = request.environ["workers.env"]
    return jsonify(get_data_version(env))

# 注意：/api/refresh（方式B）由 Default.fetch 直接拦截处理，
# 不经过 Flask，以确保刷新在真正的异步上下文中执行。

# ===== 错误处理 =====

@app.errorhandler(404)
def not_found(e):
    return jsonify({
        "code": 404,
        "msg": "接口不存在"
    }), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({
        "code": 500,
        "msg": "服务器内部错误"
    }), 500


# ===== 数据刷新 =====

async def refresh_data(env):
    """强制从网络刷新干员与关卡数据并写入 KV。

    返回数据条数统计。任一步失败时抛出异常（调用方保留旧数据）。
    注意：本函数必须在真正的异步上下文（fetch / scheduled handler）中 await，
    不要放在 Flask 的同步视图里用 run_sync 调用。
    """
    print("[刷新] 开始刷新干员与关卡数据...")
    new_operators = await fetch_operators(env, force=True)
    new_stages = await fetch_stages(env, force=True)

    if not new_operators or not new_stages:
        raise RuntimeError("数据源返回空结果")

    await env.DATA_KV.put("operators", json.dumps(new_operators, ensure_ascii=False))
    await env.DATA_KV.put("stages", json.dumps(new_stages, ensure_ascii=False))
    await env.DATA_KV.put("data_updated_at", datetime.now(timezone.utc).isoformat())

    stats = {
        "operators": len(new_operators),
        "stages": len(new_stages),
    }
    print(f"[刷新] 完成：{stats['operators']} 位干员 / {stats['stages']} 个关卡")
    return stats


# Cloudflare 规定：fetch / scheduled 等 handler 必须定义在入口类 `Default` 中。
# wsgi.entrypoint(app) 只会生成一个仅含 fetch 的类，因此这里显式继承并补上 scheduled，
# 确保两者被注册到同一个入口类里。
_WsgiDefault = wsgi.entrypoint(app)


class Default(_WsgiDefault):
    """Worker 入口类：处理 HTTP 请求（fetch）与定时任务（scheduled）。

    - fetch：拦截 POST /api/refresh（方式B），其余请求交给 Flask(WSGI) 处理。
    - scheduled：每日定时刷新（方式A）。
    """

    async def fetch(self, request, *args, **kwargs):
        # 在真正的异步上下文里处理刷新接口，避免在 Flask 同步栈中用 run_sync 嵌套 KV 操作
        try:
            url = getattr(request, "url", "") or ""
            method = str(getattr(request, "method", "") or "").upper()
            if "/api/refresh" in url and method in ("POST", "GET"):
                return await self._handle_refresh(request)
        except Exception as e:  # noqa: BLE001
            print(f"[refresh] 判断请求失败，交给 WSGI 处理：{e}")

        return await super().fetch(request, *args, **kwargs)

    async def _handle_refresh(self, request):
        from js import Response

        env = self.env
        print(f"[refresh] 收到刷新请求：{getattr(request, 'url', '')}")

        if not _deploy_refresh_enabled(env):
            return Response.new(
                json.dumps({"code": 404, "msg": "部署时刷新已关闭（ENABLE_DEPLOY_REFRESH=false）"},
                           ensure_ascii=False),
                status=404,
                headers={"content-type": "application/json; charset=utf-8"},
            )

        # 鉴权：从请求头或查询参数取 token
        expected = _get_refresh_token(env)
        provided = None
        try:
            headers = getattr(request, "headers", None)
            if headers is not None:
                provided = headers.get("X-Refresh-Token")
            if not provided:
                url = getattr(request, "url", "") or ""
                from urllib.parse import urlsplit, parse_qs
                qs = parse_qs(urlsplit(url).query)
                provided = (qs.get("token") or [None])[0]
        except Exception as e:  # noqa: BLE001
            print(f"[refresh] 解析 token 失败：{e}")

        # 只有配置了 token 时才校验；未配置则允许（刷新仅拉取公开数据，无敏感信息）
        if expected and provided != expected:
            return Response.new(
                json.dumps({"code": 403, "msg": "无权访问：token 缺失或不正确"},
                           ensure_ascii=False),
                status=403,
                headers={"content-type": "application/json; charset=utf-8"},
            )

        try:
            stats = await refresh_data(env)
            body = json.dumps({"code": 0, "msg": "刷新成功", "data": stats}, ensure_ascii=False)
            return Response.new(
                body,
                status=200,
                headers={"content-type": "application/json; charset=utf-8"},
            )
        except Exception as e:  # noqa: BLE001
            print(f"[refresh] 刷新失败：{e}")
            return Response.new(
                json.dumps({"code": 1, "msg": f"刷新失败：{e}"}, ensure_ascii=False),
                status=500,
                headers={"content-type": "application/json; charset=utf-8"},
            )

    async def scheduled(self, controller, env, ctx):
        """方式A：每日 04:00（北京时间 = UTC 20:00）刷新数据。

        无论 ENABLE_DEPLOY_REFRESH 开关如何，方式A始终启用。
        """
        print("[定时任务] 触发每日刷新...")
        try:
            await refresh_data(env)
        except Exception as e:
            print(f"[定时任务] 刷新失败，保留旧数据：{e}")

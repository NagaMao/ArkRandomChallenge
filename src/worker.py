from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from pyodide.ffi import run_sync
from workers import wsgi
import json
import random
from datetime import datetime, timezone
from data_fetcher import fetch_operators, fetch_stages

app = Flask(__name__)
CORS(app)

# ===== 刷新开关 =====
# True  = 方式 A（每日定时）+ 方式 B（部署时刷新）同时启用
# False = 只启用方式 A（每日定时），/api/refresh 返回 404
# 默认值可被 wrangler.jsonc 的 vars.ENABLE_DEPLOY_REFRESH 覆盖。
ENABLE_DEPLOY_REFRESH_DEFAULT = True


def _parse_bool(value, default=False):
    """把字符串/布尔环境变量解析为布尔值。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def deploy_refresh_enabled(env):
    """读取方式 B（部署时刷新）开关，未配置时回退到默认值。"""
    try:
        value = getattr(env, "ENABLE_DEPLOY_REFRESH", None)
    except Exception:
        value = None
    return _parse_bool(value, ENABLE_DEPLOY_REFRESH_DEFAULT)


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


async def refresh_all_data(env):
    """强制从网络重新拉取干员与关卡数据并写入 KV。

    供方式 A（定时任务）与方式 B（部署时刷新）共用。
    返回 (干员数量, 关卡数量)。
    """
    new_operators = await fetch_operators(env, force=True)
    new_stages = await fetch_stages(env, force=True)
    await env.DATA_KV.put("operators", json.dumps(new_operators, ensure_ascii=False))
    await env.DATA_KV.put("stages", json.dumps(new_stages, ensure_ascii=False))
    await env.DATA_KV.put("data_updated_at", datetime.now(timezone.utc).isoformat())
    return len(new_operators), len(new_stages)

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
    updated_at = kv_get(env, "data_updated_at")
    return jsonify({
        "version": "1.0.0",
        "lastUpdated": updated_at,
    })


# 注意：方式 B 的 POST /api/refresh 不在 Flask 里定义，而是由入口类 Default.fetch
# 直接拦截处理（见文件末尾）。原因：刷新需要从网络拉取数据（await fetch(...)），
# 若放在 Flask 同步视图里用 run_sync 调用，会在 Cloudflare 上触发运行时错误
# （HTTP 503 / error code 1102）。因此必须在真正的异步上下文（fetch handler）中执行。

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


# ===== Worker 入口 =====

# Flask WSGI 入口：wsgi.entrypoint(app) 返回一个名为 Default 的入口类
# （只包含 fetch 方法）。
#
# ⚠️ Cloudflare 规定 scheduled handler 必须定义在入口类 Default 中。
# 因此这里通过【继承】WSGI 入口类，把 scheduled 方法补进同一个 Default 类。
# 若像过去那样另起一个 ScheduledHandler 类，scheduled 永远不会被触发，
# KV 里的 operators 会一直停留在旧快照，线上干员一览也就没有最新干员。
_WsgiDefault = wsgi.entrypoint(app)


def _json_response(payload, status=200):
    """构造一个返回 JSON 的 JS Response（用于 Default.fetch 拦截路径）。"""
    from js import Response

    return Response.new(
        json.dumps(payload, ensure_ascii=False),
        status=status,
        headers={"content-type": "application/json; charset=utf-8"},
    )


async def _handle_refresh(request, env):
    """方式 B：处理 POST /api/refresh，在真正的异步上下文中执行刷新。

    - 开关为 false 时：接口不可用，返回 404。
    - 开关为 true 时：需携带正确的 REFRESH_TOKEN（请求头 X-Refresh-Token 或
      query 参数 ?token=），校验通过后强制刷新 KV 中的干员与关卡数据。
    """
    # 开关关闭 -> 视为接口不存在
    if not deploy_refresh_enabled(env):
        return _json_response({"code": 404, "msg": "接口不存在"}, 404)

    # 鉴权：未配置 REFRESH_TOKEN 时禁用，避免接口被公开滥用
    try:
        expected_token = getattr(env, "REFRESH_TOKEN", None)
    except Exception:
        expected_token = None

    if not expected_token:
        return _json_response(
            {"code": 403, "msg": "未配置 REFRESH_TOKEN，刷新接口已禁用"}, 403
        )

    # 读取客户端提供的 token（优先请求头，其次 query 参数）
    provided_token = None
    try:
        headers = getattr(request, "headers", None)
        if headers is not None:
            provided_token = headers.get("X-Refresh-Token")
        if not provided_token:
            from urllib.parse import urlsplit, parse_qs

            qs = parse_qs(urlsplit(request.url).query)
            provided_token = (qs.get("token") or [None])[0]
    except Exception as e:  # noqa: BLE001
        print(f"[refresh] 解析 token 失败：{e}")

    if provided_token != str(expected_token):
        return _json_response({"code": 403, "msg": "刷新令牌无效"}, 403)

    # 执行刷新（真正的异步上下文，直接 await）
    try:
        op_count, stage_count = await refresh_all_data(env)
    except Exception as e:  # noqa: BLE001
        print(f"[refresh] 刷新失败：{e}")
        return _json_response({"code": 1, "msg": f"刷新失败，保留旧数据：{e}"}, 500)

    # 读取刷新时间（env 是 _EnvWrapper，KV 调用需 await）
    updated_at = None
    try:
        raw = await env.DATA_KV.get("data_updated_at")
        if raw is not None:
            updated_at = str(raw)
    except Exception as e:  # noqa: BLE001
        print(f"[refresh] 读取刷新时间失败：{e}")

    return _json_response({
        "code": 0,
        "msg": "刷新成功",
        "data": {
            "operators": op_count,
            "stages": stage_count,
            "lastUpdated": updated_at,
        },
    })


class Default(_WsgiDefault):
    """Worker 入口类：同时承载 fetch（WSGI）与 scheduled（定时刷新）。

    - fetch：拦截 POST /api/refresh（方式 B），其余请求交给 Flask(WSGI)。
    - scheduled：每日定时刷新（方式 A）。
    """

    async def fetch(self, request, *args, **kwargs):
        # 在真正的异步上下文里处理刷新接口，避免在 Flask 同步栈中用 run_sync
        # 嵌套网络请求 + KV 操作（会触发 Cloudflare 503 / error 1102）。
        try:
            url = str(getattr(request, "url", "") or "")
            method = str(getattr(request, "method", "") or "").upper()
            if "/api/refresh" in url and method == "POST":
                return await _handle_refresh(request, self.env)
        except Exception as e:  # noqa: BLE001
            print(f"[refresh] 判断请求失败，交给 WSGI 处理：{e}")

        return await super().fetch(request, *args, **kwargs)

    async def scheduled(self, controller, env, ctx):
        """方式 A：每日北京时间 04:00（= UTC 20:00）强制刷新数据。

        无论 ENABLE_DEPLOY_REFRESH 开关如何，方式 A 始终启用。
        """
        print("[定时任务] 开始刷新干员与关卡数据...")
        try:
            op_count, stage_count = await refresh_all_data(env)
            print(f"[定时任务] 刷新完成：{op_count} 位干员 / {stage_count} 个关卡")
        except Exception as e:
            print(f"[定时任务] 刷新失败，保留旧数据：{e}")

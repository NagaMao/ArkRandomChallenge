from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from pyodide.ffi import run_sync
from workers import wsgi, WorkerEntrypoint
import json
import random
from data_fetcher import fetch_operators, fetch_stages, get_data_version

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

# Flask WSGI 入口（处理 fetch 请求）
Default = wsgi.entrypoint(app)


class ScheduledHandler(WorkerEntrypoint):
    """定时任务处理类：每日 04:00 (北京时间 = UTC 20:00) 刷新数据"""
    async def scheduled(self, controller, env, ctx):
        print("[定时任务] 开始刷新干员与关卡数据...")
        try:
            new_operators = await fetch_operators(env, force=True)
            new_stages = await fetch_stages(env, force=True)
            await env.DATA_KV.put("operators", json.dumps(new_operators, ensure_ascii=False))
            await env.DATA_KV.put("stages", json.dumps(new_stages, ensure_ascii=False))
            print(f"[定时任务] 刷新完成：{len(new_operators)} 位干员 / {len(new_stages)} 个关卡")
        except Exception as e:
            print(f"[定时任务] 刷新失败，保留旧数据：{e}")

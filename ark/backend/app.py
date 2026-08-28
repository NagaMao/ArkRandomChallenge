from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import json
import os
import random
from data_fetcher import fetch_operators, fetch_stages, get_data_version
import urllib3

# 禁用 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 设置静态文件夹为 frontend 目录
app = Flask(__name__, static_folder='../frontend', static_url_path='')
CORS(app)

# 黑名单存储
EXCLUDE_FILE = "exclude.json"

def load_exclude():
    """加载黑名单"""
    if os.path.exists(EXCLUDE_FILE):
        with open(EXCLUDE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"operators": [], "stages": []}

def save_exclude(exclude_data):
    """保存黑名单"""
    with open(EXCLUDE_FILE, "w", encoding="utf-8") as f:
        json.dump(exclude_data, f, ensure_ascii=False, indent=2)

# 加载数据
print("正在加载干员数据...")
operators_data = fetch_operators()
print(f"已加载 {len(operators_data)} 位干员")

print("正在加载关卡数据...")
stages_data = fetch_stages()
print(f"已加载 {len(stages_data)} 个关卡")

# ===== 前端路由 =====
@app.route('/')
def index():
    """返回首页"""
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/<path:path>')
def static_files(path):
    """返回静态资源（css, js 等）"""
    return send_from_directory(app.static_folder, path)

# ===== API 路由 =====
@app.route("/api/operators", methods=["GET"])
def get_operators():
    """获取干员列表，支持筛选"""
    stars_param = request.args.get("stars", "")
    professions_param = request.args.get("professions", "")
    exclude = load_exclude()
    
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
    exclude = load_exclude()
    result = [s for s in stages_data if s["id"] not in exclude["stages"]]
    return jsonify({
        "code": 0,
        "data": result,
        "total": len(result)
    })

@app.route("/api/random-team", methods=["POST"])
def random_team():
    """生成随机队伍"""
    data = request.json
    team_size = data.get("teamSize", 4)
    stars = data.get("stars", [1, 2, 3, 4, 5, 6])
    professions = data.get("professions", [])
    random_skill = data.get("randomSkill", True)
    
    exclude = load_exclude()
    
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
            # 按实际技能数量随机
            skill_idx = random.randint(0, len(op["skills"]) - 1)
            op["selected_skill"] = op["skills"][skill_idx]
        else:
            # 默认选第一个技能（但前端不显示）
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
    data = request.json
    action = data.get("action")  # "add" 或 "remove"
    target_type = data.get("type")  # "operator" 或 "stage"
    target_id = data.get("id")
    
    if not target_id:
        return jsonify({
            "code": 1,
            "msg": "缺少目标 ID"
        })
    
    exclude = load_exclude()
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
    
    save_exclude(exclude)
    
    return jsonify({
        "code": 0,
        "msg": "更新成功",
        "data": exclude
    })

@app.route("/api/exclude/list", methods=["GET"])
def get_exclude():
    """获取黑名单列表"""
    return jsonify({
        "code": 0,
        "data": load_exclude()
    })

@app.route("/api/version", methods=["GET"])
def version():
    """获取数据版本"""
    return jsonify(get_data_version())

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

if __name__ == "__main__":
    app.run(debug=True, port=5000)
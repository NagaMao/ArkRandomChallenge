import json
import os
import requests
from datetime import datetime
import urllib3

# 禁用 SSL 警告（仅本地测试用）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 数据源
DATA_URLS = {
    'operators': 'https://raw.githubusercontent.com/Kengxxiao/ArknightsGameData/master/zh_CN/gamedata/excel/character_table.json',
    'stages': 'https://raw.githubusercontent.com/Kengxxiao/ArknightsGameData/master/zh_CN/gamedata/excel/stage_table.json'
}

CACHE_DIR = "data_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

def fetch_operators():
    """获取干员数据"""
    cache_file = os.path.join(CACHE_DIR, "operators.json")
    
    if os.path.exists(cache_file):
        print("从缓存加载干员数据...")
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)
    
    print("从网络获取干员数据...")
    url = DATA_URLS['operators']
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        resp = requests.get(url, headers=headers, verify=False, timeout=30)
        print(f"状态码: {resp.status_code}")
        resp.raise_for_status()
        
        raw_data = resp.json()
        operators = parse_operators(raw_data)
        
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(operators, f, ensure_ascii=False, indent=2)
        
        print(f"成功获取 {len(operators)} 位干员数据")
        return operators
        
    except Exception as e:
        print(f"错误: {e}")
        raise

def fetch_stages():
    """获取关卡数据"""
    cache_file = os.path.join(CACHE_DIR, "stages.json")
    
    if os.path.exists(cache_file):
        print("从缓存加载关卡数据...")
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)
    
    print("从网络获取关卡数据...")
    url = DATA_URLS['stages']
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        resp = requests.get(url, headers=headers, verify=False, timeout=30)
        print(f"状态码: {resp.status_code}")
        resp.raise_for_status()
        
        raw_data = resp.json()
        stages = parse_stages(raw_data)
        
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(stages, f, ensure_ascii=False, indent=2)
        
        print(f"成功获取 {len(stages)} 个关卡数据")
        return stages
        
    except Exception as e:
        print(f"错误: {e}")
        raise

def parse_operators(raw_data):
    """
    解析原始干员数据 - 仅保留可获取的干员
    
    从原始数据中提取以下字段：
    - id: 干员唯一标识
    - name: 干员名称
    - star: 星级 (1-6)
    - profession: 职业（中文）
    - skills: 技能列表 [{skillId, name}]
    
    过滤条件：
    1. isNotObtainable = false（可获取）
    2. id 不以 token_ 或 trap_ 开头
    3. profession 不是 TOKEN 或 TRAP
    4. star >= 1（非0星）
    """
    result = []
    
    profession_map = {
        "CASTER": "术师",
        "MEDIC": "医疗",
        "PIONEER": "先锋",
        "SNIPER": "狙击",
        "TANK": "重装",
        "WARRIOR": "近卫",
        "SUPPORT": "辅助",
        "SPECIAL": "特种"
    }
    
    rarity_map = {
        "TIER_1": 1,
        "TIER_2": 2,
        "TIER_3": 3,
        "TIER_4": 4,
        "TIER_5": 5,
        "TIER_6": 6,
    }
    
    for char_id, char_data in raw_data.items():
        # 跳过没有名字的条目
        name = char_data.get("name", "")
        if not name:
            continue
        
        # ===== 过滤条件 =====
        
        # 1. 过滤不可获取的干员
        if char_data.get("isNotObtainable", False):
            continue
        
        # 2. 过滤 id 以 token_ 或 trap_ 开头的
        if char_id.startswith(("token_", "trap_")):
            continue
        
        # 3. 过滤 profession 为 TOKEN 或 TRAP 的
        prof_en = char_data.get("profession", "")
        if prof_en in ("TOKEN", "TRAP"):
            continue
        
        # 4. 过滤 0 星干员
        rarity_str = char_data.get("rarity", "TIER_0")
        star = rarity_map.get(rarity_str, 0)
        if star < 1:
            continue
        
        # ===== 提取技能 =====
        skills = []
        skill_data = char_data.get("skills", [])
        for i, skill in enumerate(skill_data, 1):
            skill_name = skill.get("skillName", f"技能{i}")
            if skill_name and skill_name.strip():
                skills.append({
                    "skillId": f"sk{i}",
                    "name": skill_name
                })
        
        # 职业映射
        profession = profession_map.get(prof_en, prof_en)
        
        result.append({
            "id": char_id,
            "name": name,
            "star": star,
            "profession": profession,
            "skills": skills
        })
    
    return result

def parse_stages(raw_data):
    """解析原始关卡数据"""
    result = []
    
    stages = raw_data.get("stages", {})
    for stage_id, stage_data in stages.items():
        if not stage_id.startswith(("main_", "act_")):
            continue
        
        code = stage_data.get("code", "")
        name = stage_data.get("name", "")
        difficulty = stage_data.get("difficulty", "NORMAL")
        stage_type = stage_data.get("stageType", "")
        
        if not name:
            name = code if code else stage_id
        
        # 根据不同类型生成显示名称
        if difficulty == "FOUR_STAR":
            display_name = f"突袭 {code} {name}"
        elif difficulty == "SIX_STAR":
            display_name = f"沙盘 {code} {name}"
        elif difficulty == "NORMAL":
            display_name = f"{code} {name}"
        else:
            display_name = f"关卡难度出错"
        
        result.append({
            "id": stage_id,
            "code": code,
            "name": name,
            "display_name": display_name,
            "chapter": stage_data.get("zoneId", ""),
            "isOpen": True,
            "difficulty": difficulty,
            "stage_type": stage_type
        })
    
    return result

def get_data_version():
    return {
        "version": "1.0.0",
        "lastUpdated": datetime.now().isoformat()
    }
import json
import os
import time
import requests
from datetime import datetime
import urllib3

# 禁用 SSL 警告（仅本地测试用）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 数据源。按顺序尝试，前一个失败自动回退到下一个。
# 优先使用国内的 CDN 镜像（jsDelivr / ghproxy），最后才回退到 GitHub 原始地址。
DATA_SOURCES = {
    'operators': [
        'https://cdn.jsdelivr.net/gh/Kengxxiao/ArknightsGameData@master/zh_CN/gamedata/excel/character_table.json',
        'https://raw.githubusercontent.com/Kengxxiao/ArknightsGameData/master/zh_CN/gamedata/excel/character_table.json',
    ],
    'stages': [
        'https://cdn.jsdelivr.net/gh/Kengxxiao/ArknightsGameData@master/zh_CN/gamedata/excel/stage_table.json',
        'https://raw.githubusercontent.com/Kengxxiao/ArknightsGameData/master/zh_CN/gamedata/excel/stage_table.json',
    ],
}

# 单个数据源的超时（连接, 读取）
REQUEST_TIMEOUT = (10, 60)
# 每个数据源的重试次数
REQUEST_RETRIES = 2

CACHE_DIR = "data_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

# 缓存有效期（秒）。24 小时，用于服务启动时判断缓存是否过期
CACHE_TTL = 24 * 60 * 60

def _cache_is_fresh(cache_file):
    """判断缓存文件是否存在且未超过有效期"""
    if not os.path.exists(cache_file):
        return False
    age = time.time() - os.path.getmtime(cache_file)
    return age < CACHE_TTL

def _load_cache(cache_file):
    """读取缓存文件，不存在则返回 None"""
    if os.path.exists(cache_file):
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return None

def _download(urls, label, parse_func, cache_file):
    """按顺序尝试多个数据源下载并解析数据，成功后写入缓存。

    Args:
        urls: 数据源 URL 列表，按优先级排列
        label: 用于日志的标签（如 "干员"）
        parse_func: 原始 JSON -> 结果列表 的解析函数
        cache_file: 缓存文件路径

    Returns:
        (数据列表, 是否成功)。全部失败时返回 (None, False)。
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }

    for url in urls:
        for attempt in range(1, REQUEST_RETRIES + 1):
            try:
                print(f"从网络获取{label}数据 ({url}) 第 {attempt} 次尝试...")
                resp = requests.get(url, headers=headers, verify=False, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()

                raw_data = resp.json()
                result = parse_func(raw_data)

                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)

                print(f"成功获取 {len(result)} 条{label}数据")
                return result, True
            except Exception as e:
                print(f"获取{label}数据失败: {e}")

    return None, False

def fetch_operators(force=False):
    """获取干员数据

    Args:
        force: True 时忽略缓存，强制从网络刷新
    """
    cache_file = os.path.join(CACHE_DIR, "operators.json")

    if not force and _cache_is_fresh(cache_file):
        print("从缓存加载干员数据...")
        return _load_cache(cache_file)

    data, ok = _download(DATA_SOURCES['operators'], "干员", parse_operators, cache_file)
    if ok:
        return data

    # 网络全部失败：回退到旧缓存（即使已过期）
    fallback = _load_cache(cache_file)
    if fallback is not None:
        print("警告：网络获取干员数据失败，回退使用旧缓存（数据可能不是最新）")
        return fallback

    raise RuntimeError("无法获取干员数据：网络不可用且本地无缓存")

def fetch_stages(force=False):
    """获取关卡数据

    Args:
        force: True 时忽略缓存，强制从网络刷新
    """
    cache_file = os.path.join(CACHE_DIR, "stages.json")

    if not force and _cache_is_fresh(cache_file):
        print("从缓存加载关卡数据...")
        return _load_cache(cache_file)

    data, ok = _download(DATA_SOURCES['stages'], "关卡", parse_stages, cache_file)
    if ok:
        return data

    # 网络全部失败：回退到旧缓存（即使已过期）
    fallback = _load_cache(cache_file)
    if fallback is not None:
        print("警告：网络获取关卡数据失败，回退使用旧缓存（数据可能不是最新）")
        return fallback

    raise RuntimeError("无法获取关卡数据：网络不可用且本地无缓存")

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
    """返回数据版本信息，lastUpdated 取缓存文件的实际更新时间"""
    op_cache = os.path.join(CACHE_DIR, "operators.json")
    st_cache = os.path.join(CACHE_DIR, "stages.json")

    mtimes = [os.path.getmtime(p) for p in (op_cache, st_cache) if os.path.exists(p)]
    last_updated = datetime.fromtimestamp(max(mtimes)).isoformat() if mtimes else None

    return {
        "version": "1.0.0",
        "lastUpdated": last_updated
    }
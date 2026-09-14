import json
from workers import fetch

# 数据源。按顺序尝试，前一个失败自动回退到下一个。
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


async def _download(urls, label, parse_func):
    """按顺序尝试多个数据源下载并解析数据。

    Args:
        urls: 数据源 URL 列表，按优先级排列
        label: 用于日志的标签（如 "干员"）
        parse_func: 原始 JSON -> 结果列表 的解析函数

    Returns:
        (数据列表, 是否成功)。全部失败时返回 (None, False)。
    """
    for url in urls:
        try:
            print(f"从网络获取{label}数据 ({url})...")
            resp = await fetch(url)
            if resp.status != 200:
                print(f"获取{label}数据失败: HTTP {resp.status}")
                continue

            text = await resp.text()
            raw_data = json.loads(text)
            result = parse_func(raw_data)

            print(f"成功获取 {len(result)} 条{label}数据")
            return result, True
        except Exception as e:
            print(f"获取{label}数据失败: {e}")

    return None, False


async def fetch_operators(env, force=False):
    """获取干员数据

    Args:
        env: Worker env 对象（用于访问 KV）
        force: True 时忽略缓存，强制从网络刷新
    """
    if not force:
        cached = await env.DATA_KV.get("operators")
        if cached is not None:
            return json.loads(str(cached))

    data, ok = await _download(DATA_SOURCES['operators'], "干员", parse_operators)
    if ok:
        await env.DATA_KV.put("operators", json.dumps(data, ensure_ascii=False))
        return data

    # 网络全部失败：回退到旧缓存
    cached = await env.DATA_KV.get("operators")
    if cached is not None:
        print("警告：网络获取干员数据失败，回退使用旧缓存")
        return json.loads(str(cached))

    raise RuntimeError("无法获取干员数据：网络不可用且 KV 无缓存")


async def fetch_stages(env, force=False):
    """获取关卡数据

    Args:
        env: Worker env 对象（用于访问 KV）
        force: True 时忽略缓存，强制从网络刷新
    """
    if not force:
        cached = await env.DATA_KV.get("stages")
        if cached is not None:
            return json.loads(str(cached))

    data, ok = await _download(DATA_SOURCES['stages'], "关卡", parse_stages)
    if ok:
        await env.DATA_KV.put("stages", json.dumps(data, ensure_ascii=False))
        return data

    # 网络全部失败：回退到旧缓存
    cached = await env.DATA_KV.get("stages")
    if cached is not None:
        print("警告：网络获取关卡数据失败，回退使用旧缓存")
        return json.loads(str(cached))

    raise RuntimeError("无法获取关卡数据：网络不可用且 KV 无缓存")


def parse_operators(raw_data):
    """
    解析原始干员数据 - 仅保留可获取的干员
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
        name = char_data.get("name", "")
        if not name:
            continue

        if char_data.get("isNotObtainable", False):
            continue

        if char_id.startswith(("token_", "trap_")):
            continue

        prof_en = char_data.get("profession", "")
        if prof_en in ("TOKEN", "TRAP"):
            continue

        rarity_str = char_data.get("rarity", "TIER_0")
        star = rarity_map.get(rarity_str, 0)
        if star < 1:
            continue

        skills = []
        skill_data = char_data.get("skills", [])
        for i, skill in enumerate(skill_data, 1):
            skill_name = skill.get("skillName", f"技能{i}")
            if skill_name and skill_name.strip():
                skills.append({
                    "skillId": f"sk{i}",
                    "name": skill_name
                })

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


def get_data_version(env=None):
    """返回数据版本信息"""
    return {
        "version": "1.0.0",
        "lastUpdated": None  # 在 Workers 环境中，版本时间由 KV 缓存写入时间决定
    }

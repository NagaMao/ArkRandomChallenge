"""森空岛（Skland）API 封装 —— Cloudflare Worker (Pyodide) 版本。

与本地版 ark/backend/skland.py 逻辑完全等价，唯一区别是：
本地版用同步 requests，这里改用 Worker 运行时的异步 fetch。

实现完整的登录链路：
    1. 手机密码 / 手机验证码登录  -> 鹰角网络通行证 token
    2. token -> OAuth2 授权 code
    3. code  -> 森空岛 cred + token（后续所有 zonai 接口的身份凭证与签名密钥）
    4. cred + token -> 绑定角色列表（player/binding）
    5. cred + token + uid -> 玩家游戏数据（player/info），从 data.chars 取出拥有干员

签名算法（当前客户端版本，与社区实现对齐）：

    timestamp = 当前秒级时间戳 - 1
    header_for_sign = {"platform": "", "timestamp": "", "dId": "", "vName": ""}
    header_ca = {**header_for_sign, "timestamp": str(timestamp)}
    header_ca_str = json.dumps(header_ca, separators=(",", ":"))

    # GET 请求：query_params 为 URL 的 query 字符串（不含 "?"）
    # POST 请求：query_params 为 json.dumps(body)
    secret = f"{path}{query_params}{timestamp}{header_ca_str}"
    hex_secret = HMAC_SHA256(key=cred_token, msg=secret).hexdigest()
    sign = MD5(hex_secret).hexdigest()

注意：签名密钥是「用 code 换取 cred 时返回的 token 字段」，不是 cred 本身。
"""

import hashlib
import hmac
import json
import time
from urllib.parse import urlparse

from js import Object
from js import fetch as _js_fetch
from pyodide.ffi import to_js as _to_js


def to_js(obj):
    """Python dict -> JavaScript Object（官方推荐的转换方式）。"""
    return _to_js(obj, dict_converter=Object.fromEntries)


async def _do_fetch(url, init):
    """发起一次 fetch 请求。

    直接使用 JavaScript 全局 fetch(input, init)（Cloudflare 官方文档明确
    fetch() 是 JS 全局函数，可通过 FFI 调用），避免 workers.fetch 包装函数
    参数形态不确定带来的问题。init 必须是 JS Object（由 to_js 转换）。
    """
    return await _js_fetch(url, init)


# ===== 常量配置 =====

# 森空岛 App 固定的 OAuth2 appCode
SKLAND_APP_CODE = "4ca99fa6b56cc2ba"

# 模拟客户端的请求头信息（当前客户端版本）
SKLAND_HEADERS = {
    "User-Agent": (
        "Skland/1.32.1 (com.hypergryph.skland; build:103201004; "
        "Android 33; ) Okhttp/4.11.0"
    ),
    "Accept-Encoding": "gzip",
    "Connection": "close",
}


class SklandError(Exception):
    """森空岛接口调用异常，message 为面向用户的错误说明。"""

    def __init__(self, message, raw=None):
        super().__init__(message)
        self.message = message
        self.raw = raw


# ===== 签名相关 =====

def _generate_sign(cred_token, path, query_params, timestamp):
    """生成森空岛接口签名（纯计算，无 IO）。"""
    header_for_sign = {"platform": "", "timestamp": "", "dId": "", "vName": ""}
    header_ca = {**header_for_sign, "timestamp": str(timestamp)}
    header_ca_str = json.dumps(header_ca, separators=(",", ":"))

    secret = f"{path}{query_params}{timestamp}{header_ca_str}"
    hex_secret = hmac.new(
        cred_token.encode("utf-8"), secret.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return hashlib.md5(hex_secret.encode("utf-8")).hexdigest()


def _build_sign_header(cred, cred_token, url, method, json_body=None):
    """构造带签名的请求头（纯计算，无 IO）。"""
    timestamp = str(int(time.time()) - 1)
    parsed = urlparse(url)
    path = parsed.path

    if method == "post":
        query_params = json.dumps(json_body) if json_body is not None else ""
    else:
        query_params = parsed.query

    sign = _generate_sign(cred_token, path, query_params, timestamp)

    headers = dict(SKLAND_HEADERS)
    headers.update({
        "cred": cred,
        "sign": sign,
        "timestamp": timestamp,
        "dId": "",
        "platform": "",
        "vName": "",
    })
    return headers


# ===== HTTP 辅助 =====

async def _post_json(url, payload, extra_headers=None):
    """发起 POST 请求，返回解析后的 JSON（dict）。

    使用 Worker 运行时的 fetch。请求选项通过 to_js 转成 JS 对象，
    保证 Pyodide 能正确识别 method / headers / body。
    """
    headers = dict(extra_headers or {})
    headers.setdefault("Content-Type", "application/json")
    body = json.dumps(payload)
    init = to_js({"method": "POST", "headers": headers, "body": body})
    try:
        resp = await _do_fetch(url, init)
    except Exception as e:
        raise SklandError(f"网络请求失败：{e}")

    text = await resp.text()
    try:
        return json.loads(str(text))
    except ValueError:
        raise SklandError(f"接口返回非 JSON 内容（HTTP {resp.status}）")


async def _get_json(url, headers):
    """发起 GET 请求，返回解析后的 JSON（dict）。"""
    init = to_js({"method": "GET", "headers": headers})
    try:
        resp = await _do_fetch(url, init)
    except Exception as e:
        raise SklandError(f"网络请求失败：{e}")

    text = await resp.text()
    try:
        return json.loads(str(text))
    except ValueError:
        raise SklandError(f"接口返回非 JSON 内容（HTTP {resp.status}）")


async def _skland_get(url, cred, cred_token):
    """发起一次带签名的 GET 请求。"""
    headers = _build_sign_header(cred, cred_token, url, "get")
    return await _get_json(url, headers)


def _check_hypergryph(data, action):
    """校验鹰角（as.hypergryph.com）接口返回结果。"""
    if data.get("status") != 0:
        msg = data.get("msg") or data.get("message") or "未知错误"
        raise SklandError(f"{action}失败：{msg}", raw=data)
    return data


def _check_skland(data, action):
    """校验森空岛（zonai.skland.com）接口返回结果。"""
    code = data.get("code")
    if code not in (0, None):
        msg = data.get("message") or data.get("msg") or "未知错误"
        raise SklandError(f"{action}失败：{msg}", raw=data)
    return data


# ===== 登录：获取鹰角 token =====

async def login_by_password(phone, password):
    """手机号 + 密码登录，返回鹰角网络通行证 token。"""
    url = "https://as.hypergryph.com/user/auth/v1/token_by_phone_password"
    data = await _post_json(url, {"phone": phone, "password": password})
    _check_hypergryph(data, "账号密码登录")
    token = data.get("data", {}).get("token")
    if not token:
        raise SklandError("登录成功但未返回 token")
    return token


async def send_phone_code(phone):
    """发送手机验证码（type=2 表示用于登录）。"""
    url = "https://as.hypergryph.com/general/v1/send_phone_code"
    data = await _post_json(url, {"phone": phone, "type": 2})
    _check_hypergryph(data, "发送验证码")
    return True


async def login_by_phone_code(phone, code):
    """手机号 + 验证码登录，返回鹰角网络通行证 token。"""
    url = "https://as.hypergryph.com/user/auth/v2/token_by_phone_code"
    data = await _post_json(url, {"phone": phone, "code": code})
    _check_hypergryph(data, "验证码登录")
    token = data.get("data", {}).get("token")
    if not token:
        raise SklandError("登录成功但未返回 token")
    return token


# ===== 用 token 换取森空岛 cred =====

async def _get_oauth_code(token):
    """用鹰角 token 换取 OAuth2 授权 code。"""
    url = "https://as.hypergryph.com/user/oauth2/v2/grant"
    payload = {"token": token, "appCode": SKLAND_APP_CODE, "type": 0}
    data = await _post_json(url, payload, extra_headers=dict(SKLAND_HEADERS))
    _check_hypergryph(data, "获取授权代码")
    code = data.get("data", {}).get("code")
    if not code:
        raise SklandError("未获取到 OAuth 授权 code")
    return code


async def get_cred_by_token(token):
    """用鹰角 token 换取森空岛凭证。

    Returns:
        dict，含 {"cred": str, "token": str}，其中 token 为后续签名密钥。
    """
    code = await _get_oauth_code(token)
    return await get_cred_by_code(code)


async def get_cred_by_code(code):
    """用 OAuth2 授权 code 换取森空岛 cred。

    注意：此接口不需要签名（此时还没有 cred/token）。
    """
    url = "https://zonai.skland.com/api/v1/user/auth/generate_cred_by_code"
    data = await _post_json(
        url, {"kind": 1, "code": code},
        extra_headers=dict(SKLAND_HEADERS),
    )
    _check_skland(data, "获取 cred")
    cred_data = data.get("data", {}) or {}
    cred = cred_data.get("cred")
    sign_token = cred_data.get("token")
    if not cred:
        raise SklandError("未获取到 cred")
    if not sign_token:
        raise SklandError("未获取到签名 token")
    return {"cred": cred, "token": sign_token}


# ===== 使用 cred 拉取数据 =====

async def get_binding_list(cred, cred_token):
    """获取玩家绑定的游戏角色列表。"""
    url = "https://zonai.skland.com/api/v1/game/player/binding"
    data = await _skland_get(url, cred, cred_token)
    _check_skland(data, "获取绑定角色列表")
    return data.get("data", {}).get("list", []) or []


async def get_player_info(cred, cred_token, uid):
    """获取玩家游戏内数据（体积较大，含 data.chars 拥有干员列表）。"""
    url = f"https://zonai.skland.com/api/v1/game/player/info?uid={uid}"
    data = await _skland_get(url, cred, cred_token)
    _check_skland(data, "获取玩家数据")
    return data.get("data", {}) or {}


async def get_owned_char_ids(cred, cred_token, uid):
    """获取玩家拥有的干员 charId 集合。

    Skland 的 data.chars 每项含 charId（如 "char_1013_chen2"），
    与本地全量干员数据的 id 字段格式完全一致，可直接用于过滤。

    Returns:
        set[str]，玩家拥有的干员 id 集合
    """
    info = await get_player_info(cred, cred_token, uid)
    chars = info.get("chars", []) or []
    owned = set()
    for c in chars:
        char_id = c.get("charId")
        if char_id:
            owned.add(char_id)
    return owned

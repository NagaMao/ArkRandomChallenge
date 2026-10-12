"""森空岛（Skland）API 封装。

实现完整的登录链路，用于获取玩家绑定的游戏角色以及其拥有的干员列表：

    1. 手机密码 / 手机验证码登录  -> 鹰角网络通行证 token
    2. token -> OAuth2 授权 code
    3. code  -> 森空岛 cred + token（后续所有 zonai 接口的身份凭证与签名密钥）
    4. cred + token -> 绑定角色列表（player/binding）
    5. cred + token + uid -> 玩家游戏数据（player/info），从 data.chars 取出拥有干员

签名说明（重要）
----------------
zonai.skland.com 的部分接口（player/binding、player/info 等）需要签名请求头，
否则会返回 HTTP 401 / code 10000「请求异常」。

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

请求头：
    cred:        森空岛凭证
    sign:        上述签名
    timestamp:   与签名中一致的时间戳
    dId:         空字符串（本实现不申请真实 dId）
    platform:    空字符串
    vName:       空字符串

注意：签名密钥是「用 code 换取 cred 时返回的 token 字段」，不是 cred 本身，
也不是固定盐值。务必在登录后妥善保存 cred 与 token 两个值。

本模块只负责「取数据」，不负责持久化凭证。
"""

import hashlib
import hmac
import json
import time
import urllib3
from urllib.parse import urlparse

import requests

# 禁用 SSL 警告（与项目其它模块保持一致）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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

REQUEST_TIMEOUT = (10, 30)


class SklandError(Exception):
    """森空岛接口调用异常，message 为面向用户的错误说明。"""

    def __init__(self, message, raw=None):
        super().__init__(message)
        self.message = message
        self.raw = raw


# ===== 签名相关 =====

def _generate_sign(cred_token, path, query_params, timestamp):
    """生成森空岛接口签名。

    Args:
        cred_token: 换取 cred 时返回的 token（签名密钥）
        path: 请求路径（不含 query），如 "/api/v1/game/player/binding"
        query_params: GET 为 URL query 字符串（不含 "?"）；POST 为 json.dumps(body)
        timestamp: 秒级时间戳（字符串）

    Returns:
        签名字符串（MD5(HMAC_SHA256(cred_token, secret)) 的 hex）
    """
    header_for_sign = {"platform": "", "timestamp": "", "dId": "", "vName": ""}
    header_ca = {**header_for_sign, "timestamp": str(timestamp)}
    header_ca_str = json.dumps(header_ca, separators=(",", ":"))

    secret = f"{path}{query_params}{timestamp}{header_ca_str}"
    hex_secret = hmac.new(
        cred_token.encode("utf-8"), secret.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return hashlib.md5(hex_secret.encode("utf-8")).hexdigest()


def _build_sign_header(cred, cred_token, url, method, json_body=None):
    """构造带签名的请求头。

    Args:
        cred: 森空岛凭证
        cred_token: 签名密钥（换取 cred 时返回的 token）
        url: 完整请求 URL
        method: "get" 或 "post"
        json_body: POST 请求体（dict 或 None）

    Returns:
        headers dict
    """
    timestamp = str(int(time.time()) - 1)
    parsed = urlparse(url)
    path = parsed.path

    if method == "post":
        query_params = (
            json.dumps(json_body) if json_body is not None else ""
        )
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


def _skland_get(url, cred, cred_token):
    """发起一次带签名的 GET 请求。"""
    headers = _build_sign_header(cred, cred_token, url, "get")
    try:
        resp = requests.get(
            url, headers=headers, timeout=REQUEST_TIMEOUT, verify=False,
        )
    except requests.RequestException as e:
        raise SklandError(f"网络请求失败：{e}")
    try:
        return resp.json()
    except ValueError:
        raise SklandError(f"接口返回非 JSON 内容（HTTP {resp.status_code}）")


def _check_hypergryph(data, action):
    """校验鹰角（as.hypergryph.com）接口返回结果。"""
    if data.get("status") != 0:
        msg = data.get("msg") or data.get("message") or "未知错误"
        raise SklandError(f"{action}失败：{msg}", raw=data)
    return data


def _check_skland(data, action):
    """校验森空岛（zonai.skland.com）接口返回结果。

    森空岛成功时 code 为 0 或不存在 code 字段且带 data。
    """
    code = data.get("code")
    if code not in (0, None):
        msg = data.get("message") or data.get("msg") or "未知错误"
        raise SklandError(f"{action}失败：{msg}", raw=data)
    return data


# ===== 登录：获取鹰角 token =====

def login_by_password(phone, password):
    """手机号 + 密码登录，返回鹰角网络通行证 token。"""
    url = "https://as.hypergryph.com/user/auth/v1/token_by_phone_password"
    payload = {"phone": phone, "password": password}

    try:
        resp = requests.post(
            url, json=payload,
            headers={"Content-Type": "application/json"},
            timeout=REQUEST_TIMEOUT, verify=False,
        )
        data = resp.json()
    except requests.RequestException as e:
        raise SklandError(f"网络请求失败：{e}")
    except ValueError:
        raise SklandError("登录接口返回非 JSON 内容")

    _check_hypergryph(data, "账号密码登录")
    token = data.get("data", {}).get("token")
    if not token:
        raise SklandError("登录成功但未返回 token")
    return token


def send_phone_code(phone):
    """发送手机验证码（type=2 表示用于登录）。"""
    url = "https://as.hypergryph.com/general/v1/send_phone_code"
    payload = {"phone": phone, "type": 2}

    try:
        resp = requests.post(
            url, json=payload,
            headers={"Content-Type": "application/json"},
            timeout=REQUEST_TIMEOUT, verify=False,
        )
        data = resp.json()
    except requests.RequestException as e:
        raise SklandError(f"网络请求失败：{e}")
    except ValueError:
        raise SklandError("发送验证码接口返回非 JSON 内容")

    _check_hypergryph(data, "发送验证码")
    return True


def login_by_phone_code(phone, code):
    """手机号 + 验证码登录，返回鹰角网络通行证 token。"""
    url = "https://as.hypergryph.com/user/auth/v2/token_by_phone_code"
    payload = {"phone": phone, "code": code}

    try:
        resp = requests.post(
            url, json=payload,
            headers={"Content-Type": "application/json"},
            timeout=REQUEST_TIMEOUT, verify=False,
        )
        data = resp.json()
    except requests.RequestException as e:
        raise SklandError(f"网络请求失败：{e}")
    except ValueError:
        raise SklandError("验证码登录接口返回非 JSON 内容")

    _check_hypergryph(data, "验证码登录")
    token = data.get("data", {}).get("token")
    if not token:
        raise SklandError("登录成功但未返回 token")
    return token


# ===== 用 token 换取森空岛 cred =====

def _get_oauth_code(token):
    """用鹰角 token 换取 OAuth2 授权 code。"""
    url = "https://as.hypergryph.com/user/oauth2/v2/grant"
    payload = {"token": token, "appCode": SKLAND_APP_CODE, "type": 0}

    try:
        resp = requests.post(
            url, json=payload,
            headers={**SKLAND_HEADERS, "Content-Type": "application/json"},
            timeout=REQUEST_TIMEOUT, verify=False,
        )
        data = resp.json()
    except requests.RequestException as e:
        raise SklandError(f"网络请求失败：{e}")
    except ValueError:
        raise SklandError("OAuth 接口返回非 JSON 内容")

    _check_hypergryph(data, "获取授权代码")
    code = data.get("data", {}).get("code")
    if not code:
        raise SklandError("未获取到 OAuth 授权 code")
    return code


def get_cred_by_token(token):
    """用鹰角 token 换取森空岛凭证。

    Returns:
        dict，含 {"cred": str, "token": str}，其中 token 为后续签名密钥。
    """
    code = _get_oauth_code(token)
    return get_cred_by_code(code)


def get_cred_by_code(code):
    """用 OAuth2 授权 code 换取森空岛 cred。

    注意：此接口不需要签名（此时还没有 cred/token）。

    Returns:
        dict，含 {"cred": str, "token": str}
    """
    url = "https://zonai.skland.com/api/v1/user/auth/generate_cred_by_code"
    payload = {"kind": 1, "code": code}

    try:
        resp = requests.post(
            url, json=payload,
            headers={**SKLAND_HEADERS, "Content-Type": "application/json"},
            timeout=REQUEST_TIMEOUT, verify=False,
        )
        data = resp.json()
    except requests.RequestException as e:
        raise SklandError(f"网络请求失败：{e}")
    except ValueError:
        raise SklandError("获取 cred 接口返回非 JSON 内容")

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

def get_binding_list(cred, cred_token):
    """获取玩家绑定的游戏角色列表。

    Returns:
        list，每项形如：
        {
            "appCode": "arknights",
            "appName": "明日方舟",
            "bindingList": [
                {"uid": "xxx", "channelMasterId": "1", "channelName": "官服",
                 "nickName": "xxx", "isDefault": true, "isOfficial": true}
            ]
        }
    """
    url = "https://zonai.skland.com/api/v1/game/player/binding"
    data = _skland_get(url, cred, cred_token)
    _check_skland(data, "获取绑定角色列表")
    return data.get("data", {}).get("list", []) or []


def get_player_info(cred, cred_token, uid):
    """获取玩家游戏内数据（体积较大，含 data.chars 拥有干员列表）。

    Args:
        cred: 森空岛凭证
        cred_token: 签名密钥
        uid: 游戏 uid

    Returns:
        完整的 data 字段（dict）
    """
    url = f"https://zonai.skland.com/api/v1/game/player/info?uid={uid}"
    data = _skland_get(url, cred, cred_token)
    _check_skland(data, "获取玩家数据")
    return data.get("data", {}) or {}


def get_owned_char_ids(cred, cred_token, uid):
    """获取玩家拥有的干员 charId 集合。

    Skland 的 data.chars 每项含 charId（如 "char_1013_chen2"），
    与本地全量干员数据的 id 字段格式完全一致，可直接用于过滤。

    Returns:
        set[str]，玩家拥有的干员 id 集合
    """
    info = get_player_info(cred, cred_token, uid)
    chars = info.get("chars", []) or []
    owned = set()
    for c in chars:
        char_id = c.get("charId")
        if char_id:
            owned.add(char_id)
    return owned

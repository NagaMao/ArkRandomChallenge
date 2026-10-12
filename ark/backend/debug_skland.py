"""森空岛接口诊断脚本。

用法：
    python debug_skland.py

会依次执行：
    1. 手机号 + 密码登录 -> 鹰角 token
    2. token -> OAuth2 code -> 森空岛 cred + 签名 token
    3. 调用 player/binding，打印绑定的角色列表
    4. 对第一个角色调用 player/info，打印拥有干员数量

本脚本复用 skland.py 的真实实现，因此结果与后端接口完全一致。
凭证只在本脚本内存中使用，不会写入任何文件。
"""

import json
import skland
def main():
    phone = input("手机号: ").strip()
    password = input("密码: ").strip()

    print("\n[1] 手机密码登录...")
    try:
        token = skland.login_by_password(phone, password)
    except skland.SklandError as e:
        print("!! 登录失败：", e.message)
        return
    print("OK, 通行证 token 已获取")

    print("\n[2] 换取 cred + 签名 token...")
    try:
        cred_info = skland.get_cred_by_token(token)
    except skland.SklandError as e:
        print("!! 换取 cred 失败：", e.message)
        return
    cred = cred_info["cred"]
    cred_token = cred_info["token"]
    print("cred =", cred)
    print("token =", cred_token)

    print("\n[3] 获取绑定角色列表（player/binding）...")
    try:
        bindings = skland.get_binding_list(cred, cred_token)
    except skland.SklandError as e:
        print("!! 获取绑定角色失败：", e.message)
        print("   原始返回：", json.dumps(e.raw, ensure_ascii=False))
        return
    print("OK")
    print(json.dumps(bindings, ensure_ascii=False, indent=2))

    arknights = next((b for b in bindings if b.get("appCode") == "arknights"), None)
    chars = arknights.get("bindingList", []) if arknights else []
    if not chars:
        print("\n!! 未找到明日方舟角色")
        return

    first_uid = chars[0]["uid"]
    print(f"\n[4] 获取角色 {first_uid} 的干员数据（player/info）...")
    try:
        owned = skland.get_owned_char_ids(cred, cred_token, first_uid)
    except skland.SklandError as e:
        print("!! 获取干员数据失败：", e.message)
        print("   原始返回：", json.dumps(e.raw, ensure_ascii=False))
        return
    print(f"OK，共拥有 {len(owned)} 位干员")
    print("示例：", sorted(owned)[:10])

    print("\n===== 全部通过 =====")
if __name__ == "__main__":
    main()


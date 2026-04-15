#!/usr/bin/env python3
"""
多平台自动发布工具
用法:
  python3 publish.py --platform xhs --image ~/Downloads/xxx.png --title "标题" --content "内容"
  python3 publish.py --platform xhs --image ~/Downloads/xxx.png --title "标题" --content "内容" --phone 18811210168

支持平台: xhs (小红书)
"""

import argparse
import subprocess
import sqlite3
import re
import time
import sys
import os
from typing import Optional


PHONE = "18811210168"  # 默认手机号


# ──────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────

def run_applescript(script: str) -> str:
    """通过 stdin 传递脚本，支持多行 AppleScript"""
    result = subprocess.run(
        ["osascript", "-"],
        input=script,
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"AppleScript 错误: {result.stderr.strip()}")
    return result.stdout.strip()


def safari_js(js: str) -> str:
    """在 Safari 当前标签页执行 JavaScript"""
    # 转义双引号和反斜杠
    escaped = js.replace('\\', '\\\\').replace('"', '\\"')
    script = f'tell application "Safari" to do JavaScript "{escaped}" in current tab of window 1'
    return run_applescript(script)


def safari_url() -> str:
    return run_applescript('tell application "Safari" to get URL of current tab of window 1')


def safari_navigate(url: str) -> None:
    run_applescript(f'tell application "Safari" to set URL of current tab of window 1 to "{url}"')
    time.sleep(3)


def read_latest_sms_code(keyword="小红书") -> Optional[str]:
    """从 macOS Messages DB 读取最新验证码"""
    db_path = os.path.expanduser("~/Library/Messages/chat.db")
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT text FROM message WHERE text LIKE ? ORDER BY date DESC LIMIT 5",
            (f"%{keyword}%验证码%",)
        )
        rows = cur.fetchall()
        conn.close()
        for row in rows:
            text = row[0] or ""
            match = re.search(r'验证码[是：:]\s*(\d{4,8})', text)
            if match:
                return match.group(1)
    except Exception as e:
        print(f"  [警告] 读取 Messages DB 失败: {e}")
    return None


def sheet_count() -> int:
    try:
        result = run_applescript(
            'tell application "System Events" to tell process "Safari" to return count of sheets of window 1'
        )
        return int(result)
    except Exception:
        return 0


def open_file_picker_and_select(image_path: str) -> bool:
    """触发文件选择器并选择图片"""
    abs_path = os.path.expanduser(image_path)

    # 触发 file input
    safari_js("var fi=document.querySelector('input[type=file]'); fi && fi.click();")
    time.sleep(2)

    sc = sheet_count()
    print(f"  [debug] 文件选择器 sheets={sc}")
    if sc == 0:
        print("  [警告] 文件选择器未打开")
        return False

    # 激活 Safari 确保键盘事件能送达
    run_applescript('tell application "Safari" to activate')
    time.sleep(0.5)

    # Cmd+Shift+G 打开路径输入（在 Safari 进程内发送）
    run_applescript('''
tell application "System Events"
  tell process "Safari"
    set frontmost to true
    keystroke "g" using {command down, shift down}
  end tell
end tell
''')
    time.sleep(1.5)

    # 检查子sheet是否打开
    try:
        sub_sc = int(run_applescript(
            'tell application "System Events" to tell process "Safari" to return count of sheets of sheet 1 of window 1'
        ))
    except Exception:
        sub_sc = 0
    print(f"  [debug] Cmd+Shift+G 后 sub-sheets={sub_sc}")

    # 用 keystroke 真实打字输入路径
    run_applescript('tell application "System Events" to keystroke "a" using {command down}')
    time.sleep(0.2)
    run_applescript(f'tell application "System Events" to keystroke "{abs_path}"')
    time.sleep(0.5)

    # 回车确认路径（子sheet 或当前焦点）
    run_applescript('tell application "System Events" to key code 36')
    time.sleep(2)

    # 检查状态并对主sheet回车选择文件
    for attempt in range(3):
        sc_now = sheet_count()
        print(f"  [debug] 回车后第{attempt+1}次 sheets={sc_now}")
        if sc_now == 0:
            return True
        # 检查是否还有子sheet
        try:
            sub_now = int(run_applescript(
                'tell application "System Events" to tell process "Safari" to return count of sheets of sheet 1 of window 1'
            ))
        except Exception:
            sub_now = 0
        if sub_now == 0:
            # 对主sheet回车
            run_applescript('tell application "System Events" to key code 36')
        else:
            # 对子sheet回车
            run_applescript('tell application "System Events" to key code 36')
        time.sleep(2)

    time.sleep(3)
    final_sc = sheet_count()
    print(f"  [debug] 最终 sheets={final_sc}")
    return final_sc == 0


# ──────────────────────────────────────────────
# 平台: 小红书 (XHS)
# ──────────────────────────────────────────────

def xhs_login(phone: str) -> bool:
    """登录小红书创作者中心（如已登录则跳过）"""
    url = safari_url()
    if "creator.xiaohongshu.com" in url and "login" not in url:
        print("  [跳过] 小红书已登录")
        return True

    print(f"  [1/4] 导航到登录页...")
    safari_navigate("https://creator.xiaohongshu.com/login")
    time.sleep(2)

    print(f"  [2/4] 填手机号 {phone}...")
    safari_js(f"""
        var inputs = Array.from(document.querySelectorAll('input'));
        var phone = inputs.find(i => i.placeholder === '手机号');
        if(phone) {{
            Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set.call(phone,'{phone}');
            phone.dispatchEvent(new Event('input',{{bubbles:true}}));
        }}
    """)
    time.sleep(0.5)

    print("  [3/4] 发送验证码...")
    safari_js("""
        var btn = Array.from(document.querySelectorAll('*')).find(
            el => el.children.length===0 && el.innerText && el.innerText.trim()==='发送验证码'
        );
        btn && btn.click();
    """)

    print("  [3/4] 等待短信...")
    code = None
    for attempt in range(12):  # 最多等60秒
        time.sleep(5)
        code = read_latest_sms_code("小红书")
        if code:
            print(f"  [3/4] 收到验证码: {code}")
            break
        print(f"  [3/4] 等待中... ({(attempt+1)*5}s)")

    if not code:
        print("  [错误] 未收到验证码，请手动检查短信")
        return False

    print("  [4/4] 填验证码并登录...")
    safari_js(f"""
        var inputs = Array.from(document.querySelectorAll('input'));
        var codeInput = inputs.find(i => i.placeholder === '验证码');
        if(codeInput) {{
            Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set.call(codeInput,'{code}');
            codeInput.dispatchEvent(new Event('input',{{bubbles:true}}));
            codeInput.dispatchEvent(new Event('change',{{bubbles:true}}));
        }}
    """)
    time.sleep(0.5)
    safari_js("""
        var btn = Array.from(document.querySelectorAll('button')).find(b => b.innerText && b.innerText.includes('登'));
        btn && btn.click();
    """)
    time.sleep(4)

    url = safari_url()
    if "login" in url:
        print("  [错误] 登录失败，仍在登录页")
        return False
    print(f"  [OK] 登录成功: {url}")
    return True


def xhs_publish(title: str, content: str, image_path: str) -> bool:
    """发布小红书图文"""
    print("  [1/4] 进入图文发布页...")
    safari_navigate("https://creator.xiaohongshu.com/publish/publish?source=official")

    print("  [1/4] 切换到上传图文 tab...")
    safari_js("""
        var tab = Array.from(document.querySelectorAll('*')).find(
            el => el.children.length===0 && el.innerText && el.innerText.trim()==='上传图文'
        );
        tab && tab.click();
    """)
    time.sleep(1)

    print(f"  [2/4] 上传图片: {image_path}")
    success = open_file_picker_and_select(image_path)
    if not success:
        print("  [错误] 图片上传失败")
        return False

    # 等待图片处理
    for _ in range(10):
        time.sleep(2)
        blob_count = safari_js("""
            Array.from(document.querySelectorAll('img')).filter(i=>i.src.startsWith('blob:')).length
        """)
        if int(float(blob_count or "0")) > 0:
            print(f"  [2/4] 图片上传成功 ({blob_count} 张)")
            break
    else:
        print("  [警告] 图片可能未上传，继续尝试...")

    print("  [3/4] 填写标题和内容...")
    safe_title = title.replace("'", "\\'").replace('"', '\\"')
    safari_js(f"""
        var ti = document.querySelector('[placeholder*="标题"]');
        if(ti) {{
            Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set.call(ti,'{safe_title}');
            ti.dispatchEvent(new Event('input',{{bubbles:true}}));
        }}
    """)
    time.sleep(0.5)

    safe_content = content.replace("'", "\\'").replace('"', '\\"').replace('\n', '<br>')
    safari_js(f"""
        var ed = document.querySelector('[contenteditable=true]');
        if(ed) {{
            ed.focus();
            ed.innerHTML = '{safe_content}';
            ed.dispatchEvent(new Event('input',{{bubbles:true}}));
        }}
    """)
    time.sleep(0.5)

    print("  [4/4] 点击发布...")
    safari_js("""
        var btn = Array.from(document.querySelectorAll('button')).find(
            b => b.innerText && b.innerText.trim()==='发布' && !b.disabled
        );
        btn && btn.click();
    """)
    time.sleep(5)

    url = safari_url()
    if "published=true" in url or "/publish/success" in url:
        print("  [OK] 发布成功!")
        return True
    else:
        print(f"  [警告] 未检测到发布成功标志，当前 URL: {url}")
        return False


# ──────────────────────────────────────────────
# 平台路由（后续在此添加新平台）
# ──────────────────────────────────────────────

PLATFORMS = {
    "xhs": {
        "name": "小红书",
        "login": xhs_login,
        "publish": xhs_publish,
    },
    # 未来可扩展:
    # "weibo": { "name": "微博", "login": weibo_login, "publish": weibo_publish },
    # "bilibili": { "name": "B站", "login": bili_login, "publish": bili_publish },
}


# ──────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="多平台自动发布工具")
    parser.add_argument("--platform", "-p", default="xhs",
                        choices=list(PLATFORMS.keys()),
                        help="发布平台 (默认: xhs)")
    parser.add_argument("--image", "-i", required=True, help="图片路径")
    parser.add_argument("--title", "-t", required=True, help="帖子标题")
    parser.add_argument("--content", "-c", required=True, help="帖子正文")
    parser.add_argument("--phone", default=PHONE, help=f"手机号 (默认: {PHONE})")
    args = parser.parse_args()

    platform = PLATFORMS[args.platform]
    print(f"\n{'='*50}")
    print(f"目标平台: {platform['name']}")
    print(f"图片: {args.image}")
    print(f"标题: {args.title}")
    print(f"{'='*50}\n")

    # 登录
    print(f"[步骤 1] 登录 {platform['name']}...")
    if not platform["login"](args.phone):
        print("登录失败，退出")
        sys.exit(1)

    # 发布
    print(f"\n[步骤 2] 发布内容...")
    if not platform["publish"](args.title, args.content, args.image):
        print("发布失败")
        sys.exit(1)

    print(f"\n✅ 全部完成！")


if __name__ == "__main__":
    main()

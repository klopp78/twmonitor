#!/usr/bin/env python3
"""
X → Telegram 监控管理菜单
"""

import os
import sys
import json
import subprocess
import signal
from pathlib import Path
from datetime import datetime

BASE_DIR    = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.json"
SCRIPT      = BASE_DIR / "twitter_monitor.py"
PID_FILE    = BASE_DIR / "monitor.pid"
LOG_FILE    = BASE_DIR / "monitor.log"

G  = "\033[92m"
Y  = "\033[93m"
R  = "\033[91m"
B  = "\033[94m"
W  = "\033[0m"
BD = "\033[1m"

def ok(msg):   print(f"{G}✓ {msg}{W}")
def warn(msg): print(f"{Y}⚠ {msg}{W}")
def err(msg):  print(f"{R}✗ {msg}{W}")
def info(msg): print(f"{B}→ {msg}{W}")

# ── 配置读写 ──────────────────────────────────────────────

def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except:
            pass
    return {
        "telegram_bot_token": "",
        "telegram_chat_id":   "",
        "twitter_users":      {},
        "loop_interval":      600,
        "imgbb_api_key":      "",
    }

def save_config(cfg: dict):
    # 兼容旧版 list 格式 → 转成 dict
    if isinstance(cfg.get("twitter_users"), list):
        cfg["twitter_users"] = {u: u for u in cfg["twitter_users"]}
    CONFIG_FILE.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    ok("配置已保存")

# ── 进程管理 ──────────────────────────────────────────────

def is_running() -> bool:
    if not PID_FILE.exists():
        return False
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)
        return True
    except:
        PID_FILE.unlink(missing_ok=True)
        return False

# ── 1. 安装依赖 ───────────────────────────────────────────

def install_deps():
    print(f"\n{BD}=== 安装依赖 ==={W}")
    packages = [
        "playwright==1.42.0",
        "playwright-stealth==1.0.6",
        "beautifulsoup4",
        "requests",
    ]
    for pkg in packages:
        info(f"安装 {pkg} ...")
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", pkg,
             "--break-system-packages", "-q"],
            capture_output=True, text=True
        )
        if r.returncode == 0:
            ok(pkg)
        else:
            err(f"{pkg} 失败：\n{r.stderr.strip()}")

    info("安装 Chromium 浏览器...")
    r = subprocess.run(
        ["playwright", "install", "chromium"],
        capture_output=True, text=True
    )
    if r.returncode == 0:
        ok("Chromium 安装完成")
    else:
        err(f"Chromium 失败：\n{r.stderr.strip()}")
        warn("可手动运行：python3 -m playwright install chromium")

    input(f"\n{G}按 Enter 返回主菜单...{W}")

# ── 2. 配置 Telegram ──────────────────────────────────────

def config_telegram():
    print(f"\n{BD}=== 配置 Telegram ==={W}")
    cfg = load_config()

    cur_token = cfg.get("telegram_bot_token", "")
    print(f"当前 Bot Token : {cur_token[:10] + '...' if len(cur_token) > 10 else cur_token or '(未设置)'}")
    token = input("输入 Bot Token（留空保留原值）: ").strip()
    if token:
        cfg["telegram_bot_token"] = token

    print(f"当前 Chat ID   : {cfg.get('telegram_chat_id') or '(未设置)'}")
    chat_id = input("输入 Chat ID（留空保留原值）: ").strip()
    if chat_id:
        cfg["telegram_chat_id"] = chat_id

    print(f"当前 ImgBB Key : {cfg.get('imgbb_api_key') or '(未设置，图片将直接用原URL)'}")
    imgbb = input("输入 ImgBB API Key（留空跳过）: ").strip()
    if imgbb:
        cfg["imgbb_api_key"] = imgbb

    interval = input(
        f"轮询间隔秒数（当前 {cfg.get('loop_interval', 600)}s，留空保留）: "
    ).strip()
    if interval.isdigit():
        cfg["loop_interval"] = int(interval)

    save_config(cfg)
    input(f"\n{G}按 Enter 返回主菜单...{W}")

# ── 3. 管理监控名单 ───────────────────────────────────────

def manage_accounts():
    while True:
        cfg   = load_config()
        users = cfg.get("twitter_users", {})
        if isinstance(users, list):
            users = {u: u for u in users}
            cfg["twitter_users"] = users

        print(f"\n{BD}=== 监控名单 ==={W}")
        if users:
            print(f"  {'#':<4} {'备注名':<16} Twitter 用户名")
            print(f"  {'-'*42}")
            for i, (username, alias) in enumerate(users.items(), 1):
                display = alias if alias != username else "（无备注）"
                print(f"  {i:<4} {display:<16} @{username}")
        else:
            warn("名单为空")

        print(f"\n  {B}[a]{W} 添加  {B}[d]{W} 删除  {B}[e]{W} 修改备注  {B}[q]{W} 返回")
        choice = input("选择: ").strip().lower()

        if choice == "a":
            print(f"\n{BD}添加账号{W}")
            username = input("Twitter 用户名（不带 @）: ").strip().lstrip("@")
            if not username:
                warn("用户名不能为空"); continue
            if username in users:
                warn(f"@{username} 已在名单中"); continue
            alias = input(
                f"备注名（例：马斯克，留空则显示 @{username}）: "
            ).strip()
            if not alias:
                alias = username
            users[username] = alias
            cfg["twitter_users"] = users
            save_config(cfg)
            ok(f"已添加：{alias} @{username}")

        elif choice == "d":
            if not users:
                warn("名单为空"); continue
            num = input("输入要删除的编号: ").strip()
            if num.isdigit() and 1 <= int(num) <= len(users):
                username = list(users.keys())[int(num) - 1]
                alias    = users.pop(username)
                cfg["twitter_users"] = users
                save_config(cfg)
                ok(f"已删除：{alias} @{username}")
            else:
                err("无效编号")

        elif choice == "e":
            if not users:
                warn("名单为空"); continue
            num = input("输入要修改备注的编号: ").strip()
            if num.isdigit() and 1 <= int(num) <= len(users):
                username  = list(users.keys())[int(num) - 1]
                old_alias = users[username]
                new_alias = input(
                    f"新备注名（当前：{old_alias}，留空保留）: "
                ).strip()
                if new_alias:
                    users[username] = new_alias
                    cfg["twitter_users"] = users
                    save_config(cfg)
                    ok(f"已更新：{new_alias} @{username}")
            else:
                err("无效编号")

        elif choice == "q":
            break

# ── 4/5. 启动 / 停止监控 ──────────────────────────────────

def start_monitor():
    print(f"\n{BD}=== 启动监控 ==={W}")
    cfg = load_config()

    if not cfg.get("telegram_bot_token"):
        err("未设置 Bot Token"); input("按 Enter 返回..."); return
    if not cfg.get("telegram_chat_id"):
        err("未设置 Chat ID");   input("按 Enter 返回..."); return

    users = cfg.get("twitter_users", {})
    if isinstance(users, list):
        users = {u: u for u in users}
    if not users:
        err("监控名单为空"); input("按 Enter 返回..."); return
    if not SCRIPT.exists():
        err(f"找不到 {SCRIPT}"); input("按 Enter 返回..."); return
    if is_running():
        warn("监控已在运行中"); input("按 Enter 返回..."); return

    log_fd = open(LOG_FILE, "a")
    proc   = subprocess.Popen(
        [sys.executable, str(SCRIPT)],
        stdout=log_fd, stderr=log_fd,
        start_new_session=True,
    )
    PID_FILE.write_text(str(proc.pid))
    ok(f"监控已启动（PID: {proc.pid}）")
    info(f"日志文件：{LOG_FILE}")
    print()
    for username, alias in users.items():
        label = f"{alias} @{username}" if alias != username else f"@{username}"
        info(f"监控：{label}")
    info(f"轮询间隔：{cfg.get('loop_interval', 600)} 秒")

    input(f"\n{G}按 Enter 返回主菜单...{W}")

def stop_monitor():
    print(f"\n{BD}=== 停止监控 ==={W}")
    if not is_running():
        warn("监控未在运行"); input("按 Enter 返回..."); return
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        PID_FILE.unlink(missing_ok=True)
        ok(f"已发送停止信号（PID: {pid}）")
        info("脚本会在当前轮询完成后停止")
    except Exception as e:
        err(f"停止失败：{e}")
    input(f"\n{G}按 Enter 返回主菜单...{W}")

# ── 6/7. 日志 ─────────────────────────────────────────────

def view_log():
    print(f"\n{BD}=== 最新日志（最后 40 行）==={W}")
    if not LOG_FILE.exists():
        warn("日志文件不存在")
    else:
        lines = LOG_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()
        for line in lines[-40:]:
            print(line)
    input(f"\n{G}按 Enter 返回主菜单...{W}")

def clear_log():
    print(f"\n{BD}=== 清空日志 ==={W}")
    if not LOG_FILE.exists():
        warn("日志文件不存在"); input("按 Enter 返回..."); return
    confirm = input(f"{Y}确定清空日志？（输入 yes 确认）: {W}").strip().lower()
    if confirm == "yes":
        LOG_FILE.write_text("", encoding="utf-8")
        ok("日志已清空")
    else:
        info("已取消")
    input(f"\n{G}按 Enter 返回主菜单...{W}")

# ── 8. 测试 Telegram ──────────────────────────────────────

def test_telegram():
    print(f"\n{BD}=== 测试 Telegram ==={W}")
    cfg   = load_config()
    token = cfg.get("telegram_bot_token", "").strip()
    cid   = cfg.get("telegram_chat_id", "").strip()
    if not token or not cid:
        err("请先配置 Bot Token 和 Chat ID"); input("按 Enter 返回..."); return
    import requests
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": cid, "text": "✅ X2Telegram 测试消息，配置正常！"},
            timeout=10
        )
        result = resp.json()
        if result.get("ok"):
            ok("测试消息发送成功！请查看 Telegram")
        else:
            err(f"发送失败：{result}")
    except Exception as e:
        err(f"请求异常：{e}")
    input(f"\n{G}按 Enter 返回主菜单...{W}")

# ── 主菜单 ────────────────────────────────────────────────

def main_menu():
    while True:
        cfg      = load_config()
        running  = is_running()
        status   = f"{G}运行中 ●{W}" if running else f"{R}已停止 ○{W}"
        users    = cfg.get("twitter_users", {})
        if isinstance(users, list):
            users = {u: u for u in users}
        token_ok = f"{G}✓{W}" if cfg.get("telegram_bot_token") else f"{R}✗{W}"
        chat_ok  = f"{G}✓{W}" if cfg.get("telegram_chat_id")   else f"{R}✗{W}"

        print(f"""
{BD}╔══════════════════════════════╗
║   X → Telegram 监控管理菜单  ║
╚══════════════════════════════╝{W}
  状态：    {status}
  Token：   {token_ok}  Chat ID： {chat_ok}
  监控账号：{len(users)} 个  轮询间隔：{cfg.get('loop_interval', 600)}s

  {B}[1]{W} 安装依赖
  {B}[2]{W} 配置 Telegram（Token / Chat ID / ImgBB / 间隔）
  {B}[3]{W} 管理监控名单
  {B}[4]{W} 启动监控
  {B}[5]{W} 停止监控
  {B}[6]{W} 查看日志
  {B}[7]{W} 清空日志
  {B}[8]{W} 测试 Telegram 发送
  {B}[q]{W} 退出
""")
        choice = input("请选择: ").strip().lower()

        if   choice == "1": install_deps()
        elif choice == "2": config_telegram()
        elif choice == "3": manage_accounts()
        elif choice == "4": start_monitor()
        elif choice == "5": stop_monitor()
        elif choice == "6": view_log()
        elif choice == "7": clear_log()
        elif choice == "8": test_telegram()
        elif choice == "q": print("再见！"); break
        else: warn("无效选项")

if __name__ == "__main__":
    main_menu()

#!/usr/bin/env python3
"""
x2telegram 管理菜单
功能：安装依赖 / 配置 Telegram / 管理监控名单（含备注名）/ 启动监控
"""

import os
import sys
import json
import subprocess
import signal
from pathlib import Path

BASE_DIR    = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.json"
SCRIPT      = BASE_DIR / "x2telegram.py"
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

# ============================================================
# 配置读写
# ============================================================

def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except:
            pass
    return {
        "TELEGRAM_BOT_TOKEN": "",
        "TELEGRAM_CHAT_ID":   "",
        "TWITTER_USERS":      {},
        "IMGBB_API_KEY":      "",
        "LOOP_INTERVAL":      600,
    }

def save_config(cfg: dict):
    if isinstance(cfg.get("TWITTER_USERS"), list):
        cfg["TWITTER_USERS"] = {u: u for u in cfg["TWITTER_USERS"]}
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    ok("配置已保存")

# ============================================================
# 1. 安装依赖
# ============================================================

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
            err(f"{pkg} 失败:\n{r.stderr.strip()}")

    info("安装 Chromium 浏览器...")
    r = subprocess.run(["playwright", "install", "chromium"],
                       capture_output=True, text=True)
    if r.returncode == 0:
        ok("Chromium 安装完成")
    else:
        err(f"Chromium 失败:\n{r.stderr.strip()}")
        warn("可手动运行: python3 -m playwright install chromium")

    input(f"\n{G}按 Enter 返回主菜单...{W}")

# ============================================================
# 2. 配置 Telegram
# ============================================================

def config_telegram():
    print(f"\n{BD}=== 配置 Telegram ==={W}")
    cfg = load_config()

    print(f"当前 Bot Token : {cfg.get('TELEGRAM_BOT_TOKEN') or '(未设置)'}")
    token = input("输入 Bot Token（留空保留原值）: ").strip()
    if token:
        cfg["TELEGRAM_BOT_TOKEN"] = token

    print(f"当前 Chat ID   : {cfg.get('TELEGRAM_CHAT_ID') or '(未设置)'}")
    chat_id = input("输入 Chat ID（留空保留原值）: ").strip()
    if chat_id:
        cfg["TELEGRAM_CHAT_ID"] = chat_id

    print(f"当前 ImgBB Key : {cfg.get('IMGBB_API_KEY') or '(未设置，图片会降级)'}")
    imgbb = input("输入 ImgBB API Key（留空跳过）: ").strip()
    if imgbb:
        cfg["IMGBB_API_KEY"] = imgbb

    interval = input(f"轮询间隔秒数（当前 {cfg.get('LOOP_INTERVAL', 600)}s，留空保留）: ").strip()
    if interval.isdigit():
        cfg["LOOP_INTERVAL"] = int(interval)

    save_config(cfg)
    input(f"\n{G}按 Enter 返回主菜单...{W}")

# ============================================================
# 3. 管理监控名单
# ============================================================

def manage_accounts():
    while True:
        cfg   = load_config()
        users = cfg.get("TWITTER_USERS", {})
        if isinstance(users, list):
            users = {u: u for u in users}
            cfg["TWITTER_USERS"] = users

        print(f"\n{BD}=== 监控名单 ==={W}")
        if users:
            print(f"  {'#':<4} {'备注名':<16} {'Twitter 用户名'}")
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
            alias = input(f"备注名（如：abcd，留空则显示 @{username}）: ").strip()
            if not alias:
                alias = username
            users[username] = alias
            cfg["TWITTER_USERS"] = users
            save_config(cfg)
            ok(f"已添加：{alias} @{username}")

        elif choice == "d":
            if not users:
                warn("名单为空"); continue
            num = input("输入要删除的编号: ").strip()
            if num.isdigit() and 1 <= int(num) <= len(users):
                username = list(users.keys())[int(num) - 1]
                alias    = users.pop(username)
                cfg["TWITTER_USERS"] = users
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
                new_alias = input(f"新备注名（当前：{old_alias}，留空保留）: ").strip()
                if new_alias:
                    users[username] = new_alias
                    cfg["TWITTER_USERS"] = users
                    save_config(cfg)
                    ok(f"已更新：{new_alias} @{username}")
            else:
                err("无效编号")

        elif choice == "q":
            break

# ============================================================
# 4. 启动 / 停止 / 日志
# ============================================================

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

def start_monitor():
    print(f"\n{BD}=== 启动监控 ==={W}")
    cfg = load_config()

    if not cfg.get("TELEGRAM_BOT_TOKEN"):
        err("未设置 Bot Token"); input("按 Enter 返回..."); return
    if not cfg.get("TELEGRAM_CHAT_ID"):
        err("未设置 Chat ID");   input("按 Enter 返回..."); return

    users = cfg.get("TWITTER_USERS", {})
    if isinstance(users, list):
        users = {u: u for u in users}
    if not users:
        err("监控名单为空"); input("按 Enter 返回..."); return
    if not SCRIPT.exists():
        err(f"找不到 {SCRIPT}"); input("按 Enter 返回..."); return
    if is_running():
        warn("监控已在运行中"); input("按 Enter 返回..."); return

    # 传递格式："备注名:用户名,备注名:用户名"
    users_str = ",".join(f"{alias}:{username}" for username, alias in users.items())

    env = os.environ.copy()
    env["TELEGRAM_BOT_TOKEN"] = cfg["TELEGRAM_BOT_TOKEN"]
    env["TELEGRAM_CHAT_ID"]   = cfg["TELEGRAM_CHAT_ID"]
    env["TWITTER_USER"]       = users_str
    env["LOOP_MODE"]          = "true"
    env["LOOP_INTERVAL"]      = str(cfg.get("LOOP_INTERVAL", 600))
    if cfg.get("IMGBB_API_KEY"):
        env["IMGBB_API_KEY"]  = cfg["IMGBB_API_KEY"]

    log_fd = open(LOG_FILE, "a")
    proc   = subprocess.Popen(
        [sys.executable, str(SCRIPT)],
        env=env, stdout=log_fd, stderr=log_fd,
        start_new_session=True,
    )
    PID_FILE.write_text(str(proc.pid))
    ok(f"监控已启动（PID: {proc.pid}）")
    info(f"日志: {LOG_FILE}")
    print()
    for username, alias in users.items():
        label = f"{alias} @{username}" if alias != username else f"@{username}"
        info(f"监控：{label}")
    info(f"轮询间隔：{cfg.get('LOOP_INTERVAL', 600)} 秒")

    input(f"\n{G}按 Enter 返回主菜单...{W}")

def stop_monitor():
    print(f"\n{BD}=== 停止监控 ==={W}")
    if not is_running():
        warn("监控未在运行"); input("按 Enter 返回..."); return
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        PID_FILE.unlink(missing_ok=True)
        ok(f"已停止（PID: {pid}）")
    except Exception as e:
        err(f"停止失败: {e}")
    input(f"\n{G}按 Enter 返回主菜单...{W}")

def view_log():
    print(f"\n{BD}=== 最新日志（最后 30 行）==={W}")
    if not LOG_FILE.exists():
        warn("日志文件不存在")
    else:
        lines = LOG_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()
        for line in lines[-30:]:
            print(line)
    input(f"\n{G}按 Enter 返回主菜单...{W}")

# ============================================================
# 主菜单
# ============================================================

def main_menu():
    while True:
        cfg     = load_config()
        running = is_running()
        status  = f"{G}运行中 ●{W}" if running else f"{R}已停止 ○{W}"
        users   = cfg.get("TWITTER_USERS", {})
        if isinstance(users, list):
            users = {u: u for u in users}
        token_ok = "✓" if cfg.get("TELEGRAM_BOT_TOKEN") else "✗"

        print(f"""
{BD}╔══════════════════════════════╗
║   X → Telegram 监控管理菜单  ║
╚══════════════════════════════╝{W}
  状态：  {status}
  Token： {token_ok}  |  监控账号：{len(users)} 个

  {B}[1]{W} 安装依赖
  {B}[2]{W} 配置 Telegram（Token / Chat ID）
  {B}[3]{W} 管理监控名单
  {B}[4]{W} 启动监控（持续运行）
  {B}[5]{W} 停止监控
  {B}[6]{W} 查看日志
  {B}[q]{W} 退出
""")
        choice = input("请选择: ").strip().lower()

        if   choice == "1": install_deps()
        elif choice == "2": config_telegram()
        elif choice == "3": manage_accounts()
        elif choice == "4": start_monitor()
        elif choice == "5": stop_monitor()
        elif choice == "6": view_log()
        elif choice == "q": print("再见！"); break
        else: warn("无效选项")

if __name__ == "__main__":
    main_menu()

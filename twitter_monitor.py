#!/usr/bin/env python3
"""
X → Telegram 监控脚本
配置从 config.json 读取
"""

import os
import time
import random
import json
import requests
import base64
from datetime import datetime, timezone, timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync
from bs4 import BeautifulSoup

BASE_DIR    = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.json"
LAST_ID_FILE = BASE_DIR / "last_id.json"
INSTANCES_FILE = BASE_DIR / "instances.json"

# UTC+8 马来西亚时区
MYT = timezone(timedelta(hours=8))

NITTER_INSTANCES = [
    'https://xcancel.com',
    'https://nitter.privacyredirect.com',
    'https://nitter.poast.org',
    'https://nitter.hu',
    'https://nitter.moomoo.me',
    'https://nitter.net',
]

# ── 配置 ──────────────────────────────────────────────────

def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except:
            pass
    return {}

# ── 时间格式化（UTC → UTC+8）────────────────────────────

def format_time(raw: str) -> str:
    """
    原始格式示例：
      'May 11, 2025 · 1:15 AM UTC'
      'May 11, 2025 at 1:15 AM UTC'
    输出：May 11, 2025 · 9:15 AM (UTC+8)
    """
    if not raw or raw == "Unknown":
        return raw
    try:
        # 统一格式：去掉 · / at，提取可解析部分
        cleaned = raw.replace(" · ", " ").replace(" at ", " ").replace(" UTC", "").strip()
        dt_utc = datetime.strptime(cleaned, "%b %d, %Y %I:%M %p")
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
        dt_myt = dt_utc.astimezone(MYT)
        return dt_myt.strftime("%b %d, %Y · %-I:%M %p (UTC+8)")
    except Exception:
        return raw  # 解析失败原样返回

# ── 工具 ──────────────────────────────────────────────────

def get_random_ua():
    return random.choice([
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
    ])

def load_instances() -> list:
    if INSTANCES_FILE.exists():
        try:
            data = json.loads(INSTANCES_FILE.read_text(encoding="utf-8"))
            if data and isinstance(data, list):
                print(f"[系统] 加载 {len(data)} 个 Nitter 实例")
                return data
        except:
            pass
    return NITTER_INSTANCES.copy()

def get_original_image_url(nitter_url: str) -> str:
    import urllib.parse, re
    try:
        if 'pbs.twimg.com' in nitter_url:
            return nitter_url
        if '/pic/enc/' in nitter_url:
            enc = nitter_url.split('/pic/enc/')[-1].split('?')[0]
            try:
                decoded = bytes.fromhex(enc).decode('utf-8')
                if 'pbs.twimg.com' in decoded:
                    return decoded
            except:
                pass
        path = urllib.parse.unquote(nitter_url)
        if '/media/' in path:
            part = path.split('/media/')[-1].split('?')[0]
            if '.' in part:
                mid, ext = part.rsplit('.', 1)
                ext = ext.split('&')[0].split('?')[0]
                return f"https://pbs.twimg.com/media/{mid}?format={ext}&name=large"
        if 'pbs.twimg.com' in path:
            m = re.search(r'(pbs\.twimg\.com/media/[^?&]+)', path)
            if m:
                return "https://" + m.group(1)
    except:
        pass
    return nitter_url

def translate_text(text: str) -> str:
    if not text or not text.strip():
        return ""
    try:
        resp = requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params={"client": "gtx", "sl": "auto", "tl": "zh-CN", "dt": "t", "q": text},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15
        )
        data = resp.json()
        if data and data[0]:
            return "".join(p[0] for p in data[0] if p[0])
    except:
        pass
    return ""

def upload_to_imgbb(image_url: str, api_key: str) -> str:
    if not api_key:
        return ""
    try:
        r = requests.get(image_url, timeout=30, headers={
            'User-Agent': get_random_ua(),
            'Referer': 'https://twitter.com/'
        })
        r.raise_for_status()
        img_b64 = base64.b64encode(r.content).decode()
        up = requests.post('https://api.imgbb.com/1/upload',
                           data={'key': api_key, 'image': img_b64}, timeout=30)
        result = up.json()
        if result.get('success'):
            return result['data']['url']
    except:
        pass
    return ""

def nitter_to_twitter(url: str) -> str:
    import re
    # 替换所有 nitter 相关域名 + xcancel → x.com
    url = re.sub(r'https?://[a-zA-Z0-9\-\.]*nitter[a-zA-Z0-9\-\.]*', 'https://x.com', url)
    url = url.replace('https://xcancel.com', 'https://x.com')
    # 去掉推文链接末尾的 #m
    url = re.sub(r'#m$', '', url)
    return url

# ── Telegram 推送 ─────────────────────────────────────────

def send_telegram(cfg: dict, tweet: dict, username: str, alias: str) -> bool:
    token = cfg.get("telegram_bot_token", "").strip()
    cid   = cfg.get("telegram_chat_id", "").strip()
    if not token or not cid:
        print("[Telegram] 未配置 token/chat_id，跳过")
        return False

    base = f"https://api.telegram.org/bot{token}"
    imgbb_key = cfg.get("imgbb_api_key", "").strip()

    # 备注名 + 用户名
    if alias and alias != username:
        author_line = f"{alias} @{username}"
    else:
        author_line = f"@{username}"

    # 时间
    time_str = format_time(tweet.get('published', ''))

    # 内容清理 + 翻译
    raw = tweet['content'].replace('€∋', '').strip()
    translated = translate_text(raw)
    if translated and translated.strip() != raw.strip():
        content_block = f"{translated}\n\n<i>{raw}</i>"
    else:
        content_block = raw

    # 推文链接
    tw_link = nitter_to_twitter(tweet['link'])

    # 转发标签
    rt_tag = "🔃 转发" if tweet.get('is_retweet') else ""

    # 拼消息
    parts = []
    if rt_tag:
        parts.append(rt_tag)
    parts.append(f"🕐 发布：{time_str}")
    parts.append(f"👤 {author_line}")
    parts.append("")
    parts.append(content_block)
    parts.append("")
    parts.append(f'🔗 <a href="{tw_link}">查看原推</a>')

    text = "\n".join(parts)

    images    = tweet.get('images', [])
    video_url = tweet.get('video_url')
    sent = False

    try:
        if images:
            final_url = ""
            if imgbb_key:
                print(f"[{username}] 上传图片到 ImgBB...")
                final_url = upload_to_imgbb(images[0], imgbb_key)
            if not final_url:
                final_url = images[0]

            resp = requests.post(f"{base}/sendPhoto", json={
                "chat_id": cid,
                "photo": final_url,
                "caption": text,
                "parse_mode": "HTML"
            }, timeout=15)
            if resp.json().get('ok'):
                print(f"[{username}] Telegram 图片推送成功")
                sent = True
            else:
                print(f"[{username}] 图片推送失败：{resp.json()}，降级文字")

        if not sent:
            resp = requests.post(f"{base}/sendMessage", json={
                "chat_id": cid,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": False
            }, timeout=15)
            if resp.json().get('ok'):
                print(f"[{username}] Telegram 文字推送成功")
                sent = True
            else:
                print(f"[{username}] 文字推送失败：{resp.json()}")

        # 多张图（2~4张）
        if sent and len(images) > 1:
            for img in images[1:4]:
                fu = upload_to_imgbb(img, imgbb_key) if imgbb_key else img
                requests.post(f"{base}/sendPhoto", json={"chat_id": cid, "photo": fu or img}, timeout=15)

        # 视频链接
        if sent and video_url:
            requests.post(f"{base}/sendMessage", json={
                "chat_id": cid,
                "text": f"🎬 视频：{video_url}"
            }, timeout=15)

    except Exception as e:
        print(f"[{username}] Telegram 异常：{e}")
        return False

    return sent

# ── Nitter 抓取（原版逻辑完整保留）─────────────────────────

def scrape_nitter(target: str, dynamic_instances: list = None) -> dict:
    is_search = target.startswith('search:')
    keyword   = target[7:] if is_search else target
    instances = (dynamic_instances or NITTER_INSTANCES.copy())[:]

    if len(instances) > 5:
        top5, rest = instances[:5], instances[5:]
        random.shuffle(top5); random.shuffle(rest)
        instances = top5 + rest
    else:
        random.shuffle(instances)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for instance in instances:
            try:
                ctx  = browser.new_context(user_agent=get_random_ua(), viewport={'width':1280,'height':720})
                page = ctx.new_page()
                stealth_sync(page)

                url = (f"{instance.rstrip('/')}/search?f=tweets&q={requests.utils.quote(keyword)}"
                       if is_search else f"{instance.rstrip('/')}/{keyword}")
                print(f"[{target}] 加载：{url}")

                try:
                    resp = page.goto(url, wait_until="networkidle", timeout=45000)
                    if resp and resp.status == 403:
                        print(f"[{target}] {instance} 403，跳过")
                        ctx.close(); continue
                except Exception as e:
                    print(f"[{target}] {instance} 加载失败：{e}")
                    ctx.close(); continue

                for i in range(5):
                    content = page.content()
                    if any(k in content for k in ["Verifying your browser","Just a moment","Checking your browser"]):
                        print(f"[{target}] 浏览器验证中 ({i+1}/5)...")
                        page.wait_for_timeout(5000)
                    else:
                        break

                soup  = BeautifulSoup(page.content(), 'html.parser')
                items = soup.select('.timeline-item')
                if not items:
                    print(f"[{target}] {instance} 未找到推文"); ctx.close(); continue

                valid = []
                for item in items[:8]:
                    if item.select_one('.pinned'):
                        print(f"[{target}] 跳过置顶"); continue

                    is_rt = item.select_one('.retweet-header') is not None

                    images = []
                    for img in item.select('.attachment.image img,.tweet-image img,.still-image img,.attachments img'):
                        if any(c in str(img.parent.get('class',[])) for c in ['avatar','profile']):
                            continue
                        src = img.get('src','')
                        if not src: continue
                        if src.startswith('//'): src = 'https:' + src
                        elif src.startswith('/'): src = instance.rstrip('/') + src
                        src = get_original_image_url(src)
                        if 'emoji' not in src.lower() and 'hashtag_click' not in src:
                            images.append(src)

                    video_url = None
                    try:
                        vel = item.select_one('video source') or item.select_one('video')
                        if vel:
                            poster = (item.select_one('video') or vel).get('poster','')
                            if poster:
                                if poster.startswith('//'): poster = 'https:' + poster
                                elif poster.startswith('/'): poster = instance.rstrip('/') + poster
                                poster = get_original_image_url(poster)
                                if poster not in images: images.append(poster)
                            vs = vel.get('src','')
                            if vs:
                                if vs.startswith('//'): video_url = 'https:' + vs
                                elif vs.startswith('/'): video_url = instance.rstrip('/') + vs
                                else: video_url = vs
                    except Exception as e:
                        print(f"[{target}] 视频提取异常：{e}")

                    cel = item.select_one('.tweet-content')
                    lel = item.select_one('.tweet-link')
                    del_ = item.select_one('.tweet-date a')
                    ael = item.select_one('.username')

                    if not cel or not lel: continue

                    href = lel.get('href','')
                    tid  = href.split('/status/')[-1].split('#')[0] if '/status/' in href else href

                    valid.append({
                        'content':    cel.get_text(strip=True),
                        'link':       instance.rstrip('/') + href,
                        'published':  del_.get('title','') if del_ else 'Unknown',
                        'author':     ael.get_text(strip=True) if ael else keyword,
                        'guid':       tid,
                        'is_retweet': is_rt,
                        'images':     images,
                        'video_url':  video_url,
                    })
                    break  # 只取第一条非置顶

                if valid:
                    print(f"[{target}] 抓取成功：{valid[0]['guid']}")
                    ctx.close(); browser.close()
                    return valid[0]

                print(f"[{target}] {instance} 无有效推文")
                ctx.close()

            except Exception as e:
                print(f"[{target}] {instance} 出错：{e}")
                continue

        browser.close()
    return None

# ── 主循环 ────────────────────────────────────────────────

def main():
    cfg = load_config()

    users_raw = cfg.get("twitter_users", {})
    if isinstance(users_raw, list):
        users_raw = {u: u for u in users_raw}

    if not users_raw:
        print("[错误] 监控名单为空，请先运行 manage.py"); return
    if not cfg.get("telegram_bot_token") or not cfg.get("telegram_chat_id"):
        print("[错误] 未配置 Telegram，请先运行 manage.py"); return

    interval  = int(cfg.get("loop_interval", 600))
    instances = load_instances()

    print(f"[{datetime.now()}] 监控启动，账号：{list(users_raw.keys())}，间隔：{interval}s")

    while True:
        cycle_start = time.time()
        print(f"\n--- 新轮询 [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ---")

        try:
            last_ids = json.loads(LAST_ID_FILE.read_text(encoding="utf-8")) if LAST_ID_FILE.exists() else {}
        except:
            last_ids = {}

        updated = False
        for username, alias in users_raw.items():
            try:
                tweet = scrape_nitter(username, instances)
                if not tweet:
                    continue
                cid = tweet['guid']
                # 兼容旧格式（str）→ 转成 list
                sent_ids = last_ids.get(username, [])
                if isinstance(sent_ids, str):
                    sent_ids = [sent_ids]
                if cid not in sent_ids:
                    print(f"[{username}] 新推文：{cid}")
                    sent_ids.append(cid)
                    if len(sent_ids) > 20:
                        sent_ids = sent_ids[-20:]
                    last_ids[username] = sent_ids
                    updated = True
                    send_telegram(cfg, tweet, username, alias)
                else:
                    print(f"[{username}] 无新推文")
            except Exception as e:
                print(f"[{username}] 处理异常：{e}")

        if updated:
            LAST_ID_FILE.write_text(json.dumps(last_ids, indent=2, ensure_ascii=False), encoding="utf-8")
            print("[系统] last_id.json 已更新")

        elapsed    = time.time() - cycle_start
        sleep_time = max(10, interval - elapsed)
        print(f"--- 耗时 {elapsed:.1f}s，休眠 {sleep_time:.1f}s ---")
        time.sleep(sleep_time)

if __name__ == "__main__":
    main()

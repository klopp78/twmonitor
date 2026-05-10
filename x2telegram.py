"""
Twitter/X 监控系统 - Telegram 版
依赖：pip install playwright==1.42.0 playwright-stealth==1.0.6 beautifulsoup4 requests
      playwright install chromium
"""

import os
import time
import random
import json
import requests
import base64
import re
import urllib.parse
from datetime import datetime
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync
from bs4 import BeautifulSoup

# ============================================================
# 配置区（由 menu.py 通过环境变量传入，也可手动填写）
# ============================================================

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '你的BOT_TOKEN')
TELEGRAM_CHAT_ID   = os.environ.get('TELEGRAM_CHAT_ID', '你的CHAT_ID')

# 格式："备注名:用户名,备注名:用户名"
USERS_RAW = os.environ.get('TWITTER_USER', '')

# 解析成 {username: alias} 字典
def parse_users(raw: str) -> dict:
    result = {}
    for item in raw.split(','):
        item = item.strip()
        if not item:
            continue
        if ':' in item:
            alias, username = item.split(':', 1)
            result[username.strip()] = alias.strip()
        else:
            result[item] = item  # 没有备注就用用户名本身
    return result

USERS = parse_users(USERS_RAW)  # {username: alias}

LOOP_MODE = os.environ.get('LOOP_MODE', 'false').lower() == 'true'
INTERVAL  = int(os.environ.get('LOOP_INTERVAL', '600'))

IMGBB_API_KEY    = os.environ.get('IMGBB_API_KEY', '')
USE_IMAGE_BED    = os.environ.get('USE_IMAGE_BED', 'true').lower() == 'true'
CLOUDFLARE_PROXY = os.environ.get('CLOUDFLARE_PROXY', '').strip()

BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
LAST_ID_FILE   = os.path.join(BASE_DIR, 'last_id.json')
INSTANCES_FILE = os.path.join(BASE_DIR, 'instances.json')

NITTER_INSTANCES = [
    'https://nitter.poast.org',
    'https://xcancel.com',
    'https://nitter.privacyredirect.com',
    'https://nitter.hu',
    'https://nitter.moomoo.me',
]

# ============================================================
# 工具函数
# ============================================================

def get_random_ua():
    return random.choice([
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
    ])

def load_instances():
    if os.path.exists(INSTANCES_FILE):
        try:
            with open(INSTANCES_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if data and isinstance(data, list):
                return data
        except:
            pass
    return NITTER_INSTANCES

def get_original_image_url(nitter_url):
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
            media_part = path.split('/media/')[-1].split('?')[0]
            if '.' in media_part:
                media_id, ext = media_part.rsplit('.', 1)
                ext = ext.split('&')[0].split('?')[0]
                return f"https://pbs.twimg.com/media/{media_id}?format={ext}&name=large"
        match = re.search(r'(pbs\.twimg\.com/media/[^?&]+)', path)
        if match:
            return "https://" + match.group(1)
    except:
        pass
    return nitter_url

def translate_text(text, target_lang='zh-CN'):
    if not text or not text.strip():
        return ""
    try:
        resp = requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params={"client": "gtx", "sl": "auto", "tl": target_lang, "dt": "t", "q": text},
            headers={"User-Agent": get_random_ua()},
            timeout=15,
        )
        data = resp.json()
        if data and data[0]:
            return "".join(part[0] for part in data[0] if part[0])
    except:
        pass
    return ""

def upload_to_imgbb(image_url):
    if not IMGBB_API_KEY:
        return None
    try:
        img = requests.get(image_url, timeout=30, headers={
            'User-Agent': get_random_ua(),
            'Referer': 'https://twitter.com/'
        })
        img.raise_for_status()
        b64 = base64.b64encode(img.content).decode('utf-8')
        resp = requests.post('https://api.imgbb.com/1/upload',
                             data={'key': IMGBB_API_KEY, 'image': b64}, timeout=30)
        result = resp.json()
        if result.get('success'):
            return result['data']['url']
    except:
        pass
    return None

def resolve_image_url(img_url):
    if USE_IMAGE_BED and IMGBB_API_KEY:
        result = upload_to_imgbb(img_url)
        if result:
            return result
    if CLOUDFLARE_PROXY:
        return f"{CLOUDFLARE_PROXY.rstrip('/')}?url={urllib.parse.quote(img_url)}"
    clean = img_url.replace('https://', '').replace('http://', '')
    return f"https://wsrv.nl/?url={urllib.parse.quote(clean)}"

# ============================================================
# Playwright 抓取
# ============================================================

def scrape_nitter(username, instances=None):
    inst_list = list(instances or NITTER_INSTANCES)
    random.shuffle(inst_list)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        for instance in inst_list:
            try:
                ctx  = browser.new_context(user_agent=get_random_ua(),
                                           viewport={'width': 1280, 'height': 720})
                page = ctx.new_page()
                stealth_sync(page)

                url = f"{instance.rstrip('/')}/{username}"
                print(f"[{username}] 加载: {url}")

                try:
                    resp = page.goto(url, wait_until="networkidle", timeout=45000)
                    if resp and resp.status == 403:
                        print(f"[{username}] 403: {instance}")
                        ctx.close(); continue
                except Exception as e:
                    print(f"[{username}] 超时/失败: {e}")
                    ctx.close(); continue

                for i in range(5):
                    content = page.content()
                    if any(kw in content for kw in ["Verifying your browser", "Just a moment", "Checking your browser"]):
                        print(f"[{username}] 验证挑战 ({i+1}/5)...")
                        page.wait_for_timeout(5000)
                    else:
                        break

                soup  = BeautifulSoup(page.content(), 'html.parser')
                items = soup.select('.timeline-item')

                if not items:
                    print(f"[{username}] {instance} 无内容")
                    ctx.close(); continue

                tweet = None
                for item in items[:8]:
                    if item.select_one('.pinned'):
                        continue

                    is_retweet = item.select_one('.retweet-header') is not None

                    images = []
                    for img in item.select('.attachment.image img, .tweet-image img, .still-image img, .attachments img'):
                        src = img.get('src', '')
                        if not src or 'emoji' in src.lower():
                            continue
                        if src.startswith('//'): src = 'https:' + src
                        elif src.startswith('/'): src = instance.rstrip('/') + src
                        images.append(get_original_image_url(src))

                    video_url = None
                    video_el  = item.select_one('video')
                    if video_el:
                        poster = video_el.get('poster', '')
                        if poster:
                            if poster.startswith('//'): poster = 'https:' + poster
                            elif poster.startswith('/'): poster = instance.rstrip('/') + poster
                            poster = get_original_image_url(poster)
                            if poster not in images:
                                images.append(poster)
                        src_el = item.select_one('video source')
                        if src_el:
                            v = src_el.get('src', '')
                            if v.startswith('//'): video_url = 'https:' + v
                            elif v.startswith('/'): video_url = instance.rstrip('/') + v
                            else: video_url = v

                    content_el = item.select_one('.tweet-content')
                    link_el    = item.select_one('.tweet-link')
                    date_el    = item.select_one('.tweet-date a')

                    if not content_el or not link_el:
                        continue

                    link_href = link_el.get('href', '')
                    tweet_id  = link_href.split('/status/')[-1].split('#')[0] if '/status/' in link_href else link_href

                    tweet = {
                        'content':    content_el.get_text(strip=True),
                        'link':       instance.rstrip('/') + link_href,
                        'published':  date_el.get('title', '') if date_el else '',
                        'username':   username,
                        'guid':       tweet_id,
                        'is_retweet': is_retweet,
                        'images':     images,
                        'video_url':  video_url,
                    }
                    break

                ctx.close()

                if tweet:
                    print(f"[{username}] 抓取成功: {tweet['guid']}")
                    browser.close()
                    return tweet

                print(f"[{username}] {instance} 无有效推文")

            except Exception as e:
                print(f"[{username}] {instance} 出错: {e}")
                continue

        browser.close()
    return None

# ============================================================
# Telegram 推送
# ============================================================

def send_telegram(tweet, alias):
    base_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    username  = tweet['username']

    retweet_flag = "🔃 转发" if tweet.get('is_retweet') else "📝 新推文"

    raw        = tweet['content'].replace('€∋', '').strip()
    translated = translate_text(raw)

    # 还原 Twitter 原始链接
    twitter_link = re.sub(
        r'https://(nitter\.[^/]+|xcancel\.com)',
        'https://twitter.com',
        tweet['link']
    )

    # 显示：备注名 @用户名（备注名和用户名不同时才都显示）
    if alias and alias != username:
        display = f"{alias} @{username}"
    else:
        display = f"@{username}"

    text = (
        f"{retweet_flag} <b>{display}</b>\n\n"
        + (f"🇨🇳 {translated}\n\n" if translated else "")
        + f"{raw}\n\n"
        + (f"🕐 {tweet['published']}\n" if tweet.get('published') else "")
        + f"🔗 <a href='{twitter_link}'>查看原推</a>"
        + (f"\n🎬 <a href='{tweet['video_url']}'>观看视频</a>" if tweet.get('video_url') else "")
    )

    if tweet.get('images'):
        img_url = resolve_image_url(tweet['images'][0])
        try:
            r = requests.post(f"{base_url}/sendPhoto", json={
                "chat_id":    TELEGRAM_CHAT_ID,
                "photo":      img_url,
                "caption":    text[:1024],
                "parse_mode": "HTML",
            }, timeout=15)
            if r.ok:
                print(f"[{username}] 图片推送成功")
                return True
            print(f"[{username}] 图片失败，降级纯文字: {r.text}")
        except Exception as e:
            print(f"[{username}] 图片异常: {e}")

    try:
        r = requests.post(f"{base_url}/sendMessage", json={
            "chat_id":                  TELEGRAM_CHAT_ID,
            "text":                     text[:4096],
            "parse_mode":               "HTML",
            "disable_web_page_preview": False,
        }, timeout=10)
        r.raise_for_status()
        print(f"[{username}] 文字推送成功")
        return True
    except Exception as e:
        print(f"[{username}] 推送失败: {e}")
        return False

# ============================================================
# 主循环
# ============================================================

def main():
    if not USERS:
        print("未配置监控账号，请通过 menu.py 添加")
        return

    print(f"[启动] 监控账号: {list(USERS.keys())}")
    print(f"[启动] LOOP_MODE={LOOP_MODE}, INTERVAL={INTERVAL}s")

    instances = load_instances()

    while True:
        cycle_start = time.time()
        print(f"\n=== 新一轮轮询 [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ===")

        last_ids = {}
        if os.path.exists(LAST_ID_FILE):
            try:
                with open(LAST_ID_FILE, 'r', encoding='utf-8') as f:
                    last_ids = json.load(f)
            except:
                pass

        updated = False
        for username, alias in USERS.items():
            try:
                tweet = scrape_nitter(username, instances)
                if not tweet:
                    continue

                current_id = tweet['guid']
                if last_ids.get(username) == current_id:
                    print(f"[{username}] 无新推文")
                    continue

                print(f"[{username}] 发现新推文: {current_id}")
                if send_telegram(tweet, alias):
                    last_ids[username] = current_id
                    updated = True

                time.sleep(1)

            except Exception as e:
                print(f"[{username}] 异常: {e}")

        if updated:
            with open(LAST_ID_FILE, 'w', encoding='utf-8') as f:
                json.dump(last_ids, f, indent=2, ensure_ascii=False)
            print("[系统] 状态已保存")

        if not LOOP_MODE:
            print("[系统] 单次模式，结束")
            break

        elapsed    = time.time() - cycle_start
        sleep_time = max(10, INTERVAL - elapsed)
        print(f"=== 轮询结束，耗时 {elapsed:.1f}s，休眠 {sleep_time:.1f}s ===")
        time.sleep(sleep_time)


if __name__ == "__main__":
    main()

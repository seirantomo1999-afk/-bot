# selenium_check.py
# -*- coding: utf-8 -*-
"""
都立公園予約サイト ステルス版スクレイパ
※ 通知は on_hit コールバックで即時発火
"""

import os, re, time, random, datetime as dt
from contextlib import suppress

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC

with suppress(Exception):
    import undetected_chromedriver as uc

from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service as ChromeService

try:
    import jpholiday
except Exception:
    jpholiday = None


# ====== 設定 ======
SHOW_BROWSER = False
USE_UC_FIRST = True

TARGET_DAY = (dt.date.today() + dt.timedelta(days=1)).strftime("%Y-%m-%d")
PURPOSE_VALUE = "1000_1030"
PARK_KEYWORDS = [
    "東白鬚公園", "汐入公園", "東綾瀬公園",
    "舎人公園", "亀戸中央公園", "大島小松川公園"
]

ONLY_HOLIDAYS = True
NEXT_WEEKS_TO_CHECK = 4
MAX_TOTAL_RUNTIME_SEC = 300

URL = "https://kouen.sports.metro.tokyo.lg.jp/web/"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

X_DAY        = '//*[@id="daystart-home"]'
X_PURPOSE    = '//*[@id="purpose-home"]'
X_PARK       = '//*[@id="bname-home"]'
X_SEARCH     = '//*[@id="btn-go"]'
X_WEEK_TBODY = '//*[@id="week-info"]/tbody'
X_NEXT_WEEK  = '//*[@id="next-week"]'

SLOT_LABELS = {"10": "9時", "20": "11時", "30": "13時", "40": "15時", "50": "17時", "60": "19時"}
ID_RE = re.compile(r"A_(\d{8})_(\d{2})")


def jitter(a=0.12, b=0.35):
    time.sleep(random.uniform(a, b))


def slot_to_hour(code: str) -> str:
    return SLOT_LABELS.get(code, code)


def is_holiday_or_weekend(d: dt.date) -> bool:
    if d.weekday() >= 5:
        return True
    if jpholiday and jpholiday.is_holiday(d):
        return True
    return False


def scrape_week_A_holidays_only(tbody):
    results = []
    for el in tbody.find_elements(By.XPATH, './/*[@id]'):
        cid = el.get_attribute("id") or ""
        m = ID_RE.match(cid)
        if not m:
            continue
        ymd, slot = m.groups()
        d = dt.datetime.strptime(ymd, "%Y%m%d").date()
        if ONLY_HOLIDAYS and not is_holiday_or_weekend(d):
            continue
        results.append((d, ymd, slot_to_hour(slot)))
    return results


def build_options(headless: bool):
    opts = webdriver.ChromeOptions()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1280,900")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument(f"--user-agent={USER_AGENT}")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    return opts


def make_driver():
    headless = not SHOW_BROWSER
    if USE_UC_FIRST:
        try:
            return uc.Chrome(options=build_options(headless), use_subprocess=True)
        except Exception:
            pass
    return webdriver.Chrome(
        service=ChromeService(ChromeDriverManager().install()),
        options=build_options(headless)
    )


def run_for_park(driver, wait, park_keyword: str, start_ts: float, on_hit=None):
    driver.get(URL)
    jitter()

    wait.until(EC.presence_of_element_located((By.XPATH, X_DAY)))
    day_el = driver.find_element(By.XPATH, X_DAY)
    driver.execute_script("arguments[0].value = arguments[1];", day_el, TARGET_DAY)

    Select(driver.find_element(By.XPATH, X_PURPOSE)).select_by_value(PURPOSE_VALUE)

    park_el = Select(driver.find_element(By.XPATH, X_PARK))
    for opt in park_el.options:
        if park_keyword in opt.text:
            park_el.select_by_value(opt.get_attribute("value"))
            break

    driver.find_element(By.XPATH, X_SEARCH).click()

    for _ in range(NEXT_WEEKS_TO_CHECK + 1):
        if time.time() - start_ts > MAX_TOTAL_RUNTIME_SEC:
            return

        tbody = wait.until(EC.presence_of_element_located((By.XPATH, X_WEEK_TBODY)))
        slots = scrape_week_A_holidays_only(tbody)

        # ★ 見つけた瞬間に通知
        if slots and on_hit:
            for d, ymd, hour in slots:
                on_hit(park_keyword, ymd, d, hour)

        with suppress(Exception):
            next_btn = driver.find_element(By.XPATH, X_NEXT_WEEK)
            next_btn.click()
            time.sleep(1)

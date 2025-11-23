# -*- coding: utf-8 -*-
"""
都立公園予約サイト ステルス版スクレイパ (A/B/E 対策入り)
- A: 初回アクセスのレース対策（セッション/Cookie/初期化完了待ち）＋失敗時ワンリロード
- B: Bot/ヘッダー分岐の回避（UA/言語/automationフラグ抑制）
- E: エラーページ検知時の最小リトライ（driver.refresh() 1回）

既存機能:
- 人間っぽい操作（微小ランダム待機 / スクロール / ホバー）
- テスト時はブラウザ表示（SHOW_BROWSER=True）
- 本番はヘッドレスかつ画像等ブロックで高速化
- undetected-chromedriver があれば優先して使用
- A_セル（空き）だけ抽出、★休日（祝日含む）★のみ表示
"""

import os
import re
import time
import random
import datetime as dt
from contextlib import suppress

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC

# uc があれば使う（無ければ通常のChrome + 可能な限りステルス調整）
with suppress(Exception):
    import undetected_chromedriver as uc

from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service as ChromeService

# 祝日（任意）
try:
    import jpholiday
except Exception:
    jpholiday = None

# ====== 設定 ======
SHOW_BROWSER = False          # テスト時は True で画面表示（非ヘッドレス）
USE_UC_FIRST = True           # undetected-chromedriver を優先（導入推奨）
CHROME_PROFILE_DIR = None     # 例: r"C:\\Users\\you\\AppData\\Local\\Google\\Chrome\\User Data"
CHROME_PROFILE_NAME = None    # 例: "Default" / "Profile 1" 等（未指定なら既定）

TARGET_DAY = (dt.date.today() + dt.timedelta(days=1)).strftime("%Y-%m-%d")
PURPOSE_VALUE = "1000_1030"   # テニス（人工芝）
PARK_KEYWORDS = ["東白鬚公園", "汐入公園", "東綾瀬公園" ,"舎人公園", "亀戸中央公園", "大島小松川公園]

ONLY_HOLIDAYS = True
NEXT_WEEKS_TO_CHECK = 4      # 今週 + 3週
MAX_TOTAL_RUNTIME_SEC = 300  # 念のため全体ガード（超えたら打ち切り）
JITTER_RANGE = (0.12, 0.35)  # 微小ランダム待機（人間っぽさ）

URL = "https://kouen.sports.metro.tokyo.lg.jp/web/"

# A/B 用のヘッダー・UA
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
ACCEPT_LANG_PREF = "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7"

# XPath
X_DAY        = '//*[@id="daystart-home"]'
X_PURPOSE    = '//*[@id="purpose-home"]'
X_PARK       = '//*[@id="bname-home"]'
X_SEARCH     = '//*[@id="btn-go"]'
X_WEEK_TBODY = '//*[@id="week-info"]/tbody'
X_NEXT_WEEK  = '//*[@id="next-week"]'

SLOT_LABELS = {"10": "9時", "20": "11時", "30": "13時", "40": "15時", "50": "17時", "60": "19時"}
ID_RE  = re.compile(r"A_(\d{8})_(\d{2})")
YMD_RE = re.compile(r"(\d{8})_(10|20|30|40|50|60)")

# エラーメッセージ検知（E）
ERROR_TEXTS = [
    "施設予約システムからのお知らせ",
    "現在、ご指定のページはアクセスできません",
    "ご迷惑をおかけしております",
    "しばらく経ってから、アクセスしてください",
    # 汎用
    "システムエラー",
    "エラーが発生",
]


def jitter(a=JITTER_RANGE[0], b=JITTER_RANGE[1]):
    time.sleep(random.uniform(a, b))


def big_jitter():
    # ページが重い時だけ少し長め
    time.sleep(random.uniform(0.4, 0.8))


def slot_to_hour(code: str) -> str:
    return SLOT_LABELS.get(code, f"slot:{code}")


def is_holiday_or_weekend(d: dt.date) -> bool:
    if d.weekday() >= 5:  # 土=5, 日=6
        return True
    if jpholiday is not None and jpholiday.is_holiday(d):
        return True
    return False


def human_scroll(driver, px=None):
    h = driver.execute_script("return document.body.scrollHeight") or 2000
    if px is None:
        px = random.randint(200, min(1000, h))
    driver.execute_script(f"window.scrollBy(0,{px});")
    jitter()


def human_hover(driver, el):
    try:
        ActionChains(driver).move_to_element(el).perform()
        jitter()
    except Exception:
        pass


def human_click(driver, el):
    human_hover(driver, el)
    try:
        _ = el.location_once_scrolled_into_view
    except Exception:
        pass
    jitter()
    el.click()
    jitter()


def add_basic_stealth(driver):
    # 可能な範囲で webdriver 感を薄める（B）
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": """
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'languages', {get: () => ['ja-JP', 'ja', 'en-US', 'en']});
                Object.defineProperty(navigator, 'platform', {get: () => 'Win32'});
                Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            """}
        )
    except Exception:
        pass


def set_date_js(driver, wait, input_el, ymd_dash: str):
    driver.execute_script("""
      const el = arguments[0], val = arguments[1];
      el.removeAttribute('readonly'); el.removeAttribute('disabled');
      el.value = val; el.setAttribute('value', val);
      el.dispatchEvent(new Event('input', {bubbles:true}));
      el.dispatchEvent(new Event('change',{bubbles:true}));
      el.dispatchEvent(new Event('blur',  {bubbles:true}));
    """, input_el, ymd_dash)
    wait.until(lambda d: (input_el.get_attribute("value") or "") in (ymd_dash, ymd_dash.replace("-", "/")))
    jitter()


def pick_park_value_by_keyword(select_el, keyword: str) -> str | None:
    sel = Select(select_el)
    for opt in sel.options:
        txt = (opt.text or "").strip()
        val = opt.get_attribute("value")
        if val and (keyword in txt):
            return val
    return None


def get_week_range_text(tbody) -> str:
    ymds = []
    for n in tbody.find_elements(By.XPATH, './/*[@id]'):
        _id = n.get_attribute('id') or ''
        m = YMD_RE.search(_id)
        if m: ymds.append(m.group(1))
    if not ymds: return "(範囲不明)"
    ymds = sorted(set(ymds))
    first = dt.datetime.strptime(ymds[0], "%Y%m%d").date()
    last  = dt.datetime.strptime(ymds[-1], "%Y%m%d").date()
    return f"{first} 〜 {last}"


def scrape_week_A_holidays_only(tbody):
    results = []
    for el in tbody.find_elements(By.XPATH, './/*[@id]'):
        cid = el.get_attribute('id') or ''
        m = ID_RE.match(cid)
        if not m:
            continue
        ymd, slot = m.groups()
        try:
            d = dt.datetime.strptime(ymd, "%Y%m%d").date()
        except ValueError:
            continue
        if ONLY_HOLIDAYS and not is_holiday_or_weekend(d):
            continue
        results.append((d, ymd, slot_to_hour(slot)))
    results.sort(key=lambda x: (x[0], x[2]))
    return results


def detect_overload(driver):
    """混雑/エラーっぽい表示の軽い検知（文言は適宜調整）"""
    text = (driver.page_source or "").lower()
    bad_keywords = ["アクセスが集中", "しばらくしてから", "エラーが発生", "ただいま混雑"]
    return any(k.lower() in text for k in bad_keywords)


# ===== A/E: 初期化完了待ち & エラー時ワンリロード =====

def has_session_cookie(driver) -> bool:
    try:
        cookies = driver.get_cookies() or []
        for c in cookies:
            name = (c.get('name') or '').lower()
            if name.startswith('jsessionid') or name in ('jsessionid', 'routeid', 'sessionid'):
                return True
    except Exception:
        pass
    return False


def wait_for_session_ready(driver, wait, timeout=20):
    """A: DOM完了 + セッションCookie + 初期UIの存在まで待つ"""
    wait.until(lambda d: d.execute_script("return document.readyState") == "complete")

    t0 = time.time()
    while time.time() - t0 < timeout:
        cookie_ok = has_session_cookie(driver)
        ui_ok = False
        try:
            # 代表的な初期UI要素（利用日/目的/公園）がDOM上に現れているか
            ui_ok = (
                len(driver.find_elements(By.XPATH, X_DAY)) > 0 and
                len(driver.find_elements(By.XPATH, X_PURPOSE)) > 0 and
                len(driver.find_elements(By.XPATH, X_PARK)) > 0
            )
        except Exception:
            ui_ok = False
        if cookie_ok and ui_ok:
            return True
        time.sleep(0.2)
    return False


def is_error_page(driver) -> bool:
    src = (driver.page_source or "")
    return any(t in src for t in ERROR_TEXTS)


def reload_once_if_error(driver, wait):
    """E: エラーページを検知したら 1 回だけリロード"""
    if is_error_page(driver):
        driver.refresh()
        WebDriverWait(driver, 20).until(lambda d: d.execute_script("return document.readyState") == "complete")
        return True
    return False


# ===== メインフロー =====

def run_for_park(driver, wait, park_keyword: str, start_ts: float):
    print(f"\n>>> [{park_keyword}] 開始")

    # Top へ（A/B: UA/言語済みのオプション + 初期化待ち + E: リロード）
    driver.get(URL)
    jitter(); human_scroll(driver, px=300)

    # 軽い過負荷検知で1回だけ待って再読込
    if detect_overload(driver):
        print("   混雑を検知 → 数秒待ってリロード")
        time.sleep(random.uniform(2, 4))
        driver.get(URL)
        big_jitter()

    # A: 初期化完了待ち（Cookie + UI）
    if not wait_for_session_ready(driver, wait):
        print("   初期化が揃わず → リロード")
        driver.refresh()
        wait_for_session_ready(driver, wait)

    # E: 既にエラーページなら 1 回だけ自動で再読込
    if reload_once_if_error(driver, wait):
        # 再読み込み後も初期化を担保
        wait_for_session_ready(driver, wait)

    # 1) 利用日
    day_el = wait.until(EC.presence_of_element_located((By.XPATH, X_DAY)))
    human_hover(driver, day_el)
    set_date_js(driver, wait, day_el, TARGET_DAY)

    # 2) 種目
    purpose_el = wait.until(EC.presence_of_element_located((By.XPATH, X_PURPOSE)))
    human_hover(driver, purpose_el)
    Select(purpose_el).select_by_value(PURPOSE_VALUE)
    jitter()

    # 3) 公園（ロードが遅いことがあるので数秒粘る）
    park_el = wait.until(EC.presence_of_element_located((By.XPATH, X_PARK)))
    sel_park = Select(park_el)
    for _ in range(15):
        if len(sel_park.options) > 1:
            break
        time.sleep(0.25)
        sel_park = Select(wait.until(EC.presence_of_element_located((By.XPATH, X_PARK))))

    value = pick_park_value_by_keyword(park_el, park_keyword)
    if not value:
        print(f"   [{park_keyword}] 公園が見つかりません（キーワード要確認）")
        return

    Select(park_el).select_by_value(value)
    jitter()

    # 4) 検索
    btn = wait.until(EC.element_to_be_clickable((By.XPATH, X_SEARCH)))
    human_click(driver, btn)

    # E: 検索直後のエラーをワンリロードで救う
    if reload_once_if_error(driver, wait):
        # 検索ボタンまで復帰
        wait.until(EC.presence_of_element_located((By.XPATH, X_SEARCH)))

    all_results = []
    for wk in range(NEXT_WEEKS_TO_CHECK + 1):
        if time.time() - start_ts > MAX_TOTAL_RUNTIME_SEC:
            print("   全体時間ガードにより打ち切り")
            break

        tbody = wait.until(EC.presence_of_element_located((By.XPATH, X_WEEK_TBODY)))
        rng = get_week_range_text(tbody)
        slots = scrape_week_A_holidays_only(tbody)
        all_results.append((wk, rng, slots))

        print(f"   週{wk} 取得: {rng} / 件数 {len(slots)}")
        human_scroll(driver, px=random.randint(200, 600))

        if wk < NEXT_WEEKS_TO_CHECK:
            with suppress(Exception):
                next_btn = wait.until(EC.element_to_be_clickable((By.XPATH, X_NEXT_WEEK)))
                old = tbody
                human_click(driver, next_btn)
                WebDriverWait(driver, 12).until(EC.staleness_of(old))

    # 出力
    print(f"\n==================== [{park_keyword}] の結果（休日A_のみ） ====================")
    total = 0
    for wk, rng, slots in all_results:
        label = "今週" if wk == 0 else f"{wk} 週後"
        print(f"\n--- {label} : {rng} ---")
        if slots:
            for _, ymd, hour in slots:
                print(f"{ymd} {hour} に空きがあります。")
            total += len(slots)
        else:
            print("（該当なし）")
    print(f"\n合計 {total} 件")
    print("====================================================================\n")


def build_options(headless: bool):
    opts = webdriver.ChromeOptions()
    if headless:
        # UC の headless は比較的検知されにくい
        opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1280,900")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--lang=ja-JP")                               # B: 言語ヘッダー
    opts.add_argument(f"--user-agent={USER_AGENT}")                 # B: UA
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])  # B
    opts.add_experimental_option("useAutomationExtension", False)           # B

    # 言語プリファレンス（B: Accept-Language 相当）
    prefs = {
        "intl.accept_languages": ACCEPT_LANG_PREF,
        "profile.default_content_setting_values.notifications": 2,
    }
    # 本番高速化：画像/フォントOFF（ヘッドレス時のみ）
    if headless:
        prefs.update({
            "profile.managed_default_content_settings.images": 2,
            "profile.managed_default_content_settings.fonts": 2,
        })
    opts.add_experimental_option("prefs", prefs)

    # プロファイル利用（自然さUP）
    if CHROME_PROFILE_DIR and os.path.isdir(CHROME_PROFILE_DIR):
        opts.add_argument(f"--user-data-dir={CHROME_PROFILE_DIR}")
        if CHROME_PROFILE_NAME:
            opts.add_argument(f"--profile-directory={CHROME_PROFILE_NAME}")

    return opts


def make_driver():
    headless = not SHOW_BROWSER
    if USE_UC_FIRST:
        try:
            opts = build_options(headless)
            driver = uc.Chrome(options=opts, use_subprocess=True)
            add_basic_stealth(driver)
            return driver
        except Exception:
            print("undetected-chromedriver 失敗 → 通常Seleniumにフォールバック")
    # フォールバック：通常のChrome + できる限りステルス
    opts = build_options(headless)
    driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=opts)
    add_basic_stealth(driver)
    return driver


def main():
    start_ts = time.time()
    driver = make_driver()
    wait = WebDriverWait(driver, 20)

    try:
        # ページ入ったら軽くスクロールで「人間らしさ」
        driver.get("about:blank")
        jitter(); jitter()

        for kw in PARK_KEYWORDS:
            run_for_park(driver, wait, kw, start_ts)
            if time.time() - start_ts > MAX_TOTAL_RUNTIME_SEC:
                print("全体時間ガードにより終了")
                break

    finally:
        with suppress(Exception):
            driver.quit()


if __name__ == "__main__":
    main()

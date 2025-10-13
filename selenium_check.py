# -*- coding: utf-8 -*-
"""
都立公園予約サイトスクレイパ（CI対応版）
- 毎回トップURLから開始（条件変更モーダルは使わない）
- 公園キーワードの配列を順番に処理
- A_セル（空き）だけ抽出
- フィルタは「休日のみ（祝日含む）」になっています（切替可能）
- 「次の週」を NEXT_WEEKS_TO_CHECK 回クリックして先の週も収集
- GitHub ActionsなどCI環境では自動でヘッドレス起動
"""

import os
import time
import re
import datetime as dt

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service as ChromeService

# 祝日ライブラリ（任意）
try:
    import jpholiday
except Exception:
    jpholiday = None

# ===== 設定 =====
TARGET_DAY = (dt.date.today() + dt.timedelta(days=1)).strftime("%Y-%m-%d")  # ← 明日からにする例
PURPOSE_VALUE = "1000_1030"   # テニス（人工芝）
PARK_KEYWORDS = ["東白", "汐入", "舎人", "亀戸中央", "大島小松川", "東綾瀬"]

# フィルタ（どちらか片方だけ True にする想定）
ONLY_HOLIDAYS  = False   # ★休日（祝日含む）のみ表示
ONLY_WEEKDAYS  = True  # 平日のみ（祝日除く）表示

NEXT_WEEKS_TO_CHECK = 5  # 今週＋8週＝計9週
TIMEOUT_SEC = 20
# =================

URL = "https://kouen.sports.metro.tokyo.lg.jp/web/"

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

def setup_driver() -> webdriver.Chrome:
    """ローカルでは画面表示、CIではヘッドレス&安定化フラグを付けて起動"""
    opts = Options()

    # 共通の安定化フラグ
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1280,2000")

    # GitHub Actions等のCI判定（どちらかがあればCIとみなす）
    is_ci = os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get("CI") == "true"

    if is_ci:
        # ヘッドレス（新実装）で起動
        opts.add_argument("--headless=new")
        # setup-chrome@v1 が CHROME_PATH を環境変数で渡すため、それがあれば使う
        chrome_bin = os.environ.get("CHROME_PATH") or os.environ.get("GOOGLE_CHROME_SHIM")
        if chrome_bin:
            opts.binary_location = chrome_bin
    else:
        # ローカルは従来通り見えるウィンドウで
        opts.add_argument("--start-maximized")

    service = ChromeService(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)
    driver.set_page_load_timeout(TIMEOUT_SEC)
    return driver

def slot_to_hour(code: str) -> str:
    return SLOT_LABELS.get(code, f"slot:{code}")

def is_holiday_or_weekend(d: dt.date) -> bool:
    """土日 or 祝日なら True（jpholiday未導入なら土日だけ）"""
    if d.weekday() >= 5:
        return True
    if jpholiday is not None and jpholiday.is_holiday(d):
        return True
    return False

def is_weekday_ex_holiday(d: dt.date) -> bool:
    """平日（祝日除く）"""
    if d.weekday() >= 5:
        return False
    if jpholiday is not None and jpholiday.is_holiday(d):
        return False
    return True

def set_date_js(driver, wait, input_el, ymd_dash: str):
    """readonly/disabled対策＋イベント発火込で日付をセット"""
    driver.execute_script("""
      const el = arguments[0], val = arguments[1];
      el.removeAttribute('readonly'); el.removeAttribute('disabled');
      el.value = val; el.setAttribute('value', val);
      el.dispatchEvent(new Event('input', {bubbles:true}));
      el.dispatchEvent(new Event('change',{bubbles:true}));
      el.dispatchEvent(new Event('blur',  {bubbles:true}));
    """, input_el, ymd_dash)
    wait.until(lambda d: (input_el.get_attribute("value") or "") in (ymd_dash, ymd_dash.replace("-", "/")))

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
        if m:
            ymds.append(m.group(1))
    if not ymds:
        return "(範囲不明)"
    ymds = sorted(set(ymds))
    first = dt.datetime.strptime(ymds[0], "%Y%m%d").date()
    last  = dt.datetime.strptime(ymds[-1], "%Y%m%d").date()
    return f"{first} 〜 {last}"

def scrape_week_A_filtered(tbody):
    """
    この週の A_セル（空き）だけを拾い、フィルタ条件で [(date, ymd, hour)] を返す
    - ONLY_HOLIDAYS=True の場合は 休日（祝日含む）のみ
    - ONLY_WEEKDAYS=True の場合は 平日（祝日除く）のみ
    - 両方Falseなら全日
    """
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

        # フィルタ
        if ONLY_HOLIDAYS and not is_holiday_or_weekend(d):
            continue
        if ONLY_WEEKDAYS and not is_weekday_ex_holiday(d):
            continue

        results.append((d, ymd, slot_to_hour(slot)))
    results.sort(key=lambda x: (x[0], x[2]))
    return results

def run_for_park(driver, wait, park_keyword: str):
    """トップURL→検索→今週＋次週×N の順で収集して表示"""
    # 0) トップへ
    driver.get(URL)

    # 1) 利用日
    day_el = wait.until(EC.presence_of_element_located((By.XPATH, X_DAY)))
    set_date_js(driver, wait, day_el, TARGET_DAY)

    # 2) 種目
    purpose_el = wait.until(EC.presence_of_element_located((By.XPATH, X_PURPOSE)))
    Select(purpose_el).select_by_value(PURPOSE_VALUE)

    # 3) 公園（部分一致で value を取得して選択）
    park_el = wait.until(EC.presence_of_element_located((By.XPATH, X_PARK)))
    sel_park = Select(park_el)
    # ロード直後は option が1件(空)のことがあるため待つ
    for _ in range(20):
        if len(sel_park.options) > 1:
            break
        time.sleep(0.3)
        sel_park = Select(wait.until(EC.presence_of_element_located((By.XPATH, X_PARK))))

    value = pick_park_value_by_keyword(park_el, park_keyword)
    if not value:
        print(f"[{park_keyword}] 公園が見つかりません（キーワードを見直してください）")
        return
    Select(park_el).select_by_value(value)

    # 4) 検索
    btn = wait.until(EC.element_to_be_clickable((By.XPATH, X_SEARCH)))
    btn.click()

    # 5) 今週＋次週×Nを収集
    all_results = []  # [(week_index, range_text, slots)]
    for wk in range(NEXT_WEEKS_TO_CHECK + 1):
        tbody = wait.until(EC.presence_of_element_located((By.XPATH, X_WEEK_TBODY)))
        rng = get_week_range_text(tbody)
        slots = scrape_week_A_filtered(tbody)
        all_results.append((wk, rng, slots))

        if wk < NEXT_WEEKS_TO_CHECK:
            # 次週へ
            try:
                next_btn = wait.until(EC.element_to_be_clickable((By.XPATH, X_NEXT_WEEK)))
            except Exception:
                break  # ボタンが無ければ終了
            old = tbody
            next_btn.click()
            try:
                WebDriverWait(driver, 20).until(EC.staleness_of(old))
            except Exception:
                pass

    # 6) 出力
    mode = "休日A_のみ" if ONLY_HOLIDAYS else ("平日A_のみ" if ONLY_WEEKDAYS else "全日A_")
    print(f"\n==================== [{park_keyword}] の結果（{mode}） ====================")
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

def main():
    driver = setup_driver()
    wait = WebDriverWait(driver, TIMEOUT_SEC)
    try:
        for kw in PARK_KEYWORDS:
            run_for_park(driver, wait, kw)
    finally:
        driver.quit()

if __name__ == "__main__":
    main()

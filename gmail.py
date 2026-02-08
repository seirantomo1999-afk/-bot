# gmail.py
from __future__ import annotations

import base64
import os
import datetime
from concurrent.futures import ThreadPoolExecutor

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

import selenium_check


SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
TO = "seirantomo1999@gmail.com"
SUBJECT = "【自動通知】都立コート 休日空き状況"


def create_message(to: str, subject: str, body_text: str) -> dict:
    msg = MIMEMultipart()
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    return {"raw": raw}


def get_service():
    if not os.path.exists("token.json"):
        raise RuntimeError("token.json が見つかりません（Secrets復元を確認してください）")

    creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    # Actionsでは初回ブラウザ認証不可なので refresh で回す
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open("token.json", "w") as f:
                f.write(creds.to_json())
        else:
            raise RuntimeError("token.json が無効で refresh もできません（refresh_token 必須）")

    return build("gmail", "v1", credentials=creds)


def send_text(service, to: str, subject: str, body_text: str):
    message = create_message(to, subject, body_text)
    service.users().messages().send(userId="me", body=message).execute()


def main():
    service = get_service()

    # 探索を止めないため送信を非同期化
    executor = ThreadPoolExecutor(max_workers=2)

    # 同一実行中の重複通知防止（最低限）
    seen = set()

    def on_hit(park: str, ymd: str, d: datetime.date, hour: str):
        key = f"{park}_{ymd}_{hour}"
        if key in seen:
            return
        seen.add(key)

        w = "月火水木金土日"[d.weekday()]
        body = f"{park} {ymd}({w}) {hour} に空きがあります。"

        # ★見つけた瞬間に送信（探索は継続）
        executor.submit(send_text, service, TO, SUBJECT, body)

    start_ts = selenium_check.time.time()
    driver = selenium_check.make_driver()
    wait = selenium_check.WebDriverWait(driver, 20)

    try:
        driver.get("about:blank")
        selenium_check.jitter(); selenium_check.jitter()

        for kw in selenium_check.PARK_KEYWORDS:
            selenium_check.run_for_park(driver, wait, kw, start_ts, on_hit=on_hit)

    finally:
        # Actionsで送信が落ちないよう必ず完了待ち
        executor.shutdown(wait=True)
        with selenium_check.suppress(Exception):
            driver.quit()


if __name__ == "__main__":
    main()

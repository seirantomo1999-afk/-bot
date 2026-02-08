# gmail.py
from __future__ import annotations
import os, base64, datetime
from concurrent.futures import ThreadPoolExecutor

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import selenium_check


SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
TO = "seirantomo1999@gmail.com"
SUBJECT = "【自動通知】都立コート 休日空き状況"


def get_service():
    creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open("token.json", "w") as f:
            f.write(creds.to_json())
    return build("gmail", "v1", credentials=creds)


def send_text(service, to, subject, body):
    msg = MIMEMultipart()
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    service.users().messages().send(userId="me", body={"raw": raw}).execute()


def main():
    service = get_service()
    executor = ThreadPoolExecutor(max_workers=2)
    seen = set()

    def on_hit(park, ymd, d, hour):
        key = f"{park}_{ymd}_{hour}"
        if key in seen:
            return
        seen.add(key)
        w = "月火水木金土日"[d.weekday()]
        body = f"{park} {ymd}({w}) {hour} に空きがあります。"
        executor.submit(send_text, service, TO, SUBJECT, body)

    start_ts = selenium_check.time.time()
    driver = selenium_check.make_driver()
    wait = selenium_check.WebDriverWait(driver, 20)

    try:
        for kw in selenium_check.PARK_KEYWORDS:
            selenium_check.run_for_park(
                driver, wait, kw, start_ts, on_hit=on_hit
            )
    finally:
        executor.shutdown(wait=True)
        driver.quit()


if __name__ == "__main__":
    main()

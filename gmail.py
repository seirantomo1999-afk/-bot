# gmail.py 監視ラッパー版
from __future__ import annotations

import base64
import os
import subprocess
import sys
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request


SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
TO = "seirantomo1999@gmail.com"


def get_service():
    creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open("token.json", "w") as f:
                f.write(creds.to_json())
        else:
            raise RuntimeError("token.json が無効で refresh もできません（refresh_token 必須）")
    return build("gmail", "v1", credentials=creds)


def create_message(to: str, subject: str, body_text: str) -> dict:
    msg = MIMEMultipart()
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    return {"raw": raw}


def send_message(service, subject: str, body: str):
    msg = create_message(to=TO, subject=subject, body_text=body or "(本文なし)")
    service.users().messages().send(userId="me", body=msg).execute()


def main():
    service = get_service()

    # selenium_check.py は「空きがあれば中で即通知」をする前提で、ここでは監視だけする
    result = subprocess.run(
        [sys.executable, "selenium_check.py"],
        capture_output=True,
        text=True,
        timeout=900
    )

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()

    # 異常終了ならエラーメール
    if result.returncode != 0:
        subject = "【エラー】都立コート bot 実行失敗"
        body = f"""selenium_check.py が異常終了しました。

returncode: {result.returncode}

--- stdout ---
{stdout or "(なし)"}

--- stderr ---
{stderr or "(なし)"}
"""
        send_message(service, subject, body[:7000])
        print("Sent error email.")
        sys.exit(0)  # ★ワークフローは成功扱いにする

    # 正常終了（空き無しでもOK）
    print("selenium_check.py finished normally.")
    sys.exit(0)


if __name__ == "__main__":
    main()

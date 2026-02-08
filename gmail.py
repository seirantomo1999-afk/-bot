# gmail.py
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


def send_text(service, subject: str, body: str):
    msg = MIMEMultipart()
    msg["To"] = TO
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    service.users().messages().send(userId="me", body={"raw": raw}).execute()


def main():
    service = get_service()

    result = subprocess.run(
        [sys.executable, "selenium_check.py"],
        capture_output=True,
        text=True,
        timeout=900
    )

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()

    print("=== selenium_check.py finished ===")
    print("returncode:", result.returncode)

    # 異常終了ならエラーメール
    if result.returncode != 0:
        subject = "【エラー】都立コート通知bot 失敗"
        body = f"""selenium_check.py が異常終了しました。

returncode: {result.returncode}

--- stdout ---
{stdout or "(なし)"}

--- stderr ---
{stderr or "(なし)"}
"""
        try:
            send_text(service, subject, body[:7000])
            print("Sent error email.")
        except Exception as e:
            print("[ERROR] Failed to send error email:", e)

        sys.exit(0)  # ★workflowは成功扱い

    # 正常終了（空きなしでもOK）
    sys.exit(0)


if __name__ == "__main__":
    main()

# gmail.py 監視ラッパー強化版
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
    if not os.path.exists("token.json"):
        raise RuntimeError("token.json が見つかりません（Secrets復元を確認）")
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

    # 子プロセス実行
    result = subprocess.run(
        [sys.executable, "selenium_check.py"],
        capture_output=True,
        text=True,
        timeout=900,
        env={**os.environ, "GITHUB_ACTIONS": "true"},
    )

    stdout = (result.stdout or "")
    stderr = (result.stderr or "")

    # ★ここが重要：必ずログに出す（原因切り分け用）
    print("=== selenium_check.py finished ===")
    print("returncode:", result.returncode)
    print("--- stderr (head) ---")
    print(stderr[:2000] if stderr else "(empty)")
    print("--- stdout (head) ---")
    print(stdout[:2000] if stdout else "(empty)")

    # エラー判定（returncode != 0 だけだと見逃すケースがあるので、stderrも見る）
    is_error = (result.returncode != 0) or ("Traceback" in stderr) or ("free():" in stderr) or ("core dumped" in stderr)

    if is_error:
        subject = "【エラー】都立コートbot 実行失敗"
        body = f"""selenium_check.py が失敗扱いになりました。

returncode: {result.returncode}

--- stderr ---
{stderr or "(なし)"}

--- stdout ---
{stdout or "(なし)"}
"""
        try:
            send_text(service, subject, body[:7000])
            print("Sent error email.")
        except Exception as e:
            # ★メール送れない理由をログに残す（これが今見えてない可能性大）
            print("[ERROR] Failed to send error email:", e)

    # ★運用方針：ワークフローは成功扱い（以前と同じ）
    sys.exit(0)


if __name__ == "__main__":
    main()


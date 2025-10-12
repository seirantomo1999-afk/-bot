# gmail_send.py
from __future__ import annotations
import base64, os, subprocess, sys
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request  # refresh用

# Gmail送信スコープ
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

def get_service():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)  # 初回だけブラウザで許可
        with open("token.json", "w") as f:
            f.write(creds.to_json())
    return build("gmail", "v1", credentials=creds)

def create_message(to: str, subject: str, body_text: str) -> dict:
    msg = MIMEMultipart()
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    return {"raw": raw}

def send_message(service, user_id: str, message: dict):
    return service.users().messages().send(userId=user_id, body=message).execute()

if __name__ == "__main__":
    print("Running:", __file__)
    service = get_service()

    # ===== スクレイピングの結果を本文にする =====
    result = subprocess.run(
        ["python", r"C:\Users\seira\OneDrive\デスクトップ\selenium_check.py"],
        capture_output=True, text=True, timeout=900
    )
    raw_out = (result.stdout or "").splitlines()
    raw_err = (result.stderr or "").strip()

    # --- ② 「該当なし」行とその1つ上の行も除外 ---
    DROP_KEYWORDS = ("該当なし", "空きなし", "A_で始まるセルは見つかりません")

    filtered = []
    skip_prev = False  # 前行を削除フラグ
    for i, ln in enumerate(raw_out):
        if any(k in ln for k in DROP_KEYWORDS):
            # 直前の1行を削除（残っていれば）
            if filtered:
                filtered.pop()
            skip_prev = True
            continue
        if skip_prev:
            # 該当なしの直後の空行などもスキップ
            skip_prev = False
            if ln.strip() == "":
                continue
        filtered.append(ln)

    body = "\n".join(filtered).strip()

    # --- ① 全部が「該当なし」なら送信しない ---
    has_hit = any("に空きがあります" in ln for ln in filtered)

    # スクレイパ異常終了時はエラーメールに切り替え（任意）
    if result.returncode != 0:
        subject = "【エラー】都立公園スクレイピング失敗"
        body = (body + "\n\n--- エラー出力 ---\n" + (raw_err or "(なし)")).strip()
        to = "seirantomo1999@gmail.com"
        msg = create_message(to=to, subject=subject, body_text=body or "(本文なし)")
        resp = send_message(service, "me", msg)
        print("Sent (error report):", resp.get("id"))
        sys.exit(0)

    # 空きヒットが無ければ送らず終了
    if not has_hit:
        print("空きが見つからなかったため、メール送信をスキップしました。")
        sys.exit(0)

    # 空きあり → 通知送信
    subject = "【自動通知】都立公園 平日空き状況"
    to = "seirantomo1999@gmail.com"
    msg = create_message(to=to, subject=subject, body_text=body or "(本文なし)")
    resp = send_message(service, "me", msg)
    print("Sent:", resp.get("id"))

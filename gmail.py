# gmail_send.py
from __future__ import annotations
import base64, os, subprocess, sys
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request  # refresh用
import datetime, re
def get_weekday_jp(date_str: str) -> str:
    dt = datetime.datetime.strptime(date_str, "%Y%m%d")
    return "月火水木金土日"[dt.weekday()]

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
    ["python", "selenium_check.py"],
        capture_output=True, text=True, timeout=900
    )
    raw_out = (result.stdout or "").splitlines()
        # === 必要な空き行だけ抽出 & 整形 ===
    park_pattern = re.compile(r"^>>> \[(.+?)\]")     # 公園名
    slot_pattern = re.compile(r"^(\d{8})\s+(.*)$")   # YYYYMMDD 19時 に空きがあります。
    
    lines = []
    current_park = None
    
    for ln in raw_out:
        # 公園名検出
        m_park = park_pattern.match(ln)
        if m_park:
            current_park = m_park.group(1)
            continue

        # 空き行検出
        if "に空きがあります" in ln:
            m_slot = slot_pattern.match(ln.strip())
            if m_slot:
                date_str = m_slot.group(1)
                rest    = m_slot.group(2)
                w = get_weekday_jp(date_str)
                lines.append(f"{current_park} {date_str}({w}) {rest}")  # ← 全角スペース4つ

    # 本文に変換（空行なし）
    body = "\n".join(lines).strip()
    
    raw_err = (result.stderr or "").strip()

    # 空きが1件でもあれば True
    has_hit = bool(lines)

    raw_err = (result.stderr or "").strip()

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
    subject = "【自動通知】都立コート 休日空き状況"
    to = "seirantomo1999@gmail.com"
    msg = create_message(to=to, subject=subject, body_text=body or "(本文なし)")
    resp = send_message(service, "me", msg)
    print("Sent:", resp.get("id"))

# hkbot/cloud.py
import os
import requests

WA_API = "https://graph.facebook.com/v20.0"

PHONE_ID = os.getenv("WA_PHONE_NUMBER_ID")  # e.g. 8480475...
TOKEN    = os.getenv("WA_TOKEN")            # Access Token（先用短期，建議改永久）
HEADERS  = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

def _post_json(path: str, payload: dict):
    """統一送出 & 在 4xx/5xx 印出 Graph API 錯誤 body，便於除錯。"""
    url = f"{WA_API}/{PHONE_ID}{path}"
    r = requests.post(url, json=payload, headers=HEADERS, timeout=10)
    if r.status_code >= 400:
        # 回傳更清楚的錯誤訊息（包含 Graph API 的 JSON 內容）
        raise requests.HTTPError(f"{r.status_code} {r.reason}: {url} | {r.text}")
    return r.json()

def send_text(to: str, text: str):
    data = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text[:3500]}
    }
    return _post_json("/messages", data)

def send_buttons(to: str, body_text: str, buttons: list):
    """
    buttons: [{"id":"opt_swing","title":"波段"}, {"id":"opt_short","title":"短線"}]
    """
    data = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {"buttons": [
                {"type": "reply", "reply": {"id": b["id"], "title": b["title"]}}
                for b in buttons[:3]
            ]}
        }
    }
    return _post_json("/messages", data)

def send_list(to: str, header: str, body_text: str, sections: list, button_text: str = "選擇"):
    """
    sections: [{"title":"期間","rows":[{"id":"days_60","title":"60 天"}, ...]}]
    """
    data = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {"type": "text", "text": header[:60]},
            "body": {"text": body_text},
            "action": {"button": button_text[:20], "sections": sections}
        }
    }
    return _post_json("/messages", data)
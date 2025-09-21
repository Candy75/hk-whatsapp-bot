# hkbot/cloud.py
import os, requests

WA_API = "https://graph.facebook.com/v20.0"

PHONE_ID = os.getenv("WA_PHONE_NUMBER_ID")
TOKEN    = os.getenv("WA_TOKEN")
HEADERS  = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

def send_text(to: str, text: str):
    url = f"{WA_API}/{PHONE_ID}/messages"
    data = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text[:3500]}}
    r = requests.post(url, json=data, headers=HEADERS, timeout=10); r.raise_for_status(); return r.json()

def send_buttons(to: str, body_text: str, buttons: list):
    """
    buttons: [{"id":"opt_swing","title":"波段"}, {"id":"opt_short","title":"短線"}]
    """
    url = f"{WA_API}/{PHONE_ID}/messages"
    payload = {
      "messaging_product": "whatsapp",
      "to": to,
      "type": "interactive",
      "interactive": {
        "type": "button",
        "body": {"text": body_text},
        "action": {"buttons": [
          {"type":"reply","reply":{"id":b["id"],"title":b["title"]}} for b in buttons[:3]
        ]}
      }
    }
    r = requests.post(url, json=payload, headers=HEADERS, timeout=10); r.raise_for_status(); return r.json()

def send_list(to: str, header: str, body_text: str, sections: list, button_text="選擇"):
    """
    sections: [{"title":"期間","rows":[{"id":"days_60","title":"60 天"},{"id":"days_120","title":"120 天"}]}]
    """
    url = f"{WA_API}/{PHONE_ID}/messages"
    payload = {
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
    r = requests.post(url, json=payload, headers=HEADERS, timeout=10); r.raise_for_status(); return r.json()
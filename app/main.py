# app/main.py
import os, re, html, json, logging
from urllib.parse import parse_qs
from fastapi import FastAPI, Request, Response, status

# 你的功能模組
from hkbot.logic import parse_codes_from_text, build_whatsapp_summary
# Cloud API 發送（buttons/list/text）
from hkbot.cloud import send_text, send_buttons, send_list

app = FastAPI()
log = logging.getLogger("uvicorn.error")

# ======== 共用 ========
HELP_TEXT = (
    "🤖 使用說明：\n"
    "• 直接輸入代碼（可多隻）：例如 9988, 06618\n"
    "• 參數：mode=short|swing|position、days=60/90/120/240…\n"
    "  範例：9988 6618 mode=swing days=120\n"
    "• 輸入 help 取得互動選單\n"
    "— 本服務僅供教育參考，非投資建議 —"
)

def _parse_mode_days(txt: str):
    m = re.search(r"mode\s*=\s*(short|swing|position)", txt, re.I)
    d = re.search(r"days\s*=\s*(\d{1,4})", txt, re.I)
    mode = (m.group(1).lower() if m else "swing")
    days = int(d.group(1)) if d else 120
    days = max(60, min(days, 1000))
    return mode, days

# ======== 健康檢查 ========
@app.get("/health")
async def health():
    return {"ok": True}

# =====================================================================
#                          A) WhatsApp Cloud API
# =====================================================================

VERIFY_TOKEN = os.getenv("WA_VERIFY_TOKEN", "change-me")

# ---- A-1) Verify webhook (正式) ----
@app.get("/wa-webhook")
async def wa_verify(request: Request):
    """
    Meta 會用 GET 驗證：
      hub.mode=subscribe
      hub.verify_token=你的驗證字串
      hub.challenge=隨機字串
    我們需在 token 相符時，200/純文字回傳 hub.challenge。
    """
    params = dict(request.query_params)
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge", "")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return Response(content=challenge, media_type="text/plain", status_code=200)
    return Response(content="Verification failed.", media_type="text/plain", status_code=status.HTTP_403_FORBIDDEN)

# ---- A-2) Receive messages (互動/文字) ----
@app.post("/wa-webhook")
async def wa_webhook(request: Request):
    """
    處理 Cloud API 來的訊息（buttons/list/text）。
    這裡採『處理第一則 message』的簡化邏輯；有需要可擴充迴圈。
    """
    try:
        data = await request.json()
    except Exception as e:
        log.exception("wa_webhook json parse err: %r", e)
        return {"status": "ignored"}

    try:
        entry = (data.get("entry") or [])[0]
        change = (entry.get("changes") or [])[0]
        value = change.get("value") or {}
        messages = value.get("messages") or []
        if not messages:
            return {"status": "no_messages"}

        msg = messages[0]
        wa_from = msg.get("from")  # 純數字的國碼電話（收件人）
        profile = (msg.get("profile") or {})
        # 使用者文字
        text_body = (msg.get("text") or {}).get("body", "").strip()

        # 1) 互動回覆：Buttons
        interactive = msg.get("interactive")
        if interactive and interactive.get("type") == "button":
            br = interactive.get("button_reply") or {}
            btn_id = br.get("id", "")
            mapping = {
                "opt_short": "short",
                "opt_swing": "swing",
                "opt_position": "position",
            }
            if btn_id in mapping:
                mode = mapping[btn_id]
                send_text(wa_from, f"✅ 已選擇模式：{mode}。\n請輸入代碼，例如：9988 06618（可再加 days=120）")
                return {"ok": True}

        # 2) 互動回覆：List
        if interactive and interactive.get("type") == "list":
            lr = interactive.get("list_reply") or {}
            lid = lr.get("id", "")
            if lid.startswith("days_"):
                try:
                    days = int(lid.split("_", 1)[1])
                    send_text(wa_from, f"✅ 已選擇期間：{days} 天。\n請輸入代碼，例如：9988 06618（可再加 mode=swing）")
                    return {"ok": True}
                except Exception:
                    pass

        # 3) 文字命令
        low = text_body.lower()
        if low in ("help", "menu", "？", "h"):
            # 先給按鈕選模式
            send_buttons(wa_from, "請選擇分析模式：", [
                {"id": "opt_short", "title": "短線"},
                {"id": "opt_swing", "title": "波段"},
                {"id": "opt_position", "title": "中長線"},
            ])
            # 再送清單選期間
            send_list(wa_from, "期間", "請選擇資料期間：", [{
                "title": "期間",
                "rows": [
                    {"id": "days_60", "title": "60 天"},
                    {"id": "days_120", "title": "120 天"},
                    {"id": "days_240", "title": "240 天"},
                ]
            }], button_text="選擇")
            return {"ok": True}

        if low in ("ping", "hi", "hello"):
            send_text(wa_from, "pong ✅ 服務正常")
            return {"ok": True}

        # 4) 直接輸入代碼
        if text_body:
            mode, days = _parse_mode_days(text_body)
            symbols = parse_codes_from_text(text_body)
            if symbols:
                text = build_whatsapp_summary(symbols, days=days, mode=mode)
                send_text(wa_from, text)
                return {"ok": True}

        # 若無法解析，提示 help
        send_text(wa_from, "請輸入代碼（例如 9988 06618），或輸入 help 使用互動選單。")
        return {"ok": True}

    except Exception as e:
        log.exception("wa_webhook error: %r | payload=%s", e, json.dumps(data)[:500])
        # 回 200 讓 Meta 不重試太多次
        return {"error": str(e)}

# =====================================================================
#                          B) Twilio（可選，沿用）
# =====================================================================

def _twiml_message(body: str) -> str:
    esc = html.escape(body)
    return f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{esc}</Message></Response>'

async def read_twilio_form(request: Request) -> dict:
    """
    先試 Starlette 的 form()；失敗則 fallback 解析 raw x-www-form-urlencoded。
    """
    try:
        form = await request.form()  # 需要 python-multipart
        return {k: v for k, v in form.items()}
    except Exception as e:
        raw = (await request.body()).decode("utf-8", "ignore")
        parsed = parse_qs(raw, keep_blank_values=True)
        fallback = {k: (v[0] if isinstance(v, list) and v else "") for k, v in parsed.items()}
        log.warning("Twilio form parse failed, fallback used. err=%r raw=%r", e, raw[:300])
        return fallback

@app.post("/whatsapp")
async def twilio_webhook(request: Request):
    """
    舊的 Twilio Sandbox 路由（保留）。若你只用 Cloud API，可以不設定 Twilio 的 webhook。
    """
    try:
        form = await read_twilio_form(request)
        body = (form.get("Body") or "").strip()
        from_num = form.get("From") or ""

        if not body:
            return Response(content=_twiml_message("請輸入代碼，或輸入 help 查看說明。"),
                            media_type="application/xml")

        if body.lower() in ("help", "menu", "？", "h"):
            return Response(content=_twiml_message(HELP_TEXT), media_type="application/xml")

        if body.lower() == "ping":
            return Response(content=_twiml_message("pong ✅"), media_type="application/xml")

        mode, days = _parse_mode_days(body)
        symbols = parse_codes_from_text(body)
        if not symbols:
            return Response(content=_twiml_message("沒有偵測到有效代碼，請輸入如：9988, 06618（可加 mode= 與 days=）"),
                            media_type="application/xml")

        text = build_whatsapp_summary(symbols, days=days, mode=mode)
        return Response(content=_twiml_message(text), media_type="application/xml")

    except Exception as e:
        log.exception("twilio_webhook error: %r", e)
        return Response(content=_twiml_message("伺服器忙線中，請稍後再試 🙏"),
                        media_type="application/xml", status_code=200)
# app/main.py
import html, re, logging
from urllib.parse import parse_qs
from fastapi import FastAPI, Request, Response
from hkbot.logic import parse_codes_from_text, build_whatsapp_summary

app = FastAPI()
log = logging.getLogger("uvicorn.error")

HELP_TEXT = (
    "🤖 使用說明：\n"
    "• 直接輸入代碼（可多隻）：例如 9988, 06618\n"
    "• 可加參數：mode=short|swing|position、days=60/90/120/240…\n"
    "  範例：9988 6618 mode=swing days=120\n"
    "• 輸入 help 取得說明\n"
    "— 本服務僅供教育參考，非投資建議 —"
)

def _parse_mode_days(txt: str):
    m = re.search(r"mode\s*=\s*(short|swing|position)", txt, re.I)
    d = re.search(r"days\s*=\s*(\d{1,4})", txt, re.I)
    mode = (m.group(1).lower() if m else "swing")
    days = int(d.group(1)) if d else 90
    days = max(60, min(days, 1000))
    return mode, days

def _twiml_message(body: str) -> str:
    esc = html.escape(body)
    return f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{esc}</Message></Response>'

async def read_twilio_form(request: Request) -> dict:
    """
    先嘗試 Starlette 的 form()；失敗就解析 raw body（x-www-form-urlencoded）。
    確保回傳的是普通 dict，值為字串。
    """
    try:
        form = await request.form()  # 需要 python-multipart
        return {k: v for k, v in form.items()}
    except Exception as e:
        # fallback：解析原始 body
        raw = (await request.body()).decode("utf-8", "ignore")
        parsed = parse_qs(raw, keep_blank_values=True)
        # 取第一個值
        fallback = {k: (v[0] if isinstance(v, list) and v else "") for k, v in parsed.items()}
        log.warning("Form parse failed, used fallback. err=%r raw=%r", e, raw[:300])
        return fallback

@app.get("/health")
async def health():
    return {"ok": True}

@app.post("/whatsapp")
async def whatsapp_webhook(request: Request):
    try:
        form = await read_twilio_form(request)
        body = (form.get("Body") or "").strip()
        _from = form.get("From") or ""

        if not body:
            return Response(content=_twiml_message("請輸入港股代碼，或輸入 help 查看說明。"),
                            media_type="application/xml")

        if body.lower() in ("help", "menu", "？", "h"):
            return Response(content=_twiml_message(HELP_TEXT), media_type="application/xml")

        mode, days = _parse_mode_days(body)
        symbols = parse_codes_from_text(body)
        if not symbols:
            return Response(content=_twiml_message("沒有偵測到有效代碼，請輸入如：9988, 06618（可加 mode= 與 days=）"),
                            media_type="application/xml")

        text = build_whatsapp_summary(symbols, days=days, mode=mode)
        return Response(content=_twiml_message(text), media_type="application/xml")

    except Exception as e:
        # 把詳細錯誤寫 log，不把 stacktrace 回給 Twilio
        log.exception("whatsapp_webhook error: %r", e)
        return Response(content=_twiml_message("伺服器忙線中，請稍後再試 🙏"),
                        media_type="application/xml", status_code=200)
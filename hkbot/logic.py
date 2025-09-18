# hkbot/logic.py

import re
import requests
import pandas as pd
import yfinance as yf

# ---------- 代碼驗證 ----------
def validate_hk_stock_code(input_code: str):
    if not input_code:
        return None
    code = input_code.strip().upper().replace('.HK','')
    if not code.isdigit() or len(code) > 5:
        return None
    return f"{code.zfill(4)}.HK"

def parse_codes_from_text(text: str, max_n=5):
    # 抓 1~5 位數字，避免把電話號碼吃進來；你也可要求用逗號分隔
    cands = re.findall(r'\b(\d{1,5})\b', text)
    codes = []
    for c in cands:
        sym = validate_hk_stock_code(c)
        if sym and sym not in codes:
            codes.append(sym)
        if len(codes) >= max_n:
            break
    return codes

# ---------- 名稱查詢（Yahoo API，找不到就回 symbol） ----------
def get_stock_names(symbol: str):
    try:
        r = requests.get(
            "https://query1.finance.yahoo.com/v7/finance/quote",
            params={"symbols": symbol, "lang": "zh-Hant-TW", "region": "TW"},
            timeout=6
        )
        res = (r.json().get("quoteResponse") or {}).get("result") or []
        if res:
            name = res[0].get("shortName") or res[0].get("longName") or res[0].get("displayName")
            return name or symbol
    except Exception:
        pass
    return symbol

# ---------- yfinance 批次下載 ----------
def get_multiple_stocks_data(symbols, days=90):
    if not symbols:
        return {}
    data = {}
    try:
        df = yf.download(
            tickers=" ".join(symbols),
            period=f"{max(days, 60)}d",  # 至少 60 天，避免資料過少
            interval="1d",
            group_by="ticker",
            auto_adjust=False,
            progress=False,
            threads=True
        )
        for sym in symbols:
            if isinstance(df.columns, pd.MultiIndex):
                if sym in df.columns.levels[0]:
                    sub = df[sym].dropna().copy()
                else:
                    continue
            else:
                sub = df.copy()
            if not sub.empty:
                need = [c for c in ['Open','High','Low','Close','Volume'] if c in sub.columns]
                if len(need) >= 4:
                    data[sym] = sub[need].copy()
    except Exception:
        pass
    return data

# ---------- AI 建議（沿用你 V9.4 的簡化版） ----------
def _rsi(series: pd.Series, period=14):
    s = series.astype(float)
    delta = s.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    roll_up = up.ewm(alpha=1/period, adjust=False).mean()
    roll_down = down.ewm(alpha=1/period, adjust=False).mean().replace(0, 1e-9)
    rs = roll_up / roll_down
    return 100 - (100 / (1 + rs))

def ai_recommendation(df: pd.DataFrame, mode="swing"):
    if df is None or df.empty:
        return {'label': '持有', 'reason': '資料不足'}
    if mode == "short":
        ema_fast, ema_slow, rsi_p, vol_n, min_rows = 10, 20, 7, 10, 30
    elif mode == "position":
        ema_fast, ema_slow, rsi_p, vol_n, min_rows = 50, 100, 14, 50, 80
    else:
        ema_fast, ema_slow, rsi_p, vol_n, min_rows = 20, 50, 14, 20, 50
    if len(df) < min_rows:
        return {'label': '持有', 'reason': f'資料不足（<{min_rows} 筆）'}
    data = df.copy().astype(float)
    data[f'EMA{ema_fast}'] = data['Close'].ewm(span=ema_fast, adjust=False).mean()
    data[f'EMA{ema_slow}'] = data['Close'].ewm(span=ema_slow, adjust=False).mean()
    data['RSI'] = _rsi(data['Close'], rsi_p)
    data['VOLN'] = data['Volume'].rolling(20).mean()

    last = data.iloc[-1]
    price = float(last['Close'])
    ema_f = float(last[f'EMA{ema_fast}'])
    ema_s = float(last[f'EMA{ema_slow}'])
    rsi = float(last['RSI'])
    vol = float(last['Volume'])
    voln = float(last['VOLN']) if pd.notna(last['VOLN']) else None

    hi, lo = float(data['Close'].max()), float(data['Close'].min())
    pos = (price - lo) / (hi - lo + 1e-9)

    score, reasons = 0, []
    if price > ema_f > ema_s:
        score += 2; reasons.append(f"價格>EMA{ema_fast}>EMA{ema_slow}（多頭）")
    elif price < ema_f < ema_s:
        score -= 2; reasons.append(f"價格<EMA{ema_fast}<EMA{ema_slow}（空頭）")
    else:
        reasons.append("均線訊號混合")
    if rsi < 35:
        score += 1; reasons.append(f"RSI={rsi:.1f} 偏低")
    elif rsi > 65:
        score -= 1; reasons.append(f"RSI={rsi:.1f} 偏高")
    if voln and voln > 0:
        ratio = vol / max(1.0, voln)
        if ratio >= 1.5:
            score += 1; reasons.append(f"量能放大（{ratio:.2f}×）")
        elif ratio <= 0.7:
            score -= 1; reasons.append(f"量能偏弱（{ratio:.2f}×）")
    if pos >= 0.85:
        score -= 1; reasons.append("接近區間高位")
    elif pos <= 0.15:
        score += 1; reasons.append("接近區間低位")

    if score >= 2: label = "買入"
    elif score <= -2: label = "賣出"
    else: label = "持有"
    return {'label': label, 'reason': "；".join(reasons[:4])}

# ---------- 把結果組成 WhatsApp 短訊 ----------
def build_whatsapp_summary(symbols, days=90, mode="swing"):
    data = get_multiple_stocks_data(symbols, days=days)
    if not data:
        return "查無有效數據，請確認代碼或稍後再試。"

    lines = []
    lines.append(f"📊 期間：最近 {max(days,60)} 天｜模式：{ {'short':'短線','swing':'波段','position':'中長線'}.get(mode,'波段') }")
    for sym in symbols:
        df = data.get(sym)
        if df is None or df.empty: 
            lines.append(f"{sym}：無資料")
            continue
        name = get_stock_names(sym)
        last = df.iloc[-1]['Close']
        if len(df) >= 2:
            prev = df.iloc[-2]['Close']
            chg = (last/prev - 1) * 100.0
            chg_str = f"{chg:+.2f}%"
        else:
            chg_str = "---"
        ai = ai_recommendation(df, mode=mode)
        lines.append(f"• {sym} {name}｜收 HK${last:.2f}（日變{chg_str}）｜AI：{ai['label']}（{ai['reason']}）")
    lines.append("— 本訊息僅供參考，非投資建議 —")
    txt = "\n".join(lines)
    # WhatsApp 單則訊息最好 < 4096 chars
    return txt[:3500]
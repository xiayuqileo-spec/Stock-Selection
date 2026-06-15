#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import datetime

import numpy as np
import pandas as pd
import requests
from bokeh.embed import components
from bokeh.layouts import column
from bokeh.models import ColumnDataSource, HoverTool, Span
from bokeh.plotting import figure


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://gu.qq.com/",
}


def _symbol(code):
    if code.startswith(("4", "8")):
        return f"bj{code}"
    return f"sh{code}" if code.startswith(("5", "6", "9")) else f"sz{code}"


def _number(items, index, default=0.0):
    try:
        return float(items[index])
    except (IndexError, TypeError, ValueError):
        return default


def fetch_quote(code):
    response = requests.get(f"https://qt.gtimg.cn/q={_symbol(code)}", headers=HEADERS, timeout=12)
    response.raise_for_status()
    response.encoding = "gbk"
    values = response.text.split('="', 1)[1].rsplit('"', 1)[0].split("~")
    if len(values) < 35 or not values[1]:
        raise ValueError("未找到该股票的实时行情")
    return {
        "name": values[1], "code": values[2], "price": _number(values, 3),
        "previous_close": _number(values, 4), "open": _number(values, 5),
        "updated_at": values[30], "change": _number(values, 31),
        "change_percent": _number(values, 32), "high": _number(values, 33),
        "low": _number(values, 34), "amount": _number(values, 37),
        "turnover": _number(values, 38), "pe": _number(values, 39),
        "market_cap": _number(values, 45), "pb": _number(values, 46),
        "limit_up": _number(values, 47), "limit_down": _number(values, 48),
        "volume_ratio": _number(values, 49),
    }


def fetch_history(code):
    today = datetime.date.today()
    start = (today - datetime.timedelta(days=900)).strftime("%Y-%m-%d")
    params = {"param": f"{_symbol(code)},day,{start},{today:%Y-%m-%d},520,qfq"}
    response = requests.get(
        "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
        params=params, headers=HEADERS, timeout=15,
    )
    response.raise_for_status()
    item = response.json().get("data", {}).get(_symbol(code), {})
    rows = item.get("qfqday") or item.get("day") or []
    if len(rows) < 60:
        raise ValueError("历史行情数据不足，暂时无法计算技术指标")
    data = pd.DataFrame([row[:6] for row in rows], columns=["date", "open", "close", "high", "low", "volume"])
    for field in ("open", "close", "high", "low", "volume"):
        data[field] = pd.to_numeric(data[field], errors="coerce").fillna(0.0)
    data["volume"] *= 100
    data["p_change"] = data["close"].pct_change(fill_method=None).fillna(0) * 100
    return data


def _ema(series, span):
    return series.ewm(span=span, adjust=False).mean()


def calculate_indicators(data):
    data = data.copy()
    for days in (20, 50, 200):
        data[f"ma{days}"] = data["close"].rolling(days, min_periods=1).mean()
    data["macd"] = _ema(data["close"], 12) - _ema(data["close"], 26)
    data["macds"] = _ema(data["macd"], 9)
    data["macdh"] = data["macd"] - data["macds"]
    delta = data["close"].diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = -delta.clip(upper=0).ewm(alpha=1 / 14, adjust=False).mean()
    data["rsi"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    previous_close = data["close"].shift(1)
    true_range = pd.concat([
        data["high"] - data["low"],
        (data["high"] - previous_close).abs(),
        (data["low"] - previous_close).abs(),
    ], axis=1).max(axis=1)
    data["atr"] = true_range.ewm(alpha=1 / 14, adjust=False).mean()
    data["boll"] = data["close"].rolling(20, min_periods=1).mean()
    std = data["close"].rolling(20, min_periods=1).std().fillna(0)
    data["boll_ub"] = data["boll"] + 2 * std
    data["boll_lb"] = data["boll"] - 2 * std
    return data.fillna(0)


def _signal(label, result, detail, tone="neutral"):
    return {"label": label, "result": result, "detail": detail, "tone": tone}


def build_summary(data):
    latest, previous = data.iloc[-1], data.iloc[-2]
    close, open_price = float(latest["close"]), float(latest["open"])
    ma20, ma50, ma200 = (float(latest[x]) for x in ("ma20", "ma50", "ma200"))
    macd, macds, macdh = (float(latest[x]) for x in ("macd", "macds", "macdh"))
    rsi, atr = float(latest["rsi"]), float(latest["atr"])
    volume_ratio = float(latest["volume"] / data.tail(6).head(5)["volume"].mean())
    signals, score = [], 0

    if close > ma20 > ma50:
        signals.append(_signal("均线趋势", "多头偏强", "收盘价位于 MA20 和 MA50 上方，短中期趋势向上。", "positive")); score += 2
    elif close < ma20 < ma50:
        signals.append(_signal("均线趋势", "空头偏弱", "收盘价位于 MA20 和 MA50 下方，短中期趋势承压。", "negative")); score -= 2
    else:
        signals.append(_signal("均线趋势", "震荡整理", "均线尚未形成一致方向，趋势信号不明确。"))

    previous_macdh = float(previous["macdh"])
    if macdh > 0 >= previous_macdh:
        signals.append(_signal("MACD", "金叉信号", "MACD 柱由负转正，短期动能改善。", "positive")); score += 2
    elif macdh < 0 <= previous_macdh:
        signals.append(_signal("MACD", "死叉信号", "MACD 柱由正转负，短期动能转弱。", "negative")); score -= 2
    elif macd > macds and macdh > previous_macdh:
        signals.append(_signal("MACD", "多头动能增强", "DIF 位于 DEA 上方且红柱扩大。", "positive")); score += 1
    elif macd < macds and macdh < previous_macdh:
        signals.append(_signal("MACD", "空头动能增强", "DIF 位于 DEA 下方且绿柱扩大。", "negative")); score -= 1
    else:
        signals.append(_signal("MACD", "动能收敛", "MACD 柱缩短，当前方向动能减弱。"))

    candle_range = max(float(latest["high"] - latest["low"]), 0.0001)
    if abs(close - open_price) / candle_range < 0.15:
        signals.append(_signal("当日K线", "十字/小实体", "多空力量接近平衡，需等待确认。"))
    elif close > open_price:
        signals.append(_signal("当日K线", "阳线", "收盘高于开盘，日内买方占优。", "positive")); score += 1
    else:
        signals.append(_signal("当日K线", "阴线", "收盘低于开盘，日内卖方占优。", "negative")); score -= 1

    if rsi >= 70:
        signals.append(_signal("RSI(14)", "偏热", "进入超买区，追高风险上升。", "negative")); score -= 1
    elif rsi <= 30:
        signals.append(_signal("RSI(14)", "偏冷", "进入超卖区，可能出现技术性反弹。", "positive")); score += 1
    else:
        signals.append(_signal("RSI(14)", "中性", "位于常态区间，暂无极端超买或超卖。"))

    volume_tone = "positive" if close >= open_price else "negative"
    if volume_ratio >= 1.5:
        signals.append(_signal("成交量", "明显放量", f"约为近5日均量的 {volume_ratio:.2f} 倍。", volume_tone))
    elif volume_ratio <= 0.7:
        signals.append(_signal("成交量", "明显缩量", f"约为近5日均量的 {volume_ratio:.2f} 倍，参与度偏低。"))
    else:
        signals.append(_signal("成交量", "量能正常", f"约为近5日均量的 {volume_ratio:.2f} 倍。"))

    verdict = "技术面偏强" if score >= 3 else "技术面偏弱" if score <= -3 else "技术面中性"
    tone = "positive" if score >= 3 else "negative" if score <= -3 else "neutral"
    return {
        "date": str(latest["date"]), "change_20": round((close / data.iloc[-21]["close"] - 1) * 100, 2),
        "change_60": round((close / data.iloc[-61]["close"] - 1) * 100, 2),
        "ma20": round(ma20, 2), "ma50": round(ma50, 2), "ma200": round(ma200, 2),
        "rsi": round(rsi, 2), "macd": round(macd, 3), "macds": round(macds, 3),
        "macdh": round(macdh, 3), "atr_percent": round(atr / close * 100, 2),
        "boll_upper": round(float(latest["boll_ub"]), 2), "boll_middle": round(float(latest["boll"]), 2),
        "boll_lower": round(float(latest["boll_lb"]), 2), "high_60": round(float(data.tail(60)["high"].max()), 2),
        "low_60": round(float(data.tail(60)["low"].min()), 2), "verdict": verdict,
        "verdict_tone": tone, "signals": signals,
    }


def build_chart(data, code, name):
    view = data.tail(160).copy()
    view["index"] = np.arange(len(view))
    view["color"] = np.where(view["close"] >= view["open"], "#ef4444", "#16a34a")
    view["macd_color"] = np.where(view["macdh"] >= 0, "#ef4444", "#16a34a")
    source = ColumnDataSource(view)
    x_range = (-2, len(view) + 1)
    price = figure(height=340, sizing_mode="stretch_width", x_range=x_range, tools="pan,wheel_zoom,box_zoom,reset,save")
    price.title.text = f"{code} {name} 日K线与均线"
    price.segment("index", "high", "index", "low", color="color", source=source)
    price.vbar("index", 0.65, "open", "close", fill_color="color", line_color="color", source=source)
    price.line("index", "ma20", source=source, color="#2563eb", line_width=2, legend_label="MA20")
    price.line("index", "ma50", source=source, color="#f59e0b", line_width=2, legend_label="MA50")
    price.add_tools(HoverTool(tooltips=[("日期", "@date"), ("开盘", "@open{0.00}"), ("最高", "@high{0.00}"), ("最低", "@low{0.00}"), ("收盘", "@close{0.00}"), ("涨跌", "@p_change{0.00}%")]))
    price.legend.location = "top_left"
    volume = figure(height=150, sizing_mode="stretch_width", x_range=price.x_range, tools="pan,wheel_zoom,reset")
    volume.title.text = "成交量"
    volume.vbar("index", 0.65, 0, "volume", fill_color="color", line_color="color", source=source)
    macd_plot = figure(height=190, sizing_mode="stretch_width", x_range=price.x_range, tools="pan,wheel_zoom,reset")
    macd_plot.title.text = "MACD（DIF / DEA / 柱状图）"
    macd_plot.vbar("index", 0.65, 0, "macdh", fill_color="macd_color", line_color="macd_color", source=source, alpha=0.7)
    macd_plot.line("index", "macd", source=source, color="#2563eb", line_width=2, legend_label="DIF")
    macd_plot.line("index", "macds", source=source, color="#f59e0b", line_width=2, legend_label="DEA")
    macd_plot.add_layout(Span(location=0, dimension="width", line_color="#94a3b8"))
    macd_plot.legend.location = "top_left"
    ticks = list(range(0, len(view), max(len(view) // 8, 1)))
    macd_plot.xaxis.ticker = ticks
    macd_plot.xaxis.major_label_overrides = {i: str(view.iloc[i]["date"]) for i in ticks}
    price.xaxis.visible = False
    volume.xaxis.visible = False
    script, div = components(column(price, volume, macd_plot, sizing_mode="stretch_width"))
    return {"script": script, "div": div}


def analyze_stock(code):
    quote = fetch_quote(code)
    data = calculate_indicators(fetch_history(code))
    return {"quote": quote, "summary": build_summary(data), "chart": build_chart(data, code, quote["name"])}

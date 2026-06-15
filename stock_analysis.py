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

from data_sources import fetch_extra_data

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
    low_9 = data["low"].rolling(9, min_periods=1).min()
    high_9 = data["high"].rolling(9, min_periods=1).max()
    rsv = (data["close"] - low_9) / (high_9 - low_9).replace(0, np.nan) * 100
    data["kdjk"] = rsv.ewm(alpha=1 / 3, adjust=False).mean()
    data["kdjd"] = data["kdjk"].ewm(alpha=1 / 3, adjust=False).mean()
    data["kdjj"] = 3 * data["kdjk"] - 2 * data["kdjd"]
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
        "verdict_tone": tone, "signals": signals, "raw_score": score,
        "kdjk": round(float(latest["kdjk"]), 2), "kdjd": round(float(latest["kdjd"]), 2),
        "kdjj": round(float(latest["kdjj"]), 2), "volume_ratio": round(volume_ratio, 2),
    }


def _range(low, high):
    low, high = sorted((max(float(low), 0), max(float(high), 0)))
    return f"{low:.2f} - {high:.2f}"


def _metric(financials, name, unit=""):
    value = financials.get(name)
    if value is None:
        return "数据缺失"
    if unit == "亿":
        return f"{value / 100000000:.2f} 亿"
    return f"{value:.2f}{unit}"


def build_report(quote, data, summary, extra):
    latest = data.iloc[-1]
    close = float(latest["close"])
    atr = max(float(latest["atr"]), close * 0.01)
    ma20, ma50 = float(latest["ma20"]), float(latest["ma50"])
    low_20 = float(data.tail(20)["low"].min())
    low_60 = float(data.tail(60)["low"].min())
    high_20 = float(data.tail(20)["high"].max())
    high_60 = float(data.tail(60)["high"].max())
    support = max(low_60, min(low_20, ma20, float(latest["boll_lb"])))
    pressure = min(x for x in (high_20, high_60, float(latest["boll_ub"])) if x > close) if any(
        x > close for x in (high_20, high_60, float(latest["boll_ub"]))
    ) else close + 2 * atr

    technical_score = max(1.0, min(10.0, 5.5 + summary["raw_score"] * 0.75))
    valuation_score = 5.0
    valuation_notes = []
    if quote["pe"] > 0:
        valuation_score += 1.2 if quote["pe"] < 15 else 0.4 if quote["pe"] < 30 else -1.0 if quote["pe"] > 60 else 0
    if quote["pb"] > 0:
        valuation_score += 0.8 if quote["pb"] < 2 else -0.8 if quote["pb"] > 8 else 0
    valuation_score = max(1.0, min(10.0, valuation_score))
    fund_score = max(2.0, min(8.0, 5 + (quote["volume_ratio"] - 1) * 1.2 + min(quote["turnover"], 5) * 0.15))
    risk_score = max(2.0, min(8.0, 7.2 - summary["atr_percent"] * 0.65))
    profile, financials, notices = extra["profile"], extra["financials"], extra["notices"]
    fundamental_score = 4.5
    revenue_growth = financials.get("营业总收入增长率")
    profit_growth = financials.get("归属母公司净利润增长率")
    roe = financials.get("净资产收益率(ROE)")
    debt = financials.get("资产负债率")
    cash = financials.get("经营现金流量净额")
    if revenue_growth is not None:
        fundamental_score += 0.8 if revenue_growth > 10 else -0.5 if revenue_growth < 0 else 0.3
    if profit_growth is not None:
        fundamental_score += 1.0 if profit_growth > 10 else -0.8 if profit_growth < 0 else 0.3
    if roe is not None:
        fundamental_score += 0.8 if roe > 15 else -0.4 if roe < 6 else 0.2
    if debt is not None:
        fundamental_score += 0.5 if debt < 45 else -0.7 if debt > 70 else 0
    if cash is not None:
        fundamental_score += 0.4 if cash > 0 else -0.7
    fundamental_score = max(1.0, min(10.0, fundamental_score))
    industry_score = 5.2 if profile.get("所属行业") else 4.5
    scores = {
        "基本面": round(fundamental_score, 1), "行业前景": industry_score, "估值吸引力": round(valuation_score, 1),
        "技术走势": round(technical_score, 1), "资金面": round(fund_score, 1),
        "风险控制": round(risk_score, 1),
    }
    overall = round(sum(scores.values()) / len(scores), 1)
    scores["综合得分"] = overall

    if overall >= 7.8 and technical_score >= 7:
        advice = "强烈买入"
    elif overall >= 6.3 and technical_score >= 6:
        advice = "谨慎买入"
    elif overall < 4.2:
        advice = "回避"
    elif technical_score <= 3.2:
        advice = "减仓"
    else:
        advice = "观望"

    ideal_low = max(low_60, support - atr * 0.35)
    ideal_high = support + atr * 0.35
    acceptable_low = ideal_high
    acceptable_high = min(close, ma20 + atr * 0.5) if close > ideal_high else ideal_high + atr
    acceptable_high = max(acceptable_low, acceptable_high)
    chase_low = max(close + atr, pressure - atr * 0.3)
    stop = max(0, min(low_60, support - atr * 1.3))
    target_1 = max(close + atr, pressure)
    target_2 = max(high_60, target_1 + atr * 2)

    pe_text = f"{quote['pe']:.2f}" if quote["pe"] > 0 else "缺失"
    pb_text = f"{quote['pb']:.2f}" if quote["pb"] > 0 else "缺失"
    valuation_notes.append(f"当前 PE 为 {pe_text}、PB 为 {pb_text}；PS、PEG、历史估值分位及同行估值数据缺失，因此估值判断偏保守。")
    trend = "上涨" if close > ma20 > ma50 else "下跌" if close < ma20 < ma50 else "震荡"
    kd_text = "偏强" if latest["kdjk"] > latest["kdjd"] else "偏弱"
    position = "轻仓 10%-20%"
    investor = "风险承受能力一般、愿意等待技术确认的投资者"
    if advice == "谨慎买入":
        position, investor = "中仓 20%-40%，分批建仓", "能承受中等波动、严格执行止损的投资者"
    elif advice == "强烈买入":
        position, investor = "中仓 30%-50%，不建议一次性重仓", "风险承受能力较高且有纪律的投资者"
    elif advice in ("减仓", "回避"):
        position, investor = "不新开仓；已有仓位降至 0%-10%", "仅适合高风险承受能力投资者观察"

    return {
        "fundamental": [
            ("公司主营业务", profile.get("主营业务") or "数据缺失。"),
            ("收入和利润增长", f"报告期 {financials.get('period', '未知')}：营业收入 {_metric(financials, '营业总收入', '亿')}，同比 {_metric(financials, '营业总收入增长率', '%')}；归母净利润 {_metric(financials, '归母净利润', '亿')}，同比 {_metric(financials, '归属母公司净利润增长率', '%')}。"),
            ("盈利质量", f"毛利率 {_metric(financials, '毛利率', '%')}，净利率 {_metric(financials, '销售净利率', '%')}，ROE {_metric(financials, '净资产收益率(ROE)', '%')}，经营现金流 {_metric(financials, '经营现金流量净额', '亿')}。"),
            ("负债与财务风险", f"资产负债率 {_metric(financials, '资产负债率', '%')}，流动比率 {_metric(financials, '流动比率')}，速动比率 {_metric(financials, '速动比率')}。"),
            ("管理层与竞争优势", f"法人代表：{profile.get('法人代表') or '数据缺失'}。竞争优势需结合品牌、渠道、技术与公告进一步判断。"),
        ],
        "industry": [
            ("所属行业与地位", f"巨潮行业分类：{profile.get('所属行业') or '数据缺失'}；所属市场：{profile.get('所属市场') or '数据缺失'}；入选指数：{profile.get('入选指数') or '数据缺失'}。"),
            ("行业景气度与空间", "当前未接入行业增速和同行横向财务数据，行业景气度仍按中性偏谨慎处理。"),
            ("政策与竞争格局", "已接入巨潮公告用于追踪政策及公司事件，但主要竞争对手与市场份额仍需进一步核验。"),
        ],
        "valuation": valuation_notes,
        "technical": [
            ("当前趋势", f"{trend}；现价 {close:.2f}，MA20 为 {ma20:.2f}，MA50 为 {ma50:.2f}。"),
            ("关键支撑位", f"{support:.2f}，依据近20/60日低点、MA20与布林下轨综合计算。"),
            ("关键压力位", f"{pressure:.2f}，依据近20/60日高点与布林上轨综合计算。"),
            ("成交量", f"最新量能约为近5日均量的 {summary['volume_ratio']:.2f} 倍。"),
            ("MACD / RSI / KDJ", f"MACD柱 {summary['macdh']:.3f}，RSI {summary['rsi']:.2f}，KDJ 为 {kd_text}（K {summary['kdjk']:.2f} / D {summary['kdjd']:.2f} / J {summary['kdjj']:.2f}）。"),
        ],
        "funds": [
            ("主力与机构", "主力资金流向、机构持仓变化数据缺失，不将短期上涨直接视为机构买入。"),
            ("市场关注度", f"换手率 {quote['turnover']:.2f}%，量比 {quote['volume_ratio']:.2f}，以此作为有限的市场热度参考。"),
            ("公告与炒作风险", f"巨潮资讯近期开示公告 {len(notices)} 条；高换手或量比显著升高时仍需警惕短期炒作。"),
        ],
        "risks": [
            "财务摘要来自 AKShare，需以公司正式定期报告为准，仍存在业绩不及预期风险。",
            "行业增速、市场份额及竞争对手数据尚未完整接入，行业周期与政策风险无法充分量化。",
            f"ATR 波动率约 {summary['atr_percent']:.2f}%，价格跌破 {stop:.2f} 时技术结构将明显恶化。",
            "估值历史分位、机构持仓和完整新闻情绪仍缺失，存在估值回落、流动性及黑天鹅风险。",
        ],
        "profile": profile, "financials": financials, "notices": notices,
        "data_errors": extra["errors"], "sources": extra["sources"],
        "scores": scores, "advice": advice,
        "prices": {
            "理想买入区间": _range(ideal_low, ideal_high),
            "可接受买入区间": _range(acceptable_low, acceptable_high),
            "不建议追高区间": f"{chase_low:.2f} 以上",
            "止损位": f"{stop:.2f}", "第一目标价": f"{target_1:.2f}", "第二目标价": f"{target_2:.2f}",
        },
        "position": position, "investor": investor,
        "one_line": f"当前建议为“{advice}”；优先在 {_range(ideal_low, ideal_high)} 分批考虑，建议{position}。",
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
    summary = build_summary(data)
    extra = fetch_extra_data(code)
    return {
        "quote": quote, "summary": summary, "report": build_report(quote, data, summary, extra),
        "chart": build_chart(data, code, quote["name"]),
    }

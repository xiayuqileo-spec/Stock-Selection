#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import datetime

import akshare as ak
import pandas as pd
import requests


CNINFO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "http://www.cninfo.com.cn/",
}


def _safe_value(value):
    if pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def fetch_profile(code):
    frame = ak.stock_profile_cninfo(symbol=code)
    return frame.iloc[0].to_dict() if frame is not None and not frame.empty else {}


def fetch_financials(code):
    frame = ak.stock_financial_abstract(symbol=code)
    if frame is None or frame.empty:
        return {}
    periods = sorted([str(x) for x in frame.columns if str(x).isdigit()], reverse=True)
    latest = periods[0]
    previous_year = str(int(latest[:4]) - 1) + latest[4:]
    previous = previous_year if previous_year in periods else periods[1]
    metrics = [
        "营业总收入", "归母净利润", "营业总收入增长率", "归属母公司净利润增长率",
        "毛利率", "销售净利率", "净资产收益率(ROE)", "经营现金流量净额",
        "资产负债率", "流动比率", "速动比率",
    ]
    result = {"period": latest, "compare_period": previous}
    for metric in metrics:
        rows = frame.loc[frame["指标"] == metric]
        if rows.empty:
            continue
        row = rows.iloc[-1]
        result[metric] = _safe_value(row.get(latest))
        result[f"{metric}_上期"] = _safe_value(row.get(previous))
    return result


def fetch_cninfo_notices(code, limit=8):
    search = requests.post(
        "http://www.cninfo.com.cn/new/information/topSearch/query",
        data={"keyWord": code, "maxSecNum": "10", "maxListNum": "5"},
        headers=CNINFO_HEADERS, timeout=12,
    )
    search.raise_for_status()
    securities = search.json()
    security = next((item for item in securities if item.get("code") == code), None)
    if not security:
        return []
    market = "sh" if code.startswith(("5", "6", "9")) else "sz"
    column = "sse" if market == "sh" else "szse"
    today = datetime.date.today()
    start = today - datetime.timedelta(days=550)
    response = requests.post(
        "http://www.cninfo.com.cn/new/hisAnnouncement/query",
        data={
            "pageNum": "1", "pageSize": str(limit), "column": column, "tabName": "fulltext",
            "stock": f"{code},{security['orgId']}", "searchkey": "", "secid": "",
            "plate": market, "category": "", "trade": "",
            "seDate": f"{start:%Y-%m-%d}~{today:%Y-%m-%d}", "sortName": "", "sortType": "",
            "isHLtitle": "true",
        },
        headers=CNINFO_HEADERS, timeout=15,
    )
    response.raise_for_status()
    notices = []
    for item in response.json().get("announcements") or []:
        notices.append({
            "title": item.get("announcementTitle", ""),
            "date": datetime.datetime.fromtimestamp(item["announcementTime"] / 1000).strftime("%Y-%m-%d"),
            "url": "http://static.cninfo.com.cn/" + item.get("adjunctUrl", ""),
        })
    return notices


def fetch_extra_data(code):
    result = {"profile": {}, "financials": {}, "notices": [], "errors": [], "sources": ["AKShare", "巨潮资讯"]}
    for label, func, key in [
        ("AKShare/巨潮公司资料", fetch_profile, "profile"),
        ("AKShare财务摘要", fetch_financials, "financials"),
        ("巨潮资讯公告", fetch_cninfo_notices, "notices"),
    ]:
        try:
            result[key] = func(code)
        except Exception as exc:
            result["errors"].append(f"{label}获取失败：{exc}")
    return result

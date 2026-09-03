#!/usr/bin/env python3
"""Fetch latest 0050 + BTC prices and rebuild data.json."""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "data.json"
UA = {"User-Agent": "Mozilla/5.0 drawdown-panel/1.0"}
SPLIT = pd.Timestamp("2025-06-18")
TW = timezone(timedelta(hours=8))


def get(url, params=None, retries=4):
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=40)
            if r.status_code == 200:
                return r
            last = RuntimeError(f"{r.status_code} {url}")
        except Exception as e:
            last = e
        time.sleep(1.2 * (i + 1))
    raise last


def load_0050() -> pd.DataFrame:
    p = DATA / "0050.csv"
    df = pd.read_csv(p)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def append_0050(df: pd.DataFrame) -> pd.DataFrame:
    last = df["date"].max()
    start = (last + pd.Timedelta(days=1)).date()
    today = datetime.now(TW).date()
    if start > today:
        return df
    frames = [df]
    cur = start.replace(day=1)
    while cur <= today:
        date_str = f"{cur.year}{cur.month:02d}01"
        url = (
            "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
            f"?date={date_str}&stockNo=0050&response=json"
        )
        try:
            j = get(url).json()
        except Exception as e:
            print("TWSE skip", date_str, e)
            if cur.month == 12:
                cur = cur.replace(year=cur.year + 1, month=1)
            else:
                cur = cur.replace(month=cur.month + 1)
            time.sleep(0.6)
            continue
        rows = []
        for item in j.get("data") or []:
            ds = item[0].replace("/", "-")
            parts = ds.split("-")
            if len(parts[0]) == 3:  # 民國年
                ds = f"{int(parts[0])+1911}-{parts[1]}-{parts[2]}"
            dt = pd.Timestamp(ds)
            if dt <= last:
                continue
            def n(x):
                return float(str(x).replace(",", ""))
            rows.append(
                {
                    "date": dt,
                    "stock_id": "0050",
                    "Trading_Volume": n(item[1]) if item[1] not in ("--", "") else 0,
                    "Trading_money": n(item[2]) if item[2] not in ("--", "") else 0,
                    "open": n(item[3]),
                    "max": n(item[4]),
                    "min": n(item[5]),
                    "close": n(item[6]),
                    "spread": item[7],
                    "Trading_turnover": n(item[8]) if item[8] not in ("--", "") else 0,
                }
            )
        if rows:
            frames.append(pd.DataFrame(rows))
            print("0050 added", rows[0]["date"].date(), "->", rows[-1]["date"].date(), len(rows))
        if cur.month == 12:
            cur = cur.replace(year=cur.year + 1, month=1)
        else:
            cur = cur.replace(month=cur.month + 1)
        time.sleep(0.5)
    out = pd.concat(frames, ignore_index=True)
    out = out.drop_duplicates("date").sort_values("date").reset_index(drop=True)
    out.to_csv(DATA / "0050.csv", index=False)
    return out


def load_btc() -> pd.DataFrame:
    p = DATA / "btc.csv"
    df = pd.read_csv(p)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def append_btc(df: pd.DataFrame) -> pd.DataFrame:
    last = df["date"].max()
    p1 = int((last - pd.Timedelta(days=3)).timestamp())
    p2 = int(datetime.now(timezone.utc).timestamp()) + 86400
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/BTC-USD"
        f"?period1={p1}&period2={p2}&interval=1d&events=div%2Csplit"
    )
    j = get(url).json()
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    close = res["indicators"]["quote"][0]["close"]
    rows = []
    for t, c in zip(ts, close):
        if c is None:
            continue
        dt = pd.to_datetime(t, unit="s").normalize()
        rows.append({"date": dt, "close": float(c)})
    add = pd.DataFrame(rows)
    out = pd.concat([df, add], ignore_index=True)
    out = out.drop_duplicates("date").sort_values("date").reset_index(drop=True)
    print("BTC last", out["date"].max().date(), float(out["close"].iloc[-1]))
    out.to_csv(DATA / "btc.csv", index=False)
    return out


def analyze(df: pd.DataFrame, thresholds, asset_id, currency):
    df = df.sort_values("date").reset_index(drop=True)
    if asset_id == "0050":
        px = df["close"].astype(float).to_numpy().copy()
        dates = pd.to_datetime(df["date"])
        px[dates < SPLIT] = px[dates < SPLIT] / 4.0
    else:
        px = df["close"].astype(float).to_numpy()
        dates = pd.to_datetime(df["date"])
    n = len(px)
    ath = np.maximum.accumulate(px)
    dd = px / ath - 1.0
    date_vals = dates.values
    ths = list(thresholds)

    def fwd(i, days):
        target = dates.iloc[i] + pd.Timedelta(days=days)
        j = int(np.searchsorted(date_vals, np.datetime64(target)))
        if j >= n:
            return None, None, None
        return (
            dates.iloc[j].strftime("%Y-%m-%d"),
            round(float(px[j]), 2),
            round(float(px[j] / px[i] - 1) * 100, 1),
        )

    def days_until(i, target_px):
        for j in range(i + 1, n):
            if px[j] >= target_px - 1e-9:
                return int((dates.iloc[j] - dates.iloc[i]).days), dates.iloc[j].strftime("%Y-%m-%d")
        return None, None

    horizons = [("1m", 30), ("3m", 91), ("6m", 182), ("9m", 273), ("1y", 365), ("3y", 365 * 3)]
    buys = {str(t): [] for t in ths}
    cycle_peak_i = 0
    hit = {t: False for t in ths}
    for i in range(n):
        if px[i] > px[cycle_peak_i] + 1e-12 and abs(px[i] - ath[i]) < 1e-9:
            cycle_peak_i = i
            hit = {t: False for t in ths}
            continue
        for t in ths:
            if (not hit[t]) and dd[i] <= -t / 100.0:
                hit[t] = True
                buy = px[i]
                extra = buy
                extra_j = i
                for j in range(i, n):
                    if px[j] < extra:
                        extra = px[j]
                        extra_j = j
                    if j > i and px[j] >= buy - 1e-9:
                        break
                d_cost, dt_cost = days_until(i, buy)
                d_ath, dt_ath = days_until(i, px[cycle_peak_i])
                e = {
                    "th": t,
                    "peak_date": dates.iloc[cycle_peak_i].strftime("%Y-%m-%d"),
                    "peak_px": round(float(px[cycle_peak_i]), 2),
                    "buy_date": dates.iloc[i].strftime("%Y-%m-%d"),
                    "buy_px": round(float(buy), 2),
                    "dd_at_buy": round(float(dd[i]) * 100, 1),
                    "trough_date": dates.iloc[extra_j].strftime("%Y-%m-%d"),
                    "trough_px": round(float(extra), 2),
                    "extra_dd": round(float(extra / buy - 1) * 100, 1),
                    "cost_date": dt_cost,
                    "cost_days": d_cost,
                    "ath_date": dt_ath,
                    "ath_days": d_ath,
                    "fwd": {},
                }
                for name, days in horizons:
                    dt, p, r = fwd(i, days)
                    e["fwd"][name] = {"date": dt, "px": p, "ret": r}
                e["ret_1y"] = e["fwd"]["1y"]["ret"]
                e["ret_3y"] = e["fwd"]["3y"]["ret"]
                buys[str(t)].append(e)

    def daily_stats(th):
        mask = dd <= -th / 100.0
        idxs = np.where(mask)[0]
        cost_days, r1s, r3s = [], [], []
        for i in idxs:
            d, _ = days_until(i, px[i])
            if d is not None:
                cost_days.append(d)
            r1 = fwd(i, 365)[2]
            r3 = fwd(i, 365 * 3)[2]
            if r1 is not None:
                r1s.append(r1 / 100)
            if r3 is not None:
                r3s.append(r3 / 100)
        def pack(arr, pct=False):
            if not arr:
                return None
            a = np.array(arr, dtype=float)
            k = 100 if pct else 1
            return {
                "n": int(len(a)),
                "mean": round(float(a.mean()) * k, 1),
                "median": round(float(np.median(a)) * k, 1),
                "win": round(float((a > 0).mean()) * 100, 1) if pct else None,
                "min": round(float(a.min()) * k, 1),
            }
        return {
            "samples": int(mask.sum()),
            "cost": pack(cost_days),
            "ret1": pack(r1s, True),
            "ret3": pack(r3s, True),
        }

    stats = {str(t): daily_stats(t) for t in ths}
    daily = [{"d": d.strftime("%Y-%m-%d"), "p": round(float(p), 2)} for d, p in zip(dates, px)]
    w = pd.Series(px, index=dates).resample("W-FRI").last().dropna()
    weekly = [{"d": i.strftime("%Y-%m-%d"), "p": round(float(v), 2)} for i, v in w.items()]
    print(asset_id, "n", n, "last", float(px[-1]), "asof", dates.iloc[-1].date())
    return {
        "id": asset_id,
        "asof": dates.iloc[-1].strftime("%Y-%m-%d"),
        "last": round(float(px[-1]), 2),
        "ath": round(float(ath[-1]), 2),
        "dd_now": round(float(dd[-1]) * 100, 2),
        "thresholds": ths,
        "series": daily,
        "weekly": weekly,
        "buys": buys,
        "stats": stats,
        "currency": currency,
        "start": dates.iloc[0].strftime("%Y-%m-%d"),
        "updated": datetime.now(TW).strftime("%Y-%m-%d %H:%M"),
    }


def main():
    DATA.mkdir(exist_ok=True)
    a50 = analyze(append_0050(load_0050()), [10, 20, 30], "0050", "TWD")
    btc = analyze(append_btc(load_btc()), [30, 40, 50], "BTC", "USD")
    payload = {"assets": {"0050": a50, "BTC": btc}}
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("wrote", OUT, OUT.stat().st_size)


if __name__ == "__main__":
    main()

"""台股 TOP50 網頁版的資料核心。無 GUI、無使用者私密憑證。

市值＝普通股發行股數×股價。盤中以最近全市場正式收盤前 200 名
作為候選池，並非即時掃描全市場。資料來源有延遲/可能限流。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
from threading import Lock
from typing import Any
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPSHandler, HTTPCookieProcessor
from urllib.error import URLError
import http.client
import http.cookiejar
import csv
import io
import json
import re
import ssl
import time

TW = timezone(timedelta(hours=8))
LISTED_QUOTE_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
LISTED_SHARES_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
OTC_QUOTE_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
OTC_SHARES_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"
OTC_SHARES_FALLBACK = "https://mopsfin.twse.com.tw/opendata/t187ap03_O.csv"
MIS_ROOT = "https://mis.twse.com.tw/stock/index.jsp"
MIS_QUOTES = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
OFFICIAL_HOSTS = frozenset({"openapi.twse.com.tw", "www.tpex.org.tw", "mis.twse.com.tw", "mopsfin.twse.com.tw"})
BILLION = Decimal("100000000")
MA_WINDOWS = (60, 120, 240)
TOP = 50
CANDIDATES = 200


class SafeCompatibilityHTTPS(HTTPSHandler):
    """遇到 Missing Subject Key Identifier 時只放寬 X509_STRICT，不停用 SSL 驗證。"""
    def __init__(self):
        super().__init__(context=ssl.create_default_context())
        self.compat = ssl.create_default_context()
        if hasattr(ssl, "VERIFY_X509_STRICT"):
            self.compat.verify_flags &= ~ssl.VERIFY_X509_STRICT

    def https_open(self, req):
        try:
            return super().https_open(req)
        except URLError as exc:
            reason = getattr(exc, "reason", None)
            host = urlsplit(req.full_url).hostname
            if (host in OFFICIAL_HOSTS
                    and isinstance(reason, ssl.SSLCertVerificationError)
                    and "Missing Subject Key Identifier" in str(reason)
                    and hasattr(ssl, "VERIFY_X509_STRICT")):
                return self.do_open(http.client.HTTPSConnection, req, context=self.compat)
            raise


def opener(cookie=False):
    items = [SafeCompatibilityHTTPS()]
    if cookie:
        items.append(HTTPCookieProcessor(http.cookiejar.CookieJar()))
    return build_opener(*items)


def now_tw():
    return datetime.now(TW)


def is_session(at):
    return at.weekday() < 5 and (9, 0) <= (at.hour, at.minute) < (13, 30)


def is_after_close(at):
    return at.weekday() < 5 and (at.hour, at.minute) >= (13, 30)


def numeric(value) -> Decimal | None:
    if value is None:
        return None
    s = str(value).strip().replace(",", "").replace("，", "")
    if s in {"", "-", "--", "---", "N/A", "null", "－", "None"}:
        return None
    try:
        val = Decimal(s)
        return val if val.is_finite() else None
    except (ValueError, InvalidOperation):
        return None


def parse_date(value) -> date:
    s = re.sub(r"\D", "", str(value or ""))
    if len(s) == 7:
        return date(int(s[:3]) + 1911, int(s[3:5]), int(s[5:7]))
    if len(s) == 8:
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    raise ValueError(f"無法辨識行情日期：{value}")


def dominant_date(quotes: list[dict]) -> date:
    counts = {}
    for row in quotes[:400]:
        try:
            d = parse_date(row.get("Date"))
            counts[d] = counts.get(d, 0) + 1
        except (TypeError, ValueError):
            pass
    if not counts:
        raise ValueError("官方收盤行情缺少 Date 日期欄")
    return max(counts, key=counts.get)


def stock_code(code) -> bool:
    s = str(code).strip()
    return len(s) == 4 and s.isascii() and s.isdigit() and not s.startswith(("0", "91"))


def get_json(url: str, *, agent=None, timeout=19):
    client = agent or opener()
    referer = ("https://finance.yahoo.com/" if "finance.yahoo.com" in url else
               "https://www.tpex.org.tw/" if "tpex" in url else "https://www.twse.com.tw/")
    hdr = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
           "Accept": "application/json, */*", "Referer": referer}
    with client.open(Request(url, headers=hdr), timeout=timeout) as rsp:
        return json.load(rsp)


def get_list(url, *, agent=None):
    result = get_json(url, agent=agent, timeout=30)
    if not isinstance(result, list) or not result or not isinstance(result[0], dict):
        raise ValueError(f"官方回傳非股票資料陣列：{url}")
    return result


def get_otc_shares(agent):
    try:
        return get_list(OTC_SHARES_URL, agent=agent)
    except Exception as original_error:
        try:
            req = Request(OTC_SHARES_FALLBACK,
                          headers={"User-Agent": "Mozilla/5.0", "Accept": "text/csv,*/*"})
            with agent.open(req, timeout=30) as rsp:
                raw = rsp.read().decode("utf-8-sig")
            rows = list(csv.DictReader(io.StringIO(raw)))
            if not rows:
                raise ValueError("上櫃普通股股數 CSV 空白")
            return rows
        except Exception as fb_error:
            raise RuntimeError(f"上櫃公司基本資料無法讀取：{original_error}; 備援：{fb_error}") from fb_error


def company_shares(rec):
    for col in ("已發行普通股數或TDR原股發行股數", "已發行普通股數或TDR原發行股數",
                "已發行普通股數", "IssueShares"):
        n = numeric(rec.get(col))
        if n is not None and n > 0:
            return n
    return None


def build_universe(listed, listed_info, otc, otc_info):
    d1, d2 = dominant_date(listed), dominant_date(otc)
    info = {"上市": {}, "上櫃": {}}
    for market, rows in (("上市", listed_info), ("上櫃", otc_info)):
        for r in rows:
            code = str(r.get("公司代號") or r.get("SecuritiesCompanyCode") or "").strip()
            shares = company_shares(r)
            if stock_code(code) and shares:
                name = str(r.get("公司簡稱") or r.get("CompanyAbbreviation") or
                           r.get("公司名稱") or r.get("CompanyName") or code).strip()
                info[market][code] = (shares, name)
    if len(info["上市"]) < 500 or len(info["上櫃"]) < 300:
        raise ValueError(f"發行股數資料不足：上市 {len(info['上市'])} / 上櫃 {len(info['上櫃'])}")
    output = []
    for market, rows, code_col, price_col, trade_day in (
            ("上市", listed, "Code", "ClosingPrice", d1),
            ("上櫃", otc, "SecuritiesCompanyCode", "Close", d2)):
        for r in rows:
            code = str(r.get(code_col, "")).strip()
            if not stock_code(code) or code not in info[market]:
                continue
            price = numeric(r.get(price_col))
            if price is None or price <= 0:
                continue
            shares, name = info[market][code]
            diff = numeric(str(r.get("Change", "")).replace("＋", "+").replace("－", "-"))
            prev = price - diff if diff is not None and price - diff > 0 else None
            output.append({"code": code, "name": name, "market": market,
                           "shares": shares, "price": price, "prev_close": prev,
                           "quote_day": trade_day, "quote_time": "13:30", "source": "官方收盤價"})
    if len(output) < 700:
        raise ValueError(f"有效股票僅 {len(output)} 檔，不能建立可靠排行")
    output.sort(key=lambda x: x["shares"] * x["price"], reverse=True)
    return {"records": output, "listed_date": d1, "otc_date": d2,
            "synchronized": d1 == d2, "retrieved": now_tw()}


def fetch_official():
    agent = opener()
    lq = get_list(LISTED_QUOTE_URL, agent=agent)
    li = get_list(LISTED_SHARES_URL, agent=agent)
    oq = get_list(OTC_QUOTE_URL, agent=agent)
    oi = get_otc_shares(agent)
    return build_universe(lq, li, oq, oi)


def limit_tick(price):
    if price < 10: return Decimal("0.01")
    if price < 50: return Decimal("0.05")
    if price < 100: return Decimal("0.1")
    if price < 500: return Decimal("0.5")
    if price < 1000: return Decimal("1")
    return Decimal("5")


def limit_estimate(prev):
    if not prev or prev <= 0:
        return None, None
    raw_up, raw_down = prev * Decimal("1.10"), prev * Decimal("0.90")
    up = (raw_up / limit_tick(raw_up)).to_integral_value(rounding=ROUND_FLOOR) * limit_tick(raw_up)
    down = (raw_down / limit_tick(raw_down)).to_integral_value(rounding=ROUND_CEILING) * limit_tick(raw_down)
    return up, down


def market_limits(row):
    price = row["price"]
    up, down = row.get("limit_up"), row.get("limit_down")
    confirmed = bool(up and down and row.get("limit_day") == row["quote_day"])
    if not confirmed:
        up, down = limit_estimate(row.get("prev_close"))
    if up is not None and price == up:
        return "▲ 漲停" if confirmed else "▲ 推估漲停", up, down
    if down is not None and price == down:
        return "▼ 跌停" if confirmed else "▼ 推估跌停", up, down
    return "", up, down


class MisClient:
    def __init__(self):
        self.agent = opener(cookie=True)
        self.primed = False

    def warmup(self):
        if self.primed: return
        self.primed = True
        try:
            req = Request(MIS_ROOT, headers={"User-Agent": "Mozilla/5.0"})
            with self.agent.open(req, timeout=8) as rsp:
                rsp.read(128)
        except Exception:
            pass

    def fetch(self, candidates):
        self.warmup()
        msgs = []
        for i in range(0, len(candidates), 50):
            group = candidates[i:i+50]
            symbols = "|".join(("tse" if r["market"] == "上市" else "otc") + "_" + r["code"] + ".tw" for r in group)
            query = urlencode({"ex_ch": symbols, "json": 1, "delay": 0, "_": int(time.time()*1000)})
            request = Request(MIS_QUOTES + "?" + query,
                              headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json",
                                       "Referer": MIS_ROOT})
            with self.agent.open(request, timeout=13) as rsp:
                data = json.load(rsp)
            if not isinstance(data, dict) or not isinstance(data.get("msgArray"), list):
                raise ValueError("MIS 即時行情回傳格式不正確")
            msgs.extend(data["msgArray"])
            if i + 50 < len(candidates):
                time.sleep(0.25)
        return msgs


def apply_mis(candidates, messages, at):
    msg = {(str(r.get("ex", "")).lower(), str(r.get("c", ""))): r
           for r in messages if isinstance(r, dict)}
    output = []
    fresh = 0
    for src in candidates:
        row = dict(src)
        key = ("tse" if src["market"] == "上市" else "otc", src["code"])
        raw = msg.get(key)
        if raw:
            try:
                day = parse_date(raw.get("d"))
            except ValueError:
                day = None
            if day and day >= src["quote_day"] and day <= at.date():
                p = numeric(raw.get("z")) or numeric(raw.get("pz"))
                y = numeric(raw.get("y"))
                if y is not None and y > 0:
                    row["prev_close"] = y
                up, down = numeric(raw.get("u")), numeric(raw.get("w"))
                if up and down and 0 < down < up:
                    row.update(limit_up=up, limit_down=down, limit_day=day)
                if p is not None and p > 0:
                    row.update(price=p, quote_day=day,
                               quote_time=str(raw.get("t") or "--:--"),
                               source="今日最新成交" if day == at.date() else "前次成交參考")
                    if day == at.date():
                        fresh += 1
                elif day == at.date() and y and y > 0:
                    row.update(price=y, quote_day=day,
                               quote_time=str(raw.get("t") or "--:--"),
                               source="今日未成交（昨收參考）")
        output.append(row)
    output.sort(key=lambda x: x["shares"] * x["price"], reverse=True)
    return output, fresh


def parse_history(payload):
    ch = payload.get("chart") if isinstance(payload, dict) else None
    if not isinstance(ch, dict) or ch.get("error"):
        raise ValueError("歷史股價來源異常")
    items = ch.get("result")
    if not isinstance(items, list) or not items:
        raise ValueError("歷史股價結果為空")
    record = items[0]
    stamps = record.get("timestamp") or []
    quotes = (record.get("indicators") or {}).get("quote") or []
    if not quotes:
        raise ValueError("歷史日K缺少收盤價")
    closes = quotes[0].get("close") or []
    history = {}
    for stamp, val in zip(stamps, closes):
        n = numeric(val)
        if n is None or n <= 0: continue
        try:
            dt = datetime.fromtimestamp(int(stamp), TW).date()
        except (TypeError, ValueError, OSError, OverflowError):
            continue
        history[dt] = n
    if len(history) < 60:
        raise ValueError(f"歷史股價不足：{len(history)} 個交易日")
    return history


def fetch_history(symbol):
    errors = []
    for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
        url = f"https://{host}/v8/finance/chart/{quote(symbol)}?interval=1d&range=2y"
        try:
            return parse_history(get_json(url, timeout=12))
        except Exception as exc:
            errors.append(f"{host}: {str(exc)[:85]}")
    raise RuntimeError("；".join(errors))


def symbol_for(row):
    return f"{row['code']}.TW" if row["market"] == "上市" else f"{row['code']}.TWO"


class HistoryStore:
    """背景拉歷史股價，前端每 15 秒更新時不阻塞、也不反覆下載。"""
    def __init__(self):
        self.lock = Lock()
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="dailyclose")
        self.results: dict[str, tuple[dict, float]] = {}
        self.pending: dict[str, Any] = {}
        self.errors: dict[str, tuple[str, float]] = {}

    def schedule(self, records):
        current = time.time()
        with self.lock:
            for row in records:
                key = symbol_for(row)
                good = self.results.get(key)
                if good and current - good[1] < 18*3600:
                    continue
                err = self.errors.get(key)
                if err and current - err[1] < 3600:
                    continue
                if key not in self.pending:
                    self.pending[key] = self.executor.submit(fetch_history, key)

    def get(self, key):
        with self.lock:
            fut = self.pending.get(key)
            if fut and fut.done():
                self.pending.pop(key)
                try:
                    self.results[key] = (fut.result(), time.time())
                    self.errors.pop(key, None)
                except Exception as exc:
                    self.errors[key] = (str(exc)[:140], time.time())
            cached = self.results.get(key)
            if cached:
                return cached[0], "歷史日K"
            if key in self.errors:
                return None, "無法取得歷史日K"
            return None, "歷史日K讀取中"


def moving_averages(row, history):
    if not history:
        return {n: None for n in MA_WINDOWS}
    day = row["quote_day"]
    prior = sorted((d for d in history if d < day), reverse=True)
    if not prior or (day - prior[0]).days > 21:
        return {n: None for n in MA_WINDOWS}
    prices = [row["price"]] + [history[d] for d in prior[:239]]
    return {n: (sum(prices[:n], Decimal(0)) / n if len(prices) >= n else None)
            for n in MA_WINDOWS}


def ma_alert(row, ma):
    price = row["price"]
    half = price <= ma[120] if ma.get(120) is not None else None
    year = price <= ma[240] if ma.get(240) is not None else None
    if half and year: return "‼ ≤半年＋年線", half, year
    if year: return "⚠ ≤年線", half, year
    if half: return "⚠ ≤半年線", half, year
    if half is None or year is None: return "均線未齊", half, year
    return "", half, year


def enrich(rows, store):
    output = []
    store.schedule(rows[:TOP])
    for rank, src in enumerate(rows[:TOP], 1):
        row = dict(src)
        hist, hist_status = store.get(symbol_for(row))
        ma = moving_averages(row, hist)
        alert, half, year = ma_alert(row, ma)
        limit, up, down = market_limits(row)
        prev = row.get("prev_close")
        delta = row["price"] - prev if prev else None
        pct = (delta / prev * 100) if prev else None
        row.update(rank=rank, ma60=ma[60], ma120=ma[120], ma240=ma[240],
                   half_alert=half, year_alert=year, ma_alert=alert, ma_state=hist_status,
                   limit=limit, up_price=up, down_price=down,
                   delta=delta, pct=pct, cap=row["shares"]*row["price"]/BILLION)
        output.append(row)
    return output


def dec_str(val, digits=2):
    return f"{val:,.{digits}f}" if val is not None else "—"


def csv_bytes(rows, asof):
    f = io.StringIO()
    writer = csv.writer(f)
    writer.writerow(["報表產生時間(台灣)", "排名", "股票代號", "公司名稱", "市場", "資料交易日", "報價時間", "股價", "漲跌元", "漲跌幅%",
                     "市值億元", "漲跌停", "漲停價", "跌停價", "季線60日", "半年線120日", "年線240日", "均線警示", "股價≤半年線", "股價≤年線", "均線來源狀態", "價格來源"])
    def yn(x): return "是" if x is True else "否" if x is False else "無資料"
    for r in rows:
        writer.writerow([asof.strftime("%Y-%m-%d %H:%M:%S"), r["rank"], r["code"], r["name"], r["market"],
                         str(r["quote_day"]), r["quote_time"], r["price"], r["delta"] if r["delta"] is not None else "",
                         dec_str(r["pct"]) if r["pct"] is not None else "", dec_str(r["cap"]), r["limit"],
                         r["up_price"] or "", r["down_price"] or "", r["ma60"] or "", r["ma120"] or "", r["ma240"] or "",
                         r["ma_alert"], yn(r["half_alert"]), yn(r["year_alert"]), r["ma_state"], r["source"]])
    return ("\ufeff"+f.getvalue()).encode("utf-8")

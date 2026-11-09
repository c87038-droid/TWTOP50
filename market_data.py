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

from dated_official import fetch_latest_dated_twse, fetch_latest_dated_tpex, fetch_latest_dated_index

TW = timezone(timedelta(hours=8))
LISTED_QUOTE_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
LISTED_SHARES_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
OTC_QUOTE_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
LISTED_PE_URL = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"
OTC_PE_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis"
OTC_SHARES_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"
OTC_SHARES_FALLBACK = "https://mopsfin.twse.com.tw/opendata/t187ap03_O.csv"
INDEX_CLOSE_URL = "https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX"
INDEX_INTRADAY_URL = "https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_INDEX?response=json"
MIS_ROOT = "https://mis.twse.com.tw/stock/index.jsp"
MIS_QUOTES = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
OFFICIAL_HOSTS = frozenset({"openapi.twse.com.tw", "www.tpex.org.tw", "mis.twse.com.tw", "mopsfin.twse.com.tw", "www.twse.com.tw"})
BILLION = Decimal("100000000")
MA_WINDOWS = (5, 20, 60, 120, 240)
TOP = 50
DATA_BUILD = "20261109-R19-DATED-CLOSE"
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


def _quote_hhmm(raw):
    """Only genuine HH:MM[:SS] trade timestamps qualify for age calculations."""
    m = re.fullmatch(r"\s*([01]?\d|2[0-3]):([0-5]\d)(?::([0-5]\d))?\s*", str(raw or ""))
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)


def quote_quality(stock, at):
    """Return (label, age_minutes, current_with_timestamp, within_20_minutes).

    Official daily files are NOT intraday quote timestamps, including when a
    synthetic 13:30 was stored by older versions. Never imply that a screen
    refresh is a trade. Carrying a prior tick retains its true age.
    """
    day = stock.get("quote_day") or stock.get("day")
    source = str(stock.get("source", ""))
    clock = _quote_hhmm(stock.get("quote_time") or stock.get("time"))
    if not isinstance(day, date) or day > at.date():
        return "日期未確認／資料異常", None, False, False
    if "未成交" in source or "昨收" in source:
        return "未成交／昨收參考（非最新成交）", None, False, False
    official = ("官方收盤" in source or "證交所正式收盤" in source or
                "收盤（日資料）" in source)
    if official:
        if day == at.date() and not (at.weekday()<5 and (at.hour,at.minute)<(13,30)):
            return "當日正式收盤", None, False, False
        if day == at.date():
            return "日資料日期異常，待核對", None, False, False
        return "歷史正式收盤（非今日股價）", None, False, False
    if day < at.date():
        return "歷史參考價（非今日股價）", None, False, False
    if not clock:
        return "當日日期可核對／成交時間未確認", None, False, False
    hh,mm,ss=clock
    moment=at.replace(hour=hh,minute=mm,second=ss,microsecond=0)
    lag=(at-moment).total_seconds()/60
    if lag < -2:
        return "報價時間晚於目前時間，待核對", None, False, False
    lag=max(0,lag)
    if any(x in source for x in ("沿用", "上次成交", "連線失敗")):
        label="沿用先前成交"
    elif "備援" in source:
        label="免費備援報價"
    elif "MIS" in source or "今日最新成交" in source:
        label="免費盤中成交"
    else:
        label="當日成交參考"
    age=int(lag)
    suffix=f"{label}／約{age}分鐘前"
    if lag>20:
        suffix="⚠ 延遲超過20分鐘／"+suffix
    elif lag>5:
        suffix="延遲行情／"+suffix
    return suffix, age, True, lag<=20


def index_quality(index, at):
    if not index:
        return "無可驗證大盤資訊",None,False,False
    shaped={"quote_day":index.get("day"),"quote_time":index.get("time"),"source":index.get("source","")}
    return quote_quality(shaped,at)


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
                           "quote_day": trade_day, "quote_time": "收盤（日資料）", "source": "官方收盤價"})
    if len(output) < 700:
        raise ValueError(f"有效股票僅 {len(output)} 檔，不能建立可靠排行")
    output.sort(key=lambda x: x["shares"] * x["price"], reverse=True)
    return {"records": output, "listed_date": d1, "otc_date": d2,
            "synchronized": d1 == d2, "retrieved": now_tw()}


def fetch_official():
    """指定日期官方盤後資料優先；過期 OpenAPI 只能當作有日期標示的備援。"""
    agent = opener()
    li = get_list(LISTED_SHARES_URL, agent=agent)
    oi = get_otc_shares(agent)
    errors = []
    try:
        d1, lq = fetch_latest_dated_twse(lambda url: get_json(url, agent=agent, timeout=15), now_tw().date(), 5)
    except Exception as exc:
        errors.append('上市指定日期查詢失敗：' + str(exc)[:135])
        lq = get_list(LISTED_QUOTE_URL, agent=agent)
    try:
        d2, oq = fetch_latest_dated_tpex(lambda url: get_json(url, agent=agent, timeout=15), now_tw().date(), 5)
    except Exception as exc:
        errors.append('上櫃指定日期查詢失敗：' + str(exc)[:135])
        oq = get_list(OTC_QUOTE_URL, agent=agent)
    # 不因其中一個端點過期，就把整體看作今日正式排名。
    result = build_universe(lq, li, oq, oi)
    result['source_errors'] = errors
    return result


def parse_index_close(rows):
    """讀取證交所 MI_INDEX 官方收盤：漲跌點數通常是正數，須依漲跌符號還原。"""
    for r in rows:
        if str(r.get("指數", "")).strip() != "發行量加權股價指數":
            continue
        day = parse_date(r.get("日期"))
        value = numeric(r.get("收盤指數"))
        points = numeric(r.get("漲跌點數"))
        signed_pct = numeric(r.get("漲跌百分比", r.get("漲跌百分比(%)")))
        if value is None or value <= 0 or points is None:
            raise ValueError("加權指數缺少收盤或漲跌資料")
        mark = str(r.get("漲跌", "")).strip()
        if mark in ("-", "－", "▼", "−"):
            points = -abs(points)
        elif mark in ("+", "＋", "▲"):
            points = abs(points)
        elif signed_pct is not None:
            points = abs(points) if signed_pct > 0 else -abs(points) if signed_pct < 0 else Decimal(0)
        else:
            raise ValueError("加權指數缺少有效漲跌符號")
        prev = value - points
        if signed_pct is None:
            signed_pct = (points / prev * 100) if prev > 0 else None
        return {"value": value, "delta": points, "pct": signed_pct, "day": day,
                "time": "收盤", "source": "證交所正式收盤", "state": "正式收盤"}
    raise ValueError("官方回傳資料沒有發行量加權股價指數")


def fetch_official_index():
    """大盤優先查詢有日期的 TWSE FMTQIK；舊 OpenAPI 是歷史備援。"""
    old = None
    try:
        old = parse_index_close(get_list(INDEX_CLOSE_URL))
    except Exception:
        pass
    try:
        recent = fetch_latest_dated_index(lambda url: get_json(url, timeout=15), now_tw().date(), 5)
        if old is None or recent['day'] >= old['day']:
            return recent
    except Exception:
        if old is None:
            raise
    return old


def parse_intraday_index(payload):
    """MI_5MINS_INDEX：只接受帶有可驗證交易日的資料，避免誤用前日快照。"""
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list) or not payload["data"]:
        raise ValueError("盤中指數回傳格式不符合預期")
    if str(payload.get("stat", "OK")) != "OK":
        raise ValueError("盤中指數來源未回傳 OK")
    day = parse_date(payload.get("date"))
    last = payload["data"][-1]
    if not isinstance(last, list) or len(last) < 2:
        raise ValueError("盤中指數缺少時間或指數數值")
    value = numeric(last[1])
    if value is None or value <= 0:
        raise ValueError("盤中指數數值無效")
    return {"value": value, "day": day, "time": str(last[0]), "source": "證交所盤中指數", "prev": None}


def parse_mis_index(payload):
    """MIS 為第二個嘗試的來源；若不是 t00 加權指數，絕不當成大盤。"""
    if not isinstance(payload, dict):
        raise ValueError("MIS 指數資料非物件")
    candidates = payload.get("msgArray", [])
    for r in candidates if isinstance(candidates, list) else []:
        if str(r.get("c", "")).lower() != "t00" or str(r.get("ex", "")).lower() != "tse":
            continue
        day = parse_date(r.get("d"))
        # 大盤只有確認存在 z 報價時才視為盤中指數，拒用 pz 充當新指數。
        value = numeric(r.get("z"))
        if value is None or value <= 0:
            raise ValueError("MIS 大盤指數數值無效")
        return {"value": value, "day": day, "time": str(r.get("t") or ""),
                "source": "證交所 MIS 盤中指數", "prev": numeric(r.get("y"))}
    raise ValueError("MIS 未提供有效加權指數代號 t00")


def fetch_live_index():
    errors = []
    try:
        return parse_intraday_index(get_json(INDEX_INTRADAY_URL, timeout=9))
    except Exception as exc:
        errors.append(str(exc)[:90])
    try:
        agent = opener(cookie=True)
        query = urlencode({"ex_ch": "tse_t00.tw", "json": 1, "delay": 0, "_": int(time.time()*1000)})
        return parse_mis_index(get_json(MIS_QUOTES + "?" + query, agent=agent, timeout=9))
    except Exception as exc:
        errors.append(str(exc)[:90])
    raise RuntimeError("大盤盤中行情暫無法讀取：" + "；".join(errors))


def resolve_index(close, live, at):
    """正式收盤優先；盤中只用當日快照並以正確的前日收盤計算漲跌。"""
    if close and close["day"] == at.date() and not is_session(at):
        return close.copy()
    # 盤後絕不拿盤中最後成交快照冒充「正式收盤」。
    if live and live["day"] == at.date() and is_session(at):
        prev = live.get("prev")
        if prev is None or prev <= 0:
            prev = close["value"] if close and close["day"] < at.date() else None
        val = live["value"]
        delta = val - prev if prev else None
        pct = delta / prev * 100 if prev and delta is not None else None
        state = "盤中行情（免費來源，請核對成交時間）"
        return {"value": val, "delta": delta, "pct": pct, "day": live["day"],
                "time": live["time"], "source": live["source"], "state": state}
    if close:
        latest = close.copy()
        if is_after_close(at) and close["day"] < at.date():
            latest["state"] = "盤後等待今日正式收盤資料（目前僅有歷史收盤）"
        else:
            latest["state"] = "最近交易日正式收盤" if close["day"] < at.date() else "正式收盤"
        return latest
    return None


def parse_pe_rows(rows, market):
    """官方收盤本益比：空白、零或負值代表未公布有效本益比。"""
    code_key = "Code" if market == "上市" else "SecuritiesCompanyCode"
    pe_key = "PEratio" if market == "上市" else "PriceEarningRatio"
    output = {}
    for r in rows:
        code = str(r.get(code_key, "")).strip()
        if not stock_code(code):
            continue
        pe = numeric(r.get(pe_key))
        if pe is not None and pe <= 0:
            pe = None
        try:
            day = parse_date(r.get("Date"))
        except (ValueError, TypeError):
            day = None
        output[(market, code)] = (pe, day)
    if len(output) < 200:
        raise ValueError(f"{market}估值資料不完整（{len(output)} 檔）")
    return output


def fetch_pe_snapshot():
    """分市場獨立下載，讀不到本益比也不影響市值前 50 排名。"""
    agent = opener()
    output, warnings = {}, []
    for market, url in (("上市", LISTED_PE_URL), ("上櫃", OTC_PE_URL)):
        try:
            output.update(parse_pe_rows(get_list(url, agent=agent), market))
        except Exception as exc:
            warnings.append(f"{market}本益比更新失敗：{str(exc)[:110]}")
    return output, warnings


def attach_pe(rows, pe_map):
    """複製前 50 名而不修改官方排行榜的共用快取。"""
    output = []
    for src in rows:
        r = dict(src)
        r["pe"], r["pe_day"] = pe_map.get((r["market"], r["code"]), (None, None))
        output.append(r)
    return output


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
        """Batch-isolated MIS fetch. A single failed batch must not erase good quotes.

        Return (messages, warnings). Retry a failed batch once with smaller groups;
        expose failures if nothing usable was received. Public MIS is best effort.
        """
        self.warmup()
        msgs, warnings = [], []

        def retrieve(group):
            symbols = "|".join(("tse" if r["market"] == "上市" else "otc") + "_" + r["code"] + ".tw" for r in group)
            query = urlencode({"ex_ch": symbols, "json": 1, "delay": 0, "_": int(time.time()*1000)})
            request = Request(MIS_QUOTES + "?" + query,
                              headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                                       "Accept": "application/json, */*", "Referer": MIS_ROOT})
            with self.agent.open(request, timeout=10) as rsp:
                data = json.load(rsp)
            if not isinstance(data, dict) or not isinstance(data.get("msgArray"), list):
                raise ValueError("MIS 回傳的 msgArray 不是陣列")
            return [r for r in data["msgArray"] if isinstance(r, dict)]

        for i in range(0, len(candidates), 40):
            group = candidates[i:i+40]
            try:
                msgs.extend(retrieve(group))
            except Exception as exc:
                # Recover from request-length and transient network failures.
                recovered = 0
                for j in range(0, len(group), 10):
                    try:
                        block = retrieve(group[j:j+10])
                        recovered += len(block)
                        msgs.extend(block)
                    except Exception as sub_exc:
                        warnings.append(f"MIS 第{i+j+1}～{min(i+j+10,len(candidates))}檔無法連線：{str(sub_exc)[:90]}")
                if not recovered:
                    warnings.append(f"MIS 第{i+1}～{min(i+40,len(candidates))}檔失敗：{str(exc)[:90]}")
        if not msgs:
            raise RuntimeError("MIS 所有批次都沒有有效回應；" + "；".join(warnings[:2]))
        return msgs, warnings


def fetch_backup_intraday(candidates, at, max_symbols=80):
    """Best-effort dated 1-minute fallback, never imply licensed live data.

    Yahoo frequently rate limits cloud IPs. Try its two documented public chart
    hosts and return only valid timestamped trades from the requested day.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    target = candidates[:max_symbols]
    today = at.date()
    def one(row):
        symbol = str(row["code"]) + (".TW" if row["market"] == "上市" else ".TWO")
        for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
            url = f"https://{host}/v8/finance/chart/{quote(symbol)}?interval=1m&range=1d"
            try:
                payload = get_json(url, timeout=4)
                result = ((payload.get("chart") or {}).get("result") or [None])[0]
                if not isinstance(result, dict):
                    continue
                stamps = result.get("timestamp") or []
                indicators = (result.get("indicators") or {}).get("quote") or []
                closes = (indicators[0].get("close") or []) if indicators else []
                for stamp, raw_price in reversed(list(zip(stamps, closes))):
                    price = numeric(raw_price)
                    if price is None or price <= 0:
                        continue
                    timestamp = datetime.fromtimestamp(int(stamp), TW)
                    if timestamp.date() != today or timestamp > at + timedelta(minutes=2):
                        continue
                    prev = numeric((result.get("meta") or {}).get("chartPreviousClose"))
                    return ((row["market"], row["code"]),
                            {"price": price, "quote_day": timestamp.date(),
                             "quote_time": timestamp.strftime("%H:%M:%S"),
                             "prev_close": prev if prev and prev > 0 else None,
                             "timestamp": timestamp})
            except Exception:
                continue
        return None

    found = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = [pool.submit(one, row) for row in target]
        for future in as_completed(jobs):
            answer = future.result()
            if answer:
                found[answer[0]] = answer[1]
    return found


def retain_verified_quotes(rows, saved, at):
    """Remember today's previously verified prices without declaring them fresh.

    saved maps (market, code) to a copied row. All carried prices retain the
    original trade timestamp and are visibly labelled as previously obtained.
    """
    today = at.date()
    result = []
    for stock in rows:
        row = dict(stock)
        key = (row["market"], row["code"])
        prior = saved.get(key)
        quality = quote_quality(row, at)
        valid = row.get("quote_day") == today and quality[2] and row.get("source") in (
            "今日最新成交", "備援分鐘行情（可能延遲）", "授權行情快照（富果）")
        if valid:
            if prior and prior.get("quote_day") == today and str(prior.get("quote_time") or "") > str(row.get("quote_time") or ""):
                row = dict(prior)
                row["source"] = "沿用當日已取得成交（本輪行情較舊）"
            else:
                saved[key] = dict(row)
        elif prior and prior.get("quote_day") == today:
            row = dict(prior)
            row["source"] = "沿用當日已取得成交（本輪更新失敗）"
        result.append(row)
    # Only retain data from the same trading date; never carry it to tomorrow.
    for key in list(saved):
        if saved[key].get("quote_day") != today:
            del saved[key]
    result.sort(key=lambda r: r["shares"] * r["price"], reverse=True)
    return result


def apply_backup_quotes(candidates, backups, at):
    """Keep fresher MIS prices; backup quote timestamps remain visible."""
    result = []
    applied = 0
    for src in candidates:
        row = dict(src)
        quote = backups.get((row["market"], row["code"]))
        if quote and quote["quote_day"] == at.date():
            current_time = str(row.get("quote_time") or "")
            current_is_today_trade = (row.get("quote_day") == at.date()
                                      and row.get("source") == "今日最新成交")
            # Do not regress a fresher MIS trade to an older Yahoo quote.
            if not current_is_today_trade or quote["quote_time"] > current_time:
                row.update(price=quote["price"], quote_day=quote["quote_day"],
                           quote_time=quote["quote_time"],
                           source="備援分鐘行情（可能延遲）")
                if quote.get("prev_close"):
                    row["prev_close"] = quote["prev_close"]
                applied += 1
        result.append(row)
    result.sort(key=lambda r: r["shares"] * r["price"], reverse=True)
    return result, applied


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
                # z 才是已揭示的成交價；pz 僅當「時間未確認的參考價」，
                # 不得借用欄位 t 把 pz 冒充成有時間戳記的新成交。
                traded = numeric(raw.get("z"))
                p = traded or numeric(raw.get("pz"))
                y = numeric(raw.get("y"))
                if y is not None and y > 0:
                    row["prev_close"] = y
                up, down = numeric(raw.get("u")), numeric(raw.get("w"))
                if up and down and 0 < down < up:
                    row.update(limit_up=up, limit_down=down, limit_day=day)
                if p is not None and p > 0:
                    raw_clock = str(raw.get("t") or "")
                    valid_clock = traded is not None and _quote_hhmm(raw_clock) is not None
                    row.update(price=p, quote_day=day,
                               quote_time=raw_clock if valid_clock else "時間未確認",
                               source=("今日最新成交" if valid_clock else "當日參考價（成交時間未確認）")
                               if day == at.date() else "前次成交參考")
                    if day == at.date() and valid_clock:
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
    if len(history) < 5:
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
    prices = [row["price"]] + [history[d] for d in prior[:max(MA_WINDOWS) - 1]]
    return {n: (sum(prices[:n], Decimal(0)) / n if len(prices) >= n else None)
            for n in MA_WINDOWS}


def ma_alert(row, ma):
    """返回警示文字及四個觸線布林值（None=歷史價不足）。"""
    price = row["price"]
    def hit(n):
        avg = ma.get(n)
        return price <= avg if avg is not None and avg > 0 else None
    five, twenty, half, year = (hit(n) for n in (5, 20, 120, 240))
    alerts = []
    if five:
        alerts.append("≤5日線")
    if twenty:
        alerts.append("≤20日線")
    short = "⚠ " + "＋".join(alerts) if alerts else ""
    if half and year:
        long = "‼ ≤半年＋年線"
    elif year:
        long = "⚠ ≤年線"
    elif half:
        long = "⚠ ≤半年線"
    else:
        long = ""
    text = "｜".join(x for x in (short, long) if x)
    if not text and (half is None or year is None):
        text = "均線未齊"
    return text, five, twenty, half, year


def enrich(rows, store):
    output = []
    store.schedule(rows[:TOP])
    for rank, src in enumerate(rows[:TOP], 1):
        row = dict(src)
        hist, hist_status = store.get(symbol_for(row))
        ma = moving_averages(row, hist)
        alert, five, twenty, half, year = ma_alert(row, ma)
        limit, up, down = market_limits(row)
        prev = row.get("prev_close")
        delta = row["price"] - prev if prev else None
        pct = (delta / prev * 100) if prev else None
        row.update(rank=rank, ma5=ma[5], ma20=ma[20], ma60=ma[60], ma120=ma[120], ma240=ma[240],
                   ma5_alert=five, ma20_alert=twenty, half_alert=half, year_alert=year, ma_alert=alert, ma_state=hist_status,
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
                     "市值億元", "本益比(倍)", "本益比資料日", "漲跌停", "漲停價", "跌停價", "5日線", "20日線", "季線60日", "半年線120日", "年線240日", "均線警示", "股價≤5日線", "股價≤20日線", "股價≤半年線", "股價≤年線", "均線來源狀態", "價格來源", "行情驗證狀態", "延遲分鐘數(可驗證者)"])
    def yn(x): return "是" if x is True else "否" if x is False else "無資料"
    for r in rows:
        writer.writerow([asof.strftime("%Y-%m-%d %H:%M:%S"), r["rank"], r["code"], r["name"], r["market"],
                         str(r["quote_day"]), r["quote_time"], r["price"], r["delta"] if r["delta"] is not None else "",
                         dec_str(r["pct"]) if r["pct"] is not None else "", dec_str(r["cap"]),
                         dec_str(r.get("pe")) if r.get("pe") is not None else "",
                         r["pe_day"].isoformat() if r.get("pe_day") else "", r["limit"],
                         r["up_price"] or "", r["down_price"] or "", r["ma5"] if r["ma5"] is not None else "", r["ma20"] if r["ma20"] is not None else "", r["ma60"] or "", r["ma120"] or "", r["ma240"] or "",
                         r["ma_alert"], yn(r["ma5_alert"]), yn(r["ma20_alert"]), yn(r["half_alert"]), yn(r["year_alert"]), r["ma_state"], r["source"], quote_quality(r,asof)[0],
                         quote_quality(r,asof)[1] if quote_quality(r,asof)[1] is not None else ""])
    return ("\ufeff"+f.getvalue()).encode("utf-8")


# R22: Optional licensed live market snapshots. This function never fabricates prices.
# Requires Fugle Developer/Advanced plan with snapshot quotes permissions.
def fetch_licensed_snapshots(api_key, at=None):
    """Returns (quotes by market/code, TAIEX quote or None, warnings).

    A network success is NOT a fresh price. Every quote must have the
    requested Taiwan trading date and a valid exchange timestamp.
    """
    from urllib.request import Request
    from datetime import datetime, timedelta
    import json
    at = at or now_tw()
    market_quotes, index, warnings = {}, None, []
    if not api_key or not str(api_key).strip():
        return market_quotes, index, ['未設定授權行情金鑰']
    for label, category in [('上市', 'TSE'), ('上櫃', 'OTC')]:
        url = 'https://api.fugle.tw/marketdata/v1.0/stock/snapshot/quotes/' + category
        try:
            req = Request(url, headers={
                'X-API-KEY': api_key.strip(),
                'Accept': 'application/json',
                'User-Agent': 'TaiwanTop50-PrivateDashboard/1.0',
            })
            with opener().open(req, timeout=14) as response:
                payload = json.load(response)
            if not isinstance(payload, dict) or not isinstance(payload.get('data'), list):
                raise ValueError('授權快照的 JSON 格式不符預期')
            trading_day = parse_date(payload.get('date'))
            snapshot_time = str(payload.get('time') or '').strip()
            if len(snapshot_time) == 6 and snapshot_time.isdigit():
                snap_label = f'{snapshot_time[:2]}:{snapshot_time[2:4]}:{snapshot_time[4:6]}'
            else:
                snap_label = '時間未提供'
            # Require date equality: no old Friday price on Monday.
            if trading_day != at.date():
                warnings.append(f'{label}授權快照日期為 {trading_day}，非今天 {at.date()}，不覆蓋原行情')
                continue
            for rec in payload['data']:
                if not isinstance(rec, dict):
                    continue
                code = str(rec.get('symbol') or '').strip()
                # closePrice is the most recent EXECUTED trade; lastPrice may include trial matching.
                price = numeric(rec.get('closePrice'))
                if price is None or price <= 0:
                    continue
                stamp = rec.get('lastUpdated')
                quoted_at = None
                if isinstance(stamp, (float, int)):
                    try:
                        num = float(stamp)
                        if num > 1e14: num /= 1e6
                        elif num > 1e11: num /= 1e3
                        quoted_at = datetime.fromtimestamp(num, TW)
                    except (ValueError, OverflowError, OSError):
                        pass
                if quoted_at is None:
                    # Time-only is valid when the provider's date matches today.
                    try:
                        from datetime import time as _time
                        vals = list(map(int, snap_label.split(':')))
                        quoted_at = datetime.combine(trading_day, _time(*vals), tzinfo=TW)
                    except (ValueError, TypeError):
                        continue
                if quoted_at.date() != trading_day or quoted_at > at + timedelta(minutes=2):
                    continue
                # During an open session an hours-old snapshot is not current.
                if ((at.hour, at.minute) >= (9, 0) and (at.hour, at.minute) < (13, 30)
                        and (at - quoted_at).total_seconds() > 1200):
                    continue
                previous = numeric(rec.get('previousClose'))
                change = numeric(rec.get('change'))
                if (previous is None or previous <= 0) and change is not None and price - change > 0:
                    previous = price - change
                record = {
                    'price': price, 'prev_close': previous, 'quote_day': trading_day,
                    'quote_time': quoted_at.strftime('%H:%M:%S'),
                    'quote_at': quoted_at,
                    'source': '授權行情快照（富果）',
                }
                if category == 'TSE' and code == 'IX0001' and rec.get('type') == 'INDEX':
                    diff = numeric(rec.get('change'))
                    pct = numeric(rec.get('changePercent'))
                    index = {
                        'value': price, 'delta': diff, 'pct': pct,
                        'day': trading_day, 'time': record['quote_time'],
                        'source': '富果授權加權指數快照', 'state': '盤中行情快照',
                    }
                elif stock_code(code):
                    market_quotes[(label, code)] = record
        except Exception as exc:
            # Do not ever log / display api_key; HTTP exception strings omit request headers.
            warnings.append(f'{label}授權快照讀取失敗：{type(exc).__name__}：{str(exc)[:90]}')
    return market_quotes, index, warnings


def merge_licensed_quotes(rows, quotes, at=None):
    """Licensed quotes override free feeds only when dated today and time-valid."""
    from datetime import timedelta
    at = at or now_tw()
    out, count = [], 0
    for src in rows:
        rec = dict(src)
        extra = quotes.get((rec['market'], rec['code']))
        if extra and extra['quote_day'] == at.date() and extra['quote_at'] <= at + timedelta(minutes=2):
            existing = None
            if rec.get('quote_day') == at.date():
                try:
                    existing = datetime.strptime(str(rec.get('quote_time', ''))[:8], '%H:%M:%S').time()
                except ValueError:
                    pass
            if existing is None or extra['quote_at'].time() >= existing:
                rec.update(price=extra['price'], quote_day=extra['quote_day'],
                           quote_time=extra['quote_time'], source=extra['source'])
                if extra.get('prev_close') is not None:
                    rec['prev_close'] = extra['prev_close']
                count += 1
        out.append(rec)
    out.sort(key=lambda r: r['shares']*r['price'], reverse=True)
    return out, count

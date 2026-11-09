"""官方指定交易日收盤資料備援（不使用任何付費或非授權網頁擷取）。

TWSE: www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date=...&type=ALLBUT0999&response=json
TPEx: www.tpex.org.tw/www/zh-tw/afterTrading/otc?date=...&type=EW&response=json
TAIEX: TWSE FMTQIK by date/month.

Only claims an as-of date when that date is independently present in the payload.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from html import unescape
from urllib.parse import urlencode
import re

TWSE_DATED = 'https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX'
TPEX_DATED = 'https://www.tpex.org.tw/www/zh-tw/afterTrading/otc'
TWSE_INDEX = 'https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK'


def clean(x):
    return re.sub(r'\s+', '', re.sub(r'<[^>]*>', '', unescape(str(x or '')))).strip()


def number(x):
    s = clean(x).replace(',', '').replace('，', '').replace('＋', '+').replace('－', '-').replace('−','-')
    if s in ('', '-', '--', '---', '不適用', 'N/A', '除息', '除權', 'X', '—'):
        return None
    try:
        out = Decimal(s)
        return out if out.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def day_from(x):
    s = str(x or '').strip()
    s = re.sub(r'[^0-9]', '', s)
    if len(s) == 7:
        return date(1911 + int(s[:3]), int(s[3:5]), int(s[5:7]))
    if len(s) == 8:
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    raise ValueError(f'資料來源未提供可驗證日期：{x!r}')


def make_url(base, **params):
    return base + '?' + urlencode(params)


def fields_tables(payload):
    if not isinstance(payload, dict):
        raise ValueError('指定日期行情不是 JSON 物件')
    status = str(payload.get('stat', 'OK')).strip().lower()
    if status not in ('ok',):
        raise ValueError('交易所尚未公布指定日期資料：' + status[:100])
    tables = payload.get('tables', [])
    if isinstance(tables, list):
        for t in tables:
            if isinstance(t, dict) and isinstance(t.get('fields'), list) and isinstance(t.get('data'), list):
                yield [clean(x) for x in t['fields']], t['data'], str(t.get('title',''))
    for key in payload:
        m = re.fullmatch(r'fields(\d+)', str(key))
        if m and isinstance(payload.get(key), list) and isinstance(payload.get('data' + m.group(1)), list):
            yield [clean(x) for x in payload[key]], payload['data' + m.group(1)], ''
    if isinstance(payload.get('fields'), list) and isinstance(payload.get('data'), list):
        yield [clean(x) for x in payload['fields']], payload['data'], ''


def _payload_day(payload):
    # An explicitly dated request is NOT proof of the payload's date.
    if payload.get('date') is not None:
        try:
            return day_from(payload['date'])
        except (TypeError, ValueError):
            pass
    titles = [payload.get(name) for name in ('title', 'reportDate', 'Date')]
    titles += [t.get('title') for t in payload.get('tables', []) if isinstance(t, dict)]
    for val in titles:
        val = str(val or '')
        for p in (r'(\d{3})年(\d{1,2})月(\d{1,2})日',r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})'):
            m = re.search(p, val)
            if m:
                year, month, day = (int(v) for v in m.groups())
                return date(year + 1911 if year < 1911 else year, month, day)
    return None


def _stock_code(x):
    s = clean(x)
    return len(s) == 4 and s.isascii() and s.isdecimal() and not s.startswith(('0','91'))


def _find_field(fields, candidates):
    for key in candidates:
        if key in fields:
            return fields.index(key)
    return None


def _row_change(raw, sign=''):
    val = number(raw)
    if val is None:
        return None
    sign = clean(sign)
    if any(s in sign for s in ('-', '－', '▼', '跌', '−')):
        return -abs(val)
    if any(s in sign for s in ('+', '＋', '▲', '漲')):
        return abs(val)
    # Some feeds provide the negative sign in raw rather than separate HTML sign.
    return val


def parse_twse_dated(payload, requested_day):
    actual = _payload_day(payload)
    if actual != requested_day:
        raise ValueError(f'證交所指定日期查詢回傳日期 {actual}，不是 {requested_day}')
    best = []
    for fields, rows, _ in fields_tables(payload):
        i_code = _find_field(fields, ('證券代號',))
        i_close = _find_field(fields, ('收盤價',))
        i_name = _find_field(fields, ('證券名稱',))
        i_chg = _find_field(fields, ('漲跌價差',))
        i_sign = _find_field(fields, ('漲跌(+/-)', '漲跌(+／-)', '漲跌符號'))
        if i_code is None or i_close is None or i_name is None:
            continue
        chosen=[]
        for values in rows:
            if not isinstance(values,(list,tuple)) or len(values) <= max(i_code,i_close,i_name):
                continue
            code = clean(values[i_code]); price=number(values[i_close])
            if not _stock_code(code) or price is None or price <= 0:
                continue
            chg = _row_change(values[i_chg] if i_chg is not None and len(values)>i_chg else '',
                              values[i_sign] if i_sign is not None and len(values)>i_sign else '')
            chosen.append({'Date':requested_day.strftime('%Y%m%d'),'Code':code,'Name':clean(values[i_name]),
                           'ClosingPrice':str(price),'Change':str(chg) if chg is not None else ''})
        if len(chosen) > len(best):
            best=chosen
    if len(best) < 500:
        raise ValueError(f'證交所 {requested_day} 指定日期股票只有 {len(best)} 檔，拒絕覆蓋資料')
    return best


def parse_tpex_dated(payload, requested_day, verified_query=False):
    actual = _payload_day(payload)
    # TPEx has variants without a top-level date; a row Date column is accepted.
    best=[]
    for fields, rows, _ in fields_tables(payload):
        i_code=_find_field(fields,('代號', '證券代號'))
        i_close=_find_field(fields,('收盤','收盤價'))
        i_name=_find_field(fields,('名稱','證券名稱'))
        i_chg=_find_field(fields,('漲跌','漲跌價差'))
        i_day=_find_field(fields,('資料日期','日期'))
        if None in (i_code,i_close,i_name):
            continue
        if actual is None and i_day is None and not verified_query:
            # An undated response is usable only after two distinct query days return distinct content.
            raise ValueError('櫃買中心資料無日期欄位，須以不同日期對照驗證')
        chosen=[]
        for v in rows:
            if not isinstance(v,(list,tuple)) or len(v)<=max(i_code,i_close,i_name):
                continue
            if i_day is not None:
                try:
                    if day_from(v[i_day]) != requested_day:
                        continue
                except (ValueError,TypeError):
                    continue
            code=clean(v[i_code]); px=number(v[i_close])
            if not _stock_code(code) or px is None or px<=0:
                continue
            chg=number(v[i_chg]) if i_chg is not None and i_chg<len(v) else None
            chosen.append({'Date':requested_day.strftime('%Y%m%d'),'SecuritiesCompanyCode':code,
                           'CompanyName':clean(v[i_name]),'Close':str(px),
                           'Change':str(chg) if chg is not None else ''})
        if len(chosen)>len(best):
            best=chosen
    if actual is not None and actual!=requested_day:
        raise ValueError(f'櫃買回傳日期 {actual} 不等於 {requested_day}')
    if len(best)<300:
        raise ValueError(f'櫃買 {requested_day} 僅 {len(best)} 檔，不足以建立市值前50大')
    return best


def parse_index_from_fmtqik(payload, requested_day):
    if not isinstance(payload,dict) or str(payload.get('stat','OK')).upper()!='OK':
        raise ValueError('加權指數指定日期端點暫無有效資料')
    for fields, rows,_ in fields_tables(payload):
        i_date = _find_field(fields,('日期','日 期'))
        i_val = _find_field(fields,('發行量加權股價指數','收盤指數'))
        i_delta = _find_field(fields,('漲跌點數', '漲跌'))
        if None in (i_date,i_val,i_delta):
            continue
        for r in rows:
            if not isinstance(r,(list,tuple)) or len(r)<=max(i_date,i_val,i_delta):
                continue
            try: day=day_from(r[i_date])
            except (TypeError,ValueError): continue
            if day!=requested_day: continue
            px=number(r[i_val]); delta=number(r[i_delta])
            if px is None or px<=0 or delta is None:
                continue
            prev=px-delta
            return {'value':px,'delta':delta,'pct':delta/prev*100 if prev>0 else None,
                    'day':day,'time':'收盤','source':'證交所正式收盤（指定日期）','state':'正式收盤'}
    raise ValueError(f'證交所 FMTQIK 尚無 {requested_day} 指數收盤資料')


def recent_dates(today, lookback=8):
    return [today-timedelta(days=i) for i in range(lookback)]


def fetch_latest_dated_twse(get_json, today, days=8):
    errs=[]
    for d in recent_dates(today, days):
        if d.weekday()>=5: continue
        url=make_url(TWSE_DATED,date=d.strftime('%Y%m%d'),type='ALLBUT0999',response='json')
        try:
            return d,parse_twse_dated(get_json(url),d)
        except Exception as e:
            errs.append(f'{d}: {str(e)[:100]}')
    raise RuntimeError('證交所指定日期收盤行情不可用；'+ '；'.join(errs[:2]))


def fetch_latest_dated_tpex(get_json, today, days=8):
    errs=[]
    for d in recent_dates(today,days):
        if d.weekday()>=5:continue
        url=make_url(TPEX_DATED,date=d.strftime('%Y/%m/%d'),type='EW',response='json')
        try:
            payload=get_json(url)
            try:
                return d,parse_tpex_dated(payload,d)
            except ValueError as e:
                if '須以不同日期對照驗證' not in str(e):
                    raise
                # Some TPEx JSON responses omit their own date. Cross-check that
                # requesting two distinct dates actually returns two different
                # full-market quote sets; otherwise never label the requested day.
                previous=d-timedelta(days=1)
                while previous.weekday()>=5:
                    previous-=timedelta(days=1)
                url2=make_url(TPEX_DATED,date=previous.strftime('%Y/%m/%d'),type='EW',response='json')
                other=get_json(url2)
                current_rows=parse_tpex_dated(payload,d,verified_query=True)
                previous_rows=parse_tpex_dated(other,previous,verified_query=True)
                sample=lambda rows: {(r['SecuritiesCompanyCode'],r['Close']) for r in rows}
                if len(sample(current_rows).symmetric_difference(sample(previous_rows)))<20:
                    raise ValueError('櫃買未能證明 date 參數被採用，拒絕當日收盤')
                return d,current_rows
        except Exception as e:
            errs.append(f'{d}: {str(e)[:110]}')
    raise RuntimeError('櫃買指定日期收盤行情不可用；'+ '；'.join(errs[:2]))


def fetch_latest_dated_index(get_json, today, days=8):
    errs=[]
    for d in recent_dates(today, days):
        if d.weekday()>=5:continue
        url=make_url(TWSE_INDEX,date=d.strftime('%Y%m%d'),response='json')
        try:
            return parse_index_from_fmtqik(get_json(url),d)
        except Exception as e:
            errs.append(f'{d}: {str(e)[:100]}')
    raise RuntimeError('證交所指定日期指數不可用；'+ '；'.join(errs[:2]))

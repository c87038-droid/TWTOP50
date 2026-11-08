"""台股市值前 50 大手機網頁。部署：Streamlit Community Cloud，入口 app.py。"""
from __future__ import annotations

from datetime import datetime
from html import escape
import threading
import time

import streamlit as st

import market_data as md

st.set_page_config(
    page_title="台股市值前50大｜手機排行榜",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# 雙檔版本驗證：即使 GitHub 只更新 app.py，仍能顯示可理解的錯誤，而非 ImportError。
WEB_BUILD = "20261108-R9-LARGE"
REQUIRED = (
    "TOP", "CANDIDATES", "HistoryStore", "MisClient", "apply_mis", "csv_bytes",
    "dec_str", "enrich", "fetch_official", "fetch_pe_snapshot", "attach_pe",
    "is_after_close", "is_session", "now_tw",
    "fetch_official_index", "fetch_live_index", "resolve_index",
)
missing = [name for name in REQUIRED if not hasattr(md, name)]
if missing:
    st.error("GitHub 上的 app.py 與 market_data.py 不是同一個版本，網站暫時無法啟動。")
    st.markdown("**修復方法：**請把修正版的 `app.py` 和 `market_data.py` 兩個檔案一起覆蓋到 GitHub 資料庫的最外層，再按 `Commit changes`。")
    st.code("market_data.py 缺少：" + ", ".join(missing), language="text")
    st.stop()

(TOP, CANDIDATES, HistoryStore, MisClient, apply_mis, csv_bytes,
 dec_str, enrich, fetch_official, fetch_pe_snapshot, attach_pe,
 is_after_close, is_session, now_tw,
 fetch_official_index, fetch_live_index, resolve_index) = tuple(getattr(md, name) for name in REQUIRED)

st.markdown("""
<style>
#MainMenu, footer {visibility:hidden}
.block-container {max-width: 1500px; padding-top: 1.15rem; padding-bottom: 3rem}
h1,h2,h3 {font-family:system-ui,'Microsoft JhengHei',sans-serif}
.board-title {font-size:clamp(25px,3vw,36px);font-weight:850;color:#142b45;letter-spacing:-.6px}
.board-subtitle {color:#667b90;font-size:14px;margin-top:3px}
.summarybar {display:flex;gap:10px;flex-wrap:wrap;margin:12px 0}
.summarybox {flex:1;min-width:135px;border:1px solid #dbe5ef;background:#f5f8fc;border-radius:13px;padding:12px}
.summarybox .metric-label {display:block;color:#52647c;font-size:13px;margin-bottom:5px}
.summarybox .metric-value {font-weight:800;font-size:21px;color:#173250}
.index-card {padding:16px 20px;margin:14px 0 12px;border-radius:16px;background:linear-gradient(115deg,#142f53,#204c7a);color:#fff;box-shadow:0 3px 12px #142b4525}
.index-title {font-size:15px;font-weight:700;letter-spacing:.4px;color:#e1ebf8}
.index-main {display:flex;flex-wrap:wrap;align-items:baseline;gap:12px;margin-top:4px}
.index-level {font-size:clamp(32px,6.3vw,48px);line-height:1.25;font-weight:850;white-space:nowrap;letter-spacing:-.8px;font-variant-numeric:tabular-nums}
.index-move {font-size:clamp(18px,3.6vw,24px);line-height:1.4;font-weight:800;white-space:nowrap;font-variant-numeric:tabular-nums}
.index-up {color:#ff9d9d}.index-down {color:#90f0b9}.index-flat {color:#e8eef6}
.index-note {font-size:12px;color:#cfdfef;margin-top:8px;line-height:1.6}
@media(max-width:560px){.index-card{padding:14px 12px}.index-main{gap:6px 13px}.index-level{font-size:34px}.index-move{font-size:20px}}

.board-note {color:#53677c;font-size:13px;margin:8px 0 13px;line-height:1.65}
.stock-list {display:flex;flex-direction:column;gap:7px}
.stock-row {display:grid;grid-template-columns:42px minmax(125px,1.1fr) minmax(115px,.82fr) minmax(105px,.80fr) minmax(153px,1fr) minmax(250px,1.9fr) minmax(165px,1.25fr);gap:10px;align-items:center;background:#fff;border:1px solid #e1e8f0;border-left:5px solid #c7d7e6;border-radius:12px;padding:11px 9px;box-shadow:0 1px 3px #142b4510;font-size:14px;color:#24374c}
.stock-head {font-size:12px;font-weight:700;color:#52667e;background:#e9f1fa;box-shadow:none}
.stock-row .rank {font-size:19px;font-weight:800;text-align:center;color:#24466d}
.stock-row .identity-line {display:flex;align-items:center;gap:7px;flex-wrap:wrap}
.stock-row .stock-code {font-size:15px;line-height:1.3;font-weight:850;color:#075ca8;background:#e6f3ff;border:1px solid #b5d9fa;padding:3px 7px;border-radius:7px;white-space:nowrap;font-variant-numeric:tabular-nums}
.stock-row .stock-market {font-size:12px;color:#5e7792;margin-top:4px}
.stock-row .stock-name {font-size:17px;font-weight:780;line-height:1.3;color:#213b5c}
.stock-row .price-value {font-size:20px;font-weight:850;white-space:nowrap}
.stock-row .change {font-size:13px;white-space:nowrap;margin-top:3px}
.stock-row .pe-inline {font-size:13px;color:#395672;font-weight:600;margin-top:4px;white-space:nowrap}
.stock-row .pe-inline strong {font-size:16px;color:#105791;font-weight:850}
.stock-row .cap {font-weight:700;white-space:nowrap}
.stock-row .cap-label {font-size:12px;color:#6a7a8f;margin-top:3px}
.stock-row .ma {font-size:12px;line-height:1.85;display:flex;gap:10px;flex-wrap:wrap}
.stock-row .ma strong {font-size:13px;color:#334c68}
.stock-row .info {font-size:11px;color:#6e8298;line-height:1.5}
.stock-row .flag {font-size:12px;font-weight:750;line-height:1.5}
.stock-row .warn {font-size:12px;font-weight:800;line-height:1.45}
.stock-row.limit-up {background:#ffe9ec;border-left-color:#d32d48}
.stock-row.limit-down {background:#e4f7eb;border-left-color:#159768}
.stock-row.ma-half:not(.limit-up):not(.limit-down) {background:#fff6d7;border-left-color:#d99a10}
.stock-row.ma-year:not(.limit-up):not(.limit-down) {background:#f4eaff;border-left-color:#865bc7}
.stock-row.ma-both:not(.limit-up):not(.limit-down) {background:#ffe0cf;border-left-color:#d8682b}
.stock-row .up {color:#c5293f}.stock-row .down{color:#068157}
.stock-row .warn {color:#935419}
.stock-row.ma-year .warn {color:#6940a6}
.stock-row.ma-both .warn {color:#983d1a}
.stock-row .plain {color:#546d83}
@media(max-width:1040px) {
.stock-head {display:none}
.stock-row {grid-template-columns:37px minmax(125px,1.25fr) minmax(90px,.9fr) minmax(100px,.9fr);grid-template-areas:"rank identity price cap" "rank flags flags flags" "ma ma ma ma" "quote quote quote quote";column-gap:9px;row-gap:4px}
.stock-row .rank{grid-area:rank}.stock-row .identity{grid-area:identity}.stock-row .price{grid-area:price}.stock-row .cap{grid-area:cap}
.stock-row .flags{grid-area:flags}.stock-row .ma{grid-area:ma}.stock-row .info{grid-area:quote}
.stock-row .ma {display:flex;gap:12px;flex-wrap:wrap;padding-top:5px;border-top:1px solid #e1e8f0;margin-top:4px}
.stock-row .flags{display:flex;gap:10px;flex-wrap:wrap}
.stock-row .pe-inline{font-size:11px;letter-spacing:-.2px}
.stock-row .pe-inline strong{font-size:13px}
}
@media(max-width:560px) {
.block-container {padding-left:11px;padding-right:11px;padding-top:0.5rem}
.stock-row {grid-template-columns:30px minmax(80px,1fr) 95px;grid-template-areas:"rank identity price" "rank identity cap" "flags flags flags" "ma ma ma" "quote quote quote";padding:10px 8px;gap:5px}
.stock-row .rank{font-size:17px}.stock-row .stock-name {font-size:16px}
.stock-row .stock-code{font-size:15px;padding:3px 6px}
.stock-row .identity-line{gap:5px}
.stock-row .price-value{font-size:20px}.stock-row .price,.stock-row .cap{text-align:right}
.stock-row .cap{font-size:12px}.stock-row .cap-label{display:inline;margin-left:5px}
.stock-row .ma{font-size:12px;gap:8px;justify-content:space-between}
.stock-row .info{font-size:11px}
.summarybox {min-width:105px;padding:9px}.summarybox .metric-value{font-size:17px}
}

/* R9 大字體：保留 R8 行情、排名、本益比、均線演算法；以 CSS 改善閱讀性。 */
.board-title {font-size:clamp(30px,3.3vw,43px);line-height:1.25}
.board-subtitle {font-size:16px;line-height:1.65}
.summarybox .metric-label {font-size:15px}
.summarybox .metric-value {font-size:24px}
.index-title {font-size:18px}
.index-level {font-size:clamp(38px,6.4vw,57px)}
.index-move {font-size:clamp(21px,3.8vw,30px)}
.index-note {font-size:14px;line-height:1.65}
.board-note {font-size:15px;line-height:1.7}
.stock-row {font-size:16px;line-height:1.55;min-width:0;padding:14px 12px;row-gap:10px}
.stock-head {font-size:14px}
.stock-row .identity {min-width:0}
.stock-row .rank {font-size:22px}
.stock-row .stock-code {font-size:18px;padding:5px 8px}
.stock-row .stock-name {font-size:20px}
.stock-row .stock-market {font-size:14px}
.stock-row .price-value {font-size:25px}
.stock-row .change {font-size:15px}
.stock-row .pe-inline {font-size:15px}
.stock-row .pe-inline strong {font-size:18px}
.stock-row .cap {font-size:17px}
.stock-row .cap-label {font-size:14px}
.stock-row .ma {font-size:15px;line-height:1.8}
.stock-row .ma strong {font-size:15px}
.stock-row .info {font-size:13px;line-height:1.65;overflow-wrap:anywhere}
.stock-row .flag, .stock-row .warn {font-size:15px;line-height:1.6}
@media (max-width:1040px) {
  .stock-row {row-gap:9px}
  .stock-row .pe-inline {font-size:15px;letter-spacing:normal}
  .stock-row .pe-inline strong {font-size:18px}
}
@media (max-width:560px) {
  .block-container {padding-left:10px;padding-right:10px}
  .board-title {font-size:29px}
  .board-subtitle {font-size:15px}
  .index-card {padding:15px 12px}
  .index-level {font-size:36px}
  .index-move {font-size:21px;white-space:normal}
  .index-note {font-size:13px}
  .summarybox {min-width:calc(50% - 6px);padding:11px}
  .summarybox .metric-label {font-size:14px}
  .summarybox .metric-value {font-size:19px;overflow-wrap:anywhere}
  .stock-row {
    grid-template-columns:30px minmax(0,1fr) minmax(112px,auto);
    grid-template-areas:"rank identity price" "rank identity cap" "flags flags flags" "ma ma ma" "quote quote quote";
    gap:8px 7px;padding:13px 10px
  }
  .stock-row .rank {font-size:20px}
  .stock-row .identity {overflow-wrap:anywhere}
  .stock-row .stock-name {font-size:19px}
  .stock-row .stock-code {font-size:17px;padding:4px 7px}
  .stock-row .identity-line {gap:6px}
  .stock-row .price-value {font-size:23px}
  .stock-row .change {font-size:14px;white-space:normal}
  .stock-row .pe-inline {font-size:14px;white-space:normal}
  .stock-row .pe-inline strong {font-size:16px}
  .stock-row .cap {font-size:15px}
  .stock-row .cap-label {font-size:12px}
  .stock-row .ma {font-size:15px;justify-content:flex-start;gap:4px 15px;flex-wrap:wrap}
  .stock-row .ma strong {font-size:15px}
  .stock-row .flag, .stock-row .warn {font-size:15px}
  .stock-row .info {font-size:13px}
  .board-note {font-size:14px}
}
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=300, show_spinner=False)
def official_snapshot():
    return fetch_official()


@st.cache_data(ttl=15, show_spinner=False)
def mis_snapshot(key: str, _candidates):
    # key=日期/候選名單內容；_candidates 不納入快取鍵，避免每次複製大量 Decimal。
    return MisClient().fetch(_candidates)


@st.cache_data(ttl=600, show_spinner=False)
def pe_snapshot():
    return fetch_pe_snapshot()


@st.cache_data(ttl=300, show_spinner=False)
def official_index_snapshot():
    return fetch_official_index()


@st.cache_data(ttl=15, show_spinner=False)
def intraday_index_snapshot():
    return fetch_live_index()


def index_card(at):
    """獨立顯示大盤：排行／本益比即使出錯也不影響大盤資訊。"""
    close = live = None
    issues = []
    try:
        close = official_index_snapshot()
    except Exception as exc:
        issues.append("官方收盤來源：" + str(exc)[:90])
    if is_session(at) or (is_after_close(at) and (not close or close["day"] < at.date())):
        try:
            live = intraday_index_snapshot()
        except Exception as exc:
            issues.append("盤中來源：" + str(exc)[:90])
    status = resolve_index(close, live, at)
    if not status:
        st.warning("加權指數目前無法取得，排行榜仍可獨立使用。" + ("；".join(issues)[:160] if issues else ""))
        return
    delta = status["delta"]
    pct = status["pct"]
    colour = "index-up" if delta is not None and delta > 0 else "index-down" if delta is not None and delta < 0 else "index-flat"
    mark = "▲" if delta is not None and delta > 0 else "▼" if delta is not None and delta < 0 else "—"
    movement = f"{mark} {abs(delta):,.2f} 點" if delta is not None else "漲跌待確認"
    percent = f"{pct:+.2f}%" if pct is not None else "—"
    stamp = f"{status['day']:%Y-%m-%d} {status['time']}"
    st.markdown(f"""<section class="index-card" aria-label="台股加權股價指數">
    <div class="index-title">🇹🇼 台股加權指數（TAIEX）</div>
    <div class="index-main"><span class="index-level">{status['value']:,.2f}</span>
    <span class="index-move {colour}">{movement}　{percent}</span></div>
    <div class="index-note">{escape(status['state'])} · {escape(stamp)} · {escape(status['source'])} · 台灣時間</div>
    </section>""", unsafe_allow_html=True)
    if issues and close and (not live or close["day"] < at.date()) and is_session(at):
        st.caption("⚠️ 盤中大盤資料暫無法更新，顯示最近交易日正式收盤值（不是現在的盤中指數）。")


@st.cache_resource(show_spinner=False)
def resources():
    return {"hist": HistoryStore(), "lock": threading.Lock(),
            "last_official": None, "last_top50": None, "last_top50_at": None,
            "last_pe_map": {}}


def build_board(state, at):
    warnings = []
    try:
        official = official_snapshot()
        with state["lock"]:
            state["last_official"] = official
    except Exception as exc:
        with state["lock"]:
            official = state["last_official"]
        if official is None:
            raise RuntimeError(f"暫時無法取得官方排行榜：{str(exc)[:180]}") from exc
        warnings.append("官方資料來源目前連線異常，沿用伺服器上次成功取得的官方資料。")

    base = official["records"]
    if not official["synchronized"]:
        warnings.append("上市／上櫃官方收盤日期尚未同步，目前為跨日期參考排名，非正式收盤排名。")
    mode = "正式收盤價" if official["synchronized"] else "日期未同步參考價"
    fresh = 0
    universe = base
    last_date = max(official["listed_date"], official["otc_date"])
    if is_session(at) or (is_after_close(at) and last_date < at.date()):
        candidates = base[:CANDIDATES]
        key = f"{official['listed_date']}_{official['otc_date']}_" + "-".join(x["code"] for x in candidates[:5])
        try:
            messages = mis_snapshot(key, candidates)
            mixed, fresh = apply_mis(candidates, messages, at)
            if fresh:
                universe = mixed
                if is_session(at):
                    mode = "盤中近即時估算"
                else:
                    mode = "盤後最後成交（待官方確認）"
                    warnings.append("當日正式收盤資料尚未同步，目前顯示最後成交價的估算排名，請留意股價來源。")
            elif is_session(at):
                warnings.append("目前尚未取得今日有效成交報價，可能休市或報價服務延遲；顯示最近官方收盤價。")
        except Exception as exc:
            warnings.append(f"盤中報價暫時無法更新，保留最新可用的收盤基準資料：{str(exc)[:110]}")

    top = universe[:TOP]
    if len(top) < TOP:
        raise RuntimeError(f"本次有效股票只有 {len(top)} 檔，不足 50。")
    try:
        pe_map, pe_warnings = pe_snapshot()
        if pe_map:
            with state["lock"]:
                state["last_pe_map"].update(pe_map)
        warnings.extend(pe_warnings)
    except Exception as exc:
        warnings.append(f"本益比來源暫時無法讀取：{str(exc)[:110]}")
    with state["lock"]:
        valuation = dict(state["last_pe_map"])
    rows = enrich(attach_pe(top, valuation), state["hist"])
    with state["lock"]:
        state["last_top50"] = rows
        state["last_top50_at"] = at
    return rows, official, mode, fresh, warnings, at


def fmt(val, digits=2):
    return dec_str(val, digits)


def stock_html(row):
    name = escape(str(row["name"]))
    code = escape(str(row["code"]))
    market = escape(str(row["market"]))
    text_limit = escape(row["limit"] or "—")
    alert = escape(row["ma_alert"] or "—")
    change = row["pct"]
    change_class = "up" if change is not None and change > 0 else "down" if change is not None and change < 0 else "plain"
    pct = f"{change:+.2f}%" if change is not None else "—"
    delta = f"{row['delta']:+.2f}" if row["delta"] is not None else "—"
    pe = f"{fmt(row['pe'])} 倍" if row.get("pe") is not None else "—"
    pe_time = f" · 本益比基準 {row['pe_day']}" if row.get("pe_day") else ""
    css = []
    if "漲停" in row["limit"]: css.append("limit-up")
    elif "跌停" in row["limit"]: css.append("limit-down")
    if row["half_alert"] and row["year_alert"]: css.append("ma-both")
    elif row["year_alert"]: css.append("ma-year")
    elif row["half_alert"]: css.append("ma-half")
    css = " ".join(css)
    meta = escape(f"{row['quote_day']} {row['quote_time']} · {row['source']} · {row['ma_state']}{pe_time}")
    return f'''<div class="stock-row {css}">
<div class="rank">{row['rank']}</div>
<div class="identity"><div class="identity-line"><span class="stock-code" aria-label="股票代碼 {code}">{code}</span><span class="stock-name">{name}</span></div><div class="stock-market">{market}</div></div>
<div class="price"><div class="price-value">{fmt(row['price'])}</div><div class="change {change_class}">{pct} ({delta})</div><div class="pe-inline">本益比 <strong>{pe}</strong></div></div>
<div class="cap">{fmt(row['cap'],1)}<div class="cap-label">億元市值</div></div>
<div class="flags"><div class="flag {'up' if '漲停' in row['limit'] else 'down' if '跌停' in row['limit'] else 'plain'}">{text_limit}</div><div class="warn">{alert}</div></div>
<div class="ma"><span><strong>季線</strong> {fmt(row['ma60'])}</span><span><strong>半年線</strong> {fmt(row['ma120'])}</span><span><strong>年線</strong> {fmt(row['ma240'])}</span></div>
<div class="info">{meta}</div>
</div>'''


st.markdown('<div class="board-title">📈 台股市值 TOP 50｜大盤指數＋本益比</div><div class="board-subtitle">上市＋上櫃 · 單頁 50 名 · 盤中／盤後 · 官方收盤本益比 · 三條均線 · 大盤漲跌 · R9 大字體版</div>', unsafe_allow_html=True)


@st.fragment(run_every="15s")
def live_board():
    state = resources()
    at = now_tw()
    index_card(at)
    try:
        records, official, mode, fresh, warnings, grabbed_at = build_board(state, at)
        used_old = False
    except Exception as exc:
        with state["lock"]:
            prior = state["last_top50"]
            prior_at = state["last_top50_at"]
        if not prior:
            st.error(f"目前無法顯示排行榜：{exc}")
            st.info("請稍後重新整理。免費資料來源偶爾會封鎖或延遲，網站不會編造股價與均線。")
            return
        records = prior
        grabbed_at = prior_at
        official = None
        mode = "沿用上次可用排行榜"
        fresh = 0
        used_old = True
        warnings = [f"行情讀取失敗，正在顯示伺服器上一次成功資料（{grabbed_at:%Y-%m-%d %H:%M:%S}） 。原因：{str(exc)[:130]}"]

    trade_days = sorted({r["quote_day"].isoformat() for r in records})
    ma_ready = sum(1 for r in records if r["ma120"] is not None and r["ma240"] is not None)
    alert_count = sum(1 for r in records if r["half_alert"] or r["year_alert"])
    limit_count = sum(1 for r in records if "漲停" in r["limit"] or "跌停" in r["limit"])
    st.markdown(
        '<div class="summarybar">'
        f'<div class="summarybox"><span class="metric-label">目前模式</span><span class="metric-value">{escape(mode)}</span></div>'
        f'<div class="summarybox"><span class="metric-label">市值排名</span><span class="metric-value">{len(records)} / 50</span></div>'
        f'<div class="summarybox"><span class="metric-label">半年／年線警示</span><span class="metric-value">{alert_count} 檔</span></div>'
        f'<div class="summarybox"><span class="metric-label">均線已備齊</span><span class="metric-value">{ma_ready} / 50</span></div>'
        '</div>', unsafe_allow_html=True)
    st.caption(f"台灣時間 {now_tw():%Y-%m-%d %H:%M:%S} · 資料日期：{'、'.join(trade_days)} · 本輪今日有效成交：{fresh} 檔 · 漲跌停／推估：{limit_count} 檔")

    for warning in warnings:
        st.warning(warning, icon="⚠️")
    col_search, col_filter = st.columns([2, 1], gap="small")
    with col_search:
        search = st.text_input("搜尋股票", placeholder="輸入代號或公司名稱（預設顯示 50 名）", key="stock_filter")
    with col_filter:
        selected = st.selectbox("快速篩選", ["全部50名", "≤半年線", "≤年線", "同時≤兩線", "漲停", "跌停", "均線資料不足"], key="alert_filter")

    visible = []
    for r in records:
        if search and search.strip().lower() not in (r["code"]+r["name"]).lower():
            continue
        if selected == "≤半年線" and r["half_alert"] is not True: continue
        if selected == "≤年線" and r["year_alert"] is not True: continue
        if selected == "同時≤兩線" and not (r["half_alert"] and r["year_alert"]): continue
        if selected == "漲停" and "漲停" not in r["limit"]: continue
        if selected == "跌停" and "跌停" not in r["limit"]: continue
        if selected == "均線資料不足" and r["ma120"] is not None and r["ma240"] is not None: continue
        visible.append(r)

    tool1, tool2 = st.columns([1, 1], gap="small")
    with tool1:
        st.download_button("⬇️ 下載完整 50 名 CSV", data=csv_bytes(records, grabbed_at),
                           file_name=f"台股市值前50大_{grabbed_at:%Y%m%d_%H%M}.csv", mime="text/csv",
                           use_container_width=True, key="csv_all")
    with tool2:
        if st.button("🔄 立即重新整理", use_container_width=True, key="manual_refresh"):
            mis_snapshot.clear()
            official_snapshot.clear()
            pe_snapshot.clear()
            official_index_snapshot.clear()
            intraday_index_snapshot.clear()
            st.rerun(scope="fragment")
    st.markdown(f'<div class="board-note">顯示 <strong>{len(visible)}</strong> 檔（完整排名固定 1～50；篩選不會重新編號）。紅色＝漲停、綠色＝跌停、黃色＝≤半年線、紫色＝≤年線、橘色＝同時≤兩線。<br>本益比取 TWSE／TPEx 官方最近收盤估值（非盤中即時，日期以各檔顯示為準）。均線使用 60／120／240 個交易日的未還原收盤價。資料不足時顯示「—」，不會以 0 代替。</div>', unsafe_allow_html=True)

    if visible:
        header = '''<div class="stock-row stock-head"><div>名次</div><div>股票代碼／公司名稱</div><div>股價／本益比</div><div>市值</div><div>漲跌停／警示</div><div>季／半年／年線</div><div>資料時間</div></div>'''
        st.markdown('<div class="stock-list">'+header+''.join(stock_html(r) for r in visible)+'</div>', unsafe_allow_html=True)
    else:
        st.info("目前沒有符合篩選條件的股票，請改選『全部50名』。")

    st.markdown('''<div class="board-note" style="margin-top:20px">
<b>資料使用說明：</b>盤中每 15 秒<strong>嘗試</strong>更新，未必為零延遲逐筆成交；盤中從最近正式收盤市值前 200 名中估算前 50 名。
盤後優先使用 TWSE／TPEx 全市場正式收盤資料；尚未發布時會明示「待官方確認」。週末與休市日顯示最近交易日。
均線日K採 Yahoo Finance 非官方資料，可能因連線限制而短暫缺漏；漲跌停以 MIS 當日公告價優先，只有推算價會加註「推估」。
若公司虧損或來源未提供本益比，顯示「—」而非 0。網頁不會在沒有人開啟時持續接收行情；重新打開會重新查詢。非投資建議。
</div>''', unsafe_allow_html=True)


live_board()

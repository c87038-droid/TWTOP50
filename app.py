"""台股市值前 50 大手機網頁。部署：Streamlit Community Cloud，入口 app.py。"""
from __future__ import annotations

from datetime import datetime
from html import escape
import threading
import time
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor

import streamlit as st

import market_data as md

st.set_page_config(
    page_title="台股市值前50大｜手機排行榜",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# 雙檔版本驗證：即使 GitHub 只更新 app.py，仍能顯示可理解的錯誤，而非 ImportError。
WEB_BUILD = "20261110-R22-MOBILE-FAST"
EXPECTED_DATA_BUILD = "20261110-R22-MOBILE-FAST"
REQUIRED = (
    "TOP", "CANDIDATES", "HistoryStore", "MisClient", "apply_mis", "csv_bytes",
    "dec_str", "enrich", "fetch_official", "fetch_pe_snapshot", "attach_pe",
    "is_after_close", "is_session", "now_tw",
    "fetch_official_index", "fetch_live_index", "resolve_index", "quote_quality", "index_quality", "fetch_backup_intraday", "apply_backup_quotes", "retain_verified_quotes", "fetch_licensed_snapshots", "merge_licensed_quotes",
)
missing = [name for name in REQUIRED if not hasattr(md, name)]
if not missing and getattr(md, "DATA_BUILD", None) != EXPECTED_DATA_BUILD:
    st.error("手機版 R22 需要同步更新 market_data.py，請勿只更新 app.py。")
    st.info("請將 R22 ZIP 中的 app.py、market_data.py 一起上傳到 GitHub 資料庫根目錄並 Commit changes。")
    st.stop()
if missing:
    st.error("GitHub 上的 app.py 與 market_data.py 不是同一個版本，網站暫時無法啟動。")
    st.markdown("**修復方法：**請把修正版的 `app.py` 和 `market_data.py` 兩個檔案一起覆蓋到 GitHub 資料庫的最外層，再按 `Commit changes`。")
    st.code("market_data.py 缺少：" + ", ".join(missing), language="text")
    st.stop()

(TOP, CANDIDATES, HistoryStore, MisClient, apply_mis, csv_bytes,
 dec_str, enrich, fetch_official, fetch_pe_snapshot, attach_pe,
 is_after_close, is_session, now_tw,
 fetch_official_index, fetch_live_index, resolve_index, quote_quality, index_quality, fetch_backup_intraday, apply_backup_quotes, retain_verified_quotes, fetch_licensed_snapshots, merge_licensed_quotes) = tuple(getattr(md, name) for name in REQUIRED)

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
.stock-row {display:grid;grid-template-columns:42px minmax(125px,1.1fr) minmax(115px,.82fr) minmax(105px,.80fr) minmax(153px,1fr) minmax(90px,.72fr) minmax(250px,1.9fr) minmax(165px,1.25fr);gap:10px;align-items:center;background:#fff;border:1px solid #e1e8f0;border-left:5px solid #c7d7e6;border-radius:12px;padding:11px 9px;box-shadow:0 1px 3px #142b4510;font-size:14px;color:#24374c}
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
.stock-row {grid-template-columns:37px minmax(125px,1.25fr) minmax(90px,.9fr) minmax(100px,.9fr);grid-template-areas:"rank identity price cap" "rank flags flags pe" "ma ma ma ma" "quote quote quote quote";column-gap:9px;row-gap:4px}
.stock-row .rank{grid-area:rank}.stock-row .identity{grid-area:identity}.stock-row .price{grid-area:price}.stock-row .cap{grid-area:cap}
.stock-row .flags{grid-area:flags}.stock-row .pe-inline{grid-area:pe}.stock-row .ma{grid-area:ma}.stock-row .info{grid-area:quote}
.stock-row .ma {display:flex;gap:12px;flex-wrap:wrap;padding-top:5px;border-top:1px solid #e1e8f0;margin-top:4px}
.stock-row .flags{display:flex;gap:10px;flex-wrap:wrap}
.stock-row .pe-inline{font-size:11px;letter-spacing:-.2px}
.stock-row .pe-inline strong{font-size:13px}
}
@media(max-width:560px) {
.block-container {padding-left:11px;padding-right:11px;padding-top:0.5rem}
.stock-row {grid-template-columns:30px minmax(80px,1fr) 95px;grid-template-areas:"rank identity price" "rank identity cap" "flags flags pe" "ma ma ma" "quote quote quote";padding:10px 8px;gap:5px}
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
    grid-template-areas:"rank identity price" "rank identity cap" "flags flags pe" "ma ma ma" "quote quote quote";
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

/* R10 稍加大字體：約 8–12%；不修改前 50 名、行情、本益比、均線或下載邏輯。 */
.board-title {font-size:clamp(32px,3.6vw,46px)}
.board-subtitle {font-size:17px}
.index-title {font-size:20px}
.index-level {font-size:clamp(41px,6.6vw,62px)}
.index-move {font-size:clamp(23px,3.9vw,32px)}
.index-note {font-size:15px}
.summarybox .metric-label {font-size:16px}
.summarybox .metric-value {font-size:26px}
.board-note {font-size:16px}
.stock-row {font-size:17px;padding:15px 12px;line-height:1.56}
.stock-head {font-size:15px}
.stock-row .rank {font-size:24px}
.stock-row .stock-code {font-size:20px}
.stock-row .stock-name {font-size:22px}
.stock-row .stock-market {font-size:15px}
.stock-row .price-value {font-size:27px}
.stock-row .change {font-size:16px}
.stock-row .pe-inline {font-size:16px}
.stock-row .pe-inline strong {font-size:20px}
.stock-row .cap {font-size:18px}
.stock-row .cap-label {font-size:15px}
.stock-row .ma {font-size:17px}
.stock-row .ma strong {font-size:17px}
.stock-row .flag, .stock-row .warn {font-size:17px}
.stock-row .info {font-size:14px}
div[data-testid="stButton"] button, div[data-testid="stDownloadButton"] button {font-size:17px}
@media (max-width:1040px){
 .stock-row .pe-inline {font-size:16px}
 .stock-row .pe-inline strong {font-size:19px}
}
@media (max-width:560px){
 .board-title {font-size:31px}
 .board-subtitle {font-size:16px}
 .index-level {font-size:39px}
 .index-move {font-size:23px}
 .index-note {font-size:14px}
 .summarybox .metric-label {font-size:15px}
 .summarybox .metric-value {font-size:21px}
 .stock-row {padding:14px 10px;gap:8px 6px}
 .stock-row .rank {font-size:21px}
 .stock-row .stock-name {font-size:21px}
 .stock-row .stock-code {font-size:18px}
 .stock-row .price-value {font-size:25px}
 .stock-row .change {font-size:15px}
 .stock-row .pe-inline {font-size:15px}
 .stock-row .pe-inline strong {font-size:18px}
 .stock-row .cap {font-size:16px}
 .stock-row .cap-label {font-size:13px}
 .stock-row .ma, .stock-row .ma strong {font-size:16px}
 .stock-row .flag, .stock-row .warn {font-size:16px}
 .stock-row .info {font-size:14px}
 .board-note {font-size:15px}
}


/* R11 排版優化：只有寬度／高度／間距；沿用 R10 所有字體大小與字型。 */
*, *::before, *::after {box-sizing:border-box}
.stock-list {width:100%;max-width:100%;gap:8px}
.stock-row {width:100%;max-width:100%;height:auto;min-height:0;box-sizing:border-box;overflow:visible;align-items:center}
.stock-row > div {min-width:0}
.stock-row .identity-line {max-width:100%}
.stock-row .stock-name {overflow-wrap:anywhere}
.stock-row .price, .stock-row .cap {min-width:0}
.stock-row .price-value {font-variant-numeric:tabular-nums}
.stock-row .ma span {white-space:nowrap;max-width:100%}
.summarybar {width:100%;max-width:100%}
.summarybox {min-width:0;height:auto}
.index-card {width:100%;max-width:100%;height:auto}
.index-main {min-width:0}
@media (min-width:1041px) {
  .stock-row:not(.stock-head) {grid-template-columns:35px minmax(135px,1.25fr) minmax(125px,1fr) minmax(110px,.75fr) minmax(125px,1fr) minmax(90px,.72fr) minmax(225px,1.6fr) minmax(145px,1.15fr);gap:9px;padding:12px 10px}
  .stock-head {grid-template-columns:35px minmax(135px,1.25fr) minmax(125px,1fr) minmax(110px,.75fr) minmax(125px,1fr) minmax(90px,.72fr) minmax(225px,1.6fr) minmax(145px,1.15fr);gap:9px;padding:10px}
}
@media (min-width:561px) and (max-width:1040px) {
  .stock-row {grid-template-columns:36px minmax(0,1.25fr) minmax(115px,.85fr) minmax(112px,.8fr);column-gap:10px;row-gap:6px;padding:11px 12px}
  .stock-row .ma {margin-top:3px;padding-top:4px;row-gap:3px}
  .stock-row .flags {gap:6px 12px}
}
@media (max-width:560px) {
  .block-container {width:100%;max-width:100%;padding-left:8px;padding-right:8px}
  .stock-list {gap:7px}
  .stock-row {
    grid-template-columns:29px minmax(0,1fr) minmax(104px,max-content);
    grid-template-areas:
      "rank identity price"
      "rank identity cap"
      "flags flags pe"
      "ma ma ma"
      "quote quote quote";
    column-gap:7px;row-gap:5px;
    padding:10px 9px;
    border-radius:11px;
    align-items:start;
  }
  .stock-row .rank {align-self:start}
  .stock-row .identity-line {gap:4px 6px;align-content:start}
  .stock-row .stock-market {margin-top:2px}
  .stock-row .price,.stock-row .cap {justify-self:end;text-align:right;max-width:100%}
  .stock-row .change,.stock-row .pe-inline,.stock-row .cap-label {margin-top:2px}
  .stock-row .cap-label {margin-left:4px}
  .stock-row .flags {display:flex;gap:2px 12px;align-items:center;flex-wrap:wrap}
  .stock-row .ma {display:flex;gap:3px 14px;justify-content:flex-start;align-items:center;flex-wrap:wrap;padding-top:5px;margin-top:1px;border-top:1px solid #e1e8f0}
  .stock-row .info {margin-top:1px;overflow-wrap:anywhere}
  .summarybar {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px;margin:9px 0}
  .summarybox {width:100%;min-width:0;padding:9px 10px}
  .index-card {padding:12px 13px;margin:10px 0}
  .index-main {gap:4px 10px}
  .board-note {margin:6px 0 9px}
}
@media (max-width:345px) {
  .block-container {padding-left:6px;padding-right:6px}
  .stock-row {
    grid-template-columns:27px minmax(0,1fr) minmax(0,1fr);
    grid-template-areas:
      "rank identity identity"
      "price price cap"
      "flags flags pe"
      "ma ma ma"
      "quote quote quote";
    padding:9px 8px;
    column-gap:6px;row-gap:5px;
  }
  .stock-row .price {justify-self:start;text-align:left}
  .stock-row .cap {justify-self:end;text-align:right}
  .stock-row .cap-label {display:block;margin-left:0}
  .stock-row .ma {column-gap:12px}
}

/* R20：本益比是獨立欄，位於漲跌停／警示右側；不更動字型字級。 */
.stock-row .pe-inline {min-width:0;max-width:100%;overflow-wrap:normal;line-height:1.5}
@media (max-width:1040px) {
  .stock-row .pe-inline {align-self:center;justify-self:end;margin-top:0;text-align:right}
}
@media (max-width:560px) {
  .stock-row .pe-inline {align-self:start;white-space:normal;overflow-wrap:anywhere}
}
/* R13 短期均線標示：字型、字級維持 R12；只增加顏色及底色。 */
.stock-row .ma span.ma5-hit {background:#e0ecff;border:1px solid #98baf3;color:#164b99;border-radius:7px;padding:1px 6px;font-weight:800}
.stock-row .ma span.ma20-hit {background:#dff8ee;border:1px solid #87cbb7;color:#086855;border-radius:7px;padding:1px 6px;font-weight:800}
.stock-row .ma span.ma5-hit strong {color:#164b99}
.stock-row .ma span.ma20-hit strong {color:#086855}
.stock-row.ma-short5:not(.limit-up):not(.limit-down):not(.ma-half):not(.ma-year):not(.ma-both) {border-left-color:#4b83c9;background:#f0f6ff}
.stock-row.ma-short20:not(.limit-up):not(.limit-down):not(.ma-half):not(.ma-year):not(.ma-both) {border-left-color:#28a38c;background:#edfdf7}
.stock-row .warn {overflow-wrap:anywhere}
</style>
""", unsafe_allow_html=True)


def get_licensed_key():
    """Keys belong only in Streamlit Secrets; do not paste into GitHub."""
    key = os.environ.get('FUGLE_API_KEY', '').strip()
    if key: return key
    try:
        return str(st.secrets.get('FUGLE_API_KEY', '')).strip()
    except Exception:
        return ''


class AsyncQuoteFeed:
    """Background I/O with last-good snapshots; never block a fragment rerun.

    A completed fetch updates the in-memory snapshot; pending / failed jobs
    preserve existing values but do not change their *source timestamps*.
    """
    def __init__(self):
        self.pool = ThreadPoolExecutor(max_workers=7, thread_name_prefix="top50-mobile")
        self.lock = threading.RLock()
        self.slots = {}

    def request(self, name, fetcher, ttl=15, retry=30):
        now = time.monotonic()
        with self.lock:
            slot = self.slots.setdefault(name, {
                "value": None, "future": None, "completed": 0.0,
                "checked": 0.0, "error": "", "duration": None,
            })
            future = slot["future"]
            if future is not None and future.done():
                slot["future"] = None
                slot["checked"] = now
                try:
                    payload, elapsed = future.result()
                    slot["value"] = payload
                    slot["completed"] = now
                    slot["duration"] = elapsed
                    slot["error"] = ""
                except Exception as exc:
                    slot["error"] = str(exc)[:125]
            if slot["future"] is None:
                interval = ttl if slot["completed"] >= slot["checked"] and slot["completed"] else retry
                if not slot["checked"] or (now-slot["checked"] >= interval):
                    def run():
                        started = time.monotonic()
                        return fetcher(), time.monotonic()-started
                    slot["future"] = self.pool.submit(run)
                    slot["checked"] = now
            return slot["value"], slot["future"] is not None, slot["error"]

    def invalidate(self):
        with self.lock:
            for slot in self.slots.values():
                slot["completed"] = 0
                slot["checked"] = 0

    def summary(self):
        with self.lock:
            entries=[]
            for key, slot in self.slots.items():
                state = "抓取中" if slot["future"] is not None else "已取得" if slot["value"] is not None else "尚未取得"
                if slot["error"]:
                    state += "／失敗：" + slot["error"][:75]
                if slot["duration"] is not None:
                    state += f"（上次成功耗時 {slot['duration']:.1f} 秒）"
                entries.append(f"{key}：{state}")
            return entries


@st.cache_resource(show_spinner=False)
def quote_feed():
    return AsyncQuoteFeed()


def get_licensed_today():
    key = get_licensed_key()
    if not key:
        return {}, None, []
    digest = hashlib.sha256(key.encode()).hexdigest()[:12]
    result, pending, error = quote_feed().request(
        "授權行情_" + digest, lambda: fetch_licensed_snapshots(key), ttl=15, retry=45)
    if result is not None:
        return result
    return {}, None, ["授權行情" + ("連線中" if pending else ": " + error)]


def index_card(at):
    """獨立顯示大盤：排行／本益比即使出錯也不影響大盤資訊。"""
    close = live = None
    issues = []
    feed = quote_feed()
    close, waiting_close, error_close = feed.request(
        "大盤_官方收盤", fetch_official_index,
        ttl=120 if is_after_close(at) else 1800, retry=35)
    if error_close:
        issues.append("官方收盤來源：" + error_close[:90])
    # 盤中獨立查詢，慢速官方資料不會擋住大盤或個股畫面。
    if is_session(at):
        live, waiting_live, error_live = feed.request(
            "大盤_盤中", fetch_live_index, ttl=15, retry=25)
        if error_live:
            issues.append("盤中來源：" + error_live[:90])
    status = resolve_index(close, live, at)
    if get_licensed_key() and is_session(at):
        _, licensed_index, license_warnings = get_licensed_today()
        if licensed_index and licensed_index['day'] == at.date():
            # Prefer verified current-session index over old official close.
            if not (close and close['day'] == at.date()):
                status = licensed_index
        elif is_session(at):
            issues.extend(license_warnings[:2])
    if not status:
        st.warning("加權指數正在背景讀取；資料尚未取得時不會顯示猜測值。" + ("；".join(issues)[:160] if issues else ""))
        return
    delta = status["delta"]
    pct = status["pct"]
    colour = "index-up" if delta is not None and delta > 0 else "index-down" if delta is not None and delta < 0 else "index-flat"
    mark = "▲" if delta is not None and delta > 0 else "▼" if delta is not None and delta < 0 else "—"
    movement = f"{mark} {abs(delta):,.2f} 點" if delta is not None else "漲跌待確認"
    percent = f"{pct:+.2f}%" if pct is not None else "—"
    index_label, index_age, _index_valid, index_recent = index_quality(status, at)
    stamp = f"{status['day']:%Y-%m-%d} {status['time']}"
    st.markdown(f"""<section class="index-card" aria-label="台股加權股價指數">
    <div class="index-title">🇹🇼 台股加權指數（TAIEX）</div>
    <div class="index-main"><span class="index-level">{status['value']:,.2f}</span>
    <span class="index-move {colour}">{movement}　{percent}</span></div>
    <div class="index-note">{escape(index_label)} · {escape(stamp)} · {escape(status['source'])} · 台灣時間</div>
    </section>""", unsafe_allow_html=True)
    if is_after_close(at) and close and close["day"] < at.date():
        st.warning(f"盤後官方加權指數尚未同步至 {at:%Y-%m-%d}；目前顯示 {close['day']} 的歷史收盤，並非今日收盤。若今天休市，則此資料可能就是最近交易日收盤。")
    if is_session(at) and not index_recent:
        st.error(f"⚠ 大盤指數不是已驗證的20分鐘內行情：{index_label}。畫面查詢時間不等於指數報價時間。")
    if issues and is_session(at):
        st.warning("大盤行情查詢診斷：" + "；".join(issues)[:420])
    if issues and close and (not live or close["day"] < at.date()) and is_session(at):
        st.caption("⚠️ 盤中大盤來源若只有前一交易日資料，會顯示歷史收盤；不能當成今天的指數。")


@st.cache_resource(show_spinner=False)
def resources():
    return {"hist": HistoryStore(), "lock": threading.Lock(),
            "last_official": None, "last_top50": None, "last_top50_at": None,
            "last_pe_map": {}, "last_verified_quotes": {}}


def build_board(state, at):
    warnings = []
    feed = quote_feed()
    # 正式收盤資料比盤中報價慢，而且只在盤後變動：獨立背景更新。
    official_ttl = 150 if is_after_close(at) else (1800 if is_session(at) else 3600)
    official, waiting_official, error_official = feed.request(
        "全市場_官方收盤_" + str(at.date()), fetch_official,
        ttl=official_ttl, retry=45)
    if official is not None:
        with state["lock"]:
            state["last_official"] = official
    else:
        with state["lock"]:
            official = state["last_official"]
        if official is None:
            raise RuntimeError("正在背景讀取全市場正式收盤資料，尚未取得可顯示的名單。請保持網頁開啟；" +
                               ("連線異常：" + error_official if error_official else "來源讀取中"))
    if error_official:
        warnings.append("官方全市場資料暫時未成功更新：" + error_official + "；已明確保留原始行情日期。")

    for issue in official.get("source_errors", []):
        warnings.append("⚠ 指定日期來源：" + issue)
    base = official["records"]
    if not official["synchronized"]:
        warnings.append("上市／上櫃官方收盤日期尚未同步，目前為跨日期參考排名，非正式收盤排名。")
    mode = ("最近取得的官方收盤（歷史資料）" if official["synchronized"] and
            max(official["listed_date"], official["otc_date"]) < at.date() else
            "正式收盤價" if official["synchronized"] else "日期未同步參考價")
    fresh = 0
    universe = base
    last_date = max(official["listed_date"], official["otc_date"])
    # 盤中：用免費 MIS / 備援行情；盤後：一律回到 TWSE+TPEx 官方收盤資料。
    if is_session(at):
        candidates = base[:CANDIDATES]
        # 200檔盤中報價獨立在背景取回；每15秒可啟動新一輪，
        # 不等待慢速官方 / 本益比 / 備援抓取，也不因網路卡住而凍結網頁。
        messages_pack, waiting_mis, error_mis = feed.request(
            "個股_MIS_" + str(at.date()),
            lambda snapshot=[dict(r) for r in candidates]: MisClient().fetch(snapshot),
            ttl=15, retry=25)
        if messages_pack is not None:
            messages, partial_errors = messages_pack
            universe, fresh = apply_mis(candidates, messages, at)
            if partial_errors:
                warnings.append(f"MIS 有 {len(partial_errors)} 組失敗，其餘成功報價已採用。" + "；".join(partial_errors[:2]))
            if fresh:
                mode = "盤中已取得成交價估算（請看成交時間）"
        else:
            warnings.append("MIS 盤中報價正在背景抓取；目前顯示的舊價格仍以原始交易時間為準。")
        if error_mis:
            warnings.append("MIS 報價查詢失敗：" + error_mis)
        # Avoid showing a yesterday close with an apparently new refresh time.
        # Backup is a delayed minute feed: never describe it as exchange live ticks.
        if fresh < 20:
            backup, waiting_backup, backup_error = feed.request(
                "個股_備援分鐘行情_" + str(at.date()),
                lambda snapshot=[dict(r) for r in candidates[:60]], when=at: fetch_backup_intraday(
                    snapshot, when, max_symbols=60),
                ttl=180, retry=90)
            if backup is not None:
                universe, backup_count = apply_backup_quotes(universe, backup, at)
                if backup_count:
                    mode = "盤中備援分鐘行情（可能延遲）"
                    warnings.append(f"MIS 報價不足，已引用 {backup_count} 檔帶時間戳記的備援分鐘行情。")
            if backup_error:
                warnings.append("備援分鐘行情來源連線失敗：" + backup_error)
        if get_licensed_key():
            live_quotes, licensed_index, licensed_warnings = get_licensed_today()
            universe, count_licensed = merge_licensed_quotes(universe, live_quotes, at)
            if count_licensed:
                mode = '授權盤中行情快照' if is_session(at) else '授權盤後行情參考'
            else:
                warnings.append('授權來源未取得今天的有效股價，不能視為已成功更新。')
            warnings.extend(licensed_warnings[:2])
        with state["lock"]:
            universe = retain_verified_quotes(universe, state["last_verified_quotes"], at)
        fresh = sum(r["quote_day"] == at.date() and r.get("source") in
                    ("今日最新成交", "備援分鐘行情（可能延遲）", "授權行情快照（富果）") for r in universe)

    if is_after_close(at) and last_date < at.date():
        mode = f"盤後等待今日正式收盤（目前 {last_date} 歷史收盤）"
        warnings.append("盤後不使用盤中最後成交價替代正式收盤。若今天有開市，請等證交所與櫃買中心資料同步後再按『立即重新整理』。")
    elif is_after_close(at) and not official["synchronized"]:
        warnings.append("盤後上市與上櫃官方收盤日期不同，現在是跨日參考名單，不是正式前50名。")
    top = universe[:TOP]
    if len(top) < TOP:
        raise RuntimeError(f"本次有效股票只有 {len(top)} 檔，不足 50。")
    pe_result, pe_waiting, pe_error = feed.request(
        "本益比_官方", fetch_pe_snapshot, ttl=1800, retry=90)
    if pe_result is not None:
        pe_map, pe_warnings = pe_result
        if pe_map:
            with state["lock"]:
                state["last_pe_map"].update(pe_map)
        warnings.extend(pe_warnings)
    if pe_error:
        warnings.append("本益比來源稍後重試：" + pe_error)
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
    if row.get("ma5_alert"): css.append("ma-short5")
    if row.get("ma20_alert"): css.append("ma-short20")
    if row["half_alert"] and row["year_alert"]: css.append("ma-both")
    elif row["year_alert"]: css.append("ma-year")
    elif row["half_alert"]: css.append("ma-half")
    css = " ".join(css)
    quality_text = str(row.get("quality_status") or "尚未驗證")
    meta = escape(f"{row['quote_day']} {row['quote_time']} · {quality_text} · {row['source']} · {row['ma_state']}{pe_time}")
    return f'''<div class="stock-row {css}">
<div class="rank">{row['rank']}</div>
<div class="identity"><div class="identity-line"><span class="stock-code" aria-label="股票代碼 {code}">{code}</span><span class="stock-name">{name}</span></div><div class="stock-market">{market}</div></div>
<div class="price"><div class="price-value">{fmt(row['price'])}</div><div class="change {change_class}">{pct} ({delta})</div></div>
<div class="cap">{fmt(row['cap'],1)}<div class="cap-label">億元市值</div></div>
<div class="flags"><div class="flag {'up' if '漲停' in row['limit'] else 'down' if '跌停' in row['limit'] else 'plain'}">{text_limit}</div><div class="warn">{alert}</div></div>
<div class="pe-inline">本益比 <strong>{pe}</strong></div>
<div class="ma"><span class="{'ma5-hit' if row.get('ma5_alert') else ''}"><strong>{'⚠ ' if row.get('ma5_alert') else ''}5日線</strong> {fmt(row['ma5'])}</span><span class="{'ma20-hit' if row.get('ma20_alert') else ''}"><strong>{'⚠ ' if row.get('ma20_alert') else ''}20日線</strong> {fmt(row['ma20'])}</span><span><strong>季線</strong> {fmt(row['ma60'])}</span><span><strong>半年線</strong> {fmt(row['ma120'])}</span><span><strong>年線</strong> {fmt(row['ma240'])}</span></div>
<div class="info">{meta}</div>
</div>'''


st.markdown('<div class="board-title">📈 台股市值 TOP 50｜大盤指數＋本益比</div><div class="board-subtitle">上市＋上櫃 · 單頁 50 名 · 盤中／盤後 · 官方收盤本益比 · 五條均線 · 大盤漲跌 · R22 背景抓取快速更新版（保留本益比右移）</div>', unsafe_allow_html=True)
st.caption("免費資料顯示｜查詢時間 ≠ 成交時間；人工交叉核對：[HiStock 台股排行](https://histock.tw/stock/rank.aspx)（不作為自動抓取來源）。")


@st.fragment(run_every="10s")
def live_board():
    state = resources()
    at = now_tw()
    index_card(at)
    if is_session(at):
        st.caption("🟠 盤中模式｜09:00–13:30｜優先取得最新成交價；免費來源可能延遲，須以各檔成交時間為準。")
    elif is_after_close(at):
        st.caption("🔵 盤後模式｜13:30 後只使用官方收盤資料。若尚未公布當日收盤，會顯示最近交易日與等待更新提醒。")
    else:
        st.caption("🔵 非交易時段｜顯示最近交易日官方收盤資料。")
    if get_licensed_key():
        st.caption('行情模式：已設定授權來源；以有當日交易日期的快照為優先，連線失敗會顯示原因。')
    elif is_session(at):
        st.info('免費行情查核模式：畫面每15秒嘗試查詢，並不代表股價每15秒更新；每檔價格均會標示實際資料日期和可核對的成交時間。')
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
    for r in records:
        r["quality_status"], r["quality_lag"], r["quality_dated"], r["quality_recent"] = quote_quality(r, at)
    recent_count = sum(1 for r in records if r["quality_recent"])
    dated_count = sum(1 for r in records if r["quality_dated"])
    historical_count = sum(1 for r in records if r["quote_day"] < at.date())
    carried = sum("沿用當日已取得成交" in r.get("source", "") for r in records)
    ma_ready = sum(1 for r in records if r["ma120"] is not None and r["ma240"] is not None)
    alert_count = sum(1 for r in records if r["half_alert"] or r["year_alert"] or r.get("ma5_alert") or r.get("ma20_alert"))
    limit_count = sum(1 for r in records if "漲停" in r["limit"] or "跌停" in r["limit"])
    st.markdown(
        '<div class="summarybar">'
        f'<div class="summarybox"><span class="metric-label">目前模式</span><span class="metric-value">{escape(mode)}</span></div>'
        f'<div class="summarybox"><span class="metric-label">市值排名</span><span class="metric-value">{len(records)} / 50</span></div>'
        f'<div class="summarybox"><span class="metric-label">均線警示</span><span class="metric-value">{alert_count} 檔</span></div>'
        f'<div class="summarybox"><span class="metric-label">均線已備齊</span><span class="metric-value">{ma_ready} / 50</span></div>'
        '</div>', unsafe_allow_html=True)
    valid_today = [r for r in records if r["quote_day"] == at.date() and r.get("source") in
                   ("今日最新成交", "備援分鐘行情（可能延遲）", "授權行情快照（富果）")]
    newest_time = max((r["quote_time"] for r in valid_today if r.get("quote_time")), default="無")
    st.caption(f"網頁查詢時間（不是成交時間）：{now_tw():%Y-%m-%d %H:%M:%S} · 資料交易日：{'、'.join(trade_days)} · 當日有成交時間：{dated_count}/50 · 20分鐘內報價：{recent_count}/50 · 歷史資料：{historical_count}/50 · 漲跌停／推估：{limit_count} 檔")
    if is_session(at) and recent_count < len(records):
        st.error(f"⚠ 今日仍有 {len(records)-recent_count} 檔未取得20分鐘內可驗證報價，不能把舊價視為最新。請看每檔股票最下方的行情驗證狀態。")
    if is_session(at) and not valid_today:
        st.error("本輪尚未取得今日新成交價！部分股票可能沿用今天先前已取得的價格，其餘為舊收盤資料，不能視為即時行情。")
    elif is_session(at) and newest_time != "無":
        try:
            quote_at = datetime.combine(at.date(), datetime.strptime(newest_time[:8], "%H:%M:%S").time(), tzinfo=at.tzinfo)
            if (at - quote_at).total_seconds() > 900:
                st.warning(f"行情較舊：前50名最近一筆有效成交在 {newest_time}，距目前超過15分鐘，請注意資料延遲。")
        except (ValueError, TypeError):
            pass

    for warning in warnings:
        st.warning(warning, icon="⚠️")
    with st.expander("🩺 行情來源檢查／沒有更新怎麼辦", expanded=False):
        st.write(f"網站伺服器現在時間（台灣）：{at:%Y-%m-%d %H:%M:%S}")
        st.write(f"前50名20分鐘內有效報價：{recent_count}/50；沿用當日先前報價：{carried} 檔；最近成交時間：{newest_time}")
        st.write("若20分鐘內有效報價為0/50，代表無法驗證近20分鐘成交價。免費公開來源不保證連線與更新頻率；請查看資料交易日與實際成交時間。")
        if warnings:
            st.code("\n".join(warnings[:6]), language="text")
        st.caption("背景查詢狀態（耗時是網站抓取時間，不是成交延遲）：")
        for item in quote_feed().summary():
            st.text(item)
    col_search, col_filter = st.columns([2, 1], gap="small")
    with col_search:
        search = st.text_input("搜尋股票", placeholder="輸入代號或公司名稱（預設顯示 50 名）", key="stock_filter")
    with col_filter:
        selected = st.selectbox("快速篩選", ["全部50名", "≤5日線", "≤20日線", "同時≤5＋20日線", "≤半年線", "≤年線", "同時≤半年＋年線", "漲停", "跌停", "均線資料不足"], key="alert_filter")

    visible = []
    for r in records:
        if search and search.strip().lower() not in (r["code"]+r["name"]).lower():
            continue
        if selected == "≤5日線" and r.get("ma5_alert") is not True: continue
        if selected == "≤20日線" and r.get("ma20_alert") is not True: continue
        if selected == "同時≤5＋20日線" and not (r.get("ma5_alert") and r.get("ma20_alert")): continue
        if selected == "≤半年線" and r["half_alert"] is not True: continue
        if selected == "≤年線" and r["year_alert"] is not True: continue
        if selected == "同時≤半年＋年線" and not (r["half_alert"] and r["year_alert"]): continue
        if selected == "漲停" and "漲停" not in r["limit"]: continue
        if selected == "跌停" and "跌停" not in r["limit"]: continue
        if selected == "均線資料不足" and r["ma120"] is not None and r["ma240"] is not None: continue
        visible.append(r)

    tool1, tool2 = st.columns([1, 1], gap="small")
    with tool1:
        st.download_button("⬇️ 下載完整 50 名 CSV", data=csv_bytes(records, now_tw()),
                           file_name=f"台股市值前50大_{now_tw():%Y%m%d_%H%M}.csv", mime="text/csv",
                           use_container_width=True, key="csv_all")
    with tool2:
        if st.button("🔄 立即重新整理", use_container_width=True, key="manual_refresh"):
            quote_feed().invalidate()
            st.rerun(scope="fragment")
    st.markdown(f'<div class="board-note">顯示 <strong>{len(visible)}</strong> 檔（完整排名固定 1～50；篩選不會重新編號）。紅色＝漲停、綠色＝跌停、藍色＝≤5日線、青綠色＝≤20日線、黃色＝≤半年線、紫色＝≤年線、橘色＝同時≤半年＋年線。<br>本益比取 TWSE／TPEx 官方最近收盤估值（非盤中即時，日期以各檔顯示為準）。均線使用 5／20／60／120／240 個交易日的未還原收盤價；盤中包含目前顯示股價作為當日價格。資料不足時顯示「—」，不會以 0 代替。</div>', unsafe_allow_html=True)

    if visible:
        header = '''<div class="stock-row stock-head"><div>名次</div><div>股票代碼／公司名稱</div><div>股價</div><div>市值</div><div>漲跌停／警示</div><div>本益比</div><div>5／20／季／半年／年線</div><div>資料時間</div></div>'''
        st.markdown('<div class="stock-list">'+header+''.join(stock_html(r) for r in visible)+'</div>', unsafe_allow_html=True)
    else:
        st.info("目前沒有符合篩選條件的股票，請改選『全部50名』。")

    st.markdown('''<div class="board-note" style="margin-top:20px">
<b>資料使用說明：</b>盤中每 15 秒<strong>嘗試</strong>抓取新資料，畫面每 10 秒檢查完成結果，未必為零延遲逐筆成交；盤中從最近正式收盤市值前 200 名中估算前 50 名。
盤後優先使用 TWSE／TPEx 全市場正式收盤資料；尚未發布時會明示「待官方確認」。週末與休市日顯示最近交易日。
均線日K採 Yahoo Finance 非官方資料，可能因連線限制而短暫缺漏；漲跌停以 MIS 當日公告價優先，只有推算價會加註「推估」。
若公司虧損或來源未提供本益比，顯示「—」而非 0。網頁不會在沒有人開啟時持續接收行情；重新打開會重新查詢。非投資建議。
</div>''', unsafe_allow_html=True)


live_board()

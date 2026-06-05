import os
import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
from fredapi import Fred
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="Economic Dashboard", layout="wide")
st.title("📊 Economic Dashboard")
st.caption(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

# ── FRED API setup ────────────────────────────────────
FRED_API_KEY = os.getenv("FRED_API_KEY")
fred = Fred(api_key=FRED_API_KEY)

# ── 한국부동산원 API key (data.go.kr) ─────────────────
REB_API_KEY = os.getenv("REB_API_KEY")

@st.cache_data(ttl=3600)
def get_fred_data(series_id, start_date=None, end_date=None):
    try:
        data = fred.get_series(series_id, observation_start=start_date, observation_end=end_date)
        return data.dropna()
    except Exception as e:
        st.warning(f"FRED fetch failed [{series_id}]: {e}")
        return None

@st.cache_data(ttl=3600)
def get_data(ticker, period):
    try:
        df = yf.download(ticker, period=period, auto_adjust=False, progress=False)
        if df.empty:
            return None
        col = 'Adj Close' if 'Adj Close' in df.columns else 'Close'
        close = df[col]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        return close.dropna()
    except Exception:
        return None

@st.cache_data(ttl=3600)
def get_data_batch(tickers: tuple, period: str) -> dict:
    """Download multiple tickers in parallel; returns {ticker: Series}."""
    def _fetch(t):
        return t, get_data(t, period)
    results = {}
    with ThreadPoolExecutor(max_workers=min(len(tickers), 6)) as ex:
        futures = {ex.submit(_fetch, t): t for t in tickers}
        for fut in as_completed(futures):
            ticker, data = fut.result()
            results[ticker] = data
    return results

@st.cache_data(ttl=3600)
def get_data_range(ticker, start_date, end_date):
    try:
        df = yf.download(ticker, start=start_date, end=end_date,
                         auto_adjust=False, progress=False)
        if df.empty:
            return None
        col = 'Adj Close' if 'Adj Close' in df.columns else 'Close'
        close = df[col]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        return close.dropna()
    except Exception:
        return None

@st.cache_data(ttl=3600)
def get_data_batch_range(tickers: tuple, start_date, end_date) -> dict:
    def _fetch(t):
        return t, get_data_range(t, start_date, end_date)
    results = {}
    with ThreadPoolExecutor(max_workers=min(len(tickers), 6)) as ex:
        futures = {ex.submit(_fetch, t): t for t in tickers}
        for fut in as_completed(futures):
            ticker, data = fut.result()
            results[ticker] = data
    return results

# ── Apartment price index via 한국부동산원 API ──────────
@st.cache_data(ttl=3600)
def get_apt_price_index(service_key: str, start_ym: str, end_ym: str):
    """
    Fetch monthly apartment price index from R-ONE (한국부동산원).
    URL : https://www.reb.or.kr/r-one/openapi/SttsApiTbl.do
    매매 STATBL_ID=A_2024_00045 / 전세 STATBL_ID=A_2024_00050
    ITEM_CD2=100001, ITEM_CD: 전국=500001 서울=500008 지방권=500003
    Returns: (deal_dict, rent_dict, endpoint_url | None)
    """
    BASE_URL    = "https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do"
    TIMEOUT     = 10
    STATBL_DEAL = "A_2024_00045"
    STATBL_RENT = "A_2024_00050"
    ITEM_CD2    = "100001"
    region_map  = {"전국": 500001, "수도권": 500002, "지방권": 500003, "서울": 500008}

    def _fetch_rows(statbl_id: str, item_cd: str) -> list:
        """Request one (STATBL_ID, ITEM_CD) combination; return row list."""
        params = {
            "KEY":            service_key,
            "STATBL_ID":      statbl_id,
            "ITEM_CD2":       ITEM_CD2,
            "CLS_ID":         item_cd,
            "Type":           "json",
            "pIndex":         1,
            "pSize":          200,
            "DTACYCLE_CD":    "MM",
            "START_WRTTIME":  start_ym,
            "END_WRTTIME":    end_ym,
        }
        try:
            r = requests.get(BASE_URL, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            j = r.json()

            # R-ONE JSON wraps data as: {"SttsApiTblData": [{"head":[...]}, {"row":[...]}]}
            # or as a bare list: [{"head":[...]}, {"row":[...]}]
            wrapper = j.get("SttsApiTblData") if isinstance(j, dict) else j
            if isinstance(wrapper, list):
                for block in wrapper:
                    rows = block.get("row")
                    if rows is not None:
                        return rows if isinstance(rows, list) else [rows]

            # Fallback: standard response envelope
            items = (j.get("response", {})
                      .get("body", {})
                      .get("items", {})
                      .get("item", []))
            return items if isinstance(items, list) else [items]
        except Exception:
            return []

    def _to_series(rows: list) -> "pd.Series | None":
        """Parse row list → pd.Series indexed by month, filtered to [start_ym, end_ym]."""
        dates, vals = [], []
        for row in rows:
            # Period field: WRTTIME_IDTFR_ID (YYYYMM) is the actual R-ONE field
            ym_raw = (row.get("WRTTIME_IDTFR_ID") or row.get("PRD_DE") or row.get("BASE_YM")
                      or row.get("STDR_YM") or row.get("yearMonth") or row.get("YM") or "")
            val_raw = (row.get("DTA_VAL") or row.get("INDX_VAL") or row.get("VAL")
                       or row.get("DATA_VALUE") or row.get("priceIndex") or "")
            if not ym_raw or not val_raw:
                continue
            ym_str = str(ym_raw).replace("-", "").strip()[:6]
            if not (start_ym <= ym_str <= end_ym):
                continue
            try:
                dates.append(pd.to_datetime(ym_str, format="%Y%m"))
                vals.append(float(str(val_raw).replace(",", "")))
            except Exception:
                pass
        if not dates:
            return None
        return pd.Series(vals, index=pd.DatetimeIndex(dates)).sort_index()

    deal_dict: dict = {}
    rent_dict: dict = {}

    for region_name, item_cd in region_map.items():
        rows = _fetch_rows(STATBL_DEAL, item_cd)
        s = _to_series(rows)
        if s is not None and not s.empty:
            deal_dict[region_name] = s

        rows = _fetch_rows(STATBL_RENT, item_cd)
        s = _to_series(rows)
        if s is not None and not s.empty:
            rent_dict[region_name] = s

    if deal_dict or rent_dict:
        return deal_dict, rent_dict, BASE_URL
    return {}, {}, None

# ── Period selectors (per phase) ──────────────────────
_OPTIONS    = ["1mo", "3mo", "6mo", "1y", "2y", "5y"]
_period_map = {"1mo": 1, "3mo": 3, "6mo": 6, "1y": 12, "2y": 24, "5y": 60}
fred_end    = datetime.now()

period_p1 = st.sidebar.selectbox("📌 Phase 1 — Global",   _OPTIONS, index=3)  # default 1y
period_p2 = st.sidebar.selectbox("📌 Phase 2 — US Macro", _OPTIONS, index=4)  # default 2y
period_p3 = st.sidebar.selectbox("📌 Phase 3 — Korea",    _OPTIONS, index=3)  # default 1y

_months_back_p1 = _period_map[period_p1]
_months_back_p2 = _period_map[period_p2]
_months_back_p3 = _period_map[period_p3]

fred_start_p2 = fred_end - timedelta(days=_months_back_p2 * 30)

# ── Sidebar: Master Chart controls ───────────────────
st.sidebar.markdown("---")
with st.sidebar.expander("📊 Master Chart", expanded=False):
    mc_range_mode = st.radio("기간 설정", ["프리셋", "직접 입력"],
                             horizontal=True, key="mc_range_mode")
    if mc_range_mode == "프리셋":
        mc_period = st.select_slider(
            "기간 선택",
            options=["1mo", "3mo", "6mo", "1y", "2y", "3y", "5y", "7y",
                     "10y", "15y", "20y", "30y", "max"],
            value="2y", key="mc_period",
        )
        mc_custom_start = mc_custom_end = None
    else:
        mc_period = "custom"
        _now = datetime.now().date()
        _dr  = st.date_input(
            "날짜 범위",
            value=(_now.replace(year=_now.year - 2), _now),
            min_value=datetime(1990, 1, 1).date(),
            max_value=_now,
            key="mc_date_range",
        )
        if isinstance(_dr, (list, tuple)) and len(_dr) == 2:
            mc_custom_start, mc_custom_end = _dr
        else:
            mc_custom_start = _now.replace(year=_now.year - 2)
            mc_custom_end   = _now
    st.markdown("---")
    mc_recession = st.checkbox("📍 경기침체 구간 표시 (USREC)", value=True, key="mc_recession")
    st.markdown("**시리즈 선택**")

    st.caption("💱 환율")
    mc_usdkrw  = st.checkbox("USD/KRW",              value=True,  key="mc_usdkrw")
    mc_eurkrw  = st.checkbox("EUR/KRW",              value=False, key="mc_eurkrw")
    mc_usdjpy  = st.checkbox("USD/JPY (엔화)",        value=False, key="mc_usdjpy")
    mc_dxy     = st.checkbox("DXY 달러 인덱스",       value=False, key="mc_dxy")

    st.caption("🥇 원자재")
    mc_gold    = st.checkbox("Gold Price",            value=True,  key="mc_gold")
    mc_silver  = st.checkbox("Silver Price",          value=False, key="mc_silver")
    mc_ratio   = st.checkbox("Gold/Silver Ratio",     value=False, key="mc_ratio")
    mc_cugold  = st.checkbox("Copper/Gold (경기기대)", value=False, key="mc_cugold")
    mc_wti     = st.checkbox("WTI Oil",               value=False, key="mc_wti")
    mc_copper  = st.checkbox("Copper (닥터 구리)",    value=False, key="mc_copper")
    mc_natgas  = st.checkbox("Natural Gas",           value=False, key="mc_natgas")

    st.caption("🌏 글로벌 지수")
    mc_sp500   = st.checkbox("S&P 500",               value=True,  key="mc_sp500")
    mc_nasdaq  = st.checkbox("NASDAQ",                value=False, key="mc_nasdaq")
    mc_sox     = st.checkbox("SOX 반도체지수",         value=False, key="mc_sox")
    mc_nikkei  = st.checkbox("Nikkei 225 (일본)",     value=False, key="mc_nikkei")
    mc_dax     = st.checkbox("DAX (독일/유럽)",        value=False, key="mc_dax")
    mc_sse     = st.checkbox("Shanghai (중국)",        value=False, key="mc_sse")
    mc_vix     = st.checkbox("VIX 공포지수",          value=False, key="mc_vix")
    mc_btc     = st.checkbox("Bitcoin",               value=False, key="mc_btc")

    st.caption("🇰🇷 한국 지수")
    mc_kospi   = st.checkbox("KOSPI",                 value=True,  key="mc_kospi")
    mc_kosdaq  = st.checkbox("KOSDAQ",                value=False, key="mc_kosdaq")
    mc_samsung = st.checkbox("삼성전자",               value=False, key="mc_samsung")

    st.caption("📊 채권 & 금리")
    mc_us10y   = st.checkbox("US 10Y Yield",          value=False, key="mc_us10y")
    mc_us30y   = st.checkbox("US 30Y Yield",          value=False, key="mc_us30y")
    mc_yldcrv  = st.checkbox("Yield Curve 10Y-2Y",    value=False, key="mc_yldcrv")
    mc_fedrate = st.checkbox("Fed Funds Rate",         value=False, key="mc_fedrate")

    st.caption("⚠️ 신용 스프레드")
    mc_hy_spread = st.checkbox("HY Spread (고위험채권)", value=False, key="mc_hy_spread")
    mc_ig_spread = st.checkbox("IG Spread (투자등급채권)", value=False, key="mc_ig_spread")

    st.caption("💧 Fed 유동성")
    mc_walcl   = st.checkbox("Fed 총자산 (Balance Sheet)", value=False, key="mc_walcl")
    mc_rrp     = st.checkbox("Reverse Repo (역레포)",   value=False, key="mc_rrp")
    mc_netliq  = st.checkbox("Net Liquidity (순유동성)", value=False, key="mc_netliq")

    st.caption("📊 경기선행지수")
    mc_icsa    = st.checkbox("Initial Jobless Claims",  value=False, key="mc_icsa")
    mc_payems  = st.checkbox("Nonfarm Payroll (비농업고용)", value=False, key="mc_payems")
    mc_umcsent = st.checkbox("Consumer Sentiment (소비자심리)", value=False, key="mc_umcsent")

    st.caption("🏠 미국 주택")
    mc_houst      = st.checkbox("Housing Starts (주택착공)",  value=False, key="mc_houst")
    mc_permit     = st.checkbox("Building Permits (건축허가)", value=False, key="mc_permit")
    mc_mortgage30 = st.checkbox("30Y Mortgage Rate",          value=False, key="mc_mortgage30")

    st.caption("🏦 미국 매크로")
    mc_cpi     = st.checkbox("US CPI (YoY %)",        value=False, key="mc_cpi")
    mc_pce     = st.checkbox("PCE YoY (Fed 타겟)",    value=False, key="mc_pce")
    mc_ppi     = st.checkbox("PPI YoY (생산자물가)",   value=False, key="mc_ppi")
    mc_breakeven = st.checkbox("Breakeven Inflation (기대인플레이션)", value=False, key="mc_breakeven")
    mc_unrate  = st.checkbox("실업률",                 value=False, key="mc_unrate")
    mc_m2      = st.checkbox("M2 Money Supply",       value=False, key="mc_m2")

    st.caption("🇰🇷 한국 부동산")
    st.markdown("<small>매매가격지수</small>", unsafe_allow_html=True)
    mc_deal_전국  = st.checkbox("매매 — 전국",  value=False, key="mc_deal_전국")
    mc_deal_수도권 = st.checkbox("매매 — 수도권", value=False, key="mc_deal_수도권")
    mc_deal_서울  = st.checkbox("매매 — 서울",  value=False, key="mc_deal_서울")
    mc_deal_지방권 = st.checkbox("매매 — 지방권", value=False, key="mc_deal_지방권")
    st.markdown("<small>전세가격지수</small>", unsafe_allow_html=True)
    mc_rent_전국  = st.checkbox("전세 — 전국",  value=False, key="mc_rent_전국")
    mc_rent_수도권 = st.checkbox("전세 — 수도권", value=False, key="mc_rent_수도권")
    mc_rent_서울  = st.checkbox("전세 — 서울",  value=False, key="mc_rent_서울")
    mc_rent_지방권 = st.checkbox("전세 — 지방권", value=False, key="mc_rent_지방권")

# ── Sidebar navigation (clickable) ───────────────────
st.sidebar.markdown("---")
st.sidebar.markdown("""
<style>
section[data-testid="stSidebar"] a.nav-link {
    display: block;
    padding: 3px 6px;
    color: #1f77b4;
    text-decoration: none;
    border-radius: 4px;
    font-size: 0.88em;
    line-height: 1.6;
}
section[data-testid="stSidebar"] a.nav-link:hover {
    background: rgba(28,131,225,0.1);
}
section[data-testid="stSidebar"] .nav-phase {
    font-weight: 700;
    font-size: 0.82em;
    color: #444;
    margin-top: 6px;
    margin-bottom: 2px;
    display: block;
}
</style>
<a class="nav-link" href="#master-chart">📊 Master Chart</a>
<span class="nav-phase">📌 Phase 1 — Global</span>
<a class="nav-link" href="#exchange-rate">💱 Exchange Rate</a>
<a class="nav-link" href="#gold-silver">🥇 Gold / Silver Ratio</a>
<a class="nav-link" href="#indices">📈 Major Indices</a>
<a class="nav-link" href="#vix">😨 VIX Fear Index</a>
<a class="nav-link" href="#oil">🛢️ Oil Price</a>
<span class="nav-phase">📌 Phase 2 — US Macro</span>
<a class="nav-link" href="#rate-cpi">📉 US Rate vs CPI</a>
<a class="nav-link" href="#m2">💵 M2 Money Supply</a>
<a class="nav-link" href="#gdp">📊 US GDP Growth</a>
<a class="nav-link" href="#dxy">💲 Dollar Index (DXY)</a>
<span class="nav-phase">📌 Phase 3 — Korea</span>
<a class="nav-link" href="#kr-rate-cpi">🏛️ Korea Rate vs CPI</a>
<a class="nav-link" href="#apt-price">🏢 Apartment Price Index</a>
<a class="nav-link" href="#jeonse-rate">📐 전세가율</a>
<a class="nav-link" href="#kosdaq">📊 KOSPI / KOSDAQ</a>
""", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════
# PRE-FETCH — download all market tickers in parallel
# ════════════════════════════════════════════════════════
_p1_tickers = ("USDKRW=X", "EURKRW=X", "GC=F", "SI=F", "^GSPC", "^KS11", "^IXIC", "^VIX", "CL=F")
_p2_tickers = ("DX-Y.NYB",)
_p3_tickers = ("^KQ11", "^KS11")
_mkt_p1 = get_data_batch(_p1_tickers, period_p1)
_mkt_p2 = get_data_batch(_p2_tickers, period_p2)
_mkt_p3 = get_data_batch(_p3_tickers, period_p3)

# ── Master Chart pre-fetch ────────────────────────────
_mc_fred_days = {
    "1mo": 31, "3mo": 92, "6mo": 183,
    "1y": 365, "2y": 730, "3y": 1095, "5y": 1825, "7y": 2555,
    "10y": 3650, "15y": 5475, "20y": 7300, "30y": 10950, "max": 365 * 40,
}
if mc_period == "custom":
    mc_fred_start  = datetime.combine(mc_custom_start, datetime.min.time())
    mc_fred_end_dt = datetime.combine(mc_custom_end,   datetime.min.time())
else:
    mc_fred_start  = fred_end - timedelta(days=_mc_fred_days[mc_period])
    mc_fred_end_dt = fred_end
mc_start_ym = mc_fred_start.strftime("%Y%m")

_mc_need: list = []
if mc_usdkrw:                              _mc_need.append("USDKRW=X")
if mc_eurkrw:                              _mc_need.append("EURKRW=X")
if mc_usdjpy:                              _mc_need.append("USDJPY=X")
if mc_dxy:                                 _mc_need.append("DX-Y.NYB")
if mc_gold or mc_ratio or mc_cugold:       _mc_need.append("GC=F")
if mc_silver or mc_ratio:                  _mc_need.append("SI=F")
if mc_wti:                                 _mc_need.append("CL=F")
if mc_copper or mc_cugold:                 _mc_need.append("HG=F")
if mc_natgas:                              _mc_need.append("NG=F")
if mc_sp500:                               _mc_need.append("^GSPC")
if mc_nasdaq:                              _mc_need.append("^IXIC")
if mc_sox:                                 _mc_need.append("^SOX")
if mc_nikkei:                              _mc_need.append("^N225")
if mc_dax:                                 _mc_need.append("^GDAXI")
if mc_sse:                                 _mc_need.append("000001.SS")
if mc_vix:                                 _mc_need.append("^VIX")
if mc_btc:                                 _mc_need.append("BTC-USD")
if mc_kospi:                               _mc_need.append("^KS11")
if mc_kosdaq:                              _mc_need.append("^KQ11")
if mc_samsung:                             _mc_need.append("005930.KS")
if mc_us10y:                               _mc_need.append("^TNX")
if mc_us30y:                               _mc_need.append("^TYX")

if mc_period == "custom":
    _mc_mkt = get_data_batch_range(tuple(_mc_need), mc_custom_start, mc_custom_end) if _mc_need else {}
else:
    _mc_mkt = get_data_batch(tuple(_mc_need), mc_period) if _mc_need else {}

_extra_start   = mc_fred_start - timedelta(days=400)
_fe            = mc_fred_end_dt
_mc_fedfunds   = get_fred_data("FEDFUNDS",      mc_fred_start, _fe) if mc_fedrate    else None
_mc_us10y_fr   = get_fred_data("DGS10",         mc_fred_start, _fe) if mc_us10y      else None
_mc_us30y_fr   = get_fred_data("DGS30",         mc_fred_start, _fe) if mc_us30y      else None
_mc_yldcrv     = get_fred_data("T10Y2Y",        mc_fred_start, _fe) if mc_yldcrv     else None
_mc_hy_spread  = get_fred_data("BAMLH0A0HYM2", mc_fred_start, _fe) if mc_hy_spread   else None
_mc_ig_spread  = get_fred_data("BAMLC0A0CM",   mc_fred_start, _fe) if mc_ig_spread   else None
_mc_walcl      = get_fred_data("WALCL",         mc_fred_start, _fe) if mc_walcl or mc_netliq  else None
_mc_rrp_data   = get_fred_data("RRPONTSYD",     mc_fred_start, _fe) if mc_rrp or mc_netliq    else None
_mc_tga        = get_fred_data("WTREGEN",       mc_fred_start, _fe) if mc_netliq     else None
_mc_icsa       = get_fred_data("ICSA",          mc_fred_start, _fe) if mc_icsa       else None
_mc_payems     = get_fred_data("PAYEMS",        mc_fred_start, _fe) if mc_payems     else None
_mc_umcsent    = get_fred_data("UMCSENT",       mc_fred_start, _fe) if mc_umcsent    else None
_mc_houst      = get_fred_data("HOUST",         mc_fred_start, _fe) if mc_houst      else None
_mc_permit_fr  = get_fred_data("PERMIT",        mc_fred_start, _fe) if mc_permit     else None
_mc_mortgage30 = get_fred_data("MORTGAGE30US",  mc_fred_start, _fe) if mc_mortgage30 else None
_mc_cpi_raw    = get_fred_data("CPIAUCSL",      _extra_start,  _fe) if mc_cpi        else None
_mc_pce_raw    = get_fred_data("PCEPI",         _extra_start,  _fe) if mc_pce        else None
_mc_ppi_raw    = get_fred_data("PPIACO",        _extra_start,  _fe) if mc_ppi        else None
_mc_breakeven  = get_fred_data("T10YIE",        mc_fred_start, _fe) if mc_breakeven  else None
_mc_unrate     = get_fred_data("UNRATE",        mc_fred_start, _fe) if mc_unrate     else None
_mc_m2_raw     = get_fred_data("M2SL",          _extra_start,  _fe) if mc_m2         else None
_mc_usrec      = get_fred_data("USREC",         mc_fred_start, _fe) if mc_recession  else None

_mc_deal: dict = {}
_mc_rent_apt: dict = {}
_mc_apt_needed = any([mc_deal_전국, mc_deal_수도권, mc_deal_서울, mc_deal_지방권,
                       mc_rent_전국, mc_rent_수도권, mc_rent_서울, mc_rent_지방권])
if _mc_apt_needed:
    _mc_deal, _mc_rent_apt, _ = get_apt_price_index(REB_API_KEY, mc_start_ym, fred_end.strftime("%Y%m"))


# ════════════════════════════════════════════════════════
# MASTER CHART
# ════════════════════════════════════════════════════════
st.markdown('<div id="master-chart"></div>', unsafe_allow_html=True)
st.header("📊 Master Chart")

_mc_colors = {
    "USDKRW=X": "royalblue", "EURKRW=X": "orange",
    "GC=F": "gold",          "SI=F": "slategray",
    "^GSPC": "royalblue",    "^KS11": "crimson",
    "^IXIC": "green",        "^VIX": "purple",
    "CL=F": "saddlebrown",
}
_kr_colors = {"전국": "gray", "서울": "royalblue", "수도권": "green", "지방권": "crimson"}

_mc_series: list = []  # (label, pd.Series, color, unit)

def _add(label, s, color, unit):
    if s is not None and not s.empty:
        _mc_series.append((label, s.squeeze(), color, unit))

# 환율
if mc_usdkrw:  _add("USD/KRW",           _mc_mkt.get("USDKRW=X"),  "royalblue",      "KRW")
if mc_eurkrw:  _add("EUR/KRW",           _mc_mkt.get("EURKRW=X"),  "darkorange",     "KRW")
if mc_usdjpy:  _add("USD/JPY",           _mc_mkt.get("USDJPY=X"),  "indianred",      "JPY")
if mc_dxy:     _add("DXY",               _mc_mkt.get("DX-Y.NYB"),  "darkgreen",      "Index")
# 원자재
if mc_gold:    _add("Gold Price",         _mc_mkt.get("GC=F"),      "gold",           "USD")
if mc_silver:  _add("Silver Price",       _mc_mkt.get("SI=F"),      "slategray",      "USD")
if mc_ratio:
    _g  = _mc_mkt.get("GC=F")
    _sv = _mc_mkt.get("SI=F")
    if _g is not None and _sv is not None and not _g.empty and not _sv.empty:
        _c2 = pd.concat([_g.squeeze(), _sv.squeeze()], axis=1).dropna()
        _c2.columns = ["Gold", "Silver"]
        _add("Gold/Silver Ratio", _c2["Gold"] / _c2["Silver"], "goldenrod", "Ratio")
if mc_cugold:
    _gc = _mc_mkt.get("GC=F")
    _cu = _mc_mkt.get("HG=F")
    if _gc is not None and _cu is not None and not _gc.empty and not _cu.empty:
        _c3 = pd.concat([_cu.squeeze(), _gc.squeeze()], axis=1).dropna()
        _c3.columns = ["Cu", "Au"]
        _add("Copper/Gold Ratio", _c3["Cu"] / _c3["Au"], "peru", "Ratio")
if mc_wti:     _add("WTI Oil",            _mc_mkt.get("CL=F"),      "saddlebrown",    "USD/bbl")
if mc_copper:  _add("Copper",             _mc_mkt.get("HG=F"),      "chocolate",      "USD/lb")
if mc_natgas:  _add("Natural Gas",        _mc_mkt.get("NG=F"),      "cadetblue",      "USD/MMBtu")
# 글로벌 지수
if mc_sp500:   _add("S&P 500",            _mc_mkt.get("^GSPC"),     "#1f77b4",        "Index")
if mc_nasdaq:  _add("NASDAQ",             _mc_mkt.get("^IXIC"),     "#2ca02c",        "Index")
if mc_sox:     _add("SOX 반도체",          _mc_mkt.get("^SOX"),      "#9467bd",        "Index")
if mc_nikkei:  _add("Nikkei 225",         _mc_mkt.get("^N225"),     "#e377c2",        "Index")
if mc_dax:     _add("DAX",               _mc_mkt.get("^GDAXI"),    "#8c564b",        "Index")
if mc_sse:     _add("Shanghai",           _mc_mkt.get("000001.SS"), "#d62728",        "Index")
if mc_vix:     _add("VIX",               _mc_mkt.get("^VIX"),      "mediumpurple",   "Index")
if mc_btc:     _add("Bitcoin",            _mc_mkt.get("BTC-USD"),   "#f7931a",        "USD")
# 한국 지수
if mc_kospi:   _add("KOSPI",             _mc_mkt.get("^KS11"),     "crimson",        "Index")
if mc_kosdaq:  _add("KOSDAQ",            _mc_mkt.get("^KQ11"),     "mediumvioletred","Index")
if mc_samsung: _add("삼성전자",            _mc_mkt.get("005930.KS"), "#1428A0",        "KRW")
# 채권 & 금리 (우축 %)
if mc_us10y:
    _s10y = _mc_mkt.get("^TNX") or _mc_us10y_fr
    if _s10y is not None and not _s10y.empty:
        _mc_series.append(("US 10Y Yield", _s10y.squeeze(), "navy", "%"))
if mc_us30y:
    _s30y = _mc_mkt.get("^TYX") or _mc_us30y_fr
    if _s30y is not None and not _s30y.empty:
        _mc_series.append(("US 30Y Yield", _s30y.squeeze(), "midnightblue", "%"))
if mc_yldcrv and _mc_yldcrv is not None and not _mc_yldcrv.empty:
    _mc_series.append(("Yield Curve 10Y-2Y", _mc_yldcrv, "darkcyan", "%"))
if mc_fedrate and _mc_fedfunds is not None and not _mc_fedfunds.empty:
    _mc_series.append(("Fed Funds Rate", _mc_fedfunds, "steelblue", "%"))
# 신용 스프레드 (우축 %)
if mc_hy_spread and _mc_hy_spread is not None and not _mc_hy_spread.empty:
    _mc_series.append(("HY Spread", _mc_hy_spread, "#e63946", "%"))
if mc_ig_spread and _mc_ig_spread is not None and not _mc_ig_spread.empty:
    _mc_series.append(("IG Spread", _mc_ig_spread, "#f4a261", "%"))
# Fed 유동성 (좌축, 단위 B USD / M USD)
if mc_walcl and _mc_walcl is not None and not _mc_walcl.empty:
    _add("Fed 총자산", _mc_walcl, "#00b4d8", "M USD")
if mc_rrp and _mc_rrp_data is not None and not _mc_rrp_data.empty:
    _add("Reverse Repo", _mc_rrp_data, "#48cae4", "B USD")
if mc_netliq:
    if all(x is not None for x in [_mc_walcl, _mc_rrp_data, _mc_tga]):
        _nl = (_mc_walcl - _mc_rrp_data - _mc_tga).dropna()
        if not _nl.empty:
            _add("Net Liquidity", _nl, "#0077b6", "M USD")
# 경기선행지수
if mc_icsa and _mc_icsa is not None and not _mc_icsa.empty:
    _add("Jobless Claims", _mc_icsa, "#6c757d", "K")
if mc_payems and _mc_payems is not None and not _mc_payems.empty:
    _add("Nonfarm Payroll", _mc_payems, "#495057", "K")
if mc_umcsent and _mc_umcsent is not None and not _mc_umcsent.empty:
    _add("Consumer Sentiment", _mc_umcsent, "#20c997", "Index")
# 미국 주택
if mc_houst and _mc_houst is not None and not _mc_houst.empty:
    _add("Housing Starts", _mc_houst, "#fd7e14", "K units")
if mc_permit and _mc_permit_fr is not None and not _mc_permit_fr.empty:
    _add("Building Permits", _mc_permit_fr, "#ffc107", "K units")
if mc_mortgage30 and _mc_mortgage30 is not None and not _mc_mortgage30.empty:
    _mc_series.append(("30Y Mortgage Rate", _mc_mortgage30, "#dc3545", "%"))
# 미국 매크로
if mc_cpi and _mc_cpi_raw is not None and not _mc_cpi_raw.empty:
    _yoy = (_mc_cpi_raw.pct_change(12) * 100).dropna()
    if not _yoy.empty:
        _mc_series.append(("US CPI YoY", _yoy, "#d62728", "%"))
if mc_pce and _mc_pce_raw is not None and not _mc_pce_raw.empty:
    _yoy = (_mc_pce_raw.pct_change(12) * 100).dropna()
    if not _yoy.empty:
        _mc_series.append(("PCE YoY", _yoy, "#e377c2", "%"))
if mc_ppi and _mc_ppi_raw is not None and not _mc_ppi_raw.empty:
    _yoy = (_mc_ppi_raw.pct_change(12) * 100).dropna()
    if not _yoy.empty:
        _mc_series.append(("PPI YoY", _yoy, "#ff6b6b", "%"))
if mc_breakeven and _mc_breakeven is not None and not _mc_breakeven.empty:
    _mc_series.append(("Breakeven Inflation", _mc_breakeven, "#f77f00", "%"))
if mc_unrate and _mc_unrate is not None and not _mc_unrate.empty:
    _mc_series.append(("Unemployment Rate", _mc_unrate, "#adb5bd", "%"))
if mc_m2 and _mc_m2_raw is not None and not _mc_m2_raw.empty:
    _add("M2 Money Supply", _mc_m2_raw, "teal", "B USD")
# 한국 부동산
_deal_sel = {"전국": mc_deal_전국, "수도권": mc_deal_수도권, "서울": mc_deal_서울, "지방권": mc_deal_지방권}
_rent_sel = {"전국": mc_rent_전국, "수도권": mc_rent_수도권, "서울": mc_rent_서울, "지방권": mc_rent_지방권}
_rent_colors = {"전국": "#999999", "수도권": "#74b9ff", "서울": "#0984e3", "지방권": "#ff7675"}
for _rgn, _on in _deal_sel.items():
    if _on and _rgn in _mc_deal:
        _mc_series.append((f"매매-{_rgn}", _mc_deal[_rgn], _kr_colors.get(_rgn, "black"), "Index"))
for _rgn, _on in _rent_sel.items():
    if _on and _rgn in _mc_rent_apt:
        _mc_series.append((f"전세-{_rgn}", _mc_rent_apt[_rgn], _rent_colors.get(_rgn, "black"), "Index"))

_MC_PALETTE = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#17becf", "#bcbd22", "#7f7f7f",
    "#4e9af1", "#f5a623", "#50c878", "#e05c5c", "#b39ddb",
]

# 기준점 슬라이더 — 시리즈 빌드 후 날짜 범위 계산, session_state로 선-참조
_all_s_idx = [s.index for _, s, _, _ in _mc_series if not s.empty]
if _all_s_idx:
    _rb_min = min(i.min() for i in _all_s_idx).date()
    _rb_max = max(i.max() for i in _all_s_idx).date()
else:
    _rb_min = (datetime.now() - timedelta(days=730)).date()
    _rb_max = datetime.now().date()

_rb_key  = f"mc_rebase_{mc_period}"
_rb_val  = st.session_state.get(_rb_key, _rb_min)
try:
    _rb_val = max(_rb_min, min(_rb_max, _rb_val))
except Exception:
    _rb_val = _rb_min

_rebase_ts = pd.Timestamp(_rb_val) if _rb_val != _rb_min else None

if not _mc_series:
    st.info("사이드바 '📊 Master Chart' 에서 시리즈를 하나 이상 선택하세요.", icon="📊")
else:
    _fig = make_subplots(specs=[[{"secondary_y": True}]])
    _has_primary = _has_secondary = False

    for _idx, (_label, _series, _, _unit) in enumerate(_mc_series):
        _col = _MC_PALETTE[_idx % len(_MC_PALETTE)]
        _s   = _series.dropna()
        if _s.empty:
            continue

        _is_rate = (_unit == "%")
        if _is_rate:
            _fig.add_trace(go.Scatter(
                x=_s.index, y=_s.values.flatten(),
                name=f"{_label} ({_unit})",
                line=dict(color=_col, width=2, dash="dot"),
                mode="lines",
                hovertemplate=f"<b>{_label}</b><br>%{{x|%Y-%m-%d}}<br>%{{y:.2f}}%<extra></extra>",
            ), secondary_y=True)
            _has_secondary = True
        else:
            if _rebase_ts is not None:
                _loc = min(_s.index.searchsorted(_rebase_ts), len(_s) - 1)
                _base = float(_s.iloc[_loc])
            else:
                _base = float(_s.iloc[0])
            _norm = (_s / _base * 100) if _base != 0 else _s
            _fig.add_trace(go.Scatter(
                x=_norm.index, y=_norm.values.flatten(),
                name=_label,
                line=dict(color=_col, width=2),
                mode="lines",
                hovertemplate=f"<b>{_label}</b><br>%{{x|%Y-%m-%d}}<br>%{{y:.1f}}<extra></extra>",
            ), secondary_y=False)
            _has_primary = True

    # 경기침체 구간 음영
    if mc_recession and _mc_usrec is not None and not _mc_usrec.empty:
        _in_rec = False
        _rec_x0 = None
        for _dt, _val in _mc_usrec.items():
            if _val == 1 and not _in_rec:
                _in_rec = True
                _rec_x0 = _dt
            elif _val == 0 and _in_rec:
                _in_rec = False
                _fig.add_vrect(x0=_rec_x0, x1=_dt,
                               fillcolor="rgba(180,180,180,0.18)",
                               line_width=0, layer="below",
                               annotation_text="Recession", annotation_position="top left",
                               annotation_font_size=9, annotation_font_color="gray")
        if _in_rec and _rec_x0 is not None:
            _fig.add_vrect(x0=_rec_x0, x1=fred_end,
                           fillcolor="rgba(180,180,180,0.18)",
                           line_width=0, layer="below")

    # 기준점 수직선
    if _rebase_ts is not None:
        _fig.add_vline(
            x=str(_rb_val),
            line_dash="dash", line_color="rgba(40,40,40,0.6)", line_width=1.5,
        )
        _fig.add_annotation(
            x=str(_rb_val), y=1, yref="paper",
            text=f"기준 {_rb_val}", showarrow=False,
            xanchor="left", yanchor="top",
            font=dict(size=10, color="rgba(40,40,40,0.8)"),
            bgcolor="rgba(255,255,255,0.7)",
        )
    if _has_primary:
        _fig.add_hline(y=100, line_dash="dot",
                       line_color="rgba(128,128,128,0.4)", line_width=1)
    _fig.update_yaxes(title_text="Indexed (기준점 = 100)", secondary_y=False)
    if _has_secondary:
        _fig.update_yaxes(title_text="Rate / % (absolute)", secondary_y=True)
    _fig.update_layout(
        height=520,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0),
        margin=dict(t=10, b=40, l=60, r=60),
        clickmode="event",
    )

    st.plotly_chart(_fig, use_container_width=True, key="mc_master_chart")

    # 기준점 슬라이더 (차트 바로 아래)
    _col_btn, _col_sl = st.columns([1, 7])
    with _col_btn:
        if st.button("초기화", key="mc_rebase_reset"):
            st.session_state[_rb_key] = _rb_min
            st.rerun()
    with _col_sl:
        st.slider(
            "📍 기준점 (= 100) — 드래그해서 조정",
            min_value=_rb_min,
            max_value=_rb_max,
            value=_rb_val,
            format="YYYY-MM-DD",
            key=_rb_key,
        )
    if _rebase_ts is not None:
        st.caption(f"기준점: **{str(_rb_val)}** = 100 │ 가격·지수: 좌축 │ 금리·%: 우축(점선) │ 회색 음영: 침체 구간")
    else:
        st.caption("기준점: 시작일 = 100 │ 가격·지수: 좌축 │ 금리·%: 우축(점선) │ 회색 음영: 침체 구간")

st.divider()

# ════════════════════════════════════════════════════════
# PHASE 1 — GLOBAL MARKETS
# ════════════════════════════════════════════════════════

# ── 1. Exchange Rate ──────────────────────────────────
st.markdown('<div id="exchange-rate"></div>', unsafe_allow_html=True)
st.header("💱 Exchange Rate")
col1, col2 = st.columns(2)

with col1:
    usd_krw = _mkt_p1.get("USDKRW=X")
    if usd_krw is not None and not usd_krw.empty:
        usd_val = float(usd_krw.iloc[-1])
        usd_chg = ((usd_krw.iloc[-1] / usd_krw.iloc[0]) - 1) * 100
        st.metric("USD/KRW", f"₩{usd_val:,.1f}", f"{float(usd_chg):.1f}%")
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=usd_krw.index, y=usd_krw.values.flatten(),
                                  mode='lines', name='USD/KRW', line=dict(color='royalblue')))
        fig.update_layout(xaxis_title="Date", yaxis_title="KRW", height=260,
                          margin=dict(t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)

with col2:
    eur_krw = _mkt_p1.get("EURKRW=X")
    if eur_krw is not None and not eur_krw.empty:
        eur_val = float(eur_krw.iloc[-1])
        eur_chg = ((eur_krw.iloc[-1] / eur_krw.iloc[0]) - 1) * 100
        st.metric("EUR/KRW", f"₩{eur_val:,.1f}", f"{float(eur_chg):.1f}%")
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=eur_krw.index, y=eur_krw.values.flatten(),
                                  mode='lines', name='EUR/KRW', line=dict(color='orange')))
        fig.update_layout(xaxis_title="Date", yaxis_title="KRW", height=260,
                          margin=dict(t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)

# ── 2. Gold / Silver Ratio ────────────────────────────
st.markdown('<div id="gold-silver"></div>', unsafe_allow_html=True)
st.header("🥇 Gold / Silver Ratio")
gold = _mkt_p1.get("GC=F")
silver = _mkt_p1.get("SI=F")

if gold is not None and silver is not None and not gold.empty and not silver.empty:
    gold_flat   = gold.squeeze()
    silver_flat = silver.squeeze()
    combined    = pd.concat([gold_flat, silver_flat], axis=1).dropna()
    combined.columns = ['Gold', 'Silver']
    ratio = combined['Gold'] / combined['Silver']

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Gold/Silver Ratio", f"{ratio.iloc[-1]:.1f}")
    with col2:
        st.metric("Gold Price (USD)", f"${combined['Gold'].iloc[-1]:,.1f}")
    with col3:
        st.metric("Silver Price (USD)", f"${combined['Silver'].iloc[-1]:,.2f}")

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=ratio.index, y=ratio.values, mode='lines',
                              name='Gold/Silver Ratio', line=dict(color='gold')))
    fig.add_hline(y=80, line_dash="dash", line_color="red", annotation_text="Historical High (80)")
    fig.add_hline(y=50, line_dash="dash", line_color="green", annotation_text="Historical Avg (50)")
    fig.update_layout(title="Gold / Silver Ratio (higher = silver undervalued)", height=350)
    st.plotly_chart(fig, use_container_width=True)

# ── 3. Major Indices ──────────────────────────────────
st.markdown('<div id="indices"></div>', unsafe_allow_html=True)
st.header("📈 Major Indices")
col1, col2, col3 = st.columns(3)

indices = {
    "S&P 500": ("^GSPC", "royalblue", col1),
    "KOSPI":   ("^KS11", "crimson",   col2),
    "NASDAQ":  ("^IXIC", "green",     col3),
}
for name, (ticker, color, col) in indices.items():
    data = _mkt_p1.get(ticker)
    if data is not None and not data.empty:
        with col:
            change = ((data.iloc[-1] / data.iloc[0]) - 1) * 100
            st.metric(name, f"{float(data.iloc[-1].item()):,.1f}", f"{change.item():.1f}%")
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=data.index, y=data.values.flatten(),
                                      mode='lines', line=dict(color=color)))
            fig.update_layout(title=name, height=250, margin=dict(t=30, b=10))
            st.plotly_chart(fig, use_container_width=True)

# ── 4. VIX Fear Index ─────────────────────────────────
st.markdown('<div id="vix"></div>', unsafe_allow_html=True)
st.header("😨 VIX Fear Index")
vix = _mkt_p1.get("^VIX")

if vix is not None and not vix.empty:
    current_vix = vix.iloc[-1].item()
    if current_vix < 20:
        status, color = "😌 Calm (below 20)", "green"
    elif current_vix < 30:
        status, color = "⚠️ Caution (20-30)", "orange"
    else:
        status, color = "🚨 Fear (above 30)", "red"

    col1, col2 = st.columns([1, 3])
    with col1:
        st.metric("Current VIX", f"{current_vix:.1f}")
        st.markdown(f"**Status:** :{color}[{status}]")
    with col2:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=vix.index, y=vix.values.flatten(),
                                  mode='lines', fill='tozeroy', line=dict(color='purple')))
        fig.add_hline(y=20, line_dash="dash", line_color="orange", annotation_text="Caution (20)")
        fig.add_hline(y=30, line_dash="dash", line_color="red",    annotation_text="Fear (30)")
        fig.update_layout(title="VIX Fear Index", height=300)
        st.plotly_chart(fig, use_container_width=True)

# ── 5. Oil Price ──────────────────────────────────────
st.markdown('<div id="oil"></div>', unsafe_allow_html=True)
st.header("🛢️ Oil Price (WTI Crude Oil)")
oil = _mkt_p1.get("CL=F")

if oil is not None and not oil.empty:
    oil    = oil.squeeze()
    change = ((oil.iloc[-1] / oil.iloc[0]) - 1) * 100
    col1, col2 = st.columns([1, 3])
    with col1:
        st.metric("WTI Price", f"${float(oil.iloc[-1]):,.1f}", f"{float(change):.1f}%")
    with col2:
        fig = go.Figure()
        _oil_min = float(oil.min())
        _oil_max = float(oil.max())
        _oil_pad = (_oil_max - _oil_min) * 0.08
        fig.add_trace(go.Scatter(x=oil.index, y=oil.values.flatten(),
                                  mode='lines', fill='tozeroy', line=dict(color='saddlebrown')))
        fig.update_layout(title="WTI Crude Oil (USD/barrel)", height=300)
        fig.update_yaxes(range=[max(0, _oil_min - _oil_pad), _oil_max + _oil_pad])
        st.plotly_chart(fig, use_container_width=True)
else:
    st.warning("Failed to load oil price data. (ticker: CL=F)")


# ════════════════════════════════════════════════════════
# PHASE 2 — US MACRO INDICATORS
# ════════════════════════════════════════════════════════
st.divider()
st.header("🏦 Phase 2 — US Macro Indicators")

# ── 6. US Interest Rate vs CPI ────────────────────────
st.markdown('<div id="rate-cpi"></div>', unsafe_allow_html=True)
st.subheader("📉 US Interest Rate vs CPI")

fed_rate = get_fred_data("FEDFUNDS", fred_start_p2, fred_end)
cpi      = get_fred_data("CPIAUCSL", fred_start_p2 - timedelta(days=13 * 30), fred_end)

if fed_rate is not None and cpi is not None and not fed_rate.empty and not cpi.empty:
    cpi_yoy    = cpi.pct_change(12) * 100
    cpi_yoy    = cpi_yoy.dropna()
    common_idx = fed_rate.index.intersection(cpi_yoy.index)
    if len(common_idx) > 0:
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(go.Scatter(x=fed_rate.loc[common_idx].index,
                                  y=fed_rate.loc[common_idx].values,
                                  name="Fed Funds Rate (%)",
                                  line=dict(color="royalblue", width=2)),
                       secondary_y=False)
        fig.add_trace(go.Scatter(x=cpi_yoy.loc[common_idx].index,
                                  y=cpi_yoy.loc[common_idx].values,
                                  name="CPI YoY (%)",
                                  line=dict(color="crimson", width=2, dash="dot")),
                       secondary_y=True)
        fig.add_hline(y=2.0, line_dash="dash", line_color="gray",
                      annotation_text="Fed 2% Target", secondary_y=True)
        fig.update_layout(title="US Federal Funds Rate vs CPI Inflation (YoY)",
                          height=380, legend=dict(x=0.01, y=0.99))
        fig.update_yaxes(title_text="Fed Funds Rate (%)", secondary_y=False)
        fig.update_yaxes(title_text="CPI YoY (%)", secondary_y=True)
        st.plotly_chart(fig, use_container_width=True)

        col1, col2 = st.columns(2)
        with col1:
            st.metric("Fed Funds Rate (latest)", f"{fed_rate.iloc[-1]:.2f}%")
        with col2:
            if not cpi_yoy.empty:
                st.metric("CPI YoY (latest)", f"{cpi_yoy.iloc[-1]:.2f}%")
    else:
        st.warning("No overlapping dates for the selected period.")
else:
    st.error("Failed to load US Rate / CPI data from FRED.")

# ── 7. M2 Money Supply ───────────────────────────────
st.markdown('<div id="m2"></div>', unsafe_allow_html=True)
st.subheader("💵 M2 Money Supply")

m2_start = fred_end - timedelta(days=max(_months_back_p2 * 30, 365 * 3))
m2 = get_fred_data("M2SL", m2_start, fred_end)
m1 = get_fred_data("M1SL", m2_start, fred_end)

if m2 is not None and not m2.empty:
    m2_yoy = m2.pct_change(12) * 100
    m2_yoy = m2_yoy.dropna()
    m1_yoy = (m1.pct_change(12) * 100).dropna() if m1 is not None and not m1.empty else None

    col1, col2 = st.columns([1, 3])
    with col1:
        st.metric("M2 (latest)", f"${m2.iloc[-1]:,.0f}B")
        if not m2_yoy.empty:
            st.metric("M2 YoY Growth", f"{m2_yoy.iloc[-1]:.1f}%")
        if m1 is not None and not m1.empty:
            st.metric("M1 (latest)", f"${m1.iloc[-1]:,.0f}B")
        if m1_yoy is not None and not m1_yoy.empty:
            st.metric("M1 YoY Growth", f"{m1_yoy.iloc[-1]:.1f}%")
    with col2:
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(go.Scatter(x=m2.index, y=m2.values,
                                  name="M2 (Billions USD)", line=dict(color="teal", width=2)),
                       secondary_y=False)
        if m1 is not None and not m1.empty:
            fig.add_trace(go.Scatter(x=m1.index, y=m1.values,
                                      name="M1 (Billions USD)", line=dict(color="royalblue", width=2)),
                           secondary_y=False)
        if not m2_yoy.empty:
            fig.add_trace(go.Scatter(x=m2_yoy.index, y=m2_yoy.values,
                                      name="M2 YoY Growth (%)",
                                      line=dict(color="darkorange", width=1.5, dash="dot")),
                           secondary_y=True)
        if m1_yoy is not None and not m1_yoy.empty:
            fig.add_trace(go.Scatter(x=m1_yoy.index, y=m1_yoy.values,
                                      name="M1 YoY Growth (%)",
                                      line=dict(color="steelblue", width=1.5, dash="dot")),
                           secondary_y=True)
        if not m2_yoy.empty or (m1_yoy is not None and not m1_yoy.empty):
            fig.add_hline(y=0, line_dash="dash", line_color="gray", secondary_y=True)
        fig.update_layout(title="M1 / M2 Money Supply & YoY Growth", height=350,
                          legend=dict(x=0.01, y=0.99))
        fig.update_yaxes(title_text="Money Supply (Billions USD)", secondary_y=False)
        fig.update_yaxes(title_text="YoY Growth (%)", secondary_y=True)
        st.plotly_chart(fig, use_container_width=True)
else:
    st.error("Failed to load M2 data from FRED.")

# ── 8. US GDP Growth ─────────────────────────────────
st.markdown('<div id="gdp"></div>', unsafe_allow_html=True)
st.subheader("📊 US GDP Growth (Real)")

gdp_start = fred_end - timedelta(days=max(_months_back_p2 * 30, 5 * 365))
gdp = get_fred_data("GDPC1", gdp_start, fred_end)

if gdp is not None and not gdp.empty:
    gdp_qoq = gdp.pct_change(1) * 100
    gdp_yoy = gdp.pct_change(4) * 100
    gdp_qoq, gdp_yoy = gdp_qoq.dropna(), gdp_yoy.dropna()

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Real GDP (latest)", f"${gdp.iloc[-1]:,.0f}B")
    with col2:
        if not gdp_qoq.empty:
            st.metric("QoQ Growth", f"{gdp_qoq.iloc[-1]:.2f}%")
    with col3:
        if not gdp_yoy.empty:
            st.metric("YoY Growth", f"{gdp_yoy.iloc[-1]:.2f}%")

    fig = make_subplots(rows=1, cols=2,
                        subplot_titles=("Real GDP Level (Billions USD)", "GDP Growth Rate (%)"))
    fig.add_trace(go.Scatter(x=gdp.index, y=gdp.values, name="Real GDP",
                              line=dict(color="steelblue", width=2), fill="tozeroy"),
                   row=1, col=1)
    if not gdp_qoq.empty:
        colors_qoq = ["green" if v >= 0 else "red" for v in gdp_qoq.values]
        fig.add_trace(go.Bar(x=gdp_qoq.index, y=gdp_qoq.values, name="QoQ %",
                              marker_color=colors_qoq, opacity=0.75),
                       row=1, col=2)
    if not gdp_yoy.empty:
        fig.add_trace(go.Scatter(x=gdp_yoy.index, y=gdp_yoy.values, name="YoY %",
                                  line=dict(color="darkorange", width=2)),
                       row=1, col=2)
    fig.update_layout(height=380, showlegend=True, legend=dict(x=0.55, y=0.99))
    fig.add_hline(y=0, line_dash="dash", line_color="gray", row=1, col=2)
    st.plotly_chart(fig, use_container_width=True)
else:
    st.error("Failed to load GDP data from FRED.")

# ── 9. Dollar Index (DXY) ─────────────────────────────
st.markdown('<div id="dxy"></div>', unsafe_allow_html=True)
st.subheader("💲 US Dollar Index (DXY)")

dxy = _mkt_p2.get("DX-Y.NYB")

if dxy is not None and not dxy.empty:
    dxy        = dxy.squeeze()
    change_pct = ((dxy.iloc[-1] / dxy.iloc[0]) - 1) * 100
    val        = float(dxy.iloc[-1])

    col1, col2 = st.columns([1, 3])
    with col1:
        st.metric("DXY (latest)", f"{val:.2f}", f"{float(change_pct):.2f}%")
        if val >= 105:
            st.markdown("🔴 **Strong Dollar**")
        elif val >= 100:
            st.markdown("🟡 **Moderate Strength**")
        else:
            st.markdown("🟢 **Weaker Dollar**")
    with col2:
        fig = go.Figure()
        dxy_pad = max((float(dxy.max()) - float(dxy.min())) * 0.3, 1.5)
        dxy_lo  = float(dxy.min()) - dxy_pad
        dxy_hi  = float(dxy.max()) + dxy_pad
        fig.add_trace(go.Scatter(x=dxy.index, y=dxy.values.flatten(),
                                  mode="lines", name="DXY",
                                  line=dict(color="darkgreen", width=2)))
        fig.add_hline(y=100, line_dash="dash", line_color="gray",
                      annotation_text="100 (Parity benchmark)")
        fig.update_layout(title="US Dollar Index (DXY)", height=320,
                          xaxis_title="Date", yaxis_title="Index Level",
                          yaxis=dict(range=[dxy_lo, dxy_hi]))
        st.plotly_chart(fig, use_container_width=True)
else:
    st.error("Failed to load DXY data. (ticker: DX-Y.NYB)")


# ════════════════════════════════════════════════════════
# PHASE 3 — KOREA INDICATORS
# ════════════════════════════════════════════════════════
st.divider()
st.header("🇰🇷 Phase 3 — Korea Indicators")

# ── 10. Korea Interest Rate vs CPI ────────────────────
st.markdown('<div id="kr-rate-cpi"></div>', unsafe_allow_html=True)
st.subheader("🏛️ Korea Interest Rate vs CPI")

kr_wide_start = fred_end - timedelta(days=365 * 5)   # KORCPIALLMINMEI last updated Nov 2023 on FRED
kr_rate = get_fred_data("IR3TIB01KRM156N", kr_wide_start, fred_end)
kr_cpi  = get_fred_data("KORCPIALLMINMEI", kr_wide_start, fred_end)

if kr_rate is not None and kr_cpi is not None and not kr_rate.empty and not kr_cpi.empty:
    kr_cpi_yoy = (kr_cpi.pct_change(12) * 100).dropna()
    common     = kr_rate.index.intersection(kr_cpi_yoy.index)

    if len(common) > 0:
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(go.Scatter(x=kr_rate.loc[common].index,
                                  y=kr_rate.loc[common].values,
                                  name="Korea 3M T-Bill Rate (%)",
                                  line=dict(color="darkred", width=2)),
                       secondary_y=False)
        fig.add_trace(go.Scatter(x=kr_cpi_yoy.loc[common].index,
                                  y=kr_cpi_yoy.loc[common].values,
                                  name="Korea CPI YoY (%)",
                                  line=dict(color="darkorange", width=2, dash="dot")),
                       secondary_y=True)
        fig.add_hline(y=2.0, line_dash="dash", line_color="gray",
                      annotation_text="BOK 2% Target", secondary_y=True)
        fig.update_layout(title="Korea Interest Rate vs CPI Inflation (YoY)",
                          height=380, legend=dict(x=0.01, y=0.99))
        fig.update_yaxes(title_text="Korea 3M Rate (%, proxy)", secondary_y=False)
        fig.update_yaxes(title_text="CPI YoY (%)", secondary_y=True)
        st.plotly_chart(fig, use_container_width=True)
        st.caption("금리: FRED IR3TIB01KRM156N (3개월 국고채, BOK 기준금리 대리지표) | "
                   "CPI: FRED KORCPIALLMINMEI (OECD 제공, 최신 데이터 ~2023년 11월 기준)")

        col1, col2 = st.columns(2)
        with col1:
            st.metric("Korea 3M Rate (latest)", f"{kr_rate.iloc[-1]:.2f}%")
        with col2:
            if not kr_cpi_yoy.empty:
                st.metric("Korea CPI YoY (latest)", f"{kr_cpi_yoy.iloc[-1]:.2f}%")
    else:
        st.warning("No overlapping dates for Korea rate and CPI.")
else:
    st.error("Failed to load Korea interest rate / CPI data from FRED.")

# ── 11. Apartment Price Index ─────────────────────────
st.markdown('<div id="apt-price"></div>', unsafe_allow_html=True)
st.subheader("🏢 아파트 가격지수 — 서울 vs 지방 (매매 / 전세)")

# Date range for apartment data (always extend at least 3 years back for context)
apt_end_ym   = fred_end.strftime("%Y%m")
apt_start_ym = (fred_end - timedelta(days=max(_months_back_p3 * 30, 365 * 3))).strftime("%Y%m")

with st.spinner("한국부동산원 API에서 데이터 로딩 중..."):
    deal_data, rent_data, _working_ep = get_apt_price_index(REB_API_KEY, apt_start_ym, apt_end_ym)

colors_region = {"전국": "gray", "서울": "royalblue", "수도권": "green", "지방권": "crimson"}

if deal_data or rent_data:
    # ─ 매매/전세 dual-panel chart ─────────────────────────
    fig = make_subplots(
        rows=1, cols=2,
        subplot_titles=("아파트 매매가격지수", "아파트 전세가격지수"),
    )
    for region, series in (deal_data or {}).items():
        fig.add_trace(go.Scatter(
            x=series.index, y=series.values, name=f"매매-{region}",
            line=dict(color=colors_region.get(region, "black"), width=2)),
            row=1, col=1)
    for region, series in (rent_data or {}).items():
        fig.add_trace(go.Scatter(
            x=series.index, y=series.values, name=f"전세-{region}",
            line=dict(color=colors_region.get(region, "black"), width=2, dash="dot")),
            row=1, col=2)

    fig.update_layout(height=400, showlegend=True, legend=dict(x=0.55, y=0.99))
    st.plotly_chart(fig, use_container_width=True)

    if _working_ep:
        st.caption(f"데이터 출처: {_working_ep}")

    # ─ Latest metrics row ──────────────────────────────────
    if deal_data:
        metric_cols = st.columns(len(deal_data))
        for i, (region, series) in enumerate(deal_data.items()):
            with metric_cols[i]:
                yoy = ((series.iloc[-1] / series.iloc[-13]) - 1) * 100 if len(series) > 12 else None
                st.metric(f"매매 {region}", f"{series.iloc[-1]:.1f}",
                          f"{yoy:.1f}% YoY" if yoy is not None else "")
else:
    # ─ API failed — show actionable guidance ──────────────
    st.warning(
        "아파트 가격지수 API 연결에 실패했습니다. "
        "아래 방법으로 서비스 신청 상태를 확인하세요.",
        icon="⚠️"
    )
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("""
**데이터 신청 방법**
1. [공공데이터포털](https://www.data.go.kr) 로그인
2. 마이페이지 → **활용신청 현황** 확인
3. 다음 서비스가 **승인** 상태인지 확인:
   - `한국부동산원_주택가격동향조사`
   - 또는 `아파트 가격지수`
4. 미신청 시 서비스 검색 후 **활용신청** (즉시승인)
        """)
    with col_b:
        st.markdown("""
**현재 등록된 키**
```
29401f124...8e (data.go.kr)
```
**시도한 기간**
```
{} ~ {}
```
**확인된 문제**
- apis.data.go.kr/1611000/* → 모두 HTTP 500
- R-ONE SttsApiTblData → ERROR-300
- openapi.reb.or.kr → 접속 불가 (timeout)

**data.go.kr 마이페이지에서 승인된 서비스명을 확인하세요.**
        """.format(apt_start_ym, apt_end_ym))

    with st.expander("🔍 상세 진단 (개발자용)"):
        st.code(
            "시도한 엔드포인트:\n"
            "  apis.data.go.kr/1611000/ApartPriceService/getApartPrice\n"
            "  apis.data.go.kr/1611000/ApartHousePriceService/getApartHousePrice\n"
            "  apis.data.go.kr/1611000/HousePriceInfoService/getHousePriceInfo\n"
            "  apis.data.go.kr/1611000/AptPriceIndexService/getAptPriceIndex\n"
            "  apis.data.go.kr/1611000/AptMonthlyPriceInfoSvc/getAptMonthlyPriceInfo\n"
            "  apis.data.go.kr/1611000/ApartPriceIndexSvc/getApartPriceIndex\n"
            "  apis.data.go.kr/1613000/ApartPriceIndexSvc/getApartPriceIndex\n"
            "  www.reb.or.kr/r-one/openapi/SttsApiTblData.do (publicDataPk 8종)\n\n"
            "결과: 모두 HTTP 500 또는 ERROR-300\n"
            "원인: 서비스 경로 불일치 또는 미승인 서비스\n"
            "해결: data.go.kr 마이페이지에서 승인된 서비스명/경로 확인 필요",
            language="text"
        )

# ── 12. 전세가율 ───────────────────────────────────────
st.markdown('<div id="jeonse-rate"></div>', unsafe_allow_html=True)
st.subheader("📐 전세가율 (전세/매매 비율)")

if deal_data and rent_data:
    common_regions = set(deal_data.keys()) & set(rent_data.keys())
    if common_regions:
        fig = go.Figure()
        all_vals = []
        for region in sorted(common_regions):
            deal_s = deal_data[region]
            rent_s = rent_data[region]
            common_idx = deal_s.index.intersection(rent_s.index)
            if len(common_idx) > 0:
                jeonse_rate = (rent_s.loc[common_idx] / deal_s.loc[common_idx]) * 100
                all_vals.extend(jeonse_rate.dropna().values.tolist())
                fig.add_trace(go.Scatter(
                    x=jeonse_rate.index, y=jeonse_rate.values,
                    name=f"전세가율 {region}",
                    line=dict(color=colors_region.get(region, "black"), width=2.5),
                    mode="lines",
                ))
        if all_vals:
            y_min, y_max = min(all_vals), max(all_vals)
            pad = max((y_max - y_min) * 0.3, 2)
            y_range = [y_min - pad, y_max + pad]
        else:
            y_range = [40, 115]
        fig.update_layout(
            title="아파트 전세가율 (전세가지수 / 매매가지수 × 100)",
            height=400, yaxis_title="전세가율 (%)",
            yaxis=dict(range=y_range),
            legend=dict(x=0.01, y=0.99),
        )
        st.plotly_chart(fig, use_container_width=True)
        st.caption("※ 가격지수 기준 비율 (실거래 전세가율과 다를 수 있음) | 현재 수치가 실거래 기준 70% 위험선·50% 안전선보다 높게 표시되는 것은 지수 기반 특성")
    else:
        st.warning("공통 지역 데이터가 없어 전세가율을 계산할 수 없습니다.")
else:
    st.info(
        "전세가율 차트는 위 아파트 가격지수 API 연결 후 자동으로 표시됩니다.",
        icon="📐"
    )

# ── 13. KOSPI / KOSDAQ ─────────────────────────────────
st.markdown('<div id="kosdaq"></div>', unsafe_allow_html=True)
st.subheader("📊 KOSPI / KOSDAQ")

kospi  = _mkt_p3.get("^KS11")
kosdaq = _mkt_p3.get("^KQ11")

col_ks, col_kq = st.columns(2)

with col_ks:
    if kospi is not None and not kospi.empty:
        kospi     = kospi.squeeze()
        ks_change = ((kospi.iloc[-1] / kospi.iloc[0]) - 1) * 100
        st.metric("KOSPI (latest)", f"{float(kospi.iloc[-1]):,.2f}", f"{float(ks_change):.1f}%")
        if ks_change >= 5:
            st.markdown("🟢 **강세** — 기간 내 +5% 이상")
        elif ks_change <= -5:
            st.markdown("🔴 **약세** — 기간 내 -5% 이하")
        else:
            st.markdown("🟡 **보합** — 기간 내 ±5% 이내")
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=kospi.index, y=kospi.values.flatten(),
            mode="lines", name="KOSPI",
            line=dict(color="crimson", width=2),
            fill="tozeroy",
        ))
        _ks_pad = (float(kospi.max()) - float(kospi.min())) * 0.08
        fig.update_layout(title="KOSPI Composite Index", height=320,
                          xaxis_title="Date", yaxis_title="Index Level")
        fig.update_yaxes(range=[max(0, float(kospi.min()) - _ks_pad), float(kospi.max()) + _ks_pad])
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.error("Failed to load KOSPI data. (ticker: ^KS11)")

with col_kq:
    if kosdaq is not None and not kosdaq.empty:
        kosdaq    = kosdaq.squeeze()
        kq_change = ((kosdaq.iloc[-1] / kosdaq.iloc[0]) - 1) * 100
        st.metric("KOSDAQ (latest)", f"{float(kosdaq.iloc[-1]):,.2f}", f"{float(kq_change):.1f}%")
        if kq_change >= 5:
            st.markdown("🟢 **강세** — 기간 내 +5% 이상")
        elif kq_change <= -5:
            st.markdown("🔴 **약세** — 기간 내 -5% 이하")
        else:
            st.markdown("🟡 **보합** — 기간 내 ±5% 이내")
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=kosdaq.index, y=kosdaq.values.flatten(),
            mode="lines", name="KOSDAQ",
            line=dict(color="mediumvioletred", width=2),
            fill="tozeroy",
        ))
        _kq_pad = (float(kosdaq.max()) - float(kosdaq.min())) * 0.08
        fig.update_layout(title="KOSDAQ Composite Index", height=320,
                          xaxis_title="Date", yaxis_title="Index Level")
        fig.update_yaxes(range=[max(0, float(kosdaq.min()) - _kq_pad), float(kosdaq.max()) + _kq_pad])
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.error("Failed to load KOSDAQ data. (ticker: ^KQ11)")

# Economic Dashboard — CLAUDE.md

## Project Overview
Streamlit-based economic dashboard (`dashboard.py`, 760 lines).
Working directory: `C:\Users\top00\Claudeworks\dashboard\`
Run command: `py -m streamlit run dashboard.py`

---

## Architecture

### Data Sources (5개)
| Source | Library/API | What it provides | Cache TTL |
|---|---|---|---|
| **yfinance** | `yf.download()` | Market tickers (exchange rates, indices, commodities) | 3600s |
| **FRED** | `fredapi.Fred` | US/Korea macro indicators (rates, CPI, M2, GDP) | 3600s |
| **한국부동산원 data.go.kr** | `requests` GET | Apartment price index (매매/전세) | 3600s |
| **한국부동산원 R-ONE** | `requests` GET | Apartment price fallback | 3600s |
| *(planned)* | — | — | — |

### Key Functions
- `get_data(ticker, period)` — single yfinance fetch
- `get_data_batch(tickers, period)` — **parallel** fetch via ThreadPoolExecutor(max_workers=6)
- `get_fred_data(series_id, start, end)` — FRED single series
- `get_apt_price_index(service_key, start_ym, end_ym)` — apartment API with probe/fallback logic

### Dashboard Sections (Phases)
- **Phase 1 — Global**: Exchange Rate, Gold/Silver, Major Indices, VIX, Oil
- **Phase 2 — US Macro**: Fed Rate vs CPI, M2, GDP, DXY
- **Phase 3 — Korea**: Korea Rate vs CPI, Apt Price Index, 전세가율, KOSDAQ

---

## API Keys (.env 파일로 관리)
- `.env` 파일에 저장 (`dashboard/.env`) — `.gitignore`로 커밋 제외
- `FRED_API_KEY` — FRED API
- `REB_API_KEY` — R-ONE 한국부동산원 API

---

## Known Issues & Fixes

### 아파트 가격지수 API ⚠️ 중요
- **data.go.kr (`apis.data.go.kr/1611000/*`) 절대 사용 금지** — 이 프로젝트 키는 data.go.kr 키가 아님
- **인증키는 R-ONE (한국부동산원) 전용**: `www.reb.or.kr/r-one/openapi/` 에서만 유효
- 기존 코드의 `SttsApiTblData.do` → 잘못된 엔드포인트, **`SttsApiTbl.do`** 가 맞음

### R-ONE API 정확한 스펙
- **URL**: `https://www.reb.or.kr/r-one/openapi/SttsApiTbl.do`
- **인증키**: `29401f124ae44e13bb874ff5df08368e`
- **매매가격지수**: `STATBL_ID=A_2024_00045`
- **전세가격지수**: `STATBL_ID=A_2024_00050`
- **항목코드**: `ITEM_CD2=100001` (지수)
- **지역코드** (`ITEM_CD`): 전국=500001, 수도권=500002, 지방권=500003, 서울=500008
- **공통 파라미터**: `Type=json`, `pIndex=1`, `pSize=200`

### 기타
- Auto-update 실패 중 (`/status` 로 확인 필요)

---

## 작업 규칙

### 실행 방식
- 모든 파일/폴더 작업은 PowerShell 대신 **Python 스크립트로 실행**할 것

---

## Rules for Claude Code

### ⛔ 하지 말 것
- 명시적 요청 없이 **작동하는 코드 리팩토링 금지**
- `@st.cache_data` 제거 또는 TTL 변경 금지 (성능에 직결)
- API key 변경 금지
- 한 번에 여러 섹션 동시 수정 금지
- **루트에 임시 파일·스크린샷·스크립트 생성 금지** — 반드시 `_work/` 안에서만 생성할 것

### ✅ 해야 할 것
- 작업 전 **변경할 함수/라인 번호 먼저 명시**하고 확인받기
- 10줄 이상 변경 시 **diff 요약 먼저 보여주기**
- 새 데이터 소스 추가 시 이 CLAUDE.md의 Data Sources 표 업데이트

### 📌 작업 단위 원칙
- 기능 하나 = PR 하나 = 커밋 하나
- "Phase N 전체 수정" 같은 큰 단위 지시는 거부하고 쪼개서 확인받기
- 수정 완료 후 반드시 `py -m streamlit run dashboard.py` 로 실행 확인

---

## Ticker Reference
```
USDKRW=X, EURKRW=X   — 환율
GC=F, SI=F            — 금/은
^GSPC, ^KS11, ^IXIC   — S&P500, KOSPI, NASDAQ
^VIX                  — 공포지수
CL=F                  — WTI 원유
DX-Y.NYB              — 달러인덱스 DXY
^KQ11                 — KOSDAQ
```

## FRED Series Reference
```
FEDFUNDS              — Fed Funds Rate
CPIAUCSL              — US CPI
M2SL                  — M2 Money Supply
GDPC1                 — Real GDP
IR3TIB01KRM156N       — Korea 3M T-Bill (BOK 기준금리 proxy)
KORCPIALLMINMEI       — Korea CPI
```

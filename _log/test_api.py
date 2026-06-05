import requests

KEY = "29401f124ae44e13bb874ff5df08368e"
URL = "https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do"

params = {
    "KEY": KEY,
    "STATBL_ID": "A_2024_00045",
    "ITEM_CD2": "100001",
    "CLS_ID": 500001,
    "Type": "json",
    "pIndex": 1,
    "pSize": 60,
    "DTACYCLE_CD": "MM",
    "START_WRTTIME": "202001",
    "END_WRTTIME": "202606",
}

r = requests.get(URL, params=params, timeout=10)
print(f"Status: {r.status_code}")
raw = r.content.decode("utf-8", errors="replace")
print(raw[:1200])

import requests

KEY = '29401f124ae44e13bb874ff5df08368e'
BASE_URL = 'https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do'

params = dict(KEY=KEY, STATBL_ID='A_2024_00045', ITEM_CD2='100001',
              CLS_ID=500001, Type='json', pIndex=3, pSize=100, DTACYCLE_CD='MM')
r = requests.get(BASE_URL, params=params, timeout=15).json()
blocks = r.get('SttsApiTblData', [])
rows = blocks[1].get('row', []) if len(blocks) > 1 else []
print(f'Got {len(rows)} rows on page 3')
if rows:
    first_dt = rows[0]['WRTTIME_IDTFR_ID']
    last_dt = rows[-1]['WRTTIME_IDTFR_ID']
    print(f'First: {first_dt}  Last: {last_dt}')

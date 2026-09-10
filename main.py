from fastapi import FastAPI, HTTPException
import requests
import os

app = FastAPI(title="GoldMatrix AI Bridge")

CAPITAL_API_KEY = os.getenv("CAPITAL_API_KEY")
CAPITAL_IDENTIFIER = os.getenv("CAPITAL_IDENTIFIER")
CAPITAL_PASSWORD = os.getenv("CAPITAL_API_PASSWORD")
FRED_API_KEY = os.getenv("FRED_API_KEY")

CAPITAL_BASE_URL = "https://demo-api-capital.backend-capital.com/api/v1"

EPIC_MAP = {
    "GOLD": "GOLD",
    "XAUUSD": "GOLD",
    "XAU/USD": "GOLD",
    "OIL": "OIL_CRUDE",
    "WTI": "OIL_CRUDE",
    "US500": "US500",
    "SPX": "US500"
}

def get_capital_session():
    if not all([CAPITAL_API_KEY, CAPITAL_IDENTIFIER, CAPITAL_PASSWORD]):
        raise HTTPException(status_code=500, detail="Capital.com credentials missing in Environment Variables")

    # 1. إنشاء الجلسة الرئيسية
    session_url = f"{CAPITAL_BASE_URL}/session"
    headers = {
        "X-CAP-API-KEY": CAPITAL_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "identifier": CAPITAL_IDENTIFIER,
        "password": CAPITAL_PASSWORD
    }
    
    response = requests.post(session_url, json=payload, headers=headers)
    
    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code, 
            detail=f"Capital Auth Failed: {response.text}"
        )
    
    cst = response.headers.get("CST")
    x_security_token = response.headers.get("X-SECURITY-TOKEN")
    
    auth_headers = {
        "X-CAP-API-KEY": CAPITAL_API_KEY,
        "CST": cst,
        "X-SECURITY-TOKEN": x_security_token
    }

    # 2. التغلب على خطأ null.accountId عبر جلب الحساب الأول وتثبيته
    acc_response = requests.get(f"{CAPITAL_BASE_URL}/accounts", headers=auth_headers)
    if acc_response.status_code == 200:
        accounts_data = acc_response.json()
        accounts = accounts_data.get("accounts", [])
        if accounts:
            active_account_id = accounts[0].get("accountId")
            # تحويل الجلسة إلى الحساب النشط
            requests.put(
                f"{CAPITAL_BASE_URL}/session", 
                json={"accountId": active_account_id}, 
                headers=auth_headers
            )

    return cst, x_security_token

@app.get("/market-data/{epic}")
def get_market_data(epic: str, resolution: str = "MINUTE_15", max_candles: int = 10):
    try:
        clean_epic = EPIC_MAP.get(epic.upper(), epic.upper())
        cst, security_token = get_capital_session()
        
        url = f"{CAPITAL_BASE_URL}/prices/{clean_epic}?resolution={resolution}&max={max_candles}"
        headers = {
            "X-CAP-API-KEY": CAPITAL_API_KEY,
            "CST": cst,
            "X-SECURITY-TOKEN": security_token
        }
        res = requests.get(url, headers=headers)
        
        if res.status_code != 200:
            raise HTTPException(
                status_code=res.status_code, 
                detail=f"Capital Price Fetch Failed: {res.text}"
            )
            
        return res.json()
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/fred/{series_id}")
def get_fred_data(series_id: str):
    if not FRED_API_KEY:
        raise HTTPException(status_code=500, detail="FRED_API_KEY missing in Environment Variables")
        
    url = f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}&sort_order=desc&limit=1&file_type=json&api_key={FRED_API_KEY}"
    res = requests.get(url)
    if res.status_code == 200:
        return res.json()
    raise HTTPException(status_code=res.status_code, detail="FRED API Request Failed")

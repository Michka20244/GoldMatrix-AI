from fastapi import FastAPI, HTTPException
import requests
import os

app = FastAPI(title="GoldMatrix AI Bridge")

CAPITAL_API_KEY = os.getenv("CAPITAL_API_KEY")
CAPITAL_IDENTIFIER = os.getenv("CAPITAL_IDENTIFIER")
CAPITAL_PASSWORD = os.getenv("CAPITAL_PASSWORD")
FRED_API_KEY = os.getenv("FRED_API_KEY", "74d61b160736c0601a12eebe47a17f24")

CAPITAL_BASE_URL = "https://demo-api-capital.backend-capital.com/api/v1"

def get_capital_session():
    url = f"{CAPITAL_BASE_URL}/session"
    headers = {
        "X-CAP-API-KEY": CAPITAL_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "identifier": CAPITAL_IDENTIFIER,
        "password": CAPITAL_PASSWORD
    }
    response = requests.post(url, json=payload, headers=headers)
    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="Capital.com Authentication Failed")
    
    cst = response.headers.get("CST")
    x_security_token = response.headers.get("X-SECURITY-TOKEN")
    return cst, x_security_token

@app.get("/market-data/{epic}")
def get_market_data(epic: str, resolution: str = "MINUTE_15", max_candles: int = 10):
    try:
        cst, security_token = get_capital_session()
        url = f"{CAPITAL_BASE_URL}/prices/{epic}?resolution={resolution}&max={max_candles}"
        headers = {
            "X-CAP-API-KEY": CAPITAL_API_KEY,
            "CST": cst,
            "X-SECURITY-TOKEN": security_token
        }
        res = requests.get(url, headers=headers)
        return res.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/fred/{series_id}")
def get_fred_data(series_id: str):
    url = f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}&sort_order=desc&limit=1&file_type=json&api_key={FRED_API_KEY}"
    res = requests.get(url)
    if res.status_code == 200:
        return res.json()
    raise HTTPException(status_code=res.status_code, detail="FRED API Request Failed")

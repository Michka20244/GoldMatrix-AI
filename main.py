from fastapi import FastAPI, HTTPException
import requests
import os
import time

app = FastAPI(title="GoldMatrix AI Bridge")

# ---------------------------------------------------------
# Environment Variables
# ---------------------------------------------------------
CAPITAL_API_KEY = os.getenv("CAPITAL_API_KEY")
CAPITAL_IDENTIFIER = os.getenv("CAPITAL_IDENTIFIER")
CAPITAL_PASSWORD = os.getenv("CAPITAL_PASSWORD") or os.getenv("CAPITAL_API_PASSWORD")
FRED_API_KEY = os.getenv("FRED_API_KEY")

# Base URLs
CAPITAL_BASE_URL = "https://demo-api-capital.backend-capital.com/api/v1"
FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

# Timeframe / Resolution Map
RESOLUTION_MAP = {
    "M1": "MINUTE",
    "M5": "MINUTE_5",
    "M15": "MINUTE_15",
    "M30": "MINUTE_30",
    "H1": "HOUR",
    "H4": "HOUR_4",
    "D1": "DAY",
    "W1": "WEEK"
}

# Static Fallback EPIC Map
EPIC_MAP = {
    "GOLD": "GOLD",
    "XAUUSD": "GOLD",
    "XAU/USD": "GOLD",
    "SILVER": "SILVER",
    "XAGUSD": "SILVER",
    "OIL": "OIL_CRUDE",
    "WTI": "OIL_CRUDE",
    "BRENT": "OIL_BRENT",
    "US500": "US500",
    "SPX": "US500",
    "NAS100": "US100",
    "US30": "US30"
}

# Session & EPIC Cache Memory
session_cache = {
    "cst": None,
    "security_token": None,
    "last_used": 0
}
epic_cache = {}

# ---------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------
def assert_credentials():
    missing = []
    if not CAPITAL_API_KEY:
        missing.append("CAPITAL_API_KEY")
    if not CAPITAL_IDENTIFIER:
        missing.append("CAPITAL_IDENTIFIER")
    if not CAPITAL_PASSWORD:
        missing.append("CAPITAL_PASSWORD (or CAPITAL_API_PASSWORD)")
    if missing:
        raise HTTPException(
            status_code=500,
            detail=f"Capital.com environment variables are missing: {', '.join(missing)}"
        )

def get_capital_session():
    """ Authenticates with Capital.com using encryptedPassword: False """
    assert_credentials()
    
    now = time.time()
    # reuse active session if used within last 8 minutes (480 seconds)
    if session_cache["cst"] and session_cache["security_token"] and (now - session_cache["last_used"] < 480):
        return session_cache["cst"], session_cache["security_token"]

    url = f"{CAPITAL_BASE_URL}/session"
    headers = {
        "X-CAP-API-KEY": CAPITAL_API_KEY,
        "Content-Type": "application/json"
    }
    
    # Crucial Fix: encryptedPassword=False ensures plain text password acceptance
    payload = {
        "identifier": CAPITAL_IDENTIFIER,
        "password": CAPITAL_PASSWORD,
        "encryptedPassword": False
    }

    try:
        res = requests.post(url, json=payload, headers=headers, timeout=10)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Network error connecting to Capital.com: {str(e)}")

    if res.status_code != 200:
        raise HTTPException(
            status_code=res.status_code,
            detail=f"Capital Auth Failed (HTTP {res.status_code}): {res.text}"
        )

    cst = res.headers.get("CST")
    security_token = res.headers.get("X-SECURITY-TOKEN")

    if not cst or not security_token:
        raise HTTPException(status_code=500, detail="Capital session response missing CST or X-SECURITY-TOKEN headers")

    # Ensure active account selection to prevent error.null.accountId
    auth_headers = {
        "X-CAP-API-KEY": CAPITAL_API_KEY,
        "CST": cst,
        "X-SECURITY-TOKEN": security_token
    }
    
    try:
        acc_res = requests.get(f"{CAPITAL_BASE_URL}/accounts", headers=auth_headers, timeout=10)
        if acc_res.status_code == 200:
            accounts = acc_res.json().get("accounts", [])
            if accounts:
                active_acc_id = accounts[0].get("accountId")
                requests.put(
                    f"{CAPITAL_BASE_URL}/session",
                    json={"accountId": active_acc_id},
                    headers=auth_headers,
                    timeout=5
                )
    except Exception:
        pass  # Continue if single account setup

    session_cache["cst"] = cst
    session_cache["security_token"] = security_token
    session_cache["last_used"] = now

    return cst, security_token

def resolve_epic(symbol: str) -> str:
    """ Resolves canonical symbol to Capital EPIC """
    clean_symbol = symbol.upper().replace("/", "").replace(" ", "").replace("_", "")
    
    # Check static map first
    if clean_symbol in EPIC_MAP:
        return EPIC_MAP[clean_symbol]

    # Check dynamic cache
    if clean_symbol in epic_cache:
        return epic_cache[clean_symbol]

    # Dynamic search fallback via Capital API
    cst, security_token = get_capital_session()
    headers = {
        "X-CAP-API-KEY": CAPITAL_API_KEY,
        "CST": cst,
        "X-SECURITY-TOKEN": security_token
    }
    
    search_url = f"{CAPITAL_BASE_URL}/markets?searchTerm={clean_symbol}"
    res = requests.get(search_url, headers=headers, timeout=10)
    
    if res.status_code == 200:
        markets = res.json().get("markets", [])
        if markets:
            resolved = markets[0].get("epic")
            epic_cache[clean_symbol] = resolved
            return resolved

    # Default to input if search yields nothing
    return clean_symbol

# ---------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------

@app.get("/")
def root():
    return {"status": "online", "service": "GoldMatrix AI Bridge"}

@app.get("/market-data/{epic}")
def get_market_data(epic: str, resolution: str = "MINUTE_15", max_candles: int = 10):
    """ Fetches OHLC historical candles for a given EPIC or symbol """
    try:
        cst, security_token = get_capital_session()
        
        # Map timeframe alias if provided (e.g. M15 -> MINUTE_15)
        clean_resolution = RESOLUTION_MAP.get(resolution.upper(), resolution.upper())
        resolved_epic = resolve_epic(epic)

        url = f"{CAPITAL_BASE_URL}/prices/{resolved_epic}?resolution={clean_resolution}&max={max_candles}"
        headers = {
            "X-CAP-API-KEY": CAPITAL_API_KEY,
            "CST": cst,
            "X-SECURITY-TOKEN": security_token
        }
        
        res = requests.get(url, headers=headers, timeout=10)

        # Retry once on session expiration (HTTP 401)
        if res.status_code == 401:
            session_cache["cst"] = None
            cst, security_token = get_capital_session()
            headers["CST"] = cst
            headers["X-SECURITY-TOKEN"] = security_token
            res = requests.get(url, headers=headers, timeout=10)

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
    """ Fetches macroeconomic observations from St. Louis FRED API """
    if not FRED_API_KEY:
        raise HTTPException(status_code=500, detail="FRED_API_KEY is missing in Environment Variables")

    url = f"{FRED_BASE_URL}?series_id={series_id}&sort_order=desc&limit=1&file_type=json&api_key={FRED_API_KEY}"
    
    try:
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            return res.json()
        raise HTTPException(status_code=res.status_code, detail=f"FRED API Failed: {res.text}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

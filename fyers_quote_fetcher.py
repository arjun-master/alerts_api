import os
import base64
import pyotp
import requests
from fyers_apiv3 import fyersModel
from urllib.parse import parse_qs, urlparse
from datetime import datetime, timedelta

# User credentials and app details (replace with your actual values or load from env)
redirect_uri = "https://127.0.0.1:5000/"
client_id = 'RWCTF2HW7T-100'
secret_key = '9PZG0GHS3D'
FY_ID = "XR00722"
TOTP_KEY = "DGAIVG64HJDJ4CGG6YKMTEHOMH2T2MXE"
PIN = "2580"


def getEncodedString(string):
    string = str(string)
    base64_bytes = base64.b64encode(string.encode("ascii"))
    return base64_bytes.decode("ascii")


def get_access_token():
    URL_SEND_LOGIN_OTP = "https://api-t2.fyers.in/vagator/v2/send_login_otp_v2"
    res = requests.post(url=URL_SEND_LOGIN_OTP, json={"fy_id": getEncodedString(FY_ID), "app_id": "2"}).json()
    if "request_key" not in res:
        raise Exception(f"Failed to send login OTP: {res}")

    URL_VERIFY_OTP = "https://api-t2.fyers.in/vagator/v2/verify_otp"
    res2 = requests.post(url=URL_VERIFY_OTP, json={"request_key": res["request_key"], "otp": pyotp.TOTP(TOTP_KEY).now()}).json()
    if "request_key" not in res2:
        raise Exception(f"Failed to verify OTP: {res2}")

    ses = requests.Session()
    URL_VERIFY_OTP2 = "https://api-t2.fyers.in/vagator/v2/verify_pin_v2"
    payload2 = {"request_key": res2["request_key"], "identity_type": "pin", "identifier": getEncodedString(PIN)}
    res3 = ses.post(url=URL_VERIFY_OTP2, json=payload2).json()
    if "data" not in res3 or "access_token" not in res3["data"]:
        raise Exception(f"Failed to verify PIN: {res3}")

    ses.headers.update({'authorization': f"Bearer {res3['data']['access_token']}"})

    TOKENURL = "https://api-t1.fyers.in/api/v3/token"
    payload3 = {"fyers_id": FY_ID,
                "app_id": client_id[:-4],
                "redirect_uri": redirect_uri,
                "appType": "100", "code_challenge": "",
                "state": "None", "scope": "", "nonce": "", "response_type": "code", "create_cookie": True}
    res4 = ses.post(url=TOKENURL, json=payload3).json()
    if 'Url' not in res4:
        raise Exception(f"Failed to get auth URL: {res4}")
    url = res4['Url']
    parsed = urlparse(url)
    auth_code = parse_qs(parsed.query)['auth_code'][0]

    session = fyersModel.SessionModel(
        client_id=client_id,
        secret_key=secret_key,
        redirect_uri=redirect_uri,
        response_type="code",
        grant_type="authorization_code"
    )
    session.set_token(auth_code)
    response = session.generate_token()
    if 'access_token' not in response:
        raise Exception(f"Failed to generate access token: {response}")
    return response['access_token']


def get_fyers_client():
    access_token = get_access_token()
    fyers = fyersModel.FyersModel(client_id=client_id, is_async=False, token=access_token, log_path=os.getcwd())
    return fyers


def fetch_quotes(symbols):
    """
    symbols: list of strings, e.g. ["NSE:RELIANCE-EQ", "NSE:TCS-EQ"]
    Returns: dict of quotes
    """
    fyers = get_fyers_client()
    symbol_str = ",".join(symbols)
    quote_data = {"symbols": symbol_str}
    return fyers.quotes(quote_data)


def get_previous_day_ohlc(symbol):
    """
    Fetch previous day's OHLC for a single symbol.
    Returns: dict with ohlc data or None if not available.
    """
    fyers = get_fyers_client()
    prev_day = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    data = {
        "symbol": symbol,
        "resolution": "D",
        "date_format": "1",
        "range_from": prev_day,
        "range_to": prev_day,
        "cont_flag": "1"
    }
    response = fyers.history(data)
    if response.get("s") == "ok" and response.get("candles"):
        ohlc = response["candles"][0]  # [timestamp, open, high, low, close, volume]
        return {
            "date": prev_day,
            "open": ohlc[1],
            "high": ohlc[2],
            "low": ohlc[3],
            "close": ohlc[4],
            "volume": ohlc[5]
        }
    return None


def get_previous_day_ohlc_bulk(symbols):
    """
    Fetch previous day's OHLC for a list of symbols.
    Returns: dict mapping symbol to ohlc dict or None.
    """
    results = {}
    for symbol in symbols:
        results[symbol] = get_previous_day_ohlc(symbol)
    return results 
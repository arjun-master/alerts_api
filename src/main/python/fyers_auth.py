#!/usr/bin/env python
# coding: utf-8

import os
import pyotp
import requests
import json
import math
import pytz
import warnings
import pandas as pd
import base64
from datetime import datetime, timedelta, date
from time import sleep
from urllib.parse import parse_qs, urlparse
from fyers_apiv3 import fyersModel

pd.set_option('display.max_columns', None)
warnings.filterwarnings('ignore')

# Configuration
redirect_uri = "https://127.0.0.1:5000/"
client_id = 'RWCTF2HW7T-100'
secret_key = '9PZG0GHS3D'
FY_ID = "XR00722"  # Your fyers ID
TOTP_KEY = "DGAIVG64HJDJ4CGG6YKMTEHOMH2T2MXE"  # TOTP secret
PIN = "2580"  # User pin for fyers account

def getEncodedString(string):
    string = str(string)
    base64_bytes = base64.b64encode(string.encode("ascii"))
    return base64_bytes.decode("ascii")

# Step 1: Send Login OTP
URL_SEND_LOGIN_OTP = "https://api-t2.fyers.in/vagator/v2/send_login_otp_v2"
res = requests.post(url=URL_SEND_LOGIN_OTP, json={"fy_id": getEncodedString(FY_ID), "app_id": "2"}).json()
print("Step 1 - Send Login OTP Response:", res)

# Step 2: Verify OTP
if datetime.now().second % 30 > 27:
    sleep(5)
URL_VERIFY_OTP = "https://api-t2.fyers.in/vagator/v2/verify_otp"
res2 = requests.post(url=URL_VERIFY_OTP, json={"request_key": res["request_key"], "otp": pyotp.TOTP(TOTP_KEY).now()}).json()
print("Step 2 - Verify OTP Response:", res2)

# Step 3: Verify PIN
ses = requests.Session()
URL_VERIFY_OTP2 = "https://api-t2.fyers.in/vagator/v2/verify_pin_v2"
payload2 = {"request_key": res2["request_key"], "identity_type": "pin", "identifier": getEncodedString(PIN)}
res3 = ses.post(url=URL_VERIFY_OTP2, json=payload2).json()
print("Step 3 - Verify PIN Response:", res3)

# Step 4: Set authorization header
ses.headers.update({
    'authorization': f"Bearer {res3['data']['access_token']}"
})

# Step 5: Get token
TOKENURL = "https://api-t1.fyers.in/api/v3/token"
payload3 = {
    "fyers_id": FY_ID,
    "app_id": client_id[:-4],
    "redirect_uri": redirect_uri,
    "appType": "100",
    "code_challenge": "",
    "state": "None",
    "scope": "",
    "nonce": "",
    "response_type": "code",
    "create_cookie": True
}

res3 = ses.post(url=TOKENURL, json=payload3).json()
print("Step 5 - Get Token Response:", res3)

# Step 6: Extract auth code
auth_code = res3['data']['auth']
print("Auth Code:", auth_code)

# Step 7: Generate access token
grant_type = "authorization_code"
response_type = "code"

session = fyersModel.SessionModel(
    client_id=client_id,
    secret_key=secret_key,
    redirect_uri=redirect_uri,
    response_type=response_type,
    grant_type=grant_type
)

# Set the authorization code in the session object
session.set_token(auth_code)

# Generate the access token using the authorization code
response = session.generate_token()
print("Access Token Response:", response)

access_token = response['access_token']

# Initialize the FyersModel instance
fyers = fyersModel.FyersModel(
    client_id=client_id,
    is_async=False,
    token=access_token,
    log_path=os.getcwd()
)

# Get user profile
profile = fyers.get_profile()
print("User Profile:", profile) 
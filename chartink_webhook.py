import os
import base64
import pyotp
import requests
import logging
import json
from flask import Flask, request, jsonify
from datetime import datetime, timedelta
from dotenv import load_dotenv
from logging.handlers import RotatingFileHandler

# Create logs directory in the current working directory
log_dir = os.path.join(os.getcwd(), 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'webhook.log')

# Configure logging with rotation
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(
            log_file,
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
    ]
)
logger = logging.getLogger(__name__)

# Log startup information
logger.info("="*50)
logger.info("Starting webhook server")
logger.info(f"Current working directory: {os.getcwd()}")
logger.info(f"Log file location: {log_file}")
logger.info(f"Python version: {os.sys.version}")
logger.info("="*50)

# Load environment variables from .env file
load_dotenv()
logger.info("Environment variables loaded")

# Configuration
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8199254732:AAEn-4X-z87-pSp1SKcJEjJjoyewXvOxmfg")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "-1002511791814")
FYERS_CLIENT_ID = os.getenv("FYERS_CLIENT_ID", "RWCTF2HW7T-100")
FYERS_SECRET_KEY = os.getenv("FYERS_SECRET_KEY", "9PZG0GHS3D")
FYERS_ID = os.getenv("FYERS_ID", "XR00722")
FYERS_TOTP_KEY = os.getenv("FYERS_TOTP_KEY", "DGAIVG64HJDJ4CGG6YKMTEHOMH2T2MXE")
FYERS_PIN = os.getenv("FYERS_PIN", "2580")
FYERS_REDIRECT_URI = os.getenv("FYERS_REDIRECT_URI", "https://trade.fyers.in/api-login/redirect-uri/index.html")

# Log configuration (without sensitive data)
logger.info("Configuration loaded:")
logger.info(f"TELEGRAM_CHAT_ID: {TELEGRAM_CHAT_ID}")
logger.info(f"FYERS_CLIENT_ID: {FYERS_CLIENT_ID}")
logger.info(f"FYERS_ID: {FYERS_ID}")
logger.info(f"FYERS_REDIRECT_URI: {FYERS_REDIRECT_URI}")

app = Flask(__name__)

def getEncodedString(string):
    """Encode string to base64"""
    string = str(string)
    base64_bytes = base64.b64encode(string.encode("ascii"))
    return base64_bytes.decode("ascii")

def get_fyers_access_token():
    """Get Fyers access token using TOTP and PIN"""
    try:
        logger.info("Starting Fyers authentication process")
        
        # Step 1: Send Login OTP
        logger.info("Step 1: Sending login OTP")
        URL_SEND_LOGIN_OTP = "https://api-t2.fyers.in/vagator/v2/send_login_otp_v2"
        res = requests.post(url=URL_SEND_LOGIN_OTP, json={"fy_id": getEncodedString(FYERS_ID), "app_id": "2"}).json()
        logger.info(f"Login OTP response: {res}")
        if "request_key" not in res:
            raise Exception(f"Failed to send login OTP: {res}")

        # Step 2: Verify OTP
        logger.info("Step 2: Verifying OTP")
        URL_VERIFY_OTP = "https://api-t2.fyers.in/vagator/v2/verify_otp"
        otp = pyotp.TOTP(FYERS_TOTP_KEY).now()
        logger.info(f"Generated TOTP: {otp}")
        res2 = requests.post(url=URL_VERIFY_OTP, json={"request_key": res["request_key"], "otp": otp}).json()
        logger.info(f"OTP verification response: {res2}")
        if "request_key" not in res2:
            raise Exception(f"Failed to verify OTP: {res2}")

        # Step 3: Verify PIN
        logger.info("Step 3: Verifying PIN")
        ses = requests.Session()
        URL_VERIFY_OTP2 = "https://api-t2.fyers.in/vagator/v2/verify_pin_v2"
        payload2 = {"request_key": res2["request_key"], "identity_type": "pin", "identifier": getEncodedString(FYERS_PIN)}
        res3 = ses.post(url=URL_VERIFY_OTP2, json=payload2).json()
        logger.info(f"PIN verification response: {res3}")
        if "data" not in res3 or "access_token" not in res3["data"]:
            raise Exception(f"Failed to verify PIN: {res3}")

        ses.headers.update({'authorization': f"Bearer {res3['data']['access_token']}"})

        # Step 4: Get Auth Code
        logger.info("Step 4: Getting auth code")
        TOKENURL = "https://api-t1.fyers.in/api/v3/token"
        payload3 = {
            "fyers_id": FYERS_ID,
            "app_id": FYERS_CLIENT_ID[:-4],
            "redirect_uri": FYERS_REDIRECT_URI,
            "appType": "100", "code_challenge": "",
            "state": "None", "scope": "", "nonce": "", "response_type": "code", "create_cookie": True
        }
        res4 = ses.post(url=TOKENURL, json=payload3).json()
        logger.info(f"Auth code response: {res4}")
        if 'Url' not in res4:
            raise Exception(f"Failed to get auth URL: {res4}")
        
        # Extract auth code from URL
        from urllib.parse import parse_qs, urlparse
        url = res4['Url']
        parsed = urlparse(url)
        auth_code = parse_qs(parsed.query)['auth_code'][0]
        logger.info(f"Extracted auth code: {auth_code}")

        # Step 5: Exchange Auth Code for Access Token
        logger.info("Step 5: Exchanging auth code for access token")
        from fyers_apiv3 import fyersModel
        session = fyersModel.SessionModel(
            client_id=FYERS_CLIENT_ID,
            secret_key=FYERS_SECRET_KEY,
            redirect_uri=FYERS_REDIRECT_URI,
            response_type="code",
            grant_type="authorization_code"
        )
        session.set_token(auth_code)
        response = session.generate_token()
        logger.info(f"Token generation response: {response}")
        if "access_token" not in response:
            raise Exception(f"Failed to get access token: {response}")
        
        logger.info("Successfully obtained Fyers access token")
        return response["access_token"]
    except Exception as e:
        logger.error(f"Error getting Fyers access token: {str(e)}", exc_info=True)
        raise

def get_historical_closes(access_token, symbols):
    """Get historical close prices for given symbols"""
    logger.info(f"Fetching historical closes for symbols: {symbols}")
    closes = {}
    today = datetime.now().date()
    headers = {"Authorization": f"Bearer {access_token}"}
    
    for symbol in symbols:
        logger.info(f"Processing symbol: {symbol}")
        closes[symbol] = {}
        for days_back, label in zip([1, 3, 7], ["prev_day", "three_days_back", "seven_days_back"]):
            date = today - timedelta(days=days_back)
            data = {
                "symbol": symbol,
                "resolution": "D",
                "date_format": "1",
                "range_from": date.strftime("%Y-%m-%d"),
                "range_to": date.strftime("%Y-%m-%d"),
                "cont_flag": "1"
            }
            logger.info(f"Fetching {label} data for {symbol} on {date}")
            try:
                response = requests.post("https://api.fyers.in/data/history", headers=headers, json=data)
                logger.info(f"Fyers API Response Status: {response.status_code}")
                logger.info(f"Fyers API Response Headers: {dict(response.headers)}")
                
                if response.status_code != 200:
                    logger.error(f"Fyers API returned non-200 status code: {response.status_code}")
                    logger.error(f"Response content: {response.text}")
                    closes[symbol][label] = None
                    continue
                
                try:
                    resp = response.json()
                    logger.info(f"Historical data response for {symbol} {label}: {resp}")
                    if resp.get("s") == "ok" and resp.get("candles"):
                        closes[symbol][label] = resp["candles"][0][4]  # close price
                    else:
                        closes[symbol][label] = None
                        logger.warning(f"No data found for {symbol} {label}. Response: {resp}")
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse JSON response for {symbol} {label}: {str(e)}")
                    logger.error(f"Raw response content: {response.text}")
                    closes[symbol][label] = None
            except requests.RequestException as e:
                logger.error(f"Request failed for {symbol} {label}: {str(e)}")
                closes[symbol][label] = None
    
    logger.info(f"Historical closes data: {closes}")
    return closes

def escape_markdown_v2(text):
    """Escape special characters for Telegram MarkdownV2"""
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = str(text).replace(char, f'\\{char}')
    return text

def format_message(data, closes):
    """Format message for Telegram"""
    logger.info("Formatting message for Telegram")
    msg = f"*{escape_markdown_v2(data.get('alert_name', 'N/A'))}*\n"
    msg += f"Scan: {escape_markdown_v2(data.get('scan_name', 'Unknown Scan'))}\n"
    msg += f"Stocks: *{escape_markdown_v2(data.get('stocks', 'No stocks'))}*\n"
    msg += f"Prices: {escape_markdown_v2(data.get('trigger_prices', 'N/A'))}\n"
    msg += f"Triggered At: {escape_markdown_v2(data.get('triggered_at', 'N/A'))}\n\n"
    msg += "*Historical Close Prices:*\n\n"
    
    for symbol, hist in closes.items():
        msg += f"*{escape_markdown_v2(symbol)}*\n"
        msg += f"Prev Day Close: {escape_markdown_v2(hist['prev_day'])}\n"
        msg += f"3 Days Back Close: {escape_markdown_v2(hist['three_days_back'])}\n"
        msg += f"7 Days Back Close: {escape_markdown_v2(hist['seven_days_back'])}\n\n"
    
    logger.info(f"Formatted message: {msg}")
    return msg

def send_telegram_message(message):
    """Send message to Telegram channel"""
    logger.info("Sending message to Telegram")
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "MarkdownV2"
    }
    logger.info(f"Telegram API request payload: {payload}")
    resp = requests.post(url, json=payload)
    logger.info(f"Telegram API response: {resp.text}")
    return resp.ok, resp.text

@app.route("/webhook", methods=["POST"])
def webhook():
    """Handle incoming webhook requests"""
    try:
        logger.info("Received webhook request")
        logger.info(f"Request headers: {dict(request.headers)}")
        logger.info(f"Request data: {request.get_data()}")
        
        data = request.json
        if not data:
            logger.error("No data received in webhook request")
            return jsonify({"status": "error", "message": "No data received"}), 400

        logger.info(f"Processing webhook data: {data}")

        # Process stocks
        stocks = [s.strip() for s in data.get("stocks", "").split(",") if s.strip()]
        formatted_stocks = []
        for stock in stocks:
            if not stock.startswith("NSE:"):
                stock = f"NSE:{stock}"
            if not stock.endswith("-EQ"):
                stock = f"{stock}-EQ"
            formatted_stocks.append(stock)
        
        logger.info(f"Formatted stocks: {formatted_stocks}")

        # Get Fyers access token and historical data
        logger.info("Getting Fyers access token")
        access_token = get_fyers_access_token()
        logger.info("Fetching historical closes")
        closes = get_historical_closes(access_token, formatted_stocks)
        
        # Format and send message
        logger.info("Formatting message")
        msg = format_message(data, closes)
        logger.info("Sending message to Telegram")
        success, response = send_telegram_message(msg)
        
        if success:
            logger.info("Webhook processed successfully")
            return jsonify({
                "status": "success",
                "message": "Webhook processed successfully"
            })
        else:
            logger.error(f"Failed to send message: {response}")
            return jsonify({
                "status": "error",
                "message": f"Failed to send message: {response}"
            })
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    logger.info("Starting webhook server")
    # For production, use gunicorn or uwsgi
    app.run(host="0.0.0.0", port=8080) 
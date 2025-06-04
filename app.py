import os
import base64
import pyotp
import requests
import logging
import json
import time
from flask import Flask, request, jsonify
from datetime import datetime, timedelta
from dotenv import load_dotenv
from logging.handlers import RotatingFileHandler
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib3 import PoolManager
import gc
import concurrent.futures
from functools import partial

# Create logs directory in the current working directory
log_dir = os.path.join(os.getcwd(), 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'webhook.log')
perf_log_file = os.path.join(log_dir, 'performance.log')
token_file = os.path.join(log_dir, 'fyers_token.json')

# Configure logging with rotation and reduced verbosity
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(
            log_file,
            maxBytes=5*1024*1024,
            backupCount=3,
            encoding='utf-8'
        )
    ]
)
logger = logging.getLogger(__name__)

# Configure performance logging
perf_logger = logging.getLogger('performance')
perf_logger.setLevel(logging.INFO)
perf_handler = RotatingFileHandler(
    perf_log_file,
    maxBytes=5*1024*1024,
    backupCount=3,
    encoding='utf-8'
)
perf_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
perf_logger.addHandler(perf_handler)

# Performance measurement decorator
def measure_performance(operation_name):
    def decorator(func):
        def wrapper(*args, **kwargs):
            start_time = time.time()
            start_memory = gc.get_count()
            result = func(*args, **kwargs)
            end_time = time.time()
            end_memory = gc.get_count()
            
            execution_time = (end_time - start_time) * 1000  # Convert to milliseconds
            memory_delta = tuple(e - s for e, s in zip(end_memory, start_memory))
            
            perf_logger.info(
                f"Operation: {operation_name} | "
                f"Time: {execution_time:.2f}ms | "
                f"Memory Delta: {memory_delta} | "
                f"Args: {args} | "
                f"Kwargs: {kwargs}"
            )
            return result
        return wrapper
    return decorator

def load_cached_token():
    """Load cached token from file if it exists and is from today"""
    try:
        if os.path.exists(token_file):
            with open(token_file, 'r') as f:
                token_data = json.load(f)
                token_date = datetime.fromisoformat(token_data['timestamp']).date()
                today = datetime.now().date()
                if token_date == today:  # Only use token if it's from today
                    logger.info(f"Using cached token from {token_date}")
                    return token_data['token']
                else:
                    logger.info(f"Cached token expired (from {token_date}, today is {today})")
    except json.JSONDecodeError as e:
        logger.error(f"Invalid token file format: {str(e)}")
    except Exception as e:
        logger.error(f"Error loading cached token: {str(e)}")
    return None

def save_token(token):
    """Save token to file with today's timestamp"""
    try:
        # Ensure logs directory exists
        os.makedirs(os.path.dirname(token_file), exist_ok=True)
        
        token_data = {
            'token': token,
            'timestamp': datetime.now().isoformat()
        }
        
        # Write to a temporary file first
        temp_file = f"{token_file}.tmp"
        with open(temp_file, 'w') as f:
            json.dump(token_data, f)
        
        # Atomic rename to ensure file integrity
        os.replace(temp_file, token_file)
        
        logger.info(f"Successfully saved new token for {datetime.now().date()}")
    except Exception as e:
        logger.error(f"Error saving token: {str(e)}")
        # Clean up temp file if it exists
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except:
                pass

# Load environment variables from .env file
load_dotenv()

# Configuration
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
FYERS_CLIENT_ID = os.getenv("FYERS_CLIENT_ID")
FYERS_SECRET_KEY = os.getenv("FYERS_SECRET_KEY")
FYERS_ID = os.getenv("FYERS_ID")
FYERS_TOTP_KEY = os.getenv("FYERS_TOTP_KEY")
FYERS_PIN = os.getenv("FYERS_PIN")
FYERS_REDIRECT_URI = os.getenv("FYERS_REDIRECT_URI")

# Validate required environment variables
required_vars = [
    "TELEGRAM_TOKEN",
    "TELEGRAM_CHAT_ID",
    "FYERS_CLIENT_ID",
    "FYERS_SECRET_KEY",
    "FYERS_ID",
    "FYERS_TOTP_KEY",
    "FYERS_PIN",
    "FYERS_REDIRECT_URI"
]

missing_vars = [var for var in required_vars if not os.getenv(var)]
if missing_vars:
    raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

# Create a session with connection pooling and retries
session = requests.Session()
retry_strategy = Retry(
    total=3,
    backoff_factor=0.5,
    status_forcelist=[500, 502, 503, 504]
)
adapter = HTTPAdapter(
    max_retries=retry_strategy,
    pool_connections=10,
    pool_maxsize=10,
    pool_block=False
)
session.mount("http://", adapter)
session.mount("https://", adapter)

app = Flask(__name__)

def getEncodedString(string):
    """Encode string to base64"""
    return base64.b64encode(str(string).encode("ascii")).decode("ascii")

@measure_performance("get_fyers_access_token")
def get_fyers_access_token():
    """Get Fyers access token using TOTP and PIN"""
    # Try to load cached token first
    cached_token = load_cached_token()
    if cached_token:
        logger.info("Using cached Fyers token")
        return cached_token

    logger.info("Generating new Fyers token")
    try:
        # Step 1: Send Login OTP
        URL_SEND_LOGIN_OTP = "https://api-t2.fyers.in/vagator/v2/send_login_otp_v2"
        payload = {"fy_id": getEncodedString(FYERS_ID), "app_id": "2"}
        logger.info(f"Sending login OTP request: POST {URL_SEND_LOGIN_OTP}")
        logger.info(f"Request payload: {json.dumps(payload, indent=2)}")
        
        res = session.post(
            url=URL_SEND_LOGIN_OTP,
            json=payload,
            timeout=10
        ).json()
        
        logger.info(f"Login OTP response: {json.dumps(res, indent=2)}")
        
        if "request_key" not in res:
            raise Exception(f"Failed to send login OTP: {res}")

        # Step 2: Verify OTP
        URL_VERIFY_OTP = "https://api-t2.fyers.in/vagator/v2/verify_otp"
        otp = pyotp.TOTP(FYERS_TOTP_KEY).now()
        payload = {"request_key": res["request_key"], "otp": otp}
        logger.info(f"Verifying OTP: POST {URL_VERIFY_OTP}")
        logger.info(f"Request payload: {json.dumps(payload, indent=2)}")
        
        res2 = session.post(
            url=URL_VERIFY_OTP,
            json=payload,
            timeout=10
        ).json()
        
        logger.info(f"OTP verification response: {json.dumps(res2, indent=2)}")
        
        if "request_key" not in res2:
            raise Exception(f"Failed to verify OTP: {res2}")

        # Step 3: Verify PIN
        URL_VERIFY_OTP2 = "https://api-t2.fyers.in/vagator/v2/verify_pin_v2"
        payload2 = {
            "request_key": res2["request_key"],
            "identity_type": "pin",
            "identifier": getEncodedString(FYERS_PIN)
        }
        logger.info(f"Verifying PIN: POST {URL_VERIFY_OTP2}")
        logger.info(f"Request payload: {json.dumps(payload2, indent=2)}")
        
        res3 = session.post(url=URL_VERIFY_OTP2, json=payload2, timeout=10).json()
        
        logger.info(f"PIN verification response: {json.dumps(res3, indent=2)}")
        
        if "data" not in res3 or "access_token" not in res3["data"]:
            raise Exception(f"Failed to verify PIN: {res3}")

        session.headers.update({'authorization': f"Bearer {res3['data']['access_token']}"})

        # Step 4: Get Auth Code
        TOKENURL = "https://api-t1.fyers.in/api/v3/token"
        payload3 = {
            "fyers_id": FYERS_ID,
            "app_id": FYERS_CLIENT_ID[:-4],
            "redirect_uri": FYERS_REDIRECT_URI,
            "appType": "100",
            "code_challenge": "",
            "state": "None",
            "scope": "",
            "nonce": "",
            "response_type": "code",
            "create_cookie": True
        }
        logger.info(f"Getting auth code: POST {TOKENURL}")
        logger.info(f"Request payload: {json.dumps(payload3, indent=2)}")
        
        res4 = session.post(url=TOKENURL, json=payload3, timeout=10).json()
        
        logger.info(f"Auth code response: {json.dumps(res4, indent=2)}")
        
        if 'Url' not in res4:
            raise Exception(f"Failed to get auth URL: {res4}")
        
        # Extract auth code from URL
        from urllib.parse import parse_qs, urlparse
        url = res4['Url']
        parsed = urlparse(url)
        auth_code = parse_qs(parsed.query)['auth_code'][0]
        logger.info(f"Extracted auth code: {auth_code}")

        # Step 5: Exchange Auth Code for Access Token
        from fyers_apiv3 import fyersModel
        session_model = fyersModel.SessionModel(
            client_id=FYERS_CLIENT_ID,
            secret_key=FYERS_SECRET_KEY,
            redirect_uri=FYERS_REDIRECT_URI,
            response_type="code",
            grant_type="authorization_code"
        )
        session_model.set_token(auth_code)
        logger.info("Exchanging auth code for access token")
        response = session_model.generate_token()
        
        logger.info(f"Access token response: {json.dumps(response, indent=2)}")
        
        if "access_token" not in response:
            raise Exception(f"Failed to get access token: {response}")
        
        # Save the new token
        save_token(response["access_token"])
        return response["access_token"]
    except Exception as e:
        logger.error(f"Error getting Fyers access token: {str(e)}")
        raise

def fetch_stock_data(symbols_batch, headers, today, use_historical):
    """Fetch data for a batch of stocks"""
    stock_data = {}
    try:
        # Get today's data for all stocks in batch
        if use_historical:
            # Get historical data for all stocks in one call
            data = {
                "symbols": symbols_batch,
                "resolution": "D",
                "date_format": "1",
                "range_from": today.strftime("%Y-%m-%d"),
                "range_to": today.strftime("%Y-%m-%d"),
                "cont_flag": "1"
            }
            response = session.post(
                "https://api.fyers.in/data/history",
                headers=headers,
                json=data,
                timeout=5
            )
            
            if response.status_code == 200:
                try:
                    resp = response.json()
                    if resp.get("s") == "ok" and resp.get("candles"):
                        for symbol, candle in zip(symbols_batch, resp["candles"]):
                            stock_data[symbol] = {"prev_day": candle[4] if candle else None}
                except Exception:
                    for symbol in symbols_batch:
                        stock_data[symbol] = {"prev_day": None}
            else:
                for symbol in symbols_batch:
                    stock_data[symbol] = {"prev_day": None}
        else:
            # Get live quotes for all stocks in one call
            symbols_str = ",".join(symbols_batch)
            quote_url = f"https://api.fyers.in/data/quotes?symbols={symbols_str}"
            response = session.get(quote_url, headers=headers, timeout=5)
            
            if response.status_code == 200:
                try:
                    quote_data = response.json()
                    if quote_data.get("d"):
                        for quote in quote_data["d"]:
                            symbol = quote.get("n")
                            if symbol in symbols_batch:
                                stock_data[symbol] = {"prev_day": quote.get("lp")}
                except Exception:
                    for symbol in symbols_batch:
                        stock_data[symbol] = {"prev_day": None}
            else:
                for symbol in symbols_batch:
                    stock_data[symbol] = {"prev_day": None}

        # Get historical data for 3 and 7 days back in one call
        for days_back, label in zip([3, 7], ["three_days_back", "seven_days_back"]):
            date = today - timedelta(days=days_back)
            data = {
                "symbols": symbols_batch,
                "resolution": "D",
                "date_format": "1",
                "range_from": date.strftime("%Y-%m-%d"),
                "range_to": date.strftime("%Y-%m-%d"),
                "cont_flag": "1"
            }
            try:
                response = session.post(
                    "https://api.fyers.in/data/history",
                    headers=headers,
                    json=data,
                    timeout=5
                )
                
                if response.status_code == 200:
                    try:
                        resp = response.json()
                        if resp.get("s") == "ok" and resp.get("candles"):
                            for symbol, candle in zip(symbols_batch, resp["candles"]):
                                if symbol in stock_data:
                                    stock_data[symbol][label] = candle[4] if candle else None
                    except Exception:
                        for symbol in symbols_batch:
                            if symbol in stock_data:
                                stock_data[symbol][label] = None
                else:
                    for symbol in symbols_batch:
                        if symbol in stock_data:
                            stock_data[symbol][label] = None
            except Exception:
                for symbol in symbols_batch:
                    if symbol in stock_data:
                        stock_data[symbol][label] = None

    except Exception as e:
        logger.error(f"Error fetching data for batch: {str(e)}")
        for symbol in symbols_batch:
            stock_data[symbol] = {
                "prev_day": None,
                "three_days_back": None,
                "seven_days_back": None
            }
    
    return stock_data

@measure_performance("get_historical_closes")
def get_historical_closes(access_token, symbols):
    """Get historical close prices for given symbols"""
    closes = {}
    today = datetime.now().date()
    headers = {"Authorization": f"Bearer {access_token}"}
    
    # Get current time in IST (server is set to Asia/Kolkata)
    current_time = datetime.now().time()
    
    # Market hours in IST (9:00 AM to 3:30 PM)
    market_start = datetime.strptime("09:00:00", "%H:%M:%S").time()
    market_end = datetime.strptime("15:30:00", "%H:%M:%S").time()
    
    # Use live data during market hours, historical data otherwise
    use_historical = not (market_start <= current_time <= market_end)
    logger.info(f"Current time (IST): {current_time}, Using {'historical' if use_historical else 'live'} data")

    # Get all required dates
    dates = [
        today,
        today - timedelta(days=3),
        today - timedelta(days=7)
    ]
    
    # Process each symbol individually
    for symbol in symbols:
        closes[symbol] = {
            "prev_day": None,
            "three_days_back": None,
            "seven_days_back": None
        }
        
        try:
            # Fetch historical data for this symbol
            data = {
                "symbol": symbol,  # Send single symbol instead of array
                "resolution": "D",
                "date_format": "1",
                "range_from": min(dates).strftime("%Y-%m-%d"),
                "range_to": max(dates).strftime("%Y-%m-%d"),
                "cont_flag": "1"
            }
            
            logger.info(f"Fetching {'historical' if use_historical else 'live'} data for {symbol}")
            logger.info(f"Request data: {json.dumps(data, indent=2)}")
            
            response = session.post(
                "https://api.fyers.in/data/history",
                headers=headers,
                json=data,
                timeout=10
            )
            
            logger.info(f"Data response status for {symbol}: {response.status_code}")
            logger.info(f"Data response for {symbol}: {response.text}")
            
            if response.status_code == 200:
                try:
                    resp = response.json()
                    if resp.get("s") == "ok" and resp.get("candles"):
                        logger.info(f"Successfully received {len(resp['candles'])} candles for {symbol}")
                        
                        # Process candles for this symbol
                        for candle in resp["candles"]:
                            candle_date = datetime.fromtimestamp(candle[1]).date()
                            if candle_date == today:
                                closes[symbol]["prev_day"] = candle[4]
                            elif candle_date == today - timedelta(days=3):
                                closes[symbol]["three_days_back"] = candle[4]
                            elif candle_date == today - timedelta(days=7):
                                closes[symbol]["seven_days_back"] = candle[4]
                        
                        logger.info(f"Processed data for {symbol}: {json.dumps(closes[symbol], indent=2)}")
                    else:
                        logger.warning(f"Invalid response format or no candles for {symbol}: {resp}")
                except Exception as e:
                    logger.error(f"Error processing data for {symbol}: {str(e)}")
            else:
                logger.error(f"Failed to fetch data for {symbol}: {response.status_code}")
        except Exception as e:
            logger.error(f"Error fetching data for {symbol}: {str(e)}")
    
    # Force garbage collection after processing
    gc.collect()
    
    return closes

def escape_markdown_v2(text):
    """Escape special characters for Telegram MarkdownV2"""
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = str(text).replace(char, f'\\{char}')
    return text

def format_message(data, closes):
    """Format message for Telegram"""
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
    
    return msg

@measure_performance("send_telegram_message")
def send_telegram_message(message):
    """Send message to Telegram channel"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "MarkdownV2"
    }
    try:
        resp = session.post(url, json=payload, timeout=5)
        return resp.ok, resp.text
    except Exception as e:
        logger.error(f"Error sending Telegram message: {str(e)}")
        return False, str(e)

@app.route("/webhook", methods=["POST"])
def webhook():
    """Handle incoming webhook requests"""
    start_time = time.time()
    try:
        data = request.json
        if not data:
            return jsonify({"status": "error", "message": "No data received"}), 400

        # Process stocks
        stocks = [s.strip() for s in data.get("stocks", "").split(",") if s.strip()]
        formatted_stocks = []
        for stock in stocks:
            if not stock.startswith("NSE:"):
                stock = f"NSE:{stock}"
            if not stock.endswith("-EQ"):
                stock = f"{stock}-EQ"
            formatted_stocks.append(stock)

        # Get Fyers access token and historical data
        access_token = get_fyers_access_token()
        closes = get_historical_closes(access_token, formatted_stocks)
        
        # Format and send message
        msg = format_message(data, closes)
        success, response = send_telegram_message(msg)
        
        total_time = (time.time() - start_time) * 1000  # Convert to milliseconds
        perf_logger.info(
            f"Webhook Request | "
            f"Total Time: {total_time:.2f}ms | "
            f"Stocks Count: {len(formatted_stocks)} | "
            f"Success: {success}"
        )
        
        if success:
            return jsonify({
                "status": "success",
                "message": "Webhook processed successfully",
                "execution_time_ms": total_time
            })
        else:
            return jsonify({
                "status": "error",
                "message": f"Failed to send message: {response}",
                "execution_time_ms": total_time
            })
    except Exception as e:
        total_time = (time.time() - start_time) * 1000
        logger.error(f"Error processing webhook: {str(e)}")
        perf_logger.error(
            f"Webhook Error | "
            f"Total Time: {total_time:.2f}ms | "
            f"Error: {str(e)}"
        )
        return jsonify({
            "status": "error",
            "message": str(e),
            "execution_time_ms": total_time
        }), 500

if __name__ == "__main__":
    # For production, use gunicorn with optimized settings:
    # gunicorn -w 2 -b 0.0.0.0:8080 --timeout 30 --keep-alive 5 --max-requests 1000 --max-requests-jitter 50 app:app
    app.run(host="0.0.0.0", port=8080) 
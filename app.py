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

# Get today's date for log files
today_date = datetime.now().strftime('%Y-%m-%d')
log_file = os.path.join(log_dir, f'webhook_{today_date}.log')
perf_log_file = os.path.join(log_dir, f'performance_{today_date}.log')
token_file = os.path.join(log_dir, 'fyers_token.json')  # Keep token file name constant

# Configure logging with rotation and reduced verbosity
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(
            log_file,
            maxBytes=5*1024*1024,  # 5MB
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
    maxBytes=5*1024*1024,  # 5MB
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
                today = validate_date(datetime.now().date())
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
        
        # Get current time and validate it's not in the future
        current_time = datetime.now()
        current_date = validate_date(current_time.date())
        if current_time.date() != current_date:
            current_time = datetime.combine(current_date, current_time.time())
        
        token_data = {
            'token': token,
            'timestamp': current_time.isoformat()
        }
        
        # Write to a temporary file first
        temp_file = f"{token_file}.tmp"
        with open(temp_file, 'w') as f:
            json.dump(token_data, f)
        
        # Atomic rename to ensure file integrity
        os.replace(temp_file, token_file)
        
        logger.info(f"Successfully saved new token for {current_date}")
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
    """Fetch data for a batch of stocks using Fyers SDK"""
    stock_data = {}
    try:
        # Initialize Fyers SDK
        from fyers_apiv3 import fyersModel
        fyers = fyersModel.FyersModel(client_id=FYERS_CLIENT_ID, token=headers["Authorization"].split(" ")[1])
        
        # Get today's data for all stocks in batch
        if use_historical:
            # Get historical data using SDK
            data = {
                "symbol": ",".join(symbols_batch),
                "resolution": "D",
                "date_format": 1,
                "range_from": today.strftime("%Y-%m-%d"),
                "range_to": today.strftime("%Y-%m-%d"),
                "cont_flag": "1"
            }
            logger.info(f"Fetching historical data: {json.dumps(data, indent=2)}")
            resp = fyers.history(data)
            
            if resp.get("s") == "ok" and resp.get("candles"):
                for symbol, candle in zip(symbols_batch, resp["candles"]):
                    stock_data[symbol] = {"prev_day": candle[4] if candle else None}
            else:
                for symbol in symbols_batch:
                    stock_data[symbol] = {"prev_day": None}
        else:
            # Get live quotes using SDK
            symbols_str = ",".join(symbols_batch)
            logger.info(f"Fetching live quotes for: {symbols_str}")
            quotes = fyers.quotes({"symbols": symbols_str})
            
            if quotes.get("s") == "ok" and quotes.get("d"):
                for quote in quotes["d"]:
                    symbol = quote.get("n")
                    if symbol in symbols_batch:
                        stock_data[symbol] = {"prev_day": quote.get("lp")}
            else:
                for symbol in symbols_batch:
                    stock_data[symbol] = {"prev_day": None}

        # Get historical data for 3 and 7 days back using SDK
        for days_back, label in zip([3, 7], ["three_days_back", "seven_days_back"]):
            date = today - timedelta(days=days_back)
            data = {
                "symbol": ",".join(symbols_batch),
                "resolution": "D",
                "date_format": 1,
                "range_from": date.strftime("%Y-%m-%d"),
                "range_to": date.strftime("%Y-%m-%d"),
                "cont_flag": "1"
            }
            try:
                logger.info(f"Fetching {label} data: {json.dumps(data, indent=2)}")
                resp = fyers.history(data)
                
                if resp.get("s") == "ok" and resp.get("candles"):
                    for symbol, candle in zip(symbols_batch, resp["candles"]):
                        if symbol in stock_data:
                            stock_data[symbol][label] = candle[4] if candle else None
                else:
                    for symbol in symbols_batch:
                        if symbol in stock_data:
                            stock_data[symbol][label] = None
            except Exception as e:
                logger.error(f"Error fetching {label} data: {str(e)}")
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

def get_previous_working_day(date):
    """Get the previous working day, skipping weekends"""
    # Start with the previous day
    prev_date = date - timedelta(days=1)
    
    # Keep going back until we find a weekday
    while prev_date.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
        prev_date = prev_date - timedelta(days=1)
    
    # Ensure we don't return a future date
    return validate_date(prev_date)

def get_exchange_symbol(fyers, symbol):
    """Check symbol availability in BSE first, then NSE if not found"""
    # Remove any existing prefixes and suffixes
    base_symbol = symbol.replace("NSE:", "").replace("BSE:", "").replace("-EQ", "")
    base_symbol = base_symbol.replace(".NS", "").replace(".BO", "").upper()
    
    # First try BSE since most stocks are available there
    bse_symbol = f"BSE:{base_symbol}-EQ"
    try:
        quotes = fyers.quotes({"symbols": bse_symbol})
        if quotes.get("s") == "ok" and quotes.get("d"):
            for quote in quotes["d"]:
                if quote.get("s") == "ok" and quote.get("v", {}).get("lp") is not None:
                    logger.info(f"Symbol {base_symbol} found in BSE")
                    return bse_symbol
    except Exception as e:
        logger.info(f"Symbol {base_symbol} not found in BSE: {str(e)}")
    
    # If not in BSE, try NSE
    nse_symbol = f"NSE:{base_symbol}-EQ"
    try:
        quotes = fyers.quotes({"symbols": nse_symbol})
        if quotes.get("s") == "ok" and quotes.get("d"):
            for quote in quotes["d"]:
                if quote.get("s") == "ok" and quote.get("v", {}).get("lp") is not None:
                    logger.info(f"Symbol {base_symbol} found in NSE")
                    return nse_symbol
    except Exception as e:
        logger.info(f"Symbol {base_symbol} not found in NSE: {str(e)}")
    
    # If not found in either exchange, default to NSE format
    logger.warning(f"Symbol {base_symbol} not found in either BSE or NSE, defaulting to NSE format")
    return f"NSE:{base_symbol}-EQ"

def validate_date(date):
    """Validate that a date is not in the future and return the most recent valid date"""
    today = datetime.now().date()
    if date > today:
        logger.warning(f"Date {date} is in the future, using today's date {today} instead")
        return today
    return date

def date_to_unix_timestamp(date, end_of_day=False):
    """Convert datetime.date to Unix timestamp (seconds since epoch)"""
    if end_of_day:
        time_obj = datetime.max.time()  # 23:59:59.999999
    else:
        time_obj = datetime.min.time()  # 00:00:00
    return int(datetime.combine(date, time_obj).timestamp())

@measure_performance("get_historical_closes")
def get_historical_closes(access_token, symbols):
    """Get historical close prices for given symbols using Fyers SDK"""
    closes = {}
    today = validate_date(datetime.now().date())
    
    try:
        # Initialize Fyers SDK
        from fyers_apiv3 import fyersModel
        fyers = fyersModel.FyersModel(client_id=FYERS_CLIENT_ID, token=access_token)
        
        # Process each symbol individually for historical data
        for symbol in symbols:
            try:
                # Get exchange-specific symbol
                exchange_symbol = get_exchange_symbol(fyers, symbol)
                
                # Initialize closes dict for this symbol
                closes[symbol] = {
                    "current_data": None,
                    "three_days_back": {"close": None, "volume": None},
                    "seven_days_back": {"close": None, "volume": None}
                }
                
                # Get live quotes
                logger.info(f"Fetching live quotes for: {exchange_symbol}")
                quotes = fyers.quotes({"symbols": exchange_symbol})
                logger.info(f"Quotes response: {json.dumps(quotes, indent=2)}")
                
                # Process live quotes
                if quotes.get("s") == "ok" and quotes.get("d"):
                    for quote in quotes["d"]:
                        if quote.get("s") == "ok" and quote.get("v"):
                            closes[symbol]["current_data"] = quote.get("v", {})
                            logger.info(f"Live quote for {symbol}: {json.dumps(quote.get('v', {}), indent=2)}")
                
                # Get historical data for 3 and 7 days back
                for days_back, label in zip([3, 7], ["three_days_back", "seven_days_back"]):
                    # Start from today and move back until we find a valid trading day
                    target_date = today
                    valid_days_found = 0
                    
                    while valid_days_found < days_back and target_date > today - timedelta(days=30):  # Limit search to last 30 days
                        target_date = get_previous_working_day(target_date)
                        if target_date.weekday() < 5:  # If it's a weekday
                            valid_days_found += 1
                        target_date = target_date - timedelta(days=1)
                    
                    # Move forward one day since the loop overshoots by one
                    target_date = target_date + timedelta(days=1)
                    
                    # Convert dates to Unix timestamps
                    range_from = date_to_unix_timestamp(target_date)  # Start of day
                    range_to = date_to_unix_timestamp(target_date, end_of_day=True)  # End of day
                    
                    hist_data = {
                        "symbol": exchange_symbol,  # Single symbol
                        "resolution": "D",  # Daily resolution
                        "date_format": "0",  # Use Unix timestamp format
                        "range_from": str(range_from),
                        "range_to": str(range_to),
                        "cont_flag": "1"
                    }
                    
                    try:
                        logger.info(f"Fetching {label} data for {exchange_symbol}: {json.dumps(hist_data, indent=2)}")
                        hist_resp = fyers.history(hist_data)
                        logger.info(f"Historical response for {exchange_symbol}: {json.dumps(hist_resp, indent=2)}")
                        
                        if hist_resp.get("s") == "ok" and hist_resp.get("candles"):
                            # candle format: [timestamp, open, high, low, close, volume]
                            candle = hist_resp["candles"][0] if hist_resp["candles"] else None
                            if candle and len(candle) >= 6:
                                closes[symbol][label] = {
                                    "close": candle[4],  # Close price is 5th field
                                    "volume": candle[5]  # Volume is 6th field
                                }
                                logger.info(f"Historical {label} for {symbol}: close={closes[symbol][label]['close']}, volume={closes[symbol][label]['volume']}")
                    except Exception as e:
                        logger.error(f"Error fetching {label} data for {symbol}: {str(e)}")
            
            except Exception as e:
                logger.error(f"Error processing symbol {symbol}: {str(e)}")
    
    except Exception as e:
        logger.error(f"Error initializing Fyers SDK: {str(e)}")
    
    # Force garbage collection after processing
    gc.collect()
    
    return closes

def escape_markdown_v2(text):
    """Escape special characters for Telegram MarkdownV2"""
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    escaped_text = str(text)
    for char in special_chars:
        escaped_text = escaped_text.replace(char, f'\\{char}')
    return escaped_text

def format_volume(volume):
    """Format volume in K (thousands), L (lakhs), or Cr (crores) with 2 decimal places"""
    try:
        volume = float(volume)
        if volume >= 10000000:  # 1 Crore = 100L = 10M
            return f"{volume/10000000:.2f}Cr"
        elif volume >= 100000:  # 1 Lakh = 100K
            return f"{volume/100000:.2f}L"
        elif volume >= 1000:    # 1K = 1000
            return f"{volume/1000:.2f}K"
        else:
            return f"{volume:.0f}"
    except (TypeError, ValueError):
        return "N/A"

def calculate_percent_change(current, previous):
    """Calculate percentage change between two values"""
    try:
        current = float(current)
        previous = float(previous)
        if previous != 0:
            change = ((current - previous) / previous) * 100
            return f"{change:+.2f}%"
    except (TypeError, ValueError):
        pass
    return "N/A"

def calculate_volume_change(current_vol, previous_vol):
    """Calculate volume change in X format"""
    try:
        current_vol = float(current_vol)
        previous_vol = float(previous_vol)
        if previous_vol > 0:
            ratio = current_vol / previous_vol
            if ratio >= 1:
                return f"+{ratio:.1f}x"
            else:
                return f"{ratio:.1f}x"
    except (TypeError, ValueError):
        pass
    return ""

def format_message(data, closes):
    """Format message for Telegram"""
    # Header section with minimal info
    msg = f"🚨 *{escape_markdown_v2(data.get('alert_name', 'N/A'))}*\n"
    msg += f"⌚️ {escape_markdown_v2(data.get('triggered_at', 'N/A'))}\n\n"
    
    for symbol, data in closes.items():
        # Extract base symbol without exchange prefix
        base_symbol = symbol.replace('NSE:', '').replace('BSE:', '').replace('-EQ', '')
        
        current_data = data.get("current_data", {})
        if current_data and isinstance(current_data, dict) and 'lp' in current_data:
            current = current_data
            three_days = data.get('three_days_back', {})
            seven_days = data.get('seven_days_back', {})
            
            # Get all required values
            ltp = str(current.get('lp', 'N/A'))
            change = str(current.get('ch', 'N/A'))
            change_percent = str(current.get('chp', 'N/A'))
            
            # Get volumes and calculate volume changes
            current_volume = current.get('volume', 0)
            three_day_volume = three_days.get('volume', 0)
            seven_day_volume = seven_days.get('volume', 0)
            
            # Calculate volume changes
            three_day_vol_change = calculate_volume_change(current_volume, three_day_volume)
            seven_day_vol_change = calculate_volume_change(current_volume, seven_day_volume)
            
            # Format volumes with their respective scales
            current_vol_formatted = format_volume(current_volume)
            three_day_vol_formatted = format_volume(three_day_volume)
            seven_day_vol_formatted = format_volume(seven_day_volume)
            
            # Calculate historical changes
            current_price = current.get('lp')
            three_day_price = three_days.get('close')
            seven_day_price = seven_days.get('close')
            three_day_change = calculate_percent_change(current_price, three_day_price)
            seven_day_change = calculate_percent_change(current_price, seven_day_price)
            
            # Format prices with 2 decimal places
            try:
                three_day_price_fmt = f"{float(three_day_price):.2f}"
            except (TypeError, ValueError):
                three_day_price_fmt = "N/A"
                
            try:
                seven_day_price_fmt = f"{float(seven_day_price):.2f}"
            except (TypeError, ValueError):
                seven_day_price_fmt = "N/A"
            
            # Add arrow and color indicator based on price change
            try:
                change_pct_float = float(change_percent)
                if float(change) > 0:
                    arrow = "🟢"
                    trend = "↗️"
                    # Add upper arrows if change is greater than 3%
                    if change_pct_float > 3:
                        trend = "⬆️⬆️"
                elif float(change) < 0:
                    arrow = "🔴"
                    trend = "↘️"
                else:
                    arrow = "⚪️"
                    trend = "➡️"
            except (ValueError, TypeError):
                arrow = "⚪️"
                trend = "➡️"
            
            # Format historical changes with arrows
            try:
                three_day_arrow = "↗️" if float(three_day_change.rstrip('%')) > 0 else "↘️" if float(three_day_change.rstrip('%')) < 0 else "➡️"
                seven_day_arrow = "↗️" if float(seven_day_change.rstrip('%')) > 0 else "↘️" if float(seven_day_change.rstrip('%')) < 0 else "➡️"
            except (ValueError, TypeError):
                three_day_arrow = "➡️"
                seven_day_arrow = "➡️"
            
            # Format volume changes with emojis
            three_day_vol_emoji = "📈" if three_day_vol_change.startswith('+') else "📉" if three_day_vol_change else "➡️"
            seven_day_vol_emoji = "📈" if seven_day_vol_change.startswith('+') else "📉" if seven_day_vol_change else "➡️"
            
            # Format the message in a compact way
            msg += f"{arrow} *{escape_markdown_v2(base_symbol)}*\n"
            msg += f"💵 {escape_markdown_v2(ltp)} {trend} {escape_markdown_v2(change_percent)}% • 📊 Vol: {escape_markdown_v2(current_vol_formatted)}\n"
            
            # Historical data in compact format with prices
            msg += f"📈 3D: {escape_markdown_v2(three_day_price_fmt)} {three_day_arrow}{escape_markdown_v2(three_day_change)} \\[📊 {escape_markdown_v2(three_day_vol_formatted)} {three_day_vol_emoji} {escape_markdown_v2(three_day_vol_change)}\\]\n"
            msg += f"📉 7D: {escape_markdown_v2(seven_day_price_fmt)} {seven_day_arrow}{escape_markdown_v2(seven_day_change)} \\[📊 {escape_markdown_v2(seven_day_vol_formatted)} {seven_day_vol_emoji} {escape_markdown_v2(seven_day_vol_change)}\\]\n"
            msg += "\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\n"
        else:
            msg += f"⚠️ *{escape_markdown_v2(base_symbol)}* • No Data Available\n"
            msg += "\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\n"
    
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
            # Clean the symbol and add NSE prefix by default
            stock = stock.replace("NSE:", "").replace("BSE:", "").replace("-EQ", "")
            stock = stock.replace(".NS", "").replace(".BO", "").upper()
            formatted_stock = f"NSE:{stock}-EQ"
            formatted_stocks.append(formatted_stock)

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
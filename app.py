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
from collections import deque, OrderedDict
from threading import Lock
import psutil
import threading

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

class HistoricalQuoteCache:
    """Cache for historical quotes with TTL and memory monitoring"""
    def __init__(self, maxsize=2000, ttl_seconds=32400):  # 9 hours TTL
        self.maxsize = maxsize
        self.ttl_seconds = ttl_seconds
        self.cache = OrderedDict()
        self.lock = threading.Lock()
        self.last_cleanup = time.time()
        self.cleanup_interval = 300  # Cleanup every 5 minutes
        self.hits = 0
        self.misses = 0
        self.last_memory_check = time.time()
        self.memory_check_interval = 60  # Check memory every minute
        self.memory_warning_threshold = 0.8  # 80% memory usage warning
        logger.info(f"Initialized HistoricalQuoteCache with TTL: {ttl_seconds/3600:.1f} hours, Max size: {maxsize}")

    def _check_memory_usage(self):
        """Monitor memory usage of the process"""
        now = time.time()
        if now - self.last_memory_check < self.memory_check_interval:
            return

        process = psutil.Process(os.getpid())
        memory_info = process.memory_info()
        system_memory = psutil.virtual_memory()
        
        # Calculate cache memory usage
        cache_size = len(self.cache)
        estimated_cache_memory = cache_size * 204  # 204 bytes per entry
        
        # Log memory usage
        logger.info(
            f"Memory Usage - "
            f"Process: {memory_info.rss / 1024 / 1024:.1f}MB, "
            f"System: {system_memory.percent}%, "
            f"Cache entries: {cache_size}, "
            f"Estimated cache memory: {estimated_cache_memory / 1024 / 1024:.1f}MB"
        )
        
        # Check if memory usage is too high
        if system_memory.percent > self.memory_warning_threshold * 100:
            logger.warning(
                f"High memory usage detected - "
                f"System: {system_memory.percent}%, "
                f"Process: {memory_info.rss / 1024 / 1024:.1f}MB"
            )
            # Reduce cache size if memory usage is high
            self._reduce_cache_size()
        
        self.last_memory_check = now

    def _reduce_cache_size(self):
        """Reduce cache size when memory usage is high"""
        with self.lock:
            current_size = len(self.cache)
            target_size = int(current_size * 0.7)  # Reduce to 70% of current size
            if target_size < current_size:
                logger.warning(f"Reducing cache size from {current_size} to {target_size}")
                while len(self.cache) > target_size:
                    self.cache.popitem(last=False)

    def _cleanup_expired(self):
        """Remove expired entries from cache"""
        now = time.time()
        if now - self.last_cleanup < self.cleanup_interval:
            return

        with self.lock:
            expired_keys = []
            for key, (value, timestamp) in self.cache.items():
                if now - timestamp > self.ttl_seconds:
                    expired_keys.append(key)

            if expired_keys:
                logger.info(f"Cleaning up {len(expired_keys)} expired cache entries")
                for key in expired_keys:
                    del self.cache[key]

            self.last_cleanup = now
            # Log cache statistics
            total = self.hits + self.misses
            if total > 0:
                hit_rate = (self.hits / total) * 100
                logger.info(
                    f"Cache stats - "
                    f"Size: {len(self.cache)}/{self.maxsize}, "
                    f"Hit rate: {hit_rate:.1f}%, "
                    f"Hits: {self.hits}, "
                    f"Misses: {self.misses}"
                )

    def get(self, key):
        """Get value from cache if not expired"""
        self._cleanup_expired()
        self._check_memory_usage()
        
        with self.lock:
            if key in self.cache:
                value, timestamp = self.cache[key]
                if time.time() - timestamp <= self.ttl_seconds:
                    # Move to end (most recently used)
                    self.cache.move_to_end(key)
                    self.hits += 1
                    return value
                else:
                    del self.cache[key]
            self.misses += 1
        return None

    def set(self, key, value):
        """Set value in cache with current timestamp"""
        self._cleanup_expired()
        self._check_memory_usage()
        
        with self.lock:
            if len(self.cache) >= self.maxsize:
                # Remove oldest item
                self.cache.popitem(last=False)
                logger.debug(f"Cache full, removed oldest entry")
            self.cache[key] = (value, time.time())
            logger.debug(f"Added new entry to cache, current size: {len(self.cache)}")

    def clear(self):
        """Clear all cached data"""
        with self.lock:
            self.cache.clear()
            self.hits = 0
            self.misses = 0
            logger.info("Cache cleared")

# Initialize global cache with 9-hour TTL and 2000 symbol limit
historical_cache = HistoricalQuoteCache(maxsize=2000, ttl_seconds=32400)  # 9 hours = 9 * 60 * 60

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

class RateLimiter:
    """Rate limiter for API calls"""
    def __init__(self, max_requests: int, time_window: float):
        """
        Initialize rate limiter
        :param max_requests: Maximum number of requests allowed in the time window
        :param time_window: Time window in seconds
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = deque()
        self.lock = Lock()
        self.min_delay = 0.2  # Minimum delay between requests in seconds

    def wait_if_needed(self):
        """
        Wait if necessary to stay within rate limits
        """
        with self.lock:
            now = time.time()
            
            # Remove old requests outside the time window
            while self.requests and now - self.requests[0] > self.time_window:
                self.requests.popleft()
            
            # If we've hit the limit, wait until we can make another request
            if len(self.requests) >= self.max_requests:
                sleep_time = self.requests[0] + self.time_window - now
                if sleep_time > 0:
                    time.sleep(sleep_time)
            
            # Always add a small delay between requests
            if self.requests:
                last_request = self.requests[-1]
                time_since_last = now - last_request
                if time_since_last < self.min_delay:
                    time.sleep(self.min_delay - time_since_last)
            
            # Add current request timestamp
            self.requests.append(time.time())

# Initialize rate limiter for Fyers API (8 requests per second to be safe)
fyers_rate_limiter = RateLimiter(max_requests=8, time_window=1.0)

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
def get_historical_closes(symbols, days_back=1):
    """Get historical closing prices for multiple symbols"""
    try:
        # Get access token
        access_token = get_fyers_access_token()
        if not access_token:
            return {symbol: "No Data Available" for symbol in symbols}

        # Initialize Fyers SDK
        from fyers_apiv3 import fyersModel
        fyers = fyersModel.FyersModel(client_id=FYERS_CLIENT_ID, token=access_token)

        # Process symbols and fetch quotes
        exchange_symbols = []
        symbol_to_exchange = {}
        live_quotes = {}
        
        # First try NSE for all symbols
        nse_symbols = [f"NSE:{symbol.replace('NSE:', '').replace('BSE:', '').replace('-EQ', '').replace('.NS', '').replace('.BO', '').upper()}-EQ" for symbol in symbols]
        nse_symbols_str = ",".join(nse_symbols)
        logger.info(f"Fetching NSE quotes for: {nse_symbols_str}")
        
        try:
            quotes = fyers.quotes({"symbols": nse_symbols_str})
            logger.info(f"NSE quotes response: {json.dumps(quotes, indent=2)}")
            
            if quotes.get("s") == "ok" and quotes.get("d"):
                for quote in quotes["d"]:
                    if quote.get("s") == "ok" and quote.get("v"):
                        quote_symbol = quote.get("n")
                        # Find the original symbol for this quote
                        for symbol, nse_symbol in zip(symbols, nse_symbols):
                            if nse_symbol == quote_symbol:
                                live_quotes[symbol] = quote.get("v", {}).get("lp", 0)
                                exchange_symbols.append(quote_symbol)
                                symbol_to_exchange[symbol] = quote_symbol
                                break
        except Exception as e:
            logger.error(f"Error fetching NSE quotes: {str(e)}")

        # Then try BSE for remaining symbols
        remaining_symbols = [symbol for symbol in symbols if symbol not in symbol_to_exchange]
        if remaining_symbols:
            bse_symbols = [f"BSE:{symbol.replace('NSE:', '').replace('BSE:', '').replace('-EQ', '').replace('.NS', '').replace('.BO', '').upper()}-EQ" for symbol in remaining_symbols]
            bse_symbols_str = ",".join(bse_symbols)
            logger.info(f"Fetching BSE quotes for: {bse_symbols_str}")
            
            try:
                quotes = fyers.quotes({"symbols": bse_symbols_str})
                logger.info(f"BSE quotes response: {json.dumps(quotes, indent=2)}")
                
                if quotes.get("s") == "ok" and quotes.get("d"):
                    for quote in quotes["d"]:
                        if quote.get("s") == "ok" and quote.get("v"):
                            quote_symbol = quote.get("n")
                            # Find the original symbol for this quote
                            for symbol, bse_symbol in zip(remaining_symbols, bse_symbols):
                                if bse_symbol == quote_symbol:
                                    live_quotes[symbol] = quote.get("v", {}).get("lp", 0)
                                    exchange_symbols.append(quote_symbol)
                                    symbol_to_exchange[symbol] = quote_symbol
                                    break
            except Exception as e:
                logger.error(f"Error fetching BSE quotes: {str(e)}")

        if not exchange_symbols:
            return {symbol: "No Data Available" for symbol in symbols}

        # Process historical data with caching
        results = {}
        for symbol, exchange_symbol in symbol_to_exchange.items():
            try:
                # Generate cache key
                cache_key = f"{exchange_symbol}_{days_back}"
                
                # Try to get from cache first
                cached_data = historical_cache.get(cache_key)
                if cached_data is not None:
                    logger.info(f"Cache hit for {symbol}")
                    results[symbol] = cached_data
                    continue

                # If not in cache, fetch from API
                logger.info(f"Cache miss for {symbol}, fetching from API")
                data = {
                    "symbol": exchange_symbol,
                    "resolution": "D",
                    "date_format": "1",
                    "range_from": (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d'),
                    "range_to": datetime.now().strftime('%Y-%m-%d'),
                    "cont_flag": "1"
                }
                logger.info(f"Historical data request for {symbol}: {json.dumps(data, indent=2)}")
                resp = fyers.history(data)
                logger.info(f"Historical data response for {symbol}: {json.dumps(resp, indent=2)}")

                if resp.get("s") == "ok" and resp.get("candles"):
                    closes = [candle[4] for candle in resp["candles"]]
                    if closes:
                        result = {
                            'live_price': live_quotes.get(symbol, 0),
                            'historical_closes': closes
                        }
                        # Store in cache
                        historical_cache.set(cache_key, result)
                        results[symbol] = result
                    else:
                        logger.warning(f"No closing prices found for {symbol}")
                        results[symbol] = "No Data Available"
                else:
                    logger.error(f"Error in historical data response for {symbol}: {resp}")
                    results[symbol] = "No Data Available"

                # Add delay between historical data requests
                time.sleep(0.2)

            except Exception as e:
                logger.error(f"Error processing {symbol}: {str(e)}")
                results[symbol] = "No Data Available"

        return results

    except Exception as e:
        logger.error(f"Error in get_historical_closes: {str(e)}")
        return {symbol: "No Data Available" for symbol in symbols}

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
        if isinstance(data, dict) and 'live_price' in data and 'historical_closes' in data:
            # Extract base symbol without exchange prefix
            base_symbol = symbol.replace('NSE:', '').replace('BSE:', '').replace('-EQ', '')
            
            # Get current and historical prices
            current_price = data['live_price']
            historical_closes = data['historical_closes']
            
            if current_price and historical_closes:
                # Calculate changes
                prev_close = historical_closes[0] if historical_closes else current_price
                three_day_close = historical_closes[2] if len(historical_closes) > 2 else prev_close
                seven_day_close = historical_closes[6] if len(historical_closes) > 6 else prev_close
                
                # Calculate price changes
                change = current_price - prev_close
                change_percent = (change / prev_close * 100) if prev_close else 0
                three_day_change = ((current_price - three_day_close) / three_day_close * 100) if three_day_close else 0
                seven_day_change = ((current_price - seven_day_close) / seven_day_close * 100) if seven_day_close else 0
                
                # Get volumes (using dummy values for now since we don't have volume data)
                current_volume = 812700  # Example: 81.27L
                three_day_volume = 594500  # Example: 59.45L
                seven_day_volume = 619600  # Example: 61.96L
                
                # Calculate volume changes
                three_day_vol_change = f"+{current_volume/three_day_volume:.1f}x" if three_day_volume else ""
                seven_day_vol_change = f"+{current_volume/seven_day_volume:.1f}x" if seven_day_volume else ""
                
                # Format volumes
                current_vol_formatted = f"{current_volume/100000:.2f}L"
                three_day_vol_formatted = f"{three_day_volume/100000:.2f}L"
                seven_day_vol_formatted = f"{seven_day_volume/100000:.2f}L"
                
                # Add arrow and color indicator based on price change
                if change > 0:
                    arrow = "🟢"
                    trend = "↗️"
                    if change_percent > 3:
                        trend = "⬆️⬆️"
                elif change < 0:
                    arrow = "🔴"
                    trend = "↘️"
                else:
                    arrow = "⚪️"
                    trend = "➡️"
                
                # Format historical changes with arrows
                three_day_arrow = "↗️" if three_day_change > 0 else "↘️" if three_day_change < 0 else "➡️"
                seven_day_arrow = "↗️" if seven_day_change > 0 else "↘️" if seven_day_change < 0 else "➡️"
                
                # Format volume changes with emojis
                three_day_vol_emoji = "📈" if three_day_vol_change.startswith('+') else "📉" if three_day_vol_change else "➡️"
                seven_day_vol_emoji = "📈" if seven_day_vol_change.startswith('+') else "📉" if seven_day_vol_change else "➡️"
                
                # Format the message
                msg += f"{arrow} *{escape_markdown_v2(base_symbol)}*\n"
                msg += f"💵 {escape_markdown_v2(f'{current_price:.1f}')} {trend} {escape_markdown_v2(f'{change_percent:+.2f}%')} • 📊 Vol: {escape_markdown_v2(current_vol_formatted)}\n"
                msg += f"📈 3D: {escape_markdown_v2(f'{three_day_close:.2f}')} {three_day_arrow}{escape_markdown_v2(f'{three_day_change:+.2f}%')} \\[📊 {escape_markdown_v2(three_day_vol_formatted)} {three_day_vol_emoji} {escape_markdown_v2(three_day_vol_change)}\\]\n"
                msg += f"📉 7D: {escape_markdown_v2(f'{seven_day_close:.2f}')} {seven_day_arrow}{escape_markdown_v2(f'{seven_day_change:+.2f}%')} \\[📊 {escape_markdown_v2(seven_day_vol_formatted)} {seven_day_vol_emoji} {escape_markdown_v2(seven_day_vol_change)}\\]\n"
                msg += "\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\n"
            else:
                msg += f"⚠️ *{escape_markdown_v2(base_symbol)}* • No Data Available\n"
                msg += "\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\n"
        else:
            base_symbol = symbol.replace('NSE:', '').replace('BSE:', '').replace('-EQ', '')
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

        # Get historical data
        closes = get_historical_closes(formatted_stocks)
        
        # Format message
        msg = f"🚨 *{escape_markdown_v2(data.get('alert_name', 'N/A'))}*\n"
        msg += f"⌚️ {escape_markdown_v2(data.get('triggered_at', 'N/A'))}\n\n"
        
        for symbol, data in closes.items():
            if isinstance(data, dict) and 'live_price' in data and 'historical_closes' in data:
                # Extract base symbol without exchange prefix
                base_symbol = symbol.replace('NSE:', '').replace('BSE:', '').replace('-EQ', '')
                
                # Get current and historical prices
                current_price = data['live_price']
                historical_closes = data['historical_closes']
                
                if current_price and historical_closes:
                    # Calculate changes
                    prev_close = historical_closes[0] if historical_closes else current_price
                    three_day_close = historical_closes[2] if len(historical_closes) > 2 else prev_close
                    seven_day_close = historical_closes[6] if len(historical_closes) > 6 else prev_close
                    
                    # Calculate price changes
                    change = current_price - prev_close
                    change_percent = (change / prev_close * 100) if prev_close else 0
                    three_day_change = ((current_price - three_day_close) / three_day_close * 100) if three_day_close else 0
                    seven_day_change = ((current_price - seven_day_close) / seven_day_close * 100) if seven_day_close else 0
                    
                    # Get volumes (using dummy values for now since we don't have volume data)
                    current_volume = 812700  # Example: 81.27L
                    three_day_volume = 594500  # Example: 59.45L
                    seven_day_volume = 619600  # Example: 61.96L
                    
                    # Calculate volume changes
                    three_day_vol_change = f"+{current_volume/three_day_volume:.1f}x" if three_day_volume else ""
                    seven_day_vol_change = f"+{current_volume/seven_day_volume:.1f}x" if seven_day_volume else ""
                    
                    # Format volumes
                    current_vol_formatted = f"{current_volume/100000:.2f}L"
                    three_day_vol_formatted = f"{three_day_volume/100000:.2f}L"
                    seven_day_vol_formatted = f"{seven_day_volume/100000:.2f}L"
                    
                    # Add arrow and color indicator based on price change
                    if change > 0:
                        arrow = "🟢"
                        trend = "↗️"
                        if change_percent > 3:
                            trend = "⬆️⬆️"
                    elif change < 0:
                        arrow = "🔴"
                        trend = "↘️"
                    else:
                        arrow = "⚪️"
                        trend = "➡️"
                    
                    # Format historical changes with arrows
                    three_day_arrow = "↗️" if three_day_change > 0 else "↘️" if three_day_change < 0 else "➡️"
                    seven_day_arrow = "↗️" if seven_day_change > 0 else "↘️" if seven_day_change < 0 else "➡️"
                    
                    # Format volume changes with emojis
                    three_day_vol_emoji = "📈" if three_day_vol_change.startswith('+') else "📉" if three_day_vol_change else "➡️"
                    seven_day_vol_emoji = "📈" if seven_day_vol_change.startswith('+') else "📉" if seven_day_vol_change else "➡️"
                    
                    # Format the message
                    msg += f"{arrow} *{escape_markdown_v2(base_symbol)}*\n"
                    msg += f"💵 {escape_markdown_v2(f'{current_price:.1f}')} {trend} {escape_markdown_v2(f'{change_percent:+.2f}%')} • 📊 Vol: {escape_markdown_v2(current_vol_formatted)}\n"
                    msg += f"📈 3D: {escape_markdown_v2(f'{three_day_close:.2f}')} {three_day_arrow}{escape_markdown_v2(f'{three_day_change:+.2f}%')} \\[📊 {escape_markdown_v2(three_day_vol_formatted)} {three_day_vol_emoji} {escape_markdown_v2(three_day_vol_change)}\\]\n"
                    msg += f"📉 7D: {escape_markdown_v2(f'{seven_day_close:.2f}')} {seven_day_arrow}{escape_markdown_v2(f'{seven_day_change:+.2f}%')} \\[📊 {escape_markdown_v2(seven_day_vol_formatted)} {seven_day_vol_emoji} {escape_markdown_v2(seven_day_vol_change)}\\]\n"
                    msg += "\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\n"
                else:
                    msg += f"⚠️ *{escape_markdown_v2(base_symbol)}* • No Data Available\n"
                    msg += "\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\n"
            else:
                base_symbol = symbol.replace('NSE:', '').replace('BSE:', '').replace('-EQ', '')
                msg += f"⚠️ *{escape_markdown_v2(base_symbol)}* • No Data Available\n"
                msg += "\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\n"
        
        # Send message
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
from fyers_quote_fetcher import fetch_quotes, get_previous_day_ohlc, get_previous_day_ohlc_bulk
from datetime import datetime, timedelta
import json

def main():
    # Test symbols from different sectors
    test_symbols = [
        "NSE:RELIANCE-EQ",  # Reliance Industries
        "NSE:TCS-EQ",       # Tata Consultancy Services
        "NSE:HDFCBANK-EQ",  # HDFC Bank
        "NSE:INFY-EQ",      # Infosys
        "NSE:ICICIBANK-EQ", # ICICI Bank
        "NSE:HINDUNILVR-EQ", # Hindustan Unilever
        "NSE:SBIN-EQ",      # State Bank of India
        "NSE:BAJFINANCE-EQ", # Bajaj Finance
        "NSE:BHARTIARTL-EQ", # Bharti Airtel
        "NSE:KOTAKBANK-EQ"  # Kotak Mahindra Bank
    ]
    
    print("Fetching quotes for test symbols...")
    try:
        quotes = fetch_quotes(test_symbols)
        print(json.dumps(quotes, indent=2))
    except Exception as e:
        print(f"Error fetching quotes: {str(e)}")

    # Fetch previous day's OHLC for a single symbol
    print("\nFetching previous day's OHLC for NSE:RELIANCE-EQ...")
    try:
        ohlc_single = get_previous_day_ohlc("NSE:RELIANCE-EQ")
        print(json.dumps(ohlc_single, indent=2))
    except Exception as e:
        print(f"Error fetching previous day's OHLC for NSE:RELIANCE-EQ: {str(e)}")

    # Fetch previous day's OHLC for all test symbols
    print("\nFetching previous day's OHLC for all test symbols...")
    try:
        ohlc_bulk = get_previous_day_ohlc_bulk(test_symbols)
        print(json.dumps(ohlc_bulk, indent=2))
    except Exception as e:
        print(f"Error fetching previous day's OHLC for all symbols: {str(e)}")

if __name__ == "__main__":
    main() 
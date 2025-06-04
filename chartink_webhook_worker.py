import json
import requests
from datetime import datetime, timedelta
from fyers_quote_fetcher import get_fyers_client

def escape_markdown_v2(text):
    if not text or not isinstance(text, str):
        return text or ""
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text

def get_historical_closes(fyers, symbols):
    closes = {}
    for symbol in symbols:
        closes[symbol] = {}
        today = datetime.now().date()
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
            resp = fyers.history(data)
            if resp.get("s") == "ok" and resp.get("candles"):
                closes[symbol][label] = resp["candles"][0][4]  # close price
            else:
                closes[symbol][label] = None
    return closes

def format_message(webhook_data, closes):
    # Escape all text for MarkdownV2
    alert_name = escape_markdown_v2(webhook_data.get('alert_name', 'N/A'))
    scan_name = escape_markdown_v2(webhook_data.get('scan_name', 'Unknown Scan'))
    stocks = escape_markdown_v2(webhook_data.get('stocks', 'No stocks'))
    trigger_prices = escape_markdown_v2(webhook_data.get('trigger_prices', 'N/A'))
    triggered_at = escape_markdown_v2(webhook_data.get('triggered_at', 'N/A'))

    # Format the main alert message
    msg = f"*AlertName: {alert_name}*\n"
    msg += f"Scan: {scan_name}\n"
    msg += f"Stocks: *{stocks}*\n"
    msg += f"Prices: {trigger_prices}\n"
    msg += f"Triggered At: {triggered_at}\n\n"

    # Add historical data
    msg += "*Historical Close Prices:*\n\n"
    for symbol, data in closes.items():
        msg += f"*{escape_markdown_v2(symbol)}*\n"
        msg += f"Prev Day Close: {escape_markdown_v2(str(data.get('prev_day', 'N/A')))}\n"
        msg += f"3 Days Back Close: {escape_markdown_v2(str(data.get('three_days_back', 'N/A')))}\n"
        msg += f"7 Days Back Close: {escape_markdown_v2(str(data.get('seven_days_back', 'N/A')))}\n\n"
    return msg

def send_telegram_message(token, chat_id, message):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "MarkdownV2"
    }
    resp = requests.post(url, json=payload)
    return resp.status_code == 200, resp.text

def handle_webhook(request_data, fyers_client, telegram_token, telegram_chat_id):
    try:
        # Extract and process stocks
        stocks = request_data.get('stocks', '').split(',')
        stocks = [s.strip() for s in stocks if s.strip()]
        
        # Add NSE: prefix and -EQ suffix if not present
        formatted_stocks = []
        for stock in stocks:
            if not stock.startswith('NSE:'):
                stock = f"NSE:{stock}"
            if not stock.endswith('-EQ'):
                stock = f"{stock}-EQ"
            formatted_stocks.append(stock)

        # Get historical data
        closes = get_historical_closes(fyers_client, formatted_stocks)
        
        # Format and send message
        msg = format_message(request_data, closes)
        success, response = send_telegram_message(telegram_token, telegram_chat_id, msg)
        
        return {
            "status": "success" if success else "error",
            "message": "Webhook processed successfully" if success else f"Failed to send message: {response}",
            "execution_time_ms": 0  # You can add timing if needed
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error processing webhook: {str(e)}",
            "execution_time_ms": 0
        }

# Example usage in Cloudflare Worker:
"""
async def handleRequest(request):
    if request.method != "POST":
        return new Response("Method not allowed", { status: 405 })

    try:
        data = await request.json()
        fyers = get_fyers_client()  # Initialize Fyers client
        result = handle_webhook(
            data,
            fyers,
            env.TELEGRAM_TOKEN,
            env.TELEGRAM_CHAT_ID
        )
        return new Response(JSON.stringify(result), {
            headers: { "Content-Type": "application/json" },
            status: 200 if result["status"] == "success" else 500
        })
    except Exception as e:
        return new Response(JSON.stringify({
            "status": "error",
            "message": str(e)
        }), { status: 500 })
""" 
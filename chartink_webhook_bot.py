import requests
from datetime import datetime, timedelta
from fyers_quote_fetcher import get_previous_day_ohlc, get_fyers_client
from flask import Flask, request, jsonify
import re

app = Flask(__name__)

def escape_markdown_v2(text):
    if not text or not isinstance(text, str):
        return text or ""
    # Escape special characters for MarkdownV2
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text

class ChartinkWebhookBot:
    def __init__(self, telegram_token, telegram_chat_id):
        self.telegram_token = telegram_token
        self.telegram_chat_id = telegram_chat_id
        self.fyers = get_fyers_client()

    def get_historical_closes(self, symbols):
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
                resp = self.fyers.history(data)
                if resp.get("s") == "ok" and resp.get("candles"):
                    closes[symbol][label] = resp["candles"][0][4]  # close price
                else:
                    closes[symbol][label] = None
        return closes

    def format_message(self, webhook_data, closes):
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

    def send_telegram_message(self, message):
        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        payload = {
            "chat_id": self.telegram_chat_id,
            "text": message,
            "parse_mode": "MarkdownV2"
        }
        resp = requests.post(url, json=payload)
        print("Message content:", message)
        print("Telegram API response:", resp.text)
        return resp.status_code == 200

    def process_webhook(self, webhook_data):
        try:
            # Extract and process stocks
            stocks = webhook_data.get('stocks', '').split(',')
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
            closes = self.get_historical_closes(formatted_stocks)
            
            # Format and send message
            msg = self.format_message(webhook_data, closes)
            success = self.send_telegram_message(msg)
            
            return success, "Webhook processed successfully"
        except Exception as e:
            return False, f"Error processing webhook: {str(e)}"

# Initialize the bot with your credentials
TELEGRAM_TOKEN = "8199254732:AAEn-4X-z87-pSp1SKcJEjJjoyewXvOxmfg"
TELEGRAM_CHAT_ID = "-1002511791814"
bot = ChartinkWebhookBot(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID)

@app.route('/webhook', methods=['POST'])
def handle_webhook():
    start_time = datetime.now()
    
    try:
        # Parse the incoming JSON request
        data = request.get_json()
        if not data:
            return jsonify({"error": "Invalid JSON payload"}), 400

        # Process the webhook
        success, message = bot.process_webhook(data)
        
        # Calculate execution time
        execution_time = (datetime.now() - start_time).total_seconds() * 1000
        
        if success:
            return jsonify({
                "status": "success",
                "message": message,
                "execution_time_ms": round(execution_time, 2)
            }), 200
        else:
            return jsonify({
                "status": "error",
                "message": message,
                "execution_time_ms": round(execution_time, 2)
            }), 500
            
    except Exception as e:
        execution_time = (datetime.now() - start_time).total_seconds() * 1000
        return jsonify({
            "status": "error",
            "message": f"Internal server error: {str(e)}",
            "execution_time_ms": round(execution_time, 2)
        }), 500

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8080) 
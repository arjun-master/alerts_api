# Chartink Telegram Webhook

A Flask-based webhook service that processes stock alerts from Chartink and sends them to a Telegram channel with historical price data from Fyers API.

## Features

- Receives webhook alerts from Chartink
- Fetches historical price data from Fyers API
- Sends formatted messages to Telegram channel
- Token caching and automatic renewal
- Performance logging and monitoring
- Error handling and retry mechanisms

## Prerequisites

- Python 3.8+
- Fyers Trading Account
- Telegram Bot Token
- Telegram Channel ID

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/chartink-telegram-webhook.git
cd chartink-telegram-webhook
```

2. Create and activate virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Create a `.env` file with your credentials:
```env
# Telegram Configuration
TELEGRAM_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id

# Fyers API Configuration
FYERS_CLIENT_ID=your_fyers_client_id
FYERS_SECRET_KEY=your_fyers_secret_key
FYERS_ID=your_fyers_id
FYERS_TOTP_KEY=your_fyers_totp_key
FYERS_PIN=your_fyers_pin
FYERS_REDIRECT_URI=https://trade.fyers.in/api-login/redirect-uri/index.html
```

All environment variables are required. The application will fail to start if any of these variables are missing.

## Usage

1. Start the Flask server:
```bash
python app.py
```

2. For production deployment:
```bash
gunicorn -w 2 -b 0.0.0.0:8080 --timeout 30 --keep-alive 5 --max-requests 1000 --max-requests-jitter 50 app:app
```

3. Configure Chartink to send webhooks to your server's `/webhook` endpoint.

## Project Structure

```
chartink-telegram-webhook/
├── app.py                 # Main Flask application
├── requirements.txt       # Python dependencies
├── .env                  # Environment variables (not in git)
├── .gitignore           # Git ignore rules
├── README.md            # Project documentation
└── logs/                # Log files directory
    ├── webhook.log      # Webhook activity logs
    └── performance.log  # Performance metrics
```

## API Endpoints

### POST /webhook

Receives stock alerts from Chartink and processes them.

Request body:
```json
{
    "alert_name": "Alert Name",
    "scan_name": "Scan Name",
    "stocks": "RELIANCE,TCS,HDFCBANK",
    "trigger_prices": "1500,3500,2000",
    "triggered_at": "2024-03-20 10:00:00"
}
```

## Logging

The application maintains two types of logs:
- `webhook.log`: General application logs
- `performance.log`: Performance metrics for key operations

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details. 
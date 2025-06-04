from fyers_apiv3 import fyersModel
import webbrowser
import json
import os
from datetime import datetime, timedelta

class FyersClient:
    def __init__(self):
        # Configuration from application.properties
        self.app_id = "RWCTF2HW7T"
        self.secret_id = "Y5BBJF9DW9"
        self.redirect_uri = "https://trade.fyers.in/api-login/redirect-uri/index.html"
        self.auth_code = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhcHBfaWQiOiJSV0NURjJIVzdUIiwidXVpZCI6IjMxYzBhZGE5OGQ1ZTQxZjg5NjU5MmZmMTllY2QyNjAxIiwiaXBBZGRyIjoiIiwibm9uY2UiOiIiLCJzY29wZSI6IiIsImRpc3BsYXlfbmFtZSI6IlhSMDA3MjIiLCJvbXMiOiJLMSIsImhzbV9rZXkiOiIwZWEyODJhOTgyZThmNmMwYzkyZDNhYjZjY2U5MWJlZmQ0Mjk5NGM0ZGU5N2UyYjFhOWFiODBhZSIsImlzRGRwaUVuYWJsZWQiOiJZIiwiaXNNdGZFbmFibGVkIjoiTiIsImF1ZCI6IltcImQ6MVwiLFwiZDoyXCJdIiwiZXhwIjoxNzQ4OTE2NDQzLCJpYXQiOjE3NDg4ODY0NDMsImlzcyI6ImFwaS5sb2dpbi5meWVycy5pbiIsIm5iZiI6MTc0ODg4NjQ0Mywic3ViIjoiYXV0aF9jb2RlIn0.I3v1jKoxoOzDcxnsNf3FohX5rqOCd2yte-eWgF6fKNM"
        self.access_token = None
        self.fyers = None

    def get_auth_token(self):
        """Generate authentication URL and open in browser"""
        response_type = "code"
        grant_type = "authorization_code"
        
        app_session = fyersModel.SessionModel(
            client_id=self.app_id,
            redirect_uri=self.redirect_uri,
            response_type=response_type,
            grant_type=grant_type,
            state="state",
            scope="",
            nonce=""
        )
        
        generate_token_url = app_session.generate_authcode()
        webbrowser.open(generate_token_url, new=1)

    def generate_access_token(self):
        """Generate access token using auth code"""
        app_session = fyersModel.SessionModel(
            client_id=self.app_id,
            secret_key=self.secret_id,
            grant_type="authorization_code"
        )
        
        app_session.set_token(self.auth_code)
        self.access_token = app_session.generate_token()
        return self.access_token

    def initialize_client(self):
        """Initialize Fyers client with access token"""
        if not self.access_token:
            self.generate_access_token()
            
        self.fyers = fyersModel.FyersModel(
            client_id=self.app_id,
            is_async=False,
            token=self.access_token,
            log_path=""
        )
        return self.fyers

    def get_historical_data(self, symbol, resolution="D", days=30):
        """Get historical data for a symbol"""
        if not self.fyers:
            self.initialize_client()

        # Calculate date range
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        data = {
            "symbol": symbol,
            "resolution": resolution,
            "date_format": "0",
            "range_from": str(int(start_date.timestamp())),
            "range_to": str(int(end_date.timestamp())),
            "cont_flag": "1"
        }
        
        response = self.fyers.history(data=data)
        return response

def main():
    # Create Fyers client instance
    client = FyersClient()
    
    # Open browser to get new auth token
    print("Opening browser to get new auth code...")
    client.get_auth_token()
    
    # Wait for user to complete authentication
    auth_code = input("Please enter the auth code from the browser URL: ")
    client.auth_code = auth_code
    
    # Initialize client and get access token
    print("Generating access token...")
    client.initialize_client()
    
    # Example: Get historical data for SBIN
    print("Fetching historical data for SBIN...")
    symbol = "NSE:SBIN-EQ"
    historical_data = client.get_historical_data(symbol)
    
    # Print the response
    print(json.dumps(historical_data, indent=2))

if __name__ == "__main__":
    main() 
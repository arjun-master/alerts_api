#!/bin/bash

# Update system
sudo apt-get update
sudo apt-get upgrade -y

# Install Python and required packages
sudo apt-get install -y python3-pip python3-venv git

# Create application directory
mkdir -p /home/ubuntu/chartink-telegram-webhook
cd /home/ubuntu/chartink-telegram-webhook

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install gunicorn
pip install gunicorn

# Clone repository
git clone https://github.com/arjun-master/alerts_api.git .

# Install dependencies
pip install -r requirements.txt

# Create logs directory
mkdir -p logs

# Copy systemd service file
sudo cp chartink-webhook.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable and start service
sudo systemctl enable chartink-webhook
sudo systemctl start chartink-webhook

# Set up Nginx (optional, for reverse proxy)
sudo apt-get install -y nginx

# Create Nginx configuration
sudo tee /etc/nginx/sites-available/chartink-webhook << EOF
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://localhost:8080;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

# Enable Nginx site
sudo ln -s /etc/nginx/sites-available/chartink-webhook /etc/nginx/sites-enabled/
sudo rm /etc/nginx/sites-enabled/default

# Test Nginx configuration
sudo nginx -t

# Restart Nginx
sudo systemctl restart nginx 
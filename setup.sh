#!/bin/bash
# x402chat Setup Script
# Installs dependencies, configures environment, and sets up systemd service

set -e  # Exit on error

echo "=========================================="
echo "  x402chat Setup"
echo "=========================================="
echo ""

# Detect current directory (works even when called from different location)
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

echo "App directory: $APP_DIR"
echo ""

# Check for required commands
for cmd in python3 openssl; do
    if ! command -v $cmd &> /dev/null; then
        echo "Error: $cmd is required but not installed."
        if [ "$cmd" = "python3" ]; then
            echo "Install with: sudo apt install python3 python3-venv python3-pip"
        else
            echo "Install with: sudo apt install openssl"
        fi
        exit 1
    fi
done

# Check Python version (require 3.10+)
PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYTHON_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
PYTHON_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 10 ]); then
    echo "Error: Python 3.10+ is required (found $PYTHON_VERSION)"
    exit 1
fi
echo "Python version: $PYTHON_VERSION ✓"

# Prompt for venv name
read -p "Virtual environment folder name [env]: " VENV_NAME
VENV_NAME=${VENV_NAME:-env}

# Create virtual environment if it doesn't exist
if [ ! -d "$VENV_NAME" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_NAME"
else
    echo "Using existing virtual environment: $VENV_NAME"
fi

# Activate and install dependencies
echo "Installing dependencies..."
source "$APP_DIR/$VENV_NAME/bin/activate"
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo "Dependencies installed ✓"

# Setup .env file
if [ ! -f ".env" ]; then
    if [ ! -f ".env.example" ]; then
        echo "Error: .env.example not found"
        exit 1
    fi

    echo ""
    echo "Creating .env file..."
    cp .env.example .env

    # Generate encryption key (cross-platform sed)
    ENCRYPTION_KEY=$(openssl rand -base64 32)
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=$ENCRYPTION_KEY|" .env
    else
        sed -i "s|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=$ENCRYPTION_KEY|" .env
    fi
    echo "Generated ENCRYPTION_KEY ✓"

    echo ""
    echo "IMPORTANT: Edit .env and set your HELIUS_API_KEY"
    echo "  nano $APP_DIR/.env"
    echo ""
else
    echo ".env file already exists"
    # Check if ENCRYPTION_KEY is set
    if grep -q "^ENCRYPTION_KEY=$" .env || grep -q "^ENCRYPTION_KEY=\"\"" .env; then
        echo "WARNING: ENCRYPTION_KEY is empty in .env"
        read -p "Generate ENCRYPTION_KEY now? [Y/n]: " GEN_KEY
        GEN_KEY=${GEN_KEY:-Y}
        if [[ "$GEN_KEY" =~ ^[Yy]$ ]]; then
            ENCRYPTION_KEY=$(openssl rand -base64 32)
            if [[ "$OSTYPE" == "darwin"* ]]; then
                sed -i '' "s|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=$ENCRYPTION_KEY|" .env
            else
                sed -i "s|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=$ENCRYPTION_KEY|" .env
            fi
            echo "Generated ENCRYPTION_KEY ✓"
        fi
    fi
fi

# Initialize database
echo "Initializing database..."
python app.py init

# Fix static file permissions (git doesn't preserve read permissions)
echo "Setting static file permissions..."
chmod 644 static/*.js static/*.css static/*.html 2>/dev/null || true
echo "Static files readable ✓"

# Ask about systemd setup (Linux only)
echo ""
if [[ "$OSTYPE" == "linux"* ]]; then
    read -p "Set up systemd service for auto-start? [Y/n]: " SETUP_SYSTEMD
    SETUP_SYSTEMD=${SETUP_SYSTEMD:-Y}

    if [[ "$SETUP_SYSTEMD" =~ ^[Yy]$ ]]; then
        # Check for service template
        if [ ! -f "$APP_DIR/x402chat.service" ]; then
            echo "Error: x402chat.service template not found"
            exit 1
        fi

        # Check for systemctl
        if ! command -v systemctl &> /dev/null; then
            echo "Error: systemctl not found. Is this a systemd-based system?"
            exit 1
        fi

        # Get the user to run as
        read -p "User to run service as [$USER]: " SERVICE_USER
        SERVICE_USER=${SERVICE_USER:-$USER}

        # Verify user exists
        if ! id "$SERVICE_USER" &> /dev/null; then
            echo "Error: User '$SERVICE_USER' does not exist"
            exit 1
        fi

        echo "Creating systemd service..."

        # Generate service file from template
        sed -e "s|{{USER}}|$SERVICE_USER|g" \
            -e "s|{{APP_DIR}}|$APP_DIR|g" \
            -e "s|{{VENV}}|$VENV_NAME|g" \
            "$APP_DIR/x402chat.service" | sudo tee /etc/systemd/system/x402chat.service > /dev/null

        sudo systemctl daemon-reload
        sudo systemctl enable x402chat
        echo "Service enabled ✓"

        echo ""
        read -p "Start the service now? [Y/n]: " START_NOW
        START_NOW=${START_NOW:-Y}

        if [[ "$START_NOW" =~ ^[Yy]$ ]]; then
            sudo systemctl start x402chat
            echo ""
            echo "Service started! Checking status..."
            sleep 2
            sudo systemctl status x402chat --no-pager || true
        fi

        echo ""
        echo "Useful commands:"
        echo "  sudo systemctl status x402chat     # Check status"
        echo "  sudo systemctl restart x402chat    # Restart"
        echo "  sudo systemctl stop x402chat       # Stop"
        echo "  journalctl -u x402chat -f          # Live logs"

        # Verify routes after service starts
        if [[ "$START_NOW" =~ ^[Yy]$ ]]; then
            echo ""
            echo "Verifying static file routes..."
            sleep 1

            ROUTES=("/" "/index.css" "/index.js" "/dashboard" "/dashboard.css" "/dashboard.js"
                   "/donate.css" "/donate.js" "/security-utils.js" "/wallet-auth.js"
                   "/privacy-scorer.js" "/notification.mp3" "/global.css" "/overlay" "/favicon.svg")

            ALL_OK=true
            for route in "${ROUTES[@]}"; do
                STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8765$route 2>/dev/null || echo "000")
                if [ "$STATUS" = "200" ]; then
                    echo "  ✅ $route"
                else
                    echo "  ❌ $route - HTTP $STATUS"
                    ALL_OK=false
                fi
            done

            if [ "$ALL_OK" = true ]; then
                echo ""
                echo "✅ All routes verified successfully!"
            else
                echo ""
                echo "⚠️  Some routes failed. Check the logs: journalctl -u x402chat -n 50"
            fi
        fi
    fi

    # Ask about nginx setup
    echo ""
    read -p "Set up nginx reverse proxy? [y/N]: " SETUP_NGINX
    SETUP_NGINX=${SETUP_NGINX:-N}

    if [[ "$SETUP_NGINX" =~ ^[Yy]$ ]]; then
        if [ ! -f "$APP_DIR/nginx-x402chat.conf" ]; then
            echo "Error: nginx-x402chat.conf template not found"
        elif [ ! -x /usr/sbin/nginx ]; then
            echo "Error: nginx not installed. Install with: sudo apt install nginx"
        else
            read -p "Domain name (e.g., example.com): " DOMAIN_NAME
            if [ -z "$DOMAIN_NAME" ]; then
                echo "Error: Domain name required"
            else
                echo "Creating nginx config..."
                sed "s|{{DOMAIN}}|$DOMAIN_NAME|g" "$APP_DIR/nginx-x402chat.conf" \
                    | sudo tee /etc/nginx/sites-available/x402chat > /dev/null

                if [ ! -L /etc/nginx/sites-enabled/x402chat ]; then
                    sudo ln -s /etc/nginx/sites-available/x402chat /etc/nginx/sites-enabled/
                fi

                if sudo nginx -t 2>/dev/null; then
                    sudo systemctl reload nginx
                    echo "nginx configured ✓"
                    echo ""
                    echo "To enable HTTPS, run:"
                    echo "  sudo certbot --nginx -d $DOMAIN_NAME -d www.$DOMAIN_NAME"
                else
                    echo "Warning: nginx config test failed. Check /etc/nginx/sites-available/x402chat"
                fi
            fi
        fi
    fi
else
    echo "Note: systemd/nginx setup skipped (not Linux)"
    echo "To run manually: source $VENV_NAME/bin/activate && python app.py server"
fi

echo ""
echo "=========================================="
echo "  Setup Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "  1. Edit .env with your HELIUS_API_KEY"
echo "  2. Visit https://your-domain.com or http://localhost:8765"
echo ""

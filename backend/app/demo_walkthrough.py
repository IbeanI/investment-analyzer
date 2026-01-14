# demo_walkthrough.py
import subprocess
import sys
import time

import requests

# =============================================================================
# CONFIGURATION
# =============================================================================
API_URL = "http://127.0.0.1:8000"
BACKEND_CONTAINER = "backend"  # Name of your service in docker-compose.yml

# Colors for pretty printing
GREEN = "\033[92m"
RED = "\033[91m"
RESET = "\033[0m"


def log(message, success=True):
    color = GREEN if success else RED
    print(f"{color}[*] {message}{RESET}")


def run_command(command, check=True):
    """Run a shell command and print output."""
    print(f"$ {command}")
    result = subprocess.run(command, shell=True, text=True, capture_output=True)
    if check and result.returncode != 0:
        log(f"Command failed: {command}\n{result.stderr}", success=False)
        sys.exit(1)
    return result


# =============================================================================
# STEP 1: INFRASTRUCTURE TEARDOWN & STARTUP
# =============================================================================
print("=== STEP 1: RESTARTING INFRASTRUCTURE ===")
# 1. Bring down everything and remove volumes (Clean Slate)
run_command("docker compose down -v")

# 2. Rebuild and start
run_command("docker compose up -d --build")

# 3. Wait for Health Check
print("Waiting for API to be healthy...", end="", flush=True)
for _ in range(30):  # Wait up to 30 seconds
    try:
        response = requests.get(f"{API_URL}/health/db")
        if response.status_code == 200:
            print(" Done.")
            break
    except requests.exceptions.ConnectionError:
        time.sleep(1)
        print(".", end="", flush=True)
else:
    log("API did not start in time.", success=False)
    sys.exit(1)

# =============================================================================
# STEP 2: DATABASE INITIALIZATION
# =============================================================================
print("\n=== STEP 2: INITIALIZING DATABASE ===")
# Run init_db.py inside the container
run_command(f"docker compose exec {BACKEND_CONTAINER} python init_db.py")

# =============================================================================
# STEP 3: SEEDING DATA (USER)
# =============================================================================
print("\n=== STEP 3: CREATING TEST USER ===")
# Since we don't have a POST /users/ endpoint yet, we inject it via Python
# running inside the container.
create_user_script = """
from app.database import SessionLocal
from app.models import User
db = SessionLocal()
if not db.query(User).filter_by(email='demo@example.com').first():
    user = User(email='demo@example.com', hashed_password='hashed_secret')
    db.add(user)
    db.commit()
    print('User created successfully.')
else:
    print('User already exists.')
db.close()
"""
# Escape quotes for shell compatibility
cmd = f"docker compose exec {BACKEND_CONTAINER} python -c \"{create_user_script}\""
run_command(cmd)

# =============================================================================
# STEP 4: API TESTING (PORTFOLIO)
# =============================================================================
print("\n=== STEP 4: CREATING PORTFOLIO ===")
payload = {
    "name": "My Tech Portfolio",
    "user_id": 1,  # The user we just created
    "currency": "USD"
}
response = requests.post(f"{API_URL}/portfolios/", json=payload)
if response.status_code == 201:
    data = response.json()
    log(f"Portfolio Created: ID {data['id']} - {data['name']}")
    portfolio_id = data['id']
else:
    log(f"Failed to create portfolio: {response.text}", success=False)
    sys.exit(1)

# =============================================================================
# STEP 5: API TESTING (TRANSACTION + ASSET RESOLUTION)
# =============================================================================
print("\n=== STEP 5: CREATING TRANSACTION (TRIGGERING YAHOO FETCH) ===")
# We create a transaction for "NVDA".
# The system should:
# 1. Check DB for NVDA (It's missing).
# 2. Call Yahoo Finance to get metadata.
# 3. Create the Asset "NVDA".
# 4. Create the Transaction.

txn_payload = {
    "portfolio_id": portfolio_id,
    "ticker": "NVDA",
    "exchange": "NASDAQ",
    "transaction_type": "BUY",
    "date": "2024-01-15T10:00:00Z",
    "quantity": 10,
    "price_per_share": 550.00,
    "currency": "USD",
    "fee": 5.00
}

start_time = time.time()
response = requests.post(f"{API_URL}/transactions/", json=txn_payload)
duration = time.time() - start_time

if response.status_code == 201:
    data = response.json()
    asset = data['asset']
    log(f"Transaction Created in {duration:.2f}s")
    log(f"Resolved Asset: {asset['ticker']} ({asset['name']})")
    log(f"Asset Class: {asset['asset_class']}")
else:
    log(f"Failed to create transaction: {response.text}", success=False)
    sys.exit(1)

# =============================================================================
# STEP 6: VERIFICATION
# =============================================================================
print("\n=== STEP 6: VERIFYING ASSETS ===")
# List all assets to verify NVDA was persisted
response = requests.get(f"{API_URL}/assets/")
assets = response.json()['items']
print(f"Total Assets in DB: {len(assets)}")
for asset in assets:
    print(f"- {asset['ticker']} ({asset['exchange']}): {asset['name']}")

log("\nWalkthrough Completed Successfully! 🚀")

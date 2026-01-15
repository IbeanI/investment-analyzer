# 📖 Jupyter Notebook Walkthrough Guide

## Overview

The `investment_portfolio_complete_walkthrough.ipynb` is a **comprehensive, beginner-friendly** notebook that covers **everything** from Phase 1 (Foundation) through Phase 2 (Data Ingestion).

---

## 🖥️ Recommended Setup: Side-by-Side View

For the best learning experience, set up your screen like this:

```
┌──────────────────────────────────┬──────────────────────────────────┐
│                                  │                                  │
│         JUPYTER NOTEBOOK         │       TERMINAL (Docker Logs)     │
│                                  │                                  │
│  ┌────────────────────────────┐  │  $ docker compose logs -f backend│
│  │ # Create Transaction       │  │                                  │
│  │                            │  │  INFO | Resolving asset: NVDA    │
│  │ ticker = "NVDA"            │  │  INFO | Asset not in DB...       │
│  │ [Run Cell]                 │  │  INFO | Fetching from Yahoo...   │
│  └────────────────────────────┘  │  INFO | Created new asset: 1     │
│                                  │                                  │
│  ┌────────────────────────────┐  │                                  │
│  │ ✅ Transaction created!    │  │                                  │
│  │ Asset: NVIDIA Corporation  │  │                                  │
│  └────────────────────────────┘  │                                  │
│                                  │                                  │
└──────────────────────────────────┴──────────────────────────────────┘
```

This lets you see **exactly what the server is doing** as you interact with the API.

---

## 🚀 Quick Start

### Step 1: Start Docker (if not running)

```bash
# Navigate to your project directory
cd /path/to/investment-portfolio-analyzer

# Bring down everything and remove volumes (Clean Slate)
docker compose down -v

# Rebuild and start the containers
docker compose up -d --build
```

### Step 2: Open Log Viewer Terminal

**Open a NEW terminal window** and run:

```bash
docker compose logs -f backend
```

This command:
- `logs` - Shows container output
- `-f` - "Follow" mode (real-time updates)
- `backend` - Only show the FastAPI backend logs

**Leave this terminal open and visible!**

### Step 3: Start Jupyter Notebook

In another terminal:

```bash
# If using standard Jupyter
jupyter notebook investment_portfolio_complete_walkthrough.ipynb

# Or if using JupyterLab
jupyter lab investment_portfolio_complete_walkthrough.ipynb

# Or if using VS Code
code investment_portfolio_complete_walkthrough.ipynb
```

### Step 4: Arrange Windows Side-by-Side

- **macOS**: Drag windows to screen edges, or use Split View
- **Windows**: Win+Left/Right arrow keys
- **Linux**: Depends on your window manager

---

## 📋 What You'll See in the Logs

### When Creating a NEW Asset (First Time)

```
2024-01-15 10:30:45 | INFO | Resolving asset: NVDA on NASDAQ
2024-01-15 10:30:45 | INFO | Asset NVDA on NASDAQ not in DB, fetching from provider
2024-01-15 10:30:45 | INFO | Fetching metadata for NVDA from Yahoo Finance...
2024-01-15 10:30:46 | INFO | Yahoo Finance returned: NVIDIA Corporation (Technology)
2024-01-15 10:30:46 | INFO | Created new asset: 1 (NVDA on NASDAQ)
```

**What this means:**
1. System received request for NVDA
2. Checked database - not found
3. Called Yahoo Finance API
4. Created new Asset record

### When Using a CACHED Asset (Second Time)

```
2024-01-15 10:31:00 | INFO | Resolving asset: NVDA on NASDAQ
2024-01-15 10:31:00 | DEBUG | Found existing active asset: 1
```

**What this means:**
1. System received request for NVDA
2. Found it in database - no Yahoo call needed!

### When Uploading CSV

```
2024-01-15 10:32:00 | INFO | Processing upload: transactions.csv for portfolio 1 (date_format=US)
2024-01-15 10:32:00 | INFO | Parsing CSV file: transactions.csv (date_format=US)
2024-01-15 10:32:00 | INFO | Parsed transactions.csv: 4 rows OK, 0 errors
2024-01-15 10:32:01 | INFO | Resolving 3 unique assets in batch...
2024-01-15 10:32:03 | INFO | Upload successful: 4 transactions created
```

### When There's an Error

```
2024-01-15 10:33:00 | WARNING | Invalid date format in row 2: '15/03/2024'
2024-01-15 10:33:00 | ERROR | Upload failed: 1 parsing errors
```

---

## 🔧 Log Level Configuration

By default, you'll see INFO level logs. To see more detail:

### Edit your `.env` file:

```bash
# backend/.env
LOG_LEVEL=DEBUG
```

### Restart the container:

```bash
docker compose restart backend
```

### Now you'll see DEBUG messages:

```
DEBUG | Checking database for asset: NVDA on NASDAQ
DEBUG | Query: SELECT * FROM assets WHERE ticker='NVDA' AND exchange='NASDAQ'
DEBUG | Found existing active asset: 1
```

---

## 📊 Log Filtering Commands

### Show only errors:

```bash
docker compose logs backend 2>&1 | grep -i error
```

### Show only asset resolution:

```bash
docker compose logs backend 2>&1 | grep -i "resolving\|created new asset"
```

### Show last 100 lines:

```bash
docker compose logs --tail=100 backend
```

### Show logs from last 5 minutes:

```bash
docker compose logs --since="5m" backend
```

### Show logs with timestamps:

```bash
docker compose logs -t backend
```

---

## 🎯 What to Watch For

### During Section 11 (Asset Resolution)

When you create your first transaction, watch for:
- "Resolving asset: XXX on YYY"
- "not in DB, fetching from provider"
- "Created new asset: N"

### During Section 12 (Transactions - Second Time)

Watch for the ABSENCE of Yahoo calls:
- Should just see "Found existing active asset"
- Much faster response!

### During Section 14 (CSV Upload)

Watch for:
- "Processing upload" with date_format
- "Parsing CSV file"
- Row counts and error counts
- "Upload successful" or error details

### During Section 15 (Error Handling)

Watch for:
- WARNING and ERROR messages
- Specific row numbers with issues
- Clear error descriptions

---

## 🐛 Troubleshooting

### "No logs appearing"

```bash
# Check if container is running
docker compose ps

# If not running, start it
docker compose up -d backend
```

### "Logs are old / not updating"

```bash
# Make sure you're using -f (follow) flag
docker compose logs -f backend
```

### "Too many logs / scrolling too fast"

```bash
# Clear screen and start fresh
clear && docker compose logs -f --tail=20 backend
```

### "Want to see database queries"

Add to your `.env`:
```
SQLALCHEMY_ECHO=True
```

Then restart: `docker compose restart backend`

---

## 🎓 Learning Tips

1. **Run cells slowly** - Give yourself time to read the logs
2. **Compare timing** - Notice how cached assets are faster
3. **Intentionally cause errors** - See how the system responds
4. **Experiment freely** - The notebook is designed for exploration

---

## 📁 File Locations

```
your-project/
├── investment_portfolio_complete_walkthrough.ipynb   # The notebook
├── NOTEBOOK_GUIDE.md                                 # This file
├── backend/
│   ├── .env                                          # Configuration
│   └── app/
│       └── ...                                       # Application code
└── docker-compose.yml                                # Container definitions
```

---

Happy learning! 🚀

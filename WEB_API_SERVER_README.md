# Web API Server - FastAPI Dashboard

Lightweight FastAPI web server for viewing people count data from database.

## Features

- ✅ Read-only access to SQLite database
- ✅ FastAPI REST API
- ✅ Beautiful HTML dashboard
- ✅ Auto-refresh every 5 seconds
- ✅ LAN access (bind to 0.0.0.0)
- ✅ Never crashes (safe error handling)

## Installation

```bash
pip install fastapi uvicorn[standard]
```

Or install all requirements:

```bash
pip install -r requirements.txt
```

## Usage

### Start Web Server

```bash
python web_api_server.py
```

The server will start on port 8000 and print access URLs.

### Access Dashboard

**From the same machine:**
```
http://localhost:8000
```

**From another PC on the same LAN:**
```
http://<LAN_IP>:8000
```

The LAN IP will be displayed when the server starts.

## API Endpoints

### GET `/api/status`

Returns JSON with current status:

```json
{
  "date": "2026-01-07",
  "total_morning": 5,
  "realtime": 3,
  "missing": 2,
  "last_update": "14:30:45"
}
```

### GET `/`

Returns HTML dashboard page.

## Configuration

Edit `web_api_server.py` to change:

- `DB_PATH`: Database file path (default: `"data/people_counter.db"`)
- `MORNING_START`: Morning phase start time (default: `"11:05"`)
- `MORNING_END`: Morning phase end time (default: `"11:14"`)
- `PORT`: Server port (default: `8000`)

## Data Displayed

1. **Total Morning**: Count of IN events during morning phase (11:05 - 11:14)
2. **Current Realtime**: Current people count (IN - OUT from all events today)
3. **Missing People**: Total Morning - Realtime (never negative)
4. **Last Update**: Time of last event or current time

## Safety Features

- ✅ Never crashes - returns safe defaults on error
- ✅ Read-only database access
- ✅ Handles missing database gracefully
- ✅ Handles empty database gracefully
- ✅ Auto-refresh without page reload

## Running in Background

### Windows (PowerShell)

```powershell
Start-Process python -ArgumentList "web_api_server.py" -WindowStyle Hidden
```

### Linux/Mac

```bash
nohup python web_api_server.py > web_server.log 2>&1 &
```

## Troubleshooting

### Port Already in Use

Change port in `web_api_server.py`:
```python
PORT = 8001  # Use different port
```

### Cannot Access from Other PC

1. Check firewall settings
2. Ensure server is bound to `0.0.0.0` (not `127.0.0.1`)
3. Verify both PCs are on the same network
4. Check if LAN IP is displayed correctly

### Database Not Found

Ensure database file exists at `data/people_counter.db`. Server will still run but return 0 values.


# RouteSafe

Wildfire-aware routing. RouteSafe pulls live fire detections, wind and air-quality data, builds a smoke hazard field on an H3 hex grid, scores driving routes by smoke exposure, and suggests safer alternatives.

Built at Hack Canada 2026.

## How it works

| Layer | What it does | Code |
|---|---|---|
| L1 — Ingestion | NASA FIRMS fire hotspots, wind, AQI, Google Directions proxy | `backend/services/{firms,envcanada,aqi}.py`, `backend/routers/ingestion.py` |
| L2 — Hazard field | Projects fires + wind onto an H3 hexagonal smoke-severity grid | `backend/services/hazard_field.py` |
| L3 — Route scorer | Scores each route segment, estimates smoke dose (cigarette equivalents) | `backend/services/{route_scorer,smoke_dose}.py` |
| L4 — Optimizer | Dijkstra over the H3 grid to find a lower-exposure route | `backend/services/optimizer.py` |

Frontend: React + Vite, Mapbox GL, Tailwind CSS.

## Running locally

### 1. Backend (FastAPI, port 8000)

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cd backend
cp .env.example .env            # then fill in your keys
uvicorn main:app --reload --port 8000
```

API docs: http://localhost:8000/docs

### 2. Frontend (Vite, port 5173)

```bash
cd frontend
cp .env.example .env            # then add your Mapbox token
npm install
npm run dev
```

Open http://localhost:5173. In development, Vite proxies `/score`, `/ingest`, `/directions`, `/optimize` and `/health` to the backend.

## Environment variables

**`backend/.env`**

| Variable | Where to get it |
|---|---|
| `NASA_FIRMS_API_KEY` | https://firms.modaps.eosdis.nasa.gov/api/map_key/ |
| `GOOGLE_MAPS_API_KEY` | Google Cloud Console (Directions API enabled) |
| `WAQI_TOKEN` | https://aqicn.org/data-platform/token/ (falls back to `demo`) |
| `WEATHER_API_KEY` | https://www.weatherapi.com/ |

**`frontend/.env`**

| Variable | Notes |
|---|---|
| `VITE_MAPBOX_TOKEN` | Mapbox public token (`pk.…`) |
| `VITE_API_BASE` | Optional — backend URL in production; leave unset for local dev |

`.env` files are git-ignored. Never commit real keys; only the `.env.example` templates belong in the repo.

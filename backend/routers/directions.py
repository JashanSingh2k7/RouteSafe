"""
routers/directions.py

Proxy for Google Directions API.
The browser can't call Google Directions directly (no CORS),
so the frontend calls us and we forward to Google.

GET /directions?origin=Calgary,AB&destination=Banff,AB&alternatives=false
GET /directions?origin=Calgary,AB&destination=Banff,AB&waypoints=via:51.2,-116.1|via:51.3,-115.9
"""

import os
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter()

GOOGLE_MAPS_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"


@router.get(
    "",
    summary="Proxy Google Directions API",
    description=(
        "Forwards origin/destination/waypoints to Google Directions and returns "
        "the full response including encoded polyline and duration. "
        "The frontend uses overview_polyline.points and legs[].duration.value."
    ),
)
async def get_directions(
    origin:       str  = Query(..., description="Start location", example="Calgary, AB"),
    destination:  str  = Query(..., description="End location", example="Banff, AB"),
    alternatives: bool = Query(False, description="Return alternative routes"),
    waypoints:    Optional[str] = Query(None, description="Pipe-separated waypoints, e.g. via:51.2,-116.1|via:51.3,-115.9"),
):
    if not GOOGLE_MAPS_KEY:
        raise HTTPException(
            status_code=500,
            detail="GOOGLE_MAPS_API_KEY is not set on the backend.",
        )

    params = {
        "origin": origin,
        "destination": destination,
        "alternatives": str(alternatives).lower(),
        "key": GOOGLE_MAPS_KEY,
    }

    if waypoints:
        params["waypoints"] = waypoints

    logger.info(
        "Proxying directions: %s → %s (alternatives=%s, waypoints=%s)",
        origin, destination, alternatives, waypoints,
    )

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(DIRECTIONS_URL, params=params)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"Google API returned {e.response.status_code}")
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Failed to reach Google API: {e}")

    if data.get("status") not in ("OK", "ZERO_RESULTS"):
        raise HTTPException(
            status_code=502,
            detail=f"Google Directions error: {data.get('status')} — {data.get('error_message', '')}",
        )

    return data
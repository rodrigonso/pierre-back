from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict
import uvicorn
from pinterest_scraper import PinterestScraper
from dotenv import load_dotenv
import os
from stylist_service import run_stylist_service

# Load environment variables from .env file
load_dotenv()

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

class SearchRequest(BaseModel):
    query: str
    num_pins: Optional[int] = 50

class TrendingRequest(BaseModel):
    num_pins: Optional[int] = 50

class AnalysisRequest(BaseModel):
    pins_data: List[Dict]

class StylistRequest(BaseModel):
    query: str

@app.post("/search")
async def search_pins(request: SearchRequest):
    try:
        scraper = PinterestScraper()
        results = scraper.search_pins(request.query, request.num_pins)
        scraper.close()
        return {"status": "success", "data": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/trending")
async def get_trending_pins(request: TrendingRequest):
    try:
        scraper = PinterestScraper()
        results = scraper.get_trending_pins(request.num_pins)
        scraper.close()
        return {"status": "success", "data": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/stylist")
async def get_stylist(request: StylistRequest):
    try:
        stylist_result = run_stylist_service(request.query)
        return stylist_result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

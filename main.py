from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict
import uvicorn
from pinterest_scraper import PinterestScraper
from stylist_service import StylistService
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

app = FastAPI()

# Initialize stylist service with API key from .env
stylist_service = StylistService(api_key=os.getenv("OPENAI_API_KEY"))

class SearchRequest(BaseModel):
    query: str
    num_pins: Optional[int] = 50

class TrendingRequest(BaseModel):
    num_pins: Optional[int] = 50

class AnalysisRequest(BaseModel):
    pins_data: List[Dict]

class PersonalizationRequest(BaseModel):
    pins_data: List[Dict]
    user_preferences: Dict

# class WardrobeRequest(BaseModel):
#     user_preferences: Dict
#     budget_range: Dict[str, float]
#     season: str
class WardrobeRequest(BaseModel):
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

@app.post("/build_wardrobe")
async def build_wardrobe(request: WardrobeRequest):
    try:
        wardrobe = stylist_service.build_wardrobe(
            request.query
        )
        return wardrobe
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

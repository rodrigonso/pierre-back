from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from jose import JWTError, jwt

import uvicorn
from dotenv import load_dotenv
import os
from stylist_service import run_stylist_service
from image_service import generate
from supabase import create_client, Client
from pydantic import BaseModel
from models import Product
from concurrent.futures import ThreadPoolExecutor
import asyncio

# Load environment variables from .env file
load_dotenv()

app = FastAPI()

supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# Add request authentication middleware
# @app.middleware("http")
# async def add_authentication(request: Request, call_next):

#     if request.method == "OPTIONS":
#         return await call_next(request)

#     token = request.headers.get("authorization", "").replace("Bearer ", "")

#     if not token:
#         return Response("Unauthorized", status_code=401)

#     try:
#         auth = supabase.auth.get_user(token)
#         request.state.user_id = auth.user.id
#         supabase.postgrest.auth(token)

#     except Exception:
#         return Response("Invalid user token", status_code=401)

#     return await call_next(request)\

executor = ThreadPoolExecutor()

class StylistRequest(BaseModel):
    user_gender: str
    user_prompt: str
    user_preferred_brands: list
    num_of_outfits: int

@app.post("/stylist")
async def get_stylist(request: StylistRequest):
    try:
        outfits: dict = run_stylist_service(request.model_dump())

        # Run the database operations in a separate thread
        loop = asyncio.get_event_loop()
        loop.run_in_executor(executor, process_outfits, outfits)

        return outfits
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail=str(e))

def process_outfits(outfits: dict):
    """
    Process outfits and insert data into the database in a separate thread.
    """
    for outfit in outfits.get("outfits", []):

        outfit_response = supabase.table("outfits").insert({
            "name": outfit.get("name"),
            "description": outfit.get("description")
        }).execute()

        # Get the inserted outfit's ID
        outfit_id = outfit_response.data[0]["id"]

        for item in outfit.get("items", []):
            for product in item.get("products", []):
                print("Inserting product: ", product.title)
                product_response = supabase.table("products").insert({
                    "id": product.id,
                    "type": product.type,
                    "query": product.query,
                    "link": product.link,
                    "title": product.title,
                    "price": product.price,
                    "images": product.images,
                    "source": product.source,
                    "description": product.description,
                    "outfit_id": outfit_id  # Foreign key relationship
                }).execute()

class GenerateImage(BaseModel):
    products: list

@app.post("/generate_image")
async def generate_image(request: Request):
    try:
        data = await request.json()
        generated_image_url: str = generate(data)
        return {"status": "success", "url": generated_image_url}
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

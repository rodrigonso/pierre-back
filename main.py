from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from jose import JWTError, jwt

import uvicorn
from dotenv import load_dotenv
import os
from stylist_service import run_stylist_service
from image_service import generate_outfit_image
from finder_service import run_finder_service
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

        # Run the database operations in a separate thread and wait for completion (no longer needed to be in seperate thread...)
        outfits_with_ids_and_images = await process_outfits(outfits)

        return outfits_with_ids_and_images
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail=str(e))
    
def generate_images_for_outfits(outfit: dict) -> str:
    """
    Generate images for each outfit in a separate thread.
    """
    try:
        # Offload image generation to a separate thread
        image_url = generate_outfit_image(outfit.get("items", []))
        return image_url

    except Exception as e:
        print(f"Error generating image for outfit {outfit.get('id')}: {e}")
        return None
    
def save_outfit_to_db(outfit: dict) -> dict:
    """
    Save outfit to the database.
    """
    try:
        outfit_response = supabase.table("outfits").insert({
            "name": outfit.get("name"),
            "description": outfit.get("description"),
            "query": outfit.get("query"),
            "image_url": outfit.get("image_url")
        }).execute()

        # Get the inserted outfit's ID and update the outfit
        outfit_id = outfit_response.data[0]["id"]
        outfit["id"] = outfit_id

        for product in outfit.get("items", []):
            print("Inserting product: ", product.title)
            try:
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
                }).execute()
            except Exception as product_error:
                # Log the error and continue if the product already exists
                print(f"Error inserting product {product.id}: {product_error}")

            # Insert into product_outfit_junction table
            try:
                supabase.table("product_outfit_junction").insert({
                    "outfit_id": outfit_id,
                    "product_id": product.id
                }).execute()
            except Exception as junction_error:
                # Log the error and continue
                print(f"Error inserting into product_outfit_junction for product {product.id}: {junction_error}")

    except Exception as e:
        print(f"Error saving outfit to database: {e}")
        return None
    return outfit

async def process_outfits(outfits: dict) -> dict:
    """
    Process outfits and insert data into the database in a separate thread.
    Updates the outfits dictionary with IDs from the database.
    """

    loop = asyncio.get_event_loop()
    loop2 = asyncio.get_event_loop()

    for outfit in outfits.get("outfits", []):
        outfit_image_url = await loop2.run_in_executor(executor, generate_images_for_outfits, outfit)
        outfit["image_url"] = outfit_image_url
        outfit_with_id = await loop.run_in_executor(executor, save_outfit_to_db, outfit)

        outfit = outfit_with_id

    return outfits

class GenerateImageRequest(BaseModel):
    products: list[Product]

@app.post("/generate_image")
async def generate_image(request: GenerateImageRequest):
    try:
        generated_image_url: str = generate_outfit_image(request.products)
        return {"status": "success", "url": generated_image_url}
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail=str(e))
    
class FindOutfitRequest(BaseModel):
    image_url: str

@app.post("/find_outfit")
async def find_outfit(request: FindOutfitRequest):
    try:
        # Call the finder service to get the product matches
        results = await run_finder_service(request.image_url)

        return {"status": "success", "matches": results}
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from jose import JWTError, jwt

import uvicorn
from dotenv import load_dotenv
import os
from stylist_service import run_stylist_service
from test import run_test_service
from supabase import create_client, Client
from pydantic import BaseModel

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

class StylistRequest(BaseModel):
    user_gender: str
    user_prompt: str
    user_preferred_brands: list
    num_of_outfits: int

@app.post("/stylist")
async def get_stylist(request: Request):
    try:
        stylist_result = run_stylist_service(request)
        return stylist_result
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/test")
async def get_stylist_test(request: Request):
    try:
        with open('test_response.json', 'r') as f:
            test_result = f.read()
            return test_result
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail=str(e))

class DevRequest(BaseModel):
    user_gender: str
    user_preferred_brands: list
    user_prompt: str

@app.post("/dev")
async def test(request: DevRequest):
    try:
        test = await run_test_service(request.user_prompt, request.user_gender, request.user_preferred_brands)
        print(test)
        return test.model_dump_json()

    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

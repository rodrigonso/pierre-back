from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from jose import JWTError, jwt

import uvicorn
from dotenv import load_dotenv
import os
from stylist_service import run_stylist_service
from supabase import create_client, Client

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
@app.middleware("http")
async def add_authentication(request: Request, call_next):

    if request.method == "OPTIONS":
        return await call_next(request)

    token = request.headers.get("authorization", "").replace("Bearer ", "")

    if not token:
        return Response("Unauthorized", status_code=401)

    try:
        auth = supabase.auth.get_user(token)
        request.state.user_id = auth.user.id
        supabase.postgrest.auth(token)

    except Exception:
        return Response("Invalid user token", status_code=401)

    return await call_next(request)

@app.post("/stylist")
async def get_stylist(request: Request):
    try:
        data = await request.json()
        stylist_result = run_stylist_service(data)
        return stylist_result
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

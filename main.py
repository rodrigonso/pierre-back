from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

# Import route modules
from routes import stylist, outfits, products, invite, collections

# Create FastAPI app
app = FastAPI(
    title="Pierre API",
    description="Backend API for Pierre fashion platform",
    version="1.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure this properly for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(stylist.router, prefix="/api")
app.include_router(outfits.router, prefix="/api")
app.include_router(products.router, prefix="/api")
app.include_router(invite.router, prefix="/api")
app.include_router(collections.router, prefix="/api")

@app.get("/")
async def root():
    """
    Root endpoint for health check
    
    Returns:
        dict: Welcome message and API status
    """
    return {"message": "Pierre API is running", "status": "healthy"}

@app.get("/health")
async def health_check():
    """
    Health check endpoint
    
    Returns:
        dict: API health status
    """
    return {"status": "healthy", "service": "Pierre API"}

if __name__ == "__main__":
    import uvicorn
    # Only enable reload in development mode
    is_development = os.getenv("ENVIRONMENT", "development").lower() == "development"
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=is_development, workers=12)

# Pierre API Backend

A FastAPI-based backend service for the Pierre fashion platform.

## Setup

### Prerequisites
- Python 3.8 or higher
- pip package manager

### Installation

1. Navigate to the project directory:
```bash
cd pierre-back
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
venv\Scripts\activate  # On Windows
# source venv/bin/activate  # On Linux/Mac
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Create environment file:
```bash
copy .env.example .env  # On Windows
# cp .env.example .env  # On Linux/Mac
```

### Running the API

Start the development server:
```bash
python main.py
```

Or use uvicorn directly:
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at:
- Main API: http://localhost:8000
- Interactive docs: http://localhost:8000/docs
- Alternative docs: http://localhost:8000/redoc

## API Endpoints

### Stylists
- `POST /api/stylist/` - Create a new stylist
- `GET /api/stylists/` - Get all stylists (bonus endpoint)

### Products
- `POST /api/products/` - Create a new product
- `GET /api/products/` - Get all products (bonus endpoint)

### Health Check
- `GET /` - Root endpoint
- `GET /health` - Health check endpoint

## Example Usage

### Create a Stylist
```bash
curl -X POST "http://localhost:8000/api/stylist/" \
     -H "Content-Type: application/json" \
     -d '{
       "name": "Jane Smith",
       "email": "jane@example.com",
       "specialties": ["evening wear", "casual"],
       "bio": "Professional stylist with 5 years experience",
       "experience_years": 5
     }'
```

### Create a Product
```bash
curl -X POST "http://localhost:8000/api/products/" \
     -H "Content-Type: application/json" \
     -d '{
       "name": "Designer Dress",
       "description": "Elegant evening dress",
       "category": "dresses",
       "brand": "Fashion Brand",
       "price": 299.99,
       "sizes": ["S", "M", "L"],
       "colors": ["black", "navy"]
     }'
```

## Development Notes

- Currently uses in-memory storage for simplicity
- Ready for integration with Supabase database
- CORS is configured to allow all origins (update for production)
- No authentication implemented yet (as requested)

## Next Steps

1. Integrate with Supabase database
2. Implement authentication using Supabase Auth
3. Add more sophisticated error handling
4. Implement rate limiting
5. Add logging and monitoring

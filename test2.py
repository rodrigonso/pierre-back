import requests
import json
from dotenv import load_dotenv

load_dotenv()

def fetch_and_parse_json(url):
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()  # Parse and return JSON data
    else:
        raise Exception(f"Error fetching data: {response.status_code}")

# Example usage
url = "https://serpapi.com/search.json?device=desktop&engine=google_product&gl=us&google_domain=google.com&hl=en&product_id=4783583468536379636"
data = fetch_and_parse_json(url)
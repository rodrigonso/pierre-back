import uuid
import os
from google import genai
from google.genai import types
import requests
from services.stylist import Outfit
from services.db import get_database_service

class ImageService:
    def __init__(self):
        self.client = genai.Client()
        self.db_service = get_database_service()

    def _save_image(self, data: bytes, name: str) -> str:
        path = f"images/{name}"

        f = open(path, "wb")
        f.write(data)
        f.close()

        return path

    def _dowload_image(self, image_url: str) -> bytes:
        response = requests.get(image_url)
        if response.status_code == 200:
            return response.content
        else:
            raise Exception(f"Failed to download image from {image_url}, status code: {response.status_code}")
    
    def _call_llm(self, content):
        model = "gemini-2.0-flash-exp-image-generation"
        generate_content_config = types.GenerateContentConfig(
            response_modalities=["image", "text"],
            response_mime_type="text/plain",
        )

        response: types.GenerateContentResponse = self.client.models.generate_content(
            model=model,
            contents=content,
            config=generate_content_config,
        )

        return response

    def _process_products(self, products):
        files = []
        temp_files = []
        for product in products:

            if not product.images:
                raise ValueError(f"Product {product} does not have an image URL.")

            # Skip unsupported product types
            if product.type not in ["top", "bottom", "dress", "outerwear", "shoes"]:
                continue

            image_data = self._dowload_image(product.images[0])
            file_path = self._save_image(image_data, f"garment_{product.type}.jpg")
            temp_files.append(file_path)

            uploaded_image = self.client.files.upload(file=file_path)
            files.append(uploaded_image)

        # Delete all files from the images dir
        for file_path in temp_files:
            if os.path.exists(file_path):
                os.remove(file_path)

        return files

    def generate_image(self, outfit: Outfit):
        product_images = self._process_products(outfit.products)

        user_parts = [types.Part.from_uri(file_uri=image.uri, mime_type=image.mime_type) for image in product_images]
        user_parts.append(types.Part.from_text(text="""Generate an image of a female model on a neutral background wearing the garments from the images provided."""))

        contents = [types.Content(role="user", parts=user_parts)]
        response: types.GenerateContentResponse  = self._call_llm(contents)

        generated_image_url = None
        for candidate in response.candidates:
            if candidate.content.parts[0].inline_data:

                file_name = f"{outfit.name}_{uuid.uuid4().hex}.png"
                binary_data = candidate.content.parts[0].inline_data.data
                generated_image_url = self.db_service.upload_image(file_name, binary_data)
                print(f"Generated image URL: {generated_image_url}")

                break

        return generated_image_url

from google import genai
from google.genai import types
import requests
from services.stylist import Outfit
import uuid
import os
from services.db import supabase

class ImageService:
    def __init__(self):
        self.client = genai.Client()

    def _save_image(self, data: bytes, name: str) -> str:
        path = f"images/{name}"

        f = open(path, "wb")
        f.write(data)
        f.close()

        return path
    
    def _upload_image(self, file_name: str, data: bytes) -> str:
        """
        Uploads a binary file to a Supabase storage bucket and returns the public URL.

        :param file_name: The name of the file to save in the bucket.
        :param data: The binary data of the file.
        :return: The public URL of the uploaded file.
        """
        # Upload the file to the specified bucket
        response = supabase.storage.from_('generated-images').upload(file_name, data)
        print(response)

        # Generate the public URL for the uploaded file
        public_url = supabase.storage.from_('generated-images').get_public_url(file_name)
        return public_url
    
    def _dowload_image(self, image_url: str) -> bytes:
        response = requests.get(image_url)
        if response.status_code == 200:
            return response.content
        else:
            raise Exception(f"Failed to download image from {image_url}, status code: {response.status_code}")
    
    def call_llm(self, content):
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

    def generate_image(self, outfit: Outfit):

        files = []
        temp_files = []
        for product in outfit.products:

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

        user_parts = [types.Part.from_uri(file_uri=file.uri, mime_type=file.mime_type) for file in files]
        user_parts.append(types.Part.from_text(text="""Generate an image of a female model on a neutral background wearing the garments from the images provided."""))

        contents = [types.Content(role="user", parts=user_parts)]
        response: types.GenerateContentResponse  = self.call_llm(contents)

        generated_image_url = None
        for candidate in response.candidates:
            if candidate.content.parts[0].inline_data:
                file_name = f"{outfit.name}_{uuid.uuid4().hex}.png"
                binary_data = candidate.content.parts[0].inline_data.data
                generated_image_url = self._upload_image(file_name, binary_data)
                print(f"Generated image URL: {generated_image_url}")

                break

        # Delete all files from the images dir
        for file_path in temp_files:
            if os.path.exists(file_path):
                os.remove(file_path)

        return generated_image_url

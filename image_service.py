import os
import requests
from google import genai
from google.genai import types
from models import Product
from supabase import create_client, Client
import uuid
import base64
import mimetypes
from PIL import Image
import io
from transformers import pipeline

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

def save_binary_file(file_name, data):
    f = open(file_name, "wb")
    f.write(data)
    f.close()

def upload_to_db(file_name: str, data: bytes) -> str:
    """
    Uploads a binary file to a Supabase storage bucket and returns the public URL.

    :param file_name: The name of the file to save in the bucket.
    :param data: The binary data of the file.
    :return: The public URL of the uploaded file.
    """
    # Initialize Supabase client
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_KEY")

    supabase: Client = create_client(supabase_url, supabase_key)

    # Upload the file to the specified bucket
    response = supabase.storage.from_('generated-images').upload(file_name, data)
    print(response)

    # Generate the public URL for the uploaded file
    public_url = supabase.storage.from_('generated-images').get_public_url(file_name)
    return public_url

def download_image_from_url(image_url: str) -> bytes:
    """
    Downloads an image from a URL and returns the binary data.

    :param image_url: The URL of the image to download.
    :return: The binary data of the downloaded image.
    """
    response = requests.get(image_url)
    if response.status_code == 200:
        return response.content
    else:
        raise Exception(f"Failed to download image from {image_url}")

def call_gemini_api(content) -> str:
    model = "gemini-2.0-flash-exp-image-generation"
    generate_content_config = types.GenerateContentConfig(
        response_modalities=["image", "text"],
        response_mime_type="text/plain",
    )

    response: types.GenerateContentResponse = client.models.generate_content(
        model=model,
        contents=content,
        config=generate_content_config,
    )

    return response

def generate_outfit_image(product_list: list[Product]) -> str:
    files = []
    local_files = []  # Keep track of local files to delete later

    # Upload each image to the Gemini API
    for product in product_list:
        print(f"Uploading temp image for product: {product.title}")
        if not product.images:
            continue
        image_link = product.images[0]
        
        # Use the product title as the file name to help the LLM.
        file_name = f"{''.join(e if e.isalnum() or e.isspace() else '' for e in product.title).replace(' ', '_')}.jpg"
        
        response = requests.get(image_link)
        if response.status_code == 200:

            save_binary_file(file_name, response.content)
            local_files.append(file_name)

            uploaded_file = client.files.upload(file=file_name)
            files.append(uploaded_file)
        else:
            print(f"Failed to download image from {image_link}")

    # Dynamically populate the parts key with the files list
    user_parts = [types.Part.from_uri(file_uri=file.uri, mime_type=file.mime_type) for file in files]
    user_parts.append(types.Part.from_text(text="""Generate an image of a female model on a neutral background wearing an outfit based on the images provided. Each image represents an item of the outfit, use the name of the image file to your advantage.:"""))

    contents = [types.Content(role="user", parts=user_parts)]

    response: types.GenerateContentResponse = call_gemini_api(contents)

    generated_image_url = None
    for candidate in response.candidates:
        if candidate.content.parts[0].inline_data:

            file_name = f"public/{uuid.uuid4().hex}.jpg"
            binary_data = candidate.content.parts[0].inline_data.data
            generated_image_url = upload_to_db(file_name, binary_data)
            print(f"Generated image URL: {generated_image_url}")

            break

    # Clean up local files
    for local_file in local_files:
        try:
            os.remove(local_file)
        except OSError as e:
            print(f"Error deleting file {local_file}: {e}")

    return generated_image_url

from PIL import Image

def object_detection(image_path: str) -> list[str]:
    """
    Perform object detection on the input image, crop the detected objects, and save them.

    :param image_data: The binary data of the input image.
    :return: A list of file paths for the cropped images.
    """
    from PIL import ImageOps

    # Use a pipeline as a high-level helper
    pipe = pipeline("object-detection", model="yainage90/fashion-object-detection")
    output = pipe(image_path, threshold=0.75)

    # Load the original image
    original_image = Image.open(image_path).convert("RGBA")
    cropped_image_paths = []

    # Directory to save cropped images
    output_dir = "public"
    os.makedirs(output_dir, exist_ok=True)

    print(output)

    # Iterate over detected objects and crop the image
    for idx, obj in enumerate(output):
        box = obj['box']
        label = obj['label']
        xmin, ymin, xmax, ymax = int(box['xmin']), int(box['ymin']), int(box['xmax']), int(box['ymax'])

        # Crop the image
        cropped_image = original_image.crop((xmin, ymin, xmax, ymax))

        # Save the cropped image
        cropped_image_path = os.path.join(output_dir, f"{label}_{uuid.uuid4()}.png")
        cropped_image.save(cropped_image_path)
        cropped_image_paths.append(cropped_image_path)

    return cropped_image_paths
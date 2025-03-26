import base64
import os
import requests
from google import genai
from google.genai import types
from models import Product
from supabase import create_client, Client
import uuid

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

def generate(product_list: list[Product]) -> str:
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

    files = []
    local_files = []  # Keep track of local files to delete later

    for product in product_list:
        print(f"Generating image for product: {product}")
        if not product.images:
            continue
        image_link = product.images[0]
        
        # Use the product title as the file name to help the LLM.
        # file_name = f"{product.title.replace(' ', '_').lower()}.jpg"
        file_name = f"{product.type}_{uuid.uuid4().hex}.jpg"
        
        response = requests.get(image_link)
        if response.status_code == 200:

            save_binary_file(file_name, response.content)
            local_files.append(file_name)

            uploaded_file = client.files.upload(file=file_name)
            files.append(uploaded_file)
        else:
            print(f"Failed to download image from {image_link}")

    model = "gemini-2.0-flash-exp-image-generation"
    generate_content_config = types.GenerateContentConfig(
        temperature=1,
        top_p=0.95,
        top_k=40,
        max_output_tokens=8192,
        response_modalities=["image", "text"],
        response_mime_type="text/plain",
    )

    # Dynamically populate the parts key with the files list
    user_parts = [types.Part.from_uri(file_uri=file.uri, mime_type=file.mime_type) for file in files]
    user_parts.append(types.Part.from_text(text="""Generate an image of a caucasian female model on a neutral background wearing an outfit made of of ONLY the images provided:"""))

    contents = [types.Content(role="user", parts=user_parts)]

    response: types.GenerateContentResponse = client.models.generate_content(
        model=model,
        contents=contents,
        config=generate_content_config,
    )

    generated_image_url = None
    for candidate in response.candidates:
        if candidate.content.parts[0].inline_data:

            file_name = f"public/{uuid.uuid4().hex}.jpg"
            binary_data = candidate.content.parts[0].inline_data.data
            generated_image_url = upload_to_db(file_name, binary_data)

            break

    # # Clean up local files
    # for local_file in local_files:
    #     try:
    #         os.remove(local_file)
    #     except OSError as e:
    #         print(f"Error deleting file {local_file}: {e}")

    return generated_image_url

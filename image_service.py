import os
import requests
from google import genai
from google.genai import types
from models import Product
from supabase import create_client, Client
import uuid
import base64
import mimetypes

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

def extract_items_from_image(image_url: str) -> dict:
    files = []

    file_name = f"{uuid.uuid4().hex}.jpg"

    image_bytes = download_image_from_url(image_url)

    save_binary_file(file_name, image_bytes)
    uploaded_file = client.files.upload(file=file_name)

    files.append(uploaded_file)

    model = "gemini-2.0-flash-exp-image-generation"
    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part.from_text(text="""Given an image of a person wearing various clothing items, extract each item from the image, and generate one image per clothing item individually. The output image should clearly highlight the individual item, removing any background distractions while maintaining the quality and accuracy of the clothes' appearance including colors, style. 

- Ensure that the extracted image showcases the clothing item clearly and accurately.

# Examples
1. **Input Image**: [image of a person wearing a white top with jeans pants and high heels]
   **Output**: 
	Image 1: [Image focusing solely on the white top]
	Image 2: [Image focusing solely on the jeans pants]
	Image 3: [Image focusing solely on the high heels]

# Notes
- The background should be neutral or removed entirely to focus on the clothing."""),
            ],
        ),
        types.Content(
            role="model",
            parts=[
                types.Part.from_text(text="""Okay, I understand the task. You want me to take an image of a person wearing multiple clothing items, identify each distinct item, and then generate separate images where each image prominently features only one of those clothing items against a neutral or removed background.

Here's how I will approach this task conceptually:

1.  **Object Detection and Segmentation:** The first step is to identify and segment each clothing item present in the input image. This involves using computer vision techniques to detect the boundaries and masks of different objects that are classified as clothing.

2.  **Masking and Extraction:** Once the segmentation masks for each clothing item are available, I will use these masks to isolate the pixels corresponding to that specific item.

3.  **Background Manipulation:** The areas outside the mask will be either filled with a neutral color (like white or light gray) or made transparent, effectively removing the background and any other clothing items or the person.

4.  **Image Generation:** For each extracted and masked clothing item, a new image will be generated. This image will focus solely on the isolated item, preserving its original colors, textures, and overall style as accurately as possible.

5.  **Output Presentation:** The final output will consist of a series of individual images, each clearly displaying one of the extracted clothing items.

**To proceed with this task, please provide me with the image you want me to process.** Once you upload the image, I will do my best to extract each clothing item and generate the individual images as described."""),
            ],
        ),
        types.Content(
            role="user",
            parts=[
                types.Part.from_uri(
                    file_uri=files[0].uri,
                    mime_type=files[0].mime_type,
                ),
            ],
        )
    ]
    generate_content_config = types.GenerateContentConfig(
        response_modalities=[
            "image",
            "text",
        ],
        response_mime_type="text/plain",
    )

    image_urls = []
    for chunk in client.models.generate_content_stream(
        model=model,
        contents=contents,
        config=generate_content_config,
    ):
        if not chunk.candidates or not chunk.candidates[0].content or not chunk.candidates[0].content.parts:
            continue
        if chunk.candidates[0].content.parts[0].inline_data:
            file_name = f"public/{uuid.uuid4().hex}"
            inline_data = chunk.candidates[0].content.parts[0].inline_data
            file_extension = mimetypes.guess_extension(inline_data.mime_type)
            save_binary_file(
                f"{file_name}{file_extension}", inline_data.data
            )
            print(
                "File of mime type"
                f" {inline_data.mime_type} saved"
                f"to: {file_name}"
            )
            # Upload the generated image to Supabase storage
            public_url = upload_to_db(f"{file_name}{file_extension}", inline_data.data)
            print(f"Generated image URL: {public_url}")
            image_urls.append(public_url)

        else:
            print(chunk.text)

    return image_urls
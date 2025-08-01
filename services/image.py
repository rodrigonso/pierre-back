import uuid
import os
import asyncio
from google import genai
from google.genai import types
import aiohttp
import aiofiles
from services.stylist import Outfit
from services.db import get_database_service
from services.logger import get_logger_service

logger_service = get_logger_service()

class ImageService:
    def __init__(self):
        self.client = genai.Client()
        self.database_service = None

    async def _ensure_database_service(self):
        """
        Ensure the database service is initialized.
        This method should be called before any database operations.
        """
        if self.database_service is None:
            self.database_service = await get_database_service()

    async def _save_image(self, data: bytes, name: str) -> str:
        """
        Save image data to file asynchronously.

        Args:
            data: Binary image data
            name: Filename to save as

        Returns:
            str: Path to saved file
        """
        path = f"images/{name}"

        async with aiofiles.open(path, "wb") as f:
            await f.write(data)

        return path

    async def _dowload_image(self, image_url: str) -> bytes:
        """
        Download image from URL asynchronously using aiohttp.

        Args:
            image_url: URL of the image to download

        Returns:
            bytes: Downloaded image data
            
        Raises:
            Exception: If download fails
        """
        async with aiohttp.ClientSession() as session:
            async with session.get(image_url) as response:
                if response.status == 200:
                    return await response.read()
                else:
                    raise Exception(f"Failed to download image from {image_url}, status code: {response.status}")

    async def _call_llm(self, content):
        """
        Call the LLM API asynchronously using asyncio.

        Args:
            content: Content to send to the LLM

        Returns:
            GenerateContentResponse: Response from the LLM
        """
        model = "gemini-2.0-flash-exp-image-generation"
        generate_content_config = types.GenerateContentConfig(
            response_modalities=["image", "text"],
            response_mime_type="text/plain",
        )

        # Run the potentially blocking LLM call in a thread pool
        response: types.GenerateContentResponse = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self.client.models.generate_content(
                model=model,
                contents=content,
                config=generate_content_config,
            )
        )

        return response

    async def _process_products(self, products):
        """
        Process products asynchronously by downloading images and uploading to LLM service.

        Args:
            products: List of products to process

        Returns:
            tuple: (files, temp_files) - uploaded files and local temp file paths
        """
        files = []
        temp_files = []

        # Process products concurrently for better performance
        tasks = []
        for product in products:
            if not product.images:
                logger_service.error(f"Product {product} does not have images.")
                raise ValueError(f"Product {product} does not have an image URL.")

            # Skip unsupported product types
            if product.type not in ["top", "bottom", "dress", "outerwear", "shoes"]:
                logger_service.warning(f"Skipping unsupported product type: {product.type}")
                continue

            tasks.append(self._process_single_product(product))

        # Execute all product processing tasks concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                logger_service.error(f"Error processing product: {str(result)}")
                continue

            if result:  # result is (uploaded_image, file_path)
                uploaded_image, file_path = result
                files.append(uploaded_image)
                temp_files.append(file_path)

        return files, temp_files

    async def _process_single_product(self, product):
        """
        Process a single product asynchronously.
        
        Args:
            product: Product to process
            
        Returns:
            tuple: (uploaded_image, file_path) or None if failed
        """
        try:
            image_data = await self._dowload_image(product.images[0])
            file_path = await self._save_image(image_data, f"garment_{product.type}.jpg")
            
            # File upload to LLM service - run in executor since it might be blocking
            uploaded_image = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.client.files.upload(file=file_path)
            )
            
            return uploaded_image, file_path
        except Exception as e:
            logger_service.error(f"Error processing product {product}: {str(e)}")
            return None

        return files, temp_files

    async def generate_image(self, outfit: Outfit):
        """
        Generate an image for the given outfit asynchronously.

        Args:
            outfit: Outfit object containing products and name

        Returns:
            str: URL of the generated image or None if generation failed
        """
        # Ensure database service is initialized
        await self._ensure_database_service()

        images, temp_images = await self._process_products(outfit.products)

        user_parts = [types.Part.from_uri(file_uri=image.uri, mime_type=image.mime_type) for image in images]
        user_parts.append(types.Part.from_text(text="""Generate an image of a female model on a neutral background wearing the garments from the images provided. Do NOT return any text -- you should only return the image."""))

        try:
            contents = [types.Content(role="user", parts=user_parts)]
            response: types.GenerateContentResponse = await self._call_llm(contents)

            generated_image_url = None
            for candidate in response.candidates:
                if candidate.content.parts[0].inline_data:

                    file_name = f"{outfit.name}_{uuid.uuid4().hex}.png"
                    binary_data = candidate.content.parts[0].inline_data.data
                    generated_image_url = await self.database_service.upload_image("generated-images", file_name, binary_data)

                    break
                else:
                    logger_service.error("No inline data found in the response candidate.")

                    # Write the response to a text file for debugging (async)
                    error_file_name = f"error_response_{uuid.uuid4().hex}.txt"
                    error_file_path = f"images/{error_file_name}"

                    try:
                        async with aiofiles.open(error_file_path, "w", encoding="utf-8") as error_file:
                            await error_file.write(f"Error: No inline data found in response candidate\n")
                            await error_file.write(f"Outfit name: {outfit.name}\n")
                            await error_file.write(f"Timestamp: {uuid.uuid4().hex}\n")
                            await error_file.write(f"Full response: {response}\n")
                            await error_file.write(f"Candidate content: {candidate.content}\n")
                        
                        logger_service.info(f"Error response written to: {error_file_path}")
                    except Exception as write_error:
                        logger_service.error(f"Failed to write error response to file: {str(write_error)}")

        except Exception as e:
            logger_service.error(f"Error generating image: {str(e)}")

        finally:
            # Delete all files from the images dir asynchronously
            cleanup_tasks = []
            for file_path in temp_images:
                if os.path.exists(file_path):
                    cleanup_tasks.append(asyncio.get_event_loop().run_in_executor(
                        None, 
                        lambda fp=file_path: os.remove(fp)
                    ))
            
            if cleanup_tasks:
                await asyncio.gather(*cleanup_tasks, return_exceptions=True)

        return generated_image_url

image_service = ImageService()
def get_image_service() -> ImageService:
    """
    Dependency to provide the ImageService instance.
    This can be used in route handlers that require image generation functionality.
    
    Returns:
        ImageService: Instance of the ImageService
    """
    return image_service

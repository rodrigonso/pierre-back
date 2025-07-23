from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer
from typing import List
from services.db import DatabaseOutfit, get_database_service, DatabaseProduct, DatabaseService
from utils.auth import get_current_user
from utils.models import (
    User, 
    CollectionCreate, 
    CollectionUpdate, 
    Collection, 
    CollectionWithItems, 
    AddItemToCollection,
    CollectionItem,
    CollectionItemWithData,
)
from services.logger import get_logger_service
from datetime import datetime
import uuid
import base64

router = APIRouter()
logger_service = get_logger_service()
security = HTTPBearer()

@router.post("/collections", response_model=Collection)
async def create_collection(
    collection_data: CollectionCreate,
    current_user: User = Depends(get_current_user)
):
    """
    Create a new collection for the authenticated user.
    
    This endpoint allows users to create a new collection with a name and optional description.
    Collections are used to organize liked products and outfits.
    
    Args:
        collection_data: CollectionCreate containing name and optional description
        current_user: Authenticated user from JWT token
        
    Returns:
        Collection: The created collection with metadata
        
    Raises:
        HTTPException: For any database or validation errors
    """
    try:
        logger_service.info(f"Creating collection '{collection_data.name}' for user {current_user.id}")
        
        db_service = await get_database_service()
        supabase = db_service.supabase
        
        # Insert the new collection
        collection_id = str(uuid.uuid4())
        insert_data = {
            "id": collection_id,
            "user_id": current_user.id,
            "name": collection_data.name,
            "description": collection_data.description
        }
        
        response = await supabase.table("collections").insert(insert_data).execute()
        
        if not response.data:
            raise HTTPException(status_code=500, detail="Failed to create collection")
        
        created_collection = response.data[0]
        logger_service.success(f"Created collection {collection_id} for user {current_user.id}")
        
        return Collection(
            id=created_collection["id"],
            user_id=created_collection["user_id"],
            name=created_collection["name"],
            description=created_collection["description"],
            created_at=datetime.fromisoformat(created_collection["created_at"].replace('Z', '+00:00')),
            updated_at=datetime.fromisoformat(created_collection["updated_at"].replace('Z', '+00:00')),
            item_count=0
        )
        
    except Exception as e:
        logger_service.error(f"Error creating collection for user {current_user.id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create collection: {str(e)}")

@router.get("/collections", response_model=List[Collection])
async def get_user_collections(
    current_user: User = Depends(get_current_user)
):
    """
    Get all collections for the authenticated user.
    
    This endpoint returns a list of all collections owned by the authenticated user,
    including item counts for each collection.
    
    Args:
        current_user: Authenticated user from JWT token
        
    Returns:
        List[Collection]: List of user's collections with metadata
        
    Raises:
        HTTPException: For any database errors
    """
    try:
        logger_service.info(f"Fetching collections for user {current_user.id}")
        
        db_service = await get_database_service()
        supabase = db_service.supabase
        
        collections_response = await supabase.table("collections").select("*").eq("user_id", current_user.id).order("created_at", desc=True).execute()
        
        collections = []
        for collection_data in collections_response.data or []:
            # Get item count for each collection
            count_response = await supabase.table("collection_items").select("id", count="exact").eq("collection_id", collection_data["id"]).execute()
            item_count = count_response.count or 0
            
            collections.append(Collection(
                id=collection_data["id"],
                user_id=collection_data["user_id"],
                name=collection_data["name"],
                description=collection_data["description"],
                image_url=collection_data["image_url"],
                created_at=datetime.fromisoformat(collection_data["created_at"].replace('Z', '+00:00')),
                updated_at=datetime.fromisoformat(collection_data["updated_at"].replace('Z', '+00:00')),
                item_count=item_count
            ))
        
        logger_service.success(f"Retrieved {len(collections)} collections for user {current_user.id}")
        return collections
        
    except Exception as e:
        logger_service.error(f"Error fetching collections for user {current_user.id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch collections: {str(e)}")

@router.get("/collections/{collection_id}", response_model=CollectionWithItems)
async def get_collection_with_items(
    collection_id: str,
    current_user: User = Depends(get_current_user)
):
    """
    Get a specific collection with all its items.
    
    This endpoint returns a collection with all its products and outfits.
    Only the collection owner can access their collections.
    
    Args:
        collection_id: UUID of the collection to retrieve
        current_user: Authenticated user from JWT token
        
    Returns:
        CollectionWithItems: Collection with all its items
        
    Raises:
        HTTPException: 404 if collection not found, 500 for database errors
    """
    try:
        logger_service.info(f"Fetching collection {collection_id} for user {current_user.id}")
        
        db_service = await get_database_service()
        supabase = db_service.supabase
        
        # Get the collection (RLS will ensure user can only access their own)
        collection_response = await supabase.table("collections").select("*").eq("id", collection_id).eq("user_id", current_user.id).execute()
        
        if not collection_response.data:
            logger_service.warning(f"Collection {collection_id} not found for user {current_user.id}")
            raise HTTPException(status_code=404, detail="Collection not found")
        
        collection_data = collection_response.data[0]
        
        # Get all items in the collection
        items_response = await supabase.table("collection_items").select("*").eq("collection_id", collection_id).order("added_at", desc=True).execute()
        
        items = []
        for item_data in items_response.data or []:
            # Create the base collection item
            collection_item = CollectionItemWithData(
                id=item_data["id"],
                item_type=item_data["item_type"],
                item_id=item_data["item_id"],
                added_at=datetime.fromisoformat(item_data["added_at"].replace('Z', '+00:00')),
                data=None
            )
            
            # Fetch the actual product or outfit data
            try:
                if item_data["item_type"] == "product":

                    product = await db_service.get_product(item_data["item_id"])
                    collection_item.data = product

                elif item_data["item_type"] == "outfit":

                    outfit: DatabaseOutfit = await db_service.get_outfit(item_data["item_id"])
                    collection_item.data = outfit

            except Exception as item_error:
                logger_service.error(f"Error fetching {item_data['item_type']} data for item {item_data['item_id']}: {str(item_error)}")

            items.append(collection_item)
        
        logger_service.success(f"Retrieved collection {collection_id} with {len(items)} items for user {current_user.id}")
        
        return CollectionWithItems(
            id=collection_data["id"],
            user_id=collection_data["user_id"],
            name=collection_data["name"],
            description=collection_data["description"],
            image_url=collection_data["image_url"],
            created_at=datetime.fromisoformat(collection_data["created_at"].replace('Z', '+00:00')),
            updated_at=datetime.fromisoformat(collection_data["updated_at"].replace('Z', '+00:00')),
            items=items
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger_service.error(f"Error fetching collection {collection_id} for user {current_user.id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch collection: {str(e)}")

@router.put("/collections/{collection_id}", response_model=Collection)
async def update_collection(
    collection_id: str,
    collection_data: CollectionUpdate,
    current_user: User = Depends(get_current_user)
):
    """
    Update an existing collection's name or description.
    
    This endpoint allows users to update their collection's name and/or description.
    Only the collection owner can update their collections.
    
    Args:
        collection_id: UUID of the collection to update
        collection_data: CollectionUpdate containing updated fields
        current_user: Authenticated user from JWT token
        
    Returns:
        Collection: The updated collection
        
    Raises:
        HTTPException: 404 if collection not found, 500 for database errors
    """
    try:
        logger_service.info(f"Updating collection {collection_id} for user {current_user.id}")
        
        db_service = await get_database_service()
        supabase = db_service.supabase
        
        # Prepare update data (only include non-None fields)
        update_data = {}
        if collection_data.name is not None:
            update_data["name"] = collection_data.name
        if collection_data.description is not None:
            update_data["description"] = collection_data.description
        if collection_data.image_b64:
            update_data["image_url"] = await db_service.upload_image("collection-images", f"{collection_id}.png", base64.b64decode(collection_data.image_b64))
        
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields to update")
        
        # Update the collection (RLS will ensure user can only update their own)
        response = await supabase.table("collections").update(update_data).eq("id", collection_id).eq("user_id", current_user.id).execute()
        
        if not response.data:
            logger_service.warning(f"Collection {collection_id} not found for user {current_user.id}")
            raise HTTPException(status_code=404, detail="Collection not found")
        
        updated_collection = response.data[0]
        
        # Get item count
        count_response = await supabase.table("collection_items").select("id", count="exact").eq("collection_id", collection_id).execute()
        item_count = count_response.count or 0
        
        logger_service.success(f"Updated collection {collection_id} for user {current_user.id}")
    
        return Collection(
            id=updated_collection.get("id", None),
            user_id=updated_collection.get("user_id", None),
            name=updated_collection.get("name", None),
            description=updated_collection.get("description", None),
            image_url=updated_collection.get("image_url", None),
            created_at=datetime.fromisoformat(updated_collection.get("created_at", "").replace('Z', '+00:00')),
            updated_at=datetime.fromisoformat(updated_collection.get("updated_at", "").replace('Z', '+00:00')),
            item_count=item_count
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger_service.error(f"Error updating collection {collection_id} for user {current_user.id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to update collection: {str(e)}")

@router.delete("/collections/{collection_id}")
async def delete_collection(
    collection_id: str,
    current_user: User = Depends(get_current_user)
):
    """
    Delete a collection and all its items.
    
    This endpoint permanently deletes a collection and all items within it.
    Only the collection owner can delete their collections.
    
    Args:
        collection_id: UUID of the collection to delete
        current_user: Authenticated user from JWT token
        
    Returns:
        dict: Success message
        
    Raises:
        HTTPException: 404 if collection not found, 500 for database errors
    """
    try:
        logger_service.info(f"Deleting collection {collection_id} for user {current_user.id}")
        
        db_service = await get_database_service()
        supabase = db_service.supabase
        
        # Delete the collection (CASCADE will delete collection_items automatically)
        response = await supabase.table("collections").delete().eq("id", collection_id).eq("user_id", current_user.id).execute()
        
        if not response.data:
            logger_service.warning(f"Collection {collection_id} not found for user {current_user.id}")
            raise HTTPException(status_code=404, detail="Collection not found")
        
        logger_service.success(f"Deleted collection {collection_id} for user {current_user.id}")
        return {"message": "Collection deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger_service.error(f"Error deleting collection {collection_id} for user {current_user.id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to delete collection: {str(e)}")

@router.post("/collections/{collection_id}/items")
async def add_item_to_collection(
    collection_id: str,
    item_data: AddItemToCollection,
    current_user: User = Depends(get_current_user)
):
    """
    Add a product or outfit to a collection.
    
    This endpoint adds a product or outfit to the specified collection.
    Only the collection owner can add items to their collections.
    
    Args:
        collection_id: UUID of the collection to add the item to
        item_data: AddItemToCollection containing item type and ID
        current_user: Authenticated user from JWT token
        
    Returns:
        dict: Success message with item details
        
    Raises:
        HTTPException: 404 if collection not found, 409 if item already exists, 500 for database errors
    """
    try:
        logger_service.info(f"Adding {item_data.item_type} {item_data.item_id} to collection {collection_id} for user {current_user.id}")
        
        db_service = await get_database_service()
        supabase = db_service.supabase
        
        # Verify collection exists and belongs to user
        collection_response = await supabase.table("collections").select("id").eq("id", collection_id).eq("user_id", current_user.id).execute()
        
        if not collection_response.data:
            logger_service.warning(f"Collection {collection_id} not found for user {current_user.id}")
            raise HTTPException(status_code=404, detail="Collection not found")
        
        # Add the item to the collection
        item_insert_data = {
            "collection_id": collection_id,
            "item_type": item_data.item_type,
            "item_id": item_data.item_id
        }
        
        response = await supabase.table("collection_items").insert(item_insert_data).execute()
        
        if not response.data:
            # Check if it's a duplicate item error
            existing_response = await supabase.table("collection_items").select("id").eq("collection_id", collection_id).eq("item_type", item_data.item_type).eq("item_id", item_data.item_id).execute()
            
            if existing_response.data:
                logger_service.warning(f"Item {item_data.item_type}:{item_data.item_id} already exists in collection {collection_id}")
                raise HTTPException(status_code=409, detail="Item already exists in collection")
            else:
                raise HTTPException(status_code=500, detail="Failed to add item to collection")
        
        logger_service.success(f"Added {item_data.item_type} {item_data.item_id} to collection {collection_id} for user {current_user.id}")
        
        return {
            "message": "Item added to collection successfully",
            "item_type": item_data.item_type,
            "item_id": item_data.item_id,
            "collection_id": collection_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger_service.error(f"Error adding item to collection {collection_id} for user {current_user.id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to add item to collection: {str(e)}")

@router.delete("/collections/{collection_id}/items/{item_type}/{item_id}")
async def remove_item_from_collection(
    collection_id: str,
    item_type: str,
    item_id: str,
    current_user: User = Depends(get_current_user)
):
    """
    Remove a product or outfit from a collection.
    
    This endpoint removes a specific item from the specified collection.
    Only the collection owner can remove items from their collections.
    
    Args:
        collection_id: UUID of the collection to remove the item from
        item_type: Type of item ('product' or 'outfit')
        item_id: ID of the item to remove
        current_user: Authenticated user from JWT token
        
    Returns:
        dict: Success message
        
    Raises:
        HTTPException: 404 if collection or item not found, 500 for database errors
    """
    try:
        logger_service.info(f"Removing {item_type} {item_id} from collection {collection_id} for user {current_user.id}")
        
        # Validate item_type
        if item_type not in ["product", "outfit"]:
            raise HTTPException(status_code=400, detail="Item type must be 'product' or 'outfit'")
        
        db_service = await get_database_service()
        supabase = db_service.supabase
        
        # Remove the item from the collection (RLS will ensure user can only modify their own collections)
        response = await supabase.table("collection_items").delete().eq("collection_id", collection_id).eq("item_type", item_type).eq("item_id", item_id).execute()
        
        if not response.data:
            logger_service.warning(f"Item {item_type}:{item_id} not found in collection {collection_id} for user {current_user.id}")
            raise HTTPException(status_code=404, detail="Item not found in collection")
        
        logger_service.success(f"Removed {item_type} {item_id} from collection {collection_id} for user {current_user.id}")
        
        return {
            "message": "Item removed from collection successfully",
            "item_type": item_type,
            "item_id": item_id,
            "collection_id": collection_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger_service.error(f"Error removing item from collection {collection_id} for user {current_user.id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to remove item from collection: {str(e)}")

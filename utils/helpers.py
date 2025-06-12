import requests
from dotenv import load_dotenv
from serpapi import GoogleSearch
from utils.models import Product
import uuid
from pydantic import BaseModel
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Any, List, Dict, Optional

load_dotenv()

class SearchWebResult(BaseModel):
    query: str
    results: list[str]
    success: bool
    error_message: str = None

class SearchProductsResult(BaseModel):
    query: str
    products: list[Product]
    item_type: str
    success: bool
    error_message: str = None

class ParallelTaskResult(BaseModel):
    """Result of parallel task execution"""
    task_id: str
    success: bool
    result: Any = None
    error_message: str = None
    execution_time: float = 0.0

class ParallelExecutionResult(BaseModel):
    """Result of running multiple tasks in parallel"""
    total_tasks: int
    successful_tasks: int
    failed_tasks: int
    results: List[ParallelTaskResult]
    total_execution_time: float

def search_web(self, query: str) -> SearchWebResult:
    """Tool to search the web for fashion trends, brand information, etc."""

    try:
        params = {
            "engine": "google",
            "q": query,
            "api_key": os.getenv("SERPAPI_API_KEY"),
            "num": 5,
            "hl": "en",
            "gl": "us"
        }

        search = GoogleSearch(params)
        results = search.get_dict()
        organic_results = results.get("organic_results", [])

        insights = []
        for result in organic_results[:3]:
            insights.append(f"Title: {result.get('title', '')}\nSnippet: {result.get('snippet', '')}")

        return SearchWebResult(
            query=query,
            results=results,
            success=True
        )

    except Exception as e:
        print(f"Error in web search: {e}")
        return SearchWebResult(
            query=query,
            results=[],
            success=False,
            error_message=str(e)
        )

def search_products(self, query: str, item_type: str, max_results: int = 3) -> SearchProductsResult:
    """Tool to search for products using SerpAPI"""
    try:
        params = {
            "engine": "google_shopping",
            "q": query,
            "api_key": os.getenv("SERPAPI_API_KEY"),
            "num": max_results,
            "hl": "en",
            "gl": "us",
            "location": "United States",
            "direct_link": True
        }

        search = GoogleSearch(params)
        results = search.get_dict()
        shopping_results = results.get("shopping_results", [])

        if not shopping_results:
            return SearchResult(
                query=query,
                products=[],
                item_type=item_type,
                success=False,
                error_message="No products found"
            )

        products = []
        for item in shopping_results[:max_results]:
            try:
                # Get detailed product information
                rich_url = item.get("serpapi_product_api")
                if rich_url:
                    rich_response = requests.get(rich_url + f'&api_key={os.getenv("SERPAPI_API_KEY")}')
                    rich_response_parsed = rich_response.json()
                    rich_product_info = self.extract_product_data(rich_response_parsed)
                    
                    product = Product(
                        id=rich_product_info.product.product_id or str(uuid.uuid4()),
                        query=query,
                        title=rich_product_info.product.title or item.get("title", ""),
                        price=item.get("extracted_price", 0),
                        link=rich_product_info.seller.direct_link or item.get("link", ""),
                        images=rich_product_info.product.images or [item.get("thumbnail", "")],
                        source=rich_product_info.seller.seller_name or item.get("source", ""),
                        description=rich_product_info.product.description or "",
                        type=item_type
                    )
                else:
                    # Fallback to basic item data
                    product = Product(
                        id=str(uuid.uuid4()),
                        query=query,
                        title=item.get("title", ""),
                        price=item.get("extracted_price", 0),
                        link=item.get("link", ""),
                        images=[item.get("thumbnail", "")],
                        source=item.get("source", ""),
                        description="",
                        type=item_type
                    )
                products.append(product)
            except Exception as e:
                print(f"Error processing product: {e}")
                continue

        return SearchProductsResult(
            query=query,
            products=products,
            item_type=item_type,
            success=True
        )

    except Exception as e:
        return SearchProductsResult(
            query=query,
            products=[],
            item_type=item_type,
            success=False,
            error_message=str(e)
        )

def run_tasks_in_parallel(
    tasks: List[Dict[str, Any]], 
    max_workers: Optional[int] = None,
    timeout: Optional[float] = None
) -> ParallelExecutionResult:
    """
    Execute a list of tasks in parallel using ThreadPoolExecutor.
    
    Args:
        tasks: List of task dictionaries. Each task should have:
               - 'func': The function to execute
               - 'args': Tuple of positional arguments (optional)
               - 'kwargs': Dict of keyword arguments (optional)
               - 'task_id': String identifier for the task (optional, auto-generated if not provided)
        max_workers: Maximum number of worker threads (default: None, uses ThreadPoolExecutor default)
        timeout: Maximum time to wait for all tasks to complete in seconds (optional)
    
    Returns:
        ParallelExecutionResult: Contains results from all tasks and execution statistics
        
    Example:
        tasks = [
            {
                'func': search_web,
                'args': ('fashion trends 2025',),
                'task_id': 'web_search_1'
            },
            {
                'func': search_products,
                'kwargs': {'query': 'summer dress', 'item_type': 'clothing'},
                'task_id': 'product_search_1'
            }
        ]
        result = run_tasks_in_parallel(tasks, max_workers=3, timeout=30)
    """
    import time
    
    start_time = time.time()
    results = []
    
    # Validate and prepare tasks
    prepared_tasks = []
    for i, task in enumerate(tasks):
        if 'func' not in task:
            raise ValueError(f"Task {i} missing required 'func' key")
        
        task_id = task.get('task_id', f'task_{i}_{uuid.uuid4().hex[:8]}')
        args = task.get('args', ())
        kwargs = task.get('kwargs', {})
        
        prepared_tasks.append({
            'task_id': task_id,
            'func': task['func'],
            'args': args,
            'kwargs': kwargs
        })
    
    def execute_task(task_info):
        """Execute a single task and return the result with timing"""
        task_start = time.time()
        task_id = task_info['task_id']
        
        try:
            result = task_info['func'](*task_info['args'], **task_info['kwargs'])
            execution_time = time.time() - task_start
            
            return ParallelTaskResult(
                task_id=task_id,
                success=True,
                result=result,
                execution_time=execution_time
            )
        except Exception as e:
            execution_time = time.time() - task_start
            
            return ParallelTaskResult(
                task_id=task_id,
                success=False,
                error_message=str(e),
                execution_time=execution_time
            )
    
    # Execute tasks in parallel
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        try:
            # Submit all tasks
            future_to_task = {
                executor.submit(execute_task, task): task['task_id'] 
                for task in prepared_tasks
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_task, timeout=timeout):
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    task_id = future_to_task[future]
                    results.append(ParallelTaskResult(
                        task_id=task_id,
                        success=False,
                        error_message=f"Future execution error: {str(e)}"
                    ))
                    
        except Exception as e:
            # Handle timeout or other executor errors
            print(f"Error in parallel execution: {e}")
            # Add failed results for any remaining tasks
            completed_task_ids = {result.task_id for result in results}
            for task in prepared_tasks:
                if task['task_id'] not in completed_task_ids:
                    results.append(ParallelTaskResult(
                        task_id=task['task_id'],
                        success=False,
                        error_message=f"Task did not complete: {str(e)}"
                    ))
    
    total_execution_time = time.time() - start_time
    successful_tasks = sum(1 for r in results if r.success)
    failed_tasks = len(results) - successful_tasks
    
    return ParallelExecutionResult(
        total_tasks=len(prepared_tasks),
        successful_tasks=successful_tasks,
        failed_tasks=failed_tasks,
        results=results,
        total_execution_time=total_execution_time
    )


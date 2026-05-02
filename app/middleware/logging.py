import logging
import time
import traceback
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import sys

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('app.log')
    ]
)

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    
    
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()

        import uuid
        request_id = str(uuid.uuid4())[:8]

        logger.info(f"[{request_id}] {request.method} {request.url.path}")
        
        try:
            response = await call_next(request)

            process_time = time.time() - start_time

            logger.info(
                f"[{request_id}] {request.method} {request.url.path} "
                f"- Status: {response.status_code} - Time: {process_time:.3f}s"
            )

            response.headers["X-Process-Time"] = str(process_time)
            response.headers["X-Request-ID"] = request_id
            
            return response
            
        except Exception as e:
            process_time = time.time() - start_time

            logger.error(
                f"[{request_id}] {request.method} {request.url.path} "
                f"- Error: {str(e)} - Time: {process_time:.3f}s"
            )
            logger.error(traceback.format_exc())
            
            return JSONResponse(
                status_code=500,
                content={
                    "error": "Internal server error",
                    "request_id": request_id,
                    "message": "An unexpected error occurred. Please try again later."
                }
            )


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    
    
    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
            return response
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Unhandled exception: {str(e)}")
            logger.error(traceback.format_exc())
            
            return JSONResponse(
                status_code=500,
                content={
                    "error": "Internal server error",
                    "message": "An unexpected error occurred"
                }
            )


from fastapi import HTTPException

class TimeoutMiddleware(BaseHTTPMiddleware):
    
    
    def __init__(self, app, timeout: float = 30.0):
        super().__init__(app)
        self.timeout = timeout
    
    async def dispatch(self, request: Request, call_next):
        import asyncio
        
        try:
            response = await asyncio.wait_for(
                call_next(request),
                timeout=self.timeout
            )
            return response
        except asyncio.TimeoutError:
            logger.warning(f"Request timeout: {request.url.path}")
            return JSONResponse(
                status_code=504,
                content={
                    "error": "Gateway timeout",
                    "message": "The request took too long to process"
                }
            )

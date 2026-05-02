import time
import hashlib
from collections import defaultdict
from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)


class RateLimiter(BaseHTTPMiddleware):
    
    
    def __init__(self, app, calls: int = 100, period: int = 60):
        super().__init__(app)
        self.calls = calls
        self.period = period
        self.requests: Dict[str, List[float]] = defaultdict(list)
        self.cleanup_interval = 3600  # Clean up every hour
        self.last_cleanup = time.time()
    
    def _get_client_id(self, request: Request) -> str:
        

        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()
        else:
            client_ip = request.client.host if request.client else "unknown"

        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):

            token_prefix = auth_header[7:17]
            return f"{client_ip}:{token_prefix}"
        
        return client_ip
    
    def _clean_old_requests(self):
        
        current_time = time.time()
        if current_time - self.last_cleanup > self.cleanup_interval:
            cutoff = current_time - self.period
            for key in list(self.requests.keys()):
                self.requests[key] = [t for t in self.requests[key] if t > cutoff]
                if not self.requests[key]:
                    del self.requests[key]
            self.last_cleanup = current_time
    
    def _is_rate_limited(self, client_id: str) -> bool:
        
        current_time = time.time()
        cutoff = current_time - self.period

        self.requests[client_id] = [t for t in self.requests[client_id] if t > cutoff]
        
        if len(self.requests[client_id]) >= self.calls:
            return True
        
        self.requests[client_id].append(current_time)
        return False
    
    async def dispatch(self, request: Request, call_next):

        if request.url.path in ["/health", "/", "/docs", "/redoc"]:
            return await call_next(request)

        self._clean_old_requests()

        path = request.url.path

        if "/auth/" in path:
            rate_limit_calls = 10  # 10 requests per minute for auth
            rate_limit_period = 60

        elif "/generations" in path:
            rate_limit_calls = 5  # 5 requests per minute for generation
            rate_limit_period = 60

        elif request.method in ["POST", "PUT", "DELETE"]:
            rate_limit_calls = 30
            rate_limit_period = 60

        else:
            rate_limit_calls = self.calls
            rate_limit_period = self.period

        client_id = self._get_client_id(request)
        key = f"{client_id}:{path}"
        
        if self._check_rate_limit(key, rate_limit_calls, rate_limit_period):
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": "Rate limit exceeded",
                    "message": f"Too many requests. Please try again later.",
                    "retry_after": rate_limit_period
                },
                headers={"Retry-After": str(rate_limit_period)}
            )
        
        response = await call_next(request)

        remaining = rate_limit_calls - len(self.requests.get(key, []))
        response.headers["X-RateLimit-Limit"] = str(rate_limit_calls)
        response.headers["X-RateLimit-Remaining"] = str(max(0, remaining))
        
        return response
    
    def _check_rate_limit(self, key: str, calls: int, period: int) -> bool:
        
        current_time = time.time()
        cutoff = current_time - period
        
        if key not in self.requests:
            self.requests[key] = []
        
        self.requests[key] = [t for t in self.requests[key] if t > cutoff]
        
        if len(self.requests[key]) >= calls:
            return True
        
        self.requests[key].append(current_time)
        return False


class CacheMiddleware(BaseHTTPMiddleware):
    
    
    def __init__(self, app):
        super().__init__(app)
        self.cache: Dict[str, tuple] = {}
        self.cache_ttl = 5  # 5 seconds only - reduced for instant updates
    
    def _get_cache_key(self, request: Request) -> str:
        
        return f"{request.url.path}:{request.url.query}"
    
    async def dispatch(self, request: Request, call_next):

        if request.method != "GET":
            return await call_next(request)

        path = request.url.path
        if "/auth/" in path or "/admin/" in path or path in [
            "/api/v1/products", 
            "/api/v1/categories", 
            "/api/v1/plans", 
            "/api/v1/credit-packs"
        ]:
            return await call_next(request)
        
        cache_key = self._get_cache_key(request)

        if cache_key in self.cache:
            cached_data, timestamp = self.cache[cache_key]
            if time.time() - timestamp < self.cache_ttl:
                return JSONResponse(content=cached_data)
        
        response = await call_next(request)

        if response.status_code == 200:
            try:

                body = b""
                async for chunk in response.body_iterator:
                    body += chunk
                
                import json
                cached_data = json.loads(body)
                self.cache[cache_key] = (cached_data, time.time())

                return JSONResponse(content=cached_data)
            except:
                pass
        
        return response

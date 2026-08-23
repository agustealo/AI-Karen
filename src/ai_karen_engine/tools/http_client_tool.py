"""
HTTP Client Tool for AI-Karen
Production-ready HTTP client for making API calls and web requests.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional, Union
import aiohttp
import json
from datetime import datetime

from ai_karen_engine.services.tooling.tool_service import BaseTool, ToolMetadata, ToolCategory, ToolParameter

logger = logging.getLogger(__name__)


class HTTPClientTool(BaseTool):
    """
    Production-grade HTTP client tool for API interactions.

    Features:
    - Support for all HTTP methods (GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS)
    - Custom headers and authentication
    - Request/response logging
    - Timeout and retry logic
    - JSON, form data, and multipart support
    - Response parsing (JSON, text, binary)
    - Error handling and status code validation
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__()
        self.config = config or {}
        self.timeout = self.config.get('timeout', 30)
        self.max_retries = self.config.get('max_retries', 3)
        self.retry_backoff = self.config.get('retry_backoff', 2)
        self.verify_ssl = self.config.get('verify_ssl', True)
        self.user_agent = self.config.get('user_agent', 'AI-Karen-Agent/1.0')
        self.default_headers = self.config.get('default_headers', {})

    def _create_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="http_client",
            description="Make HTTP requests (GET, POST, PUT, DELETE, etc.) to web APIs and services",
            category=ToolCategory.SYSTEM,
            version="1.0.0",
            author="AI Karen",
            parameters=[
                ToolParameter(
                    name="method",
                    type=str,
                    description="HTTP method (GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS)",
                    required=True
                ),
                ToolParameter(
                    name="url",
                    type=str,
                    description="Target URL",
                    required=True
                ),
                ToolParameter(
                    name="headers",
                    type=dict,
                    description="Request headers",
                    required=False
                ),
                ToolParameter(
                    name="params",
                    type=dict,
                    description="URL query parameters",
                    required=False
                ),
                ToolParameter(
                    name="json_data",
                    type=dict,
                    description="JSON body data",
                    required=False
                ),
                ToolParameter(
                    name="timeout",
                    type=int,
                    description="Request timeout in seconds",
                    required=False,
                    default=30
                )
            ],
            return_type=dict,
            examples=[
                {
                    "description": "Make GET request",
                    "parameters": {
                        "method": "GET",
                        "url": "https://api.example.com/users"
                    }
                },
                {
                    "description": "Make POST request with JSON",
                    "parameters": {
                        "method": "POST",
                        "url": "https://api.example.com/users",
                        "json_data": {"name": "John", "email": "john@example.com"}
                    }
                }
            ],
            tags=["http", "api", "web", "client", "requests"],
            timeout=30
        )

    async def _execute(self, parameters: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Any:
        method = parameters.get("method", "GET")
        url = parameters["url"]
        headers = parameters.get("headers")
        params = parameters.get("params")
        json_data = parameters.get("json_data")
        timeout = parameters.get("timeout", 30)

        return await self.request(
            method=method,
            url=url,
            headers=headers,
            params=params,
            json_data=json_data,
            timeout=timeout
        )

    async def request(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Union[Dict, str, bytes]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        auth: Optional[tuple] = None,
        timeout: Optional[int] = None,
        follow_redirects: bool = True
    ) -> Dict[str, Any]:
        method = method.upper()
        timeout_val = timeout or self.timeout

        request_headers = {
            'User-Agent': self.user_agent,
            **self.default_headers
        }
        if headers:
            request_headers.update(headers)

        if auth:
            import base64
            credentials = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
            auth_header = f"Basic {credentials}"
            request_headers['Authorization'] = auth_header

        kwargs = {
            'headers': request_headers,
            'params': params,
            'timeout': aiohttp.ClientTimeout(total=timeout_val),
            'allow_redirects': follow_redirects,
            'ssl': self.verify_ssl
        }

        if json_data is not None:
            kwargs['json'] = json_data
        elif data is not None:
            kwargs['data'] = data

        last_error = None
        for attempt in range(self.max_retries):
            try:
                start_time = datetime.utcnow()

                async with aiohttp.ClientSession() as session:
                    async with session.request(method, url, **kwargs) as response:
                        elapsed = (datetime.utcnow() - start_time).total_seconds()

                        body_bytes = await response.read()
                        body_text = body_bytes.decode('utf-8', errors='ignore')

                        response_json = None
                        content_type = response.headers.get('Content-Type', '')
                        if 'application/json' in content_type:
                            try:
                                response_json = json.loads(body_text)
                            except json.JSONDecodeError:
                                pass

                        result = {
                            'status_code': response.status,
                            'headers': dict(response.headers),
                            'body': body_bytes,
                            'text': body_text,
                            'json': response_json,
                            'elapsed': elapsed,
                            'url': str(response.url),
                            'method': method,
                            'ok': 200 <= response.status < 300
                        }

                        logger.info(
                            f"HTTP {method} {url} -> {response.status} "
                            f"({elapsed:.2f}s)"
                        )

                        return result

            except asyncio.TimeoutError as e:
                last_error = e
                logger.warning(
                    f"HTTP {method} {url} timeout (attempt {attempt + 1}/{self.max_retries})"
                )
            except Exception as e:
                last_error = e
                logger.error(
                    f"HTTP {method} {url} failed: {e} "
                    f"(attempt {attempt + 1}/{self.max_retries})"
                )

            if attempt < self.max_retries - 1:
                await asyncio.sleep(self.retry_backoff ** attempt)

        raise Exception(f"HTTP request failed after {self.max_retries} attempts: {last_error}")

    async def get(self, url: str, **kwargs) -> Dict[str, Any]:
        return await self.request('GET', url, **kwargs)

    async def post(self, url: str, **kwargs) -> Dict[str, Any]:
        return await self.request('POST', url, **kwargs)

    async def put(self, url: str, **kwargs) -> Dict[str, Any]:
        return await self.request('PUT', url, **kwargs)

    async def patch(self, url: str, **kwargs) -> Dict[str, Any]:
        return await self.request('PATCH', url, **kwargs)

    async def delete(self, url: str, **kwargs) -> Dict[str, Any]:
        return await self.request('DELETE', url, **kwargs)

    async def head(self, url: str, **kwargs) -> Dict[str, Any]:
        return await self.request('HEAD', url, **kwargs)

    async def options(self, url: str, **kwargs) -> Dict[str, Any]:
        return await self.request('OPTIONS', url, **kwargs)

    async def download_file(
        self,
        url: str,
        output_path: str,
        chunk_size: int = 8192,
        **kwargs
    ) -> Dict[str, Any]:
        import aiofiles

        start_time = datetime.utcnow()
        total_bytes = 0

        kwargs.pop('data', None)
        kwargs.pop('json_data', None)

        headers = kwargs.get('headers', {})
        headers.update({
            'User-Agent': self.user_agent,
            **self.default_headers
        })
        kwargs['headers'] = headers

        timeout_val = kwargs.pop('timeout', self.timeout)
        kwargs['timeout'] = aiohttp.ClientTimeout(total=timeout_val)

        async with aiohttp.ClientSession() as session:
            async with session.get(url, **kwargs) as response:
                response.raise_for_status()

                async with aiofiles.open(output_path, 'wb') as f:
                    async for chunk in response.content.iter_chunked(chunk_size):
                        await f.write(chunk)
                        total_bytes += len(chunk)

        elapsed = (datetime.utcnow() - start_time).total_seconds()

        return {
            'status': 'success',
            'output_path': output_path,
            'total_bytes': total_bytes,
            'elapsed': elapsed,
            'url': url
        }


_http_client_instance = None


def get_http_client_tool(config: Optional[Dict[str, Any]] = None) -> HTTPClientTool:
    global _http_client_instance
    if _http_client_instance is None:
        _http_client_instance = HTTPClientTool(config)
    return _http_client_instance

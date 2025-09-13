import os, yaml, pathlib, base64
from urllib.parse import urljoin

import logging
import httpx
from mcp.server.fastmcp import FastMCP

### Constants ###

VERSION = "2025.09.03.141435"

# Load OpenAPI spec
current_dir = pathlib.Path(__file__).parent
with open(current_dir / 'redmine_openapi.yml') as f:
    SPEC = yaml.safe_load(f)

# Constants from environment
REDMINE_URL = os.environ["REDMINE_URL"]
REDMINE_API_KEY = os.environ["REDMINE_API_KEY"]
_rri_b64 = os.environ.get("REDMINE_REQUEST_INSTRUCTIONS", "")
try:
    REDMINE_REQUEST_INSTRUCTIONS = base64.b64decode(_rri_b64).decode()
except Exception:
    REDMINE_REQUEST_INSTRUCTIONS = _rri_b64
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(module)s:%(lineno)d | %(message)s",
)
logger = logging.getLogger(__name__)

# Optional authentication for connecting to this MCP server
MCP_AUTH_METHOD = os.environ.get("MCP_AUTH_METHOD")
MCP_AUTH_TOKEN = os.environ.get("MCP_AUTH_TOKEN")
MCP_AUTH_HEADER = os.environ.get("MCP_AUTH_HEADER", "X-MCP-Auth")


# Core
def request(path: str, method: str = 'get', data: dict = None, params: dict = None,
            content_type: str = 'application/json', content: bytes = None) -> dict:
    headers = {'X-Redmine-API-Key': REDMINE_API_KEY, 'Content-Type': content_type}
    url = urljoin(REDMINE_URL, path.lstrip('/'))

    try:
        response = httpx.request(method=method.lower(), url=url, json=data, params=params, headers=headers,
                                 content=content, timeout=60.0)
        response.raise_for_status()

        body = None
        if response.content:
            try:
                body = response.json()
            except ValueError:
                body = response.content

        return {"status_code": response.status_code, "body": body, "error": ""}
    except Exception as e:
        try:
            status_code = e.response.status_code
        except:
            status_code = 0

        try:
            body = e.response.json()
        except:
            try:
                body = e.response.text
            except:
                body = None

        return {"status_code": status_code, "body": body, "error": f"{e.__class__.__name__}: {e}"}
        
def yd(obj):
    # Allow direct Unicode output, prevent line wrapping for long lines, and avoid automatic key sorting.
    return yaml.safe_dump(obj, allow_unicode=True, sort_keys=False, width=4096)


class AuthenticatedFastMCP(FastMCP):
    def streamable_http_app(self):
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.responses import PlainTextResponse

        app = super().streamable_http_app()

        if MCP_AUTH_METHOD and MCP_AUTH_TOKEN:
            class _AuthMiddleware(BaseHTTPMiddleware):
                async def dispatch(self, request, call_next):
                    method = MCP_AUTH_METHOD.lower()
                    if method == "bearer":
                        auth_header = request.headers.get("authorization")
                        if not auth_header or not auth_header.startswith("Bearer "):
                            return PlainTextResponse("Unauthorized", status_code=401)
                        token = auth_header.split(" ", 1)[1]
                        if token != MCP_AUTH_TOKEN:
                            return PlainTextResponse("Unauthorized", status_code=401)
                    elif method == "header":
                        header_value = request.headers.get(MCP_AUTH_HEADER)
                        if header_value != MCP_AUTH_TOKEN:
                            return PlainTextResponse("Unauthorized", status_code=401)
                    return await call_next(request)

            app.add_middleware(_AuthMiddleware)

        return app


# Tools
mcp = AuthenticatedFastMCP("Redmine MCP server")
logger.info(f"Starting MCP Redmine version {VERSION}")

@mcp.tool(description="""
Make a request to the Redmine API

Args:
    path: API endpoint path (e.g. '/issues.json')
    method: HTTP method to use (default: 'get')
    data: Dictionary for request body (for POST/PUT)
    params: Dictionary for query parameters

Returns:
    str: YAML string containing response status code, body and error message

{}""".format(REDMINE_REQUEST_INSTRUCTIONS).strip())
    
def redmine_request(path: str, method: str = 'get', data: dict = None, params: dict = None) -> str:
    return yd(request(path, method=method, data=data, params=params))

@mcp.tool()
def redmine_paths_list() -> str:
    """Return a list of available API paths from OpenAPI spec
    
    Retrieves all endpoint paths defined in the Redmine OpenAPI specification. Remember that you can use the
    redmine_paths_info tool to get the full specfication for a path.
    
    Returns:
        str: YAML string containing a list of path templates (e.g. '/issues.json')
    """
    return yd(list(SPEC['paths'].keys()))

@mcp.tool()
def redmine_paths_info(path_templates: list) -> str:
    """Get full path information for given path templates
    
    Args:
        path_templates: List of path templates (e.g. ['/issues.json', '/projects.json'])
        
    Returns:
        str: YAML string containing API specifications for the requested paths
    """
    info = {}
    for path in path_templates:
        if path in SPEC['paths']:
            info[path] = SPEC['paths'][path]

    return yd(info)

@mcp.tool()
def redmine_upload(file_path: str, description: str = None) -> str:
    """
    Upload a file to Redmine and get a token for attachment
    
    Args:
        file_path: Fully qualified path to the file to upload
        description: Optional description for the file
        
    Returns:
        str: YAML string containing response status code, body and error message
             The body contains the attachment token
    """
    try:
        path = pathlib.Path(file_path).expanduser()
        assert path.is_absolute(), f"Path must be fully qualified, got: {file_path}"
        assert path.exists(), f"File does not exist: {file_path}"

        params = {'filename': path.name}
        if description:
            params['description'] = description

        with open(path, 'rb') as f:
            file_content = f.read()

        result = request(path='uploads.json', method='post', params=params,
                         content_type='application/octet-stream', content=file_content)
        return yd(result)
    except Exception as e:
        return yd({"status_code": 0, "body": None, "error": f"{e.__class__.__name__}: {e}"})

@mcp.tool()
def redmine_download(attachment_id: int, save_path: str, filename: str = None) -> str:
    """
    Download an attachment from Redmine and save it to a local file
    
    Args:
        attachment_id: The ID of the attachment to download
        save_path: Fully qualified path where the file should be saved to
        filename: Optional filename to use for the attachment. If not provided, 
                 will be determined from attachment data or URL
        
    Returns:
        str: YAML string containing download status, file path, and any error messages
    """
    try:
        path = pathlib.Path(save_path).expanduser()
        assert path.is_absolute(), f"Path must be fully qualified, got: {save_path}"
        assert not path.is_dir(), f"Path can't be a directory, got: {save_path}"

        if not filename:
            attachment_response = request(f"attachments/{attachment_id}.json", "get")
            if attachment_response["status_code"] != 200:
                return yd(attachment_response)

            filename = attachment_response["body"]["attachment"]["filename"]

        response = request(f"attachments/download/{attachment_id}/{filename}", "get",
                           content_type="application/octet-stream")
        if response["status_code"] != 200 or not response["body"]:
            return yd(response)

        with open(path, 'wb') as f:
            f.write(response["body"])

        return yd({"status_code": 200, "body": {"saved_to": str(path), "filename": filename}, "error": ""})
    except Exception as e:
        return yd({"status_code": 0, "body": None, "error": f"{e.__class__.__name__}: {e}"})

def main():
    """Main entry point for the mcp-redmine package."""
    port = int(os.environ.get("PORT", 8369))
    mcp.settings.host = "0.0.0.0"
    mcp.settings.port = port
    mcp.run(transport="streamable-http")

if __name__ == "__main__":
    main()

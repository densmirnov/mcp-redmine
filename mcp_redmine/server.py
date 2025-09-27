import base64
import logging
import os
import pathlib
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin

import httpx
import yaml
from mcp.server.fastmcp import FastMCP

### Constants ###

VERSION = "2025.09.03.141435"

# Load OpenAPI spec
current_dir = pathlib.Path(__file__).parent
with open(current_dir / "redmine_openapi.yml") as f:
    SPEC = yaml.safe_load(f)


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RedmineSettings:
    """Runtime configuration for the Redmine MCP server."""

    url: str
    api_key: str
    port: int = 8369
    log_level: str = "INFO"
    request_instructions: str = ""
    auth_method: Optional[str] = None
    auth_token: Optional[str] = None
    auth_header: str = "X-MCP-Auth"

    @classmethod
    def from_env(cls) -> "RedmineSettings":
        """Load settings from environment variables following MCP guidance."""

        missing = [name for name in ("REDMINE_URL", "REDMINE_API_KEY") if not os.getenv(name)]
        if missing:
            names = ", ".join(missing)
            raise RuntimeError(
                f"Missing required environment variables: {names}. "
                "Set them before starting the Redmine MCP server."
            )

        instructions_raw = os.getenv("REDMINE_REQUEST_INSTRUCTIONS", "")
        instructions = instructions_raw
        if instructions_raw:
            try:
                instructions = base64.b64decode(instructions_raw).decode()
            except Exception:
                # Fall back to the provided value if decoding fails
                instructions = instructions_raw

        port_value = os.getenv("PORT")
        try:
            port = int(port_value) if port_value else 8369
        except ValueError as exc:
            raise RuntimeError(f"PORT must be an integer, got: {port_value!r}") from exc

        return cls(
            url=os.environ["REDMINE_URL"],
            api_key=os.environ["REDMINE_API_KEY"],
            port=port,
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            request_instructions=instructions,
            auth_method=os.getenv("MCP_AUTH_METHOD"),
            auth_token=os.getenv("MCP_AUTH_TOKEN"),
            auth_header=os.getenv("MCP_AUTH_HEADER", "X-MCP-Auth"),
        )


# Core
def request(
    settings: RedmineSettings,
    path: str,
    method: str = "get",
    data: dict | None = None,
    params: dict | None = None,
    content_type: str = "application/json",
    content: bytes | None = None,
) -> dict:
    headers = {"X-Redmine-API-Key": settings.api_key, "Content-Type": content_type}
    url = urljoin(settings.url, path.lstrip("/"))

    try:
        response = httpx.request(
            method=method.lower(),
            url=url,
            json=data,
            params=params,
            headers=headers,
            content=content,
            timeout=60.0,
        )
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
    def __init__(
        self,
        *args,
        auth_method: Optional[str] = None,
        auth_token: Optional[str] = None,
        auth_header: str = "X-MCP-Auth",
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._auth_method = (auth_method or "").lower() or None
        self._auth_token = auth_token
        self._auth_header = auth_header

    def streamable_http_app(self):
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.responses import PlainTextResponse

        app = super().streamable_http_app()

        auth_method = self._auth_method
        auth_token = self._auth_token
        auth_header_name = self._auth_header

        if auth_method and auth_token:
            class _AuthMiddleware(BaseHTTPMiddleware):
                async def dispatch(self, request, call_next):
                    method = auth_method
                    if method == "bearer":
                        authorization_header = request.headers.get("authorization")
                        if not authorization_header or not authorization_header.startswith("Bearer "):
                            return PlainTextResponse("Unauthorized", status_code=401)
                        token = authorization_header.split(" ", 1)[1]
                        if token != auth_token:
                            return PlainTextResponse("Unauthorized", status_code=401)
                    elif method == "header":
                        header_value = request.headers.get(auth_header_name)
                        if header_value != auth_token:
                            return PlainTextResponse("Unauthorized", status_code=401)
                    return await call_next(request)

            app.add_middleware(_AuthMiddleware)

        return app


def create_server(settings: RedmineSettings | None = None) -> AuthenticatedFastMCP:
    """Create and configure the MCP server following OpenAI guidelines."""

    settings = settings or RedmineSettings.from_env()

    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(module)s:%(lineno)d | %(message)s",
    )
    logger.setLevel(getattr(logging, settings.log_level, logging.INFO))
    logger.info(f"Starting MCP Redmine version {VERSION}")

    mcp = AuthenticatedFastMCP(
        "Redmine MCP server",
        log_level=settings.log_level,
        auth_method=settings.auth_method,
        auth_token=settings.auth_token,
        auth_header=settings.auth_header,
    )

    request_description = (
        """
        Make a request to the Redmine API

        Args:
            path: API endpoint path (e.g. '/issues.json')
            method: HTTP method to use (default: 'get')
            data: Dictionary for request body (for POST/PUT)
            params: Dictionary for query parameters

        Returns:
            str: YAML string containing response status code, body and error message

        {}
        """.format(settings.request_instructions)
        .strip()
    )

    @mcp.tool(description=request_description)
    def redmine_request(
        path: str,
        method: str = "get",
        data: dict | None = None,
        params: dict | None = None,
    ) -> str:
        return yd(request(settings, path, method=method, data=data, params=params))

    @mcp.tool()
    def redmine_paths_list() -> str:
        """Return a list of available API paths from OpenAPI spec"""

        return yd(list(SPEC["paths"].keys()))

    @mcp.tool()
    def redmine_paths_info(path_templates: list[str]) -> str:
        """Get full path information for given path templates"""

        info = {}
        for path in path_templates:
            if path in SPEC["paths"]:
                info[path] = SPEC["paths"][path]

        return yd(info)

    @mcp.tool()
    def redmine_upload(file_path: str, description: str | None = None) -> str:
        """Upload a file to Redmine and return the attachment token."""

        try:
            path = pathlib.Path(file_path).expanduser()
            assert path.is_absolute(), f"Path must be fully qualified, got: {file_path}"
            assert path.exists(), f"File does not exist: {file_path}"

            params = {"filename": path.name}
            if description:
                params["description"] = description

            with open(path, "rb") as f:
                file_content = f.read()

            result = request(
                settings,
                path="uploads.json",
                method="post",
                params=params,
                content_type="application/octet-stream",
                content=file_content,
            )
            return yd(result)
        except Exception as e:
            return yd({"status_code": 0, "body": None, "error": f"{e.__class__.__name__}: {e}"})

    @mcp.tool()
    def redmine_download(
        attachment_id: int,
        save_path: str,
        filename: str | None = None,
    ) -> str:
        """Download an attachment from Redmine and save it locally."""

        try:
            path = pathlib.Path(save_path).expanduser()
            assert path.is_absolute(), f"Path must be fully qualified, got: {save_path}"
            assert not path.is_dir(), f"Path can't be a directory, got: {save_path}"

            resolved_filename = filename
            if not resolved_filename:
                attachment_response = request(settings, f"attachments/{attachment_id}.json", "get")
                if attachment_response["status_code"] != 200:
                    return yd(attachment_response)

                resolved_filename = attachment_response["body"]["attachment"]["filename"]

            response = request(
                settings,
                f"attachments/download/{attachment_id}/{resolved_filename}",
                "get",
                content_type="application/octet-stream",
            )
            if response["status_code"] != 200 or not response["body"]:
                return yd(response)

            with open(path, "wb") as f:
                f.write(response["body"])

            return yd(
                {
                    "status_code": 200,
                    "body": {"saved_to": str(path), "filename": resolved_filename},
                    "error": "",
                }
            )
        except Exception as e:
            return yd({"status_code": 0, "body": None, "error": f"{e.__class__.__name__}: {e}"})

    return mcp


def main() -> None:
    """Main entry point for the mcp-redmine package."""

    settings = RedmineSettings.from_env()
    mcp = create_server(settings)
    mcp.settings.host = "0.0.0.0"
    mcp.settings.port = settings.port
    mcp.run(transport="streamable-http")

if __name__ == "__main__":
    main()

"""Network-facing, unprivileged FastAPI application."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Final, Literal

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict

from snarkyctl import __version__
from snarkyctl.auth import AuthFileError, verify_credentials
from snarkyctl.config import DEFAULT_CONFIG_PATH, ConfigError, load_config
from snarkyctl.control.client import ControlClient, ControlClientError
from snarkyctl.control.protocol import ControlResponse, TargetAlias
from snarkyctl.providers.base import GatewayMode, VpnStatus, VpnTargetCatalog
from snarkyctl.status import GatewayStatus

EXPOSURE_WARNING = "The VPS real public IP address is exposed."
UNKNOWN_WARNING = "The gateway's public-IP exposure state cannot be determined."
_BASIC_AUTH = HTTPBasic(auto_error=False)
REQUEST_MARKER_HEADER: Final[str] = "X-SnarkyCtl-Request"
REQUEST_MARKER_VALUE: Final[str] = "1"
SECURITY_HEADERS: Final[dict[str, str]] = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
        "connect-src 'self'; object-src 'none'; base-uri 'none'; "
        "frame-ancestors 'none'; form-action 'self'"
    ),
    "Permissions-Policy": "camera=(), geolocation=(), microphone=()",
    "Referrer-Policy": "no-referrer",
    "Strict-Transport-Security": "max-age=31536000",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}
_PACKAGE_DIRECTORY = Path(__file__).resolve().parent
_TEMPLATES = Jinja2Templates(directory=_PACKAGE_DIRECTORY / "templates")


class LivenessResponse(BaseModel):
    """Response returned by the process liveness endpoint."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ok"] = "ok"
    service: Literal["snarkyctl-web"] = "snarkyctl-web"
    version: str


class StatusResponse(BaseModel):
    """Read-only, provider-neutral gateway status returned to the browser."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = 1
    vpn_status: VpnStatus
    public_ip_exposed: bool | None
    exposure_warning: str | None


class GatewayStatusResponse(GatewayStatus):
    """Complete, partially degradable gateway snapshot."""

    version: Literal[2] = 2
    public_ip_exposed: bool | None
    exposure_warning: str | None


class VpnConnectRequest(BaseModel):
    """Provider-neutral request to connect using one approved target alias."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target: TargetAlias


class VpnOperationResponse(BaseModel):
    """Normalized result of a provider operation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[2] = 2
    message: str
    vpn_status: VpnStatus
    public_ip_exposed: bool | None
    exposure_warning: str | None


class ErrorBody(BaseModel):
    """Stable API error details."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str


class ErrorResponse(BaseModel):
    """Stable API error envelope."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    error: ErrorBody


@dataclass(frozen=True)
class WebRuntime:
    """Paths and limits needed by the unprivileged web process."""

    auth_file: Path
    control_socket: Path
    control_timeout_seconds: float


class ApiError(RuntimeError):
    """Controlled HTTP failure returned using the stable error envelope."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        authenticate: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.authenticate = authenticate


def create_app(
    runtime: WebRuntime | None = None,
    *,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> FastAPI:
    """Create the web application, optionally with an injected test runtime."""
    application = FastAPI(
        title="SnarkyCtl",
        description="Private control plane for the snarkypuss VPN gateway.",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.state.runtime = runtime
    application.state.config_path = config_path
    application.mount(
        "/static",
        StaticFiles(directory=_PACKAGE_DIRECTORY / "static"),
        name="static",
    )

    @application.middleware("http")
    async def add_security_headers(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        return response

    @application.exception_handler(ApiError)
    async def handle_api_error(_request: Request, exc: ApiError) -> JSONResponse:
        headers = {"WWW-Authenticate": 'Basic realm="SnarkyCtl"'} if exc.authenticate else None
        body = ErrorResponse(error=ErrorBody(code=exc.code, message=str(exc)))
        return JSONResponse(
            status_code=exc.status_code,
            content=body.model_dump(mode="json"),
            headers=headers,
        )

    @application.exception_handler(RequestValidationError)
    async def handle_request_validation_error(
        _request: Request,
        _exc: RequestValidationError,
    ) -> JSONResponse:
        body = ErrorResponse(
            error=ErrorBody(
                code="INVALID_REQUEST",
                message="request body does not match the API schema",
            )
        )
        return JSONResponse(status_code=400, content=body.model_dump(mode="json"))

    @application.get("/api/health/live", response_model=LivenessResponse)
    def liveness() -> LivenessResponse:
        """Report that the HTTPS application process is running."""
        return LivenessResponse(version=__version__)

    @application.get("/", response_class=HTMLResponse)
    def dashboard(
        request: Request,
        credentials: Annotated[HTTPBasicCredentials | None, Depends(_BASIC_AUTH)],
    ) -> Response:
        """Serve the authenticated, read-only status dashboard."""
        active_runtime = _get_runtime(request)
        _authenticate(active_runtime.auth_file, credentials)
        return _TEMPLATES.TemplateResponse(
            request=request,
            name="dashboard.html",
            context={"version": __version__},
        )

    @application.get(
        "/api/v1/status",
        response_model=StatusResponse,
        responses={401: {"model": ErrorResponse}, 502: {"model": ErrorResponse}},
    )
    def status(
        request: Request,
        credentials: Annotated[HTTPBasicCredentials | None, Depends(_BASIC_AUTH)],
    ) -> StatusResponse:
        """Return normalized status obtained only through the control daemon."""
        active_runtime = _get_runtime(request)
        _authenticate(active_runtime.auth_file, credentials)
        response = _control_status(active_runtime)
        if response.gateway_status is None or response.gateway_status.vpn_status is None:
            raise ApiError(502, "INVALID_RESPONSE", "control response has no VPN status")
        vpn_status = response.gateway_status.vpn_status
        exposed, warning = _exposure(vpn_status.gateway_mode)
        return StatusResponse(
            vpn_status=vpn_status,
            public_ip_exposed=exposed,
            exposure_warning=warning,
        )

    @application.get(
        "/api/v2/status",
        response_model=GatewayStatusResponse,
        responses={401: {"model": ErrorResponse}, 502: {"model": ErrorResponse}},
    )
    def gateway_status(
        request: Request,
        credentials: Annotated[HTTPBasicCredentials | None, Depends(_BASIC_AUTH)],
    ) -> GatewayStatusResponse:
        """Return a complete local gateway snapshot with partial failures."""
        active_runtime = _get_runtime(request)
        _authenticate(active_runtime.auth_file, credentials)
        response = _control_status(active_runtime)
        if response.gateway_status is None:
            raise ApiError(502, "INVALID_RESPONSE", "control response has no gateway status")
        snapshot = response.gateway_status
        mode = (
            snapshot.vpn_status.gateway_mode
            if snapshot.vpn_status is not None
            else GatewayMode.UNKNOWN
        )
        exposed, warning = _exposure(mode)
        return GatewayStatusResponse(
            **snapshot.model_dump(),
            public_ip_exposed=exposed,
            exposure_warning=warning,
        )

    @application.get(
        "/api/v2/vpn/targets",
        response_model=VpnTargetCatalog,
        responses={401: {"model": ErrorResponse}, 502: {"model": ErrorResponse}},
    )
    def vpn_targets(
        request: Request,
        credentials: Annotated[HTTPBasicCredentials | None, Depends(_BASIC_AUTH)],
    ) -> VpnTargetCatalog:
        """Return provider-neutral configured targets and capabilities."""
        active_runtime = _get_runtime(request)
        _authenticate(active_runtime.auth_file, credentials)
        client = ControlClient(
            socket_path=active_runtime.control_socket,
            timeout_seconds=active_runtime.control_timeout_seconds,
        )
        try:
            response = client.targets()
        except ControlClientError as exc:
            raise ApiError(502, exc.code, str(exc)) from exc
        if not response.success:
            raise ApiError(
                502,
                response.error_code or "CONTROL_ERROR",
                response.message,
            )
        if response.target_catalog is None:
            raise ApiError(502, "INVALID_RESPONSE", "control response has no target catalogue")
        return response.target_catalog

    @application.post(
        "/api/v2/vpn/connect",
        response_model=VpnOperationResponse,
        responses={
            400: {"model": ErrorResponse},
            401: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            502: {"model": ErrorResponse},
            504: {"model": ErrorResponse},
        },
    )
    def vpn_connect(
        connect_request: VpnConnectRequest,
        request: Request,
        credentials: Annotated[HTTPBasicCredentials | None, Depends(_BASIC_AUTH)],
    ) -> VpnOperationResponse:
        """Connect the configured provider using one approved target alias."""
        active_runtime = _get_runtime(request)
        _authenticate(active_runtime.auth_file, credentials)
        _require_same_origin(request)
        client = ControlClient(
            socket_path=active_runtime.control_socket,
            timeout_seconds=active_runtime.control_timeout_seconds,
        )
        try:
            response = client.connect(connect_request.target)
        except ControlClientError as exc:
            status_code = 504 if exc.code == "DAEMON_TIMEOUT" else 502
            raise ApiError(status_code, exc.code, str(exc)) from exc
        if not response.success:
            error_code = response.error_code or "CONTROL_ERROR"
            status_code = {
                "UNKNOWN_TARGET": 404,
                "PROVIDER_TIMEOUT": 504,
            }.get(error_code, 502)
            raise ApiError(
                status_code,
                error_code,
                response.message,
            )
        if response.vpn_status is None:
            raise ApiError(502, "INVALID_RESPONSE", "control response has no VPN status")
        exposed, warning = _exposure(response.vpn_status.gateway_mode)
        return VpnOperationResponse(
            message=response.message,
            vpn_status=response.vpn_status,
            public_ip_exposed=exposed,
            exposure_warning=warning,
        )

    return application


def _require_same_origin(request: Request) -> None:
    """Reject browser-forgeable state changes before contacting the daemon."""
    if request.headers.get(REQUEST_MARKER_HEADER) != REQUEST_MARKER_VALUE:
        raise ApiError(
            403,
            "CROSS_ORIGIN_REQUEST",
            f"state-changing requests require {REQUEST_MARKER_HEADER}: {REQUEST_MARKER_VALUE}",
        )

    fetch_site = request.headers.get("Sec-Fetch-Site")
    if fetch_site is not None and fetch_site != "same-origin":
        raise ApiError(
            403,
            "CROSS_ORIGIN_REQUEST",
            "state-changing browser requests must originate from this service",
        )

    origin = request.headers.get("Origin")
    expected_origin = f"{request.url.scheme}://{request.url.netloc}"
    if origin is not None and origin != expected_origin:
        raise ApiError(
            403,
            "CROSS_ORIGIN_REQUEST",
            "request Origin does not match this service",
        )


def _get_runtime(request: Request) -> WebRuntime:
    runtime: WebRuntime | None = request.app.state.runtime
    if runtime is not None:
        return runtime
    try:
        config = load_config(request.app.state.config_path)
    except ConfigError as exc:
        raise ApiError(503, "CONFIGURATION_ERROR", str(exc)) from exc
    runtime = WebRuntime(
        auth_file=config.settings.web.auth_file,
        control_socket=config.settings.control.socket_path,
        control_timeout_seconds=config.settings.control.operation_timeout_seconds,
    )
    request.app.state.runtime = runtime
    return runtime


def _authenticate(path: Path, credentials: HTTPBasicCredentials | None) -> None:
    if credentials is None:
        raise ApiError(
            401,
            "AUTHENTICATION_REQUIRED",
            "authentication is required",
            authenticate=True,
        )
    try:
        valid = verify_credentials(path, credentials.username, credentials.password)
    except AuthFileError as exc:
        raise ApiError(503, "AUTHENTICATION_UNAVAILABLE", str(exc)) from exc
    if not valid:
        raise ApiError(
            401,
            "INVALID_CREDENTIALS",
            "invalid username or password",
            authenticate=True,
        )


def _control_status(runtime: WebRuntime) -> ControlResponse:
    client = ControlClient(
        socket_path=runtime.control_socket,
        timeout_seconds=runtime.control_timeout_seconds,
    )
    try:
        response = client.status()
    except ControlClientError as exc:
        raise ApiError(502, exc.code, str(exc)) from exc
    if not response.success:
        raise ApiError(
            502,
            response.error_code or "CONTROL_ERROR",
            response.message,
        )
    return response


def _exposure(mode: GatewayMode) -> tuple[bool | None, str | None]:
    if mode is GatewayMode.DIRECT:
        return True, EXPOSURE_WARNING
    if mode in {GatewayMode.VPN, GatewayMode.LOCKED}:
        return False, None
    return None, UNKNOWN_WARNING


app = create_app()

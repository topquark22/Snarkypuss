"""Network-facing FastAPI application."""

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

from snarkyctl import __version__


class LivenessResponse(BaseModel):
    """Response returned by the process liveness endpoint."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ok"] = "ok"
    service: Literal["snarkyctl-web"] = "snarkyctl-web"
    version: str


app = FastAPI(
    title="SnarkyCtl",
    description="Private control plane for the snarkypuss VPN gateway.",
    version=__version__,
)


@app.get("/api/health/live", response_model=LivenessResponse)
def liveness() -> LivenessResponse:
    """Report that the HTTPS application process is running."""
    return LivenessResponse(version=__version__)

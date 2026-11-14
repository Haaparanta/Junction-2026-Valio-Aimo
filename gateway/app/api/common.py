"""Helpers shared by the /v1 routers: the state, the backend, 404s and the x-agent-tool extension."""

from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request

from ..backend import Backend
from ..stubs import StubState

AGENT = ["agent-tools"]
COMMON = ["status", "reason_code", "message_for_user", "warnings"]


def state(request: Request) -> StubState:
    return request.app.state.stubs


StateDep = Annotated[StubState, Depends(state)]


def backend(request: Request) -> Backend:
    """The app's product facts and prices (app/backend.py), picked once by create_app."""
    return request.app.state.backend


BackendDep = Annotated[Backend, Depends(backend)]


def tool(description: str, *, filters: list[str], timeout: int = 10, **voice: Any) -> dict:
    """OpenAPI extension read by agent/provision.py."""
    return {
        "x-agent-tool": {
            "description": description,
            "response_filter": COMMON + filters,
            "response_timeout_secs": timeout,
            **voice,
        }
    }


def not_found(what: str) -> HTTPException:
    return HTTPException(404, f"{what} not found")

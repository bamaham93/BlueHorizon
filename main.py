import logging
from typing import Any

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from networking import ConnectionManager

app = FastAPI(title="BlueHorizon Networking MVP")
manager = ConnectionManager()
logger = logging.getLogger(__name__)


class RoleAssignmentRequest(BaseModel):
    client_id: str
    role: str


class RouteRequest(BaseModel):
    payload: dict[str, Any]
    visible_to_roles: list[str] | None = None
    dm_only: bool = False
    client_ids: list[str] | None = None
    delay_seconds: float = Field(default=0, ge=0)


class SubsystemRouteRequest(BaseModel):
    owner_role: str
    payload: dict[str, Any]


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/state")
async def state() -> dict[str, Any]:
    return manager.get_state()


@app.post("/dm/assign-role")
async def assign_role(request: RoleAssignmentRequest) -> dict[str, Any]:
    manager.assign_role(request.client_id, request.role)
    await manager.notify_role_assignment(request.client_id)
    await manager.route_message({"type": "dm_roster_update", **manager.get_state()}, dm_only=True)
    return {"status": "assigned", "client_id": request.client_id, "role": request.role}


@app.post("/dm/push")
async def dm_push(request: RouteRequest) -> dict[str, str]:
    await manager.route_message(
        message=request.payload,
        visible_roles=request.visible_to_roles,
        dm_only=request.dm_only,
        client_ids=request.client_ids,
        delay_seconds=request.delay_seconds,
    )
    return {"status": "queued" if request.delay_seconds else "sent"}


@app.post("/dm/subsystem-update")
async def subsystem_push(request: SubsystemRouteRequest) -> dict[str, str]:
    await manager.route_subsystem_update(owner_role=request.owner_role, message=request.payload)
    return {"status": "sent"}


@app.websocket("/ws/{client_id}")
async def websocket_endpoint(
    websocket: WebSocket, client_id: str, display_name: str = Query(default="Unknown")
) -> None:
    await manager.connect(client_id=client_id, websocket=websocket, display_name=display_name)
    await manager.route_message({"type": "dm_roster_update", **manager.get_state()}, dm_only=True)

    try:
        while True:
            message = await websocket.receive_json()
            message_type = message.get("type")
            if message_type == "report":
                await manager.route_message(
                    message=message,
                    visible_roles=message.get("visible_to_roles"),
                )
            elif message_type == "dm_directive":
                delay_value = message.get("delay_seconds")
                try:
                    delay_seconds = float(delay_value) if delay_value is not None else 0
                except (TypeError, ValueError):
                    logger.warning(
                        "Invalid delay_seconds value from %s: %r, defaulting to 0",
                        client_id,
                        delay_value,
                    )
                    delay_seconds = 0
                await manager.route_message(
                    message=message,
                    client_ids=message.get("client_ids"),
                    visible_roles=message.get("visible_to_roles"),
                    delay_seconds=delay_seconds,
                )
            elif message_type == "subsystem_update":
                owner_role = message.get("owner_role")
                if owner_role:
                    await manager.route_subsystem_update(owner_role=owner_role, message=message)
            else:
                await manager.route_message({"type": "dm_event", "payload": message}, dm_only=True)
    except WebSocketDisconnect:
        manager.disconnect(client_id)
        await manager.route_message({"type": "dm_roster_update", **manager.get_state()}, dm_only=True)

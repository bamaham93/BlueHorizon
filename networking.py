import asyncio
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ClientEnvelope:
    client_id: str
    role: str | None


class ConnectionManager:
    HIDDEN_FIELDS = ("raw_roll", "hidden_modifiers", "probability", "confidence_percent")

    def __init__(self) -> None:
        self.active_connections: dict[str, Any] = {}
        self.role_assignments: dict[str, str] = {}
        self.display_names: dict[str, str] = {}
        self.waiting_room: set[str] = set()
        self._background_tasks: set[asyncio.Task[Any]] = set()

    async def connect(self, client_id: str, websocket: Any, display_name: str) -> None:
        await websocket.accept()
        existing = self.active_connections.get(client_id)
        if existing and existing is not websocket:
            await existing.close()

        self.active_connections[client_id] = websocket
        self.display_names[client_id] = display_name
        if client_id not in self.role_assignments:
            self.waiting_room.add(client_id)

        await websocket.send_json(
            {
                "type": "connection_ack",
                "client_id": client_id,
                "display_name": display_name,
                "assigned_role": self.role_assignments.get(client_id),
                "waiting_for_assignment": client_id in self.waiting_room,
            }
        )

    def disconnect(self, client_id: str) -> None:
        self.active_connections.pop(client_id, None)

    def assign_role(self, client_id: str, role: str) -> None:
        self.role_assignments[client_id] = role
        self.waiting_room.discard(client_id)

    def get_state(self) -> dict[str, Any]:
        return {
            "active_clients": [
                {
                    "client_id": cid,
                    "display_name": self.display_names.get(cid, cid),
                    "role": self.role_assignments.get(cid),
                }
                for cid in self.active_connections
            ],
            "waiting_room": [
                {
                    "client_id": cid,
                    "display_name": self.display_names.get(cid, cid),
                }
                for cid in sorted(self.waiting_room)
            ],
        }

    async def notify_role_assignment(self, client_id: str) -> None:
        websocket = self.active_connections.get(client_id)
        if websocket:
            await websocket.send_json(
                {
                    "type": "role_assigned",
                    "client_id": client_id,
                    "assigned_role": self.role_assignments[client_id],
                }
            )

    def _sanitize_for_role(self, message: dict[str, Any], role: str | None) -> dict[str, Any]:
        if role == "dm":
            return dict(message)

        sanitized = dict(message)
        for forbidden in self.HIDDEN_FIELDS:
            sanitized.pop(forbidden, None)
        return sanitized

    def _target_clients(
        self,
        visible_roles: list[str] | None,
        dm_only: bool,
        client_ids: list[str] | None,
    ) -> list[ClientEnvelope]:
        clients: list[ClientEnvelope] = []
        for client_id in self.active_connections:
            role = self.role_assignments.get(client_id)
            if dm_only:
                if role == "dm":
                    clients.append(ClientEnvelope(client_id, role))
                continue

            if client_ids is not None:
                if client_id in client_ids or role == "dm":
                    clients.append(ClientEnvelope(client_id, role))
                continue

            if visible_roles is None:
                clients.append(ClientEnvelope(client_id, role))
                continue

            if role in visible_roles or role == "dm":
                clients.append(ClientEnvelope(client_id, role))

        return clients

    async def route_message(
        self,
        message: dict[str, Any],
        visible_roles: list[str] | None = None,
        dm_only: bool = False,
        client_ids: list[str] | None = None,
        delay_seconds: float = 0,
    ) -> None:
        if delay_seconds > 0:
            task = asyncio.create_task(
                self._delayed_route(message, visible_roles, dm_only, client_ids, delay_seconds)
            )
            self._background_tasks.add(task)
            task.add_done_callback(self._on_background_task_done)
            return

        for envelope in self._target_clients(visible_roles, dm_only, client_ids):
            websocket = self.active_connections.get(envelope.client_id)
            if websocket is None:
                continue
            await websocket.send_json(self._sanitize_for_role(message, envelope.role))

    async def _delayed_route(
        self,
        message: dict[str, Any],
        visible_roles: list[str] | None,
        dm_only: bool,
        client_ids: list[str] | None,
        delay_seconds: float,
    ) -> None:
        await asyncio.sleep(delay_seconds)
        await self.route_message(
            message=message,
            visible_roles=visible_roles,
            dm_only=dm_only,
            client_ids=client_ids,
            delay_seconds=0,
        )

    async def route_subsystem_update(self, owner_role: str, message: dict[str, Any]) -> None:
        await self.route_message(message=message, visible_roles=[owner_role])

    def _on_background_task_done(self, task: asyncio.Task[Any]) -> None:
        self._background_tasks.discard(task)
        try:
            task.result()
        except Exception as exc:
            logger.warning("Delayed route task failed: %s", exc)

import logging
from typing import Any

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from networking import ConnectionManager

app = FastAPI(title="BlueHorizon Networking MVP")
manager = ConnectionManager()
logger = logging.getLogger(__name__)

UI_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>BlueHorizon MVP UI</title>
  <style>
    body { font-family: sans-serif; margin: 1.5rem; max-width: 1000px; }
    h1 { margin-top: 0; }
    section { border: 1px solid #ddd; border-radius: 8px; padding: 1rem; margin-bottom: 1rem; }
    label { display: block; margin: 0.4rem 0; }
    input, textarea, button { font: inherit; }
    textarea { width: 100%; min-height: 110px; }
    .row { display: flex; gap: 0.75rem; flex-wrap: wrap; }
    .row > * { flex: 1 1 250px; }
    #log { background: #111; color: #d6ffd6; padding: 0.8rem; border-radius: 6px; min-height: 180px; white-space: pre-wrap; }
  </style>
</head>
<body>
  <h1>BlueHorizon Networking MVP</h1>

  <section>
    <h2>WebSocket Client</h2>
    <div class="row">
      <label>Client ID <input id="clientId" value="alpha" /></label>
      <label>Display Name <input id="displayName" value="Alpha" /></label>
    </div>
    <button id="connectBtn">Connect</button>
    <button id="disconnectBtn">Disconnect</button>
    <p id="wsStatus">Status: Disconnected</p>
  </section>

  <section>
    <h2>State and Role Assignment</h2>
    <button id="refreshStateBtn">Refresh /state</button>
    <div class="row">
      <label>Assign Client ID <input id="assignClientId" value="alpha" /></label>
      <label>Assign Role <input id="assignRole" value="sonar" /></label>
    </div>
    <button id="assignRoleBtn">POST /dm/assign-role</button>
  </section>

  <section>
    <h2>DM Push</h2>
    <label>Payload JSON
      <textarea id="dmPayload">{"type":"report","body":"Possible contact.","visible_to_roles":["sonar"],"raw_roll":14,"confidence_percent":37}</textarea>
    </label>
    <div class="row">
      <label>Visible Roles (comma-separated) <input id="visibleRoles" value="sonar" /></label>
      <label>Client IDs (comma-separated) <input id="clientIds" value="" /></label>
      <label>Delay Seconds <input id="delaySeconds" type="number" min="0" step="0.1" value="0" /></label>
    </div>
    <label><input id="dmOnly" type="checkbox" /> DM only</label>
    <button id="dmPushBtn">POST /dm/push</button>
  </section>

  <section>
    <h2>Subsystem Update</h2>
    <div class="row">
      <label>Owner Role <input id="ownerRole" value="engineering" /></label>
    </div>
    <label>Payload JSON
      <textarea id="subsystemPayload">{"type":"engineering_report","subsystem":"quieting","integrity":58,"status":"DEGRADED"}</textarea>
    </label>
    <button id="subsystemBtn">POST /dm/subsystem-update</button>
  </section>

  <section>
    <h2>Log</h2>
    <div id="log"></div>
  </section>

  <script>
    let ws = null;
    const logEl = document.getElementById("log");
    const wsStatus = document.getElementById("wsStatus");

    function log(message, data) {
      const line = `[${new Date().toISOString()}] ${message}`;
      logEl.textContent += data === undefined ? `${line}\\n` : `${line} ${JSON.stringify(data)}\\n`;
      logEl.scrollTop = logEl.scrollHeight;
    }

    function parseList(value) {
      const items = value.split(",").map(v => v.trim()).filter(Boolean);
      return items.length ? items : null;
    }

    async function postJson(url, payload) {
      const resp = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await resp.json();
      if (!resp.ok) {
        throw new Error(JSON.stringify(data));
      }
      log(`POST ${url} ok`, data);
      return data;
    }

    document.getElementById("connectBtn").addEventListener("click", () => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        log("WebSocket already connected");
        return;
      }
      const clientId = encodeURIComponent(document.getElementById("clientId").value.trim());
      const displayName = encodeURIComponent(document.getElementById("displayName").value.trim() || "Unknown");
      const protocol = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${protocol}://${location.host}/ws/${clientId}?display_name=${displayName}`);

      ws.onopen = () => {
        wsStatus.textContent = "Status: Connected";
        log("WebSocket connected");
      };
      ws.onmessage = (event) => {
        try {
          log("WS recv", JSON.parse(event.data));
        } catch {
          log("WS recv raw", event.data);
        }
      };
      ws.onclose = () => {
        wsStatus.textContent = "Status: Disconnected";
        log("WebSocket disconnected");
      };
      ws.onerror = () => log("WebSocket error");
    });

    document.getElementById("disconnectBtn").addEventListener("click", () => {
      if (!ws) return;
      ws.close();
      ws = null;
    });

    document.getElementById("refreshStateBtn").addEventListener("click", async () => {
      const resp = await fetch("/state");
      const data = await resp.json();
      log("GET /state", data);
    });

    document.getElementById("assignRoleBtn").addEventListener("click", async () => {
      await postJson("/dm/assign-role", {
        client_id: document.getElementById("assignClientId").value.trim(),
        role: document.getElementById("assignRole").value.trim(),
      });
    });

    document.getElementById("dmPushBtn").addEventListener("click", async () => {
      const payload = JSON.parse(document.getElementById("dmPayload").value);
      await postJson("/dm/push", {
        payload,
        visible_to_roles: parseList(document.getElementById("visibleRoles").value),
        dm_only: document.getElementById("dmOnly").checked,
        client_ids: parseList(document.getElementById("clientIds").value),
        delay_seconds: Number(document.getElementById("delaySeconds").value || 0),
      });
    });

    document.getElementById("subsystemBtn").addEventListener("click", async () => {
      const payload = JSON.parse(document.getElementById("subsystemPayload").value);
      await postJson("/dm/subsystem-update", {
        owner_role: document.getElementById("ownerRole").value.trim(),
        payload,
      });
    });
  </script>
</body>
</html>
"""


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


@app.get("/", response_class=HTMLResponse)
async def ui() -> HTMLResponse:
    return HTMLResponse(UI_HTML)


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
                    logger.warning("Ignoring subsystem_update from %s without owner_role", client_id)
            else:
                await manager.route_message({"type": "dm_event", "payload": message}, dm_only=True)
    except WebSocketDisconnect:
        manager.disconnect(client_id)
        await manager.route_message({"type": "dm_roster_update", **manager.get_state()}, dm_only=True)

import unittest

from networking import ConnectionManager


class FakeWebSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.closed = False
        self.messages: list[dict] = []

    async def accept(self) -> None:
        self.accepted = True

    async def close(self) -> None:
        self.closed = True

    async def send_json(self, payload: dict) -> None:
        self.messages.append(payload)


class ConnectionManagerTests(unittest.IsolatedAsyncioTestCase):
    def assert_message_type_not_received(self, websocket: FakeWebSocket, message_type: str) -> None:
        self.assertFalse(any(msg.get("type") == message_type for msg in websocket.messages))

    async def test_connect_and_reconnect_keep_role_assignment(self) -> None:
        manager = ConnectionManager()
        ws1 = FakeWebSocket()

        await manager.connect("alpha", ws1, "Alpha")
        manager.assign_role("alpha", "sonar")

        ws2 = FakeWebSocket()
        await manager.connect("alpha", ws2, "Alpha")

        self.assertTrue(ws1.closed)
        self.assertEqual(manager.role_assignments["alpha"], "sonar")
        self.assertEqual(manager.active_connections["alpha"], ws2)
        self.assertEqual(ws2.messages[-1]["assigned_role"], "sonar")

    async def test_role_based_routing_and_dm_omniscience(self) -> None:
        manager = ConnectionManager()
        dm = FakeWebSocket()
        sonar = FakeWebSocket()
        captain = FakeWebSocket()

        await manager.connect("dm", dm, "DM")
        await manager.connect("sonar", sonar, "Sonar")
        await manager.connect("captain", captain, "Captain")
        manager.assign_role("dm", "dm")
        manager.assign_role("sonar", "sonar")
        manager.assign_role("captain", "captain")

        await manager.route_message(
            {
                "type": "report",
                "title": "Possible Contact",
                "visible_to_roles": ["sonar"],
            },
            visible_roles=["sonar"],
        )

        self.assertEqual(dm.messages[-1]["type"], "report")
        self.assertEqual(sonar.messages[-1]["type"], "report")
        self.assert_message_type_not_received(captain, "report")

    async def test_subsystem_visibility_enforcement(self) -> None:
        manager = ConnectionManager()
        dm = FakeWebSocket()
        engineer = FakeWebSocket()
        captain = FakeWebSocket()

        await manager.connect("dm", dm, "DM")
        await manager.connect("eng", engineer, "Eng")
        await manager.connect("captain", captain, "Captain")
        manager.assign_role("dm", "dm")
        manager.assign_role("eng", "engineering")
        manager.assign_role("captain", "captain")

        payload = {
            "type": "engineering_report",
            "subsystem": "quieting",
            "integrity": 58,
            "status": "DEGRADED",
        }
        await manager.route_subsystem_update(owner_role="engineering", message=payload)

        self.assertEqual(dm.messages[-1]["type"], "engineering_report")
        self.assertEqual(engineer.messages[-1]["type"], "engineering_report")
        self.assert_message_type_not_received(captain, "engineering_report")

    async def test_hidden_roll_fields_stripped_for_non_dm(self) -> None:
        manager = ConnectionManager()
        dm = FakeWebSocket()
        sonar = FakeWebSocket()

        await manager.connect("dm", dm, "DM")
        await manager.connect("sonar", sonar, "Sonar")
        manager.assign_role("dm", "dm")
        manager.assign_role("sonar", "sonar")

        await manager.route_message(
            {
                "type": "report",
                "visible_to_roles": ["sonar"],
                "raw_roll": 14,
                "hidden_modifiers": ["sea_state"],
                "probability": 0.37,
                "confidence_percent": 37,
                "body": "Intermittent narrowband bearing 214. Confidence LOW.",
            },
            visible_roles=["sonar"],
        )

        self.assertIn("raw_roll", dm.messages[-1])
        self.assertNotIn("raw_roll", sonar.messages[-1])
        self.assertNotIn("probability", sonar.messages[-1])


if __name__ == "__main__":
    unittest.main()

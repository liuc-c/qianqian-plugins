from copy import deepcopy
from types import SimpleNamespace
from typing import Any, cast
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock

from plugin import QianqianPlugin


class PlannerEngagementTests(IsolatedAsyncioTestCase):
    def make_plugin(
        self,
        *,
        enabled_group_ids: list[str] | None = None,
    ) -> QianqianPlugin:
        self.get_group_streams = AsyncMock(
            return_value=[
                {
                    "stream_id": "stream-1000",
                    "group_id": "1000",
                    "platform": "qq",
                },
                {
                    "stream_id": "stream-2000",
                    "group_id": "2000",
                    "platform": "qq",
                },
            ]
        )
        plugin = QianqianPlugin()
        plugin._set_context(
            cast(
                Any,
                SimpleNamespace(
                    chat=SimpleNamespace(get_group_streams=self.get_group_streams),
                    logger=Mock(),
                ),
            )
        )
        config = plugin.build_default_config()
        config["plugin"]["enabled"] = True
        config["planner_engagement"].update(
            {
                "enabled": True,
                "enabled_group_ids": enabled_group_ids or [],
            }
        )
        plugin.set_plugin_config(config)
        return plugin

    @staticmethod
    def tool_definitions() -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "send_voice_reply",
                    "description": "使用语音回复。",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "reply",
                    "description": "发送文字回复。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "attach_emoji": {
                                "type": "string",
                                "description": "附带表情包。",
                            }
                        },
                    },
                },
            },
        ]

    async def test_matching_group_enhances_voice_and_emoji_descriptions(
        self,
    ) -> None:
        plugin = self.make_plugin(enabled_group_ids=["1000"])
        tools = self.tool_definitions()

        result = await plugin.handle_planner_engagement(
            session_id="stream-1000",
            tool_definitions=tools,
        )

        self.assertEqual("continue", result["action"])
        voice = tools[0]["function"]["description"]
        emoji = tools[1]["function"]["parameters"]["properties"]["attach_emoji"][
            "description"
        ]
        self.assertIn("send_voice_reply", voice)
        self.assertIn("不要再发送内容重复的文字回复", voice)
        self.assertIn("attach_emoji", emoji)
        self.assertIn("不要长期完全不用", emoji)

    async def test_non_matching_group_keeps_tool_definitions_unchanged(self) -> None:
        plugin = self.make_plugin(enabled_group_ids=["1000"])
        tools = self.tool_definitions()
        original = deepcopy(tools)

        await plugin.handle_planner_engagement(
            session_id="stream-2000",
            tool_definitions=tools,
        )

        self.assertEqual(original, tools)

    async def test_empty_group_allowlist_applies_to_all_qq_group_streams(
        self,
    ) -> None:
        plugin = self.make_plugin()
        tools = self.tool_definitions()

        await plugin.handle_planner_engagement(
            session_id="stream-2000",
            tool_definitions=tools,
        )

        self.assertIn(
            "send_voice_reply",
            tools[0]["function"]["description"],
        )

    async def test_unknown_or_private_session_is_not_modified(self) -> None:
        plugin = self.make_plugin()
        tools = self.tool_definitions()
        original = deepcopy(tools)

        await plugin.handle_planner_engagement(
            session_id="private-stream",
            tool_definitions=tools,
        )

        self.assertEqual(original, tools)

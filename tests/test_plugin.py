import re
from types import SimpleNamespace
from typing import Any, cast
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock

from plugin import QianqianPlugin


class PluginTestCase(IsolatedAsyncioTestCase):
    async def successful_api_call(
        self,
        api_name: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if api_name == "adapter.napcat.system.get_login_info":
            return {"user_id": 9000, "nickname": "仟仟"}
        if api_name == "adapter.napcat.group.get_group_member_info":
            return {"group_id": 1000, "user_id": 9000, "role": "owner"}
        if api_name == "adapter.napcat.group.set_group_special_title":
            return {"status": "ok", "retcode": 0}
        self.fail(f"调用了未预期的 API: {api_name}")

    @staticmethod
    def anchored_message(
        message_id: str,
        text: str,
        *,
        stream_id: str = "stream-1",
        group_id: int = 1000,
        user_id: int = 2000,
        platform: str = "qq",
    ) -> dict[str, Any]:
        return {
            "message_id": message_id,
            "session_id": stream_id,
            "platform": platform,
            "processed_plain_text": text,
            "message_info": {
                "user_info": {"user_id": user_id},
                "group_info": {"group_id": group_id},
            },
        }

    def make_plugin(
        self,
        *,
        api_call: AsyncMock | None = None,
        message_get_by_id: AsyncMock | None = None,
        send_text: AsyncMock | None = None,
        logger: Mock | None = None,
    ) -> QianqianPlugin:
        self.api_call = api_call or AsyncMock(side_effect=self.successful_api_call)
        self.message_get_by_id = message_get_by_id or AsyncMock()
        self.send_text = send_text or AsyncMock()
        self.logger = logger or Mock()
        plugin = QianqianPlugin()
        plugin._set_context(
            cast(
                Any,
                SimpleNamespace(
                    api=SimpleNamespace(call=self.api_call),
                    send=SimpleNamespace(text=self.send_text),
                    message=SimpleNamespace(get_by_id=self.message_get_by_id),
                    logger=self.logger,
                ),
            )
        )
        return plugin


class PluginContractTests(PluginTestCase):
    def test_only_group_title_command_and_tool_are_registered(self) -> None:
        components = QianqianPlugin().get_components()

        self.assertEqual(
            {
                ("COMMAND", "qianqian_set_group_title_command"),
                ("TOOL", "qianqian_set_group_title"),
            },
            {(component["type"], component["name"]) for component in components},
        )

    def test_command_requires_spaces_and_never_accepts_newlines(self) -> None:
        command = next(
            component
            for component in QianqianPlugin().get_components()
            if component["type"] == "COMMAND"
        )
        pattern = re.compile(command["metadata"]["command_pattern"])

        self.assertIsNotNone(pattern.fullmatch("头衔   盐田皇帝"))
        self.assertIsNotNone(pattern.fullmatch("头衔　盐田皇帝"))
        self.assertIsNone(pattern.fullmatch("头衔盐田皇帝"))
        self.assertIsNone(pattern.fullmatch("头衔\n盐田皇帝"))


class SetGroupTitleCommandTests(PluginTestCase):
    async def test_requester_can_set_literal_title_silently_when_bot_is_owner(
        self,
    ) -> None:
        plugin = self.make_plugin()

        result = await plugin.set_group_title_command(
            stream_id="stream-1",
            group_id="1000",
            user_id="2000",
            platform="qq",
            matched_groups={"title": "  盐田皇帝  "},
        )

        self.assertEqual((True, "", 2), result)
        self.send_text.assert_not_awaited()
        self.api_call.assert_any_await(
            "adapter.napcat.group.set_group_special_title",
            version="1",
            params={
                "group_id": "1000",
                "user_id": "2000",
                "special_title": "盐田皇帝",
            },
        )

    async def test_non_owner_bot_is_rejected_with_visible_error(self) -> None:
        async def call_api(api_name: str, **kwargs: Any) -> dict[str, Any]:
            if api_name == "adapter.napcat.system.get_login_info":
                return {"user_id": 9000}
            if api_name == "adapter.napcat.group.get_group_member_info":
                return {
                    "group_id": 1000,
                    "user_id": 9000,
                    "role": "admin",
                }
            self.fail(f"机器人不是群主时不应调用 API: {api_name}")

        plugin = self.make_plugin(api_call=AsyncMock(side_effect=call_api))

        result = await plugin.set_group_title_command(
            stream_id="stream-1",
            group_id="1000",
            user_id="2000",
            platform="qq",
            matched_groups={"title": "盐田皇帝"},
        )

        error = "设置失败：机器人不是当前群群主"
        self.assertEqual((False, error, 2), result)
        self.send_text.assert_awaited_once_with(error, "stream-1")

    async def test_title_over_six_utf16_units_is_rejected_before_api_call(self) -> None:
        plugin = self.make_plugin(api_call=AsyncMock())

        result = await plugin.set_group_title_command(
            stream_id="stream-1",
            group_id="1000",
            user_id="2000",
            platform="qq",
            matched_groups={"title": "👑👑👑👑"},
        )

        error = "设置失败：头衔最多只能占 6 个字"
        self.assertEqual((False, error, 2), result)
        self.send_text.assert_awaited_once_with(error, "stream-1")
        self.api_call.assert_not_awaited()

    async def test_non_qq_context_is_rejected_before_api_call(self) -> None:
        plugin = self.make_plugin(api_call=AsyncMock())

        result = await plugin.set_group_title_command(
            stream_id="stream-1",
            group_id="1000",
            user_id="2000",
            platform="discord",
            matched_groups={"title": "盐田皇帝"},
        )

        error = "设置失败：仅支持 QQ 群聊"
        self.assertEqual((False, error, 2), result)
        self.send_text.assert_awaited_once_with(error, "stream-1")
        self.api_call.assert_not_awaited()

    async def test_adapter_exception_is_reported_without_leaking_details(self) -> None:
        plugin = self.make_plugin(
            api_call=AsyncMock(side_effect=TimeoutError("rpc secret details")),
        )

        result = await plugin.set_group_title_command(
            stream_id="stream-1",
            group_id="1000",
            user_id="2000",
            platform="qq",
            matched_groups={"title": "盐田皇帝"},
        )

        error = "设置失败：暂时无法连接 QQ 适配器"
        self.assertEqual((False, error, 2), result)
        self.send_text.assert_awaited_once_with(error, "stream-1")
        self.logger.exception.assert_called_once()

    async def test_napcat_rejection_is_reported_by_command(self) -> None:
        async def call_api(api_name: str, **kwargs: Any) -> dict[str, Any]:
            if api_name == "adapter.napcat.system.get_login_info":
                return {"user_id": 9000}
            if api_name == "adapter.napcat.group.get_group_member_info":
                return {
                    "group_id": 1000,
                    "user_id": 9000,
                    "role": "owner",
                }
            if api_name == "adapter.napcat.group.set_group_special_title":
                return {"status": "failed", "retcode": 1400}
            self.fail(f"调用了未预期的 API: {api_name}")

        plugin = self.make_plugin(api_call=AsyncMock(side_effect=call_api))

        result = await plugin.set_group_title_command(
            stream_id="stream-1",
            group_id="1000",
            user_id="2000",
            platform="qq",
            matched_groups={"title": "盐田皇帝"},
        )

        error = "设置失败：QQ 拒绝了本次头衔修改"
        self.assertEqual((False, error, 2), result)
        self.send_text.assert_awaited_once_with(error, "stream-1")


class SetGroupTitleToolTests(PluginTestCase):
    async def test_specified_title_uses_sender_from_anchored_message(self) -> None:
        message_get_by_id = AsyncMock(
            return_value=self.anchored_message(
                "msg-1",
                "请把我的头衔设置为盐田皇帝",
            )
        )
        plugin = self.make_plugin(message_get_by_id=message_get_by_id)

        result = await plugin.set_group_title_tool(
            title="盐田皇帝",
            request_message_id="msg-1",
            mode="specified",
            stream_id="stream-1",
            chat_id="stream-1",
            group_id="1000",
            platform="qq",
        )

        self.assertEqual(
            {
                "success": True,
                "content": "群专属头衔设置成功，无需向用户重复确认。",
            },
            result,
        )
        self.message_get_by_id.assert_awaited_once_with(
            "msg-1",
            stream_id="stream-1",
            include_binary_data=False,
        )
        self.send_text.assert_not_awaited()
        self.api_call.assert_any_await(
            "adapter.napcat.group.set_group_special_title",
            version="1",
            params={
                "group_id": "1000",
                "user_id": "2000",
                "special_title": "盐田皇帝",
            },
        )

    async def test_generated_title_is_allowed_after_explicit_authorization(
        self,
    ) -> None:
        message_get_by_id = AsyncMock(
            return_value=self.anchored_message("msg-2", "帮我想一个头衔")
        )
        plugin = self.make_plugin(message_get_by_id=message_get_by_id)

        result = await plugin.set_group_title_tool(
            title="盐田皇帝",
            request_message_id="msg-2",
            mode="generated",
            stream_id="stream-1",
            chat_id="stream-1",
            group_id="1000",
            platform="qq",
        )

        self.assertTrue(result["success"])
        self.api_call.assert_any_await(
            "adapter.napcat.group.set_group_special_title",
            version="1",
            params={
                "group_id": "1000",
                "user_id": "2000",
                "special_title": "盐田皇帝",
            },
        )

    async def test_missing_anchor_message_fails_closed(self) -> None:
        plugin = self.make_plugin(
            api_call=AsyncMock(),
            message_get_by_id=AsyncMock(return_value=None),
        )

        result = await plugin.set_group_title_tool(
            title="盐田皇帝",
            request_message_id="missing-message",
            mode="specified",
            stream_id="stream-1",
            chat_id="stream-1",
            group_id="1000",
            platform="qq",
        )

        self.assertEqual(
            {"success": False, "content": "设置失败：无法确认请求消息"},
            result,
        )
        self.api_call.assert_not_awaited()

    async def test_napcat_rejection_is_returned_as_readable_error(self) -> None:
        async def call_api(api_name: str, **kwargs: Any) -> dict[str, Any]:
            if api_name == "adapter.napcat.system.get_login_info":
                return {"user_id": 9000}
            if api_name == "adapter.napcat.group.get_group_member_info":
                return {
                    "group_id": 1000,
                    "user_id": 9000,
                    "role": "owner",
                }
            if api_name == "adapter.napcat.group.set_group_special_title":
                return {"status": "failed", "retcode": 1400}
            self.fail(f"调用了未预期的 API: {api_name}")

        plugin = self.make_plugin(
            api_call=AsyncMock(side_effect=call_api),
            message_get_by_id=AsyncMock(
                return_value=self.anchored_message(
                    "msg-3",
                    "把我的头衔设置成盐田皇帝",
                )
            ),
        )

        result = await plugin.set_group_title_tool(
            title="盐田皇帝",
            request_message_id="msg-3",
            mode="specified",
            stream_id="stream-1",
            chat_id="stream-1",
            group_id="1000",
            platform="qq",
        )

        self.assertEqual(
            {"success": False, "content": "设置失败：QQ 拒绝了本次头衔修改"},
            result,
        )

    async def test_message_lookup_exception_fails_closed(self) -> None:
        plugin = self.make_plugin(
            api_call=AsyncMock(),
            message_get_by_id=AsyncMock(side_effect=TimeoutError("database details")),
        )

        result = await plugin.set_group_title_tool(
            title="盐田皇帝",
            request_message_id="msg-timeout",
            mode="specified",
            stream_id="stream-1",
            chat_id="stream-1",
            group_id="1000",
            platform="qq",
        )

        self.assertEqual(
            {"success": False, "content": "设置失败：无法确认请求消息"},
            result,
        )
        self.api_call.assert_not_awaited()
        self.logger.exception.assert_called_once()

    async def test_negated_generation_request_is_not_authorized(self) -> None:
        plugin = self.make_plugin(
            api_call=AsyncMock(),
            message_get_by_id=AsyncMock(
                return_value=self.anchored_message(
                    "msg-negated",
                    "不要帮我想一个头衔",
                )
            ),
        )

        result = await plugin.set_group_title_tool(
            title="盐田皇帝",
            request_message_id="msg-negated",
            mode="generated",
            stream_id="stream-1",
            chat_id="stream-1",
            group_id="1000",
            platform="qq",
        )

        self.assertEqual(
            {"success": False, "content": "设置失败：请求消息未明确授权该头衔"},
            result,
        )
        self.api_call.assert_not_awaited()

    async def test_title_discussion_is_not_a_specified_setting_request(self) -> None:
        plugin = self.make_plugin(
            api_call=AsyncMock(),
            message_get_by_id=AsyncMock(
                return_value=self.anchored_message(
                    "msg-discussion",
                    "盐田皇帝这个头衔怎么样？",
                )
            ),
        )

        result = await plugin.set_group_title_tool(
            title="盐田皇帝",
            request_message_id="msg-discussion",
            mode="specified",
            stream_id="stream-1",
            chat_id="stream-1",
            group_id="1000",
            platform="qq",
        )

        self.assertEqual(
            {"success": False, "content": "设置失败：请求消息未明确授权该头衔"},
            result,
        )
        self.api_call.assert_not_awaited()

    async def test_specified_title_allows_llm_to_understand_request_wording(
        self,
    ) -> None:
        plugin = self.make_plugin(
            message_get_by_id=AsyncMock(
                return_value=self.anchored_message(
                    "msg-wording",
                    "请将本人的群专属头衔改为盐田皇帝",
                )
            )
        )

        result = await plugin.set_group_title_tool(
            title="盐田皇帝",
            request_message_id="msg-wording",
            mode="specified",
            stream_id="stream-1",
            chat_id="stream-1",
            platform="qq",
        )

        self.assertTrue(result["success"])

    async def test_quoted_generation_request_is_only_discussion(self) -> None:
        plugin = self.make_plugin(
            api_call=AsyncMock(),
            message_get_by_id=AsyncMock(
                return_value=self.anchored_message(
                    "msg-quoted",
                    "“随机给我设置一个头衔”这句话礼貌吗？",
                )
            ),
        )

        result = await plugin.set_group_title_tool(
            title="盐田皇帝",
            request_message_id="msg-quoted",
            mode="generated",
            stream_id="stream-1",
            chat_id="stream-1",
            platform="qq",
        )

        self.assertEqual(
            {"success": False, "content": "设置失败：请求消息未明确授权该头衔"},
            result,
        )
        self.api_call.assert_not_awaited()

    async def test_quoted_specified_request_is_only_discussion(self) -> None:
        plugin = self.make_plugin(
            api_call=AsyncMock(),
            message_get_by_id=AsyncMock(
                return_value=self.anchored_message(
                    "msg-quoted-specified",
                    "“把我的头衔设置为盐田皇帝”这句话礼貌吗？",
                )
            ),
        )

        result = await plugin.set_group_title_tool(
            title="盐田皇帝",
            request_message_id="msg-quoted-specified",
            mode="specified",
            stream_id="stream-1",
            chat_id="stream-1",
            platform="qq",
        )

        self.assertEqual(
            {"success": False, "content": "设置失败：请求消息未明确授权该头衔"},
            result,
        )
        self.api_call.assert_not_awaited()

    async def test_title_text_is_not_mistaken_for_request_negation(self) -> None:
        plugin = self.make_plugin(
            message_get_by_id=AsyncMock(
                return_value=self.anchored_message(
                    "msg-negative-title",
                    "请把我的头衔设置为“不想”",
                )
            )
        )

        result = await plugin.set_group_title_tool(
            title="不想",
            request_message_id="msg-negative-title",
            mode="specified",
            stream_id="stream-1",
            chat_id="stream-1",
            platform="qq",
        )

        self.assertTrue(result["success"])

    async def test_earlier_negation_does_not_override_later_specified_title(
        self,
    ) -> None:
        plugin = self.make_plugin(
            message_get_by_id=AsyncMock(
                return_value=self.anchored_message(
                    "msg-correction",
                    "不要盐田皇帝，把我的头衔设置为大王",
                )
            )
        )

        result = await plugin.set_group_title_tool(
            title="大王",
            request_message_id="msg-correction",
            mode="specified",
            stream_id="stream-1",
            chat_id="stream-1",
            platform="qq",
        )

        self.assertTrue(result["success"])

    async def test_context_stream_and_chat_id_must_match(self) -> None:
        plugin = self.make_plugin(api_call=AsyncMock())

        result = await plugin.set_group_title_tool(
            title="盐田皇帝",
            request_message_id="msg-cross-stream",
            mode="specified",
            stream_id="stream-other",
            chat_id="stream-current",
            platform="qq",
        )

        self.assertEqual(
            {"success": False, "content": "设置失败：无法确认请求消息"},
            result,
        )
        self.message_get_by_id.assert_not_awaited()
        self.api_call.assert_not_awaited()

    async def test_group_is_derived_from_anchor_not_tool_argument(self) -> None:
        plugin = self.make_plugin(
            message_get_by_id=AsyncMock(
                return_value=self.anchored_message(
                    "msg-derived-group",
                    "请把我的头衔设置为盐田皇帝",
                    group_id=1000,
                )
            )
        )

        result = await plugin.set_group_title_tool(
            title="盐田皇帝",
            request_message_id="msg-derived-group",
            mode="specified",
            stream_id="stream-1",
            chat_id="stream-1",
            group_id="9999",
            platform="qq",
        )

        self.assertTrue(result["success"])
        self.api_call.assert_any_await(
            "adapter.napcat.group.set_group_special_title",
            version="1",
            params={
                "group_id": "1000",
                "user_id": "2000",
                "special_title": "盐田皇帝",
            },
        )

    async def test_non_qq_anchor_returns_platform_error(self) -> None:
        plugin = self.make_plugin(
            api_call=AsyncMock(),
            message_get_by_id=AsyncMock(
                return_value=self.anchored_message(
                    "msg-discord",
                    "请把我的头衔设置为盐田皇帝",
                    platform="discord",
                )
            ),
        )

        result = await plugin.set_group_title_tool(
            title="盐田皇帝",
            request_message_id="msg-discord",
            mode="specified",
            stream_id="stream-1",
            chat_id="stream-1",
            platform="qq",
        )

        self.assertEqual(
            {"success": False, "content": "设置失败：仅支持 QQ 群聊"},
            result,
        )
        self.api_call.assert_not_awaited()

    async def test_zwj_emoji_title_is_not_treated_as_control_text(self) -> None:
        plugin = self.make_plugin(
            message_get_by_id=AsyncMock(
                return_value=self.anchored_message(
                    "msg-emoji",
                    "请把我的头衔设置为👩‍⚕️",
                )
            )
        )

        result = await plugin.set_group_title_tool(
            title="👩‍⚕️",
            request_message_id="msg-emoji",
            mode="specified",
            stream_id="stream-1",
            chat_id="stream-1",
            platform="qq",
        )

        self.assertTrue(result["success"])
        self.api_call.assert_any_await(
            "adapter.napcat.group.set_group_special_title",
            version="1",
            params={
                "group_id": "1000",
                "user_id": "2000",
                "special_title": "👩‍⚕️",
            },
        )

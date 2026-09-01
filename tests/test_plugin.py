import re
from types import SimpleNamespace
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock

from plugin import QianqianPlugin


class PluginContractTests(IsolatedAsyncioTestCase):
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


class SetGroupTitleCommandTests(IsolatedAsyncioTestCase):
    async def test_requester_can_set_literal_title_silently_when_bot_is_owner(
        self,
    ) -> None:
        async def call_api(api_name: str, **kwargs: Any) -> dict[str, Any]:
            if api_name == "adapter.napcat.system.get_login_info":
                return {"user_id": 9000, "nickname": "仟仟"}
            if api_name == "adapter.napcat.group.get_group_member_info":
                return {
                    "group_id": 1000,
                    "user_id": 9000,
                    "role": "owner",
                }
            if api_name == "adapter.napcat.group.set_group_special_title":
                return {"status": "ok", "retcode": 0}
            self.fail(f"调用了未预期的 API: {api_name}")

        api_call = AsyncMock(side_effect=call_api)
        send_text = AsyncMock()
        plugin = QianqianPlugin()
        plugin._set_context(
            SimpleNamespace(
                api=SimpleNamespace(call=api_call),
                send=SimpleNamespace(text=send_text),
                message=SimpleNamespace(get_by_id=AsyncMock()),
                logger=Mock(),
            )
        )

        result = await plugin.set_group_title_command(
            stream_id="stream-1",
            group_id="1000",
            user_id="2000",
            platform="qq",
            matched_groups={"title": "  盐田皇帝  "},
        )

        self.assertEqual((True, "", 2), result)
        send_text.assert_not_awaited()
        api_call.assert_any_await(
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

        api_call = AsyncMock(side_effect=call_api)
        send_text = AsyncMock(return_value=True)
        plugin = QianqianPlugin()
        plugin._set_context(
            SimpleNamespace(
                api=SimpleNamespace(call=api_call),
                send=SimpleNamespace(text=send_text),
                message=SimpleNamespace(get_by_id=AsyncMock()),
                logger=Mock(),
            )
        )

        result = await plugin.set_group_title_command(
            stream_id="stream-1",
            group_id="1000",
            user_id="2000",
            platform="qq",
            matched_groups={"title": "盐田皇帝"},
        )

        error = "设置失败：机器人不是当前群群主"
        self.assertEqual((False, error, 2), result)
        send_text.assert_awaited_once_with(error, "stream-1")

    async def test_title_over_six_utf16_units_is_rejected_before_api_call(self) -> None:
        api_call = AsyncMock()
        send_text = AsyncMock(return_value=True)
        plugin = QianqianPlugin()
        plugin._set_context(
            SimpleNamespace(
                api=SimpleNamespace(call=api_call),
                send=SimpleNamespace(text=send_text),
                message=SimpleNamespace(get_by_id=AsyncMock()),
                logger=Mock(),
            )
        )

        result = await plugin.set_group_title_command(
            stream_id="stream-1",
            group_id="1000",
            user_id="2000",
            platform="qq",
            matched_groups={"title": "👑👑👑👑"},
        )

        error = "设置失败：头衔最多只能占 6 个字"
        self.assertEqual((False, error, 2), result)
        send_text.assert_awaited_once_with(error, "stream-1")
        api_call.assert_not_awaited()

    async def test_non_qq_context_is_rejected_before_api_call(self) -> None:
        api_call = AsyncMock()
        send_text = AsyncMock(return_value=True)
        plugin = QianqianPlugin()
        plugin._set_context(
            SimpleNamespace(
                api=SimpleNamespace(call=api_call),
                send=SimpleNamespace(text=send_text),
                message=SimpleNamespace(get_by_id=AsyncMock()),
                logger=Mock(),
            )
        )

        result = await plugin.set_group_title_command(
            stream_id="stream-1",
            group_id="1000",
            user_id="2000",
            platform="discord",
            matched_groups={"title": "盐田皇帝"},
        )

        error = "设置失败：仅支持 QQ 群聊"
        self.assertEqual((False, error, 2), result)
        send_text.assert_awaited_once_with(error, "stream-1")
        api_call.assert_not_awaited()

    async def test_adapter_exception_is_reported_without_leaking_details(self) -> None:
        api_call = AsyncMock(side_effect=TimeoutError("rpc secret details"))
        send_text = AsyncMock(return_value=True)
        logger = Mock()
        plugin = QianqianPlugin()
        plugin._set_context(
            SimpleNamespace(
                api=SimpleNamespace(call=api_call),
                send=SimpleNamespace(text=send_text),
                message=SimpleNamespace(get_by_id=AsyncMock()),
                logger=logger,
            )
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
        send_text.assert_awaited_once_with(error, "stream-1")
        logger.exception.assert_called_once()

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

        send_text = AsyncMock(return_value=True)
        plugin = QianqianPlugin()
        plugin._set_context(
            SimpleNamespace(
                api=SimpleNamespace(call=AsyncMock(side_effect=call_api)),
                send=SimpleNamespace(text=send_text),
                message=SimpleNamespace(get_by_id=AsyncMock()),
                logger=Mock(),
            )
        )

        result = await plugin.set_group_title_command(
            stream_id="stream-1",
            group_id="1000",
            user_id="2000",
            platform="qq",
            matched_groups={"title": "盐田皇帝"},
        )

        error = "设置失败：QQ 拒绝了本次头衔修改"
        self.assertEqual((False, error, 2), result)
        send_text.assert_awaited_once_with(error, "stream-1")


class SetGroupTitleToolTests(IsolatedAsyncioTestCase):
    async def test_specified_title_uses_sender_from_anchored_message(self) -> None:
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
                return {"status": "ok", "retcode": 0}
            self.fail(f"调用了未预期的 API: {api_name}")

        message_get_by_id = AsyncMock(
            return_value={
                "session_id": "stream-1",
                "platform": "qq",
                "processed_plain_text": "请把我的头衔设置为盐田皇帝",
                "message_info": {
                    "message_id": "msg-1",
                    "user_info": {"user_id": 2000},
                    "group_info": {"group_id": 1000},
                },
            }
        )
        api_call = AsyncMock(side_effect=call_api)
        send_text = AsyncMock()
        plugin = QianqianPlugin()
        plugin._set_context(
            SimpleNamespace(
                api=SimpleNamespace(call=api_call),
                send=SimpleNamespace(text=send_text),
                message=SimpleNamespace(get_by_id=message_get_by_id),
                logger=Mock(),
            )
        )

        result = await plugin.set_group_title_tool(
            title="盐田皇帝",
            request_message_id="msg-1",
            mode="specified",
            stream_id="stream-1",
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
        message_get_by_id.assert_awaited_once_with(
            "msg-1",
            stream_id="stream-1",
            include_binary_data=False,
        )
        send_text.assert_not_awaited()
        api_call.assert_any_await(
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
                return {"status": "ok", "retcode": 0}
            self.fail(f"调用了未预期的 API: {api_name}")

        message_get_by_id = AsyncMock(
            return_value={
                "session_id": "stream-1",
                "platform": "qq",
                "processed_plain_text": "帮我想一个头衔",
                "message_info": {
                    "message_id": "msg-2",
                    "user_info": {"user_id": 2000},
                    "group_info": {"group_id": 1000},
                },
            }
        )
        api_call = AsyncMock(side_effect=call_api)
        plugin = QianqianPlugin()
        plugin._set_context(
            SimpleNamespace(
                api=SimpleNamespace(call=api_call),
                send=SimpleNamespace(text=AsyncMock()),
                message=SimpleNamespace(get_by_id=message_get_by_id),
                logger=Mock(),
            )
        )

        result = await plugin.set_group_title_tool(
            title="盐田皇帝",
            request_message_id="msg-2",
            mode="generated",
            stream_id="stream-1",
            group_id="1000",
            platform="qq",
        )

        self.assertTrue(result["success"])
        api_call.assert_any_await(
            "adapter.napcat.group.set_group_special_title",
            version="1",
            params={
                "group_id": "1000",
                "user_id": "2000",
                "special_title": "盐田皇帝",
            },
        )

    async def test_missing_anchor_message_fails_closed(self) -> None:
        message_get_by_id = AsyncMock(return_value=None)
        api_call = AsyncMock()
        plugin = QianqianPlugin()
        plugin._set_context(
            SimpleNamespace(
                api=SimpleNamespace(call=api_call),
                send=SimpleNamespace(text=AsyncMock()),
                message=SimpleNamespace(get_by_id=message_get_by_id),
                logger=Mock(),
            )
        )

        result = await plugin.set_group_title_tool(
            title="盐田皇帝",
            request_message_id="missing-message",
            mode="specified",
            stream_id="stream-1",
            group_id="1000",
            platform="qq",
        )

        self.assertEqual(
            {"success": False, "content": "设置失败：无法确认请求消息"},
            result,
        )
        api_call.assert_not_awaited()

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

        plugin = QianqianPlugin()
        plugin._set_context(
            SimpleNamespace(
                api=SimpleNamespace(call=AsyncMock(side_effect=call_api)),
                send=SimpleNamespace(text=AsyncMock()),
                message=SimpleNamespace(
                    get_by_id=AsyncMock(
                        return_value={
                            "session_id": "stream-1",
                            "platform": "qq",
                            "processed_plain_text": "头衔 盐田皇帝",
                            "message_info": {
                                "message_id": "msg-3",
                                "user_info": {"user_id": 2000},
                                "group_info": {"group_id": 1000},
                            },
                        }
                    )
                ),
                logger=Mock(),
            )
        )

        result = await plugin.set_group_title_tool(
            title="盐田皇帝",
            request_message_id="msg-3",
            mode="specified",
            stream_id="stream-1",
            group_id="1000",
            platform="qq",
        )

        self.assertEqual(
            {"success": False, "content": "设置失败：QQ 拒绝了本次头衔修改"},
            result,
        )

    async def test_message_lookup_exception_fails_closed(self) -> None:
        api_call = AsyncMock()
        logger = Mock()
        plugin = QianqianPlugin()
        plugin._set_context(
            SimpleNamespace(
                api=SimpleNamespace(call=api_call),
                send=SimpleNamespace(text=AsyncMock()),
                message=SimpleNamespace(
                    get_by_id=AsyncMock(side_effect=TimeoutError("database details"))
                ),
                logger=logger,
            )
        )

        result = await plugin.set_group_title_tool(
            title="盐田皇帝",
            request_message_id="msg-timeout",
            mode="specified",
            stream_id="stream-1",
            group_id="1000",
            platform="qq",
        )

        self.assertEqual(
            {"success": False, "content": "设置失败：无法确认请求消息"},
            result,
        )
        api_call.assert_not_awaited()
        logger.exception.assert_called_once()

    async def test_negated_generation_request_is_not_authorized(self) -> None:
        api_call = AsyncMock()
        plugin = QianqianPlugin()
        plugin._set_context(
            SimpleNamespace(
                api=SimpleNamespace(call=api_call),
                send=SimpleNamespace(text=AsyncMock()),
                message=SimpleNamespace(
                    get_by_id=AsyncMock(
                        return_value={
                            "session_id": "stream-1",
                            "platform": "qq",
                            "processed_plain_text": "不要帮我想一个头衔",
                            "message_info": {
                                "message_id": "msg-negated",
                                "user_info": {"user_id": 2000},
                                "group_info": {"group_id": 1000},
                            },
                        }
                    )
                ),
                logger=Mock(),
            )
        )

        result = await plugin.set_group_title_tool(
            title="盐田皇帝",
            request_message_id="msg-negated",
            mode="generated",
            stream_id="stream-1",
            group_id="1000",
            platform="qq",
        )

        self.assertEqual(
            {"success": False, "content": "设置失败：请求消息未明确授权该头衔"},
            result,
        )
        api_call.assert_not_awaited()

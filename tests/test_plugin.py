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
            user_id = int(kwargs["user_id"])
            return {
                "group_id": int(kwargs["group_id"]),
                "user_id": user_id,
                "role": "owner" if user_id == 9000 else "member",
            }
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
        raw_message: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return {
            "message_id": message_id,
            "session_id": stream_id,
            "platform": platform,
            "processed_plain_text": text,
            "raw_message": raw_message or [],
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
        allow_all_members_to_set_others: bool = True,
        allowed_requester_ids: list[str] | None = None,
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
        config = plugin.build_default_config()
        config["plugin"]["enabled"] = True
        config["group_title"]["allow_all_members_to_set_others"] = (
            allow_all_members_to_set_others
        )
        config["group_title"]["allowed_requester_ids"] = (
            allowed_requester_ids or []
        )
        plugin.set_plugin_config(config)
        return plugin


class PluginContractTests(PluginTestCase):
    def test_group_title_and_repeater_components_are_registered(self) -> None:
        components = QianqianPlugin().get_components()

        self.assertEqual(
            {
                ("COMMAND", "qianqian_set_group_title_command"),
                ("HOOK_HANDLER", "qianqian_repeater"),
                ("TOOL", "qianqian_set_group_title"),
            },
            {(component["type"], component["name"]) for component in components},
        )

        repeater = next(
            component
            for component in components
            if component["name"] == "qianqian_repeater"
        )
        self.assertEqual(
            "chat.receive.after_process",
            repeater["metadata"]["hook"],
        )
        self.assertEqual("blocking", repeater["metadata"]["mode"])

    def test_repeater_is_disabled_by_default(self) -> None:
        self.assertEqual(
            {
                "enabled": False,
                "repeat_probability": 0.5,
                "enabled_group_ids": [],
            },
            QianqianPlugin.build_default_config()["repeater"],
        )

    def test_setting_other_members_is_denied_by_default(self) -> None:
        self.assertEqual(
            {
                "allow_all_members_to_set_others": False,
                "allowed_requester_ids": [],
            },
            QianqianPlugin.build_default_config()["group_title"],
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

    def test_tool_description_gives_model_a_complete_invocation_contract(
        self,
    ) -> None:
        tool = next(
            component
            for component in QianqianPlugin().get_components()
            if component["type"] == "TOOL"
        )
        metadata = tool["metadata"]
        detailed_description = metadata["detailed_description"]
        parameters = {
            parameter["name"]: parameter for parameter in metadata["parameters"]
        }

        self.assertEqual(
            "执行用户明确要求的本人或指定成员 QQ 群专属头衔设置",
            metadata["brief_description"],
        )
        for stage in (
            "触发：",
            "选择：",
            "锚定：",
            "目标：",
            "完成：",
            "边界：",
        ):
            self.assertIn(stage, detailed_description)
        self.assertIn("逐字复制请求原文", parameters["title"]["description"])
        self.assertIn("逐字复制该值", parameters["request_message_id"]["description"])
        self.assertEqual(
            ["specified", "generated"],
            parameters["mode"]["enum_values"],
        )
        self.assertEqual(
            ["requester", "mentioned", "named"],
            parameters["target_mode"]["enum_values"],
        )
        self.assertFalse(parameters["target_name"]["required"])
        self.assertIn("记忆或黑话", parameters["target_name"]["description"])
        self.assertIn("不要求逐字出现在请求原文", parameters["target_name"]["description"])


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

    async def test_unique_mentioned_member_is_targeted_from_anchored_segments(
        self,
    ) -> None:
        plugin = self.make_plugin(
            message_get_by_id=AsyncMock(
                return_value=self.anchored_message(
                    "msg-mentioned",
                    "@方仟仟 给 @箫阮阮 改头衔为拉屎大王",
                    raw_message=[
                        {
                            "type": "at",
                            "data": {"target_user_id": "9000"},
                        },
                        {"type": "text", "data": " 给 "},
                        {
                            "type": "at",
                            "data": {"target_user_id": "3000"},
                        },
                        {"type": "text", "data": " 改头衔为拉屎大王"},
                    ],
                )
            )
        )

        result = await plugin.set_group_title_tool(
            title="拉屎大王",
            request_message_id="msg-mentioned",
            mode="specified",
            target_mode="mentioned",
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
                "user_id": "3000",
                "special_title": "拉屎大王",
            },
        )

    async def test_mentioned_mode_rejects_multiple_non_bot_members(self) -> None:
        plugin = self.make_plugin(
            message_get_by_id=AsyncMock(
                return_value=self.anchored_message(
                    "msg-many-mentioned",
                    "@方仟仟 给 @箫阮阮 和 @另一人 改头衔为大王",
                    raw_message=[
                        {"type": "at", "data": {"target_user_id": "9000"}},
                        {"type": "at", "data": {"target_user_id": "3000"}},
                        {"type": "at", "data": {"target_user_id": "4000"}},
                    ],
                )
            )
        )

        result = await plugin.set_group_title_tool(
            title="大王",
            request_message_id="msg-many-mentioned",
            mode="specified",
            target_mode="mentioned",
            stream_id="stream-1",
            chat_id="stream-1",
            platform="qq",
        )

        self.assertEqual(
            {
                "success": False,
                "content": "设置失败：请在请求中只 @ 一位要修改头衔的群成员",
            },
            result,
        )
        self.assertFalse(
            any(
                call.args[0]
                == "adapter.napcat.group.set_group_special_title"
                for call in self.api_call.await_args_list
            )
        )

    async def test_setting_another_member_requires_requester_authorization(
        self,
    ) -> None:
        plugin = self.make_plugin(
            allow_all_members_to_set_others=False,
            message_get_by_id=AsyncMock(
                return_value=self.anchored_message(
                    "msg-unauthorized-target",
                    "@方仟仟 给 @箫阮阮 改头衔为大王",
                    raw_message=[
                        {"type": "at", "data": {"target_user_id": "9000"}},
                        {"type": "at", "data": {"target_user_id": "3000"}},
                    ],
                )
            ),
        )

        result = await plugin.set_group_title_tool(
            title="大王",
            request_message_id="msg-unauthorized-target",
            mode="specified",
            target_mode="mentioned",
            stream_id="stream-1",
            chat_id="stream-1",
            platform="qq",
        )

        self.assertEqual(
            {
                "success": False,
                "content": "设置失败：你没有修改其他成员头衔的权限",
            },
            result,
        )

    async def test_allowed_requester_can_set_another_members_title(self) -> None:
        plugin = self.make_plugin(
            allow_all_members_to_set_others=False,
            allowed_requester_ids=["2000"],
            message_get_by_id=AsyncMock(
                return_value=self.anchored_message(
                    "msg-authorized-target",
                    "@方仟仟 给 @箫阮阮 改头衔为大王",
                    raw_message=[
                        {"type": "at", "data": {"target_user_id": "9000"}},
                        {"type": "at", "data": {"target_user_id": "3000"}},
                    ],
                )
            ),
        )

        result = await plugin.set_group_title_tool(
            title="大王",
            request_message_id="msg-authorized-target",
            mode="specified",
            target_mode="mentioned",
            stream_id="stream-1",
            chat_id="stream-1",
            platform="qq",
        )

        self.assertTrue(result["success"])

    async def test_llm_resolved_alias_is_confirmed_against_group_member(self) -> None:
        async def call_api(api_name: str, **kwargs: Any) -> Any:
            if api_name == "adapter.napcat.system.get_login_info":
                return {"user_id": 9000}
            if api_name == "adapter.napcat.group.get_group_member_info":
                return {"group_id": 1000, "user_id": 9000, "role": "owner"}
            if api_name == "adapter.napcat.group.get_group_member_list":
                return [
                    {"user_id": 3000, "card": "箫阮阮", "nickname": "软软"},
                    {"user_id": 4000, "card": "另一人", "nickname": "小明"},
                ]
            if api_name == "adapter.napcat.group.set_group_special_title":
                return {"status": "ok", "retcode": 0}
            self.fail(f"调用了未预期的 API: {api_name}")

        plugin = self.make_plugin(
            api_call=AsyncMock(side_effect=call_api),
            message_get_by_id=AsyncMock(
                return_value=self.anchored_message(
                    "msg-named",
                    "@方仟仟 给阮阮改头衔为拉屎大王",
                )
            ),
        )

        result = await plugin.set_group_title_tool(
            title="拉屎大王",
            request_message_id="msg-named",
            mode="specified",
            target_mode="named",
            target_name="箫阮阮",
            stream_id="stream-1",
            chat_id="stream-1",
            platform="qq",
        )

        self.assertTrue(result["success"])
        self.api_call.assert_any_await(
            "adapter.napcat.group.get_group_member_list",
            version="1",
            group_id="1000",
            no_cache=True,
        )
        self.api_call.assert_any_await(
            "adapter.napcat.group.set_group_special_title",
            version="1",
            params={
                "group_id": "1000",
                "user_id": "3000",
                "special_title": "拉屎大王",
            },
        )

    async def test_named_mode_rejects_duplicate_group_names(self) -> None:
        async def call_api(api_name: str, **kwargs: Any) -> Any:
            if api_name == "adapter.napcat.system.get_login_info":
                return {"user_id": 9000}
            if api_name == "adapter.napcat.group.get_group_member_info":
                return {"group_id": 1000, "user_id": 9000, "role": "owner"}
            if api_name == "adapter.napcat.group.get_group_member_list":
                return [
                    {"user_id": 3000, "card": "箫阮阮", "nickname": "软软"},
                    {"user_id": 4000, "card": "箫阮阮", "nickname": "小明"},
                ]
            self.fail(f"昵称重名时不应继续调用 API: {api_name}")

        plugin = self.make_plugin(
            api_call=AsyncMock(side_effect=call_api),
            message_get_by_id=AsyncMock(
                return_value=self.anchored_message(
                    "msg-duplicate-name",
                    "@方仟仟 给箫阮阮改头衔为大王",
                )
            ),
        )

        result = await plugin.set_group_title_tool(
            title="大王",
            request_message_id="msg-duplicate-name",
            mode="specified",
            target_mode="named",
            target_name="箫阮阮",
            stream_id="stream-1",
            chat_id="stream-1",
            platform="qq",
        )

        self.assertEqual(
            {
                "success": False,
                "content": (
                    "设置失败：找到多位同名群成员，请让用户重新发送消息并 @ 要修改的成员进行二次确认"
                ),
            },
            result,
        )

    async def test_group_card_match_takes_priority_over_qq_nickname(self) -> None:
        async def call_api(api_name: str, **kwargs: Any) -> Any:
            if api_name == "adapter.napcat.system.get_login_info":
                return {"user_id": 9000}
            if api_name == "adapter.napcat.group.get_group_member_info":
                return {"group_id": 1000, "user_id": 9000, "role": "owner"}
            if api_name == "adapter.napcat.group.get_group_member_list":
                return [
                    {"user_id": 3000, "card": "箫阮阮", "nickname": "软软"},
                    {"user_id": 4000, "card": "另一人", "nickname": "箫阮阮"},
                ]
            if api_name == "adapter.napcat.group.set_group_special_title":
                return {"status": "ok", "retcode": 0}
            self.fail(f"调用了未预期的 API: {api_name}")

        plugin = self.make_plugin(
            api_call=AsyncMock(side_effect=call_api),
            message_get_by_id=AsyncMock(
                return_value=self.anchored_message(
                    "msg-card-priority",
                    "@方仟仟 给箫阮阮改头衔为大王",
                )
            ),
        )

        result = await plugin.set_group_title_tool(
            title="大王",
            request_message_id="msg-card-priority",
            mode="specified",
            target_mode="named",
            target_name="箫阮阮",
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
                "user_id": "3000",
                "special_title": "大王",
            },
        )

    async def test_named_mode_requires_a_resolved_member_name(self) -> None:
        plugin = self.make_plugin(
            api_call=AsyncMock(),
            message_get_by_id=AsyncMock(
                return_value=self.anchored_message(
                    "msg-name-missing",
                    "@方仟仟 给阮阮改头衔为大王",
                )
            ),
        )

        result = await plugin.set_group_title_tool(
            title="大王",
            request_message_id="msg-name-missing",
            mode="specified",
            target_mode="named",
            target_name="",
            stream_id="stream-1",
            chat_id="stream-1",
            platform="qq",
        )

        self.assertEqual(
            {
                "success": False,
                "content": "设置失败：无法确认指定的群成员，请直接 @ 对方",
            },
            result,
        )
        self.api_call.assert_not_awaited()

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

    async def test_generated_mode_does_not_reparse_request_wording(self) -> None:
        plugin = self.make_plugin(
            message_get_by_id=AsyncMock(
                return_value=self.anchored_message(
                    "msg-generated-wording",
                    "帮我设置一个霸气的头衔",
                )
            )
        )

        result = await plugin.set_group_title_tool(
            title="九州执剑人",
            request_message_id="msg-generated-wording",
            mode="generated",
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
                "special_title": "九州执剑人",
            },
        )

    async def test_specified_mode_requires_title_to_appear_in_request(self) -> None:
        plugin = self.make_plugin(
            api_call=AsyncMock(),
            message_get_by_id=AsyncMock(
                return_value=self.anchored_message(
                    "msg-title-mismatch",
                    "请把我的头衔设置为盐田皇帝",
                )
            ),
        )

        result = await plugin.set_group_title_tool(
            title="九州执剑人",
            request_message_id="msg-title-mismatch",
            mode="specified",
            stream_id="stream-1",
            chat_id="stream-1",
            platform="qq",
        )

        self.assertEqual(
            {"success": False, "content": "设置失败：指定头衔与请求原文不一致"},
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

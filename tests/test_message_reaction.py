import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock

from plugin import QianqianPlugin


class MessageReactionTests(IsolatedAsyncioTestCase):
    def make_plugin(
        self,
        *,
        enabled_group_ids: list[str] | None = None,
        normal_probability: float = 1.0,
        thinking_delay_seconds: float = 1.5,
    ) -> QianqianPlugin:
        self.api_call = AsyncMock(return_value={"status": "ok", "retcode": 0})
        self.llm_generate = AsyncMock(
            return_value={
                "success": True,
                "response": '{"emoji_id": 233, "reason": "很好笑"}',
            }
        )
        self.message_get_recent = AsyncMock()
        self.chat_get_group_streams = AsyncMock(
            return_value=[{"stream_id": "stream-1000", "group_id": "1000"}]
        )
        self.logger = Mock()
        plugin = QianqianPlugin()
        plugin._set_context(
            cast(
                Any,
                SimpleNamespace(
                    api=SimpleNamespace(call=self.api_call),
                    llm=SimpleNamespace(generate=self.llm_generate),
                    message=SimpleNamespace(get_recent=self.message_get_recent),
                    chat=SimpleNamespace(get_group_streams=self.chat_get_group_streams),
                    logger=self.logger,
                ),
            )
        )
        config = plugin.build_default_config()
        config["plugin"]["enabled"] = True
        config["message_reaction"].update(
            {
                "enabled": True,
                "normal_probability": normal_probability,
                "keyword_probability": normal_probability,
                "enabled_group_ids": enabled_group_ids or [],
                "llm_model": "planner",
                "thinking_delay_seconds": thinking_delay_seconds,
            }
        )
        plugin.set_plugin_config(config)
        return plugin

    @staticmethod
    def message(
        message_id: str = "123456",
        *,
        group_id: str = "1000",
        user_id: str = "2000",
        text: str = "这也太好笑了",
    ) -> dict[str, Any]:
        return {
            "message_id": message_id,
            "timestamp": "100",
            "platform": "qq",
            "session_id": f"stream-{group_id}",
            "processed_plain_text": text,
            "raw_message": [{"type": "text", "data": text}],
            "message_info": {
                "user_info": {
                    "user_id": user_id,
                    "user_nickname": "群成员",
                },
                "group_info": {"group_id": group_id},
                "additional_config": {
                    "self_id": "9000",
                    "platform_io_target_group_id": group_id,
                },
            },
        }

    async def test_proactive_hook_selects_and_sets_reaction_without_aborting(
        self,
    ) -> None:
        plugin = self.make_plugin(enabled_group_ids=["1000"])
        message = self.message()
        self.message_get_recent.return_value = [message]

        result = await plugin.handle_message_reaction(message=message)

        self.assertIsNone(result)
        self.llm_generate.assert_awaited_once()
        self.api_call.assert_awaited_once_with(
            "adapter.napcat.message.set_msg_emoji_like",
            version="1",
            message_id="123456",
            emoji_id=233,
            set=True,
        )

    async def test_cooldown_prevents_a_second_proactive_reaction(self) -> None:
        plugin = self.make_plugin()
        first = self.message("123456")
        second = self.message("123457")
        self.message_get_recent.return_value = [second, first]

        await plugin.handle_message_reaction(message=first)
        await plugin.handle_message_reaction(message=second)

        self.api_call.assert_awaited_once()
        self.llm_generate.assert_awaited_once()

    async def test_wrong_group_and_self_message_are_ignored(self) -> None:
        plugin = self.make_plugin(enabled_group_ids=["1000"])

        await plugin.handle_message_reaction(message=self.message(group_id="9999"))
        await plugin.handle_message_reaction(message=self.message(user_id="9000"))

        self.llm_generate.assert_not_awaited()
        self.api_call.assert_not_awaited()

    async def test_command_like_message_is_ignored(self) -> None:
        plugin = self.make_plugin()

        await plugin.handle_message_reaction(message=self.message(text="/help"))

        self.llm_generate.assert_not_awaited()
        self.api_call.assert_not_awaited()

    async def test_invalid_llm_emoji_is_not_sent(self) -> None:
        plugin = self.make_plugin()
        message = self.message()
        self.message_get_recent.return_value = [message]
        self.llm_generate.return_value = {
            "success": True,
            "response": '{"emoji_id": 999999}',
        }

        await plugin.handle_message_reaction(message=message)

        self.api_call.assert_not_awaited()
        self.logger.warning.assert_called()

    async def test_tool_uses_only_a_real_message_from_the_current_group(self) -> None:
        plugin = self.make_plugin()
        message = self.message()
        self.message_get_recent.return_value = [message]

        result = await plugin.react_to_message_tool(
            target_message_id="123456",
            stream_id="stream-1000",
            chat_id="stream-1000",
            group_id="1000",
            platform="qq",
        )

        self.assertTrue(result["success"])
        self.api_call.assert_awaited_once()

        plugin._message_reaction.clear()
        self.api_call.reset_mock()
        rejected = await plugin.react_to_message_tool(
            target_message_id="654321",
            stream_id="stream-1000",
            chat_id="stream-1000",
            group_id="1000",
            platform="qq",
        )

        self.assertFalse(rejected["success"])
        self.api_call.assert_not_awaited()

    async def test_napcat_failure_is_reported_without_raising(self) -> None:
        plugin = self.make_plugin()
        message = self.message()
        self.message_get_recent.return_value = [message]
        self.api_call.return_value = {"status": "failed", "retcode": 100}

        result = await plugin.react_to_message_tool(
            target_message_id="123456",
            stream_id="stream-1000",
            group_id="1000",
            platform="qq",
        )

        self.assertFalse(result["success"])
        self.logger.warning.assert_called_once()

    @staticmethod
    def planned_call(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "item_type": "FunctionCallItem",
            "tool_call": {
                "call_id": "call-1",
                "func_name": tool_name,
                "args": arguments,
                "extra_content": {},
            },
        }

    async def let_status_task_run(self) -> None:
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    async def test_slow_normal_reply_shows_then_removes_thinking(self) -> None:
        plugin = self.make_plugin(
            enabled_group_ids=["1000"],
            thinking_delay_seconds=0.0,
        )

        result = await plugin.handle_reply_status_start(
            session_id="stream-1000",
            output_items=[self.planned_call("reply", {"msg_id": "123456"})],
        )
        await self.let_status_task_run()
        await plugin.handle_reply_status_finish(
            reply_message_id="123456",
            sent=True,
        )

        self.assertEqual("continue", result["action"])
        self.assertEqual(
            [
                ("123456", 212, True),
                ("123456", 212, False),
            ],
            [
                (
                    call.kwargs["message_id"],
                    call.kwargs["emoji_id"],
                    call.kwargs["set"],
                )
                for call in self.api_call.await_args_list
            ],
        )

    async def test_fast_normal_reply_never_flashes_thinking_or_ok(self) -> None:
        plugin = self.make_plugin(thinking_delay_seconds=10.0)

        await plugin.handle_reply_status_start(
            session_id="stream-1000",
            output_items=[self.planned_call("reply", {"msg_id": "123456"})],
        )
        await plugin.handle_reply_status_finish(
            reply_message_id="123456",
            sent=True,
        )

        self.api_call.assert_not_awaited()

    async def test_fast_title_task_only_adds_ok(self) -> None:
        plugin = self.make_plugin(thinking_delay_seconds=10.0)
        config = plugin.config.message_reaction
        started = plugin._message_reaction.begin_status(
            plugin.ctx,
            stream_id="stream-1000",
            group_id="1000",
            message_id="123456",
            kind="task",
            config=config,
        )

        finished = await plugin._message_reaction.finish_status(
            plugin.ctx,
            message_id="123456",
            success=True,
            show_success=True,
        )

        self.assertTrue(started)
        self.assertTrue(finished)
        self.api_call.assert_awaited_once_with(
            "adapter.napcat.message.set_msg_emoji_like",
            version="1",
            message_id="123456",
            emoji_id=124,
            set=True,
        )

    async def test_slow_title_task_replaces_thinking_with_ok(self) -> None:
        plugin = self.make_plugin(thinking_delay_seconds=0.0)
        config = plugin.config.message_reaction
        plugin._message_reaction.begin_status(
            plugin.ctx,
            stream_id="stream-1000",
            group_id="1000",
            message_id="123456",
            kind="task",
            config=config,
        )
        await self.let_status_task_run()

        await plugin._message_reaction.finish_status(
            plugin.ctx,
            message_id="123456",
            success=True,
            show_success=True,
        )

        self.assertEqual(
            [
                (212, True),
                (212, False),
                (124, True),
            ],
            [
                (call.kwargs["emoji_id"], call.kwargs["set"])
                for call in self.api_call.await_args_list
            ],
        )

    async def test_failed_task_removes_thinking_without_ok(self) -> None:
        plugin = self.make_plugin(thinking_delay_seconds=0.0)
        config = plugin.config.message_reaction
        plugin._message_reaction.begin_status(
            plugin.ctx,
            stream_id="stream-1000",
            group_id="1000",
            message_id="123456",
            kind="task",
            config=config,
        )
        await self.let_status_task_run()

        await plugin._message_reaction.finish_status(
            plugin.ctx,
            message_id="123456",
            success=False,
            show_success=True,
        )

        self.assertEqual(
            [(212, True), (212, False)],
            [
                (call.kwargs["emoji_id"], call.kwargs["set"])
                for call in self.api_call.await_args_list
            ],
        )

    async def test_failed_normal_reply_removes_thinking_without_ok(self) -> None:
        plugin = self.make_plugin(thinking_delay_seconds=0.0)
        await plugin.handle_reply_status_start(
            session_id="stream-1000",
            output_items=[self.planned_call("reply", {"msg_id": "123456"})],
        )
        await self.let_status_task_run()

        await plugin.handle_reply_status_finish(
            reply_message_id="123456",
            sent=False,
        )

        self.assertEqual(
            [(212, True), (212, False)],
            [
                (call.kwargs["emoji_id"], call.kwargs["set"])
                for call in self.api_call.await_args_list
            ],
        )

    async def test_reply_status_takes_over_an_inflight_proactive_reaction(
        self,
    ) -> None:
        plugin = self.make_plugin(thinking_delay_seconds=0.0)
        message = self.message()
        self.message_get_recent.return_value = [message]
        selection_started = asyncio.Event()
        release_selection = asyncio.Event()

        async def select_emoji(*args: Any, **kwargs: Any) -> dict[str, Any]:
            del args
            del kwargs
            selection_started.set()
            await release_selection.wait()
            return {
                "success": True,
                "response": '{"emoji_id": 233, "reason": "很好笑"}',
            }

        self.llm_generate.side_effect = select_emoji
        proactive_task = asyncio.create_task(
            plugin.handle_message_reaction(message=message)
        )
        await selection_started.wait()

        await plugin.handle_reply_status_start(
            session_id="stream-1000",
            output_items=[self.planned_call("reply", {"msg_id": "123456"})],
        )
        await self.let_status_task_run()
        release_selection.set()
        await proactive_task
        await plugin.handle_reply_status_finish(
            reply_message_id="123456",
            sent=True,
        )

        self.assertEqual(
            [(212, True), (212, False)],
            [
                (call.kwargs["emoji_id"], call.kwargs["set"])
                for call in self.api_call.await_args_list
            ],
        )

import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock

from plugin import QianqianPlugin


class RepeaterHookTests(IsolatedAsyncioTestCase):
    def make_plugin(
        self,
        *,
        repeat_probability: float = 1.0,
        enabled_group_ids: list[str] | None = None,
    ) -> QianqianPlugin:
        self.send_text = AsyncMock(return_value=True)
        self.send_hybrid = AsyncMock(return_value=True)
        self.logger = Mock()
        plugin = QianqianPlugin()
        plugin._set_context(
            cast(
                Any,
                SimpleNamespace(
                    send=SimpleNamespace(
                        text=self.send_text,
                        hybrid=self.send_hybrid,
                    ),
                    logger=self.logger,
                ),
            )
        )
        plugin.set_plugin_config(
            {
                "plugin": {"enabled": True, "config_version": "0.3.0"},
                "repeater": {
                    "enabled": True,
                    "repeat_probability": repeat_probability,
                    "enabled_group_ids": enabled_group_ids or [],
                },
            }
        )
        return plugin

    @staticmethod
    def message(
        text: str | None,
        *,
        user_id: str,
        timestamp: float,
        group_id: str = "1000",
        stream_id: str = "qq-group-1000",
        raw_message: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return {
            "message_id": f"message-{user_id}-{timestamp}",
            "timestamp": str(timestamp),
            "platform": "qq",
            "session_id": stream_id,
            "processed_plain_text": text,
            "is_notify": False,
            "raw_message": raw_message
            if raw_message is not None
            else [{"type": "text", "data": text}],
            "message_info": {
                "user_info": {"user_id": user_id},
                "group_info": {"group_id": group_id},
                "additional_config": {"self_id": "9000"},
            },
        }

    async def test_two_members_trigger_one_exact_repeat_and_stop_llm(self) -> None:
        plugin = self.make_plugin()

        first = await plugin.handle_repeater_message(
            message=self.message("哈哈", user_id="2000", timestamp=100.0)
        )
        second = await plugin.handle_repeater_message(
            message=self.message("哈哈", user_id="3000", timestamp=101.0)
        )
        third = await plugin.handle_repeater_message(
            message=self.message("哈哈", user_id="4000", timestamp=102.0)
        )

        self.assertEqual("continue", first["action"])
        self.assertEqual("abort", second["action"])
        self.assertEqual("continue", third["action"])
        self.send_text.assert_awaited_once_with("哈哈", "qq-group-1000")
        self.send_hybrid.assert_not_awaited()

    async def test_text_and_qq_emoji_are_repeated_as_the_same_segments(self) -> None:
        plugin = self.make_plugin()
        segments = [
            {"type": "text", "data": "好耶"},
            {
                "type": "emoji",
                "data": "[动画表情]",
                "hash": "emoji-hash",
                "binary_data_base64": "aGVsbG8=",
            },
        ]

        await plugin.handle_repeater_message(
            message=self.message(
                "好耶[动画表情]",
                user_id="2000",
                timestamp=100.0,
                raw_message=segments,
            )
        )
        result = await plugin.handle_repeater_message(
            message=self.message(
                "好耶[动画表情]",
                user_id="3000",
                timestamp=101.0,
                raw_message=segments,
            )
        )

        self.assertEqual("abort", result["action"])
        self.send_hybrid.assert_awaited_once_with(segments, "qq-group-1000")
        self.send_text.assert_not_awaited()

    async def test_rich_message_between_matching_text_resets_the_queue(self) -> None:
        plugin = self.make_plugin()

        await plugin.handle_repeater_message(
            message=self.message("哈哈", user_id="2000", timestamp=100.0)
        )
        await plugin.handle_repeater_message(
            message=self.message(
                "[图片]",
                user_id="3000",
                timestamp=101.0,
                raw_message=[{"type": "image", "data": "[图片]", "hash": "image-hash"}],
            )
        )
        after_image = await plugin.handle_repeater_message(
            message=self.message("哈哈", user_id="3000", timestamp=102.0)
        )
        next_member = await plugin.handle_repeater_message(
            message=self.message("哈哈", user_id="4000", timestamp=103.0)
        )

        self.assertEqual("continue", after_image["action"])
        self.assertEqual("abort", next_member["action"])
        self.send_text.assert_awaited_once_with("哈哈", "qq-group-1000")

    async def test_commands_never_enter_a_repeat_queue(self) -> None:
        for command in ("/help", "头衔 盐田皇帝"):
            with self.subTest(command=command):
                plugin = self.make_plugin()

                first = await plugin.handle_repeater_message(
                    message=self.message(command, user_id="2000", timestamp=100.0)
                )
                second = await plugin.handle_repeater_message(
                    message=self.message(command, user_id="3000", timestamp=101.0)
                )

                self.assertEqual("continue", first["action"])
                self.assertEqual("continue", second["action"])
                self.send_text.assert_not_awaited()

    async def test_content_over_one_hundred_characters_is_not_repeated(self) -> None:
        plugin = self.make_plugin()
        too_long = "哈" * 101

        await plugin.handle_repeater_message(
            message=self.message(too_long, user_id="2000", timestamp=100.0)
        )
        result = await plugin.handle_repeater_message(
            message=self.message(too_long, user_id="3000", timestamp=101.0)
        )

        self.assertEqual("continue", result["action"])
        self.send_text.assert_not_awaited()

    async def test_qq_emoji_without_processed_text_can_still_repeat(self) -> None:
        plugin = self.make_plugin()
        segments = [
            {
                "type": "emoji",
                "data": "",
                "hash": "emoji-hash",
                "binary_data_base64": "aGVsbG8=",
            }
        ]

        await plugin.handle_repeater_message(
            message=self.message(
                None,
                user_id="2000",
                timestamp=100.0,
                raw_message=segments,
            )
        )
        result = await plugin.handle_repeater_message(
            message=self.message(
                None,
                user_id="3000",
                timestamp=101.0,
                raw_message=segments,
            )
        )

        self.assertEqual("abort", result["action"])
        self.send_hybrid.assert_awaited_once_with(segments, "qq-group-1000")

    async def test_same_member_does_not_reach_the_repeat_threshold(self) -> None:
        plugin = self.make_plugin()

        await plugin.handle_repeater_message(
            message=self.message("哈哈", user_id="2000", timestamp=100.0)
        )
        same_member = await plugin.handle_repeater_message(
            message=self.message("哈哈", user_id="2000", timestamp=101.0)
        )
        another_member = await plugin.handle_repeater_message(
            message=self.message("哈哈", user_id="3000", timestamp=102.0)
        )

        self.assertEqual("continue", same_member["action"])
        self.assertEqual("abort", another_member["action"])
        self.send_text.assert_awaited_once_with("哈哈", "qq-group-1000")

    async def test_failed_repeat_roll_is_not_retried_in_the_same_queue(self) -> None:
        plugin = self.make_plugin(repeat_probability=0.0)

        for offset, user_id in enumerate(("2000", "3000", "4000")):
            result = await plugin.handle_repeater_message(
                message=self.message(
                    "哈哈",
                    user_id=user_id,
                    timestamp=100.0 + offset,
                )
            )
            self.assertEqual("continue", result["action"])

        self.send_text.assert_not_awaited()

    async def test_queue_expires_after_one_hundred_twenty_seconds(self) -> None:
        plugin = self.make_plugin()

        await plugin.handle_repeater_message(
            message=self.message("哈哈", user_id="2000", timestamp=100.0)
        )
        expired = await plugin.handle_repeater_message(
            message=self.message("哈哈", user_id="3000", timestamp=221.0)
        )
        fresh_second_member = await plugin.handle_repeater_message(
            message=self.message("哈哈", user_id="4000", timestamp=222.0)
        )

        self.assertEqual("continue", expired["action"])
        self.assertEqual("abort", fresh_second_member["action"])

    async def test_whitespace_is_compared_exactly(self) -> None:
        plugin = self.make_plugin()

        await plugin.handle_repeater_message(
            message=self.message("哈哈", user_id="2000", timestamp=100.0)
        )
        different = await plugin.handle_repeater_message(
            message=self.message("哈哈 ", user_id="3000", timestamp=101.0)
        )
        same = await plugin.handle_repeater_message(
            message=self.message("哈哈 ", user_id="4000", timestamp=102.0)
        )

        self.assertEqual("continue", different["action"])
        self.assertEqual("abort", same["action"])
        self.send_text.assert_awaited_once_with("哈哈 ", "qq-group-1000")

    async def test_send_failure_keeps_the_normal_message_pipeline_running(self) -> None:
        plugin = self.make_plugin()
        self.send_text.return_value = False

        await plugin.handle_repeater_message(
            message=self.message("哈哈", user_id="2000", timestamp=100.0)
        )
        failed_send = await plugin.handle_repeater_message(
            message=self.message("哈哈", user_id="3000", timestamp=101.0)
        )
        no_retry = await plugin.handle_repeater_message(
            message=self.message("哈哈", user_id="4000", timestamp=102.0)
        )

        self.assertEqual("continue", failed_send["action"])
        self.assertEqual("continue", no_retry["action"])
        self.send_text.assert_awaited_once()
        self.logger.warning.assert_called_once()

    async def test_config_update_clears_in_progress_queues(self) -> None:
        plugin = self.make_plugin()

        await plugin.handle_repeater_message(
            message=self.message("哈哈", user_id="2000", timestamp=100.0)
        )
        await plugin.on_config_update("self", {}, "0.3.0")
        after_update = await plugin.handle_repeater_message(
            message=self.message("哈哈", user_id="3000", timestamp=101.0)
        )

        self.assertEqual("continue", after_update["action"])
        self.send_text.assert_not_awaited()

    async def test_group_allowlist_and_self_messages_cannot_trigger_repeat(
        self,
    ) -> None:
        plugin = self.make_plugin(enabled_group_ids=["1000"])

        for user_id in ("2000", "3000"):
            await plugin.handle_repeater_message(
                message=self.message(
                    "哈哈",
                    user_id=user_id,
                    timestamp=100.0,
                    group_id="9999",
                    stream_id="qq-group-9999",
                )
            )
        await plugin.handle_repeater_message(
            message=self.message("哈哈", user_id="2000", timestamp=101.0)
        )
        self_message = await plugin.handle_repeater_message(
            message=self.message("哈哈", user_id="9000", timestamp=102.0)
        )
        member_message = await plugin.handle_repeater_message(
            message=self.message("哈哈", user_id="3000", timestamp=103.0)
        )

        self.assertEqual("continue", self_message["action"])
        self.assertEqual("abort", member_message["action"])
        self.send_text.assert_awaited_once_with("哈哈", "qq-group-1000")

    async def test_concurrent_members_still_produce_only_one_repeat(self) -> None:
        plugin = self.make_plugin()
        await plugin.handle_repeater_message(
            message=self.message("哈哈", user_id="2000", timestamp=100.0)
        )

        results = await asyncio.gather(
            plugin.handle_repeater_message(
                message=self.message("哈哈", user_id="3000", timestamp=101.0)
            ),
            plugin.handle_repeater_message(
                message=self.message("哈哈", user_id="4000", timestamp=102.0)
            ),
        )

        self.assertEqual(["abort", "continue"], [item["action"] for item in results])
        self.send_text.assert_awaited_once_with("哈哈", "qq-group-1000")

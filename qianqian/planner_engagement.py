"""按 QQ 群增强 Planner 对语音和表情包工具的使用提示。"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, MutableMapping
from typing import Any

from .config import DEFAULT_EMOJI_INSTRUCTION, PlannerEngagementSectionConfig

_CHAT_LOOKUP_TIMEOUT_SECONDS = 5
_LEGACY_EMOJI_INSTRUCTION = (
    "当文字回复适合用表情包加强情绪时，可以主动填写 attach_emoji，内容使用简短的"
    "情绪或表情描述，例如“开心”“无语”“疑惑”“笑哭”。不必每次使用，但不要长期"
    "完全不用。"
)
_STANDALONE_EMOJI_PREFIX = (
    "调用 send_emoji 会把表情包作为独立消息发送，与 reply 的文字消息分开。"
)
_ATTACHED_EMOJI_PREFIX = "填写 attach_emoji 会把表情包附在本轮文字回复中。"


class PlannerEngagementModule:
    """解析聊天流所属群，并修改本轮 Planner 工具定义。"""

    def __init__(self) -> None:
        self._stream_group_ids: dict[str, str] = {}

    def clear(self) -> None:
        """清空聊天流与群号映射缓存。"""
        self._stream_group_ids.clear()

    async def enhance(
        self,
        ctx: Any,
        kwargs: dict[str, Any],
        config: PlannerEngagementSectionConfig,
    ) -> bool:
        """为匹配 QQ 群的工具定义追加活跃使用说明。"""
        if not config.enabled:
            return False
        session_id = str(kwargs.get("session_id", "")).strip()
        group_id = await self._resolve_group_id(ctx, session_id)
        if not group_id:
            return False
        enabled_groups = {
            str(value).strip()
            for value in config.enabled_group_ids
            if str(value).strip()
        }
        if enabled_groups and group_id not in enabled_groups:
            return False

        changed = False
        tools = kwargs.get("tool_definitions")
        if not isinstance(tools, list):
            return False
        for tool in tools:
            function = self._function_schema(tool)
            if function is None:
                continue
            name = str(function.get("name", ""))
            if name == "send_voice_reply":
                changed |= self._append_description(
                    function,
                    config.voice_instruction,
                )
            if name == "send_emoji":
                changed |= self._append_description(
                    function,
                    self._emoji_instruction(
                        config.emoji_instruction,
                        standalone=True,
                    ),
                )
            if name == "reply":
                changed |= self._enhance_reply_emoji(
                    function,
                    self._emoji_instruction(
                        config.emoji_instruction,
                        standalone=False,
                    ),
                )
        return changed

    @staticmethod
    def _emoji_instruction(instruction: str, *, standalone: bool) -> str:
        """为独立或丰富回复表情包生成不冲突的工具提示。"""
        usage = instruction.strip()
        if usage == _LEGACY_EMOJI_INSTRUCTION:
            usage = DEFAULT_EMOJI_INSTRUCTION
        if standalone:
            usage = usage.replace("填写 attach_emoji", "调用 send_emoji")
            usage = usage.replace("attach_emoji", "send_emoji")
            prefix = _STANDALONE_EMOJI_PREFIX
        else:
            prefix = _ATTACHED_EMOJI_PREFIX
        return f"{prefix}{usage}"

    async def _resolve_group_id(self, ctx: Any, session_id: str) -> str:
        """通过 SDK 群聊流能力把内部 session_id 映射成 QQ 群号。"""
        if not session_id:
            return ""
        cached = self._stream_group_ids.get(session_id)
        if cached:
            return cached
        try:
            async with asyncio.timeout(_CHAT_LOOKUP_TIMEOUT_SECONDS):
                streams = await ctx.chat.get_group_streams(platform="qq")
        except Exception:
            ctx.logger.exception("解析 Planner 当前 QQ 群失败")
            return ""
        if not isinstance(streams, list):
            return ""
        for stream in streams:
            if not isinstance(stream, Mapping):
                continue
            stream_key = str(stream.get("stream_id", "")).strip()
            group_id = str(stream.get("group_id", "")).strip()
            if stream_key and group_id:
                self._stream_group_ids[stream_key] = group_id
        return self._stream_group_ids.get(session_id, "")

    async def resolve_group_id(self, ctx: Any, session_id: str) -> str:
        """公开复用当前聊天流到 QQ 群号的安全映射。"""
        return await self._resolve_group_id(ctx, session_id)

    @staticmethod
    def _function_schema(tool: Any) -> MutableMapping[str, Any] | None:
        if not isinstance(tool, MutableMapping):
            return None
        function = tool.get("function")
        if isinstance(function, MutableMapping):
            return function
        if "name" in tool:
            return tool
        return None

    @staticmethod
    def _append_description(
        schema: MutableMapping[str, Any],
        instruction: str,
    ) -> bool:
        instruction = instruction.strip()
        if not instruction:
            return False
        current = str(schema.get("description", "")).strip()
        if instruction in current:
            return False
        schema["description"] = f"{current}\n\n{instruction}".strip()
        return True

    @classmethod
    def _enhance_reply_emoji(
        cls,
        function: MutableMapping[str, Any],
        instruction: str,
    ) -> bool:
        parameters = function.get("parameters")
        if not isinstance(parameters, MutableMapping):
            return False
        properties = parameters.get("properties")
        if not isinstance(properties, MutableMapping):
            return False
        attach_emoji = properties.get("attach_emoji")
        if not isinstance(attach_emoji, MutableMapping):
            return False
        return cls._append_description(attach_emoji, instruction)

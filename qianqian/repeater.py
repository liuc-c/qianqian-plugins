"""QQ 群复读队列与抽签。"""

import asyncio
import base64
import hashlib
import random
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from qianqian.config import RepeaterSectionConfig
from qianqian.group_title import TITLE_COMMAND_PATTERN

_MAX_INTERVAL_SECONDS = 120
_MAX_CONTENT_LENGTH = 100
_MIN_DISTINCT_SENDERS = 2
_TITLE_COMMAND_PATTERN = re.compile(TITLE_COMMAND_PATTERN)


@dataclass(frozen=True, slots=True)
class RepeatOutput:
    """一次需要发送的复读结果。"""

    stream_id: str
    text: str
    segments: list[dict[str, Any]] | None = None


@dataclass(slots=True)
class _QueueState:
    """一个群当前的复读队列。"""

    content_key: tuple[tuple[str, str, str], ...]
    text: str
    segments: list[dict[str, Any]] | None
    sender_ids: set[str]
    last_seen_at: float
    decided: bool = False


class RepeaterModule:
    """维护各群复读队列，并对外给出单次发送决策。"""

    def __init__(self) -> None:
        self._states: dict[str, _QueueState] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def clear(self) -> None:
        """清空全部复读队列。"""
        self._states.clear()

    async def evaluate(
        self,
        message: Any,
        config: RepeaterSectionConfig,
    ) -> RepeatOutput | None:
        """接收一条 Hook 消息，并决定是否需要发送。"""
        scope = self._resolve_scope(message, config)
        if scope is None:
            return None
        stream_id, sender_id = scope
        lock = self._locks.setdefault(stream_id, asyncio.Lock())
        async with lock:
            parsed = self._parse_content(message)
            if parsed is None:
                self._states.pop(stream_id, None)
                return None
            timestamp, content_key, text, segments = parsed
            state = self._states.get(stream_id)
            if (
                state is None
                or state.content_key != content_key
                or timestamp - state.last_seen_at > _MAX_INTERVAL_SECONDS
                or timestamp < state.last_seen_at
            ):
                self._states[stream_id] = _QueueState(
                    content_key=content_key,
                    text=text,
                    segments=segments,
                    sender_ids={sender_id},
                    last_seen_at=timestamp,
                )
                return None

            state.last_seen_at = timestamp
            state.sender_ids.add(sender_id)
            if state.decided or len(state.sender_ids) < _MIN_DISTINCT_SENDERS:
                return None

            state.decided = True
            if random.random() >= config.repeat_probability:
                return None
            return RepeatOutput(
                stream_id=stream_id,
                text=state.text,
                segments=state.segments,
            )

    @staticmethod
    def _resolve_scope(
        message: Any,
        config: RepeaterSectionConfig,
    ) -> tuple[str, str] | None:
        """确认消息属于启用群且并非机器人自身。"""
        if not config.enabled or not isinstance(message, Mapping):
            return None
        if str(message.get("platform", "")).lower() != "qq":
            return None

        message_info = message.get("message_info")
        if not isinstance(message_info, Mapping):
            return None
        group_info = message_info.get("group_info")
        user_info = message_info.get("user_info")
        if not isinstance(group_info, Mapping) or not isinstance(user_info, Mapping):
            return None

        group_id = str(group_info.get("group_id", "")).strip()
        sender_id = str(user_info.get("user_id", "")).strip()
        stream_id = str(message.get("session_id", "")).strip()
        if not group_id or not sender_id or not stream_id:
            return None
        enabled_groups = {str(value).strip() for value in config.enabled_group_ids}
        if enabled_groups and group_id not in enabled_groups:
            return None

        additional_config = message_info.get("additional_config")
        if isinstance(additional_config, Mapping):
            self_id = str(additional_config.get("self_id", "")).strip()
            if self_id and sender_id == self_id:
                return None
        return stream_id, sender_id

    @staticmethod
    def _parse_content(
        message: Any,
    ) -> (
        tuple[
            float,
            tuple[tuple[str, str, str], ...],
            str,
            list[dict[str, Any]] | None,
        ]
        | None
    ):
        plain_text = message.get("processed_plain_text")
        if message.get("is_notify") is True:
            return None
        if isinstance(plain_text, str) and (
            plain_text.lstrip().startswith("/")
            or _TITLE_COMMAND_PATTERN.fullmatch(plain_text)
        ):
            return None

        try:
            timestamp = float(message.get("timestamp", ""))
        except (TypeError, ValueError):
            return None

        raw_message = message.get("raw_message")
        if not isinstance(raw_message, list) or not raw_message:
            return None
        text_parts: list[str] = []
        content_parts: list[tuple[str, str, str]] = []
        outbound_segments: list[dict[str, Any]] = []
        contains_emoji = False
        content_length = 0
        for segment in raw_message:
            if not isinstance(segment, Mapping):
                return None
            segment_type = str(segment.get("type", "")).lower()
            data = segment.get("data")
            if not isinstance(data, str) or segment_type not in {"text", "emoji"}:
                return None
            text_parts.append(data)
            if segment_type == "text":
                content_length += len(data)
                content_parts.append(("text", data, ""))
                outbound_segments.append({"type": "text", "data": data})
                continue

            contains_emoji = True
            content_length += 1
            emoji_hash = str(segment.get("hash", "")).strip()
            binary_data = segment.get("binary_data_base64")
            decoded_binary: bytes | None = None
            if isinstance(binary_data, str) and binary_data:
                try:
                    decoded_binary = base64.b64decode(binary_data, validate=True)
                except (ValueError, TypeError):
                    decoded_binary = None
            if not emoji_hash and not decoded_binary:
                return None
            identity = emoji_hash or hashlib.sha256(decoded_binary or b"").hexdigest()
            content_parts.append(("emoji", data, identity))
            outbound_emoji: dict[str, Any] = {"type": "emoji", "data": data}
            if emoji_hash:
                outbound_emoji["hash"] = emoji_hash
            if decoded_binary is not None:
                outbound_emoji["binary_data_base64"] = binary_data
            outbound_segments.append(outbound_emoji)

        text = "".join(text_parts)
        if (not text and not contains_emoji) or content_length > _MAX_CONTENT_LENGTH:
            return None
        segments = outbound_segments if contains_emoji else None
        return timestamp, tuple(content_parts), text, segments

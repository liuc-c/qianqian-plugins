"""QQ 群消息贴表情能力。

表情集合与 LLM 选择思路改编自 Ghost_chu 的 MIT 许可项目
``maiplug_message_react`` 及其后续二开版本；本实现改用 MaiBot 命名 Hook 和
NapCat Adapter 公开 API，避免直接连接 NapCat HTTP 服务。
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .config import MessageReactionSectionConfig

AVAILABLE_REACTION_EMOJIS: dict[int, str] = {
    5: "大哭",
    9: "委屈",
    13: "呲牙",
    20: "偷笑",
    37: "骷髅头",
    38: "木槌敲头",
    46: "猪头",
    49: "抱抱",
    59: "便便",
    63: "玫瑰",
    66: "爱心",
    76: "点赞",
    124: "OK",
    144: "礼花",
    146: "爆筋",
    147: "棒棒糖",
    175: "卖萌",
    187: "鬼魂",
    212: "托腮",
    233: "笑哭",
    265: "辣眼睛",
    277: "狗头",
    285: "摸鱼",
    293: "敲脑瓜",
    307: "喵喵",
    311: "打call",
    344: "大怨种",
    350: "贴贴",
    390: "头秃",
    424: "狂按按钮",
}

_REACTABLE_KEYWORDS = (
    "哈哈",
    "笑死",
    "好耶",
    "草",
    "可爱",
    "贴贴",
    "抱抱",
    "哭",
    "难过",
    "谢谢",
    "恭喜",
    "牛",
    "厉害",
    "救命",
    "离谱",
    "绷不住",
    "？",
    "!",
    "！",
    "www",
    "233",
    "orz",
)
_MAX_TRACKED_MESSAGE_IDS = 4096
_LLM_TIMEOUT_SECONDS = 60
_NAPCAT_TIMEOUT_SECONDS = 10
_THINKING_EMOJI_ID = 212
_SUCCESS_EMOJI_ID = 124
_STATUS_REPLY = "reply"
_STATUS_TASK = "task"


@dataclass(frozen=True, slots=True)
class ReactionTarget:
    """一条经过可信消息上下文解析的贴表情目标。"""

    stream_id: str
    group_id: str
    message_id: str
    sender_name: str
    content: str


@dataclass(frozen=True, slots=True)
class ReactionRecord:
    """一条消息当前由本插件维护的反应。"""

    source: str
    emoji_id: int | None = None


@dataclass(slots=True)
class PendingStatus:
    """Planner 已决定执行、但尚未完成的消息状态。"""

    stream_id: str
    group_id: str
    message_id: str
    kind: str
    task: asyncio.Task[None] | None = None
    thinking_active: bool = False


class MessageReactionModule:
    """管理主动贴表情状态并执行 LLM 选择与 NapCat 调用。"""

    def __init__(self) -> None:
        self._last_success_at: dict[str, float] = {}
        self._reaction_records: dict[str, ReactionRecord] = {}
        self._reacted_message_order: deque[str] = deque()
        self._locks: dict[str, asyncio.Lock] = {}
        self._pending_statuses: dict[str, PendingStatus] = {}

    def clear(self) -> None:
        """取消后台任务并清空冷却、去重和并发状态。"""
        for status in self._pending_statuses.values():
            if status.task is not None:
                status.task.cancel()
        self._pending_statuses.clear()
        self._last_success_at.clear()
        self._reaction_records.clear()
        self._reacted_message_order.clear()
        self._locks.clear()

    async def shutdown(self, ctx: Any) -> None:
        """卸载或重载前撤销仍显示的处理中表情并取消后台任务。"""
        for message_id in tuple(self._pending_statuses):
            await self.finish_status(
                ctx,
                message_id=message_id,
                success=False,
                show_success=False,
            )
        self.clear()

    async def react_proactively(
        self,
        ctx: Any,
        message: Any,
        config: MessageReactionSectionConfig,
    ) -> bool:
        """按配置判断一条入站群消息，并在抽中时贴表情。"""
        if not config.enabled or not config.proactive_enabled:
            return False
        target = self._target_from_message(message, config)
        if target is None:
            return False

        lock = self._locks.setdefault(target.stream_id, asyncio.Lock())
        async with lock:
            if target.message_id in self._pending_statuses:
                return False
            if target.message_id in self._reaction_records:
                return False
            elapsed = time.time() - self._last_success_at.get(target.stream_id, 0.0)
            if elapsed < config.cooldown_seconds:
                return False
            probability = (
                config.keyword_probability
                if self._looks_reactable(target.content)
                else config.normal_probability
            )
            if random.random() >= probability:
                return False
            reservation = ReactionRecord(source="proactive_pending")
            self._remember_reacted_message(target.message_id, reservation)

        emoji_id, emoji_name = await self._select_for_target(ctx, target, config)
        async with lock:
            if self._reaction_records.get(target.message_id) is not reservation:
                return False
            if target.message_id in self._pending_statuses:
                self._forget_reacted_message(target.message_id)
                return False
            if emoji_id is None:
                self._forget_reacted_message(target.message_id)
                return False
            if not await self._set_reaction(
                ctx,
                message_id=target.message_id,
                emoji_id=emoji_id,
                set_like=True,
                emoji_name=emoji_name,
            ):
                self._forget_reacted_message(target.message_id)
                return False
            self._last_success_at[target.stream_id] = time.time()
            self._reaction_records[target.message_id] = ReactionRecord(
                source="proactive",
                emoji_id=emoji_id,
            )
            return True

    async def react_from_tool(
        self,
        ctx: Any,
        *,
        stream_id: str,
        group_id: str,
        target_message_id: str,
        config: MessageReactionSectionConfig,
    ) -> dict[str, Any]:
        """验证 Tool 上下文中的目标消息，并执行一次贴表情。"""
        if not config.enabled:
            return {"success": False, "content": "消息贴表情功能未启用"}
        if not stream_id or not group_id:
            return {"success": False, "content": "消息贴表情仅支持 QQ 群聊"}
        enabled_groups = self._normalized_group_ids(config.enabled_group_ids)
        if enabled_groups and group_id not in enabled_groups:
            return {"success": False, "content": "当前 QQ 群未启用消息贴表情"}

        recent = await self._get_recent_messages(ctx, stream_id, limit=20)
        if not target_message_id and recent:
            target_message_id = str(recent[0].get("message_id", "")).strip()
        target = self._target_from_recent(
            recent,
            stream_id=stream_id,
            group_id=group_id,
            target_message_id=target_message_id,
        )
        if target is None:
            return {"success": False, "content": "无法在当前群最近消息中确认目标消息"}

        lock = self._locks.setdefault(stream_id, asyncio.Lock())
        async with lock:
            if target.message_id in self._pending_statuses:
                return {"success": False, "content": "这条消息正在处理中"}
            if target.message_id in self._reaction_records:
                return {"success": False, "content": "这条消息已经贴过表情了"}
            reservation = ReactionRecord(source="tool_pending")
            self._remember_reacted_message(target.message_id, reservation)

        emoji_id, emoji_name = await self._select_for_target(
            ctx,
            target,
            config,
            recent=recent,
        )
        async with lock:
            if self._reaction_records.get(target.message_id) is not reservation:
                return {"success": False, "content": "这条消息的状态已经发生变化"}
            if emoji_id is None:
                self._forget_reacted_message(target.message_id)
                return {"success": False, "content": "贴表情失败，请稍后再试"}
            if not await self._set_reaction(
                ctx,
                message_id=target.message_id,
                emoji_id=emoji_id,
                set_like=True,
                emoji_name=emoji_name,
            ):
                self._forget_reacted_message(target.message_id)
                return {"success": False, "content": "贴表情失败，请稍后再试"}
            self._last_success_at[stream_id] = time.time()
            self._reaction_records[target.message_id] = ReactionRecord(
                source="tool",
                emoji_id=emoji_id,
            )
        return {"success": True, "content": "已为目标消息贴上合适的表情"}

    def begin_planned_statuses(
        self,
        ctx: Any,
        *,
        stream_id: str,
        group_id: str,
        output_items: Any,
        config: MessageReactionSectionConfig,
    ) -> int:
        """从 Planner 输出中识别回复与本插件任务，并登记延迟状态。"""
        if not isinstance(output_items, list):
            return 0
        started = 0
        for item in output_items:
            if (
                not isinstance(item, Mapping)
                or item.get("item_type") != "FunctionCallItem"
            ):
                continue
            tool_call = item.get("tool_call")
            if not isinstance(tool_call, Mapping):
                continue
            tool_name = str(tool_call.get("func_name", "")).strip()
            arguments = tool_call.get("args")
            if not isinstance(arguments, Mapping):
                continue
            if tool_name == "reply":
                message_id = str(arguments.get("msg_id", "")).strip()
                kind = _STATUS_REPLY
            elif tool_name == "qianqian_set_group_title":
                message_id = str(arguments.get("request_message_id", "")).strip()
                kind = _STATUS_TASK
            else:
                continue
            if self.begin_status(
                ctx,
                stream_id=stream_id,
                group_id=group_id,
                message_id=message_id,
                kind=kind,
                config=config,
            ):
                started += 1
        return started

    def begin_status(
        self,
        ctx: Any,
        *,
        stream_id: str,
        group_id: str,
        message_id: str,
        kind: str,
        config: MessageReactionSectionConfig,
    ) -> bool:
        """立即登记状态；只有处理超过配置延迟后才真正显示托腮。"""
        if not config.enabled or not config.status_enabled:
            return False
        if kind not in {_STATUS_REPLY, _STATUS_TASK}:
            return False
        if not stream_id or not self._is_positive_integer(message_id):
            return False

        existing = self._pending_statuses.get(message_id)
        if existing is not None:
            if existing.stream_id != stream_id:
                return False
            if kind == _STATUS_TASK:
                existing.kind = _STATUS_TASK
            return True

        if not group_id:
            return False
        enabled_groups = self._normalized_group_ids(config.enabled_group_ids)
        if enabled_groups and group_id not in enabled_groups:
            return False

        record = self._reaction_records.get(message_id)
        if record is not None and record.source.startswith("tool"):
            return False
        if record is not None and record.source == "status_success":
            return False

        status = PendingStatus(
            stream_id=stream_id,
            group_id=group_id,
            message_id=message_id,
            kind=kind,
        )
        self._pending_statuses[message_id] = status
        if record is None:
            self._remember_reacted_message(
                message_id,
                ReactionRecord(source="status_pending"),
            )
        status.task = asyncio.create_task(
            self._show_thinking_after_delay(ctx, status, config),
            name=f"qianqian-thinking-{message_id}",
        )
        return True

    async def finish_status(
        self,
        ctx: Any,
        *,
        message_id: str,
        success: bool,
        show_success: bool,
    ) -> bool:
        """结束状态：回复只撤销托腮，明确任务成功时改贴 OK。"""
        status = self._pending_statuses.get(message_id)
        if status is None:
            return False
        lock = self._locks.setdefault(status.stream_id, asyncio.Lock())
        async with lock:
            if self._pending_statuses.get(message_id) is not status:
                return False
            self._pending_statuses.pop(message_id, None)
            current_task = asyncio.current_task()
            if status.task is not None and status.task is not current_task:
                status.task.cancel()

            record = self._reaction_records.get(message_id)
            if status.thinking_active:
                removed = await self._set_reaction(
                    ctx,
                    message_id=message_id,
                    emoji_id=_THINKING_EMOJI_ID,
                    set_like=False,
                    emoji_name=AVAILABLE_REACTION_EMOJIS[_THINKING_EMOJI_ID],
                )
                if not removed:
                    return False
                self._forget_reacted_message(message_id)
                record = None

            should_show_success = (
                success and show_success and status.kind == _STATUS_TASK
            )
            if should_show_success:
                if record is not None and record.emoji_id is not None:
                    removed = await self._set_reaction(
                        ctx,
                        message_id=message_id,
                        emoji_id=record.emoji_id,
                        set_like=False,
                        emoji_name=AVAILABLE_REACTION_EMOJIS.get(
                            record.emoji_id,
                            str(record.emoji_id),
                        ),
                    )
                    if not removed:
                        return False
                self._forget_reacted_message(message_id)
                if not await self._set_reaction(
                    ctx,
                    message_id=message_id,
                    emoji_id=_SUCCESS_EMOJI_ID,
                    set_like=True,
                    emoji_name=AVAILABLE_REACTION_EMOJIS[_SUCCESS_EMOJI_ID],
                ):
                    return False
                self._remember_reacted_message(
                    message_id,
                    ReactionRecord(source="status_success", emoji_id=_SUCCESS_EMOJI_ID),
                )
                return True

            if record is not None and record.source.startswith("status"):
                self._forget_reacted_message(message_id)
            return True

    async def _show_thinking_after_delay(
        self,
        ctx: Any,
        status: PendingStatus,
        config: MessageReactionSectionConfig,
    ) -> None:
        """延迟显示托腮，并在超时后自动清理。"""
        try:
            await asyncio.sleep(config.thinking_delay_seconds)
            lock = self._locks.setdefault(status.stream_id, asyncio.Lock())
            async with lock:
                if self._pending_statuses.get(status.message_id) is not status:
                    return
                record = self._reaction_records.get(status.message_id)
                if record is not None and record.source.startswith("tool"):
                    self._pending_statuses.pop(status.message_id, None)
                    return
                if record is not None and record.source == "status_success":
                    self._pending_statuses.pop(status.message_id, None)
                    return
                if record is not None and record.emoji_id is not None:
                    removed = await self._set_reaction(
                        ctx,
                        message_id=status.message_id,
                        emoji_id=record.emoji_id,
                        set_like=False,
                        emoji_name=AVAILABLE_REACTION_EMOJIS.get(
                            record.emoji_id,
                            str(record.emoji_id),
                        ),
                    )
                    if not removed:
                        self._pending_statuses.pop(status.message_id, None)
                        return
                self._forget_reacted_message(status.message_id)
                if not await self._set_reaction(
                    ctx,
                    message_id=status.message_id,
                    emoji_id=_THINKING_EMOJI_ID,
                    set_like=True,
                    emoji_name=AVAILABLE_REACTION_EMOJIS[_THINKING_EMOJI_ID],
                ):
                    self._pending_statuses.pop(status.message_id, None)
                    return
                status.thinking_active = True
                self._remember_reacted_message(
                    status.message_id,
                    ReactionRecord(
                        source="status_thinking",
                        emoji_id=_THINKING_EMOJI_ID,
                    ),
                )
            await asyncio.sleep(config.thinking_timeout_seconds)
            await self.finish_status(
                ctx,
                message_id=status.message_id,
                success=False,
                show_success=False,
            )
        except asyncio.CancelledError:
            return

    async def _select_for_target(
        self,
        ctx: Any,
        target: ReactionTarget,
        config: MessageReactionSectionConfig,
        *,
        recent: list[dict[str, Any]] | None = None,
    ) -> tuple[int | None, str]:
        """结合最近上下文为目标消息选择一个允许的反应表情。"""
        if recent is None:
            recent = await self._get_recent_messages(ctx, target.stream_id, limit=10)
        prompt = self._build_selection_prompt(target, recent)
        return await self._select_emoji(ctx, prompt, config.llm_model)

    async def _set_reaction(
        self,
        ctx: Any,
        *,
        message_id: str,
        emoji_id: int,
        set_like: bool,
        emoji_name: str,
    ) -> bool:
        """通过 NapCat Adapter 添加或撤销一条消息反应。"""
        try:
            async with asyncio.timeout(_NAPCAT_TIMEOUT_SECONDS):
                result = await ctx.api.call(
                    "adapter.napcat.message.set_msg_emoji_like",
                    version="1",
                    message_id=message_id,
                    emoji_id=emoji_id,
                    set=set_like,
                )
        except Exception:
            ctx.logger.exception("调用 NapCat 消息贴表情 API 失败")
            return False
        if (
            not isinstance(result, Mapping)
            or str(result.get("status", "")).lower() != "ok"
            or result.get("retcode") != 0
        ):
            ctx.logger.warning("NapCat 拒绝消息贴表情请求")
            return False
        action = "贴上" if set_like else "撤销"
        ctx.logger.info("QQ 群消息反应%s成功: 表情=%s", action, emoji_name)
        return True

    async def _select_emoji(
        self,
        ctx: Any,
        prompt: str,
        configured_model: str,
    ) -> tuple[int | None, str]:
        """要求 LLM 从允许列表中返回一个反应表情。"""
        try:
            async with asyncio.timeout(_LLM_TIMEOUT_SECONDS):
                if configured_model.strip():
                    result = await ctx.llm.generate(
                        prompt,
                        model=configured_model.strip(),
                    )
                else:
                    result = await ctx.llm.generate(prompt)
        except Exception:
            ctx.logger.exception("选择 QQ 消息反应表情时调用 LLM 失败")
            return None, ""

        if isinstance(result, Mapping):
            if result.get("success", True) is not True:
                ctx.logger.warning("选择 QQ 消息反应表情时 LLM 返回失败")
                return None, ""
            content = str(
                result.get("response")
                or result.get("content")
                or result.get("text")
                or ""
            )
        else:
            content = str(result or "")
        try:
            start = content.find("{")
            end = content.rfind("}")
            raw_json = (
                content[start : end + 1] if start >= 0 and end > start else content
            )
            payload = json.loads(raw_json)
            if not isinstance(payload, Mapping):
                raise TypeError("LLM 返回值不是 JSON 对象")
            emoji_id = int(payload.get("emoji_id"))
            emoji_name = AVAILABLE_REACTION_EMOJIS[emoji_id]
        except (TypeError, ValueError, KeyError, json.JSONDecodeError):
            ctx.logger.warning("LLM 未返回有效的 QQ 消息反应表情")
            return None, ""
        return emoji_id, emoji_name

    @staticmethod
    def _build_selection_prompt(
        target: ReactionTarget,
        recent: list[dict[str, Any]],
    ) -> str:
        """构造只允许返回受支持表情 ID 的选择任务。"""
        recent_lines: list[str] = []
        for message in reversed(recent[-10:]):
            message_info = message.get("message_info")
            user_info = (
                message_info.get("user_info")
                if isinstance(message_info, Mapping)
                else None
            )
            sender = "群成员"
            if isinstance(user_info, Mapping):
                sender = str(
                    user_info.get("user_cardname")
                    or user_info.get("user_nickname")
                    or "群成员"
                )
            text = str(message.get("processed_plain_text") or "").replace("\n", " ")[
                :80
            ]
            marker = (
                "（目标消息）"
                if str(message.get("message_id", "")) == target.message_id
                else ""
            )
            if text:
                recent_lines.append(f"{sender}: {text}{marker}")
        context = "\n".join(recent_lines) or "（没有可用的最近文本）"
        choices = "，".join(
            f"{emoji_id}:{name}" for emoji_id, name in AVAILABLE_REACTION_EMOJIS.items()
        )
        return (
            "你正在参与一个 QQ 群聊。请结合目标消息和最近上下文，从允许列表中选择一个最自然、"
            "不过度冒犯的消息反应表情。只输出 JSON，不要输出解释。\n"
            f"目标发送者：{target.sender_name}\n目标消息：{target.content[:120]}\n"
            f"最近上下文：\n{context}\n允许列表：{choices}\n"
            '{"emoji_id": 233, "reason": "十字以内理由"}'
        )

    async def _get_recent_messages(
        self,
        ctx: Any,
        stream_id: str,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        """读取当前聊天流最近消息；失败时安全降级为空列表。"""
        try:
            result = await ctx.message.get_recent(chat_id=stream_id, limit=limit)
        except Exception:
            ctx.logger.exception("读取贴表情目标的最近消息失败")
            return []
        if not isinstance(result, list):
            return []
        return [item for item in result if isinstance(item, dict)]

    @classmethod
    def _target_from_message(
        cls,
        message: Any,
        config: MessageReactionSectionConfig,
    ) -> ReactionTarget | None:
        """从入站 Hook 消息中提取可信 QQ 群目标。"""
        if not isinstance(message, Mapping):
            return None
        if str(message.get("platform", "")).lower() != "qq":
            return None
        if message.get("is_notify") is True or message.get("is_command") is True:
            return None
        stream_id = str(message.get("session_id", "")).strip()
        message_id = str(message.get("message_id", "")).strip()
        content = str(message.get("processed_plain_text") or "").strip()
        if not stream_id or not cls._is_positive_integer(message_id):
            return None
        if len(content) < config.min_text_length:
            return None
        if content.startswith("/"):
            return None

        message_info = message.get("message_info")
        if not isinstance(message_info, Mapping):
            return None
        group_info = message_info.get("group_info")
        user_info = message_info.get("user_info")
        additional = message_info.get("additional_config")
        if not isinstance(group_info, Mapping) or not isinstance(user_info, Mapping):
            return None
        group_id = str(group_info.get("group_id", "")).strip()
        sender_id = str(user_info.get("user_id", "")).strip()
        if not group_id or not sender_id:
            return None
        enabled_groups = cls._normalized_group_ids(config.enabled_group_ids)
        if enabled_groups and group_id not in enabled_groups:
            return None
        if isinstance(additional, Mapping):
            routed_group_id = str(
                additional.get("platform_io_target_group_id", "")
            ).strip()
            self_id = str(additional.get("self_id", "")).strip()
            if routed_group_id and routed_group_id != group_id:
                return None
            if self_id and sender_id == self_id:
                return None
        sender_name = str(
            user_info.get("user_cardname") or user_info.get("user_nickname") or "群成员"
        )
        return ReactionTarget(stream_id, group_id, message_id, sender_name, content)

    @classmethod
    def _target_from_recent(
        cls,
        recent: list[dict[str, Any]],
        *,
        stream_id: str,
        group_id: str,
        target_message_id: str,
    ) -> ReactionTarget | None:
        """只允许 Tool 选择当前流最近列表中的真实消息。"""
        if not cls._is_positive_integer(target_message_id):
            return None
        for message in recent:
            if str(message.get("message_id", "")).strip() != target_message_id:
                continue
            message_info = message.get("message_info")
            group_info = (
                message_info.get("group_info")
                if isinstance(message_info, Mapping)
                else None
            )
            user_info = (
                message_info.get("user_info")
                if isinstance(message_info, Mapping)
                else None
            )
            if not isinstance(group_info, Mapping) or not isinstance(
                user_info, Mapping
            ):
                return None
            if str(group_info.get("group_id", "")).strip() != group_id:
                return None
            sender_name = str(
                user_info.get("user_cardname")
                or user_info.get("user_nickname")
                or "群成员"
            )
            content = str(message.get("processed_plain_text") or "").strip()
            return ReactionTarget(
                stream_id,
                group_id,
                target_message_id,
                sender_name,
                content,
            )
        return None

    def _remember_reacted_message(
        self,
        message_id: str,
        record: ReactionRecord,
    ) -> None:
        """有界保存已处理消息，避免长时间运行时集合无限增长。"""
        if message_id in self._reaction_records:
            self._reaction_records[message_id] = record
            return
        self._reaction_records[message_id] = record
        self._reacted_message_order.append(message_id)
        while len(self._reacted_message_order) > _MAX_TRACKED_MESSAGE_IDS:
            expired = self._reacted_message_order.popleft()
            self._reaction_records.pop(expired, None)

    def _forget_reacted_message(self, message_id: str) -> None:
        """移除消息去重记录，使状态替换可以重新登记。"""
        self._reaction_records.pop(message_id, None)
        try:
            self._reacted_message_order.remove(message_id)
        except ValueError:
            pass

    @staticmethod
    def _looks_reactable(content: str) -> bool:
        text = content.lower()
        return any(keyword in text for keyword in _REACTABLE_KEYWORDS)

    @staticmethod
    def _normalized_group_ids(values: list[str]) -> set[str]:
        return {str(value).strip() for value in values if str(value).strip()}

    @staticmethod
    def _is_positive_integer(value: str) -> bool:
        try:
            return int(value) > 0
        except (TypeError, ValueError):
            return False

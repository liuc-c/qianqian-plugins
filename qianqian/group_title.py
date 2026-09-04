"""QQ 群专属头衔功能。"""

import asyncio
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from maibot_sdk.context import PluginContext

TITLE_COMMAND_PATTERN = r"^头衔[ \u3000]+(?P<title>.+?)[ \u3000]*$"

_ERROR_ADAPTER_UNAVAILABLE = "设置失败：暂时无法连接 QQ 适配器"
_ERROR_INVALID_MESSAGE = "设置失败：无法确认请求消息"
_ERROR_NOT_OWNER = "设置失败：机器人不是当前群群主"
_ERROR_PLATFORM = "设置失败：仅支持 QQ 群聊"
_ERROR_QQ_REJECTED = "设置失败：QQ 拒绝了本次头衔修改"
_ERROR_INVALID_MODE = "设置失败：头衔来源模式无效"
_ERROR_TITLE_MISMATCH = "设置失败：指定头衔与请求原文不一致"
_ERROR_INVALID_TARGET_MODE = "设置失败：成员指定模式无效"
_ERROR_MENTIONED_TARGET = "设置失败：请在请求中只 @ 一位要修改头衔的群成员"
_ERROR_NAMED_TARGET = "设置失败：无法确认指定的群成员，请直接 @ 对方"
_ERROR_AMBIGUOUS_TARGET = (
    "设置失败：找到多位同名群成员，请让用户重新发送消息并 @ 要修改的成员进行二次确认"
)
_ERROR_REQUESTER_NOT_ALLOWED = "设置失败：你没有修改其他成员头衔的权限"
_TOOL_SUCCESS = "群专属头衔设置成功，无需向用户重复确认。"
_MESSAGE_LOOKUP_TIMEOUT_SECONDS = 10
_NAPCAT_TIMEOUT_SECONDS = 20


class TitleMode(StrEnum):
    """Tool 支持的头衔来源。"""

    SPECIFIED = "specified"
    GENERATED = "generated"


class TitleTargetMode(StrEnum):
    """Tool 支持的成员指定方式。"""

    REQUESTER = "requester"
    MENTIONED = "mentioned"
    NAMED = "named"


@dataclass(frozen=True, slots=True)
class _AnchoredRequest:
    """经消息 ID、会话与平台共同校验的头衔请求。"""

    requester_id: str
    message_text: str
    group_id: str
    mentioned_user_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _TitleChangeResult:
    """一次群专属头衔变更的领域结果。"""

    success: bool
    message: str = ""


def _validate_title(value: Any) -> tuple[str, str | None]:
    """规范化头衔，并返回用户可见的校验错误。"""
    if not isinstance(value, str) or any(
        unicodedata.category(character) == "Cc" for character in value
    ):
        return "", "设置失败：头衔内容无效"

    title = value.strip()
    if not title:
        return "", "设置失败：头衔内容无效"

    try:
        title_length = len(title.encode("utf-16-le")) // 2
    except UnicodeEncodeError:
        return "", "设置失败：头衔内容无效"
    if title_length > 6:
        return "", "设置失败：头衔最多只能占 6 个字"
    return title, None


def _extract_anchored_request(
    message: Any,
    *,
    request_message_id: str,
    stream_id: str,
) -> _AnchoredRequest | None:
    """校验锚定消息，并提取请求者、原文、当前群与 At 目标。"""
    if not isinstance(message, Mapping):
        return None
    message_info = message.get("message_info")
    if not isinstance(message_info, Mapping):
        return None
    group_info = message_info.get("group_info")
    user_info = message_info.get("user_info")
    message_text = message.get("processed_plain_text")
    if (
        not isinstance(group_info, Mapping)
        or not isinstance(user_info, Mapping)
        or not isinstance(message_text, str)
    ):
        return None

    requester_id = str(user_info.get("user_id", "")).strip()
    anchored_group_id = str(group_info.get("group_id", "")).strip()
    if (
        not requester_id
        or not anchored_group_id
        or str(message.get("session_id", "")) != stream_id
        or str(message.get("platform", "")).lower() != "qq"
        or str(message.get("message_id", "")) != request_message_id
    ):
        return None
    mentioned_user_ids: list[str] = []
    raw_message = message.get("raw_message")
    if isinstance(raw_message, list):
        for segment in raw_message:
            if not isinstance(segment, Mapping):
                continue
            if str(segment.get("type", "")).strip().lower() != "at":
                continue
            segment_data = segment.get("data")
            if not isinstance(segment_data, Mapping):
                continue
            target_user_id = str(
                segment_data.get("target_user_id", "")
            ).strip()
            if target_user_id and target_user_id not in mentioned_user_ids:
                mentioned_user_ids.append(target_user_id)

    return _AnchoredRequest(
        requester_id=requester_id,
        message_text=message_text,
        group_id=anchored_group_id,
        mentioned_user_ids=tuple(mentioned_user_ids),
    )


class GroupTitleModule:
    """处理头衔 Command、Tool 以及 NapCat 集成。"""

    def __init__(self, ctx: PluginContext) -> None:
        self._ctx = ctx

    async def set_from_command(
        self,
        *,
        stream_id: str,
        group_id: str,
        user_id: str,
        platform: str,
        matched_groups: dict[str, str] | None,
    ) -> tuple[bool, str, int]:
        """把命令中的字面头衔设置给请求者。"""
        stream_id = str(stream_id).strip()
        group_id = str(group_id).strip()
        user_id = str(user_id).strip()
        if (
            str(platform).lower() != "qq"
            or not stream_id
            or not group_id
            or not user_id
        ):
            await self._ctx.send.text(_ERROR_PLATFORM, stream_id)
            return False, _ERROR_PLATFORM, 2

        title, error = _validate_title((matched_groups or {}).get("title", ""))
        if error:
            await self._ctx.send.text(error, stream_id)
            return False, error, 2

        result = await self._change_group_title(
            group_id=group_id,
            requester_id=user_id,
            title=title,
            target_mode=TitleTargetMode.REQUESTER,
        )
        if not result.success:
            await self._ctx.send.text(result.message, stream_id)
            return False, result.message, 2
        return True, "", 2

    async def set_from_tool(
        self,
        *,
        title: str,
        request_message_id: str,
        mode: str,
        target_mode: str = TitleTargetMode.REQUESTER.value,
        target_name: str = "",
        allow_all_members_to_set_others: bool = False,
        allowed_requester_ids: tuple[str, ...] = (),
        stream_id: str,
        chat_id: str,
        platform: str,
    ) -> dict[str, Any]:
        """根据可信请求消息为请求者或指定成员设置群专属头衔。"""
        title, error = _validate_title(title)
        if error:
            return {"success": False, "content": error}

        request_message_id = str(request_message_id).strip()
        stream_id = str(stream_id).strip()
        chat_id = str(chat_id).strip()
        if str(platform).lower() != "qq":
            return {"success": False, "content": _ERROR_PLATFORM}
        if not request_message_id or not stream_id or stream_id != chat_id:
            return {"success": False, "content": _ERROR_INVALID_MESSAGE}

        try:
            async with asyncio.timeout(_MESSAGE_LOOKUP_TIMEOUT_SECONDS):
                message = await self._ctx.message.get_by_id(
                    request_message_id,
                    stream_id=stream_id,
                    include_binary_data=False,
                )
        except Exception:
            self._ctx.logger.exception("查询群专属头衔请求消息失败")
            return {"success": False, "content": _ERROR_INVALID_MESSAGE}

        if (
            isinstance(message, Mapping)
            and str(message.get("platform", "")).strip()
            and str(message.get("platform", "")).lower() != "qq"
        ):
            return {"success": False, "content": _ERROR_PLATFORM}

        anchored_request = _extract_anchored_request(
            message,
            request_message_id=request_message_id,
            stream_id=stream_id,
        )
        if anchored_request is None:
            return {"success": False, "content": _ERROR_INVALID_MESSAGE}
        try:
            title_mode = TitleMode(str(mode).strip().lower())
        except ValueError:
            return {"success": False, "content": _ERROR_INVALID_MODE}
        if (
            title_mode is TitleMode.SPECIFIED
            and title not in anchored_request.message_text
        ):
            return {"success": False, "content": _ERROR_TITLE_MISMATCH}
        try:
            parsed_target_mode = TitleTargetMode(str(target_mode).strip().lower())
        except ValueError:
            return {"success": False, "content": _ERROR_INVALID_TARGET_MODE}

        target_name = str(target_name).strip()
        if parsed_target_mode is TitleTargetMode.NAMED and not target_name:
            return {"success": False, "content": _ERROR_NAMED_TARGET}

        result = await self._change_group_title(
            group_id=anchored_request.group_id,
            requester_id=anchored_request.requester_id,
            title=title,
            target_mode=parsed_target_mode,
            target_name=target_name,
            mentioned_user_ids=anchored_request.mentioned_user_ids,
            allow_all_members_to_set_others=allow_all_members_to_set_others,
            allowed_requester_ids=allowed_requester_ids,
        )
        return {
            "success": result.success,
            "content": _TOOL_SUCCESS if result.success else result.message,
        }

    async def _change_group_title(
        self,
        *,
        group_id: str,
        requester_id: str,
        title: str,
        target_mode: TitleTargetMode,
        target_name: str = "",
        mentioned_user_ids: tuple[str, ...] = (),
        allow_all_members_to_set_others: bool = False,
        allowed_requester_ids: tuple[str, ...] = (),
    ) -> _TitleChangeResult:
        """验证机器人权限、解析目标成员并通过 NapCat 修改头衔。"""
        try:
            async with asyncio.timeout(_NAPCAT_TIMEOUT_SECONDS):
                login_info = await self._ctx.api.call(
                    "adapter.napcat.system.get_login_info",
                    version="1",
                )
                if not isinstance(login_info, Mapping):
                    self._ctx.logger.warning("NapCat 登录信息返回值无效")
                    return _TitleChangeResult(False, _ERROR_ADAPTER_UNAVAILABLE)
                bot_id = str(login_info.get("user_id", "")).strip()
                if not bot_id:
                    self._ctx.logger.warning("NapCat 登录信息缺少机器人 QQ 号")
                    return _TitleChangeResult(False, _ERROR_ADAPTER_UNAVAILABLE)

                member_info = await self._ctx.api.call(
                    "adapter.napcat.group.get_group_member_info",
                    version="1",
                    group_id=group_id,
                    user_id=bot_id,
                    no_cache=True,
                )
                if (
                    not isinstance(member_info, Mapping)
                    or str(member_info.get("group_id", "")) != group_id
                    or str(member_info.get("user_id", "")) != bot_id
                ):
                    self._ctx.logger.warning("NapCat 群成员信息返回值无效")
                    return _TitleChangeResult(False, _ERROR_ADAPTER_UNAVAILABLE)
                if str(member_info.get("role", "")).lower() != "owner":
                    return _TitleChangeResult(False, _ERROR_NOT_OWNER)

                target_id, target_error = await self._resolve_target_id(
                    group_id=group_id,
                    requester_id=requester_id,
                    bot_id=bot_id,
                    target_mode=target_mode,
                    target_name=target_name,
                    mentioned_user_ids=mentioned_user_ids,
                )
                if target_error:
                    return _TitleChangeResult(False, target_error)
                allowed_requesters = {
                    str(user_id).strip()
                    for user_id in allowed_requester_ids
                    if str(user_id).strip()
                }
                if (
                    target_id != requester_id
                    and not allow_all_members_to_set_others
                    and requester_id not in allowed_requesters
                ):
                    return _TitleChangeResult(False, _ERROR_REQUESTER_NOT_ALLOWED)

                set_result = await self._ctx.api.call(
                    "adapter.napcat.group.set_group_special_title",
                    version="1",
                    params={
                        "group_id": group_id,
                        "user_id": target_id,
                        "special_title": title,
                    },
                )
                if (
                    not isinstance(set_result, Mapping)
                    or str(set_result.get("status", "")).lower() != "ok"
                    or set_result.get("retcode") != 0
                ):
                    self._ctx.logger.warning(
                        "QQ 拒绝群专属头衔修改: %r",
                        set_result,
                    )
                    return _TitleChangeResult(False, _ERROR_QQ_REJECTED)
        except Exception:
            self._ctx.logger.exception("调用 NapCat 群专属头衔 API 失败")
            return _TitleChangeResult(False, _ERROR_ADAPTER_UNAVAILABLE)

        return _TitleChangeResult(True)

    async def _resolve_target_id(
        self,
        *,
        group_id: str,
        requester_id: str,
        bot_id: str,
        target_mode: TitleTargetMode,
        target_name: str,
        mentioned_user_ids: tuple[str, ...],
    ) -> tuple[str, str | None]:
        """从锚定消息或当前群成员列表解析唯一目标成员。"""
        if target_mode is TitleTargetMode.REQUESTER:
            return requester_id, None

        if target_mode is TitleTargetMode.MENTIONED:
            if "all" in mentioned_user_ids:
                return "", _ERROR_MENTIONED_TARGET
            target_ids = {
                user_id
                for user_id in mentioned_user_ids
                if user_id and user_id != bot_id
            }
            if len(target_ids) != 1:
                return "", _ERROR_MENTIONED_TARGET
            target_id = target_ids.pop()
            target_info = await self._ctx.api.call(
                "adapter.napcat.group.get_group_member_info",
                version="1",
                group_id=group_id,
                user_id=target_id,
                no_cache=True,
            )
            if (
                not isinstance(target_info, Mapping)
                or str(target_info.get("group_id", "")) != group_id
                or str(target_info.get("user_id", "")) != target_id
            ):
                return "", _ERROR_NAMED_TARGET
            return target_id, None

        non_bot_mentions = {
            user_id
            for user_id in mentioned_user_ids
            if user_id and user_id not in {bot_id, "all"}
        }
        if non_bot_mentions or "all" in mentioned_user_ids:
            return "", _ERROR_MENTIONED_TARGET

        member_list = await self._ctx.api.call(
            "adapter.napcat.group.get_group_member_list",
            version="1",
            group_id=group_id,
            no_cache=True,
        )
        if not isinstance(member_list, list):
            self._ctx.logger.warning("NapCat 群成员列表返回值无效")
            return "", _ERROR_ADAPTER_UNAVAILABLE

        card_matches: set[str] = set()
        nickname_matches: set[str] = set()
        for member in member_list:
            if not isinstance(member, Mapping):
                continue
            user_id = str(member.get("user_id", "")).strip()
            if not user_id:
                continue
            if str(member.get("card", "")).strip() == target_name:
                card_matches.add(user_id)
            if str(member.get("nickname", "")).strip() == target_name:
                nickname_matches.add(user_id)

        if len(card_matches) > 1:
            return "", _ERROR_AMBIGUOUS_TARGET
        if len(card_matches) == 1:
            return card_matches.pop(), None
        if not nickname_matches:
            return "", _ERROR_NAMED_TARGET
        if len(nickname_matches) > 1:
            return "", _ERROR_AMBIGUOUS_TARGET
        return nickname_matches.pop(), None

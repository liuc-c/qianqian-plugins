"""仟仟自用插件。"""

import asyncio
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from maibot_sdk import Command, Field, MaiBotPlugin, PluginConfigBase, Tool
from maibot_sdk.types import ToolParameterInfo, ToolParamType

_GENERATED_TITLE_MARKERS = (
    "随机",
    "随便",
    "帮我想",
    "帮我取",
    "帮我起",
    "给我想",
    "给我取",
    "给我起",
)
_TITLE_DISCUSSION_MARKERS = (
    "是什么意思",
    "什么意思",
    "这个头衔怎么样",
    "什么头衔比较好",
)
_TITLE_AUTHORIZATION_NEGATIONS = ("不要", "别", "不用", "不需要", "不想")

_ERROR_ADAPTER_UNAVAILABLE = "设置失败：暂时无法连接 QQ 适配器"
_ERROR_INVALID_MESSAGE = "设置失败：无法确认请求消息"
_ERROR_NOT_OWNER = "设置失败：机器人不是当前群群主"
_ERROR_PLATFORM = "设置失败：仅支持 QQ 群聊"
_ERROR_QQ_REJECTED = "设置失败：QQ 拒绝了本次头衔修改"
_ERROR_UNAUTHORIZED_TITLE = "设置失败：请求消息未明确授权该头衔"
_TOOL_SUCCESS = "群专属头衔设置成功，无需向用户重复确认。"
_MESSAGE_LOOKUP_TIMEOUT_SECONDS = 10
_NAPCAT_TIMEOUT_SECONDS = 20


class _TitleMode(StrEnum):
    """Tool 支持的头衔来源。"""

    SPECIFIED = "specified"
    GENERATED = "generated"


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


def _extract_anchored_requester(
    message: Any,
    *,
    request_message_id: str,
    stream_id: str,
) -> tuple[str, str, str] | None:
    """校验锚定消息，并提取请求者、原文与当前群。"""
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
    return requester_id, message_text, anchored_group_id


def _is_title_authorized(title: str, mode: _TitleMode, message_text: str) -> bool:
    """判断原消息是否授权设置指定或生成的头衔。"""
    if any(
        marker in message_text
        for marker in (*_TITLE_AUTHORIZATION_NEGATIONS, *_TITLE_DISCUSSION_MARKERS)
    ):
        return False
    if mode is _TitleMode.SPECIFIED:
        return title in message_text
    if mode is _TitleMode.GENERATED:
        return "头衔" in message_text and any(
            marker in message_text for marker in _GENERATED_TITLE_MARKERS
        )
    return False


class PluginSectionConfig(PluginConfigBase):
    """插件基础配置。"""

    __ui_label__ = "插件"
    __ui_icon__ = "paw-print"
    __ui_order__ = 0

    enabled: bool = Field(default=False, description="是否启用插件")
    config_version: str = Field(default="0.2.0", description="配置版本")


class QianqianPluginConfig(PluginConfigBase):
    """仟仟自用插件配置。"""

    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)


class QianqianPlugin(MaiBotPlugin):
    """为仟仟提供自用命令与工具。"""

    config_model = QianqianPluginConfig

    async def on_load(self) -> None:
        """插件加载时执行。"""
        self.ctx.logger.info("仟仟自用插件已加载")

    async def on_unload(self) -> None:
        """插件卸载时执行。"""
        self.ctx.logger.info("仟仟自用插件已卸载")

    async def on_config_update(
        self,
        scope: str,
        config_data: dict[str, Any],
        version: str,
    ) -> None:
        """配置热重载时执行。"""
        del scope
        del config_data
        del version

    async def _change_group_title(
        self,
        *,
        group_id: str,
        requester_id: str,
        title: str,
    ) -> _TitleChangeResult:
        """通过 NapCat Adapter 修改请求者的群专属头衔。"""
        try:
            async with asyncio.timeout(_NAPCAT_TIMEOUT_SECONDS):
                login_info = await self.ctx.api.call(
                    "adapter.napcat.system.get_login_info",
                    version="1",
                )
                if not isinstance(login_info, Mapping):
                    self.ctx.logger.warning("NapCat 登录信息返回值无效")
                    return _TitleChangeResult(False, _ERROR_ADAPTER_UNAVAILABLE)
                bot_id = str(login_info.get("user_id", "")).strip()
                if not bot_id:
                    self.ctx.logger.warning("NapCat 登录信息缺少机器人 QQ 号")
                    return _TitleChangeResult(False, _ERROR_ADAPTER_UNAVAILABLE)

                member_info = await self.ctx.api.call(
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
                    self.ctx.logger.warning("NapCat 群成员信息返回值无效")
                    return _TitleChangeResult(False, _ERROR_ADAPTER_UNAVAILABLE)
                if str(member_info.get("role", "")).lower() != "owner":
                    return _TitleChangeResult(False, _ERROR_NOT_OWNER)

                set_result = await self.ctx.api.call(
                    "adapter.napcat.group.set_group_special_title",
                    version="1",
                    params={
                        "group_id": group_id,
                        "user_id": requester_id,
                        "special_title": title,
                    },
                )
                if (
                    not isinstance(set_result, Mapping)
                    or str(set_result.get("status", "")).lower() != "ok"
                    or set_result.get("retcode") != 0
                ):
                    self.ctx.logger.warning("QQ 拒绝群专属头衔修改: %r", set_result)
                    return _TitleChangeResult(False, _ERROR_QQ_REJECTED)
        except Exception:
            self.ctx.logger.exception("调用 NapCat 群专属头衔 API 失败")
            return _TitleChangeResult(False, _ERROR_ADAPTER_UNAVAILABLE)

        return _TitleChangeResult(True)

    @Tool(
        "qianqian_set_group_title",
        brief_description="在用户明确要求时，为该用户设置当前 QQ 群的群专属头衔",
        detailed_description=(
            "这是会修改 QQ 群成员资料的有副作用工具。仅当用户明确要求设置自己的群专属头衔，"
            "或明确授权你取一个头衔并立即设置时调用；讨论、询问建议或替他人设置时不要调用。"
            "request_message_id 必须复制明确设置请求所在 <message> 的 msg_id。"
        ),
        parameters=[
            ToolParameterInfo(
                name="title",
                param_type=ToolParamType.STRING,
                description="要设置的头衔，最多占 6 个字",
                required=True,
            ),
            ToolParameterInfo(
                name="request_message_id",
                param_type=ToolParamType.STRING,
                description="明确提出设置请求的原消息 msg_id",
                required=True,
            ),
            ToolParameterInfo(
                name="mode",
                param_type=ToolParamType.STRING,
                description="specified 表示用户指定原文；generated 表示用户授权生成",
                required=True,
                enum_values=[mode.value for mode in _TitleMode],
            ),
        ],
    )
    async def set_group_title_tool(
        self,
        title: str,
        request_message_id: str,
        mode: str,
        stream_id: str = "",
        chat_id: str = "",
        group_id: str = "",
        platform: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """根据可信请求消息为请求者设置群专属头衔。"""
        # 当前群必须由锚定消息派生，不能信任 Tool 调用载荷中的同名字段。
        del group_id
        del kwargs
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
                message = await self.ctx.message.get_by_id(
                    request_message_id,
                    stream_id=stream_id,
                    include_binary_data=False,
                )
        except Exception:
            self.ctx.logger.exception("查询群专属头衔请求消息失败")
            return {"success": False, "content": _ERROR_INVALID_MESSAGE}

        if (
            isinstance(message, Mapping)
            and str(message.get("platform", "")).strip()
            and str(message.get("platform", "")).lower() != "qq"
        ):
            return {"success": False, "content": _ERROR_PLATFORM}

        anchored_request = _extract_anchored_requester(
            message,
            request_message_id=request_message_id,
            stream_id=stream_id,
        )
        if anchored_request is None:
            return {"success": False, "content": _ERROR_INVALID_MESSAGE}
        requester_id, message_text, anchored_group_id = anchored_request
        try:
            title_mode = _TitleMode(str(mode).strip().lower())
        except ValueError:
            return {"success": False, "content": _ERROR_UNAUTHORIZED_TITLE}
        if not _is_title_authorized(title, title_mode, message_text):
            return {"success": False, "content": _ERROR_UNAUTHORIZED_TITLE}

        result = await self._change_group_title(
            group_id=anchored_group_id,
            requester_id=requester_id,
            title=title,
        )
        return {
            "success": result.success,
            "content": _TOOL_SUCCESS if result.success else result.message,
        }

    @Command(
        "qianqian_set_group_title_command",
        description="为命令发送者设置 QQ 群专属头衔",
        pattern=r"^头衔[ \u3000]+(?P<title>.+?)[ \u3000]*$",
    )
    async def set_group_title_command(
        self,
        stream_id: str = "",
        group_id: str = "",
        user_id: str = "",
        platform: str = "",
        matched_groups: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> tuple[bool, str, int]:
        """把命令中的字面头衔设置给请求者。"""
        del kwargs
        stream_id = str(stream_id).strip()
        group_id = str(group_id).strip()
        user_id = str(user_id).strip()
        if (
            str(platform).lower() != "qq"
            or not stream_id
            or not group_id
            or not user_id
        ):
            await self.ctx.send.text(_ERROR_PLATFORM, stream_id)
            return False, _ERROR_PLATFORM, 2

        title, error = _validate_title((matched_groups or {}).get("title", ""))
        if error:
            await self.ctx.send.text(error, stream_id)
            return False, error, 2

        result = await self._change_group_title(
            group_id=group_id,
            requester_id=user_id,
            title=title,
        )
        if not result.success:
            await self.ctx.send.text(result.message, stream_id)
            return False, result.message, 2
        return True, "", 2


def create_plugin() -> QianqianPlugin:
    """创建插件实例。"""
    return QianqianPlugin()

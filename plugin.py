"""仟仟自用插件入口。"""

from collections.abc import Mapping
from typing import Any, cast

from maibot_sdk import Command, HookHandler, MaiBotPlugin, Tool
from maibot_sdk.types import HookMode, ToolParameterInfo, ToolParamType

from qianqian.config import QianqianPluginConfig
from qianqian.group_title import (
    TITLE_COMMAND_PATTERN,
    GroupTitleModule,
    TitleMode,
)
from qianqian.repeater import RepeaterModule


class QianqianPlugin(MaiBotPlugin):
    """组合仟仟使用的 QQ 群功能模块。"""

    config_model = QianqianPluginConfig

    def __init__(self) -> None:
        super().__init__()
        self._repeater = RepeaterModule()

    async def on_load(self) -> None:
        """插件加载时执行。"""
        self.ctx.logger.info("仟仟自用插件已加载")

    async def on_unload(self) -> None:
        """插件卸载时执行。"""
        self._repeater.clear()
        self.ctx.logger.info("仟仟自用插件已卸载")

    async def on_config_update(
        self,
        scope: str,
        config_data: dict[str, Any],
        version: str,
    ) -> None:
        """配置热重载时清空短期复读状态。"""
        self._repeater.clear()
        del scope
        del config_data
        del version

    @HookHandler(
        "chat.receive.after_process",
        name="qianqian_repeater",
        description="识别 QQ 群复读队列并按配置概率原样参与",
        mode=HookMode.BLOCKING,
    )
    async def handle_repeater_message(self, **kwargs: Any) -> dict[str, Any]:
        """处理一条预处理后的群消息。"""
        config = cast(QianqianPluginConfig, self.config).repeater
        output = await self._repeater.evaluate(kwargs.get("message"), config)
        if output is None:
            return {"action": "continue", "modified_kwargs": kwargs}

        try:
            if output.segments is None:
                sent = await self.ctx.send.text(output.text, output.stream_id)
            else:
                sent = await self.ctx.send.hybrid(
                    output.segments,
                    output.stream_id,
                )
        except Exception:
            self.ctx.logger.exception("发送 QQ 群复读消息失败")
            return {"action": "continue", "modified_kwargs": kwargs}

        succeeded = (
            sent.get("sent") is True if isinstance(sent, Mapping) else sent is True
        )
        if not succeeded:
            self.ctx.logger.warning("发送 QQ 群复读消息失败")
            return {"action": "continue", "modified_kwargs": kwargs}
        return {"action": "abort"}

    @Tool(
        "qianqian_set_group_title",
        brief_description="执行用户明确授权的本人 QQ 群专属头衔设置",
        detailed_description=(
            "触发：当前 QQ 群用户明确要求设置自己的群专属头衔，或明确让你随机、构思或起一个"
            "头衔；后一种请求视为授权立即设置。"
            "选择：用户给出最终文本时使用 specified；用户把选名权交给你时使用 generated，可以"
            "参考当前对话。"
            "锚定：从承载这次明确请求的用户 <message> 逐字复制 msg_id；该消息决定请求者和当前群。"
            "完成：只调用一次；success=true 即完成，无需再次调用或重复确认；success=false 时依据"
            " content 告知用户失败。"
            "边界：仅讨论头衔、只征求建议而未授权立即设置、含糊表达或替他人设置均不触发。"
        ),
        parameters=[
            ToolParameterInfo(
                name="title",
                param_type=ToolParamType.STRING,
                description=(
                    "最终写入的头衔，限 1～6 个 UTF-16 单元；specified 时逐字复制请求原文，"
                    "generated 时根据用户授权生成"
                ),
                required=True,
            ),
            ToolParameterInfo(
                name="request_message_id",
                param_type=ToolParamType.STRING,
                description=(
                    "承载本次明确设置请求的用户 <message> 的 msg_id，逐字复制该值"
                ),
                required=True,
            ),
            ToolParameterInfo(
                name="mode",
                param_type=ToolParamType.STRING,
                description=(
                    "specified：用户已给出最终头衔；generated：用户明确让你随机、构思或起名，"
                    "并把选名权交给你"
                ),
                required=True,
                enum_values=[mode.value for mode in TitleMode],
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
        """把 Tool 请求委托给头衔模块。"""
        del group_id
        del kwargs
        return await GroupTitleModule(self.ctx).set_from_tool(
            title=title,
            request_message_id=request_message_id,
            mode=mode,
            stream_id=stream_id,
            chat_id=chat_id,
            platform=platform,
        )

    @Command(
        "qianqian_set_group_title_command",
        description="为命令发送者设置 QQ 群专属头衔",
        pattern=TITLE_COMMAND_PATTERN,
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
        """把 Command 请求委托给头衔模块。"""
        del kwargs
        return await GroupTitleModule(self.ctx).set_from_command(
            stream_id=stream_id,
            group_id=group_id,
            user_id=user_id,
            platform=platform,
            matched_groups=matched_groups,
        )


def create_plugin() -> QianqianPlugin:
    """创建插件实例。"""
    return QianqianPlugin()

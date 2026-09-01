"""仟仟自用插件。"""

from typing import Any

from maibot_sdk import Command, Field, MaiBotPlugin, PluginConfigBase, Tool
from maibot_sdk.types import ToolParameterInfo, ToolParamType


class PluginSectionConfig(PluginConfigBase):
    """插件基础配置。"""

    __ui_label__ = "插件"
    __ui_icon__ = "paw-print"
    __ui_order__ = 0

    enabled: bool = Field(default=False, description="是否启用插件")
    config_version: str = Field(default="0.1.0", description="配置版本")


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

    @Tool(
        "qianqian_echo_text",
        description="复述用户提供的文本，用于测试仟仟自用插件能否被 LLM 正常调用。",
        parameters=[
            ToolParameterInfo(
                name="text",
                param_type=ToolParamType.STRING,
                description="要复述的文本",
                required=True,
            ),
        ],
    )
    async def echo_text(self, text: str, **kwargs: Any) -> dict[str, str]:
        """原样返回指定文本。"""
        del kwargs
        return {"content": text}

    @Command(
        "qianqian_ping",
        description="测试仟仟自用插件是否在线",
        pattern=r"^/qianqian-ping$",
    )
    async def ping(
        self,
        stream_id: str = "",
        **kwargs: Any,
    ) -> tuple[bool, str, int]:
        """回复 pong，确认命令链路正常。"""
        del kwargs
        await self.ctx.send.text("pong", stream_id)
        return True, "pong", 2


def create_plugin() -> QianqianPlugin:
    """创建插件实例。"""
    return QianqianPlugin()

"""插件配置模型。"""

from maibot_sdk import Field, PluginConfigBase


class PluginSectionConfig(PluginConfigBase):
    """插件基础配置。"""

    __ui_label__ = "插件"
    __ui_icon__ = "paw-print"
    __ui_order__ = 0

    enabled: bool = Field(default=False, description="是否启用插件")
    config_version: str = Field(default="0.3.0", description="配置版本")


class RepeaterSectionConfig(PluginConfigBase):
    """QQ 群复读配置。"""

    __ui_label__ = "群复读"
    __ui_icon__ = "repeat-2"
    __ui_order__ = 10

    enabled: bool = Field(default=False, description="是否启用 QQ 群复读")
    repeat_probability: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="每条复读队列的参与概率",
    )
    enabled_group_ids: list[str] = Field(
        default_factory=list,
        description="允许复读的 QQ 群号；留空表示全部群",
    )


class QianqianPluginConfig(PluginConfigBase):
    """仟仟自用插件配置。"""

    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)
    repeater: RepeaterSectionConfig = Field(default_factory=RepeaterSectionConfig)

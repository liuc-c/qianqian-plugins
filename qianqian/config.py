"""插件配置模型。"""

from maibot_sdk import Field, PluginConfigBase


DEFAULT_EMOJI_INSTRUCTION = (
    "在纯情绪回应，或文字回复后确实需要额外加强语气时，可以主动使用表情包。"
    "表情内容使用简短的情绪或画面描述，例如“开心”“无语”“疑惑”“笑哭”。"
    "不必每次使用，每轮最多一个，避免连续刷屏，但也不要长期完全不用。"
)


class PluginSectionConfig(PluginConfigBase):
    """插件基础配置。"""

    __ui_label__ = "插件"
    __ui_icon__ = "paw-print"
    __ui_order__ = 0

    enabled: bool = Field(default=False, description="是否启用插件")
    config_version: str = Field(default="0.5.1", description="配置版本")


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


class MessageReactionSectionConfig(PluginConfigBase):
    """QQ 群消息反应配置。"""

    __ui_label__ = "消息贴表情"
    __ui_icon__ = "smile-plus"
    __ui_order__ = 15

    enabled: bool = Field(default=False, description="是否启用消息贴表情功能")
    proactive_enabled: bool = Field(
        default=True,
        description="是否在普通群聊消息中按概率主动贴表情",
    )
    status_enabled: bool = Field(
        default=True,
        description="是否用托腮和 OK 展示 Planner 回复及头衔任务状态",
    )
    thinking_delay_seconds: float = Field(
        default=1.5,
        ge=0.0,
        description="Planner 决定回复或执行任务后，延迟显示托腮的秒数",
    )
    thinking_timeout_seconds: int = Field(
        default=120,
        ge=1,
        description="托腮状态的最长保留秒数，超时后自动撤销",
    )
    normal_probability: float = Field(
        default=0.4,
        ge=0.0,
        le=1.0,
        description="普通消息主动贴表情概率",
    )
    keyword_probability: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        description="明显适合回应的消息主动贴表情概率",
    )
    cooldown_seconds: int = Field(
        default=180,
        ge=0,
        description="同一聊天流主动贴表情成功后的冷却秒数",
    )
    min_text_length: int = Field(
        default=2,
        ge=0,
        description="主动贴表情所需的最短消息文本长度",
    )
    enabled_group_ids: list[str] = Field(
        default_factory=list,
        description="允许贴表情的 QQ 群号；留空表示全部 QQ 群",
    )
    llm_model: str = Field(
        default="planner",
        description="选择反应表情使用的模型任务或模型名称；留空使用系统默认模型",
    )


class PlannerEngagementSectionConfig(PluginConfigBase):
    """Planner 语音与表情包活跃度提示配置。"""

    __ui_label__ = "Planner 活跃提示"
    __ui_icon__ = "message-circle-more"
    __ui_order__ = 20

    enabled: bool = Field(
        default=False,
        description="是否增强 Planner 的语音和表情包使用提示",
    )
    enabled_group_ids: list[str] = Field(
        default_factory=list,
        description="应用提示的 QQ 群号；留空表示全部 QQ 群",
    )
    voice_instruction: str = Field(
        default=(
            "在问候、撒娇、安慰、讲故事、情绪鲜明或适合口语表达的场景中，可以主动使用"
            " send_voice_reply，不必等待用户明确要求。语音应简短自然，不连续多次使用；发送"
            "语音后不要再发送内容重复的文字回复。"
        ),
        description="追加到 send_voice_reply 工具描述中的 Planner 指令",
    )
    emoji_instruction: str = Field(
        default=DEFAULT_EMOJI_INSTRUCTION,
        description="追加到当前可用表情包工具中的使用时机与频率指令",
    )


class GroupTitleSectionConfig(PluginConfigBase):
    """QQ 群专属头衔配置。"""

    __ui_label__ = "群专属头衔"
    __ui_icon__ = "badge"
    __ui_order__ = 5

    allow_all_members_to_set_others: bool = Field(
        default=False,
        description="是否允许所有群成员请求修改其他成员的头衔",
    )
    allowed_requester_ids: list[str] = Field(
        default_factory=list,
        description="允许请求修改他人头衔的 QQ 号；修改本人不受此项限制",
    )


class QianqianPluginConfig(PluginConfigBase):
    """仟仟自用插件配置。"""

    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)
    group_title: GroupTitleSectionConfig = Field(
        default_factory=GroupTitleSectionConfig
    )
    repeater: RepeaterSectionConfig = Field(default_factory=RepeaterSectionConfig)
    message_reaction: MessageReactionSectionConfig = Field(
        default_factory=MessageReactionSectionConfig
    )
    planner_engagement: PlannerEngagementSectionConfig = Field(
        default_factory=PlannerEngagementSectionConfig
    )

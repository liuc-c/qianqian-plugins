# 🐾 仟仟自用插件

一个基于 `maibot-plugin-sdk` 的 MaiBot 自用插件，为 QQ 群提供本人或指定成员专属头衔设置、轻量概率复读、消息贴表情和 Planner 活跃提示。

## 功能

- Command：发送 `头衔 <内容>`，把字面内容设置为发送者自己的群专属头衔。
- Tool：用户明确要求设置本人或一位指定群成员的头衔时，由 LLM 调用 `qianqian_set_group_title`；用户也可以明确授权 LLM 取一个头衔并立即设置。
- 安全锚定：Tool 根据请求消息的 `msg_id` 查询原消息，从原消息取得当前群、请求者与结构化 At；LLM 不能提供或猜测成员 QQ 号和群号。
- 成员解析：优先使用唯一 At；未 At 目标时可按当前群的群昵称或 QQ 昵称精确查找，只有唯一匹配才执行。
- 群主校验：仅当机器人 QQ 是当前群群主时执行。
- 群复读：两个不同成员连续发送严格相同的文本、Unicode Emoji 或可发送 QQ 表情后，机器人按配置概率原样参与一次。
- LLM 分流：仅在复读消息确认发送成功后截断触发消息的常规 Command、Planner 和 LLM 流程；其他情况正常放行。
- 消息贴表情：LLM 可以调用 `qianqian_msg_react` 给当前群最近消息添加 QQ 反应表情；也可以在普通群聊中按概率旁路主动贴表情。
- 回复状态：Planner 确定回复或设置头衔后，耗时超过阈值才显示“托腮”；普通回复发送后撤销，头衔设置成功后替换为 OK。
- Planner 活跃提示：按 QQ 群增强 `send_voice_reply` 和 `reply.attach_emoji` 的工具说明，让 Planner 更主动地使用语音回复和回复附带表情包。

## 前置条件

- MaiBot Host `1.2.3`～`1.x`
- `maibot-plugin-sdk` `2.5.1`～`2.x`
- [MaiBot NapCat Adapter](https://github.com/MaiM-with-u/MaiBot-Napcat-Adapter) `1.2.0`～`1.x`
- 运行 NapCat 的机器人 QQ 必须是当前群群主

本插件把 NapCat Adapter 声明为硬依赖；缺少适配器或版本不兼容时，MaiBot 会阻止插件加载。

## 安装

在 MaiBot 根目录执行：

```bash
git clone https://github.com/liuc-c/qianqian-plugins.git plugins/qianqian-plugins
```

随后启动或重启 MaiBot。Runner 会自动发现插件，并依据 `plugin.py` 中的 `config_model` 生成本地 `config.toml`。

## 启用与配置

在 MaiBot WebUI 的插件管理中找到“仟仟自用插件”，打开“是否启用插件”。

| 分组 | 配置项 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `plugin` | `enabled` | `false` | 是否启用插件 |
| `plugin` | `config_version` | `0.5.0` | 配置结构版本 |
| `group_title` | `allow_all_members_to_set_others` | `false` | 是否允许所有群成员请求修改其他成员头衔 |
| `group_title` | `allowed_requester_ids` | `[]` | 可请求修改他人头衔的 QQ 号；修改本人不受限制 |
| `repeater` | `enabled` | `false` | 是否单独启用 QQ 群复读 |
| `repeater` | `repeat_probability` | `0.5` | 每条复读队列的参与概率，范围 `0.0～1.0` |
| `repeater` | `enabled_group_ids` | `[]` | 允许复读的群号；空列表表示全部 QQ 群 |
| `message_reaction` | `enabled` | `false` | 是否启用 Tool、主动贴表情和回复状态 |
| `message_reaction` | `proactive_enabled` | `true` | 是否旁路观察普通群消息并主动贴表情 |
| `message_reaction` | `status_enabled` | `true` | 是否用托腮和 OK 展示回复及头衔任务状态 |
| `message_reaction` | `thinking_delay_seconds` | `1.5` | Planner 决定处理后延迟显示托腮的秒数 |
| `message_reaction` | `thinking_timeout_seconds` | `120` | 托腮最长保留秒数，超时自动撤销 |
| `message_reaction` | `normal_probability` | `0.4` | 普通消息触发概率，范围 `0.0～1.0` |
| `message_reaction` | `keyword_probability` | `0.75` | 明显适合互动的消息触发概率，范围 `0.0～1.0` |
| `message_reaction` | `cooldown_seconds` | `180` | 同一聊天流成功贴表情后的冷却秒数 |
| `message_reaction` | `min_text_length` | `2` | 主动贴表情所需的最短文本长度 |
| `message_reaction` | `enabled_group_ids` | `[]` | 允许贴表情的群号；空列表表示全部 QQ 群 |
| `message_reaction` | `llm_model` | `planner` | 选择反应表情使用的模型任务或模型名称；空值使用系统默认模型 |
| `planner_engagement` | `enabled` | `false` | 是否增强 Planner 的语音和表情包提示 |
| `planner_engagement` | `enabled_group_ids` | `[]` | 应用提示的群号；空列表表示全部 QQ 群 |
| `planner_engagement` | `voice_instruction` | 见默认配置 | 追加到 `send_voice_reply` 工具描述的指令 |
| `planner_engagement` | `emoji_instruction` | 见默认配置 | 追加到 `reply.attach_emoji` 的指令 |

`config.toml` 是当前安装实例的运行时配置，不应提交到 Git。

如果只希望在一个群启用新增能力，可使用以下运行时配置；请把示例群号替换为真实 QQ 群号：

```toml
[message_reaction]
enabled = true
proactive_enabled = true
status_enabled = true
thinking_delay_seconds = 1.5
thinking_timeout_seconds = 120
normal_probability = 0.4
keyword_probability = 0.75
cooldown_seconds = 180
min_text_length = 2
enabled_group_ids = ["123456789"]
llm_model = "planner"

[planner_engagement]
enabled = true
enabled_group_ids = ["123456789"]
voice_instruction = "在问候、撒娇、安慰、讲故事、情绪鲜明或适合口语表达的场景中，可以主动使用 send_voice_reply，不必等待用户明确要求。语音应简短自然，不连续多次使用；发送语音后不要再发送内容重复的文字回复。"
emoji_instruction = "当文字回复适合用表情包加强情绪时，可以主动填写 attach_emoji，内容使用简短的情绪或表情描述，例如‘开心’‘无语’‘疑惑’‘笑哭’。不必每次使用，但不要长期完全不用。"
```

## 使用方式

### Command

发送：

```text
头衔 盐田皇帝
```

规则：

- `头衔` 与内容之间必须有一个或多个空格。
- 内容两端空白会被裁掉；`头衔盐田皇帝` 不会触发。
- Command 始终按字面设置，例如 `头衔 随机` 会把头衔设置成“随机”。
- 设置成功后保持静默；失败时发送简体中文错误。

### LLM Tool

以下是明确授权，可以调用 Tool：

```text
把我的头衔设置成盐田皇帝
随机给我设置一个头衔
帮我想一个头衔
@方仟仟 给 @箫阮阮 改头衔为拉屎大王
@方仟仟 给箫阮阮改头衔为拉屎大王
```

以下只是讨论，不应调用 Tool：

```text
你觉得什么头衔比较好？
盐田皇帝这个头衔怎么样？
```

对于用户指定的头衔，Tool 会检查标题原文确实存在于请求消息中。对于生成的头衔，是否获得授权由 LLM 根据 Tool 描述和对话语义判断；插件运行时不维护触发词、否定词或问句白名单。

指定其他成员时有两种安全路径：

- `@目标成员`：插件读取锚定消息里的结构化 At，排除机器人后必须恰好只有一位成员。
- 只写成员名称、简称或群内称呼：LLM 可结合当前对话、记忆或黑话理解成规范成员名；插件再无缓存查询当前群成员列表，先精确匹配群昵称，再以 QQ 昵称兜底。
- 只有一个精确匹配时直接修改；找不到时要求直接 `@` 对方；同名多人时本次不执行，并要求用户重新发送请求、`@` 唯一目标成员完成二次确认。

修改他人头衔默认关闭。建议把可信用户的 QQ 号加入 `group_title.allowed_requester_ids`；只有确实希望全群都能使用时，才打开 `group_title.allow_all_members_to_set_others`。这两项只控制“替别人修改”，不会影响用户修改自己的头衔。

不 `@` 机器人、只写“方仟仟”或“群主”等机器人昵称/别名时，只要 MaiBot 本轮决定处理并让 LLM 调用 Tool，昵称指定仍可执行；但普通文本能否唤醒 Planner 由 MaiBot 的回复触发与人格配置决定，本插件不保证必回复。`@机器人` 是更稳定的触发方式。

Tool 还会要求 Host 注入的 `stream_id` 与 `chat_id` 一致，并只在该聊天流内查询请求消息。MaiBot Host 1.x 目前把上下文字段作为调用参数的缺省值注入，没有向插件提供不可覆盖的只读调用上下文；因此插件可以关闭常见的跨流误选，但绝对的 Host 级强绑定仍需 MaiBot 主程序支持。

### QQ 群复读

在 WebUI 中单独启用“群复读”后，两名不同成员连续发送完全相同的内容即可形成复读队列：

```text
甲：好耶🎉
乙：好耶🎉
仟仟：好耶🎉  # 按 repeat_probability 抽中时发送
```

规则：

- 每条队列只在首次达到两名不同成员时抽签一次，同一队列最多复读一次。
- 同一成员重复发送不会增加人数；`甲、甲、乙` 连续发送相同内容时，在乙发言后达到门槛。
- 文本逐字比较，不裁剪空白、不忽略大小写，也不使用 LLM 判断相似内容。
- 相邻相同消息超过 120 秒会重新建立队列，超过 100 个 Unicode 字符的消息不参与。
- 支持文本、Unicode Emoji，以及包含有效二进制数据且当前 NapCat/Host 可以重新发送的 QQ 表情。
- 命令、At、图片、回复引用、合并转发及其他富媒体消息不参与，并会结束当前队列。
- 只有确认复读消息发送成功才拦截触发消息的后续处理；未触发、未抽中、发送失败或抛出异常时均正常放行。
- 状态只保存在内存中，插件重载、禁用或 MaiBot 重启后清空。

### QQ 消息贴表情

消息贴表情与发送表情包是两套能力：

- `qianqian_msg_react` 和主动贴表情会调用 NapCat 的 `set_msg_emoji_like`，把小表情显示在某条群消息下方。
- `reply.attach_emoji` 会随机器人的文字回复发送一张表情包图片。

主动贴表情订阅 MaiBot 1.x 实际发射的 `chat.receive.after_process` Hook，并使用 `OBSERVE` 旁路模式，因此不会中止或延迟正常 Command、Planner 与 LLM 流程。一次成功后才开始计算冷却；插件重载或重启会清空内存中的冷却和去重状态。

Tool 只能选择当前群最近消息列表中真实存在的消息 ID。目标不在当前群最近消息、消息 ID 无效、LLM 返回不支持的表情或 NapCat 拒绝请求时，插件不会尝试跨群发送。

回复状态读取 Planner 返回的结构化 Tool 调用，不依赖关键词猜测。具体规则：

- Planner 选择普通 `reply` 后，超过 `thinking_delay_seconds` 仍未发送才在目标消息上贴“托腮”；发送成功或失败后都撤销，不贴 OK。
- Planner 选择 `qianqian_set_group_title` 后采用同样的延迟；设置成功时撤销托腮并贴 OK，失败时只撤销托腮，原有文字错误说明保持不变。
- 在延迟内完成的普通回复不显示任何状态；在延迟内成功的头衔任务只贴 OK，不会闪烁托腮。
- 状态最多保留 `thinking_timeout_seconds`，插件重载或卸载也会主动清理；状态反应与主动贴表情共享去重，同一请求不会由本插件叠加多个反应。

### Planner 语音与表情包提示

群专属 `chat_prompts` 在当前 MaiBot 1.2.4 中主要进入 Replyer，无法稳定影响 Planner 对工具的选择。本插件改在 `maisaka.planner.before_request` 修改本轮工具定义：

- 为 `send_voice_reply` 追加主动使用语音的提示；未安装或未启用对应语音插件时不会创建这个工具。
- 为 `reply.attach_emoji` 追加主动附带表情包的提示；需要保持 MaiBot 的丰富回复功能开启。
- 只修改 `enabled_group_ids` 匹配的 QQ 群；不改全局人格、不写回聊天历史，也不修改 MaiBot 主程序文件。

提示只提高 LLM 选择概率，不保证每轮一定使用。语音合成能否成功仍取决于语音插件自身的 API Key、音色模式和服务状态；表情包发送则要求 MaiBot 表情库中存在可用表情。

## 限制与失败行为

- 仅支持 NapCat 接入的 QQ 群聊。
- Tool 可以修改请求者本人或当前群内一位明确指定的成员；Command `头衔 <内容>` 仍只修改发送者本人，不能指定其他群。
- 默认只有 `allowed_requester_ids` 中的请求者能修改他人；开启 `allow_all_members_to_set_others` 后，当前群任何能让 LLM 接受其明确请求的成员都可能请求修改别人头衔。
- 不提供清除头衔功能。
- 头衔最多占 6 个 UTF-16 单元：普通字符通常占 1，常见 Emoji 通常占 2；最终仍以 QQ 接受结果为准。
- 没有调用冷却时间。
- 复读功能仅支持 QQ 群聊，不提供单条消息随机偷句、群内管理命令或状态持久化。
- 主动贴表情只处理带非空文本且长度达到阈值的普通 QQ 群消息；图片、空消息和无法确认来源的消息不会触发。
- 主动贴表情每次需要一次 LLM 选择，会产生相应模型调用；概率越高、冷却越短，调用量越大。
- 回复状态目前准确跟踪 MaiBot 内置 `reply` 和本插件的头衔 Tool；其他第三方 Tool 是否会发送消息没有统一契约，因此不会自动贴状态。
- Planner 活跃提示是软指令，不能把语音或表情包变成确定性概率事件。
- NapCat 把部分 QQ 原生表情降级为文字时，插件只能按收到的文字复读；表情缺少有效二进制数据时整条消息不参与。
- 机器人不是群主时提示：`设置失败：机器人不是当前群群主`。
- 适配器不可用、消息锚定失败或 QQ 拒绝修改时，会返回简洁错误；技术细节只写入插件日志。

## 权限与依赖

| 类型 | 声明 | 用途 |
| --- | --- | --- |
| Capability | `api.call` | 调用 NapCat Adapter 的公开 API |
| Capability | `chat.get_group_streams` | 把 Planner 的内部聊天流 ID 安全映射为 QQ 群号 |
| Capability | `llm.generate` | 从允许列表中选择合适的 QQ 消息反应表情 |
| Capability | `message.get_by_id` | Tool 根据请求消息 ID 取得可信发送者 |
| Capability | `message.get_recent` | 校验贴表情目标属于当前群，并提供有限最近上下文 |
| Capability | `send.text` | Command 失败提示和纯文本复读 |
| Capability | `send.hybrid` | 原样发送包含可支持 QQ 表情的复读消息 |
| Plugin | `maibot-team.napcat-adapter >=1.2.0,<2.0.0` | 查询群信息、修改群专属头衔并调用消息贴表情 API |

Python 第三方依赖为空。

消息贴表情的表情集合与 LLM 选择思路改编自 Ghost_chu 的 MIT 许可项目，版权与许可全文见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。

## 测试

静态检查：

```bash
python -m json.tool _manifest.json >/dev/null
python -m py_compile plugin.py
```

使用受支持的 SDK 运行完整测试：

```bash
uv run --no-project --with 'maibot-plugin-sdk>=2.5.1,<3.0.0' \
  python -m unittest discover -s tests
```

本地加载后至少验证：

1. 机器人是群主时，发送 `头衔 盐田皇帝` 后 QQ 侧头衔发生变化，群内没有成功回复。
2. 机器人不是群主时，收到约定的失败提示。
3. 明确要求设置或生成头衔时，LLM 能发现 Tool 并修改请求者本人。
4. 同时 `@机器人` 和 `@目标成员` 时，Tool 从结构化 At 修改唯一目标成员；使用简称或群内称呼时，LLM 解析规范成员名，插件仅在当前群精确唯一匹配后执行。
5. Planner 不会为头衔讨论调用 Tool；跨群消息 ID、错误消息 ID、多个目标 At 和重名昵称会被插件拒绝。
6. 启用复读并把概率设为 `1.0`，两名不同成员连续发送相同文本后，机器人只原样复读一次。
7. 连续消息中插入图片、At 或不同文本时，旧复读队列被清除；同一成员重复发送不会独自触发。
8. 复读概率为 `0.0`、群不在白名单或复读功能关闭时，机器人不参与复读。
9. 启用消息贴表情并把普通概率设为 `1.0`，目标群新消息会在 NapCat 中得到一个反应表情，同时正常 Planner 流程不受影响。
10. 让 LLM 调用 `qianqian_msg_react`，确认只能操作当前群最近消息，跨群或不存在的消息 ID 会被拒绝。
11. 启用 Planner 活跃提示后，从 Planner 监控中确认 `send_voice_reply` 描述和 `reply.attach_emoji` 参数描述包含配置的附加指令。
12. 普通回复超过状态延迟时先出现托腮，消息发出后托腮消失；快速回复不闪烁托腮。
13. 头衔设置成功后请求消息只有一个 OK；失败时没有 OK，并继续收到原有文字错误说明。

## 常见问题

### 插件没有加载

确认仓库位于 MaiBot 的 `plugins/qianqian-plugins/`，并已安装兼容版本的 NapCat Adapter。检查日志中的 Manifest、依赖和 SDK 兼容性错误。

### 提示机器人不是群主

确认运行 NapCat 的 QQ 在当前群中的角色是群主。群管理员不满足本插件的权限要求。

### Tool 提示无法确认请求消息

Tool 会严格校验请求消息属于当前聊天流和当前群。消息不存在、LLM 选择了错误 `msg_id` 或消息数据不完整时都会拒绝执行。

### Tool 提示直接 @ 对方

目标昵称在当前群找不到时，或同一规范名称匹配到多位成员时，插件会关闭失败。用户需要同时 `@机器人` 和 `@目标成员` 后重新发送明确请求；这条带结构化 At 的新消息就是二次确认。

### Tool 提示没有修改其他成员的权限

在 WebUI 的“群专属头衔”配置中，把可信请求者的 QQ 号加入允许名单；如果这是允许全群参与的娱乐功能，也可以打开“允许所有群成员请求修改其他成员的头衔”。

### QQ 拒绝了修改

检查 NapCat 与 QQ 日志。QQ 服务端可能因为头衔内容、账号状态或权限变化拒绝操作。

### 群里没有触发复读

确认已单独启用 `[repeater]`，当前群在 `enabled_group_ids` 范围内，并且消息来自两个不同成员、内容严格相同且相邻间隔不超过 120 秒。概率低于 `1.0` 时，没有抽中属于正常行为。

## 许可

这是仟仟的自用插件，当前未授予公开使用、修改或分发许可（`UNLICENSED`）。

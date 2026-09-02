# 消息防抖与 QQ 群复读的组合调研

> 调研日期：2026-09-02  
> 参考仓库：[`Blackwindy2333/Message_Debouncing_Refactored`](https://github.com/Blackwindy2333/Message_Debouncing_Refactored)  
> 参考版本：默认分支 `main`，HEAD [`bc57b567a73d768eb6c3291b064c3128d3c6a3ff`](https://github.com/Blackwindy2333/Message_Debouncing_Refactored/commit/bc57b567a73d768eb6c3291b064c3128d3c6a3ff)

## 结论

**可以引入，但它主要改善 LLM 收到的发言完整性，并不会天然增强复读。**

参考项目实现的是“同一会话、同一用户的尾缘防抖合并”：先暂存一条消息；短时间内同一用户继续发言就追加并重新计时；窗口结束后只向 MaiBot 放行一条合并消息。它解决的是用户把一句话拆成多条时，机器人过早回复、重复思考和上下文割裂的问题，而不是限频或反垃圾消息。[上游 README 对目标和示例的说明](https://github.com/Blackwindy2333/Message_Debouncing_Refactored/blob/bc57b567a73d768eb6c3291b064c3128d3c6a3ff/README.md#L8-L18)

对本仓库而言，推荐把防抖设计成独立的 `DebounceModule`，默认关闭，并明确放在复读的上游。不过不能原样复制参考实现，至少要处理以下差异：

- 群内永远按“群号 + 发送者”隔离，禁止跨成员合并。
- `头衔 <内容>` 和其他命令必须立即绕过防抖。
- 富媒体第一版不合并，避免破坏引用、At、图片和消息锚定。
- 配置热更新和卸载必须完整取消定时器、清空窗口并唤醒等待者。
- 同一成员连续发送完全相同的可复读内容时，不能合成 `内容\n内容`；应只保留一份原样候选，否则会破坏现有 `A、A、B` 复读规则。

如果目的只是“让复读更容易触发”，**不建议仅为此增加防抖**。如果目的是“让机器人等用户把话说完再交给 LLM”，防抖值得做，复读兼容应作为附加约束。

## 参考项目现状

核验时仓库的默认分支为 `main`，HEAD 是 `bc57b56`；仓库共有 4 个提交，没有 tag 或 GitHub Release，也没有测试文件。项目最后两个提交只调整了 Manifest 和 README，运行实现仍来自首次发布提交。相关一手来源：

- [当前 HEAD commit](https://github.com/Blackwindy2333/Message_Debouncing_Refactored/commit/bc57b567a73d768eb6c3291b064c3128d3c6a3ff)
- [提交列表 API](https://api.github.com/repos/Blackwindy2333/Message_Debouncing_Refactored/commits?per_page=100)
- [Tags API](https://api.github.com/repos/Blackwindy2333/Message_Debouncing_Refactored/tags?per_page=100)
- [Releases API](https://api.github.com/repos/Blackwindy2333/Message_Debouncing_Refactored/releases?per_page=10)
- [固定 commit 的仓库文件树](https://github.com/Blackwindy2333/Message_Debouncing_Refactored/tree/bc57b567a73d768eb6c3291b064c3128d3c6a3ff)

Manifest 声明插件版本 `2.0.1`、Host `1.0.0～1.99.99`、SDK `2.5.0～2.99.99`，且无发送 capability 或第三方依赖。[上游 Manifest](https://github.com/Blackwindy2333/Message_Debouncing_Refactored/blob/bc57b567a73d768eb6c3291b064c3128d3c6a3ff/_manifest.json#L1-L31)

本次还进行了只读的基础检查：Manifest 能通过 JSON 解析，源码能通过 `py_compile`，并能在 `maibot-plugin-sdk==2.8.0` 下导入和创建插件实例。这只能证明基本结构可加载，不能代替缺失的并发、热更新和真实 Host 集成测试。

## 上游防抖语义

### 接入点

上游注册了 `chat.receive.before_process` 阻塞 Hook，顺序为 `NORMAL`，超时 `35s`，异常策略为 `SKIP`。[Hook 声明](https://github.com/Blackwindy2333/Message_Debouncing_Refactored/blob/bc57b567a73d768eb6c3291b064c3128d3c6a3ff/plugin.py#L51-L59)

这与 MaiBot 的消息管线相符：`before_process` 位于 `SessionMessage.process()` 前，`after_process` 位于轻量预处理后，二者都允许修改消息或中止调用链。[官方 Hook 文档](https://docs.mai-mai.org/plugin/hooks.md)；[Host 固定版本中的 Hook 定义](https://github.com/MaiM-with-u/MaiBot/blob/ed8493cb741f462684d392a5b477456e8a188399/src/chat/message_receive/bot.py#L54-L87)

当前 Host 的实际顺序是：

```text
before_process
    ↓
SessionMessage.process()
    ↓
after_process
    ↓
Command
    ↓
常规 Maisaka / LLM 流程
```

来源：[Host 消息预处理链](https://github.com/MaiM-with-u/MaiBot/blob/ed8493cb741f462684d392a5b477456e8a188399/src/chat/message_receive/bot.py#L761-L792)、[Host Command 与 Maisaka 分发](https://github.com/MaiM-with-u/MaiBot/blob/ed8493cb741f462684d392a5b477456e8a188399/src/chat/message_receive/bot.py#L838-L860)。

### 窗口算法

第一条合格消息建立窗口并让当前 Hook 协程等待 `flush_event`。同 key 的后续调用会把消息追加到窗口、重置计时器并立即返回 `abort`。计时结束后，第一条消息的协程被唤醒；只有一条时原样放行，多条时返回一份合并后的 `message`。[窗口创建、追加和结算](https://github.com/Blackwindy2333/Message_Debouncing_Refactored/blob/bc57b567a73d768eb6c3291b064c3128d3c6a3ff/plugin.py#L77-L131)

计时器使用 `monotonic()`：每次追加都重新等待 `debounce_seconds`，但总时间不会超过从首条开始计算的 `max_wait_seconds`。[计时器实现](https://github.com/Blackwindy2333/Message_Debouncing_Refactored/blob/bc57b567a73d768eb6c3291b064c3128d3c6a3ff/plugin.py#L135-L153)

该算法有一个必须实测的运行前提：第一条消息正在阻塞等待时，同会话的后续消息仍能并发进入同一个 Hook。官方文档说明 `BLOCKING` 处理器在一次 Hook 调用中串行执行，但没有承诺不同入站消息一定并发调度；上游又没有测试覆盖这一点。因此接入真实 Host 和 NapCat 时必须用连续消息验证，否则串行的消息入口会让后续碎片直到首条超时后才有机会进入，防抖就无法合并。[官方 Hook 的 BLOCKING 语义](https://docs.mai-mai.org/plugin/hooks.md#处理模式)

默认配置为 `2s` 防抖、`8s` 最长等待、换行分隔、私聊和群聊都启用、只合并同一用户，命令前缀为 `/`、`!`、`！`。[配置定义](https://github.com/Blackwindy2333/Message_Debouncing_Refactored/blob/bc57b567a73d768eb6c3291b064c3128d3c6a3ff/config_models.py#L27-L97)

### 状态模型

上游使用一个全局 `_sessions` 字典和一个全局 `asyncio.Lock`。每个窗口保存 `items`、`flush_event`、`first_at`、`last_at` 和 `timer_task`。[状态初始化](https://github.com/Blackwindy2333/Message_Debouncing_Refactored/blob/bc57b567a73d768eb6c3291b064c3128d3c6a3ff/plugin.py#L20-L24)

默认 key 是 `session_id::user_id`；关闭“只合并同一用户”后退化为 `session_id`。[会话键算法](https://github.com/Blackwindy2333/Message_Debouncing_Refactored/blob/bc57b567a73d768eb6c3291b064c3128d3c6a3ff/plugin.py#L178-L199)

卸载会清空状态、取消计时器并唤醒等待协程；配置热更新却只记录日志，不清理已有窗口，所以窗口可能跨越新旧配置。[生命周期实现](https://github.com/Blackwindy2333/Message_Debouncing_Refactored/blob/bc57b567a73d768eb6c3291b064c3128d3c6a3ff/plugin.py#L28-L47)

## 与 Command、LLM 和复读的交互

| 场景 | 上游行为 | 对本仓库的影响 |
| --- | --- | --- |
| 单条普通消息 | 等待窗口后原样放行 | LLM 平白增加一段固定延迟 |
| 同一用户连续分段 | 后续消息 `abort`，最终只放行一条合并消息 | Command/LLM 正常只处理一次，能避免半句话触发 |
| 群内不同用户发言 | 默认使用不同 key，各自建立窗口 | 不会混淆发送者，但完成顺序可能与原始到达顺序不同 |
| `/`、`!`、`！` 命令 | 直接绕过，不进入窗口 | 命令立即执行，但不会冲刷更早的待结算普通消息 |
| `头衔 <内容>` | 默认前缀无法识别它 | 会被延迟；若同窗口再追加文本，合并结果可能不再匹配命令正则 |
| 复读成功 | 上游本身不知道复读 | 当前 `after_process` 复读 Hook 发送成功后 `abort`，Command/LLM 不再执行 |
| 未命中复读 | 继续后续管线 | 合并消息进入 Command 或 LLM 一次 |

上游过滤通知和已有的 `is_command`，但文本命令只依赖配置前缀；合并后还会把 `is_command` 显式设为 `False`。[过滤逻辑](https://github.com/Blackwindy2333/Message_Debouncing_Refactored/blob/bc57b567a73d768eb6c3291b064c3128d3c6a3ff/plugin.py#L157-L174)、[合并逻辑](https://github.com/Blackwindy2333/Message_Debouncing_Refactored/blob/bc57b567a73d768eb6c3291b064c3128d3c6a3ff/plugin.py#L212-L237)

在当前 Host 中，Command 匹配发生在 `after_process` 之后，因此 `before_process` 阶段不能只依赖 Host 已经设置好 `is_command`；必须自行做字面命令豁免。[Host Command 匹配位置](https://github.com/MaiM-with-u/MaiBot/blob/ed8493cb741f462684d392a5b477456e8a188399/src/chat/message_receive/bot.py#L799-L844)

本仓库现有复读位于 `chat.receive.after_process`，成功发送时返回 `abort`；未触发或发送失败时继续进入 Command/LLM。[本仓库 Hook 实现](../../plugin.py#L48-L79) 复读状态按群隔离，以严格消息段 key 比较内容，并要求至少两个不同发送者。[本仓库复读状态机](../../qianqian/repeater.py#L53-L126)

### 为什么不能直接套在复读前

1. **破坏现有 `A、A、B` 语义。** 当前复读允许 A 连续发送相同内容但只计作一名发送者，随后 B 发送相同内容即可触发。上游会先把 A 的两条合成 `内容\n内容`，而 B 的内容仍是 `内容`，两者不再相同。
2. **严格消息段比较会受分段方式影响。** A 分两条发送 `甲`、`乙` 后，上游产生相邻的 `text("甲")`、`text("\n")`、`text("乙")`；B 单条发送 `甲\n乙` 时只有一个 text 段。视觉文本相同，但当前 `content_key` 不同。
3. **会改变群消息的完成顺序。** 每名成员有独立的滑动窗口；某人持续补充内容时，他更早开始的窗口可能比另一个成员更晚放行。复读判断看到的是“完成后的发言顺序”，不是原始消息到达顺序。
4. **内容不再严格原样。** 上游提取纯文本和生成合并文本时使用 `strip()`，多条消息之间还会主动插入分隔符。[文本提取与合并](https://github.com/Blackwindy2333/Message_Debouncing_Refactored/blob/bc57b567a73d768eb6c3291b064c3128d3c6a3ff/plugin.py#L203-L257) 这与当前复读“不裁剪空白、逐字比较”的契约冲突。[本仓库复读规格](../specs/repeater.md#相同内容)
5. **跨成员合并绝对不可启用。** 上游关闭 `merge_same_user_only` 后会把整个会话的消息放进同一窗口，但合并结果仍继承首条消息的发送者和其他元数据，可能把多人发言错误归属给首个成员。[key 与消息底本](https://github.com/Blackwindy2333/Message_Debouncing_Refactored/blob/bc57b567a73d768eb6c3291b064c3128d3c6a3ff/plugin.py#L178-L237)

参考实现保留首条消息的 `message_id`、发送者和路由，只替换消息体、处理后文本和少量标志。[条目与合并字段](https://github.com/Blackwindy2333/Message_Debouncing_Refactored/blob/bc57b567a73d768eb6c3291b064c3128d3c6a3ff/plugin.py#L203-L237) 当前 Host 会把 Hook 返回的字典重新构造成 `SessionMessage`，随后才注册和持久化该合并消息。[Hook 消息反序列化](https://github.com/MaiM-with-u/MaiBot/blob/ed8493cb741f462684d392a5b477456e8a188399/src/chat/message_receive/bot.py#L218-L247)、[持久化合并后的消息](https://github.com/MaiM-with-u/MaiBot/blob/ed8493cb741f462684d392a5b477456e8a188399/src/chat/heart_flow/heartflow_message_processor.py#L24-L62) 本仓库头衔 Tool 又会按该 ID 重新读取并校验群、发送者与文本。[本仓库头衔锚定](../../qianqian/group_title.py#L139-L203) 因此需要覆盖“首条 ID 对应合并后内容”的集成测试，不能仅凭上游实现假定行为在所有兼容 Host 版本中一致。

## 可以借鉴与不能照搬的部分

### 可以借鉴

- 尾缘滑动窗口加最长等待上限。
- 每个窗口由一条等待中的首消息负责最终放行，其余碎片 `abort`。
- 使用 `monotonic()` 计算运行时等待，不受系统时间校准影响。
- 默认按同一用户隔离窗口。
- 卸载时取消后台任务并唤醒等待协程。
- 合并时保留第一条消息的可信发送者与会话路由。

### 不能照搬

- 可关闭的“只合并同一用户”：本插件应把它做成不可变安全规则。
- 私聊与所有富媒体默认启用：当前需求只需要 QQ 群，并应先收窄内容范围。
- 仅按 `/`、`!`、`！` 判断命令：会漏掉本仓库的无前缀头衔命令。
- 对文本调用 `strip()`：破坏严格原样和复读等价性。
- 配置热更新不清状态：会混用窗口创建时与结算时的配置。
- 全局单锁和 `dict[str, Any]` 状态：可以改用明确的数据类和按 key 的锁，降低跨群争用并让状态约束可测试。
- 合并任意 `image`、`voice`、`forward`：这些消息的发送、引用和锚定语义都比文本复杂，第一版没有必要承担。

## 推荐的最小设计

### 模块与配置

新增独立的 `qianqian/debounce.py`，由插件入口只负责 Hook 适配和生命周期调用；不要把计时器、消息校验继续堆进 `plugin.py`。

第一版只公开少量配置，并默认关闭：

```toml
[debounce]
enabled = false
debounce_seconds = 1.5
max_wait_seconds = 6.0
enabled_group_ids = []
```

固定规则不做配置项：

- 只处理经过严格 NapCat 路由校验的 QQ 群消息。
- key 固定为 `(group_id, sender_id)`，不同成员永不合并。
- 只合并普通文本、Unicode Emoji，以及能够保真保存的 QQ 表情；命令、通知、At、引用、转发和其他富媒体立即绕过。
- `TITLE_COMMAND_PATTERN` 和 `/` 前缀命令必须绕过。
- 配置更新和卸载都取消任务、清空状态并唤醒等待者。
- Hook 超时必须大于 `max_wait_seconds`，异常时放行原消息并记录日志。

### 与复读兼容的内容规则

对同一用户窗口中的消息分两类处理：

1. 后续消息与窗口内最后一条原始消息**完全相同**：把它当成重复发送，只保留一份原样候选，不合成 `内容\n内容`。这样既能去掉同用户刷出的重复 LLM 输入，也保留 `A、A、B` 的复读语义。
2. 后续消息与当前内容不同：按换行合并为一条完整发言，但不裁剪任一原始文本。

合并后应把相邻 text 段折叠为一个 text 段，或让复读的 `content_key` 在比较前做等价折叠。该归一化只能消除“相邻 text 段边界”的结构差异，不能忽略空白、大小写、Unicode 差异或表情顺序。

### 管线语义

最小版本采用：

```text
QQ 群普通消息
    ↓
before_process：按用户防抖、重复折叠、分段合并
    ↓
SessionMessage.process()
    ↓
after_process：现有复读队列与概率抽签
    ├─ 复读成功：发送原样内容并 abort
    └─ 未复读：进入 Command / LLM
```

这个版本能做到“LLM 只看到合并后的完整发言”，也能维持大部分现有复读规则；代价是第一条候选仍可能先进入 LLM，而第二名成员稍后才形成复读，这与当前复读规格一致。

如果以后还希望“只要短窗口内形成复读，第一条也绝不进入 LLM”，就不能只串联两个独立 Hook。需要让防抖与复读共享等待信号：`before_process` 暂存候选，第二名成员命中复读时标记整个候选批次为已消费，唤醒并 `abort` 所有待放行协程。这个方案能真正消除复读与 LLM 抢答，但并发和失败恢复明显更复杂，不建议作为第一版。

## 建议的验收重点

- 单条普通文本只延迟一次，窗口后只进入 LLM 一次。
- 同一人分三段发言只生成一条合并消息，文本和表情顺序保真。
- `A:x、A:x、B:x` 仍能形成一次复读，而不是比较 `x\nx` 与 `x`。
- A 分两条 `甲`、`乙`，B 单条 `甲\n乙` 时，明确验证是否应视为同一复读内容。
- `头衔 皇帝` 立即进入 Command，不等待、不与后续文本合并。
- 自然语言头衔 Tool 请求分段发送时，锚定的 `message_id`、发送者、群号和合并文本一致。
- 命令或富媒体插入已有窗口时，消息顺序和窗口终止规则符合约定。
- 配置热更新、插件卸载、任务取消和 Hook 超时不会遗留等待协程。
- 首条 Hook 等待期间后续同用户消息能真实进入并追加窗口，而不是被消息入口串行阻塞。
- 两个群及同群两名成员并发发言时，状态不串扰。
- 防抖窗口结束顺序与原始消息顺序不同的场景有明确测试和文档说明。

## 最终建议

把防抖作为一个**独立、默认关闭的 LLM 输入整理能力**来实现，而不是把它包装成“复读增强”。第一版借鉴上游的窗口算法，但收紧到 QQ 群、同用户和可保真消息；通过完全相同消息折叠与相邻文本段等价化，守住现有复读契约。等实际使用证明“第一条候选触发 LLM”仍然干扰复读，再考虑共享等待信号的深度联动。

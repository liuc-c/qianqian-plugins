# MaiBot + NapCat 按 @ 与群昵称指定头衔对象的可行性调研

> 调研日期：2026-09-04
>
> MaiBot 官方文档：[`MaiM-with-u/docs`](https://github.com/MaiM-with-u/docs)，固定版本 [`2f0ec78128ad970027471c9c5a5554f18b719591`](https://github.com/MaiM-with-u/docs/commit/2f0ec78128ad970027471c9c5a5554f18b719591)
>
> MaiBot 源码：[`MaiM-with-u/MaiBot`](https://github.com/MaiM-with-u/MaiBot)，固定版本 [`f976ae7eaf9c8e46a45071d1eb60e0713e24532d`](https://github.com/MaiM-with-u/MaiBot/commit/f976ae7eaf9c8e46a45071d1eb60e0713e24532d)
>
> MaiBot NapCat Adapter：[`MaiM-with-u/MaiBot-Napcat-Adapter`](https://github.com/MaiM-with-u/MaiBot-Napcat-Adapter)，固定版本 [`443d6132f543e51c45adc89a2875c5d7744d65fa`](https://github.com/MaiM-with-u/MaiBot-Napcat-Adapter/commit/443d6132f543e51c45adc89a2875c5d7744d65fa)
>
> NapCatQQ：[`NapNeko/NapCatQQ`](https://github.com/NapNeko/NapCatQQ)，固定版本 [`3ac54c181b5e74d7acee5a62293ade88630b05ba`](https://github.com/NapNeko/NapCatQQ/commit/3ac54c181b5e74d7acee5a62293ade88630b05ba)

> 实施状态：本次调研完成后，同一工作区已实现唯一 At 目标和唯一昵称目标；他人头衔权限默认关闭，可通过请求者 QQ 允许名单或“允许所有群成员”配置开启。
>
> 后续产品决策：接受 LLM 基于当前对话、记忆或黑话把简称解析为规范成员名，因此实际实现不再要求 `target_name` 逐字存在于请求原文；插件仍只对当前群成员的真实群昵称或 QQ 昵称做精确唯一确认。

## 结论

三种自然语言入口在 MaiBot + NapCat 下都具有实现基础，但可靠性不同：

| 场景 | 可实现性 | 对象解析 | 入口可靠性 | 建议优先级 |
| --- | --- | --- | --- | --- |
| `@机器人 + @成员 + 头衔` | **可以，且最可靠** | 从锚定原消息的唯一非机器人 `at` 段直接取得 QQ ID | @ 可强制触发 Planner；是否调用 Tool 仍由 LLM 决定 | **第一期** |
| `@机器人 + 群昵称 + 头衔` | **可以，但必须消歧** | 拉取当前群成员列表，在插件内按 `card` / `nickname` 精确唯一匹配 | @ 可强制触发 Planner；昵称可能重名或变化 | 第二期 |
| `机器人昵称或别名 + 群昵称 + 头衔`，无 @ | **可以，但不宜承诺每次触发** | 同上 | 普通群消息通常会进入 Host，但需名称识别和 `mentioned_bot_reply` 才会强制 Planner；仍受 LLM 工具选择影响 | 第三期调研/试运行 |

最合适的第一步是只实现“**@机器人 + 唯一一个 @目标成员**”。NapCat 上报的 `at.data.qq` 是真实 QQ ID；MaiBot NapCat Adapter 会进一步把它转换成包含 `target_user_id` 的结构化 `at` 段，插件通过已经存在的 `message.get_by_id()` 锚定请求消息后即可读取，不需要让 LLM 猜 ID。[OneBot 11 `at` 段规范](https://github.com/botuniverse/onebot-11/blob/d4456ee706f9ada9c2dfde56a2bcfc69752600e4/message/segment.md#L150-L167)；[NapCat `at` Schema](https://github.com/NapNeko/NapCatQQ/blob/3ac54c181b5e74d7acee5a62293ade88630b05ba/packages/napcat-onebot/types/message.ts#L59-L66)；[适配器转换 `at` 段](https://github.com/MaiM-with-u/MaiBot-Napcat-Adapter/blob/443d6132f543e51c45adc89a2875c5d7744d65fa/codecs/inbound/message_codec.py#L217-L245)

第二种也不需要新增适配器接口。当前 NapCat Adapter 已公开 `adapter.napcat.group.get_group_member_list`，返回的成员项含 `user_id`、`nickname`、可选 `card`、`role`、`title` 等字段；插件可在当前群内自行做精确匹配。[适配器公开 API](https://github.com/MaiM-with-u/MaiBot-Napcat-Adapter/blob/443d6132f543e51c45adc89a2875c5d7744d65fa/apis/group.py#L173-L214)；[NapCat 成员 Schema](https://github.com/NapNeko/NapCatQQ/blob/3ac54c181b5e74d7acee5a62293ade88630b05ba/packages/napcat-onebot/action/schemas.ts#L31-L51)；[NapCat 官方“获取群成员列表”](https://napcat.apifox.cn/226657034e0)

不过，这项改动会改变当前仓库的安全边界：现有 `CONTEXT.md` 和 `docs/specs/group-title.md` 明确规定“请求者是唯一允许修改的成员，不允许指定其他成员”。因此实现前必须先决定**谁有权替别人改头衔**，并同步修改规格；否则任何群成员都可能借机器人的群主权限修改别人头衔。文本里的机器人别名只表示“在叫机器人”，不构成请求者权限证明。

## MaiBot 插件实际能拿到什么

### 锚定消息的身份和会话

MaiBot 的插件消息字典包括：

- `message_id`、`platform`、`session_id`；
- `message_info.user_info` 中的发送者 `user_id`、QQ 昵称和群名片；
- `message_info.group_info` 中的当前群 `group_id`、群名；
- `raw_message` 结构化消息段；
- `is_mentioned`、`is_at` 和 `processed_plain_text`。

Host 的消息序列化定义直接列出了这些字段；其中 `at` 段会保留 `target_user_id`、目标 QQ 昵称和目标群名片。[Host 消息字典定义](https://github.com/MaiM-with-u/MaiBot/blob/f976ae7eaf9c8e46a45071d1eb60e0713e24532d/src/plugin_runtime/host/message_utils.py#L28-L59)；[`at` 序列化结构](https://github.com/MaiM-with-u/MaiBot/blob/f976ae7eaf9c8e46a45071d1eb60e0713e24532d/src/plugin_runtime/host/message_utils.py#L64-L142)

官方 SDK 文档确认 `ctx.message.get_by_id(message_id, stream_id=...)` 可在当前聊天流查询单条消息，`ctx.api.call()` 可调用 NapCat Adapter 的公开 API。[历史消息 API](https://github.com/MaiM-with-u/docs/blob/2f0ec78128ad970027471c9c5a5554f18b719591/zh/plugin/api-reference.md#L292-L334)；[跨插件 API](https://github.com/MaiM-with-u/docs/blob/2f0ec78128ad970027471c9c5a5554f18b719591/zh/plugin/api-reference.md#L500-L532)

这意味着新功能可以继续沿用当前工具的安全做法：LLM 只提交请求消息 ID 和头衔文本，插件重新查询原消息并从原消息取得当前群、请求者与 `at` 目标。**不要把 LLM 提交的 `user_id` 直接当作操作对象。** 当前 Host 构造工具调用载荷时也是先放入模型参数，再只给缺失字段补充 `stream_id`、`chat_id`、`group_id`、`user_id` 和 `platform`，所以普通工具参数不是不可伪造的只读调用上下文。[Host 工具上下文与载荷构造](https://github.com/MaiM-with-u/MaiBot/blob/f976ae7eaf9c8e46a45071d1eb60e0713e24532d/src/plugin_runtime/component_query.py#L739-L831)

### Command 也可以读取完整消息

官方 Command 文档说明处理器能取得 `stream_id`、正则捕获组和完整 `message`；Host 实现还会注入当前 `group_id`、`platform`、发送者 `user_id`，并把消息段序列化后交给插件。[Command 官方参数](https://github.com/MaiM-with-u/docs/blob/2f0ec78128ad970027471c9c5a5554f18b719591/zh/plugin/commands.md#L66-L107)；[Host Command 注入](https://github.com/MaiM-with-u/MaiBot/blob/f976ae7eaf9c8e46a45071d1eb60e0713e24532d/src/plugin_runtime/component_query.py#L475-L540)

所以若以后要求“自然语言句式一旦匹配就确定执行，不依赖 Planner 是否选中 Tool”，也可以增加收敛的 `@Command`。但用户当前允许 LLM 理解白话，而且第三种场景的 @ 已能稳定激活 Planner，第一期继续扩展现有 Tool 更贴合当前架构。官方也明确区分：Tool 是让 LLM 主动选择调用外部能力，Command 才是正则命中后直接调度处理器。[Tool 定位](https://github.com/MaiM-with-u/docs/blob/2f0ec78128ad970027471c9c5a5554f18b719591/zh/plugin/tools.md#L5-L10)；[Command 定位](https://github.com/MaiM-with-u/docs/blob/2f0ec78128ad970027471c9c5a5554f18b719591/zh/plugin/commands.md#L5-L32)

## 三种场景的具体判断

### 用户场景三：@机器人 + @目标成员

**可可靠实现，建议优先。**

NapCat 入站消息把每次 @ 表示为独立 `at` 段，`data.qq` 是 QQ 号或 `all`。NapCat 当前入站转换实际只保证 `qq`，并没有填可选的显示名，因此底层逻辑应依赖 ID，而不是依赖 @ 的文字显示名。[NapCat 入站 @ 转换](https://github.com/NapNeko/NapCatQQ/blob/3ac54c181b5e74d7acee5a62293ade88630b05ba/packages/napcat-onebot/api/msg.ts#L95-L120)

MaiBot NapCat Adapter 会查询 @ 对象的信息并把该段转换为：

```text
{
  "type": "at",
  "data": {
    "target_user_id": "...",
    "target_user_nickname": "...",
    "target_user_cardname": "..."
  }
}
```

其中 ID 来自 NapCat 的 `qq` 字段；昵称或群名片查询失败也不影响 ID。[适配器的 @ 解析与信息补全](https://github.com/MaiM-with-u/MaiBot-Napcat-Adapter/blob/443d6132f543e51c45adc89a2875c5d7744d65fa/codecs/inbound/message_codec.py#L222-L245)；[补全逻辑](https://github.com/MaiM-with-u/MaiBot-Napcat-Adapter/blob/443d6132f543e51c45adc89a2875c5d7744d65fa/codecs/inbound/message_codec.py#L291-L324)

建议的确定性规则：

1. 从锚定请求消息读取全部 `at` 段。
2. 调 `get_login_info` 取得机器人自身 QQ，排除该 ID。
3. 排除 `all`。
4. 剩余目标必须**恰好一个**；零个或多个均拒绝，并要求用户只 @ 一个目标成员。
5. 以该段的 `target_user_id` 调 `get_group_member_info(current_group, target, no_cache=true)`，确认该 QQ 仍在当前群。
6. 验证请求者权限、机器人真实群角色和头衔规则后再设置。

这种设计不需要在 Tool Schema 中暴露 `target_user_id`，也不会把机器人自己的 @ 错当成目标。

### 用户场景二：@机器人 + 目标群昵称

**可以实现，但名称不是可靠唯一键。**

OneBot / NapCat 没有“按群昵称查询 QQ ID”的专门接口。标准做法是调用 `get_group_member_list(group_id)`，再在插件内检索；OneBot 11 的成员列表元素与成员信息包含 `user_id`、`nickname`、`card`、`role`、`title` 等字段。[OneBot 11 群成员接口](https://github.com/botuniverse/onebot-11/blob/d4456ee706f9ada9c2dfde56a2bcfc69752600e4/api/public.md#L394-L434)；[NapCat 列表实现与缓存选项](https://github.com/NapNeko/NapCatQQ/blob/3ac54c181b5e74d7acee5a62293ade88630b05ba/packages/napcat-onebot/action/group/GetGroupMemberList.ts#L8-L58)

建议只采用以下关闭失败算法：

1. 原始保守建议要求 `target_name` 逐字存在于锚定请求原文；后续产品决策已放宽为允许 LLM 基于当前对话、记忆或黑话解析规范成员名。
2. 查询当前群成员列表；先找 `card == target_name` 的成员。
3. 群名片恰好命中一人时使用该人的 `user_id`；命中多人时拒绝并要求改用 @。
4. 没有群名片命中时，再找 `nickname == target_name`；仍只接受唯一结果。
5. 零命中或多命中时可用 `no_cache=true` 刷新一次；仍不唯一就拒绝。
6. 不做子串、拼音、编辑距离或 LLM 模糊匹配，也不选择列表中的第一人。

群名片和 QQ 昵称都可能重复、为空或随时变化；只有 QQ ID 是稳定操作键。因此用户场景二的用户体验可以很好，但安全性必须依赖“精确且唯一”，重名时必须退回用户场景三。

### 用户场景一：无 @，只写机器人昵称或别名 + 目标群昵称

**消息通常能收到，对象也能解析，但不能把现有 LLM 链路描述为确定性触发。**

NapCat Adapter 对普通群消息和 @ 消息走同一条入站路由；只要消息通过聊天名单、用户黑名单、官方机器人和正则过滤，就会转换并注入 Host，并不要求消息必须 @ 机器人。[适配器入站路由](https://github.com/MaiM-with-u/MaiBot-Napcat-Adapter/blob/443d6132f543e51c45adc89a2875c5d7744d65fa/runtime/router.py#L86-L139)

MaiBot 会在正文中做昵称/别名子串检测。候选来自 `bot.nickname` 与 `bot.alias_names`；命中后标记为“提及”，而 `mentioned_bot_reply=true` 时才把本轮触发概率提升到 `1.0`。[昵称与别名配置](https://github.com/MaiM-with-u/MaiBot/blob/f976ae7eaf9c8e46a45071d1eb60e0713e24532d/src/config/official_configs.py#L161-L186)；[名称/别名识别与回复提升](https://github.com/MaiM-with-u/MaiBot/blob/f976ae7eaf9c8e46a45071d1eb60e0713e24532d/src/chat/utils/utils.py#L145-L256)

当前运行时会把这种强制提及状态用于安排下一轮 Planner；真正的 @ 则由默认开启的 `inevitable_at_reply` 提升。产品字段名称虽叫“必回复”，源码层严格保证的是**强制 Planner 获得处理机会**，不是保证 LLM 一定选择头衔 Tool。[回复开关默认值](https://github.com/MaiM-with-u/MaiBot/blob/f976ae7eaf9c8e46a45071d1eb60e0713e24532d/src/config/official_configs.py#L571-L597)；[强制 Planner 轮次](https://github.com/MaiM-with-u/MaiBot/blob/f976ae7eaf9c8e46a45071d1eb60e0713e24532d/src/maisaka/runtime.py#L1278-L1322)

因此这一场景至少要求：

- 机器人昵称确实配置在 `bot.nickname`；
- 机器人别名确实配置在 `bot.alias_names`，不能只写在人设描述里；
- `chat.reply_timing.mentioned_bot_reply = true`；
- 该群没有被 NapCat Adapter 的名单或正则过滤拦截；
- Planner 能发现并选择头衔 Tool。

即使满足这些条件，目标成员仍需走用户场景二的精确唯一匹配。若以后要求“只要白话句式命中就必执行”，应增加严格正则 Command 或消息 Hook 作为确定性入口，而不是靠补充提示词承诺成功率。

## NapCat API 与权限边界

### 可直接使用的接口

当前 MaiBot NapCat Adapter 已公开所需接口：

| 目的 | Adapter API | 关键参数 |
| --- | --- | --- |
| 取得机器人 QQ | `adapter.napcat.system.get_login_info` | 无 |
| 查询机器人或目标成员 | `adapter.napcat.group.get_group_member_info` | `group_id`、`user_id`、`no_cache` |
| 通过名称解析成员 | `adapter.napcat.group.get_group_member_list` | `group_id`、`no_cache` |
| 设置专属头衔 | `adapter.napcat.group.set_group_special_title` | `params={group_id,user_id,special_title}` |

Adapter 的成员单查与列表 API 会把结果解包为成员字典或列表，设置头衔 API 则透传 NapCat 动作。[成员 API 实现](https://github.com/MaiM-with-u/MaiBot-Napcat-Adapter/blob/443d6132f543e51c45adc89a2875c5d7744d65fa/apis/group.py#L173-L214)；[设置头衔 API](https://github.com/MaiM-with-u/MaiBot-Napcat-Adapter/blob/443d6132f543e51c45adc89a2875c5d7744d65fa/apis/group.py#L559-L569)；[Adapter API 总表](https://github.com/MaiM-with-u/MaiBot-Napcat-Adapter/blob/443d6132f543e51c45adc89a2875c5d7744d65fa/docs/typed-api.md#L41-L46)

NapCat 自己的设置动作接受 `group_id`、`user_id` 和 `special_title`，然后将 QQ 号转换成内部 UID 并发送设置包。[NapCat 设置实现](https://github.com/NapNeko/NapCatQQ/blob/3ac54c181b5e74d7acee5a62293ade88630b05ba/packages/napcat-onebot/action/extends/SetSpecialTitle.ts#L7-L33)；[NapCat 官方“设置专属头衔”](https://napcat.apifox.cn/226656931e0)

### “群主”别名不是权限

OneBot / NapCat 接口契约没有把某段文本当作授权。NapCat 设置动作自身也没有先查发起消息的人或本地校验群角色，而是直接向 QQ 发包；最终能否设置由机器人账号权限与 QQ 服务端决定。仓库当前额外查询机器人在当前群的 `role` 并只接受 `owner`，这个保护应保留。

更重要的是，请求者权限和机器人权限是两个不同问题：

- **机器人权限**：机器人必须具有实际可设置头衔的 QQ 群权限；不能因为有人在文本中称它“群主”就视为已授权。
- **请求者权限**：必须另行规定哪些真实 QQ 用户有权修改其他成员。建议使用运行时配置中的请求者 QQ allowlist，或者在 Host 版本边界允许时使用 operator Command；不得依据昵称、群名片或人设身份授权。
- **目标身份**：只从锚定消息的唯一 `at` ID，或当前群成员列表的唯一精确名称匹配得到。

### `status=ok` 只代表 NapCat 受理，不是严格的 QQ 侧确认

NapCat 当前设置头衔使用 Packet backend，构包时把过期时间固定为 `-1`。[设置包内容](https://github.com/NapNeko/NapCatQQ/blob/3ac54c181b5e74d7acee5a62293ade88630b05ba/packages/napcat-core/packet/transformer/action/SetSpecialTitle.ts#L6-L21)

该调用没有要求等待响应：`SetGroupSpecialTitle()` 调用 `sendOidbPacket(req)`，底层在 `rsp=false` 时异步发送并立即返回；发送失败只在后台记录。因此 `status=ok, retcode=0` 严格来说只证明 NapCat 已接受并发起动作，不足以证明 QQ 客户端已经显示新头衔。[调用没有等待响应](https://github.com/NapNeko/NapCatQQ/blob/3ac54c181b5e74d7acee5a62293ade88630b05ba/packages/napcat-core/packet/context/operationContext.ts#L84-L87)；[无响应发送分支](https://github.com/NapNeko/NapCatQQ/blob/3ac54c181b5e74d7acee5a62293ade88630b05ba/packages/napcat-core/packet/client/nativeClient.ts#L55-L70)

如果要把 Tool 返回值称为“设置成功”，建议设置后短暂重试 `get_group_member_info(target, no_cache=true)` 并检查返回的 `title` 是否等于请求头衔；未能确认时返回“已提交但未确认生效”，而不是静默成功。该核验也能减少账号权限变化或 QQ 侧拒绝导致的假成功。

## 推荐实现契约

### 第一期：只做唯一 @ 目标

1. 保留现有 `request_message_id`、`title`、`mode`，继续锚定当前聊天流中的原消息。
2. 不向 Tool 暴露可自由填写的 `target_user_id`。
3. 从原消息的 `raw_message` 提取唯一非机器人、非 `all` 的 @ 对象。
4. 请求者必须通过新增的“可替别人设置头衔”授权检查。
5. 机器人仍必须是当前群真实 `owner`。
6. 设置前确认目标仍属于当前群；设置后无缓存查询并核验新头衔。
7. 零目标、多目标、跨群、目标已退群、权限不足、头衔无效或设置后未确认都关闭失败。

### 第二期：增加唯一群昵称

在第一期契约上新增 `target_name` 字符串参数，但必须满足：

- 原文包含该名称；
- 没有可用的唯一非机器人 @ 目标；
- `card` 优先、`nickname` 兜底；
- 只接受当前群内唯一精确匹配；
- 同名时明确提示“找到多个同名成员，请改用 @ 指定”。

### 第三期：无 @ 的昵称/别名入口

先仅通过配置试运行：把需要识别的机器人称呼放到 `bot.alias_names` 并启用 `mentioned_bot_reply`。如果实际使用仍有漏触发，再决定是否为少量明确句式增加 Command；不要扩大昵称模糊匹配，也不要让人设中的“身份词”自动获得授权语义。

## 对当前仓库的影响

调研阶段没有修改实现；随后同一工作区已按结论闭环以下契约：

- `CONTEXT.md` 与功能规格已新增指定成员、At 指定、昵称指定和授权请求者术语。
- Tool 没有接收目标 QQ 号；它从锚定消息读取结构化 At，或在当前群成员列表内解析精确唯一名称。
- LLM 可把原消息中的简称或群内称呼解析为规范成员名；该规范名不必逐字出现在原消息，误判风险由精确成员确认、权限配置和重名二次确认共同收敛。
- 昵称解析采用群昵称优先、QQ 昵称兜底；零命中、同类名称重名、多个 At 和 `@全体成员` 均关闭失败。
- 配置默认不允许修改他人，可按请求者 QQ 允许名单开放，也可显式允许所有群成员。
- 现有 `api.call` 与 `message.get_by_id` Capability 足以覆盖实现，未增加主程序改动。
- 自动化测试覆盖目标解析、授权和原有本人头衔行为。

当前仍保留一个已知边界：沿用原实现，以 NapCat 返回 `status=ok, retcode=0` 作为 Tool 成功；尚未增加设置后的 QQ 侧头衔轮询核验。

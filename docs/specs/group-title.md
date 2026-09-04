# QQ 群专属头衔功能规格

## 范围

仟仟自用插件为 QQ 群成员提供修改本人群专属头衔的 Command，以及修改本人或一位指定成员群专属头衔的 LLM Tool。功能仅支持 MaiBot NapCat Adapter，不允许指定其他群。

## Command

- 完整匹配 `头衔 <内容>`，关键字与内容之间至少有一个普通或全角空格。
- 裁掉内容两端空白；无内容、换行、控制字符或超长内容失败。
- 内容始终按字面设置，`头衔 随机` 设置的内容就是“随机”。
- 发送者是唯一操作目标。
- 成功时不发送消息；失败时发送简洁的简体中文错误。

## Tool

- 注册名为 `qianqian_set_group_title`，保持 deferred，不声明 `core_tool=True`。
- 参数为 `title`、`request_message_id`、`mode`、`target_mode` 和可选的 `target_name`；`mode` 仅允许 `specified` 或 `generated`，`target_mode` 仅允许 `requester`、`mentioned` 或 `named`。
- LLM 不得提供 `user_id` 或 `group_id`；插件不信任 Tool 调用载荷中的群号和平台，而从锚定消息派生当前群并再次验证平台。
- 插件要求 Host 注入的 `stream_id` 与 `chat_id` 一致，再以该 `stream_id` 查询 `request_message_id`，验证消息 ID、会话与平台，并从原消息提取请求者和当前群。
- `specified` 模式要求 `title` 原样存在于请求消息中。
- `generated` 模式不在插件内解析自然语言；是否获得生成授权由 LLM 依据 Tool 描述判断。
- `requester` 模式以锚定消息发送者为指定成员，保持本人头衔功能兼容。
- `mentioned` 模式从锚定消息的结构化 `raw_message` 提取 At；排除机器人后必须恰好剩余一个成员，且拒绝 `@全体成员` 与多个指定成员。
- `named` 模式允许 LLM 根据当前对话、记忆或黑话，把请求中的简称或群内称呼解析成目标成员当前准确的群昵称或 QQ 昵称；`target_name` 不要求原样存在于请求消息。
- 插件通过 `adapter.napcat.group.get_group_member_list` 无缓存查询当前群成员；先按群昵称 `card` 精确唯一匹配，无结果时再以 QQ 昵称 `nickname` 兜底。
- 插件本身不做模糊匹配；未找到时要求用户直接 At 对方，精确命中多人时不执行本次修改，并要求用户重新发送明确请求、At 唯一目标成员完成二次确认。
- 插件不维护触发词、动作词、否定词、问句或引号白名单。讨论与含糊请求由 LLM 拦截，运行时只验证可确定的参数和消息事实。
- 锚定、身份、指定成员或指定头衔原文校验失败时关闭失败，不猜测最后发言人，不使用发送者缓存。只有成员规范名允许由 LLM 基于上下文解析，不作为身份凭证直接执行。
- 成功结果返回给 LLM；Tool 不直接发送成功消息。

### Host 信任边界

MaiBot Host 1.x 当前把 Tool 上下文作为调用载荷的缺省值注入，插件侧拿不到不可覆盖的调用会话对象。因此 `stream_id == chat_id` 是当前可做的闭合校验，但无法从密码学意义上证明两个字段均未被调用载荷覆盖。若 Host 后续提供只读调用上下文，应改用该上下文；若要求绝对强绑定，必须在 MaiBot Host 侧修改，不能只靠本插件完成。

## 权限与标题规则

- 仅在 QQ 群聊中可用。
- 每次修改前查询机器人 QQ 及其当前群角色，只有 `owner` 可以继续；`admin` 与 `member` 均失败。
- 修改本人不要求额外授权；修改其他成员时，请求者必须存在于 `allowed_requester_ids`，或已开启 `allow_all_members_to_set_others`。
- 他人头衔权限依据锚定消息发送者的 QQ ID 判断，不依据昵称、群名片或文本中的“群主”等机器人别名判断。
- 默认 `allow_all_members_to_set_others = false` 且允许名单为空，因此升级后不会自动把机器人的群主权限开放给全群。
- 不使用群白名单，不设置冷却，不支持清除头衔。
- 头衔最多占 6 个 UTF-16 单元；普通字符通常占 1，常见 Emoji 通常占 2，最终以 QQ 结果为准。

## NapCat 集成

- 通过公开 API `adapter.napcat.system.get_login_info` 查询机器人 QQ。
- 通过公开 API `adapter.napcat.group.get_group_member_info` 无缓存查询机器人群角色。
- 昵称指定时通过公开 API `adapter.napcat.group.get_group_member_list` 无缓存查询当前群完整成员列表。
- 通过公开 API `adapter.napcat.group.set_group_special_title` 设置已解析成员的头衔。
- 头衔功能使用 Manifest 中的 `api.call`、`message.get_by_id`、`send.text`。
- Manifest 硬依赖 `maibot-team.napcat-adapter >=1.0.1,<2.0.0`。

## 错误与日志

- 用户只看到简洁中文错误，不看到异常或适配器内部信息。
- 消息查询异常、适配器异常和 NapCat 失败的技术信息写入插件日志。
- 至少区分：非 QQ 群聊、标题无效、机器人不是群主、请求者无权修改他人、消息无法确认、指定头衔原文不一致、At 目标无效、昵称未找到、昵称重名需二次确认、适配器不可用、QQ 拒绝修改。

## 验收

- 插件只注册一个头衔 Command 和一个头衔 Tool，不保留初始化示例组件。
- Command 与 Tool 都使用同一套标题校验、群主检查和 NapCat 设置流程。
- 自动化测试覆盖成功静默、非群主、长度、非 QQ、适配器异常、QQ 拒绝、指定头衔原文校验、生成模式不复查措辞、消息查询失败、他人头衔授权、唯一 At 成员、多个 At 成员、昵称唯一匹配与昵称重名。

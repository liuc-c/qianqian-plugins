# QQ 群专属头衔功能规格

## 范围

仟仟自用插件为 QQ 群成员提供修改本人群专属头衔的 Command 和 LLM Tool。功能仅支持 MaiBot NapCat Adapter，不允许指定其他成员或其他群。

## Command

- 完整匹配 `头衔 <内容>`，关键字与内容之间至少有一个普通或全角空格。
- 裁掉内容两端空白；无内容、换行、控制字符或超长内容失败。
- 内容始终按字面设置，`头衔 随机` 设置的内容就是“随机”。
- 发送者是唯一操作目标。
- 成功时不发送消息；失败时发送简洁的简体中文错误。

## Tool

- 注册名为 `qianqian_set_group_title`，保持 deferred，不声明 `core_tool=True`。
- 参数为 `title`、`request_message_id` 和 `mode`；`mode` 仅允许 `specified` 或 `generated`。
- LLM 不得提供 `user_id` 或 `group_id`；插件不信任 Tool 调用载荷中的群号和平台，而从锚定消息派生当前群并再次验证平台。
- 插件要求 Host 注入的 `stream_id` 与 `chat_id` 一致，再以该 `stream_id` 查询 `request_message_id`，验证消息 ID、会话与平台，并从原消息提取请求者和当前群。
- `specified` 模式要求 `title` 原样存在于请求消息中。
- `generated` 模式只接受明确授权随机、想、取或起一个头衔的消息；明显的否定表达不构成授权。
- 锚定、身份或授权校验失败时关闭失败，不猜测最后发言人，不使用发送者缓存。
- 成功结果返回给 LLM；Tool 不直接发送成功消息。

### Host 信任边界

MaiBot Host 1.x 当前把 Tool 上下文作为调用载荷的缺省值注入，插件侧拿不到不可覆盖的调用会话对象。因此 `stream_id == chat_id` 是当前可做的闭合校验，但无法从密码学意义上证明两个字段均未被调用载荷覆盖。若 Host 后续提供只读调用上下文，应改用该上下文；若要求绝对强绑定，必须在 MaiBot Host 侧修改，不能只靠本插件完成。

## 权限与标题规则

- 仅在 QQ 群聊中可用。
- 每次修改前查询机器人 QQ 及其当前群角色，只有 `owner` 可以继续；`admin` 与 `member` 均失败。
- 不使用群白名单，不设置冷却，不支持清除头衔。
- 头衔最多占 6 个 UTF-16 单元；普通字符通常占 1，常见 Emoji 通常占 2，最终以 QQ 结果为准。

## NapCat 集成

- 通过公开 API `adapter.napcat.system.get_login_info` 查询机器人 QQ。
- 通过公开 API `adapter.napcat.group.get_group_member_info` 无缓存查询机器人群角色。
- 通过公开 API `adapter.napcat.group.set_group_special_title` 设置请求者头衔。
- Manifest 声明 `api.call`、`message.get_by_id`、`send.text`。
- Manifest 硬依赖 `maibot-team.napcat-adapter >=1.0.1,<2.0.0`。

## 错误与日志

- 用户只看到简洁中文错误，不看到异常或适配器内部信息。
- 消息查询异常、适配器异常和 NapCat 失败的技术信息写入插件日志。
- 至少区分：非 QQ 群聊、标题无效、机器人不是群主、消息无法确认、请求未授权、适配器不可用、QQ 拒绝修改。

## 验收

- 插件只注册一个头衔 Command 和一个头衔 Tool，不保留初始化示例组件。
- Command 与 Tool 都使用同一套标题校验、群主检查和 NapCat 设置流程。
- 自动化测试覆盖成功静默、非群主、长度、非 QQ、适配器异常、QQ 拒绝、指定授权、生成授权、否定授权和消息查询失败。

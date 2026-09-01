# 🐾 仟仟自用插件

一个基于 `maibot-plugin-sdk` 的 MaiBot 自用插件。目前用于让 QQ 群成员为自己设置群专属头衔。

## 功能

- Command：发送 `头衔 <内容>`，把字面内容设置为发送者自己的群专属头衔。
- Tool：用户明确要求设置头衔时，由 LLM 调用 `qianqian_set_group_title`；用户也可以明确授权 LLM 取一个头衔并立即设置。
- 安全锚定：Tool 根据请求消息的 `msg_id` 查询原消息，只操作该消息的发送者，并从原消息取得当前群，不接受 LLM 指定用户或群。
- 群主校验：仅当机器人 QQ 是当前群群主时执行。

## 前置条件

- MaiBot Host `1.x`
- `maibot-plugin-sdk` `2.5.1`～`2.x`
- [MaiBot NapCat Adapter](https://github.com/MaiM-with-u/MaiBot-Napcat-Adapter) `1.0.1`～`1.x`
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
| `plugin` | `config_version` | `0.2.0` | 配置结构版本 |

`config.toml` 是当前安装实例的运行时配置，不应提交到 Git。

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
```

以下只是讨论，不应调用 Tool：

```text
你觉得什么头衔比较好？
盐田皇帝这个头衔怎么样？
```

对于用户指定的头衔，Tool 会检查标题原文确实存在于请求消息中。对于生成的头衔，是否获得授权由 LLM 根据 Tool 描述和对话语义判断；插件运行时不维护触发词、否定词或问句白名单。

Tool 还会要求 Host 注入的 `stream_id` 与 `chat_id` 一致，并只在该聊天流内查询请求消息。MaiBot Host 1.x 目前把上下文字段作为调用参数的缺省值注入，没有向插件提供不可覆盖的只读调用上下文；因此插件可以关闭常见的跨流误选，但绝对的 Host 级强绑定仍需 MaiBot 主程序支持。

## 限制与失败行为

- 仅支持 NapCat 接入的 QQ 群聊。
- 只能修改请求者自己的头衔，不能指定其他成员或其他群。
- 不提供清除头衔功能。
- 头衔最多占 6 个 UTF-16 单元：普通字符通常占 1，常见 Emoji 通常占 2；最终仍以 QQ 接受结果为准。
- 没有调用冷却时间。
- 机器人不是群主时提示：`设置失败：机器人不是当前群群主`。
- 适配器不可用、消息锚定失败或 QQ 拒绝修改时，会返回简洁错误；技术细节只写入插件日志。

## 权限与依赖

| 类型 | 声明 | 用途 |
| --- | --- | --- |
| Capability | `api.call` | 调用 NapCat Adapter 的公开 API |
| Capability | `message.get_by_id` | Tool 根据请求消息 ID 取得可信发送者 |
| Capability | `send.text` | Command 失败时发送错误消息 |
| Plugin | `maibot-team.napcat-adapter >=1.0.1,<2.0.0` | 查询机器人身份、群角色并修改群专属头衔 |

Python 第三方依赖为空。

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
4. Planner 不会为头衔讨论调用 Tool；跨群消息 ID 和错误消息 ID 会被插件拒绝。

## 常见问题

### 插件没有加载

确认仓库位于 MaiBot 的 `plugins/qianqian-plugins/`，并已安装兼容版本的 NapCat Adapter。检查日志中的 Manifest、依赖和 SDK 兼容性错误。

### 提示机器人不是群主

确认运行 NapCat 的 QQ 在当前群中的角色是群主。群管理员不满足本插件的权限要求。

### Tool 提示无法确认请求消息

Tool 会严格校验请求消息属于当前聊天流和当前群。消息不存在、LLM 选择了错误 `msg_id` 或消息数据不完整时都会拒绝执行。

### QQ 拒绝了修改

检查 NapCat 与 QQ 日志。QQ 服务端可能因为头衔内容、账号状态或权限变化拒绝操作。

## 许可

这是仟仟的自用插件，当前未授予公开使用、修改或分发许可（`UNLICENSED`）。

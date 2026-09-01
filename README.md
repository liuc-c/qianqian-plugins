# 🐾 仟仟自用插件

一个基于 `maibot-plugin-sdk` 的 MaiBot 自用插件。当前提供基础连通性命令和文本复述 Tool，可在此骨架上继续增加仟仟需要的能力。

## 功能

- `/qianqian-ping`：检查插件命令链路是否正常，成功时回复 `pong`。
- `qianqian_echo_text`：供 LLM 调用的文本复述 Tool。
- 支持配置模型、配置热重载以及标准加载/卸载生命周期。

## 安装

在 MaiBot 根目录执行：

```bash
git clone https://github.com/liuc-c/qianqian-plugins.git plugins/qianqian-plugins
```

随后启动或重启 MaiBot。Runner 会自动发现插件，并依据 `plugin.py` 中的 `config_model` 生成本地 `config.toml`。

## 启用与配置

在 MaiBot WebUI 的插件管理中找到“仟仟自用插件”，将“是否启用插件”打开。

当前配置项：

| 分组 | 配置项 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `plugin` | `enabled` | `false` | 是否启用插件 |
| `plugin` | `config_version` | `0.1.0` | 配置结构版本 |

`config.toml` 是当前安装实例的运行时配置，不应提交到 Git。

## 测试

先执行静态检查：

```bash
python -m json.tool _manifest.json >/dev/null
python -m py_compile plugin.py
```

再启动 MaiBot，并依次确认：

1. 插件加载日志中出现“仟仟自用插件已加载”。
2. 发送 `/qianqian-ping` 后收到 `pong`。
3. 在正常聊天中让 LLM 复述一段文本，观察其是否发现并调用 `qianqian_echo_text`。
4. 禁用插件后，日志中出现“仟仟自用插件已卸载”。

## 权限与依赖

- 请求能力：`send_message`，仅用于命令回复。
- Python 第三方依赖：无。
- SDK 兼容范围：`2.5.1` 至 `2.99.99`。
- MaiBot Host 兼容范围：`1.0.0` 至 `1.99.99`。

## 常见问题

### 插件没有出现

确认该仓库位于 MaiBot 的 `plugins/qianqian-plugins/`，且 `_manifest.json` 和 `plugin.py` 位于仓库根目录。

### 插件加载失败

检查 MaiBot 日志中的 Manifest 或 SDK 兼容性错误，并确认当前 Host 与 SDK 版本落在 `_manifest.json` 声明的范围内。

### 修改配置后没有生效

优先通过 WebUI 修改配置。必要时重载或重启插件，不要将本地生成的 `config.toml` 提交到仓库。

## 许可

这是仟仟的自用插件，当前未授予公开使用、修改或分发许可（`UNLICENSED`）。

# AGENTS.md

## 仓库定位

这是“仟仟自用插件”的单插件仓库，不是插件集合。仓库根目录就是 MaiBot 插件目录；保持 `_manifest.json` 和 `plugin.py` 位于根目录，不要再嵌套 `plugins/` 或 `qianqian-plugins/`。

## 官方规范

**插件开发：** 开始新增或修改功能、组件装饰器、配置、生命周期、Manifest、依赖或发布信息前，先阅读 [MaiBot Vibe Coding 插件开发指南](https://docs.mai-mai.org/plugin/vibe-coding)。涉及具体组件或 SDK API 时，继续阅读该指南链接的对应专题页；以当前官方文档为行为与兼容性依据。

**群专属头衔：** 修改头衔相关术语、Command、Tool、权限或消息锚定时，阅读 `CONTEXT.md` 和 `docs/specs/group-title.md`。

## 工作流程

1. 先阅读 `_manifest.json`、`plugin.py` 和 README 中与需求相关的部分，确认所有受影响的配置、能力、依赖和用户入口。
2. 按官方文档实现最小范围改动。插件能力使用 `@Tool`、`@Command`、`@HookHandler`、`@EventHandler`、`@API` 或 `@MessageGateway`；`@Action` 只用于维护已有旧代码。
3. 同步契约：依赖与能力写入 `_manifest.json`，配置结构写入 `config_model`，用户可见行为与配置写入 README。
4. 运行“完成标准”中的检查；所有适用项通过后再交付。

## 实现约束

- 插件类继承 `MaiBotPlugin`、声明 `config_model`，并保留 `on_load()`、`on_unload()`、`on_config_update()` 与 `create_plugin()`。
- 配置使用 `PluginConfigBase` 和 `Field`；保留 `[plugin]` 下的 `enabled` 与 `config_version`。Runner 生成的 `/config.toml` 只保存本地运行值。
- 用户可见文本使用简体中文，组件注册名使用 `qianqian_` 前缀。群专属头衔 Command 固定使用 `头衔 <内容>`；其他新增命令默认使用 `/qianqian-...`，避免与其他插件冲突。
- Python 包和插件依赖只在 `_manifest.json` 的 `dependencies` 中声明。
- 机密信息通过运行时配置提供；仓库内容不包含 token、cookie、个人账号、绝对路径或私有 URL。
- 网络调用设置超时并返回可读错误；后台任务、连接与文件句柄由 `on_unload()` 完整清理。
- 改动保持在本仓库内。需要 MaiBot 主程序能力时，先说明原因、影响面与插件侧替代方案，取得许可后再扩大范围。

## 完成标准

每次改动至少通过：

```bash
python -m json.tool _manifest.json >/dev/null
python -m py_compile plugin.py
python -m unittest discover -s tests
git diff --check
```

修改 `plugin.py` 的导入、装饰器、配置模型或工厂函数时，还要使用 Manifest 声明范围内的 SDK 成功导入模块并创建插件实例：

```bash
uv run --no-project --with 'maibot-plugin-sdk>=2.5.1,<3.0.0' \
  python -c 'import plugin; print(type(plugin.create_plugin()).__name__)'
```

交付前确认所有受影响项均已闭环：Manifest 是合法 v2 数据；生命周期与资源清理完整；依赖、能力和配置声明准确；README 覆盖新增或变化的安装、配置、命令、权限与故障排查内容；用户数据、运行时配置和机密信息未进入 Git。

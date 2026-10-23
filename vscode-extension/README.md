# TgEngin for VS Code（本地预览版）

## 使用

1. 在 VS Code 打开要工作的文件夹。
2. 按 `Cmd+Shift+P`，运行 **TgEngin: 启动 / 连接引擎**。
3. 在面板输入需求，点击 **新建任务**，依次选择执行模式、智能体、执行位置、工作目录。
4. 左侧 TgEngin 图标列出最近 100 个任务；点击任务查看最近 200 条消息。每 2.5 秒刷新。
5. 运行中可以输入补充要求，点击 **发送给当前运行任务**。完成的任务不支持直接续聊，请新建任务。
6. **执行树 JSON / 诊断原因** 在旁边打开详情。选中代码后右键 **TgEngin: 用选中代码创建任务**，可带入未保存的选中内容。

工具会直接操作确认的工作目录，不提供修改前审批或自动回滚。请保存相关文件后运行。此版本没有任务取消按钮；关闭面板不会取消任务。终端中的 Ctrl+C 会停止整个引擎，影响该引擎的所有任务。

## 本机启动配置

默认源码目录为 `/Users/zz/工作/TgEngin`，使用该目录下 `.vscode-build/node_modules/.bin/bun` 运行当前源码，读取独立配置 `.scratch/vscode/config.yaml` 与根目录 `.env`。不会把密钥打包进插件。

设置中搜索 `tgengin`，可以修改 **Endpoint / Engine Root / Bun Path / Config Path**。默认 API 地址为 `http://127.0.0.1:7802/api`。如果配置了 API 令牌，执行 **TgEngin: 设置连接令牌**；令牌保存在 VS Code SecretStorage 中。远程地址只连接，不代为启动。

启动日志在 **终端 → TgEngin Engine**。已经运行的引擎会直接连接。插件升级或关闭面板不会主动杀掉引擎，终端生命周期由 VS Code 管理。

## 空数据库初始化

本机已初始化 `work` 模式、`bot` 智能体（DeepSeek）及 `local` 执行位置。日常创建任务选择这三项即可。插件专用配置使用 `reasoningEffort: none`，可在 Config Path 指向的文件中调整。

引擎需要预先声明模式、智能体和执行位置。仓库 `examples/README.md` 的“灌底子”给出了 `/api/declare` 示例；模型密钥需在根目录 `.env` 中配置，修改后重启引擎。

## 开发和打包

插件使用 CommonJS 和 VS Code API，无前端框架或运行时 npm 依赖。从仓库根执行：

```sh
node --test vscode-extension/test/client.test.js
cd vscode-extension
../.vscode-build/node_modules/.bin/vsce package --allow-missing-repository --skip-license
```

这是本地 VSIX 预览版，尚未发布到 Marketplace。当前提供消息轮询与执行树 JSON，尚不支持逐 token 输出、任务暂停/取消、编辑器补丁审阅或完整多轮会话。

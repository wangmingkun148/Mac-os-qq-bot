# QQ 聊天 Bot（Windows 版）

本项目使用 ChatGPT、Claude AI 等生成式 AI 辅助制作，由 [Mac-os-qq-bot](https://github.com/wangmingkun148/Mac-os-qq-bot) 的 macOS 版重构而来。

一个在 Windows 上运行的 QQ 聊天机器人：通过 Windows UI Automation 读取 QQ 桌面客户端（QQ NT）的界面、复制图片、输入回复并点击发送，再回读确认。托盘图标 + 本地网页界面（面板、实时状态窗、设置），Python 后台，适合自己配置 AI 接口后在本机使用。

**所有 AI 任务使用你配置的同一个原生多模态模型。** 没有内置供应商、预设角色或已有聊天资料。聊天判断与回复、群聊风格总结、记忆压缩、网页与视频分析、主动话题、图片审核都走同一个 OpenAI 兼容接口。图片生成使用单独配置的生图接口。

## 功能

- 主群优先监听，按模型判断自然接话；可选扩展到 QQ 会话列表中的其他群和私聊。
- 会话历史和记忆按聊天隔离。收集文字消息后可总结本机的说话风格，并压缩较长摘要；支持回复打分、群友备注和自定义设定。
- 读取新图片并交给多模态模型，复制失败时不猜图。消息发送后回读 QQ 确认；发送结果不确定时暂停，避免重复发送。
- 托盘图标、实时状态窗、请求用量与日志、设置热应用。
- 可选网页阅读、视频字幕与必要画面分析；可选主动话题与人工选择话题预览。
- 可选图片生成：有人明确 @ 并请求生成后审核、生成、发送；按每人滚动 24 小时计算配额。

与 macOS 版的差别：原生菜单栏 SwiftUI 界面换成托盘 + 网页界面；“辅助功能权限”换成 Windows 的 UI Automation（不需要授权）；桌宠和 QQ 空间自动浏览**暂未移植**（见文末“尚未移植”）。

## 环境要求

- Windows 10 1809 或更新版本（建议 Windows 11），64 位；已安装并登录 **QQ NT 版本的桌面 QQ**（9.9.x，界面为 Electron 版）。
- 界面窗口使用系统自带的 Microsoft Edge（没有时用 Chrome）以无边框应用窗口方式显示，InPrivate 模式，不登录、不同步任何账号。
- 现成的 `QQChatBridge.exe` 不需要安装 Python；从源码运行需要 Python 3.12（见下文）。
- 一个 **OpenAI Chat Completions 兼容接口**，模型必须原生支持文字和图片（`image_url`）、中文与 JSON 输出。

供应商名称仅用于显示；实际请求发送到你填写的 URL。服务需返回标准 `choices[0].message.content`。地址可填 `https://你的服务/v1` 或完整的 `/chat/completions` 地址。

## 安装与首次使用

1. 到仓库 **Releases** 下载 `QQChatBridge-windows-x64.zip`，解压到一个你能读写的固定文件夹（不要直接在压缩包里运行，也不要放在 `Program Files`）。保留整个文件夹，`QQChatBridge.exe` 需要旁边的 `prompts/` 和 `config.example.json`。
2. 双击 `QQChatBridge.exe`。程序没有代码签名，SmartScreen 可能提示“未知发布者”：确认下载来自本仓库后点“更多信息 → 仍要运行”。
3. 首次启动会从 `config.example.json` 创建仅本机使用的 `config.json`，并自动打开设置窗口。填写：
   - **本账号昵称**：本账号在 QQ 中显示的昵称（左上角头像旁），不是群友昵称；
   - **主群完整名称**：与 QQ 会话列表里显示的完全一致；
   - **AI 供应商**：接口地址、API Key、模型名称，可选回复后缀、思考强度。
4. 打开并登录 QQ，保持主窗口**不要最小化、不要收进托盘**。建议到设置 → 诊断，点“用防休眠参数重启 QQ”（原因见下）。
5. 点“保存并应用”，再点托盘图标 → “开始”。程序先记录现有消息作为基线，不会回复历史消息。

默认只监听指定主群；其他群和私聊、网页浏览、自动主动话题、生图均默认关闭，按需在设置中启用。启用全会话回复后，仍由模型决定是否接话。

### QQ 被其他窗口盖住时（可选设置）

QQ 基于 Chromium，普通 Chromium 窗口被其他窗口**完全盖住**后会停止更新界面，机器人就会读到旧内容。我们在真实 QQ 上用无障碍操作验证过：QQ 被完全盖住时界面树仍会更新，所以大多数情况下不需要任何设置。如果你发现被盖住后机器人读到旧消息，可以用下面的方式之一启动 QQ，关闭 Chromium 的这个行为：

- 设置 → 诊断 → “用防休眠参数重启 QQ”（会关闭并重新启动 QQ，需要重新登录一次）；
- 或在诊断页点“在桌面创建带参数的 QQ 快捷方式”，以后用它启动 QQ；
- 手动：给 QQ 的快捷方式目标加上 `--disable-features=CalculateNativeWinOcclusion --disable-backgrounding-occluded-windows --disable-renderer-backgrounding`。

用参数启动后，机器人发送完会把焦点还给你原来的窗口（可用 `restore_focus` 配置打开或关闭）。QQ 最小化或收进托盘时一定读不到：最小化时程序会自己把它恢复；收进托盘时会尝试再次启动 QQ 让它显示出来（这一条还没有在真实 QQ 上验证过）。

### 权限与运行方式

- Windows 版**不需要**像 macOS 那样授予辅助功能权限。
- **QQ 若以管理员身份运行，本程序也必须以管理员身份运行**，否则 Windows 会阻止模拟键盘和鼠标。诊断页会提示这种不一致。
- 读取使用 UI Automation，发送文字使用 Unicode 键盘事件（不占用剪贴板），发送与复制图片会临时使用剪贴板并在结束后还原。操作 QQ 时会把 QQ 窗口切到前台，近期有键盘输入时会等待。保持电脑唤醒、联网。
- 不要在机器人操作时同时手动打字或点击 QQ；它会暂停并等你停下。
- 为了判断你是否正在打字，程序安装了一个低级键盘钩子，**只记录“最近一次按键的时间”，不记录按了什么键**，也会忽略程序自己模拟的按键。部分杀毒软件可能对此提示；源码在 `winapp/win32.py` 的 `TypingWatcher`。

## 从源码运行 / 编译

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-windows.txt
.\.venv\Scripts\python.exe -X utf8 -m winapp            # 托盘 + 界面
.\.venv\Scripts\python.exe -X utf8 -m winapp --console  # 无界面，状态打印到控制台
.\.venv\Scripts\python.exe -X utf8 -m winapp --dry-run  # 只读 QQ，不点击、不输入、不发送
```

`-X utf8` 必须带上（程序缺省会自动用它重启一次）：后台按 UTF-8 读写中文文件，而中文 Windows 的默认编码是 GBK。

打包为一个文件夹和 zip：

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
```

产物在 `dist\QQChatBridge\`（约 35 MB）。

## 可选网页和视频功能

基础聊天不需要浏览器依赖。启用完整网页浏览、播放或视频画面分析时，在项目目录建立环境：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-browser.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

设置中将 Python 路径留空（会先查找 `.venv`，现成 exe 则查找 PATH 里的 python），或填 `.venv\Scripts\python.exe` 的完整路径，再开启“浏览器任务”并保存重启。浏览器使用独立环境，不复用你的个人浏览器登录态；需登录的页面可能读不到。没有 Chromium 时，部分网页只尝试通过 Jina Reader 读取文字。视频优先读取字幕，只有无可用字幕或确实需要画面时才抽帧。网页阅读或检索可能访问 Jina Reader、Google News、YouTube 等外部服务。

## 图片生成

**图片生成后很有可能无法自动发送到 QQ，请谨慎使用。生成成功不代表发送成功，即使没发出去也可能已经消耗供应商额度。**

到设置 → 图片 → 图片生成填写完整接口地址、模型名称、API Key、尺寸和每人 24 小时上限，然后启用：

- OpenAI 兼容接口：完整地址以 `/images/generations` 结尾，支持 `data[].b64_json` 或 `data[].url` 返回值。
- 也支持 `multimodal-generation` 类型的 `input.messages` 生图接口；具体尺寸须由服务支持。

生图审核使用同一个聊天 AI，实际图片由独立生图接口生成。配额按最近 24 小时的生成记录计算，不是在午夜统一清零。

## 账号与隐私风险

QQ 可能对使用自动化的账号进行限制或封禁，建议使用小号，并控制回复和主动发言频率。本项目无法保证账号安全。群友的聊天文字、相关上下文、摘要和图片会发送给你配置的 AI 服务商，使用前应告知参与者并确认能接受该服务的数据处理方式；不要让机器人处理不应分享的敏感信息。API Key 和本地聊天记录也应妥善保管，不要上传到公开仓库。

## 数据存放

公开仓库和发布包只有源码、通用提示词、空白配置模板、程序资源和许可文件，**不含作者的 API Key、QQ 号、群名、群聊记录、长期总结、群友资料或旧测试数据**。

运行后产生的数据都在程序所在文件夹里：

| 文件 | 内容 |
| --- | --- |
| `config.json` | 本机账号、主群、接口与密钥等设置 |
| `runtime/messages.jsonl` | 按聊天区分的消息记录 |
| `runtime/style-profile.json` | 自动学习的风格摘要和会话记忆 |
| `runtime/people.json` 等 | 自己添加的群友备注、反馈与统计 |
| `runtime/status.json`、`runtime/live.json` | 当前状态、实时处理说明 |
| `runtime/bridge.log`、`runtime/native.log`、`runtime/backend.log`、`runtime/app.log` | 运行日志与错误 |
| `runtime/ui-profile/` | 界面窗口使用的浏览器临时配置（InPrivate，不含账号） |

`config.json` 和 `runtime/` 已被 Git 忽略。界面只在 `127.0.0.1` 上监听，并要求每次运行随机生成的令牌，其他程序和网页读不到配置里的 API Key。仓库没有上传运行数据的功能，也不要把使用后的整个文件夹重新公开上传。

## 常见问题

- **不回复**：看实时状态窗和日志：是模型决定不接话、接口失败还是发送未确认；检查昵称、主群名称、QQ 窗口是否可见、是否有未发送的草稿。设置 → 诊断能检查 QQ 是否可读、权限是否一致。
- **接口报错**：核对 URL 是否为 Chat Completions 兼容端点、模型名称、密钥和模型的图片能力。供应商拒绝 `response_format`、`temperature` 或 `reasoning_effort` 时会尝试省略对应可选字段。
- **读到的是旧消息**：先看 QQ 是否被最小化或收进托盘；如果是被其他窗口完全盖住，见上文“QQ 被其他窗口盖住时”。
- **图片没读到**：先试右键“复制”是否能在 QQ 里手动完成；读取失败时跳过或说明实际情况，不凭内容猜图。
- **消息停在输入框**：程序会暂停避免重复发送，先人工检查输入框，再点“开始”恢复。
- **运行受键盘输入打断**：程序会等待你停下，以减少把按键送错窗口的机会。
- **QQ 更新后失效**：本项目依赖 QQ 界面的结构（类名、标签），界面更新可能需要适配。
- **为什么不是后台无窗口机器人**：消息读取与发送依赖已登录的 QQ 桌面客户端，因此需要真实窗口。

**本项目仅在作者的个人电脑上测试过，尚未在其他电脑上充分验证，可能存在稳定性问题，也可能无法在你的电脑上运行。** Windows 版的自动化流程在“仿 QQ 页面”上做了端到端测试，也在作者的真实 QQ（9.9.x）的一个测试群里验证过：读取与解析、发送文字（含 emoji、@ 开头）、粘贴发图、右键复制取图、草稿清除、最小化后恢复、整个回复循环（用假 AI）。尚未验证切换到其他会话、QQ 收进托盘后再拉起、多显示器与不同缩放。你的 QQ 版本不同时表现可能不同，请先在只有自己的测试群里试用。

## 尚未移植

macOS 版有、Windows 版暂时没有的功能：

- 像素桌宠；
- QQ 空间自动浏览（点赞/评论）。设置页的定时项目会保留，功能上线后直接生效。

## 目录与开发

- `winapp/`：Windows 外壳。`uia.py`（UI Automation）、`qq.py`（QQ 操作：读取、切会话、发送、取图）、`native.py`（对引擎的接口）、`app.py`（配置与后台线程）、`shell.py`（托盘与窗口）、`webui.py` + `ui/`（本地网页界面）。
- `bridge.py`、`engine*.py`、`llm.py`、`ai_client.py`、`snapshot.py`…：与平台无关的 Python 后台（与 macOS 版相同，只做了 Windows 兼容修补）。
- `prompts/` 为通用规则；`config.example.json` 是公开模板；`AGENT.md` 说明架构与已知限制。
- `tests/`：单元测试 `python -X utf8 -m unittest discover -s tests`。
- `tools/`：开发辅助。`fake_qq/` 是复刻 QQ NT 界面结构的仿真页面，`e2e_fake_qq.py` 用它对真实引擎做端到端测试（读取、回复、切会话、发图、取图），`dev_dryrun.py`、`probe_uia.py`、`selftest_*.py` 用于排查。

MIT 许可证，见 `LICENSE`。附带的 Ark Pixel 字体由 TakWolf 制作，采用 SIL Open Font License 1.1，其声明保留在 `winapp/ui/ArkPixel-OFL.txt`；字体不改用 MIT 许可证。本项目与 QQ 及 AI 服务厂商无官方关联。

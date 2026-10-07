# Windows 版交接

## 范围

本分支（windows-port）把 macOS 版重构为 Windows 版：Python 后台基本不变，外壳从 Swift 换成 Python（UI Automation + 托盘 + 本地网页界面）。只含公开代码和通用资源，不读取或复制私人版的 config、runtime、记录、摘要、角色和表情。构建产物和运行文件不进入 Git。

## 架构

Python 后台（bridge/engine/llm/…）通过一个 `native` 对象读写 QQ：`native.events`（队列，收 paused/configure/proactive_now… 事件）和 `native.call(op, **kwargs)`（snapshot、select、send、send_image、capture_image、capture_latest_image、clear_draft、wake、launch、typing、status、pause、notify、resume）。macOS 版里 native 是 stdin/stdout 上的 JSON 管道，Windows 版是进程内的 `winapp.native.WinNative`。

- `winapp/uia.py`：comtypes 调 UI Automation。QQ NT 是 Electron，Chromium 把 HTML 的 aria-label/文本 → Name、class → ClassName、id → AutomationId，所以 `dump_tree` 产出与 macOS 辅助功能快照相同形状的 JSON，`snapshot.parse_snapshot` 原样复用。聊天输入框（ProseMirror，类名 `ExEditor-qq-msg-editor`）映射为 AXTextArea，值取自 TextPattern，标题取自会话头部。
- `winapp/tree.py`：对 dump 出的树做会话/标题/输入框的纯 Python 计算（可单测）。
- `winapp/qq.py`：各 op 的实现。发送文字：激活 → 聚焦输入框 → Unicode 键盘事件 → 点“发送”按钮（InvokePattern，失败再回车）→ 回读。取图：右键 → “复制” → 读剪贴板；发图：写剪贴板 → Ctrl+V → 点发送。错误码与 macOS 版一致（引擎据此判断“发送不确定→暂停且不重发”）。
- `winapp/win32.py`：SendInput、前台窗口、键盘钩子（用户是否正在打字，忽略自己注入的按键）。`winapp/clipboard.py`：剪贴板读写与保存还原。**剪贴板不能设属主窗口**：属主要响应 WM_DESTROYCLIPBOARD，我们的线程不泵消息，会让其他程序复制时卡死。
- `winapp/native.py`：UIA 与输入注入只在一个工作线程（COM 单元）里串行执行。
- `winapp/app.py`：配置读写、引擎线程生命周期、开始/暂停、诊断。`winapp/shell.py`：托盘（pystray）与窗口宿主（Edge/Chrome `--app` + `--inprivate`，不登录不同步）。`winapp/webui.py`：只绑 127.0.0.1、要求每次运行随机令牌的 HTTP 服务；`winapp/ui/`：面板、状态窗、设置页（原样移植 SwiftUI 界面，像素字体与配色）。
- `winapp/qqlaunch.py`：以防休眠参数启动/重启 QQ，检测运行中的 QQ 是否带参数。

后台的 Windows 兼容修补：`procutil.InstanceLock`（替代 fcntl）、`fsutil.replace`（Windows 下 os.replace 遇共享冲突重试）、`image_prep`（Pillow 替代 sips）、文本读写显式 UTF-8、`temporal_relevance` 无 tzdata 时退回 UTC+8、`launch` op 替代 `open -a`。

## 逻辑与数据

主群优先；可选监听其他可见会话，模型自主判断是否接话。归档、近期历史和记忆按会话隔离，长期表达摘要可共享。新图片通过 QQ 复制后传给多模态模型；失败不猜测。发送需回读确认，状态不明确时暂停。设置热更新等当前任务结束，后缀开关使用最新配置。

运行数据仅存 config.json 和 runtime/，发布包按 `build.ps1` 生成，不包含使用中的文件夹。

## 限制与待验证

- **被完全盖住的窗口**：Edge 上（页面计时器驱动的更新）不带 `CalculateNativeWinOcclusion` 开关时读到旧内容，带开关后实时；真实 QQ 上用无障碍 Invoke 折叠/展开群成员面板验证过，被完全盖住时界面树仍实时更新（`tools/test_occlusion_real.py`）。但“消息到达”这类非无障碍触发的更新是否也实时，还没有用真实消息验证。`qqlaunch` 提供带开关启动/重启 QQ 的备用方案，`restore_focus` 默认只在 QQ 带开关时才把焦点还给用户。
- 已在真实 QQ 9.9.x 的“测试群”里验证：读取与解析、输入并发送文字（含 emoji、中文标点、@ 开头）并回读确认、粘贴发图并回读、右键“复制”取图、草稿清除、最小化后唤醒、整个引擎循环（用假 AI）。没有验证：切换到另一个会话（需要打开别的聊天）、QQ 收进托盘后重新拉起、多显示器/不同缩放。
- QQ 有多个标题为“QQ”的窗口（含隐藏的登录/启动窗口）：主窗口按“有会话列表”识别并记住，不要按标题或大小挑。QQ 的容器节点（aio、ml-item、qq-msg-editor__root）不在 UIA 控件视图里，必须从缓存的整棵树定位元素（`winapp.qq.View`），实时 FindFirst 找不到。
- 粘贴的图片在输入框里是 `editor-el--inline-block` 元素；剪贴板里只有注册格式 PNG 时 QQ 不接受，必须带 CF_DIB。
- 会话键使用显示名称，重名、改名或不可见列表有局限。
- QQ 以管理员身份运行时，本程序也要以管理员身份运行。
- 未移植：桌宠、QQ 空间。
- API 服务需支持多模态和约定 JSON 输出；供应商专有协议不自动适配。
- 图片生成成功后仍很可能无法自动发到 QQ，README 明确标注谨慎使用。

## 构建与资源

`build.ps1`：PyInstaller 一个文件夹（`--python-option "X utf8"`，带 `comtypes.gen`）。浏览器依赖见 requirements-browser.txt，Windows 依赖见 requirements-windows.txt。代码采用 MIT；Ark Pixel 字体保留其 OFL 声明（winapp/ui/ArkPixel-OFL.txt）。README 和注释只解释功能，不记录开发流水。

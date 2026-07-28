# Cardputer 界面与 Codex 状态

Cardputer 使用 240×135 像素界面。下面两张 4 倍预览图由当前固件布局、随固件
发布的背景与宠物帧、RGB565 配色和安全示例文案确定性生成。它们不是相机实拍，
也不会读取真实 Codex 会话、提示词、命令或对话记录。

| 主页 | Codex 详情页 |
| --- | --- |
| ![选中 Codex 卡片的 Cardputer 主页](images/device-home.png) | ![工具运行中的 Codex 详情页](images/codex-detail.png) |

修改设备布局或宠物资源后，用下面的命令重新生成两张图：

```sh
python3 tools/render_ui_screenshots.py
```

## 主页与详情页

主页持续显示当前 Codex 状态，右侧有 Wi-Fi、已配对 Mac、亮度和自动息屏四个
入口。选中 Codex 卡片并按 `Enter` 即可打开详情页。

详情页最多可查看八个会话。标题依次使用会话标题、项目名和 `Codex` 作为降级
内容。正文只显示 `Editing project files` 这类经过隐私裁剪的活动摘要；提示词、
对话记录、推理、原始命令、工具参数和命令输出都不会转发。左右键切换会话，
`1/8` 徽标表示当前位置，Esc 返回主页。

## Codex 视觉状态与文案

协议提供六种 Agent 状态。固件把 `running` 进一步拆为 `THINKING` 和
`RUNNING`，所以屏幕上一共有七种视觉状态。状态不只依赖颜色表达：宠物动画、
工作台监视器、数据管道、平台特效和主页状态条都会一起变化。

| 视觉状态 | 上游状态 | 主页标签 | 详情页常见文案 | 样式 |
| --- | --- | --- | --- | --- |
| 离线 | Mac 链路断开，或 `offline` | `OFFLINE` | Mac 链路断开时显示 `Codex Deck is offline` | 失败宠物配红色 X 指示；真正断线时宠物上还会出现灰色斜线 |
| 空闲 | `idle`、没有选中会话，或 Agent 状态流不可用 | `IDLE` | 已连接但无可用会话时显示 `Waiting for Codex sessions`；确认提醒后显示 `Session ready` | 灰色空闲宠物、电源符号、安静的数据管道和短主页状态条 |
| 思考中 | `running` + `thinking`；缺少 phase 时也按此状态处理 | `THINKING` | `Understanding the task`、`Understanding the task...` 或 `Thinking...` | 等待宠物、较慢的青色遥测动画和移动主页状态段 |
| 执行中 | `running` + `tool` | `RUNNING` | `Editing project files`、`Running a command`、`Searching references`、`Working with an image` 或 `Running tests` 等安全摘要 | 运行宠物、更快的青色遥测、数据包、平台层和更宽的移动主页状态段 |
| 等待输入 | `needs_input` | `INPUT` | `Waiting for your approval` 或 `Waiting for your answer` | 等待宠物配橙色提示光标、呼吸式数据管道和脉冲主页状态条 |
| 已完成 | `ready` | `READY` | 通常为 `Task completed`；最后一条安全公开活动也可能保留 | 检查宠物配绿色对勾、填满的数据管道、完成平台特效和实心主页状态条 |
| 已阻塞 | `blocked` | `BLOCK` | `Task encountered a problem` | 失败宠物配红色 X 指示、断开的数据管道和实心主页状态条 |

处于 `READY` 或 `BLOCK` 时按 `Enter`，会确认 Cardputer 上的提醒：会话转为
`IDLE`，未读标记清除，详情文案变为 `Session ready`。这只是 Cardputer 视图
中的确认操作，不会修改或重新启动 Codex 任务。新的用户提示会自动把焦点切回
对应会话。

## 空状态与降级文案

| 条件 | 详情页标题 | 详情页正文 |
| --- | --- | --- |
| Mac 链路断开 | `Codex` | `Codex Deck is offline` |
| Mac 已连接，但没有可用的 Codex 会话 | `Codex` | `Waiting for Codex sessions` |
| 有活动会话 | 会话标题、项目名或 `Codex` | 最近一条经过隐私裁剪的活动摘要 |

## 额度样式

详情页的两行额度分别标为 `WEEKLY` 和 `5H`。

| 模式 | 显示方式 |
| --- | --- |
| ChatGPT 订阅 | 用进度条显示剩余百分比：30–100% 为绿色，低于 30% 为黄色，低于 10% 为红色。0% 仍保留一个红色像素标记；服务未返回某个窗口时显示 `--`。 |
| API Key 或自定义 Provider | 显示静态满格绿色轨道。ChatGPT 订阅额度窗口不适用，因此界面不会显示容易误解的百分比或无穷符号。 |
| 未知，或 Agent 状态流离线 | 灰色描边轨道中显示 `--`，不会错误标成无限额。 |

## 键盘模式指示

键盘图标位于主页状态栏最左侧，并悬浮在详情场景左上角。青色实心键盘表示键盘
转发模式已启用；如果麦克风没有静音，音频通道也会工作。带红色斜线的灰色描边
键盘表示当前使用本地导航，转发关闭。BtnA 只切换这个模式，不会改变当前页面。

## 电池与省电行为

主页状态栏和 Codex 详情场景都会在电池图标旁显示数字百分比。检测到外部 USB
供电或持续充电趋势时，图标和百分比会变为橙色，电池内部同时显示闪电符号。
Cardputer ADV 没有把充电芯片的专用状态脚连接到 MCU，因此连接电脑 USB 时可以
立即识别；使用纯充电器时，需要经过数次平滑采样后才会显示充电状态。

无输入 15 秒后背光会自动降低；达到所选的自动息屏时间后，背光与 LCD 控制器
都会进入休眠。任意输入会按设置亮度唤醒屏幕。无人操作时，静态界面也会降低
整帧刷新频率；活动中的 Codex 状态仍保留较流畅的动画。

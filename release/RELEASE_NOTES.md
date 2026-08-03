# CardBridge 1.1.0

- Build 13 fixes standalone Ctrl/Cmd/Option/Shift release flags after the
  multi-device keyboard owner merge, rejects buffered input from replaced
  same-ID sessions, keeps incremental topic subscriptions, bounds slow-device
  writes and disconnect cleanup, serializes concurrent downlinks per device,
  and refreshes paired-device metadata on authenticated reconnect.
- App startup now probes an existing Unix socket instead of trusting the path
  alone, and automatically replaces a still-shutting-down incompatible Agent
  during an in-place client update.
- Installed-state health checks now require the exact Agent build and wait past
  transitional startup/shutdown snapshots instead of reporting a false pass.
- Firmware build 9 records the already-generated protocol 2.1 source identity;
  the keyboard fix is in the desktop Agent and does not require a firmware
  flash.
- 内置 `CardBridge Microphone` HAL 驱动，首次启动一次授权即可安装。
- 麦克风以 input-only USB 兼容设备提供给 Typeless，CardBridge 通过独立 Feed 写入，避免 BlackHole 路由回放冲突。
- Cardputer 切入键盘模式时才启动麦克风，退出后立即停止采集和传输。
- 保留 BlackHole 作为未安装新驱动时的兼容回退。
- Accessibility 只由实际注入按键的 CardBridgeAgent 请求，避免主 App 显示已授权而 Agent 仍被拒绝。

# CardBridge 1.0.0 RC

- 新增原生 macOS 菜单栏 App，启动后自动桥接 Cardputer ADV。
- 显示 M5、键盘权限、BlackHole 音频和 Codex 连接状态。
- 内置并守护独立 Bridge Agent，支持登录启动和崩溃自动恢复。
- 保留已有配对并把配对密钥迁移到 macOS Keychain。
- 增加协议/能力协商、版本兼容提示、诊断导出和 Sparkle 自动更新基础。
- Wi‑Fi/VPN 地址变化后自动刷新 Bonjour，BlackHole 或 Codex 缺失时保持降级运行。
- 增加中英文界面、VoiceOver 状态和 App 内 Codex Hooks 管理。
- Codex 详情页改为 1:1 RPG 布局：左侧 100×100 宠物，右侧公开实时文案与紧凑 Weekly/5H；API、自定义提供方和读取失败使用明确的 Unlimited/灰色降级语义。
- 最终实机版使用原生 13px 中文字库和 17px 正文行距，避免缩放字距异常；Unlimited 条改为低饱和慢速彩虹渐变，并显示完整的无限符号。
- 无需 Hook 也会每 2 秒同步最近 8 个 Codex 会话，并跟随最后收到用户消息的会话；后台输出不会抢屏，Hook 启用后继续提供更即时、具体的运行状态。
- Codex 左半屏顶部新增居中的 `1/8` 会话位置徽标，可用左右键浏览历史，新用户消息到达时自动恢复跟随。

本候选版包含 CardBridge / Agent `1.0.0` build 6 与 Cardputer 固件 `0.2.0` build 7。

当前候选版仅支持 Apple Silicon，最低系统为 macOS 13。

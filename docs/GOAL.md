# GOAL — Codex Deck 多设备与桌面 Agent 标准化

> **状态：当前实施目标（2026-08-02）**
>
> 本文档是本仓库当前工作的唯一目标定义（single source of truth）。它描述
> “先标准化桌面端同步软件”的交付边界。安装、构建、权限、安全与品牌规则仍以
> [`INSTALL.md`](INSTALL.md)、[`DEVELOPMENT.md`](DEVELOPMENT.md)、
> [`ARCHITECTURE.md`](ARCHITECTURE.md)、[`PROTOCOL.md`](PROTOCOL.md)、
> [`BRANDING.md`](BRANDING.md)、根目录 [`SECURITY.md`](../SECURITY.md) 和
> `version.json` 为准；发生冲突时，安全和兼容性规则优先。

## 1. 背景与问题

Codex Deck 当前已经能让 M5Stack Cardputer ADV 通过局域网连接 Mac，使用无线
键盘、无线麦克风、Codex 会话状态和限额显示。但实现仍带有明显的“单一 M5
设备”假设：桌面 UI 只重点展示第一台设备，并发配对只有一个全局状态，所有
音频流共用一个抖动缓冲区，部分 Codex 已读状态也是全局的。

下一步需要接入微雪等其他 ESP32 设备。桌面端不能继续为每块硬件编写专用分支，
而应成为一个与设备型号无关、能力可协商、可同时服务多台设备的标准化 Codex
Deck Agent。M5 固件从产品唯一客户端变为标准设备协议的一个客户端实现。

目标关系如下：

```text
旧 M5 固件 ── legacy 兼容路径 ──┐
当前 M5 固件 ─ 标准能力客户端 ──┤
微雪固件 ───── 标准能力客户端 ──┼─ Codex Deck Agent ─ Codex App Server
未来其他设备 ─ 标准能力客户端 ──┘          │
                                      CardBridge.app
```

这里的“拆开”是协议、实现和发布周期解耦，不是停止 M5 支持，也不是删除现有
CardBridge 技术标识。

## 2. 本 Goal 的交付边界

### 2.1 必须完成

1. 桌面 Agent 同时维持多台已认证设备连接。
2. 不按厂商或板型做白名单；其他 ESP32 固件实现标准协议后可以发现、配对、
   鉴权并使用自己声明的能力。
3. 建立可版本化、可订阅、按 capability 下发的标准状态响应。
4. 多设备下正确提供：
   - 基础同步信息；
   - 麦克风桥接；
   - 键盘控制；
   - 本地网络状态；
   - Codex 会话和运行状态。
5. 新增 Token 消耗统计和实时/准实时 Token 流统计。
6. 保持已发布 M5 固件无需更新即可继续连接和使用原有功能。
7. macOS 菜单栏 App 能正确展示和管理多台设备，而不是只展示第一台 M5。
8. 补齐协议文档、模拟设备、回归测试和机器可验证的验收证据。

### 2.2 本 Goal 不做

1. 不在本 Goal 内实现或烧录微雪设备固件。微雪固件是标准桌面 Agent 完成后的
   下一个独立 Goal。
2. 不要求修改、升级或重新烧录现有 M5 固件。
3. 不把 TCP/UDP 局域网协议替换成云服务、MQTT 或公网 API。
4. 不让 ESP32 直接读取 Codex 配置、`auth.json`、完整 transcript、reasoning、
   命令、工具参数或命令输出。
5. 不把多路麦克风混音后冒充单一清晰输入，也不在本阶段创建“一设备一个”HAL
   虚拟声卡。
6. 不顺带重命名 `CardBridge.app`、`cardbridge` Python 包、mDNS 服务、端口、
   Keychain 项、配置目录或音频设备。
7. 不在未经用户单独批准的情况下安装 App、替换已安装 Agent、触发 macOS 权限
   授权或烧录硬件。

## 3. 不可破坏的兼容基线

以下能力是现有产品行为，不是本 Goal 重新设计的可选项：

- mDNS 服务 `_cardbridge._tcp` 保持不变。
- TCP 控制端口默认 `7788`，UDP 音频端口默认 `7789`。
- TCP 继续使用最大 4096 字节的 UTF-8 JSON 行协议。
- 配对继续使用六位短码和长期随机 token；认证后 TCP 消息继续携带 token。
- UDP 继续使用现有 PCM16/16 kHz/mono/20 ms/HMAC8 数据包格式。
- `key`、`ping`、`pong`、`agent_status`、`agent_list_req`、`agent_list`、
  `agent_ack`、`hello_ok`、`pair_required`、`paired` 和 `upgrade_required` 的现有
  语义必须保留。
- 缺失协议字段的固件继续按 legacy protocol v1 接受。
- 已支持的 protocol v2 M5 固件继续按当前 capability 列表工作。
- 未知消息类型必须忽略，不能因此断开连接。
- 现有 `~/.cardbridge` / Keychain 配对数据原地迁移，不重新配对、不丢 token。
- `CardBridge Microphone` 和 `CardBridge Microphone Feed` 的现有音频路径保持可用。
- Codex 公共状态继续执行隐私裁剪，不因 Token 功能扩大数据暴露范围。

任何需要破坏上述项目的设计都属于新的协议 major 版本，不得在本 Goal 中采用。

## 4. 目标架构

桌面 Agent 应形成以下内部边界：

```text
TCP 7788 ─ DeviceRegistry ─ DeviceSession ─ Capability/Subscription Router
                 │               │                         │
                 │               ├─ held keys              ├─ bridge.status
                 │               ├─ pairing/auth           ├─ network.status
                 │               ├─ read/ack cursor         ├─ codex.sessions
                 │               └─ audio state             └─ codex.usage
                 │
UDP 7789 ─ authenticated routing ─ per-device jitter ─ AudioLease ─ HAL Feed
                 │
Codex App Server ─ AgentStore + TokenUsageStore ─ bounded public snapshots
                 │
owner-only Unix socket ─ CardBridge.app multi-device UI
```

### 4.1 DeviceSession

每条已认证连接必须拥有独立 `DeviceSession`，至少保存：

- 稳定 `device_id`；
- 设备名称、型号、厂商（若客户端提供）、固件版本和 build；
- peer 地址、连接时间、最后活动时间；
- 协商后的协议版本与 capability 集合；
- 订阅主题与最小更新间隔；
- 本连接按住的键；
- 本设备音频包计数、音频缓冲和麦克风租约状态；
- 本设备自己的 Codex 提醒已读/确认游标。

同一个 `device_id` 同时出现两条已认证连接时，新连接应原子替换旧连接。替换前
必须释放旧连接持有的按键和麦克风租约，不能让同一设备重复出现在在线列表中。

### 4.2 DeviceRegistry

`DeviceRegistry` 是在线设备的唯一事实来源。业务代码不得继续通过
`devices.first`、单个全局 token 或单个全局 pairing 状态推断“当前设备”。

设备类型只能影响展示文字和 capability，不得影响认证资格。有效、稳定且长度
合规的 `device_id` 即可参与配对；设备型号不是安全边界。

### 4.3 并发配对

配对请求必须按连接或 `device_id` 隔离，允许两台新设备同时等待各自的六位码。
每个请求独立记录创建时间、失败次数和失效时间。macOS App 必须能同时显示多个
待配对请求及其设备信息。

现有三次错误后断开的防暴力破解规则继续生效，且计数不得在设备之间共享。

## 5. 标准设备协议

### 5.1 版本策略

- 沿用 `version.json` 作为版本和 capability 唯一来源。
- 本 Goal 使用兼容性新增，不升级 device protocol major。
- 实现完成时将 device protocol minor 从 `2.0` 提升到 `2.1`。
- 若本地 Agent API 新增字段或命令，将 Agent API minor 从 `1.0` 提升到 `1.1`；
  major 保持不变。
- `version.json` 必须把“Agent 支持的 capability”与“本仓库当前 M5 固件实际实现
  的 capability”拆成不同 profile。禁止继续把新服务端能力追加到一个由 Python
  Agent 和 C++ 固件共同生成的数组，否则重新构建 M5 固件会虚假声明自己支持
  `sync`、Token 或音频租约。
- Python 生成常量表示 Agent/server capability；C++ 生成常量只表示 Cardputer
  固件已经实现的 capability。未来其他设备维护自己的 capability profile。
- 修改 `version.json` 后必须运行 `python3 tools/generate_versions.py`，禁止手改
  生成的 Python、C++、Swift 和 release compatibility 文件。
- 协议 minor 协商使用双方较小值；客户端未声明的新能力不得自动启用。

### 5.2 Hello 与 capability

继续接受现有 hello。新设备应发送：

```json
{
  "t": "hello",
  "dev_id": "stable-device-id",
  "token": null,
  "device": {
    "vendor": "waveshare",
    "model": "esp32-s3-touch-amoled-1.75c",
    "name": "Desk Orb",
    "firmware": "0.1.0",
    "build": 1
  },
  "protocol": {"major": 2, "minor": 1},
  "capabilities": [
    "sync.subscribe.v1",
    "bridge.status.v1",
    "network.status.v1",
    "agents.snapshot.v1",
    "usage.tokens.v1"
  ]
}
```

`hello_ok` / `paired` 中现有字段保持不变，`capabilities` 继续表示服务端与客户端
的交集。设备未声明的 capability 不能因为服务端支持就被强行下发。

现有 capability 保持：

- `control.keys.v1`
- `audio.pcm16-16k.v1`
- `agents.snapshot.v1`
- `agents.phase.v1`
- `quota.v1`

本 Goal 新增：

- `sync.subscribe.v1`
- `bridge.status.v1`
- `network.status.v1`
- `usage.tokens.v1`
- `usage.tokens.stream.v1`
- `audio.lease.v1`

### 5.3 标准主题响应

新的标准响应采用“按主题的小快照”，禁止把全部状态塞入一个可能超过 4096
字节的大对象。协商到对应 topic capability 的设备可发起一次性读取：

```json
{"t":"sync_req","id":7,"topics":["bridge.status","network.status"],"token":"…"}
```

```json
{
  "t": "sync_snapshot",
  "id": 7,
  "topic": "bridge.status",
  "schema": 1,
  "seq": 42,
  "generated_at_ms": 1785690000000,
  "data": {},
  "token": "…"
}
```

只有额外协商到 `sync.subscribe.v1` 时才能订阅：

```json
{
  "t": "sync_subscribe",
  "topics": ["codex.sessions", "codex.usage"],
  "min_interval_ms": 500,
  "token": "…"
}
```

后续变更使用同一 envelope，消息类型为 `sync_update`。取消订阅使用
`sync_unsubscribe`。服务端用 `sync_subscribed` 确认最终 topics 和经过边界处理的
`min_interval_ms`；取消成功返回 `sync_unsubscribed`。`id` 若存在必须原样回传。
`schema` 是主题 payload 版本，不能用设备协议 minor 代替。

topic 与 capability 的映射固定为：

| topic | 读取快照所需 capability | 接收实时更新的额外 capability |
|---|---|---|
| `bridge.status` | `bridge.status.v1` | `sync.subscribe.v1` |
| `network.status` | `network.status.v1` | `sync.subscribe.v1` |
| `codex.sessions` | `agents.snapshot.v1` | `sync.subscribe.v1` |
| `codex.usage` | `usage.tokens.v1` | `usage.tokens.stream.v1` + `sync.subscribe.v1` |

请求未协商 capability 的 topic 必须返回 `capability_required`，不能因为 Agent
全局支持该 topic 就越权下发。

每条响应必须满足：

- 有稳定 `t`、`topic`、`schema`、`seq` 和时间戳；
- `data` 只包含该主题数据；
- 不超过现有 4096 字节控制行限制；
- 保持 UTF-8；
- 认证后继续带连接 token；
- 同一主题 `seq` 单调递增；
- 不支持的主题返回结构化 `error`，不能断连；
- 对旧设备不得主动发送任何 `sync_*` 消息。

### 5.4 主题定义

#### `bridge.status`

至少提供：Agent 状态、版本/build、协商协议、运行时长、权限可用性、音频输出
是否就绪、当前活动麦克风设备 ID、全局问题代码。不得包含 token 或绝对敏感
路径。

#### `network.status`

至少提供：本地网络是否可用、Agent 可达 LAN 地址、TCP/UDP 端口和 mDNS 服务
名。不得提供 Mac 保存的 Wi-Fi 密码，也不要求提供 SSID。

#### `codex.sessions`

复用现有隐私裁剪后的 Codex 会话模型，最多 8 个会话。允许包含 ID、短标题、
项目目录末级、公开状态、公开阶段、短活动说明、更新时间和本设备的未读状态。
不得包含完整 prompt、transcript、reasoning、原始工具参数或输出。

#### `codex.usage`

提供 Token 可用性、数据来源、更新时间，以及按会话的累计和最近一次统计。字段
见第 8 节。

## 6. 多设备基础功能

### 6.1 基础信息同步

所有设备共享同一个经过裁剪的 Mac/Codex 事实源，但订阅、推送频率、未读状态和
最近确认位置按设备隔离。慢设备或断开的设备不能阻塞其他设备。

状态广播必须合并高频更新，并遵守每个订阅的 `min_interval_ms`。服务端可以提高
过低的请求值，允许范围为 250 ms 至 60 s；实际采用值应在订阅确认中返回。

### 6.2 键盘控制

- 只有协商到 `control.keys.v1` 的设备可发送 `key`。
- 每个 `DeviceSession` 独立记录 held keys。
- 全局键盘路由必须处理同一按键被多设备同时按住的情况：只有最后一个持有者
  释放时才向 macOS 注入最终 key-up。
- 设备断开、被取消配对或被同 ID 新连接替换时，只释放该设备持有的键。
- 一台设备的异常消息不得清空其他设备的按键状态。
- 现有 Accessibility 授权边界保持不变。

### 6.3 麦克风桥接

macOS 当前只有一个公开 `CardBridge Microphone`，因此多设备连接不等于多路声音
同时混合。采用明确的单活动麦克风租约：

1. 每台设备拥有独立序列状态、抖动缓冲和统计。
2. 没有租约时，第一台发送有效认证音频的设备自动取得租约；这保证旧 M5 固件
   无需发送新命令。
3. 租约持有者持续把音频送入 HAL Feed。
4. 其他设备的包仍需鉴权和计数，但不得混入输出；支持 `audio.lease.v1` 的设备
   应收到 busy/owner 状态。
5. `audio_claim`、`audio_release` 和服务端 `audio_lease` 状态仅对协商到
   `audio.lease.v1` 的设备启用；显式 claim 在租约忙时返回 busy，不能静默抢占。
6. 持有者断开、取消配对、显式 release，或超过实现中记录并测试的静音超时后，
   释放租约并清空该流残留缓冲。
7. 租约切换必须重置输出边界，不能把两台设备的序列号或残余采样拼在一起。

不允许把所有 UDP 包继续送入同一个全局 jitter buffer。

### 6.4 本地网络

网络地址变化后继续刷新 mDNS，不重启整个 Agent。`network.status` 变化应推送给
已订阅的新设备；旧 M5 的重连和发现路径保持原样。

### 6.5 Codex 状态

Codex 会话事实可以共享，但 `agent_ack` 和标准主题中的 acknowledge 必须按发起
设备保存。A 设备确认完成提醒不能替 B 设备清除提醒。

新用户 Prompt 仍是全局焦点来源；后台工具和输出不能重排最近会话。现有最多
8 个会话和 4096 字节上限继续生效。

## 7. macOS App 与本地 Agent API

owner-only Unix socket 的安全模型保持不变。状态快照必须继续不包含配对 token。

本 Goal 要求 App：

- 菜单栏展示在线设备数量和全部在线设备，不再只读取 `devices.first`；
- 使用设备实际 `name/model/vendor`，不把所有设备写死为 “Cardputer ADV” 或 “M5”；
- 同时展示多个待配对请求；
- 设置页继续列出全部已配对设备，并标记在线状态；
- 展示每台设备的协议、固件、capability、最后活动和音频租约状态；
- 全局显示网络、Accessibility、HAL 音频和 Codex 健康；
- Token 统计在可用时展示，不可用时明确显示“不可用/未知”，不得显示伪造的 0；
- 诊断导出继续脱敏，不包含 token、配对码、prompt、命令输出或音频。

本地 Agent API 的新增字段应使用 minor-compatible 方式。Swift 解码不得因为旧
Agent 缺少新字段而直接丢弃整个快照；App/Agent major 不匹配仍应明确失败。

## 8. Token 消耗与实时 Token 流

### 8.1 数据源

当前 Codex App Server 稳定协议提供 `thread/tokenUsage/updated`。实现应消费该
通知中的：

- `threadId`
- `turnId`
- `tokenUsage.total`
- `tokenUsage.last`
- `tokenUsage.modelContextWindow`

每个 breakdown 至少包含：

- `totalTokens`
- `inputTokens`
- `cachedInputTokens`
- `outputTokens`
- `reasoningOutputTokens`

可选的 `account/usage/read` 只能作为账户汇总补充，不能替代线程级通知，也不能
假设所有认证模式或自定义 provider 都提供该接口。

### 8.2 标准表示

`codex.usage` 必须有明确状态：

```json
{
  "available": true,
  "source": "codex_app_server",
  "updated_at_ms": 1785690000000,
  "sessions": [
    {
      "id": "thread-id",
      "turn_id": "turn-id",
      "total": {
        "total": 12000,
        "input": 9000,
        "cached_input": 6000,
        "output": 2500,
        "reasoning_output": 500
      },
      "last": {},
      "model_context_window": 258400
    }
  ]
}
```

字段缺失或 provider 不支持时返回：

```json
{"available":false,"source":"unavailable","reason":"provider_unsupported"}
```

未知与真实零必须严格区分。

### 8.3 实时/准实时统计

`usage.tokens.stream.v1` 基于相邻累计通知计算 delta，并可提供：

- 本次新增 input/cached input/output/reasoning/total；
- 统计窗口 `window_ms`；
- `tokens_per_second`；
- 对应 session 和 turn；
- 事件时间。

“实时”定义为收到 Codex App Server 通知后及时更新，不承诺上游每生成一个 Token
就产生一条通知。必须对高频事件合并/限流，设备下行最大 4 Hz；最终真实通知频率
需要用至少一个实际 Codex turn 记录不含内容的时间和计数证据。

进程重启后，如果上游没有历史 Token 数据，不得伪造重启前统计。除非存在明确、
稳定且经过测试的官方来源，否则本 Goal 不要求自行扫描本地历史文件补算。

## 9. 向后兼容实现规则

兼容不能只靠“旧固件大概会忽略”，必须由自动测试证明：

1. legacy v1 hello（缺失 `protocol` 和 `capabilities`）仍可配对、重连、发键盘、
   发音频、收心跳和原有 Agent 状态。
2. 当前已发布 M5 protocol v2 hello 与 capability 列表保持可用。
3. 旧设备不请求、不声明新能力时：
   - 不收到 `sync_*`；
   - 不收到 Token 流；
   - 原有 `agent_status`/`agent_list` 结构与大小保持可解析；
   - 不需要主动调用任何新接口。
4. 新增字段只能是旧解析器会忽略的可选字段；新增行为优先使用新消息类型和
   capability gate。
5. 配置 schema 迁移必须是原地、幂等和可重复执行的；旧记录缺少 vendor/model
   等字段时使用安全默认值。
6. 旧设备自动取得音频租约的路径必须经过测试，不得要求 `audio_claim`。
7. 旧设备 `agent_ack` 在服务端内部改为 per-device 语义，但线格式不变。

## 10. 安全与隐私要求

- 所有认证后设备消息继续验证 token；UDP 继续验证 HMAC。
- capability 不是认证，设备型号也不是认证。
- 不记录、打印、导出或下发真实 pairing token。
- 不记录或导出 Wi-Fi 密码、API key、`auth.json`、transcript、reasoning、原始
  prompt、命令、工具参数、命令输出或音频。
- 不为了 Token 统计读取 `auth.json` 或解析敏感 transcript。
- 配对码只能显示给本机用户，继续执行失败次数限制和过期处理。
- 本地控制 socket 保持 owner-only 并校验 UID。
- 多设备不得扩大键盘注入权限；未配对设备不能发送键盘或音频。
- 任何管理员、Accessibility、Local Network、Microphone、Keychain 或 Codex Hook
  信任提示都必须停下等待用户决定。

## 11. 实施工作包

建议按以下顺序实施，避免多个执行者同时重写 `server.py` 和版本文件：

### W1 — 协议与兼容夹具

- 更新 `docs/PROTOCOL.md`，固定消息和主题契约。
- 扩展 version/capability 定义并生成所有语言常量。
- 为 legacy v1 和当前 M5 v2 建立黄金握手/消息夹具。
- 先写并发连接、并发配对、capability gate 和消息大小测试。

### W2 — 多设备核心

- 引入 `DeviceSession` / `DeviceRegistry`。
- 把 pairing、held keys、subscriptions、ack cursor 和统计迁入设备作用域。
- 实现同 ID 原子替换和无残留断开清理。
- 保持旧 handler 的线格式。

### W3 — 键盘与音频路由

- 实现多设备键盘持有关系。
- 实现每设备音频状态、独立 jitter 和单活动租约。
- 验证同 IP 多设备仍能通过不同 token/HMAC 正确路由。
- 增加切换、超时、断线和旧 M5 自动租约测试。

### W4 — 标准同步与 Token

- 实现主题快照、订阅、合并、限流和 capability gate。
- 扩展 Codex monitor/store 消费 Token usage 通知。
- 实现累计、delta、rate 和 unavailable 状态。
- 保证每条设备消息不超过 4096 字节。

### W5 — macOS App

- 扩展本地 Agent API minor-compatible snapshot。
- 完成多设备、多配对、租约和 Token UI。
- 更新本地化和脱敏诊断。
- 添加 Swift 解码、旧快照兼容和多设备视图模型测试。

### W6 — 集成与文档

- 扩展 `bridge/fake_device.py`，可指定 ID、vendor、model、capability，并能同时运行
  多实例。
- 更新架构、协议、开发和故障排查文档。
- 运行完整测试/build gate，记录结果和未执行的实机项。

并行开发时，应先合入或冻结 W1 的接口；之后按文件所有权分工。修改
`server.py`、`version.json`、生成版本文件和 `BridgeSnapshot.swift` 的工作必须有
明确单一所有者，避免两个实现者生成彼此不兼容的协议。

## 12. 验收标准

### 12.1 自动化验收

以下全部通过才算代码实现完成：

1. 两个不同 ID 的 fake devices 同时在线，快照稳定显示两台，任一断开不影响另一台。
2. 型号为 `waveshare-esp32-s3-touch-amoled-1.75c` 的模拟设备不靠 M5 特判完成
   发现后的配对、鉴权和标准主题读取。
3. 两台未配对设备可同时获得互不覆盖的配对请求和错误计数。
4. 同 ID 第二条连接替换第一条，旧连接 held keys、订阅和音频租约全部清理。
5. 两台设备同时操作不同按键，以及同时持有同一按键，macOS 注入序列正确。
6. 两路合法 UDP 流序列互不污染；只有租约持有者进入 HAL Feed；释放后另一台可接管。
7. legacy v1 与当前 M5 v2 兼容夹具完整通过，旧客户端不收到新消息。
8. 两台设备都能收到 Codex 公共状态，但 A 的 ack 不改变 B 的未读状态。
9. Token 通知能生成累计、last、delta 和 rate；回退、重复、乱序或重启不会产生
   负数或虚构统计。
10. provider 不支持 Token 时返回 explicit unavailable，不显示 0 或 unlimited。
11. 最坏 CJK 会话标题、8 会话和 Token 数据仍通过分主题消息保持每行 ≤4096 字节。
12. owner-only socket 快照、诊断和日志中搜索不到 token 或其他禁止数据。
13. `python3 tools/generate_versions.py --check` 通过。
14. `./scripts/test.sh` 通过，包括 Python、Swift 和可用时的固件 build。
15. `./scripts/build.sh` 和 App artifact validation 通过。

### 12.2 旧 M5 实机回归

不更新、不烧录旧 M5 固件，使用当前已安装固件验证：

- 自动重连原有配对；
- 键盘 down/up 和 Typeless 热键正常；
- 麦克风持续桥接正常；
- Codex 会话、阶段和 quota 正常；
- 新桌面 Agent 支持新接口后，旧固件没有报错、升级要求或强制新调用；
- 与第二台模拟/真实设备同时在线时仍稳定。

实机烧录不是本 Goal 的默认动作。需要替换已安装 App/Agent、触发权限或进行硬件
操作时，执行者必须先取得用户明确批准。

### 12.3 Token 实际会话验收

运行一个真实 Codex turn，仅记录非内容型证据：通知次数、时间戳、各类 Token
计数和最终累计。确认：

- 数值单调且与上游最终通知一致；
- UI/模拟新设备能看到累计和流速变化；
- 旧 M5 没有收到 Token 消息；
- 没有记录 prompt、response、reasoning 或工具输出。

## 13. 完成定义

只有同时满足以下条件，本 Goal 才能标记完成：

- 标准协议、capability、主题和兼容策略已经文档化；
- 多设备连接、配对、键盘、音频、Codex 状态和 Token 数据全部实现；
- macOS App 不再以第一台 M5 为唯一设备；
- 自动化验收全部通过；
- 未更新的旧 M5 固件完成实机回归，或清楚记录唯一仍需用户执行的实机步骤；
- 没有修改或提交用户无关文件；
- 没有绕过权限、安全、Keychain 或隐私边界；
- 最终交接列出修改文件、测试证据、已知限制和下一步“微雪固件 Goal”的输入契约。

“新接口已经写好”但多设备音频仍共用缓冲、旧固件没有回归、App 仍只显示第一台
设备、Token 不可用时伪装为 0，或测试只覆盖单设备，均不算完成。

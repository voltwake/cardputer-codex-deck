# GOAL — Codex Deck 仓库与目录标准化

> **状态：当前实施目标（2026-08-02）**
>
> 当前多设备与桌面 Agent 标准化实现已经在本地提交 `ba6c95f`
> (`Standardize Codex Deck for multiple devices`) 固化。本 Goal 只负责仓库命名、
> 目录边界、构建路径和发布引用的标准化，不重新设计协议，也不顺带修改设备功能。
>
> 安装、构建、安全、协议与品牌约束仍分别以 [`INSTALL.md`](INSTALL.md)、
> [`DEVELOPMENT.md`](DEVELOPMENT.md)、根目录 [`SECURITY.md`](../SECURITY.md)、
> [`PROTOCOL.md`](PROTOCOL.md) 和 [`BRANDING.md`](BRANDING.md) 为准。发生冲突时，
> 安全、向后兼容和用户授权边界优先。

## 1. 决策

本项目继续使用一个 monorepo，不新建第二个仓库，不复制历史后重新开始。

实施顺序为：

1. 在当前 `cardputer-codex-deck` 仓库内完成目录迁移；
2. 更新所有构建、测试、安装、发布、CI 和文档路径；
3. 在当前仓库完成代码审查和全量验证；
4. 合入默认分支后，将现有 GitHub 仓库原地改名为 `codex-deck`；
5. 主动更新本地 remote、更新源和所有外部引用，不长期依赖旧地址重定向。

公共产品名称统一使用 **Codex Deck**，标准拼写是 `Codex`，不是 `CodeX`。
GitHub 仓库 slug 使用小写连字符形式 `codex-deck`。

## 2. 背景与问题

当前仓库最初以 M5Stack Cardputer ADV 固件为中心建立，因此固件的
`platformio.ini`、`src/` 和 `assets/` 位于根目录，而桌面 Agent、macOS App 和
音频驱动分别散落在 `bridge/`、`macos/` 和 `driver/`。

多设备标准化完成后，M5 已经只是标准设备协议的一个实现。未来还会增加微雪及
其他设备固件。如果继续保持现有结构，会出现以下问题：

- 根目录仍暗示整个项目只等于 M5 固件；
- 新增微雪固件时容易与 M5 的 PlatformIO 配置、资源和生成文件混放；
- `bridge/` 既表示 Python Agent，又被用户理解为整个桌面桥接产品；
- 构建脚本、CI、发布工具和文档中的路径无法清楚表达组件所有权；
- 仓库旧名称 `cardputer-codex-deck` 把产品绑定在 Cardputer 上，与设备中立目标
  不一致。

本 Goal 要让仓库结构与已经完成的运行时解耦保持一致：多个独立设备固件通过
公共协议连接一个设备中立的 Codex Deck 桌面桥接服务。

## 3. 目标目录

完成后的受版本控制目录必须收敛为以下结构：

```text
codex-deck/
├── firmware/
│   └── m5stack-cardputer-adv/
│       ├── platformio.ini
│       ├── src/
│       └── assets/
├── bridge/
│   ├── agent/
│   ├── macos/
│   └── driver/
├── docs/
├── release/
├── scripts/
├── tools/
├── .github/
├── AGENTS.md
├── README.md
├── README.zh-CN.md
├── SECURITY.md
├── project-install.json
└── version.json
```

未来新增微雪固件时，只在 `firmware/` 下增加独立实现：

```text
firmware/
├── m5stack-cardputer-adv/
└── waveshare-esp32-s3-touch-amoled-1.75c/
```

设备目录必须自包含自己的板卡配置、源码、设备专用资源、依赖锁定和构建说明。
一个设备固件不得通过相对路径偷偷引用另一个设备目录中的源码或生成文件。

## 4. 目录所有权

### 4.1 `firmware/`

`firmware/` 只保存设备端实现。当前根目录中的以下内容应迁移到
`firmware/m5stack-cardputer-adv/`：

- `platformio.ini`；
- 当前 `src/`；
- 仅供 Cardputer 固件使用的 `assets/`；
- 与该固件直接绑定的分区、板卡、字体和宠物资源生成输入（若存在）。

当前 PlatformIO environment 名可以继续保留 `cardputer`，避免无意义地改变构建
产物标识。迁移目录不代表升级或重新烧录固件。

每个未来固件目录必须至少提供：

- 自己的构建入口；
- 稳定 `device_id` 的来源说明；
- 实际声明的 capability 清单；
- 对应的协议版本与兼容测试；
- 不依赖其他固件私有实现的证明。

### 4.2 `bridge/`

`bridge/` 表示完整的 Codex Deck 桌面桥接产品，而不再只表示 Python 进程：

- `bridge/agent/`：当前 Python Agent、`cardbridge` 包、模拟设备、hooks、打包配置
  和 Python 测试；
- `bridge/macos/`：当前 SwiftUI 菜单栏 App、Swift Package、共享生成常量和
  macOS 构建脚本；
- `bridge/driver/`：当前 Core Audio 麦克风驱动及其上游许可材料。

目录名称改变时，1.x 内部兼容标识仍保持不变，包括：

- `CardBridge.app`、`CardBridgeAgent.app`；
- `cardbridge` Python 包和 CLI；
- bundle identifier、mDNS `_cardbridge._tcp`、端口和 Unix socket；
- `~/.cardbridge`、Keychain 配对记录；
- `CardBridge Microphone` 和 `CardBridge Microphone Feed`；
- `CardBridge-*` 发行产物名称。

这些标识只能在未来 major release 的独立迁移 Goal 中更改。本 Goal 不得导致用户
重新配对、重新授予 Accessibility 权限或重新选择音频设备。

### 4.3 根目录公共层

以下内容继续保留在根目录，因为它们跨越所有固件和桌面桥接组件：

- `version.json`：版本、协议和 capability profile 的唯一来源；
- `docs/`：产品、协议、安装、开发、安全和当前 Goal；
- `scripts/`：面向用户与自动化的稳定命令入口；
- `tools/`：跨组件生成、校验和发布工具；
- `release/`：整个产品的兼容矩阵、appcast、发行说明和清单；
- `.github/`：覆盖所有组件的 CI 与仓库配置；
- 根 README、许可证、NOTICE、SECURITY、CONTRIBUTING 和项目元数据。

协议规范仍以 `docs/PROTOCOL.md` 和 `version.json` 为事实来源，不归属于某个设备
固件，也不归属于某个桌面 UI。

## 5. 稳定命令与开发体验

目录变化后，以下根目录命令必须继续有效，调用者不需要知道内部组件移动到了
哪里：

```sh
./scripts/install-release.sh
./scripts/doctor.sh
./scripts/bootstrap.sh
./scripts/test.sh
./scripts/build.sh
./scripts/install.sh
./scripts/healthcheck.sh
```

要求：

1. 根脚本只能作为稳定入口，内部显式定位新的组件目录；
2. 脚本不得依赖调用者当前目录，必须从脚本自身位置解析仓库根目录；
3. Python 虚拟环境迁移到 `bridge/agent/.venv`，旧的 ignored `.venv` 不进入 Git，
   由 `bootstrap.sh` 在新位置重建；
4. Swift build、Sparkle 依赖和 App 产物位于 `bridge/macos/` 对应路径；
5. PlatformIO 必须显式使用
   `firmware/m5stack-cardputer-adv/platformio.ini` 或项目目录；
6. 根 `test.sh` 和 `build.sh` 继续聚合 Python、Swift、固件、驱动与生成文件检查；
7. `--json` 的 doctor/healthcheck 输出结构不能因为源码目录移动而改变；
8. 安装后的 App、Agent、驱动、配置和 socket 路径不能因为源码目录移动而改变。

## 6. 生成文件与版本规则

目录迁移必须同步更新 `tools/generate_versions.py` 的输出目标，使其生成到新的组件
路径。仍然禁止手工修改生成文件。

至少覆盖：

- Agent 生成版本文件；
- M5 固件生成头文件；
- Swift 共享版本文件；
- release compatibility JSON。

本 Goal 是源码布局重构，不新增协议字段，因此：

- device protocol 保持当前 major/minor；
- Agent API 保持当前 major/minor；
- capability profile 内容保持不变；
- 不因为移动目录单独修改固件版本；
- 不因为移动目录强制创建新的配对或配置 schema。

若实现过程中确实需要改变上述任一运行时契约，必须停止并把它拆成新的功能 Goal，
不能隐藏在目录重构中。

## 7. CI、安装与发布路径

必须审计并更新所有硬编码旧路径，包括但不限于：

- `.github/workflows/`；
- 根 `scripts/` 与各组件脚本；
- Python 打包配置和资源收集路径；
- Swift Package、App bundle、Sparkle 和 driver 路径；
- release 脚本、校验器和 checksum/manifest 生成；
- `project-install.json`；
- README、开发文档、安装文档、贡献指南和支持文档；
- 测试 fixture 中仅用于定位源码的路径。

历史验证日志中的旧路径可以保留，但必须明确标记为历史记录，不能再被当前安装或
开发文档引用为可执行命令。

构建产物的用户可见名称和安装位置保持不变。目录迁移后生成的 App 仍必须通过
现有签名、嵌套签名和 artifact validation。

## 8. GitHub 仓库原地改名

### 8.1 为什么不新建仓库

新建仓库再复制代码会人为切断或分散提交历史、PR、Issue、Release、标签和外部
引用，也容易让两个仓库同时被误认为官方来源。本项目已有用户、发行物和兼容
记录，因此必须原地改名。

### 8.2 改名时机

GitHub 仓库改名是目录迁移合入后的独立发布步骤。只有满足以下条件后才能执行：

1. 默认分支包含完成的目录结构；
2. CI 和本地全量构建通过；
3. 当前 release 下载、appcast 和更新检查路径已经审计；
4. 没有未处理的仓库级阻塞事项；
5. 用户明确批准执行远端仓库改名。

改名目标：

```text
voltwake/cardputer-codex-deck
→ voltwake/codex-deck
```

### 8.3 改名后必须完成

- 将本地 remote 显式更新为新 URL；
- 更新 README badge、clone URL、Release URL 和仓库描述；
- 更新 `version.json` 中的 appcast/feed URL 及其生成输出；
- 更新 `raw.githubusercontent.com`、下载脚本和 release manifest 引用；
- 检查 GitHub Actions、Dependabot、Issue/PR 模板和仓库设置；
- 检查是否有把本仓库当作 GitHub Action 使用的外部 workflow；
- 验证旧网页/clone URL 的重定向，同时确保产品不依赖该重定向长期运行；
- 验证 Sparkle 更新检查和 `install-release.sh` 能从新地址取得正确产物；
- 更新 `docs/BRANDING.md` 和所有当前文档中的仓库 slug。

GitHub Pages 项目站点 URL 和以本仓库作为 GitHub Action 的调用不能假定会随仓库
重命名自动工作，必须单独审计；即使当前未使用，也要记录检查结果。

## 9. 迁移方式与 Git 历史

所有受版本控制文件使用可审查的移动操作，优先让 Git 将其识别为 rename。禁止：

- 复制到新目录后遗留第二份活动源码；
- 把 `.pio`、`.build`、`.venv`、`dist` 或驱动 build 缓存提交进仓库；
- 使用全仓库删除后重新生成的方式掩盖真实移动；
- 顺手格式化或重写与路径无关的大量源码；
- 修改那 4 张现有未跟踪 PNG 或把它们纳入提交。

迁移 PR 应把纯移动与必要的路径修复区分清楚。若某文件同时发生内容修改，修改应
限于 import、资源定位、构建入口或文档路径，便于审查历史连续性。

由于当前已有名为 `bridge/` 的 Agent 目录，实现时必须采用不会覆盖文件的中间
移动顺序，再形成 `bridge/agent`、`bridge/macos` 和 `bridge/driver`。不得用破坏性
命令清空现有 `bridge/`。

## 10. 工作包

### WP1 — 路径清单与归属锁定

- 枚举受版本控制文件、ignored 构建目录和生成文件；
- 为每个当前顶层目录确定目标位置；
- 找出脚本、CI、文档和源码中的硬编码路径；
- 建立迁移前后映射表，作为 PR 审查依据。

### WP2 — M5 固件归档到设备目录

- 创建 `firmware/m5stack-cardputer-adv/`；
- 移动 PlatformIO 配置、源码和设备专用 assets；
- 修复字体、宠物、生成头文件和构建路径；
- 保证固件二进制功能、版本和 capability 声明不变。

### WP3 — 桌面桥接产品聚合

- 将当前 Python Agent 归入 `bridge/agent/`；
- 将 macOS App 归入 `bridge/macos/`；
- 将 Core Audio driver 归入 `bridge/driver/`；
- 修复 Python 打包、Swift Package、App bundle 和 driver 引用；
- 保持所有 CardBridge 1.x 技术兼容标识不变。

### WP4 — 稳定根命令与生成器

- 更新根 `scripts/`；
- 更新 `tools/generate_versions.py` 和检查模式；
- 更新 bootstrap、test、build、install、healthcheck 与 release gate；
- 确保从仓库根目录以外调用脚本也能正确定位文件。

### WP5 — CI、文档与发布引用

- 更新 workflow、缓存 key 和 artifact 路径；
- 更新所有当前文档和 README；
- 更新安装元数据、release 工具和 appcast 源；
- 对历史文档保留必要说明，不将历史命令当作当前入口。

### WP6 — 验收

- 运行完整自动测试与构建；
- 验证旧 M5 协议 fixture 和多设备 fixture；
- 验证安装产物内容、签名和版本；
- 验证目录中不存在重复活动实现；
- 输出新的 `GOAL_ACCEPTANCE.md` 验收记录。

### WP7 — 远端仓库改名（用户批准门）

- 在用户明确批准后原地改名；
- 更新 remote 与全部仓库 URL；
- 验证 clone、fetch、release 下载和自动更新；
- 不创建新的替代仓库。

## 11. 验收标准

### 11.1 结构验收

- 根目录不再直接存在活动固件 `src/`、`assets/` 或 `platformio.ini`；
- M5 固件完整位于 `firmware/m5stack-cardputer-adv/`；
- 桌面组件完整位于 `bridge/agent`、`bridge/macos`、`bridge/driver`；
- 不存在旧路径与新路径并行维护的重复源码；
- `firmware/` 下新增第二个设备目录时无需重构桌面 Agent。

### 11.2 命令验收

以下命令必须从仓库根目录成功：

```sh
./scripts/doctor.sh
./scripts/test.sh
./scripts/build.sh
bridge/agent/.venv/bin/python tools/generate_versions.py --check
```

如果 bootstrap 后的 Python 路径由实现确定为其他稳定位置，应同步更新本文和
`DEVELOPMENT.md`，但根脚本名称不得改变。

`./scripts/install.sh` 和 `./scripts/healthcheck.sh --json` 的安装态验收仍受 macOS
权限与用户批准边界约束；自动化不得绕过管理员、Accessibility、Local Network、
Microphone、Keychain 或 Codex Hook 提示。

### 11.3 回归验收

- Python 测试不少于当前基线的 82 个，除非有明确合并/替代说明；
- Swift 测试不少于当前基线的 5 个；
- M5 firmware 构建成功，RAM/Flash 不发生无法解释的显著增长；
- legacy v1、现有 M5 protocol v2、多设备、键盘、音频租约、Token 和隐私测试
  继续通过；
- `git diff --check` 通过；
- 生成文件检查通过；
- App/Agent/driver 构建与 artifact validation 通过；
- 4 张用户 PNG 保持未跟踪且内容不变。

### 11.4 仓库改名验收

远端改名执行后：

- canonical repository 为 `voltwake/codex-deck`；
- 本地 `origin` 指向新 URL；
- 当前 README、文档、脚本、appcast 和 release metadata 不再依赖旧 slug；
- 新 URL clone/fetch 正常；
- release 下载与自动更新检查正常；
- 旧 URL 重定向只作为兼容兜底，不作为产品配置；
- PR、Issue、Release 和标签仍保留在同一仓库历史中。

## 12. 明确非目标

本 Goal 不做以下事情：

1. 不新建 `codex-deck` 仓库后复制代码；
2. 不实现微雪固件，只为它预留独立目录边界；
3. 不修改标准设备协议、Token 语义或多设备行为；
4. 不要求更新或烧录现有 M5 固件；
5. 不修复电池百分比算法，该问题应进入单独的固件 Goal；
6. 不重命名 CardBridge 1.x 技术兼容标识；
7. 不安装 App、不替换运行中 Agent、不触发权限提示；
8. 不在未经用户明确批准时修改远端 GitHub 仓库设置；
9. 不提交用户现有的 4 张未跟踪 PNG；
10. 不把目录整理扩大成与迁移无关的代码重写。

## 13. 完成定义

只有同时满足以下条件，本 Goal 的代码实施部分才算完成：

1. 目标目录结构落地且没有重复活动源码；
2. 稳定根命令、CI、打包、安装和 release 路径全部适配；
3. 版本与协议契约保持不变；
4. 自动测试、完整构建、生成检查和 artifact validation 全部通过；
5. 文档反映新的源码结构和仍保留的 CardBridge 兼容标识；
6. 验收证据写入 `docs/GOAL_ACCEPTANCE.md`；
7. 未安装、未烧录、未改权限，除非用户另行明确批准。

远端仓库最终改名属于 WP7。若用户尚未批准或尚未执行，应明确报告“代码目录
标准化完成，远端改名待用户批准”，不得把它伪装为已完成，也不得因此新建第二个
仓库。

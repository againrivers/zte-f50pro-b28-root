# 中兴 F50 Pro (B28) Root + UFI-TOOLS

> **本项目的价值：目前唯一针对 `F50ProV1.0.0B28` 实测通过的完整方案。**
>
> 社区流传的工具包标注 B10～B27，但包里所有版本其实是**同一个 6 月构建改名**，
> 在 B28 上会因为 TrustOS 不匹配而失败。本方案在真实 B28 硬件上从零走通，
> 记录了每一个坑的确切现象和根因。

<p align="center">
  <img src="https://img.shields.io/badge/firmware-B28-blue" alt="B28">
  <img src="https://img.shields.io/badge/Android-15-green" alt="Android 15">
  <img src="https://img.shields.io/badge/SoC-UMS9620-orange" alt="UMS9620">
  <img src="https://img.shields.io/badge/Magisk-28103-red" alt="Magisk">
  <img src="https://img.shields.io/badge/license-MIT-lightgrey" alt="MIT">
</p>

---

## 已验证环境

### 硬件

| 项 | 值 |
| --- | --- |
| 设备 | 中兴 F50 Pro（**MU3356，插卡版** —— 有实体 SIM 卡槽） |
| 芯片 | 紫光展锐 UMS9620 / T760 |
| Android | 15（API 35） |
| 分区数 | 83 |
| 活动 slot | `b` |

### 固件

| 项 | 值 |
| --- | --- |
| 版本 | `F50ProV1.0.0B28` |
| 构建 | `AP3A.240905.015.A2/20260818.180242` |
| Magisk | `1e3edb88(28103)` |
| UFI-TOOLS | v4.0.0 |

### 操作环境（macOS）

| 项 | 值 |
| --- | --- |
| 系统 | **macOS 27.0.1**（build `26A434`，Apple Silicon / arm64） |
| 刷写工具 | 工具包自带 `spd_dump_mac`（Universal 2，ver:232） |
| Python | 3.9.6 |
| lz4 | 1.10.0 |
| adb | 1.0.41 |
| git | 2.56.0 |

> 上述组合下的每一步产物、每一处偏移、每一条日志都是实机验证过的。

**关于硬件版本**：本项目的验证基于**插卡版**。同型号若存在其他版本（如内置卡版本），
`prodnv` / `calinv` 等内容可能不同，刷写前请重新确认自己的分区与镜像。

**关于操作系统**：文中命令按 macOS 编写（`spd_dump_mac`、`ifconfig`）。
Linux 可直接换成上游 `spd_dump`，参数一致；Windows 需另装展锐 USB 驱动并使用
`spd_dump` 或 ResearchDownload，**本项目未在 Windows 上验证**。

---

## 为什么 B28 不一样

社区工具包（[zte-f50pro-macos-toolkit](https://github.com/Tai1win10c/zte-f50pro-macos-toolkit) 等）的 `tos.bin` 存在三个问题：

1. 包里标注 `B10`、`B15`、`B27` 的多个版本，**字节完全相同**——只是改了文件名
2. 它们都来自同一个 **6 月 8 日**构建
3. 与 B28 设备 dump 出来的 TrustOS 对比，有 **611,443 / 5,195,528 字节不同（11.77%）**

在 B28 上照搬会失败。

**验证机（构建 `20260818.180242`）的结论：只刷 `init_boot_b` 即可，不需要动 TrustOS。**

> ⚠️ **但这条不是对所有 B28 都成立。**
> 部分 B28 设备的 boot 链校验在 **TrustOS/TEE 层**，只刷 init_boot 会**循环重启**
> （USB 正常枚举，不是诊断模式），必须同时处理 `trustos_b`。
> 见 [issue #1](https://github.com/againrivers/zte-f50pro-b28-root/issues/1) 和
> [docs/01-root.md §8](docs/01-root.md)。

只补丁 `init_boot` 并**保持 AVB 结构完整**，设备就能正常启动。难点不在"绕过校验"，而在"别把校验结构写坏"——见 [坑 1](docs/03-pitfalls.md)。

---

## 能做什么

- ✅ Root（Magisk 28103，su 在 `/debug_ramdisk/su`）
- ✅ 无屏幕设备的 root 授权预置（SQLite 策略注入）
- ✅ 修复 Magisk 运行环境（`post-fs-data.d` / `service.d` / 模块真正可用）
- ✅ 安装 UFI-TOOLS 高级后台（含 API 鉴权算法 + 可用的客户端）
- ✅ 关掉微信对 USB 的 AOA 探测（解决刷机时反复掉线）
- ✅ 变砖恢复（实测 7 次，全部靠同一份 6 GB 分区备份）

---

## 快速开始

### 0. 先备份（不备份不要往下做）

```bash
cd "中兴F50Pro_macOS一键工具包_shuangye"
./bin/spd_dump_mac --wait 240 r all_lite backup/
# 产出约 6 GB / 50 个分区
```

### 1. 检查你的固件

```bash
adb shell getprop ro.build.display.id
# 应含 F50ProV1.0.0B28
```

不是 B28 的话，[docs/01-root.md](docs/01-root.md) 的方法论仍然适用，但偏移和结构需要自己重新确认。

### 2. 按文档执行

| 步骤 | 文档 |
| --- | --- |
| Root 全流程 | [docs/01-root.md](docs/01-root.md) |
| 装 UFI-TOOLS | [docs/02-ufi-tools.md](docs/02-ufi-tools.md) |
| 遇到问题 | [docs/03-pitfalls.md](docs/03-pitfalls.md) |
| 刷坏了 | [docs/04-recovery.md](docs/04-recovery.md) |
| B28 专属细节 | [docs/05-b28.md](docs/05-b28.md) |
| **让 AI Agent 帮你做** | [AGENTS.md](AGENTS.md) |

### 3. 验证

```bash
A="adb -s 192.168.0.1:5555"

$A shell '/debug_ramdisk/su -c id'                       # uid=0(root)
$A shell '/debug_ramdisk/su -c "magisk -v"'              # 1e3edb88:MAGISK:R
$A shell '/debug_ramdisk/su -c "ls /data/adb/magisk | wc -l"'   # 11
$A shell '/debug_ramdisk/su -c "grep -c \"Running post-fs-data.d\" /cache/magisk.log"'  # >= 1
```

最后一条最重要——它决定你的"开机自启脚本"到底能不能跑。

---

## 踩过的坑（摘要）

| # | 症状 | 根因一句话 |
| --- | --- | --- |
| 1 | 刷完不启动，USB 变 `1782:4D00` | 补零冲掉了 `AVB0`/`AVBf` |
| 2 | 刷社区 TrustOS 后异常 | 包里的 tos 是 6 月构建，与 B28 差 11.77% |
| 3 | `su: not found` | Magisk 28+ 不再放 `/system/bin/su` |
| 4 | 脚本装了不执行 | Magisk 环境不完整 → `post-fs-data` 直接 abort |
| 5 | 刷机反复 `LIBUSB_ERROR_IO` | 微信 AOA 探测导致 USB 每 3 秒重枚举 |
| 6 | 45% 左右写入失败 | 物理干扰 + 上面的重枚举 |
| 7 | BootROM 抢不到 | 软重启窗口太短，要物理重插 |

细节与日志证据见 [docs/03-pitfalls.md](docs/03-pitfalls.md)。

---

## 参考项目

本项目是站在这些项目肩上完成的，**没有它们不可能走通**：

| 项目 | 作者 | 本项目用到的部分 |
| --- | --- | --- |
| [**kanoqwq/UFI-TOOLS**](https://github.com/kanoqwq/UFI-TOOLS) | kanoqwq | 高级后台本体、插件生态、`root_shell` 接口。文档里的鉴权算法是针对它的 API 逆向整理 |
| [**Tai1win10c/zte-f50pro-macos-toolkit**](https://github.com/Tai1win10c/zte-f50pro-macos-toolkit) | Tai1win10c | `spd_dump_mac` 二进制、分区备份脚本。本项目的备份和刷写流程基于它 |
| [**joker-skills/f50pro-MacOS-tools**](https://github.com/joker-skills/f50pro-MacOS-tools) | joker-skills | `init_boot` 重打包脚本的思路参考（`repack-init-boot.py` / `flash-root.sh`），以及 AOA 问题的早期线索 |
| [**handsomehack/spreadtrum_flash**](https://github.com/handsomehack/spreadtrum_flash) | handsomehack | 展锐 BootROM 刷写工具 `spd_dump` 上游 |
| [**topjohnwu/Magisk**](https://github.com/topjohnwu/Magisk) | topjohnwu | Root 方案本体；`magiskinit` 注入逻辑 |

**本项目相对它们的增量：**

1. **B28 实测**——社区包只到 B27（且是改名的旧构建），B28 的结构差异、TrustOS 不匹配问题首次被记录
2. **AVB 结构重建的具体做法**——不是"绕过"，是保持结构完整；含大端字段解析和页对齐计算
3. **Magisk 环境不完整的排查**——`/data/adb/magisk` 为空导致所有脚本静默失效，这个坑在中文资料里没找到
4. **无屏幕设备的 root 授权预置**——SQLite 直接写策略
5. **UFI-TOOLS API 鉴权算法**——含"必须用原始摘要拼接"这个关键细节

---

## 目录结构

```
.
├── README.md               ← 你在这里
├── LICENSE                 ← MIT
├── AGENTS.md               ← 给 AI Agent 的操作守则（含可粘贴提示词）
├── docs/
│   ├── 01-root.md          ← Root 全流程（备份→刷写→补丁→验证）
│   ├── 02-ufi-tools.md     ← 高级后台：安装、API 鉴权、插件、安全
│   ├── 03-pitfalls.md      ← 7 个坑 + 2 个网络附录
│   ├── 04-recovery.md      ← 变砖恢复与故障速查
│   └── 05-b28.md           ← B28 专属：分区表、结构、偏移
└── tools/
    ├── ufi-api.py          ← UFI-TOOLS API 客户端（已实测）
    └── inspect-init-boot.py← init_boot 镜像结构检查器（只读，安全）
```

---

## 风险声明

**这是一台没有屏幕的 CPE 设备，刷错就上不了网。**

- 所有操作前**必须**做完整分区备份，这是唯一的后悔药
- 本项目**不提供**预编译镜像下载——不同固件版本的结构不同，用错必砖
- 只要展锐 BROM 还能进，设备就永远救得回来（本项目实测恢复 7 次）
- 文中涉及的分区名、偏移、magic 值均针对 **B28**，其他版本请自行重新确认

**如果你不熟悉 `dd`、`cpio`、AVB、BootROM 这些概念，建议先读一遍 [docs/01-root.md](docs/01-root.md) 再动手。**

---

## 许可

MIT。文档和脚本可自由使用、修改、再分发。

设备固件、Magisk、UFI-TOOLS 等第三方组件遵循各自的原许可。

---

## 相关

- 有问题欢迎提 Issue，但请先看完 [docs/03-pitfalls.md](docs/03-pitfalls.md)

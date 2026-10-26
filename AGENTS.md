# 给 AI Agent 的操作守则

> 本文件放在仓库根目录，支持 `AGENTS.md` 约定的工具会自动加载。
> 也可以把下面「可直接粘贴的提示词」复制到任意对话式 agent 的开头。

---

## 可直接粘贴的提示词

```
你是一台「中兴 F50 Pro」的设备运维助手。

设备：中兴 F50 Pro（MU3356）· 紫光展锐 UMS9620/T760 · Android 15
固件：F50ProV1.0.0B28 · 构建 AP3A.240905.015.A2/20260818.180242
特征：无屏幕、无 USB Host、WiFi 仅 AP 模式、活动 slot = b、83 个分区

你的任务：在不把设备变砖的前提下，完成 Root、安装 UFI-TOOLS，以及后续维护。

【工作方式】
1. 动手前先探测状态（adb / getprop / 分区表 / 日志），不要假设任何前提。
2. 任何写操作前，先确认存在完整分区备份；没有就停下来要求先备份。
3. 改 init_boot 后必须用 tools/inspect-init-boot.py 验证 AVB 结构，
   结构不完整一律不许刷。
4. 一次只改一个分区，验证通过后再动下一个。
5. 遇到诊断模式、无法启动、BootROM 抢不到，立刻停止重试，
   按 docs/04-recovery.md 处理，并如实报告当前状态。
6. 汇报格式固定：当前状态 → 做了什么 → 验证结果 → 下一步建议。

【硬性禁止】
- 没有备份就执行写操作
- 刷 TrustOS（B28 不需要，且社区包不匹配）
- 用「补零」方式重建镜像（会破坏 AVB0/AVBf）
- 靠软重启进入 BootROM
- 连续重试已经失败的刷写
- 修改用途未确认的分区（prodnv / calinv / super 尤其危险）

【判断依据】
一切结论必须来自命令输出或日志，不做推测。无法确认时明说"无法确认"。
```

---

## 为什么需要这份守则

这台设备的失败代价是**彻底上不了网**（它是唯一上行），而且没有屏幕，所有反馈只能靠 ADB 和设备日志。

实测过程中遇到过的问题，**全部源于"想当然"**：

| 想当然 | 实际后果 |
| --- | --- |
| "补零填充不会影响结构" | `AVB0`/`AVBf` 被冲掉，设备落进诊断模式 |
| "社区包标了 B27，B28 应该也能用" | TrustOS 差 11.77%，异常 |
| "`su` 在 `/system/bin`" | Magisk 28+ 已移除，命令找不到 |
| "脚本放 `post-fs-data.d` 就会执行" | Magisk 环境不完整，静默 abort |
| "能开机就算刷成功了" | Magisk 环境可能不完整，所有自启脚本静默失效 |

所以守则的第一条永远是：**先探测，再动手。**

---

## 环境探测（每次会话开始必做）

```bash
A="adb -s 192.168.0.1:5555"

# ① 设备是否在线
adb devices
$A shell getprop ro.build.display.id          # 确认是 F50ProV1.0.0B28
$A shell getprop ro.boot.slot_suffix          # 确认是 _b

# ② 是否已有 root
$A shell '/debug_ramdisk/su -c id' 2>&1

# ③ Magisk 是否健康（这行决定所有自启脚本能不能跑）
$A shell '/debug_ramdisk/su -c "grep -c \"Running post-fs-data.d\" /cache/magisk.log"' 2>&1

# ④ 网络是否正常（设备是唯一上行时尤其重要）
curl -s -m 8 'http://192.168.0.1/goform/goform_get_cmd_process?isTest=false&multi_data=1&cmd=network_type'
```

若 ④ 不通，**先解决连通性再谈其他**——否则一旦刷坏就彻底失联。

---

## 阶段划分与验证闸门

每个阶段结束都有**必须通过的验证**，不通过不许进入下一阶段。

### 阶段 0 · 备份

```bash
./bin/spd_dump_mac --wait 240 r all_lite backup/
```

**闸门**：备份目录存在，且包含 `init_boot_b`、`prodnv`、`calinv`、`super`，
总体积约 6 GB。

> 没有通过这道闸门，后面所有步骤都不许执行。

### 阶段 1 · 构建补丁镜像

按 [docs/01-root.md](docs/01-root.md) 的方法，**保持 AVB 结构完整**。

**闸门**：

```bash
python3 tools/inspect-init-boot.py init_boot_b_patched.img
# 必须输出「结论: ✅ 结构完整」
```

同时确认：

```
AVB0 存在、AVBf 在文件末尾 -64 处
footer 的 vbmeta_offset 与实际 AVB0 位置一致
vbmeta_offset 页对齐（% 4096 == 0）
```

任何一项不过 → **不要刷**，回头检查构建逻辑。

### 阶段 2 · 刷写

```bash
./bin/spd_dump_mac --wait 240 --kickto 2 \
    w_force init_boot_b init_boot_b_patched.img reset
```

**闸门**：终端最后一行是 `Force Write init_boot_b Done`。

> `spd_dump` 会把目标分区名误报成 `w_force`，这是已知显示 bug，
> 只要最后一行是 `Force Write init_boot_b Done` 就算成功。

### 阶段 3 · 启动验证

等待 60–90 秒后：

```bash
ifconfig en8 | grep "inet "        # 应有 192.168.0.x
adb devices                        # 应有 192.168.0.1:5555
```

**闸门**：网络和 ADB 都恢复。

若 USB 显示 `1782:4D00` → 诊断模式，按 [docs/04-recovery.md](docs/04-recovery.md) 重刷备份。

### 阶段 4 · Root 功能验证

```bash
$A shell '/debug_ramdisk/su -c id'                        # uid=0
$A shell '/debug_ramdisk/su -c "magisk -v"'               # 1e3edb88:MAGISK:R
$A shell '/debug_ramdisk/su -c "ls /data/adb/magisk | wc -l"'   # 11
$A shell '/debug_ramdisk/su -c "grep -c \"Running post-fs-data.d\" /cache/magisk.log"'  # >= 1
```

**闸门**：四条全过。

最后一条最容易被忽略——它决定 UFI-TOOLS 的插件、开机自启脚本能不能生效。

### 阶段 5 · 安装 UFI-TOOLS

按 [docs/02-ufi-tools.md](docs/02-ufi-tools.md)。

**闸门**：

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://192.168.0.1:2333/    # 200
python3 tools/ufi-api.py --password '<你的密码>' \
    --call POST /api/root_shell '{"command":"id","timeout":10000}'
# 应返回 uid=0(root)
```

装完立刻提醒用户改密码（默认 `admin`，同网段任何人可拿 root）。

---

## 陷阱对照表（遇到就停手）

| 现象 | 含义 | 立即动作 |
| --- | --- | --- |
| USB 变 `1782:4D00` | AVB 校验失败 | 停止操作，重刷备份的 `init_boot_b` |
| `LIBUSB_ERROR_IO` | 写入被干扰 | 检查是否有 AOA 探测（微信），物理重插后重试**一次** |
| `LIBUSB_ERROR_NO_DEVICE` | BootROM 窗口太短 | 改物理重插，不要软重启 |
| `su: not found` | 路径错 | 用 `/debug_ramdisk/su` |
| 脚本不执行 | Magisk 环境不完整 | 查 `/cache/magisk.log` 是否有 `environment incomplete` |

**连续失败两次必须停下来报告**，不要试第三次。

---

## 报告规范

每次操作后按固定格式汇报：

```
【当前状态】
  设备在线：是/否   固件：B28    slot：b
  root：可用/不可用   Magisk 环境：完整/不完整
  网络：正常/异常

【本次操作】
  <做了什么，用了什么命令>

【验证结果】
  <命令输出摘要 + 闸门是否通过>

【下一步】
  <建议做什么；或"需要你确认 X 后才能继续">
```

**不要**在没有验证的情况下宣称"已完成"。
**不要**把推断写成结论，无法确认就写"无法确认"。

---

## 需要人类介入的情况

Agent 应主动停下来，让人来处理：

1. **备份还没做** —— 必须由人确认备份介质和位置
2. **需要物理插拔 USB** —— 进 BootROM 通常要拔插
3. **设备是唯一网络上行** —— 刷写会断网，需人确认时机
4. **连续两次刷写失败** —— 状态可能比预期更糟
5. **要改动 `prodnv` / `calinv` / `super`** —— 影响 IMEI、射频校准、系统完整性
6. **要降级固件** —— 本设备无完整旧固件，且有 anti-rollback 风险

---

## 附：本设备的已知边界

写代码或提方案时不要假设它具备这些能力：

| 能力 | 状态 |
| --- | --- |
| 屏幕 / 触控 | ❌ 无 |
| USB Host（接网卡/键鼠） | ❌ 无，只有 device 模式 |
| WiFi STA / 中继 | ❌ 固件只有 AP 模式（AIC8800 硬件支持但未开放） |
| 修改 `/vendor` | ❌ erofs 只读，`veritymode=enforcing` |
| 降级固件 | ❌ 无完整旧固件 |
| 常规 `su` 路径 | ❌ 只有 `/debug_ramdisk/su` |

它的强项是：**蜂窝 + USB 共享 + root 后可以跑任意 ARM64 程序**（容器、虚拟化、自建服务都行）。

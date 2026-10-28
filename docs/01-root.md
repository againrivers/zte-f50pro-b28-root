# 01 · Root 全流程

> 适用于中兴 F50 Pro（MU3356 / UMS9620 / Android 15）
> 刷写目标：`init_boot_b`（活动 slot 为 b）

---

## 0. 原理概述

F50 Pro 用 A/B 分区，`init_boot` 是一个 **8 MB** 的分区，里面是 Android boot image v4 格式：

```
┌─────────────────────────────────────┐ 0x0000
│ boot header (4096 B)                │   ← magic "ANDROID!"
├─────────────────────────────────────┤ 0x1000
│ kernel (本设备为空)                  │
├─────────────────────────────────────┤
│ ramdisk (LZ4 legacy 压缩)            │
├─────────────────────────────────────┤ 页对齐
│ AVB0  (vbmeta blob)                 │
├─────────────────────────────────────┤
│ 零填充                               │
├─────────────────────────────────────┤ 末尾 -64 B
│ AVBf  (footer, 64 B)                │
└─────────────────────────────────────┘ 8 MB
```

Magisk 的 root 原理是：把 ramdisk 里的 `/init` 换成 `magiskinit`，由它接管早期启动，再挂载 overlay 注入 `magiskd`。

**关键难点不是替换 init，而是保持 AVB（Android Verified Boot）结构完整。** 见 [踩坑 #1](03-pitfalls.md)。

---

## 1. 准备：完整分区备份

**这一步不做，后面任何操作都不许开始。**

用工具包里的 `spd_dump` 读取全部分区（83 个分区，约 6 GB）：

```bash
cd "中兴F50Pro_macOS一键工具包_shuangye"
./bin/spd_dump_mac --wait 240 r all_lite backup/
```

产物结构：

```
backup/backup_<时间戳>/
├── prodnv        63 MB
├── calinv        32 MB     ← 校准数据，丢了信号会异常
├── trustos_b      6 MB
├── sml_b          1 MB
├── boot_b        64 MB
├── init_boot_b    8 MB     ← 本次要改的分区
├── super       3088 MB     ← 系统分区
├── vbmeta_b       1 MB
└── ... 共 50 个关键分区
```

> **备份目录必须妥善保存**。本设备实测靠它恢复了 7 次。

---

## 2. 进入 BootROM 模式

展锐平台靠 BROM 模式刷机。触发方式：

1. 拔掉 USB
2. **物理重插**（或按住按键插）
3. 设备进入 `boot_diag` 模式，`spd_dump --wait` 会自己接上

```bash
# 检查是否识别到
system_profiler SPUSBDataType | grep -A3 -i "sprd\|1782"
```

> 软重启（`REBOOT_DEVICE`）有时也能进 BROM，但**不稳定**。物理重插最可靠。

---

## 3. 构建补丁镜像

### 3.1 从 stock 镜像解析

```python
import struct, hashlib, subprocess

STOCK = "backup/backup_xxx/init_boot_b"
img   = open(STOCK, "rb").read()
PAGE  = 4096

# boot header: magic + kernel_size(8) + ramdisk_size(12:16)
magic = img[0:8]
assert magic == b"ANDROID!", magic
ramdisk_size = struct.unpack("<I", img[12:16])[0]
print("ramdisk 大小:", ramdisk_size)
```

### 3.2 解出 ramdisk（LZ4 legacy）

```bash
dd if="$STOCK" bs=4096 skip=1 count=$(( (ramdisk_size + 4095) / 4096 )) of=rd.lz4
lz4 -d -c rd.lz4 > rd.cpio
```

cpio 是 **newc 格式**（`070701` magic）。

> 注意：原厂 cpio 里 `dev` 条目是**重复出现的**，Magisk 会拒绝处理。
> 去重到 31 个条目即可（与社区包一致）。

### 3.3 组装 Magisk 覆盖层

在 cpio 中：

| 路径 | 内容 |
| --- | --- |
| `init` | `magiskinit`（197,256 B，从 Magisk APK 的 `libmagiskinit.so` 取） |
| `.backup/.magisk` | 记录原始镜像的 `SHA1=<stock_sha1>` |
| `.backup/.rmlist` | 被替换的文件列表 |
| `.backup/init.xz` | 原始 `init` 的 xz 压缩 |
| `overlay.d/adbip.rc` | 自定义 init 服务（见下） |
| `overlay.d/sbin/start_adbip.sh` | 开机启动 ADB 的脚本 |

### 3.4 写回镜像（**最容易出错的一步**）

```python
# 重新压缩
rd_lz4 = subprocess.run(["lz4", "-l", "-9", "-c"], input=cpio,
                        capture_output=True, check=True).stdout

# 更新 header 里的 ramdisk_size
hdr = bytearray(img[:PAGE])
struct.pack_into("<I", hdr, 12, len(rd_lz4))

# 读取 AVB footer（大端！）
footer = img[-64:]
maj, mi, orig_size, vb_off, vb_size = struct.unpack(">IIQQQ", footer[4:36])

# 把 vbmeta 放到页对齐的末尾
page_end = PAGE + ((len(rd_lz4) + PAGE - 1) // PAGE) * PAGE
new = bytearray(len(img))
new[:PAGE]        = hdr
new[PAGE:PAGE+len(rd_lz4)] = rd_lz4
new[page_end:page_end+vb_size] = img[vb_off:vb_off+vb_size]

# 重写 footer（大端）
nf = bytearray(footer)
struct.pack_into(">QQQ", nf, 12, page_end, page_end, vb_size)
new[-64:] = nf

open("init_boot_b_patched.img", "wb").write(new)
```

**校验：**

```python
d = bytes(new)
print("AVB0 @", hex(d.find(b"AVB0")))
print("AVBf @", hex(d.find(b"AVBf")))
print("footer:", struct.unpack(">QQQ", d[-52:-28]))   # (voff, voff, vsize)
```

必须满足：`AVB0` 存在、`AVBf` 存在、footer 的三个值与实际位置一致。

> ⚠️ **绝对不要**简单地"用数据覆盖后补零"。补零会把 `AVB0`/`AVBf` 冲掉，
> 设备校验失败后会掉进诊断模式（`1782:4D00`）。这就是我们第一次失败的原因。

### 3.5 ramdisk 里的 adbip.rc

`overlay.d/adbip.rc` 会被 magiskinit 注入 init：

```rc
## custom service injected into init.rc
on late-start
    chmod 0755 ${MAGISKTMP}/start_adbip.sh
    mkdir /data/local/tmp 0755 root root
    start start_adbip_service

service start_adbip_service ${MAGISKTMP}/start_adbip.sh
    class main
    user root
    group root
    oneshot
    seclabel u:r:init:s0
```

> **重要经验**：`${MAGISKTMP}` 和 overlay rc 的加载时机在 `post-fs-data` **之后**、
> `late-start` 之前。所以 `on post-fs-data` 里写的命令**永远不会执行**，
> 必须放在 `on late-start` 或更晚。见 [踩坑 #4](03-pitfalls.md)。

`start_adbip.sh` 的核心动作：

```sh
#!/system/bin/sh
setprop service.adb.tcp.port 5555
setprop persist.adb.tcp.port 5555
stop adbd
start adbd
# 无屏幕设备：预置 root 授权（见第 5 节）
```

---

## 4. 刷写

```bash
./bin/spd_dump_mac --wait 240 --kickto 2 \
    w_force init_boot_b ./init_boot_b_patched.img reset
```

参数说明：

| 参数 | 作用 |
| --- | --- |
| `--wait 240` | 等待 BROM 连接，超时 240 秒 |
| `--kickto 2` | 跳到 FDL2（下载模式） |
| `w_force` | 强制写，跳过分区名匹配错误 |
| `reset` | 写完自动重启 |

**正常输出：**

```
Device is using slot b
Write Part Done: w_force, target: 0x800000, written: 0x800000
Force Write init_boot_b Done
```

> `spd_dump` 有时会把目标分区名**误报**成 `w_force`，但它会自修复分区表，实际写入位置正确。

---

## 5. 无屏幕设备的 root 授权预置

F50 Pro 没有屏幕，**没法在手机上点"允许"**。必须在 Magisk 的数据库里预先写入策略：

```sql
-- /data/adb/magisk.db
UPDATE settings SET value=3 WHERE key='root_access';   -- 允许 ADB shell 提权

INSERT OR REPLACE INTO policies (uid, policy, until, logging, notification)
VALUES (2000, 2, 0, 1, 1);                              -- uid 2000 = shell，policy 2 = allow
```

在开机脚本里用 root 执行：

```sh
/debug_ramdisk/su -c "sqlite3 /data/adb/magisk.db '...'"
```

> **su 的实际路径是 `/debug_ramdisk/su`**，不是 `/system/bin/su`。
> Magisk 28+ 已经不再往 `/system/bin` 放 su 了。见 [踩坑 #3](03-pitfalls.md)。

---

## 6. 补齐 Magisk 运行环境（**最关键的一步**）

刷完之后 `su` 能用了，但 **`post-fs-data.d`、`service.d`、模块全部失效**。

`/cache/magisk.log` 里只有一行：

```
** post-fs-data mode running
* Initializing Magisk environment
* Magisk environment incomplete, abort        ← 静默中止
```

**根因**：`/data/adb/magisk/` 是空的。

无屏幕设备没法在 Magisk App 里点"安装"，所以 Magisk 的自我初始化从未完成。magiskd 检测到环境不完整，直接跳过后续所有脚本。

**解法**：从 Magisk APK 里提取 11 个文件补齐：

| 源（APK 内） | 目标（/data/adb/magisk/） |
| --- | --- |
| `lib/arm64-v8a/libmagisk.so` | `magisk`、`magisk32`、`magisk64` |
| `lib/arm64-v8a/libbusybox.so` | `busybox` |
| `lib/arm64-v8a/libmagiskboot.so` | `magiskboot` |
| `lib/arm64-v8a/libmagiskinit.so` | `magiskinit` |
| `lib/arm64-v8a/libmagiskpolicy.so` | `magiskpolicy` |
| `lib/arm64-v8a/libinit-ld.so` | `init-ld` |
| `assets/stub.apk` | `stub.apk` |
| `assets/util_functions.sh` | `util_functions.sh` |
| `assets/boot_patch.sh` | `boot_patch.sh` |

一键脚本：

```bash
cd /tmp && rm -rf magisk_env && mkdir magisk_env && cd magisk_env
unzip -q -o /path/to/Magisk.apk

mkdir env
cp lib/arm64-v8a/libmagisk.so       env/magisk
cp lib/arm64-v8a/libmagisk.so       env/magisk32
cp lib/arm64-v8a/libmagisk.so       env/magisk64
cp lib/arm64-v8a/libbusybox.so      env/busybox
cp lib/arm64-v8a/libmagiskboot.so   env/magiskboot
cp lib/arm64-v8a/libmagiskinit.so   env/magiskinit
cp lib/arm64-v8a/libmagiskpolicy.so env/magiskpolicy
cp lib/arm64-v8a/libinit-ld.so      env/init-ld
cp assets/stub.apk                  env/stub.apk
cp assets/util_functions.sh         env/util_functions.sh
cp assets/boot_patch.sh             env/boot_patch.sh

tar -cf /tmp/magisk_env.tar -C env .

adb push /tmp/magisk_env.tar /data/local/tmp/
adb shell su -c "
  mkdir -p /data/adb/magisk
  tar -xf /data/local/tmp/magisk_env.tar -C /data/adb/magisk
  chmod 755 /data/adb/magisk/*
  chown -R 0:0 /data/adb/magisk
"
```

**修复后的日志**：

```
** post-fs-data mode running
* Initializing Magisk environment            ← 不再 abort
* Running post-fs-data.d scripts
post-fs-data.d: exec [xxx.sh]
* Loading modules
** late_start service mode running
* Running service.d scripts
```

这一步之后，**Magisk 模块、`post-fs-data.d`、`service.d` 才真正可用**。
后面所有"开机自动执行"的方案都依赖它。

---

## 7. 验证清单

```bash
A="adb -s 192.168.0.1:5555"

# ① root 可用
$A shell '/debug_ramdisk/su -c id'
# 期望 uid=0(root)

# ② Magisk 守护进程
$A shell '/debug_ramdisk/su -c "magisk -v"'
# 期望形如 1e3edb88:MAGISK:R

# ③ 环境完整
$A shell '/debug_ramdisk/su -c "ls /data/adb/magisk | wc -l"'
# 期望 11

# ④ 脚本机制生效
$A shell '/debug_ramdisk/su -c "grep -c \"Running post-fs-data.d\" /cache/magisk.log"'
# 期望 >= 1

# ⑤ 当前活动分区
$A shell 'getprop ro.boot.slot_suffix'
# 期望 _b
```

---

## 8. 关于 TrustOS / AVB 绕过

### 8.1 先分清两种失败

这两件事完全不同，处理路径也不同：

| 现象 | 失败点 | 处理方向 |
| --- | --- | --- |
| USB 变成 `1782:4D00`，设备停在诊断模式 | **AVB 结构被破坏** | 重建镜像，保持 `AVB0`/`AVBf` 完整 |
| **无限重启**，USB 正常枚举为 `ncm,mtp`，系统起不来 | **TrustOS / TEE 层拒绝** | 需要同时处理 `trustos_b` |

第 1 种是本项目早期踩的坑（见 [03-pitfalls.md](03-pitfalls.md) 坑 1）。
第 2 种来自真实用户反馈（[issue #1](https://github.com/againrivers/zte-f50pro-b28-root/issues/1)），
文档早期版本漏掉了它。

### 8.2 验证机的实测

验证机（构建 `20260818.180242`）：**只刷 `init_boot_b` 即可启动**，无需动 TrustOS。

证据：刷完 `init_boot_b_v5.img` 后设备正常启动，`/cache/magisk.log` 正常输出
`Running post-fs-data.d scripts`。

### 8.3 什么时候必须处理 TrustOS

部分 B28 设备的 boot 链校验发生在 **TrustOS/TEE 层**——bootloader 放行了，
但 TEE 随后拒绝改动过的 ramdisk，表现就是**循环重启**。

判断方法：

```bash
# 设备重启瞬间反复抓 USB
system_profiler SPUSBDataType | grep -A6 -iE "1782|ncm"
```

- 一直是 `1782:4D00` → AVB 结构问题，回去改构建
- 短暂出现正常的 `ncm,mtp` 然后消失、循环 → TrustOS 层校验

确认是后者时，两条路：

**A. 用本机 dump 派生免校验 TrustOS（推荐）**

```bash
# 从备份里取出 sml_b 与 trustos_b
./bin/dis_avb_ex sml_b trustos_b
```

用自己的分区派生，版本天然匹配。

**B. 刷社区的 `tos.bin`（不推荐）**

社区包与 B28 实机 TrustOS 有 **11.77%** 字节差异，且所有标注版本
（B10~B27）其实是同一个 6 月 8 日构建改名。有反馈称可能导致
**WiFi 5 → WiFi 4** 的能力降级。

### 8.4 结论

- **默认**只刷 `init_boot_b`
- 只有确认「循环重启 + USB 正常枚举」时才处理 TrustOS
- 优先用自己 dump 的分区派生，不要用社区的异版本文件

---

## 9. 降级说明

**本设备无法降级到 B27。**

- 各个共享渠道里都没有完整的 B27 固件
- B28 的 anti-rollback（eFuse）状态未知，强行刷旧版有**不可逆变砖**风险

如果你的目的是"避开 B28 的某个限制"，请优先考虑运行时修改，而不是降级。

# 03 · 踩坑记录

> 全部是真实踩过的坑，按"现象 → 根因 → 解法"整理。
> 7 个坑覆盖 Root、刷机、Magisk 与 USB 传输。

---

## 坑 1：AVB 结构被破坏，设备落进诊断模式

### 现象

刷完补丁镜像后设备**不启动**：

- 设备灯常亮但无网络
- USB 设备变成 `1782:4D00`，名字是 `Sprd Gadget Serial`
- `adb devices` 空，`ifconfig` 里没有 `en8`

这是展锐的 **diag（诊断）模式**——bootloader 校验失败后的降级状态。

### 根因

第一版构建脚本图省事，直接"用新数据覆盖后补零"：

```python
new = bytearray(len(img))
new[:PAGE] = hdr
new[PAGE:PAGE+len(rd)] = rd_lz4
# 剩下的全零                               ← 致命
```

但原镜像的 `AVB0`（vbmeta）在**页对齐的末尾**，`AVBf`（footer）在**最后 64 字节**。补零把它们全冲掉了。

Android 的 boot image v4 校验流程：

```
header  →  找到 ramdisk
        →  读 AVBf footer（末尾 64 B）
        →  按 footer 的偏移去找 AVB0
        →  校验失败 → 拒绝启动
```

### 解法

必须**重建结构**，保持 `AVB0` 在页对齐位置、`AVBf` 在末尾，并且 footer 的偏移字段同步更新：

```python
page_end = PAGE + ((len(rd_lz4) + PAGE - 1) // PAGE) * PAGE
new[page_end:page_end+vb_size] = img[vb_off:vb_off+vb_size]

nf = bytearray(footer_original)
struct.pack_into(">QQQ", nf, 12, page_end, page_end, vb_size)   # 大端！
new[-64:] = nf
```

完整脚本见 [01-root.md 3.4](01-root.md)。

### 经验

- **AVB footer 的字段是大端序**（`>IIQQQ`），不是小端
- `footer[4:36]` = `major, minor, original_image_size, vbmeta_offset, vbmeta_size`
- 写完必须校验：`d.find(b"AVB0")` 和 `d.find(b"AVBf")` 都要非负
- 这个错我们犯了两次，每次都靠 6 GB 备份恢复

---

## 坑 2：社区包的 TrustOS 与设备不匹配

### 现象

按某些教程额外刷了 `trustos_b`（社区包里叫 `tos.bin`），设备行为异常。

### 根因

对比后发现：

- 社区 `tos.bin` 与设备 dump 出来的 TrustOS 有 **611,443 / 5,195,528 字节不同（11.77%）**
- 社区包里标注 `B10`、`B15`、`B27` 的多个版本，**字节完全一样**——只是改了文件名
- 它们都来自同一个 6 月 8 日的构建

也就是说：**社区包里的 TrustOS 不是这台设备 B28 固件的对应版本**。

### 解法

**不要刷 TrustOS。**

只补丁 `init_boot` 就足够启动。`dis_avb_ex`（从 `sml_b` + `trustos_b` 生成免校验版本）也**不需要**——只要保持 AVB 结构完整，校验就能通过。

### 经验

社区流传的"必须刷 TrustOS 才能启动"是**针对另一个场景**（改 `super` 分区等系统级修改）。
只改 `init_boot` 不需要动它。

---

## 坑 3：`su` 找不到

### 现象

```bash
adb shell su -c id
# /system/bin/sh: su: inaccessible or not found
```

换成别的方式：

```bash
adb shell which su
# (空)
```

### 根因

**Magisk 28+ 不再往 `/system/bin/` 放 `su` 了。**

`su` 是一个指向 magisk 的符号链接，位于 Magisk 的临时挂载点：

```
/debug_ramdisk/su -> ./magisk
```

### 解法

```bash
adb shell /debug_ramdisk/su -c id
# uid=0(root) gid=0(root) context=u:r:magisk:s0
```

### 追加坑：`Permission denied`

即使路径对了，`adb shell`（uid 2000）第一次调用仍可能被拒——因为没有屏幕，**没法点"允许"**。

必须在 Magisk 数据库里预置策略：

```sql
UPDATE settings SET value=3 WHERE key='root_access';
INSERT OR REPLACE INTO policies (uid, policy, until, logging, notification)
VALUES (2000, 2, 0, 1, 1);
```

详见 [01-root.md 第 5 节](01-root.md)。

---

## 坑 4：`post-fs-data` 钩子静默失效

### 现象

写了一个脚本放到 `/data/adb/post-fs-data.d/`，重启后**完全没执行**。

没有报错，没有日志，就是什么都没发生。

### 根因（两个，叠加在一起）

#### ① Magisk 环境不完整

`/cache/magisk.log`：

```
** post-fs-data mode running
* Initializing Magisk environment
* Magisk environment incomplete, abort        ← 这里就退出了
```

`/data/adb/magisk/` 是空目录。无屏幕设备没法在 App 里点"安装"，Magisk 的自我初始化从未完成。
magiskd 检测到环境不完整，**直接跳过后续所有脚本**，不留任何错误提示。

→ 解法：[01-root.md 第 6 节](01-root.md)

#### ② overlay rc 的加载时机

修好环境后，又发现**自己注入的 init 服务**不执行：

```rc
on post-fs-data
    exec - root root -- ${MAGISKTMP}/xxx.sh     # ← 永远不触发
```

原因：**Magisk 的 overlay rc 是在 `post-fs-data` 之后才被 init 加载的**。
`post-fs-data` 触发器在 rc 被解析之前就已经 fire 过了，新的处理块永远等不到。

证据（`dmesg`）：

```
# 只有 late-start 的服务留下了执行记录
avc: denied { execute_no_trans } for comm="start_adbip.sh" ...
# post-fs-data 的块完全没有痕迹
```

→ 解法：把命令放到 `on late-start` 或更晚的触发器。

### 经验

**判断 Magisk 脚本机制是否健康，只看一行日志：**

```bash
grep "Running post-fs-data.d scripts" /cache/magisk.log
```

没有这一行，说明环境不完整，所有"开机自启"方案都是白写。

---

## 坑 5：微信把 USB 设备反复踢下线

### 现象

刷机过程中频繁失败：

```
LIBUSB_ERROR_IO         在 45% 左右
LIBUSB_ERROR_NO_DEVICE  刚 claim 就断
```

同时 `system_profiler` 能看到设备在 `1782:4D00` 和 `ncm,mtp` 之间**每 3 秒切换一次**。

### 根因

Mac 版微信会对每个新接入的 Android 设备发 **AOA（Android Open Accessory）探测**：

```
GETPROTOCOL  →  SENDSTRING  →  START
```

设备（gadget 里配了 `accessory.gs2`）照做，切进 accessory 模式（USB ID 变成 `18d1:2d00`）。
但这台设备没有应用接管配件会话，超时后退回 `ncm,mtp`——微信看到"新设备"，再探一次。

**死循环**，USB 每 3 秒重枚举一次。写数据写到一半就被拽走，必然失败。

### 解法

在 `post-fs-data` 阶段（早于 PackageManager 启动）用一个空的 `<permissions/>` 覆盖：

```sh
mount -o bind /data/adb/f50/empty-permissions.xml \
    /vendor/etc/permissions/android.hardware.usb.accessory.xml
```

系统不再声明 `android.hardware.usb.accessory` 特性后：

- `pm list features` 里该特性消失
- `UsbDeviceManager.startAccessoryMode()` 直接返回
- 微信的 AOA 探测变成空操作

**只做运行时 bind mount，不写任何分区**，删掉脚本就撤销。

> 注意 `/vendor` 是 **erofs 只读**（`dm-15`，`veritymode=enforcing`），
> 改不了文件，只能 bind mount。

### 经验

- 这类"USB 莫名其妙断"的问题，先看设备是否在**反复重枚举**，而不是怀疑线或口
- 判断 USB 是否真的连上，要用 `ioreg` / `system_profiler` 看设备是否在稳定枚举，而不是只看能否 ping 通

---

## 坑 6：写入中途 `LIBUSB_ERROR_IO`

### 现象

```
[=====          ] 45.4% Speed: 31.05Mb/s
LIBUSB_ERROR_IO
```

每次都在差不多的位置失败。

### 根因

物理层干扰：

- USB 接口接触不良
- 坑 5 的 AOA 重枚举（最常见）

### 解法

1. 先确认没有 AOA 干扰（关掉微信，或做坑 5 的修复）
2. 重新物理插拔，再跑一次同样的命令

**同样的写顺序重试是有效的**——`spd_dump` 会把分区重新写一遍，之前的半截数据不影响。

---

## 坑 7：BootROM 抢不到

### 现象

```
LIBUSB_ERROR_NO_DEVICE   on claim
```

`--wait` 已经连上了，但 `w_force` 刚要开始就断开。

### 根因

软重启（`goform` 的 `REBOOT_DEVICE`）进入 BootROM 的时间窗口很短，
`spd_dump` 抢到设备后，设备已经跑过 BROM 进入了别的状态。

### 解法

**物理断电重插**，不要在软件重启的同时跑 `spd_dump`。

流程：

1. 先启动 `spd_dump --wait 240 ...`（它会阻塞等待）
2. **然后**拔掉 USB 再插上
3. 设备进 BROM，`spd_dump` 自动接上

---

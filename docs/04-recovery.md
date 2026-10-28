# 04 · 变砖恢复

> 前提：**BootROM（展锐 BROM 模式）还能进**。
> 只要 BROM 还在，这台设备就永远救得回来——本文实测恢复 7 次。

---

## 1. 先判断设备处于什么状态

| 表现 | 状态 | 能否救 |
| --- | --- | --- |
| `adb devices` 有 `192.168.0.1:5555` | 正常 | 不需要救 |
| USB 显示 `1782:4D00` / `Sprd Gadget Serial` | **诊断模式**（AVB 结构问题） | ✅ 重刷 init_boot |
| USB 正常枚举 `ncm,mtp` 但**反复重启** | **TrustOS/TEE 层拒绝** | ⚠️ 需同时处理 `trustos_b`（见 [01-root.md §8](01-root.md)） |
| 完全没反应，`system_profiler` 里看不到设备 | 可能已关机 | 重插试试 |
| 插上后 macOS 报"未知设备"，无 USB ID | BootROM 也没了 | ⚠️ 需要短接（超出本文范围） |

### 检查命令

```bash
# 看 USB 上有什么
system_profiler SPUSBDataType | grep -iE "sprd|1782|ncm|zte|android"

# 看 adb
adb devices

# 看网络接口（正常时应有 en8 + 192.168.0.x）
ifconfig | grep -A2 "^en8"
```

---

## 2. 诊断模式（`1782:4D00`）恢复

**这是最常见的失败状态**，通常是 `init_boot` 补丁破坏了 AVB 结构。

### 恢复步骤

1. **拔掉 USB**
2. 启动刷写命令（会阻塞等待）：

```bash
cd "中兴F50Pro_macOS一键工具包_shuangye"
./bin/spd_dump_mac --wait 240 --kickto 2 \
    w_force init_boot_b backup/backup_xxx/init_boot_b reset
```

3. **插上 USB**（或按住按键插入，取决于设备）

4. 等待完成：

```
Device is using slot b
Write Part Done: w_force, target: 0x800000, written: 0x800000
Force Write init_boot_b Done
```

5. 设备自动重启，约 60–90 秒后恢复：

```bash
ifconfig en8 | grep "inet "     # 应有 192.168.0.x
adb devices                     # 应有 192.168.0.1:5555
```

### 如果还是不行

刷回**原厂完整的 init_boot**（备份里那个，未经任何修改）：

```bash
./bin/spd_dump_mac --wait 240 --kickto 2 \
    w_force init_boot_b backup/backup_xxx/init_boot_b reset
```

这会把 root 也一起抹掉，但能保证设备可用。

---

## 3. 完整分区还原

如果改的不止 `init_boot`（比如动了 `boot_b`、`super`、`vbmeta_b`），需要还原多个分区。

**还原顺序很重要**（先底层后上层）：

```bash
B=backup/backup_xxx
for p in splloader prodnv calinv trustos_b sml_b uboot_b boot_b \
         vendor_boot_b init_boot_b dtb_b dtbo_b vbmeta_b; do
    echo ">>> 还原 $p"
    ./bin/spd_dump_mac --wait 240 --kickto 2 w_force "$p" "$B/$p" reset 2>&1 | tail -2
    sleep 3
done
```

> ⚠️ `super`（3 GB）还原要 10 分钟以上，且中途断开会更麻烦。
> **只在确认系统分区损坏时才动它。**

---

## 4. 彻底救不回来时的最后手段

### 4.1 确认 BROM 是否还能进

```bash
# 插上设备后
system_profiler SPUSBDataType | grep -B2 -A6 "1782"
```

如果能看到 `1782:4D00` 之外的东西（比如 `1782:4D01`），说明 BROM 在。

### 4.2 展锐官方工具

`spd_dump` 之外，还可以试 Spreadtrum 官方的 **ResearchDownload**（Windows）。
它比 `spd_dump` 容错更强，能刷完整固件包（`.pac`）。

**但本设备没有完整的 B28 `.pac` 固件**——各共享渠道里都找不到。
所以这条路对本设备**不通**。

### 4.3 短接法

如果 BROM 都进不去，只能拆机短接 eMMC 的 BROM 引脚。
**风险极高，不在本文档范围内。**

---

## 5. 预防措施

### 5.1 改任何分区前先备份

```bash
./bin/spd_dump_mac --wait 240 r all_lite backup/
```

产出约 **6 GB / 50 个分区**。这是唯一的后悔药。

### 5.2 一次只改一个分区

改了 `init_boot` 就别同时动 `vbmeta`。
出问题时能立刻定位是哪个改动导致的。

### 5.3 改完立即验证 AVB 结构

```python
d = open("patched.img", "rb").read()
assert d.find(b"AVB0") > 0, "AVB0 丢失"
assert d.find(b"AVBf") > 0, "AVBf 丢失"
print("AVB0 @", hex(d.find(b"AVB0")), "| AVBf @", hex(d.find(b"AVBf")))
```

### 5.4 保留一个"已知能启动"的镜像

刷之前把当前能用的 `init_boot` 另存一份：

```bash
adb shell su -c "dd if=/dev/block/by-name/init_boot_b of=/data/local/tmp/init_boot_working.img"
adb pull /data/local/tmp/init_boot_working.img
```

出问题时先刷回它，确认是"新改动的问题"还是"设备本身的问题"。

---

## 6. 故障速查表

| 症状 | 最可能原因 | 处理 |
| --- | --- | --- |
| `1782:4D00`，无网络 | AVB 结构被破坏 | 重刷 `init_boot_b`（备份版） |
| 正常枚举但无限重启 | TrustOS/TEE 层校验 | 用本机 dump 派生免校验 TrustOS |
| 刷完能启动但无 root | Magisk 未初始化 / sqlite 策略缺失 | 检查 `/cache/magisk.log`，补 `/data/adb/magisk` |
| 有 root 但脚本不执行 | Magisk 环境不完整 | 同上，见坑 4 |
| `LIBUSB_ERROR_IO` 中途失败 | USB 干扰 / AOA 重枚举 | 关微信，物理重插，重试 |
| `LIBUSB_ERROR_NO_DEVICE` | BROM 窗口太短 | 物理断电重插，不要软重启 |
| 设备能 ping 通但无 HTTP | 系统服务未起 | 等 90 秒；仍不行则刷 `boot_b` |
| ADB 连不上但 2333 通 | adbd 被停 | 用 UFI-TOOLS 的 root_shell 拉起 adbd |
| 蜂窝有信号但无数据 | APN / `prodnv` 异常 | 还原 `prodnv` + `calinv` |

---

## 7. 恢复后必做的三件事

```bash
# ① 确认 root 还在
adb shell /debug_ramdisk/su -c id

# ② 确认 Magisk 环境完整
adb shell /debug_ramdisk/su -c "grep -c 'Running post-fs-data.d' /cache/magisk.log"

# ③ 确认网络正常
curl -s -m 10 -o /dev/null -w '%{http_code}\n' http://192.168.0.1/goform/goform_get_cmd_process?isTest=false\&multi_data=1\&cmd=network_type
```

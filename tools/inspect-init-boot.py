#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
init_boot 镜像结构检查器（只读）

用于确认一个 init_boot 镜像的 AVB 结构是否完整、Magisk 补丁是否正确。
不发任何写操作，可以安全地对任何镜像运行。

用法:
    python3 inspect-init-boot.py init_boot_b
    python3 inspect-init-boot.py --json init_boot_b_patched.img

退出码:
    0  结构完整
    1  结构有问题（AVB 丢失 / footer 不一致 / 无法解析）
    2  参数错误
"""

import argparse
import json
import struct
import subprocess
import sys

PAGE = 4096
BOOT_MAGIC = b"ANDROID!"
CPIO_MAGIC = b"070701"
LZ4_LEGACY = b"\x02\x21\x4c\x18"


def parse_cpio(data):
    """解析 newc cpio，返回 [{"name","size","offset"}, ...]"""
    out, i = [], 0
    while i + 110 <= len(data):
        if data[i:i + 6] != CPIO_MAGIC:
            break
        try:
            f = [int(data[i + 6 + k * 8:i + 14 + k * 8], 16) for k in range(13)]
        except ValueError:
            break
        ns, fs = f[11], f[6]
        name = data[i + 110:i + 110 + ns - 1].decode("utf-8", "replace")
        h = 110 + ns
        h += (-h) % 4
        out.append({"name": name, "size": fs, "offset": i + h})
        i = i + h + fs
        i += (-i) % 4
        if name == "TRAILER!!!":
            break
    return out


def inspect(path):
    r = {"file": path, "ok": False, "problems": [], "warnings": []}

    with open(path, "rb") as fh:
        img = fh.read()

    r["size"] = len(img)

    # --- boot header ---
    if len(img) < PAGE or img[:8] != BOOT_MAGIC:
        r["problems"].append("不是 Android boot image（magic 不匹配）")
        return r

    kernel_size = struct.unpack("<I", img[8:12])[0]
    ramdisk_size = struct.unpack("<I", img[12:16])[0]
    r["kernel_size"] = kernel_size
    r["ramdisk_size"] = ramdisk_size

    if ramdisk_size == 0 or PAGE + ramdisk_size > len(img):
        r["problems"].append(f"ramdisk_size={ramdisk_size} 不合理（超出文件范围）")
        return r

    # --- ramdisk ---
    rd = img[PAGE:PAGE + ramdisk_size]
    r["lz4_legacy"] = rd[:4] == LZ4_LEGACY
    if not r["lz4_legacy"]:
        r["warnings"].append("ramdisk 不是 LZ4 legacy 格式，可能已损坏或用了其他压缩")

    try:
        cpio = subprocess.run(["lz4", "-d", "-c"], input=rd,
                              capture_output=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        r["problems"].append(f"ramdisk 解压失败: {e}")
        return r

    r["cpio_size"] = len(cpio)
    if cpio[:6] != CPIO_MAGIC:
        r["problems"].append("解压后不是 cpio（magic 070701 不匹配）")
        return r

    entries = parse_cpio(cpio)
    r["entry_count"] = len(entries)
    r["entries"] = [e["name"] for e in entries]

    names = {e["name"] for e in entries}
    sizes = {e["name"]: e["size"] for e in entries}
    offsets = {e["name"]: e["offset"] for e in entries}

    # 重复条目（原厂镜像的 dev 会重复，Magisk 会报错）
    dup = [n for n in names if [e["name"] for e in entries].count(n) > 1]
    if dup:
        r["warnings"].append(f"cpio 有重复条目（Magisk 可能拒绝处理）: {dup}")

    # --- Magisk 补丁特征 ---
    r["magisk_patched"] = ("overlay.d" in names) or (".backup/.magisk" in names)
    if ".backup/.magisk" in names:
        off, sz = offsets[".backup/.magisk"], sizes[".backup/.magisk"]
        text = cpio[off:off + sz].decode("utf-8", "replace")
        meta = {}
        for line in text.splitlines():
            if "=" in line and line.split("=")[0].isupper():
                k, v = line.split("=", 1)
                meta[k] = v
        r["magisk_meta"] = meta
        if "SHA1" not in meta:
            r["warnings"].append(".backup/.magisk 缺少 SHA1")

    if "init" in names:
        r["init_size"] = sizes["init"]
        # magiskinit 在 B28 上是 197,256 字节
        if sizes["init"] == 197256:
            r["init_is_magiskinit"] = True

    # --- AVB ---
    avb0 = img.find(b"AVB0")
    avbf = img.rfind(b"AVBf")
    r["AVB0_offset"] = avb0
    r["AVBf_offset"] = avbf

    if avb0 < 0:
        r["problems"].append("找不到 AVB0（vbmeta）—— 启动会失败，设备会落进诊断模式")
    if avbf < 0:
        r["problems"].append("找不到 AVBf（footer）—— 启动会失败")
    if avb0 < 0 or avbf < 0:
        return r

    if avbf != len(img) - 64:
        r["warnings"].append(
            f"AVBf 不在文件末尾 -64 处（实际 0x{avbf:x}，期望 0x{len(img)-64:x}）")

    # footer 是大端
    footer = img[avbf:avbf + 64]
    try:
        maj, mi, orig_size, vb_off, vb_size = struct.unpack(">IIQQQ", footer[4:36])
    except struct.error:
        r["problems"].append("AVBf footer 解析失败")
        return r

    r["avb"] = {"major": maj, "minor": mi, "original_image_size": orig_size,
                "vbmeta_offset": vb_off, "vbmeta_size": vb_size}

    if vb_off != avb0:
        r["problems"].append(
            f"footer 指向的 vbmeta 偏移 (0x{vb_off:x}) 与实际 AVB0 位置 (0x{avb0:x}) 不一致")
    if vb_off + vb_size > len(img):
        r["problems"].append("footer 声明的 vbmeta 范围超出文件末尾")
    if vb_off % PAGE != 0:
        r["warnings"].append(f"vbmeta 偏移 0x{vb_off:x} 未页对齐")

    r["ok"] = not r["problems"]
    return r


def main():
    ap = argparse.ArgumentParser(description="init_boot 镜像结构检查器（只读）")
    ap.add_argument("image")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    r = inspect(args.image)

    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print(f"文件: {r['file']}")
        print(f"大小: {r.get('size')} 字节")
        if "ramdisk_size" in r:
            print(f"ramdisk: {r['ramdisk_size']} 字节 "
                  f"(LZ4 legacy: {r.get('lz4_legacy')})")
            print(f"cpio: {r.get('cpio_size')} 字节 / {r.get('entry_count')} 个条目")
        if r.get("magisk_patched"):
            print(f"Magisk 补丁: 是"
                  f"{' (init = magiskinit)' if r.get('init_is_magiskinit') else ''}")
            if r.get("magisk_meta"):
                for k, v in r["magisk_meta"].items():
                    print(f"  {k} = {v}")
        if "AVB0_offset" in r:
            print(f"AVB0: 0x{r['AVB0_offset']:x}")
            print(f"AVBf: 0x{r['AVBf_offset']:x}")
        if r.get("avb"):
            a = r["avb"]
            print(f"footer: major={a['major']} minor={a['minor']} "
                  f"vbmeta_off=0x{a['vbmeta_offset']:x} size={a['vbmeta_size']}")

        for w in r.get("warnings", []):
            print(f"⚠️  {w}")
        for p in r.get("problems", []):
            print(f"❌ {p}")

        print("\n结论:", "✅ 结构完整" if r["ok"] else "❌ 结构有问题，不要刷")

    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

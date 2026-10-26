# 02 · 高级后台 UFI-TOOLS

> 项目地址：<https://github.com/kanoqwq/UFI-TOOLS>
> 本设备实测版本：v4.0.0，端口 `2333`

---

## 1. 这是什么

UFI-TOOLS 是给随身 WiFi / CPE 设备用的**增强后台**，替代原厂那个简陋的 Web UI。

主要能力：

| 能力 | 说明 |
| --- | --- |
| 设备状态面板 | 信号、流量、温度、连接数 |
| **Root Shell** | 通过 HTTP API 执行 root 命令 |
| 插件系统 | JS 插件，官方商店 233 个 |
| 高级功能 | ttyd 网页终端、socat root shell、SMB 等 |
| 定时任务 | 类 cron |
| 网络工具 | 测速、抓包、APN 管理 |

> **它需要 root。** 没有 root 只能看状态，不能执行命令。

---

## 2. 安装

```bash
adb install -r UFI-TOOLS.apk

# 启动
adb shell am start -n com.kano.ufi.tools/.MainActivity
```

装好后监听 `0.0.0.0:2333`：

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://192.168.0.1:2333/
# 200
```

首次访问用默认密码 `admin` 登录，**装完第一件事就是改密码**（见第 6 节）。

---

## 3. API 鉴权算法

UFI-TOOLS 的 API 需要三个请求头。这段是逆出来的，官方文档没写全。

### 3.1 三个头

| 头 | 值 |
| --- | --- |
| `kano-t` | 当前毫秒时间戳（字符串） |
| `authorization` | `SHA256(密码)` 的**小写 hex** |
| `kano-sign` | 见下 |

`authorization` 是密码的 SHA256（小写 hex）。自己算一下就知道该填什么：

```bash
python3 -c 'import hashlib; print(hashlib.sha256(b"admin").hexdigest())'
```

### 3.2 签名算法

```
raw      = "minikano" + METHOD + PATH + timestamp
hmac     = HMAC_MD5(key, raw)                        # 16 字节
part1    = SHA256(hmac[0:8])                         # 32 字节
part2    = SHA256(hmac[8:16])                        # 32 字节
sign     = SHA256(part1 + part2)  → hex              # 小写
```

**三个关键点，错一个就 401：**

1. 前缀固定是 `minikano`
2. `PATH` 含前导 `/`，**不含 query string**（`?a=b` 部分不要）
3. `part1`/`part2` 必须用**原始 32 字节摘要**拼接，**不是 hex 字符串**

第 3 点是最容易踩的坑——很多实现写成 `sha256(h1.hexdigest() + h2.hexdigest())`，永远对不上。

**密钥从哪来：**

`key` 是 UFI-TOOLS **内嵌在 APK 里的固定值**，本项目不随仓库分发。从你手上那份 APK 提取即可：

```bash
unzip -p UFI-TOOLS.apk 'classes*.dex' | strings \
    | grep -oE 'minikano_[A-Za-z0-9_]+' | head -1
```

拿到后通过环境变量 `UFI_KEY` 传给下面的示例代码。

### 3.3 Python 参考实现

```python
import hmac, hashlib, time, urllib.request, json

import os

HOST   = "http://192.168.0.1:2333"
KEY    = os.environ["UFI_KEY"].encode()   # ← 从 APK 提取后 export
PWD    = "admin"                          # ← 改成你自己的后台密码

def call(method, path, body=None, timeout=20):
    ts  = str(int(time.time() * 1000))
    raw = ("minikano" + method + path + ts).encode()
    h   = hmac.new(KEY, raw, hashlib.md5).digest()

    # 关键：用原始摘要拼接，不是 hex
    sign = hashlib.sha256(
        hashlib.sha256(h[:8]).digest() + hashlib.sha256(h[8:]).digest()
    ).hexdigest()

    data = json.dumps(body).encode() if body else None
    req  = urllib.request.Request(HOST + path, data=data, method=method)
    req.add_header("kano-t", ts)
    req.add_header("kano-sign", sign)
    req.add_header("authorization", hashlib.sha256(PWD.encode()).hexdigest())
    if data:
        req.add_header("Content-Type", "application/json")

    return urllib.request.urlopen(req, timeout=timeout).read().decode()

# 示例：执行 root 命令
print(call("POST", "/api/root_shell",
           {"command": "id; uname -a", "timeout": 15000}))
```

---

## 4. 常用接口

### 4.1 执行 root 命令

```http
POST /api/root_shell
Content-Type: application/json

{"command": "pm list features | grep accessory", "timeout": 15000}
```

响应：

```json
{"result": "feature:android.hardware.usb.accessory\n"}
```

> 这是**最有用的接口**。设备没有屏幕时，靠它可以完成一切需要 root 的操作——
> 包括救活被自己搞挂的 ADB。

### 4.2 插件商店列表

```http
GET /api/plugins_store
```

响应结构（注意是嵌套的）：

```json
{
  "download_url": "<插件源地址，由 UFI-TOOLS 内置>",
  "res": {
    "code": 200,
    "data": { "content": [ {"name": "...js", "size": 12345}, ... ] }
  }
}
```

### 4.3 其他

| 接口 | 用途 |
| --- | --- |
| `GET /api/info` | 设备信息 |
| `GET /api/status` | 运行状态 |
| `POST /api/scheduledTask` | 定时任务 |

---

## 5. 插件生态

插件是 `.js` 文件，由 UFI-TOOLS 内置的插件商店分发（地址在 App 内返回，不在本文档重复）。本设备实测可拉取 **233 个**。

分类举例：

| 类别 | 插件 |
| --- | --- |
| 系统维护 | Magisk 模块守护、ADGuardHome、emmc 检测 |
| 设备控制 | 流量监控、断网自启、USB 网络模式切换 |
| 虚拟机 | OpenWrt / RouterOS / UEFI (QEMU) |

具体分类以 App 内插件商店为准，本文不逐一列举。

> ⚠️ 插件在设备上有 root 权限。装之前先看源码，尤其是要联网的。

---

## 6. 安全建议

**默认密码 `admin` + 监听 `0.0.0.0:2333` = 同一 WiFi 下任何人都能拿到 root。**

必做：

1. **改密码**（`authorization` 就是密码哈希，改了就换掉所有旧客户端）
2. 如果不用远程访问，防火墙限制 2333
3. 开了"高级功能"后还会多开端口（ttyd 1146、socat 等），同样暴露

检查当前暴露的端口：

```bash
adb shell su -c "netstat -tln | grep LISTEN"
```

本设备实测暴露的：

```
0.0.0.0:1146     ttyd（网页终端，直接 root shell）
0.0.0.0:2333     UFI-TOOLS 主界面
```

**这两个都是完整的 root 入口**，别在不可信网络里开着。

---

## 7. 与 Magisk 的关系

UFI-TOOLS 的部分高级功能（开机自启、模块守护插件）依赖 **Magisk 的脚本机制**：

- `/data/adb/service.d/*.sh`（开机后执行）
- `/data/adb/post-fs-data.d/*.sh`（`/data` 挂载后、Zygote 前执行）

**如果 Magisk 环境不完整，这些脚本会静默失效**，表现为"插件装了但没生效"。

排查方法见 [01-root.md 第 6 节](01-root.md)——
`/cache/magisk.log` 里出现 `Magisk environment incomplete, abort` 就是这个问题。

---

## 8. 救急：ADB 挂了怎么办

设备没有屏幕，ADB 是主要通道。如果 ADB 被搞挂（比如重启了 zygote），
**UFI-TOOLS 的 root_shell 是唯一还能用的入口**：

```python
call("POST", "/api/root_shell", {
    "command": "setprop service.adb.tcp.port 5555; start adbd; echo ok",
    "timeout": 20000
})
```

前提是 `2333` 还活着。所以：

> **不要同时改坏 ADB 和 UFI-TOOLS。**

本设备实测过一次：重启 zygote 后 adbd 被带走，靠这条命令救回来的。

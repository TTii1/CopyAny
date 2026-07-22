# CopyAny — 跨设备剪贴板历史共享

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Release](https://img.shields.io/github/v/release/TTii1/CopyAny)](https://github.com/TTii1/CopyAny/releases/latest)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11%20%7C%20Ubuntu%20Linux-blue)](#)
[![Python](https://img.shields.io/badge/python-3.11%2B-green)](#)

在多台电脑（Windows 10/11、Ubuntu Linux）之间共享剪贴板历史：任何一台复制的内容，
其他设备都能看到并可随时粘贴。同一套 Python 代码运行于两个平台。

> **Share clipboard history across your Windows and Linux machines** — copy on one
> device, paste on any other. AES-256-GCM encrypted, peer-to-peer over TCP, no cloud.

## 下载（开箱即用）

前往 [**Releases**](https://github.com/TTii1/CopyAny/releases/latest) 下载：

| 平台 | 文件 | 说明 |
|---|---|---|
| Windows 10/11 | `CopyAny.exe` | 单文件版，双击即用 |
| Ubuntu Linux x86_64 | `CopyAny-linux-x86_64.tar.gz` | 便携版，解压后直接运行，无需安装依赖 |

## 功能

- **剪贴板后台监控**：复制文本 / 图片自动入库，SHA256 去重
- **跨设备同步**：TCP 直连，新内容只广播哈希（约百字节），对端按需拉取；设备上线自动补齐缺失记录
- **历史面板**：全局快捷键（默认 `Ctrl+Q`）呼出，支持搜索、图片缩略图、置顶、删除
- **一键粘贴**：双击 / 回车 → 写入剪贴板 → 自动 `Ctrl+V`
- **剪贴板跟随（可选）**：面板底部「同步剪贴板」开关，开启后其他设备复制的内容直接写入本机剪贴板，
  无需呼出面板，`Ctrl+V` 即可粘贴。设备上线补齐的**旧历史**不会覆盖剪贴板；但对端在 1 分钟内
  刚复制的内容即使走了补齐通道（如 `have` 通知丢失、对端版本差异）也会按实时处理。
  各设备时钟可能不一致，远程记录的时间一律以**本机收到的时间**为准，面板顺序与剪贴板内容始终一致
- **系统托盘**：绿 / 红 / 灰圆点显示连接状态，最小化后台运行
- **设置面板**：GUI 内修改全部配置（群组、密钥、对端、端口、快捷键、历史上限），保存即生效
- **加密通信**：AES-256-GCM 加密传输 + HMAC-SHA256 双向挑战认证（预共享密钥）
- **本地存储**：SQLite，文本与 PNG 图片 BLOB，时间倒序，置顶免清理

## Windows 使用（已构建好，开箱即用）

```
dist\CopyAny.exe          # 单文件版，双击即用
dist\CopyAny\CopyAny.exe  # 目录版，启动更快
```

1. 双击运行，托盘出现图标，首次运行自动打开面板并生成默认配置
   （`%APPDATA%\CopyAny\config.yaml`）。
2. 打开 **设置**：修改群组 ID、共享密钥（≥8 位）、对端 IP 列表，保存即生效。
3. 两台设备配置相同的群组 ID + 密钥、互填对方 IP 后，托盘圆点变绿即已连通。
4. 防火墙弹窗请允许 `CopyAny.exe` 的 TCP 入站（默认端口 9527）。

重新构建：运行 `build\build_windows.bat`（需本机 Python 3.11+）。

## Linux 构建（Ubuntu 24.04 桌面版）

在 Linux 机器上执行：

```bash
sudo apt install -y python3 python3-venv python3-dev gcc   # 如已安装可跳过
bash linux/build.sh      # 检查依赖 -> 创建 venv -> 装依赖 -> 自检 -> PyInstaller 打包
bash linux/install.sh    # 安装到 ~/.local，创建桌面入口，可选开机自启
```

> `build.sh` 会先自检依赖，缺什么会给出对应的 `apt install` 提示（包括 Qt6 xcb
> 插件需要的 `libxcb-cursor0` 等系统库）。

> Ubuntu 24.04 默认禁止 pip 直装系统环境（PEP 668），脚本已用 venv 规避，不要直接
> `pip install -r requirements.txt` 到系统 Python。

构建产物：`dist/copyany/copyany`。配置文件：`~/.config/copyany/config.yaml`。

### 便携版（免构建，拷贝到其他 Linux 机器直接用）

`dist/CopyAny-linux-x86_64.tar.gz` 是打好包的便携版（Ubuntu 24.04 x86_64 桌面版构建，
Qt 需要的 `libxcb-cursor0` 等系统库已捆绑在 `syslib/` 内，目标机器无需装任何依赖）：

```bash
tar -xzf CopyAny-linux-x86_64.tar.gz
./copyany/CopyAny.sh        # 直接运行(便携启动器, 自动加载捆绑库)
```

如需桌面入口与开机自启，在拷贝过去的项目里执行 `bash linux/install.sh` 即可。

### ⚠ Wayland 注意事项（重点）

Ubuntu 24.04 默认登录会话是 **GNOME Wayland**，它对**所有**应用有两项硬性限制：

| 限制 | 影响 | 解决 |
|---|---|---|
| 后台窗口不能读取剪贴板 | 其他窗口复制时无法自动监控 | **推荐**：登录界面选择 "Ubuntu on Xorg"（功能完整）；留在 Wayland 则面板在前台时才能收录 |
| 后台窗口不能写入剪贴板 | 「同步剪贴板」自动写入失效 | 同上：改用 Xorg 会话；Wayland 下收到内容仍会在面板中，可照常双击粘贴 |
| 应用不能注册全局热键 | `Ctrl+Q` 无法由应用捕获 | 用 GNOME 自定义快捷键替代（见下） |

**Wayland 下的替代方案：**

1. 呼出面板：设置 → 键盘 → 查看及自定义快捷键 → 自定义快捷键，添加：
   - 名称：`CopyAny`
   - 命令：`~/.local/share/copyany/copyany --show`
   - 快捷键：`Ctrl+Q`
2. 自动粘贴（可选）：`sudo apt install ydotool`；未安装时双击记录后需手动 `Ctrl+V`。
3. 面板底部的黄色提示条会提醒当前处于受限的 Wayland 会话。

X11 会话（"Ubuntu on Xorg"）下以上功能全部原生可用，无需任何额外配置。

## 配置说明

配置文件首次运行自动生成（设置界面可视化修改，无需手编）：

```yaml
group_id: "my-group"            # 群组标识，同群组设备共享历史
shared_key: "至少8位"            # 共享密钥，同群组所有设备必须一致
listen: {host: "0.0.0.0", port: 9527}
peers:                          # 其他设备 IP
  - {host: "192.168.1.100", port: 9527}
history: {max_items: 1000}      # 置顶条目不参与清理
hotkey: {key: "ctrl+q"}
clipboard: {auto_receive: false} # 对端复制的内容自动写入本机剪贴板(面板底部开关)
```

两台设备连通条件：**相同 group_id + 相同 shared_key + 至少一方把另一方填入 peers +
端口可达**。双向互填或单向填写均可（连接是双向认证的，任一方向建立即可同步）。

## 通信协议

- TCP 直连，帧格式：`4 字节大端长度前缀 + 消息体`
- 握手（明文）：双方互发 `hello{group, nonce}` → 互发 `auth{hmac=HMAC(key, 对方nonce)}`，
  群组不一致或 HMAC 校验失败即断开
- 密钥：`PBKDF2-HMAC-SHA256(shared_key, salt=group_id, 200k 轮)` 派生 32 字节
- 握手后所有消息为 `12 字节 nonce + AES-256-GCM 密文(JSON)`
- 消息类型：`sync`（全量哈希清单）/ `want`（批量拉取）/ `item`（内容，
  base64）/ `have`（新内容哈希通知）/ `dup`（重复连接通知）/ `ping` / `pong`
- **连接去重**：握手时交换 `device_id`，两台互填 IP 产生的双向双连接只保留一条，
  被弃连接收到 `dup` 后停止重拨；与老版本互通时两条都保留、仅状态显示去重，
  避免老版本被断开后反复重连

## 目录结构

```
copyany/
  config.py     配置加载/保存（含首次运行模板）
  crypto.py     AES-256-GCM / PBKDF2 / HMAC
  store.py      SQLite 历史库（去重/置顶/搜索/清理）
  net.py        TCP 服务端+客户端、认证握手、增量同步
  clipmon.py    剪贴板监控（Qt QClipboard）
  hotkey.py     全局热键（pynput；Wayland 优雅降级）
  paster.py     模拟 Ctrl+V（pynput / ydotool）
  icons.py      运行时代码绘制图标（无图片资源依赖）
  gui/          暗色主题 / 历史面板 / 设置对话框 / 托盘
  app.py        应用装配与单实例
  selftest.py   核心自检（--selftest）
build/          图标生成、Windows 构建脚本、GUI 冒烟测试
linux/          Linux 构建/安装脚本、desktop 文件
run.py          源码入口：python run.py
```

## 故障排查

- **连不上先点"测试连接"**：设置 → 连接测试 → 测试连接。用当前填写的配置（无需保存）
  逐个探测对端，逐步指出失败原因并给出建议：防火墙未放行端口、对方未启动、端口被其他
  程序占用、群组 ID / 共享密钥不一致等，还会列出本机 IP（让对方填这个）。
- **托盘红点**：对端不可达。检查 IP/端口、防火墙（Linux: `sudo ufw allow 9527/tcp`）、
  两端群组 ID 与密钥是否一致。
- **日志**：`%APPDATA%\CopyAny\copyany.log`（Windows）或 `~/.config/copyany/copyany.log`。
- **远程记录排在本机新记录之上**：两台设备时钟不一致所致。新版已不再采用对端时间戳——实时推送的
  记录按本机收到的时间排列（补齐的历史记录保留原时间），建议两台设备都开启系统"自动设置时间"。
- **自检**：源码环境运行 `python run.py --selftest`（加密/存储/双节点同步共 4 组）。
- **Linux 托盘不显示**：Ubuntu 24.04 默认带 AppIndicator 扩展；若被禁用请重新启用。
- **端口被占用**：日志会有"监听失败"，设置里换一个端口即可。

## 贡献

欢迎提交 Issue 与 Pull Request，详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 开源协议

本项目基于 [MIT License](LICENSE) 开源。

<p align="center">
  <img src="docs/icon.png" width="180" alt="ReelCompact icon">
</p>

<h1 align="center">ReelCompact · 轻帧</h1>

<p align="center">
  A native macOS Finder Quick Action that compresses videos below 20 MB while preserving as much visual quality as possible.
</p>

<p align="center">
  <a href="https://github.com/HugoOvo/reelcompact/releases/latest">Download</a> ·
  <a href="#简体中文">简体中文</a> ·
  <a href="#english">English</a>
</p>

---

## 简体中文

### ReelCompact 是什么？

ReelCompact 是给 macOS Finder 用的视频压缩工具。选中一个或多个视频，右键进入“快速操作”，即可把文件压缩到 **19.5 MiB** 以下。

它最初是为需要向 Antigravity 上传视频做拉片的场景而写，但所有对视频大小有硬限制的平台都可以使用。

### 功能

- Finder 右键直接调用，支持多选批量
- H.264 兼容模式与 H.265 高画质模式
- FFmpeg 两轮编码，动态计算目标码率
- 使用 VMAF 抽样比较候选分辨率
- HDR 自动映射为 SDR BT.709
- 音频转为 AAC，并为视频码率动态让出空间
- 编码后强制校验文件大小和时长
- 实时进度、取消、失败提示和成功通知
- 原视频永不修改或删除
- 输出到原视频旁，重名时自动递增

输出文件名：

```text
原文件名_20MB_H264.mp4
原文件名_20MB_H265.mp4
```

### 安装

1. 从 [Releases](https://github.com/HugoOvo/reelcompact/releases/latest) 下载 ARM64 DMG。
2. 把 `ReelCompact.app` 拖到 Applications（应用程序）。
3. 打开一次 App，它会自动注册 Finder 快速操作。
4. 到 **系统设置 → 访达**，打开两个“压缩到20MB”开关。

DMG 内含静态 FFmpeg、libx264、libx265 和 libvmaf，不依赖 Homebrew 或 Rosetta。

### 使用

在 Finder 中选中视频，右键 → **快速操作**：

- **压缩到20MB（H.264 兼容）**
- **压缩到20MB（H.265 高画质）**

### 工作原理

1. `ffprobe` 读取时长、分辨率、帧率、HDR、旋转和音轨信息。
2. 根据 19.5 MiB 目标计算总码率预算。
3. 用码率/像素/帧快速筛选候选分辨率，再用最多三段样本进行 VMAF 比较。
4. 用 libx264 或 libx265 执行两轮平均码率编码。
5. 检查输出大小与时长；超限时按实测比例降低码率重试。
6. 仅在完整校验通过后，把临时文件移动到最终路径。

### 从源码构建

要求：

- Apple Silicon Mac
- macOS 13+
- Xcode Command Line Tools
- Python 3

```sh
make test
make install
```

生成 DMG：

```sh
make dmg
```

产物位于 `outputs/`。

### 项目结构

```text
src/ReelCompact.swift    SwiftUI 进度窗口与快速操作安装器
src/shrink_core.py       FFmpeg 探测、VMAF 选档、编码与校验
scripts/                 安装、构建与 DMG 脚本
tests/                   单元测试和端到端测试
assets/                  原创 SVG 与 macOS ICNS 图标
```

### 隐私

ReelCompact 全程在本机运行。它不包含账号系统、遥测、网络请求或自动上传功能。

### 兼容性

- 当前发布的 DMG 仅支持 ARM64。
- H.264 的播放兼容性最好；H.265 文件更小，但目标平台未必支持 HEVC。
- HDR 视频默认转换为 SDR BT.709，以降低发灰、偏色和播放器兼容问题。

### 许可证

项目源代码采用 [MIT License](LICENSE)。随安装包分发的第三方二进制组件见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

---

## English

ReelCompact is a native macOS Finder Quick Action that compresses videos below **19.5 MiB** with FFmpeg, adaptive bitrate planning, VMAF-assisted resolution selection, and verified output.

### Highlights

- H.264 and H.265 modes
- Batch-friendly Finder Quick Actions
- Software two-pass encoding
- VMAF sample evaluation
- HDR-to-SDR conversion
- Progress window with cancellation
- Local-only processing with no telemetry
- Original files are never modified

### Download

Get the latest Apple Silicon DMG from [Releases](https://github.com/HugoOvo/reelcompact/releases/latest).

Drag the app to Applications, launch it once, then enable the two Finder actions in **System Settings → Finder**.

### Build

```sh
make test
make dmg
```

### License

MIT. See [LICENSE](LICENSE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

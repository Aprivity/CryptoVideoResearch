# V0.7 本地 ASR（faster-whisper）· 安装、工作原理与验收

本版本新增**可选**离线语音识别作为 YouTube 无字幕视频的备选路径。现有 YouTuber 菜单、默认新闻模式、DeepSeek、独立报告和缓存均保留，不做投资建议或交易。默认关闭以避免无意间下载模型、音频或占用大量算力。

## 一、Ubuntu 从 V0.6 进入 V0.7

在原源码目录执行：

```bash
cd ~/CryptoVideoResearch
git remote set-branches --add origin feat/v0.7-local-asr
git fetch origin
git switch --track origin/feat/v0.7-local-asr
bash run.sh
```

如果已经创建过 V0.7 本地分支，改用 `git switch feat/v0.7-local-asr && git pull --ff-only`。

**首次开启 ASR**：交互菜单 →「运行设置」→「无字幕时启用本地 ASR」。建议先把 Cookies 改为 `chrome`（本人浏览器已正常登录 YouTube）、每轮报告数改成 1、模型选择 `base`（功能验收较省资源）；日常可以换回 `small` 提高识别质量。首次真正触发无字幕视频时，菜单会请求安装运行依赖。手动安装等价：

```bash
./.venv/bin/cryptovideo asr-setup
```

仅安装 Python 可选依赖，不会预先下载 Whisper 模型。第一次实际转写所需的模型权重会从网络获取并缓存在 `~/.cache/cryptovideoresearch/whisper-models/`；再次使用同型号时复用。

## 二、命令行直接分析一个视频（建议先验收）

针对经过用户验证“有音频但无字幕”的测试视频：

```bash
cd ~/CryptoVideoResearch
./.venv/bin/cryptovideo asr-setup
# 先免费测试 ASR：只生成 VTT，不调用 DeepSeek
./.venv/bin/cryptovideo transcribe 'https://www.youtube.com/watch?v=DiDuGTf_-0g' \
  --cookies chrome --asr-model base \
  --output-dir ./outputs/asr-validation
# VTT 验收后再调用 DeepSeek 生成独立报告
./.venv/bin/cryptovideo analyze 'https://www.youtube.com/watch?v=DiDuGTf_-0g' \
  --cookies chrome --asr-fallback --asr-model base \
  --output-dir ./outputs/asr-validation
```

如果 YouTube 访问正常，程序会尝试 VTT 字幕 → 没有可用字幕 → yt-dlp 下载 **单独音频流**（优先 M4A）→ faster-whisper 本地识别 → 带时间戳 VTT。上面的 `transcribe` 命令不会调用 DeepSeek；之后再执行 `analyze` 生成中文研究报告，并复用本地 VTT。报告和转写结果都以本地文件保存。

单视频输出示例：

```text
outputs/asr-validation/
└── DiDuGTf_-0g/
    ├── local-asr-base.vtt
    ├── analysis.md
    └── report.json
```

默认成功后删除所下载的源音频，只保留转写文本和报告；如要保留音频加 `--keep-audio`。转写或程序中断失败时保留已下载音频，以便重试。完整报告路径取决于 `--output-dir`。

## 三、菜单模式或脚本模式

```bash
# 有保存频道的交互方式
bash run.sh

# 脚本方式，对指定 YouTuber 的最近上传视频处理
./.venv/bin/cryptovideo run \
  --channel 'https://www.youtube.com/channel/UCGpj3DO_5_TUDCNUgS9mjiQ/videos' \
  --cookies chrome --count 1 --asr-fallback --asr-model base

# 默认全站市场新闻也可开启 ASR
./.venv/bin/cryptovideo run --count 1 --cookies chrome --asr-fallback
```

`--asr-model` 支持 `tiny`、`base`、`small`（默认）、`medium`。默认 `--asr-device cpu` 使用 `int8`，适合通用 Ubuntu；`--asr-device cuda` 需要兼容的 NVIDIA CUDA/cuDNN 运行环境，程序不会自动配置显卡驱动。

`--count N` 仍限制每轮 DeepSeek 模型调用次数，而且本地 ASR 回退尝试次数也有限。大模型转写长视频可能需要较长时间、较多 RAM/VRAM，不保证实时完成。音频下载上限为 250 MiB，避免无限制拉取。

## 四、数据与安全边界

- **优先使用原生字幕**。如果字幕存在、有效，不下载音频、不加载 Whisper。
- 若确实没有有效字幕，且启用了 ASR，才下载音频并执行本地推理。无法提取合法 VTT 的时候不会把视频简介发给 DeepSeek。
- **访问验证并非无字幕**。如果 yt-dlp 遭遇 `Sign in to confirm you're not a bot` 等明确的验证阻断，程序不会启动 ASR；请先使用你自己的登录态解决正常访问。
- Whisper 下载模型权重需要联网。**转写计算在本地进行，但不是全离线研究系统**：YouTube 音频下载联网，之后文本交由 DeepSeek API 进行云端分析。
- VTT 保存本地、每个视频独立，遇到缓存命中不会重复下载音频和调用语音模型。较旧的现成分析报告仍使用已有缓存。
- 字幕与本地 ASR 都可能听错术语、数字、公司与人名；研究报告只能作为视频观点摘要，需要独立事实核验。
- 当前音频仅从用户提供或所选频道的公开视频取得。请尊重平台条款和内容版权，勿传播未经授权的源音频。

## 五、离线测试

```bash
./.venv/bin/python -m unittest discover -s tests -v
```

自动化测试使用假音频/假模型，不真正访问 YouTube，也不会下载安装模型权重。它覆盖了字幕优先、无字幕回退、VTT 时间戳、缓存、Cookie 传入、模型调用上限，以及 YouTube 验证错误不会触发 ASR。真实的 `DiDuGTf_-0g` 视频下载 + 首次 Whisper + DeepSeek 仍需在你的 Ubuntu 本机做端到端测试。

参考官方文档：

- https://github.com/SYSTRAN/faster-whisper
- https://github.com/yt-dlp/yt-dlp

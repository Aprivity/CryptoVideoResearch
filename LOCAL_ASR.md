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

## 六、Ubuntu 本地 SOCKS 代理（`socks://`）兼容性

在安装 `faster-whisper` 后，部分 Clash/系统代理环境会将 `HTTP_PROXY`、`HTTPS_PROXY` 或 `ALL_PROXY` 设为 `socks://127.0.0.1:7890`。YouTube 下载已经成功、但是 Hugging Face 模型首次下载时报：

```text
Local ASR failed: Unknown scheme for proxy URL URL('socks://127.0.0.1:7890')
```

这是**模型下载时的 HTTPX 代理协议兼容问题**，不是本地语音推理错误，也不证明音频文件损坏。

V0.7 现在仅在加载 Whisper 模型的期间，将环境中 `socks://` 临时规范成 HTTPX 支持的 `socks5://`，并在加载结束或异常时恢复全部原值（包括 `ALL_PROXY` 和大小写不同的变量）；不会永久修改 Ubuntu 的全局代理，也不会更换用户的代理地址/端口。可选 ASR 依赖现在包含 `httpx[socks]`，如果曾在旧版安装 ASR，请**更新代码后再执行一次**：

```bash
cd ~/CryptoVideoResearch
git pull --ff-only
./.venv/bin/cryptovideo asr-setup
./.venv/bin/cryptovideo transcribe \
  'https://www.youtube.com/watch?v=DiDuGTf_-0g' \
  --cookies chrome --asr-model base \
  --output-dir ./outputs/asr-validation
```

`transcribe` 不调用 DeepSeek；已下载的音频文件在首次模型下载失败后会保留并复用。注意 `socks5://` 是代理协议指定，不是代理一定可用的证据：如果后续报连接超时、证书、Hub 下载地址被阻断等，需另外检查本地代理实际连通性。绝不要为排障关闭 HTTPS 证书验证。

## 七、pip 报 Missing dependencies for SOCKS support

若执行 `cryptovideo asr-setup` 时，在 `Installing build dependencies` 阶段报：

```text
ERROR: Could not install packages due to an OSError:
Missing dependencies for SOCKS support.
```

这是 **pip 自己缺少 PySocks 依赖**，不等于 `faster-whisper` 不兼容。旧安装器虽然把 `socks://` 改成 `socks5://`，但无法解决 pip 的引导依赖问题。

最新版 `asr-setup` 改为直接安装 `faster-whisper` 和 `httpx[socks]`，无需对本项目重复执行隔离式 editable 构建。如果本机尚未安装 PySocks，但本地代理配置是 `socks://127.0.0.1:7890`，安装器会在 **pip 子进程中临时尝试** `http://127.0.0.1:7890`；这要求该端口支持 HTTP CONNECT（例如代理软件的 mixed-port）。**并不是所有 SOCKS 端口都支持 HTTP**。

建议先执行：

```bash
cd ~/CryptoVideoResearch
git pull --ff-only
./.venv/bin/cryptovideo asr-setup
```

如果代理服务没有在 7890 提供 HTTP/mixed 服务，就在本地代理客户端中查找实际 HTTP/mixed 监听端口，例如 7891（**仅示例，不代表你的端口**），运行：

```bash
./.venv/bin/cryptovideo asr-setup --pip-proxy http://127.0.0.1:7891
```

`--pip-proxy` 只接受 HTTP(S) 代理，不接受 SOCKS；它仅作用于 pip 安装子进程。可以先验证一个端口是否为可用的 HTTP/mixed 代理：

```bash
curl --max-time 10 -I --proxy http://127.0.0.1:7890 https://pypi.org/simple/pysocks/
```

看到来自 PyPI 的 HTTP 响应，才说明这个 HTTP 代理配置可能可用。若提示 `Could not connect` 或 `Proxy CONNECT aborted`，应使用实际的 HTTP/mixed 端口而不是反复盲试。请勿关闭 TLS 证书校验。

完成依赖安装后，再运行不调用 DeepSeek 的本地转写：

```bash
./.venv/bin/cryptovideo transcribe \
  'https://www.youtube.com/watch?v=DiDuGTf_-0g' \
  --cookies chrome --asr-model base --output-dir ./outputs/asr-validation
```

## 八、Python 3.14 / PyAV 19 与 faster-whisper 1.2.1 兼容性

Ubuntu 若已安装 `av==19.0.2` 和 `faster-whisper==1.2.1`，转写可能遇到：

```text
Local ASR failed: open() got an unexpected keyword argument 'metadata_errors'
```

这是旧版 faster-whisper 传入了 PyAV 19 已移除的 `metadata_errors` 参数。官方已在源代码中通过按 PyAV 版本选择参数修复，但 1.2.1 发布版仍可能遇到问题。上游参考：https://github.com/SYSTRAN/faster-whisper/issues/1589 和 https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/audio.py 。

**本项目现使用局部兼容适配层，不需要下载或降级 PyAV。** 在实际 ASR 解码期间，只对旧调用删除该关键字参数，其余参数原样传递；转写结束或失败时恢复原始 `av.open`。不修改已安装库，也不改变其他进程。

如果日志中尝试 `pip install av<19` 但出现 `Temporary failure in name resolution`，这是 pip 包源 DNS/网络无法连通，不能据此断言 PyAV 无兼容版本。对于你已经装好 PyAV 19 的环境，优先更新源码并重新运行；无需再执行 `asr-setup`：

```bash
cd ~/CryptoVideoResearch
git pull --ff-only
./.venv/bin/cryptovideo asr-setup
./.venv/bin/cryptovideo transcribe \
  'https://www.youtube.com/watch?v=DiDuGTf_-0g' \
  --cookies chrome --asr-model base \
  --output-dir ./outputs/asr-validation
```

新的 `asr-setup` 在已安装 faster-whisper、PyAV、SOCKS 支持时会直接返回成功，**不调用 pip**。此前下载的音频和模型缓存应被复用，`transcribe` 本身不调用 DeepSeek。

注意兼容适配层的可靠性仍需在 Ubuntu 真实音频测试确认；现有 CI 主要验证了适配层参数处理、恢复现场及转写流程，不等于已经在你的机器上完成验收。

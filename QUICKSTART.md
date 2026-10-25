# CryptoVideoResearch V0.5 · 一键视频报告

面向 Ubuntu 22.04、24.04、26.04；包含 B 工作流（YouTube 市场新闻视频搜索、单独分析和报告存储）。目前**没有 Windows .exe**，不要把 Linux 的 run.sh 当成 Windows 程序。

## 方式 A：浏览器下载 ZIP，运行一条命令

1. 打开仓库分支 https://github.com/Aprivity/CryptoVideoResearch/tree/feat/v0.5-one-command-reports
2. 点击 Code → Download ZIP，把 ZIP 解压到**你愿意长期保留的位置**。
3. 在解压目录打开终端，执行：

```bash
bash run.sh
```

首次运行会通过 sudo/apt 安装 Python、Git、curl、Node.js、Summarize、yt-dlp、pipx，创建本地虚拟环境，隐藏输入 DeepSeek API Key，搜索 YouTube 并默认尝试生成 2 份单视频分析报告。无需手动执行 pip/npm/yt-dlp 命令。需要网络；如果 YouTube/DeepSeek 在所在网络不可达，需配置自己可用的网络连接或代理。此脚本**不会**自动登录浏览器或破解验证码。

如果需要浏览器 Cookies：

```bash
bash run.sh --cookies chrome
```

Chrome 需要事先安装并已在桌面登录。下载 ZIP 后切勿把项目文件随意移动，否则用户级 CLI 软链接可能失效。Git 源码克隆可支持后续快进更新；ZIP 不包含 Git 历史，无法自动拉取更新。

## 方式 B：全新 Ubuntu，直接在终端安装并生成报告

没有 curl 时，先由 apt 安装；整行复制即可：

```bash
sudo apt-get update && sudo apt-get install -y curl && curl -fL --retry 3 -o /tmp/cvr-install.sh https://raw.githubusercontent.com/Aprivity/CryptoVideoResearch/0554f7d98ba0a2a3688083b08d6f5869921bc907/scripts/bootstrap.sh && bash /tmp/cvr-install.sh
```

上面的地址固定在包含 V0.5 安装逻辑的提交，避免 GitHub Raw 分支路径缓存旧内容；安装器内部仍检出 V0.5 功能分支。建议执行前先阅读 [scripts/bootstrap.sh](scripts/bootstrap.sh)，因为脚本会安装系统软件并执行用户态网络请求。

## 后续只需一条命令

```bash
cryptovideo run
```

在当前终端 PATH 尚未更新时，先执行 `source ~/.profile`；或者始终通过源码目录执行 `bash run.sh`。

参数：

```bash
# 默认 2 份单视频报告，每轮至多 2 次 DeepSeek 模型调用尝试
cryptovideo run

# 至多 3 份独立视频报告，每轮至多 3 次模型调用尝试
cryptovideo run --count 3

# 限定 48 小时，增加日期核验，允许浏览器认证
cryptovideo run --hours 48 --verify-top 15 --cookies chrome

# 只分析日期已知、且在时间窗口内的视频；可能没有可分析候选
cryptovideo run --strict-dates

# 强制重新分析已有视频（会再次产生模型费用）
cryptovideo run --refresh

# 只搜索视频候选：不调用 DeepSeek
cryptovideo youtube-news --verify-top 10
```

默认情况下会优先二次查证 YouTube 视频发布日期、过滤确认过期的视频；如果 YouTube 无法提供日期，`cryptovideo run` 仍允许分析，但会保留**发布时间未知**的标记。想排除所有日期未知的视频时，使用 `--strict-dates`。

**花费和失败边界：** 输入 DeepSeek API Key 才会执行付费视频分析；`--count N` 将每次运行的模型调用尝试限制为 N（默认 2，允许 1–5），若 YouTube/字幕不可用可能生成少于 N 份报告。已经生成的报告默认使用缓存，不重复计费。费用由所选模型和输入规模决定，CLI 不保证具体金额。搜索与元数据查询不消耗 DeepSeek 额度。

## 输出文件

- `~/CryptoVideoResearch/outputs/youtube-news/latest.md`：本轮候选列表与分析情况（默认 Git 克隆安装目录）。
- `~/CryptoVideoResearch/outputs/youtube-news/latest.json`：机器可读的元数据。
- `~/CryptoVideoResearch/outputs/youtube-news/seen.db`：候选视频去重记录。
- `~/CryptoVideoResearch/outputs/youtube-news/videos/<视频ID>/analysis.md`：**每个视频独立的报告**。

ZIP 安装时，输出位于你解压的项目目录下的同名 `outputs/youtube-news` 路径，而不是一定在 `~/CryptoVideoResearch`。

你不必将不同的视频观点合并成总报告。本项目只整理视频转述的新闻线索和博主观点，不将未核实的视频内容等同于权威新闻，也不提供投资建议、交易信号或下单能力。

## 技术说明

目前使用外部工具 `yt-dlp` + `Summarize`，以及 DeepSeek 云端 API。因此 Python 打包成单个可执行文件仍不能保证脱离 Node.js / 网络 / 账号环境独立运行。对于 Ubuntu，下载 ZIP + `bash run.sh` 是更透明、体积更小、维护成本更低的可执行方案；Windows .exe 需要单独实现 Windows 下的环境管理和打包验证。

## 搜索成功但没有生成报告：字幕可用性

如果日志显示 `[PASS] videos=20 ... analyzed=0`，且 `latest.md` 报告 `No valid complete subtitle file was obtained`，表示**YouTube 视频搜索正常，但候选视频没有可下载的字幕，或者网络／Cookies 无法下载字幕**。不会自动将视频简介当作逐字稿，也不代表 DeepSeek Key 无效。

V0.5 已增加区域中文字幕匹配及最多检查 10 条候选（当 `--count 1` 时），并优先识别视频元数据内可用的 VTT 字幕轨。若仍没有可用字幕，则本次不会产生单视频报告。

诊断具体视频是否提供字幕：

```bash
~/.local/bin/yt-dlp --skip-download --js-runtimes node --list-subs --cookies-from-browser chrome 'https://www.youtube.com/watch?v=l9yIi3iYiU0'
```

这条命令不会下载视频或调用 DeepSeek。检查是否显示 `zh`、`zh-TW`、`zh-CN`、`en` 的 VTT 字幕轨。也可不加 `--cookies-from-browser chrome` 比较匿名访问的结果。若 YouTube 根本没有字幕，这不是下载器能保证修复的；后续需要独立的音频转写（如可选本地 ASR）功能。

在已有 V0.5 Git 仓库中升级字幕改进，无须重新部署依赖：

```bash
cd ~/CryptoVideoResearch
git pull --ff-only
bash run.sh --count 1 --cookies chrome
```

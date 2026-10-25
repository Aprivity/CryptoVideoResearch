# CryptoVideoResearch

## V0.7 · 本地 ASR 语音转写回退

B 模块现在可以在 **YouTube 原生字幕不可用时，选择性使用本地 `faster-whisper` 将单视频音频转成带时间戳的 VTT，再用 DeepSeek 生成原有的独立报告**。本地语音识别不按分钟收取云端转写费用；DeepSeek 视频分析仍调用网络 API。详细说明见 [LOCAL_ASR.md](LOCAL_ASR.md)。

- 默认 **ASR 关闭**，现有字幕分析不受影响。
- 交互菜单 `cryptovideo` →「运行设置」→「无字幕时启用本地 ASR」，首次运行会明确询问是否安装可选依赖。
- 也可使用 `cryptovideo asr-setup` 主动安装依赖；实际首次转写时再下载模型到本机缓存。
- 无字幕时才下载音频，不下载画面；模型默认 `small` + CPU `int8`，也可切换 `tiny/base/medium`、选择有对应驱动环境的 CUDA。
- 转写成 `videos/<视频ID>/local-asr-small.vtt`，默认完成后清理音频，保存 VTT 供以后重复分析；可选保留音频。
- 遇到 YouTube 登录/验证限制，程序仍然停止请求，不会尝试通过音频绕过访问限制。

```bash
# 菜单模式
bash run.sh

# 无界面脚本模式：启用可选本地 ASR，最多 1 次 DeepSeek 调用
cryptovideo run --channel @YourHandle --cookies chrome --count 1 --asr-fallback
```

---


## V0.6 · B 工作流交互式 CLI

**默认搜索市场新闻，或明确指定 YouTuber 并保留选择。** Ubuntu 终端直接运行：

```bash
cryptovideo
# 或进入源码目录
bash run.sh
```

回车（不输入）默认执行市场新闻搜索和各视频独立分析；按 **↑ / ↓ + 回车** 或 **数字键** 切换选项。输入 YouTuber 的 `@handle`、官方 YouTube 频道链接，或名称并从搜索结果中确认频道；保存的频道可重复选择、也可以删除。每个频道独立保存报告；设置（每轮 DeepSeek 调用次数、时间范围、Cookies、严格时效）自动保存到用户本地配置，**不会提交到 Git**。

```text
❯ [1] 搜索市场新闻（默认，回车）
  [2] 输入 YouTuber 名称 / @handle / 链接
  [3] 已保存的 YouTuber
  [4] 运行设置
  [5] 查看报告位置
  [6] 退出
```

旧命令继续支持：`cryptovideo run --count 1 --cookies chrome` 和 `bash run.sh --count 1`；脚本和自动化环境不显示交互菜单。也可直接指定 `cryptovideo run --channel @YourHandle --count 1`。

详细教程：[INTERACTIVE_CLI.md](INTERACTIVE_CLI.md)。

---


**V0.5 — 一键生成独立的 YouTube 市场新闻视频研究报告。** 不提供投资建议、交易信号或下单能力。

## 从零使用（Ubuntu 22.04 / 24.04 / 26.04）

**方法 1：下载 ZIP。** 在 <https://github.com/Aprivity/CryptoVideoResearch/tree/feat/v0.5-one-command-reports> 点击 Code → Download ZIP，解压后进入该目录，执行：

```bash
bash run.sh
```

首次运行会检查并安装缺失依赖，提示输入 DeepSeek API Key，然后搜索 YouTube 并默认生成最多两份单独的视频分析报告。后续仍执行 `bash run.sh` 即可。

**方法 2：从完全空白的 Ubuntu 终端安装并立即生成报告：**

```bash
sudo apt-get update && sudo apt-get install -y curl && curl -fL --retry 3 -o /tmp/cvr-install.sh https://raw.githubusercontent.com/Aprivity/CryptoVideoResearch/0554f7d98ba0a2a3688083b08d6f5869921bc907/scripts/bootstrap.sh && bash /tmp/cvr-install.sh
```

安装后，后续只需：

```bash
cryptovideo run
# 改成 3 份报告：cryptovideo run --count 3
# 若需要本机 Chrome 已登录的 Cookies：cryptovideo run --cookies chrome
```

报告索引：`outputs/youtube-news/latest.md`；视频独立报告：`outputs/youtube-news/videos/<视频ID>/analysis.md`。

首次部署需要 sudo 权限和网络连接。DeepSeek 分析会产生 API 费用，默认每次至多 2 次模型调用尝试；已成功分析的视频复用缓存。YouTube 搜索视频的发布时间可能未知，默认允许在标注未知日期的前提下分析；需要严格时间约束可使用 `--strict-dates`。

完整使用说明：[QUICKSTART.md](QUICKSTART.md)；视频研究模块：[YOUTUBE_NEWS.md](YOUTUBE_NEWS.md)；安装器源码：[scripts/bootstrap.sh](scripts/bootstrap.sh)。Windows `.exe` 尚未打包，本分支优先支持 Ubuntu。

---
YouTube 投资视频字幕提取与观点整理的开源工具。**研究资料收集，不提供投资建议、交易信号，也不执行交易。**

**V0.1 已实现的范围：** Ubuntu 下通过 yt-dlp 获取字幕，通过 [Summarize](https://github.com/steipete/summarize) 调用 DeepSeek 官方 OpenAI 兼容 API，生成带来源信息的 Markdown 分析报告和 JSON 任务记录。暂不支持批量发现、策略回测、外部事实核验或无人值守登录。

## 工作流程

```text
YouTube URL
   ↓ yt-dlp (Node/EJS + optional browser cookies)
带时间戳的 VTT 字幕
   ↓ 字幕格式与长度检查
Summarize CLI → DeepSeek API (deepseek-flash)
   ↓
outputs/<video-id>/analysis.md
outputs/<video-id>/report.json
```

刻意采用 **外部依赖**，不 Fork Summarize 或 yt-dlp；便于升级并减少维护。字幕不可用时直接失败，**不会把 YouTube 页面简介误判为完整字幕**。

## 旧版手动部署方式（开发者可选）

环境要求：Ubuntu、Python 3.10+、Node.js 24+、npm、支持本机浏览器 Cookie 的桌面环境（Cookie 可选）。首次安装需要联网，可能需要 sudo。

```bash
git clone https://github.com/Aprivity/CryptoVideoResearch.git
cd CryptoVideoResearch
bash scripts/install.sh
source .venv/bin/activate
cryptovideo setup
cryptovideo doctor
```

`install.sh` 检查 Node.js 版本，安装缺失的 Summarize、pipx yt-dlp（含 EJS）、secretstorage，并创建 Python 虚拟环境；**不会**自动安装或修改你的 Node.js / 代理 / 浏览器，也不会自动登录任何账户。若 npm 全局权限不足，请先使用 nvm 或配置 npm 用户级前缀。

`setup` 在终端交互式安全输入 DeepSeek API Key，保存在 `~/.config/cryptovideoresearch/deepseek.key`（权限 0600）。也可以仅通过进程环境变量 `DEEPSEEK_API_KEY` 提供。API 调用可能产生费用。

```bash
# 首次需要在浏览器里自行登录/完成人机验证时
cryptovideo login

# 默认匿名提取；需要使用已有 Chrome 会话时明确启用
cryptovideo analyze 'https://www.youtube.com/watch?v=ZWrgUWKOq_0' --cookies chrome

# 已有字幕，跳过 YouTube，直接分析
cryptovideo analyze-file ~/summarize-test/results/ZWrgUWKOq_0.zh-Hans.vtt --video-id ZWrgUWKOq_0

# 更换模型或输出路径
cryptovideo analyze 'https://youtu.be/ZWrgUWKOq_0' --cookies firefox --model deepseek-v4-pro --output-dir ./outputs
```

使用 `--cookies chrome` 会由 yt-dlp 直接读取本机浏览器 Cookie，**不在仓库或报告中保存 Cookie**。如出现验证失败，应自行在浏览器完成挑战或更换合法可用的来源，不保证能自动通过反爬措施。

### Ubuntu 代理

如果 Ubuntu 终端需要走本机 HTTP/Mixed 代理，先通过 **你实际使用的端口** 配置，例如：

```bash
export HTTPS_PROXY=http://127.0.0.1:7890
export HTTP_PROXY=http://127.0.0.1:7890
```

程序会向 Summarize 子进程设置 `NODE_USE_ENV_PROXY=1`，让 Node.js 24 使用环境代理。并不会改动系统代理。不要把账号凭据或私人代理 URL 提交到 Git。

### 可选：让 Claude Code 使用 DeepSeek（不影响常规 Claude 配置）

已安装 Claude Code 时，可以通过单独的启动器仅为该进程临时配置 DeepSeek Anthropic 兼容 API：

```bash
bash scripts/claude-deepseek.sh --print "仅回复：连接成功"
```

这并非 Summarize 必需步骤：本项目的摘要主链路直接调用 DeepSeek，不依赖 Claude Code。不要将 API Key 写入仓库，也不要假设任何账号都能免验证登录。

### 其他命令

```bash
cryptovideo --help
cryptovideo doctor
cryptovideo analyze --help
python -m unittest discover -s tests -v
```

分析 Markdown 是 AI 对字幕的整理，**不代表已核实的市场事实**。`report.json` 记录输入 URL、字幕类型、使用模型、文件路径及 `unverified` 状态，**尚非标准化策略数据库**。V0.2 计划加入策略 JSON Schema、批量去重和证据校验。

## 数据安全、费用与许可

- 不提交 API Key、浏览器 Cookie、完整视频字幕、用户报告；`.gitignore` 排除常见敏感文件与输出目录。
- CI 只执行本地单元测试，不调用 YouTube、DeepSeek，不使用私人 Cookie 或消耗 API 额度。
- YouTube 内容权利属于原作者；遵守平台条款，不要未经授权重新分发字幕和视频。
- 本仓库 MIT 授权，仅覆盖本仓库自有代码；第三方工具及其依赖遵循各自许可证。
- 本项目不提供投资建议、不下单、不含策略收益承诺。

上游资料：[Summarize 配置](https://github.com/steipete/summarize/blob/main/docs/config.md) · [yt-dlp EJS](https://github.com/yt-dlp/yt-dlp/wiki/EJS) · [DeepSeek API](https://api-docs.deepseek.com/quick_start/agent_integrations/)

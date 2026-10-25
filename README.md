# CryptoVideoResearch

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

## Ubuntu 快速部署

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

# V0.6 B 工作流：交互式 CLI

## 1. 从已有 V0.5 切换到 V0.6

Ubuntu 项目目录下：

```bash
cd ~/CryptoVideoResearch
git remote set-branches --add origin feat/v0.6-interactive-cli
git fetch origin
git switch --track origin/feat/v0.6-interactive-cli
bash run.sh
```

如本地已有该分支，可使用 `git switch feat/v0.6-interactive-cli && git pull --ff-only`。

重新运行安装器、重新输入 API Key、重建 venv **通常都不需要**（源码为可编辑安装）。切换分支不会删除已存在的报告和 DeepSeek Key。

## 2. 一条命令进入 B 菜单

```bash
cryptovideo
# 与上面等价：
cryptovideo menu
# 从 ZIP 下载解压目录运行：
bash run.sh
```

启动画面：

```text
CryptoVideoResearch · B 市场新闻与 YouTuber 研究
无输入直接回车 = 搜索市场新闻；按数字或 ↑/↓ 选择

❯ [1] 搜索市场新闻（默认；允许重复检索并复用报告）
  [2] 输入 YouTuber 名称 / @handle / 频道链接
  [3] 选择已保存 YouTuber（N）
  [4] 运行设置（报告数量、时间窗口、Cookies）
  [5] 查看报告位置
  [6] 退出

↑/↓ 移动 · 数字直接选择 · 回车确认 · 0 返回/退出
```

**完全不输入直接按回车**：执行 B 的默认市场新闻搜索。每次可以重新搜索，即使已发现过同一个视频也不会强制过滤结果；成功生成的同一份视频报告默认复用缓存，避免重复调用付费 API。市场新闻排序依然无法保证是真实或最近发生的新闻。

**指定 YouTuber**：选择 `2`，输入其 `@handle`、YouTube 频道首页链接（包括 `/videos`），或直接输入频道名称。若输入普通名称，程序先在 YouTube 搜索视频并列出能取得官方频道 ID 的可能频道，你需要明确确认，**不会将相似名字的多个频道混到一起**。YouTube 不返回频道 ID 时，可改用准确 `@handle` 或频道链接。

**已保存**：添加频道后会保存在本机。下一次打开直接选择 `3`，按数字或方向键从列表选择；支持翻页及删除。选择 YouTuber 后程序按该**唯一频道**的 `/videos` 上传列表读取候选。它保留技术分析和博主观点，不强制要求每条视频都包含新闻。

**运行设置**：报告数量 1–5（也是每轮 DeepSeek 模型调用尝试次数上限）、24/72/168/336 小时时间范围、Cookies 来源、是否只允许日期已确认的近期视频。设置会自动保留，每次不必重新输入。

## 3. 输出与隐私

- 默认市场新闻：`outputs/youtube-news/latest.md`，单视频报告 `outputs/youtube-news/videos/<视频ID>/analysis.md`。
- 指定 YouTuber：`outputs/youtubers/<频道标识>/latest.md`，单视频报告在其 `videos/<视频ID>/analysis.md`。
- 菜单配置：`~/.config/cryptovideoresearch/b_menu.json`。只保存频道链接/名称和运行选项，不保存浏览器 Cookies；DeepSeek Key 按原有机制另行保存。
- 缓存跨多次运行有效；`seen.db` 记录本地发现的视频，不代表视频最近刚上传。

视频元数据和标题并不能完全保证新闻时效。严格日期模式在缺少发布时间时可能无法生成报告；不过默认模式会明确标注未知日期。视频没有字幕时也可能无法完成分析。没有股票/币圈交易、回测或投资建议动作。

## 4. 保留命令行自动化入口

除了交互菜单，原有参数继续支持：

```bash
# 默认新闻，至多一次付费模型调用尝试
cryptovideo run --count 1 --cookies chrome

# 只从指定频道寻找视频，不混入全站搜索结果
cryptovideo run --channel @YourHandle --count 1 --cookies chrome

# 仅免费搜索新闻候选
cryptovideo youtube-news --analyze-top 0

# 只免费读取某个官方频道的上传列表
cryptovideo youtube-news --channel @YourHandle --analyze-top 0

# 旧的 flag-only 启动仍可用
bash run.sh --count 1 --cookies chrome
```

定时脚本和其他没有 TTY 的环境请使用 `cryptovideo run`（带明确参数），不要依赖交互菜单。Windows 原生 EXE 尚未打包。

## 5. 本地离线功能测试

```bash
cd ~/CryptoVideoResearch
./.venv/bin/python -m unittest discover -s tests -v
```

CI 覆盖了默认回车、数字菜单选项、设置持久化、频道链接安全校验、按频道提取上传视频以及旧命令兼容。方向键需要在真实 Ubuntu 终端中做交互验收，CI 无法模拟所有终端环境。

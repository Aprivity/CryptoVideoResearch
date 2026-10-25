# B 工作流 V0.4 — YouTube 市场新闻研究

**架构：** YouTube 搜索市场新闻解读视频 → 初筛、去重与来源登记 → 可选提取前 N 条字幕 → Summarize + DeepSeek 整理视频内容。**默认不再执行 RSS 新闻采集**。A 工作流（指定博主持续监控）与 C 工作流（策略循环搜索）仍保持独立。

## 核心命令

```bash
# 搜索结果筛选、标题/频道/链接记录，无 DeepSeek 调用
cryptovideo youtube-news --hours 168

# 对排名前 2 的视频提取字幕并整理（有 DeepSeek API 费用）
cryptovideo youtube-news --hours 168 --analyze-top 2 --cookies chrome

# 预先检查 CLI 和环境
cryptovideo doctor

# 离线测试（不访问 YouTube、不调用 DeepSeek）
cryptovideo youtube-news --fixture tests/fixtures/youtube_search.json --hours 720
python -m unittest discover -s tests -v
```

输出默认位于 `outputs/youtube-news/`：`latest.md`、`latest.json`、`seen.db`。如果启用视频分析，单视频报告写入 `videos/<video_id>/analysis.md`。已成功分析的视频再次运行默认复用缓存，`--refresh` 才会重新提取。

## 默认搜索范围

`youtube_news_queries.json` 目前包含四条关键词组合：BTC/比特币（中英文）、美联储/CPI/宏观、英伟达/美光/半导体。可添加或删除关键词组合。它们是搜索主题，不是推荐频道白名单。

视频初筛依据关键词相关性、标题夸张性、已知发布时间和时长。YouTube 搜索排序本身不保证最新；搜索页经常**不提供精确发布时间或观看数据**，缺失时标注“未知”，不根据检索排名杜撰发布日期。已知旧视频会被过滤；日期仅精确到天时明确标注。这个排名分数衡量**检索相关性**，不是新闻真实性、博主可信度或投资价值。

本模块只检索 **YouTube**，不请求 Google News、CoinDesk 或美联储 RSS。之前的 `cryptovideo news` 命令保留为可选遗留入口，但不是 B 的默认管线。

## V0.4.1：发布日期二次核查与筛选

真实 YouTube 检索显示，yt-dlp 的 flat 搜索结果通常没有发布日期。因此 `--hours 168` **无法单凭搜索页面保证最近七天**。现对排名前五的视频自动执行完整元数据核查：

```bash
# 搜索后对前 5 个候选读取元数据，剔除确认过期的结果，不调用 DeepSeek
cryptovideo youtube-news --hours 168 --verify-top 5

# 对更多候选核查日期，可能需要更久，但不会触发模型费用
cryptovideo youtube-news --hours 168 --verify-top 10

# 若只想快速搜索、暂时不查日期，可禁用二次核查
cryptovideo youtube-news --verify-top 0
```

**默认安全限制：** `--analyze-top N` 只分析已确认处于窗口内且拥有日期的候选；日期缺失时会跳过付费分析并报告原因。只有用户明确使用 `--allow-unknown-age` 才允许分析日期未知的视频。日期核查不代表事实核验：它只确认该视频报告的发布信息，不会验证视频声称的经济数据。

重复视频 ID 和基本相同的标题会去重，明显夸张的标题会降权。检索相关度不等同于权威性或真实性。二次核查请求仍依赖 YouTube 可用性和 Cookies、网络环境；失败时保留“未知”标记。

## 新闻内容提取

`--analyze-top 2` 是显式付费步骤：调用现有 `yt-dlp` 获取字幕，继而执行 `Summarize + DeepSeek`，使用 `prompts/youtube_news_zh.md` 专用提取规则区分：

- 视频中的新闻事件与数据（视频转述，尚未独立核验）
- 博主自己的解释与价格预测（观点，而非客观事实）
- 无从通过字幕确认的日期、数字和因果关系
- 后续可验证的证据线索

**不会**产生买卖信号、交易建议、自动下单或自动回测。YouTube 搜索可能受地区、网络代理、验证码、平台变化影响；必要时可手动在浏览器登录，使用 `--cookies chrome`，但不自动突破验证或保证每个视频都有字幕。

## 常见场景

```bash
# 只检索 BTC，修改查询配置即可；不必改代码
nano youtube_news_queries.json

# 搜索更多候选后再选取少量分析
cryptovideo youtube-news --per-query 12 --max-results 20 --analyze-top 1 --cookies chrome
```

首次调试建议只用默认搜索（不加 `--analyze-top`），确认 YouTube 在本机能访问且筛选结果有价值，再启用 1 条视频的 AI 提取。

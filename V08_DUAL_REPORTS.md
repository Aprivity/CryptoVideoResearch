# V0.8 双层报告与金融实体识别

本版本沿用 V0.7 已跑通的字幕/本地 ASR/DeepSeek 链路，**不接入新的付费服务或额外的模型调用**。

## 1. 双层输出

单视频或批量 B 工作流经过一次 DeepSeek 分析，输出：

```text
<输出目录>/videos/<video-id>/
├── analysis.md             # 完整研究报告（事件、作者观点、数字、时间戳、风险、核验线索）
├── quick.md                # 1 分钟快速摘要（模型挑选 3–5 条重点）
├── finance_quality.json    # 英文公司名候选、字幕可疑术语、待核对数字
└── report.json             # 路径、模式与核验状态
```

手动单视频 `analyze` 的目录为 `<output-dir>/<video-id>/`，没有 `videos/` 中间层。`quick.md` 在完整报告中查找 `## 一分钟速览` 小节；`analysis.md` 保留原有五节内容，并附加金融识别质量提示。摘要里的“可信度”**仅指视频陈述/字幕清晰程度；不代表事件已经外部核实，也不代表 Whisper 的真实声学置信度**。

如果用户自定义旧 prompt 导致没有 `## 一分钟速览`，会从已有报告的事件/观点条目生成**明确标为机械摘录且不声称按重要性排序**的简版摘要；不会为了凑满 3–5 条编造内容。

## 2. 金融实体词表与低置信度提示

词表位于 [src/cryptovideoresearch/data/finance_entities.json](src/cryptovideoresearch/data/finance_entities.json)，包含英文公司名称、中文名、股票 ticker、经济数据和机构术语，例如 CoreWeave、Goldman Sachs、Bernstein、American Express、Moderna、Merck、NVIDIA、Micron、SK hynix、OpenAI、VIX、FOMC、CPI 等。

- **明确别名匹配：** 给 DeepSeek 提供英文拼写候选；不证明视频新闻为真
- **疑似错误：** 如 `康衛覆`→“疑似 CoreWeave”，`Wigs`→“疑似 VIX”，仅提示并列出时间戳，**不修改 VTT**、不擅自自动更正
- **无法确定：** 如 `美趙瓦`、`iPhone 2`，只标注“实体不明确”
- **财经数字：** 自动摘取带百分比、金额或单位的片段，用于回听和后续核验，绝不宣称已验证

`finance_quality.json` 包含原始识别文本、候选实体、时间戳、识别类型与 `verification_status: unverified`。所谓“低置信度”仅是**词典疑似别名/文本启发式警报**，并非 faster-whisper 给出的音频置信分数。

如要自行扩充金融公司词表，在开发分支编辑 JSON，按现有 `aliases` / `suspect_aliases` 的字段添加词条。英语单词采用边界匹配，避免 `Meta` 被误识别成 `supermeta`。

## 3. 更新 Ubuntu

```bash
cd ~/CryptoVideoResearch
git fetch origin
git switch --track origin/feat/v0.8-dual-reports-finance-terms
# 如果之前已创建该本地分支：git switch feat/v0.8-dual-reports-finance-terms && git pull --ff-only
bash run.sh
```

无需重新安装 Whisper 模型、PyAV、yt-dlp，V0.7 的 VTT 与 ASR 缓存仍可使用。

### 立即为之前成功的报告补全快速摘要

不消耗 DeepSeek API，不修改旧 `analysis.md`：

```bash
./.venv/bin/cryptovideo upgrade-report \
  outputs/asr-validation/DiDuGTf_-0g/analysis.md

cat outputs/asr-validation/DiDuGTf_-0g/quick.md
cat outputs/asr-validation/DiDuGTf_-0g/finance_quality.json
```

**注意：**这个旧报告没有新模型输出的“一分钟速览”小节，首次转换的 `quick.md` 会标记为“机械摘录”。想让 DeepSeek 按重要程度重新选出 3–5 条，需重新运行 `analyze`（会产生一次 API 调用）。

### 使用新提示词生成模型精选的双层报告

```bash
./.venv/bin/cryptovideo analyze \
 'https://www.youtube.com/watch?v=DiDuGTf_-0g' \
 --cookies chrome --asr-fallback --asr-model base \
 --prompt prompts/youtube_news_zh.md \
 --output-dir ./outputs/asr-validation
```

上述命令可复用已存储的 `local-asr-base.vtt`，只需调用一次 DeepSeek。生成的 `quick.md` 将是模型选择的 3–5 条重点，`analysis.md` 为完整报告。B 频道批量分析及之前已有的完整分析缓存也支持此格式；旧缓存若缺配套文件会自动离线补生成。

## 4. 验收和边界

```bash
./.venv/bin/python -m unittest discover -s tests -v
```

自动测试不调用 YouTube、Hugging Face 或 DeepSeek，仅核对提取及报告结构、词表匹配、疑似术语、字幕时间戳与旧缓存升级。外部事实核查不在 V0.8 的两项功能范围之内；本项目仍是研究整理工具，不提供投资建议或交易执行。

# B 模块：市场新闻信息发现（轻量 MVP）

这是 CryptoVideoResearch 的 B 工作流第一阶段，**独立于** yt-strategy-agent 的博主持续监控，也不修改现有 V0.1 的 Summarize/视频分析功能。

## 范围与限制

- ✅ 定义 BTC/加密市场、美联储与宏观、AI 与半导体的 RSS 搜索源，支持 Google News RSS、央行官方 RSS 与新闻媒体 RSS。
- ✅ 单次运行采集标题、发布时间、来源、RSS 摘要和链接；SQLite 去重；生成 Markdown + JSON；离线 Fixture 验证。
- ✅ 对无时区/缺失发布时间的记录宁可跳过，不谎报为最新消息；RSS 源失败会提示；全部失败不会覆盖上一次报告。
- ❌ 尚**不**抓取文章全文或独立核查市场新闻，**不**调用 DeepSeek 自动解释原因，**不**进行 YouTube 相关视频发现或 summarize 分析。这些属于后续 B2。
- ❌ 不启用定时任务、邮件或 VPS，不生成买卖建议、信号、收益预测，不做回测。
- ⚠️ Google News RSS 是非官方稳定承诺的搜索接口，可能改变；Google News 链接也可能是中转链接。

## Ubuntu 使用（基于本仓库现有 V0.1 安装）

~~~bash
python -m pip install -e .
python -m unittest discover -s tests -v

# 无网络、无 API Key、无代理要求的演示；重复运行应显示 added=0
python -m cryptovideoresearch.news_monitor --fixture tests/fixtures/news_sample.xml --hours 100000
python -m cryptovideoresearch.news_monitor --fixture tests/fixtures/news_sample.xml --hours 100000

# 真实新闻源一次性抓取（需要网络，不收费、不调用 DeepSeek）
python -m cryptovideoresearch.news_monitor --config news_sources.json --hours 72
~~~

输出：outputs/news/latest.md、latest.json、news.db；news_sources.json 可以手工编辑检索主题和 RSS 地址。报告的 verification_status 永远标记为 headline-only-unverified。

## 后续 B2：复用已测试的视频分析能力

1. 对关键词关联的视频进行独立的 YouTube 发现与筛选。
2. 按需调用现有 cryptovideo analyze 视频链接 --cookies chrome，由 summarize + DeepSeek 处理字幕。
3. 将视频观点与新闻链接关联，明确区分**报道的事实、博主观点、模型推断与未核实信息**；保留可追溯来源。
4. 在单次查询链路稳定后再考虑调度，不抢先引入无人值守浏览器、Apify 或大体积机器学习依赖。

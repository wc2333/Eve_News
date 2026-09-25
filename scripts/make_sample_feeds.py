"""Regenerate src/evenews/sample/feeds/*.xml - the offline demo and test fixtures.

Run this after adding or renaming a source in src/evenews/data/config.example.yaml
(the feed slug is the source name), then commit the regenerated XML together with
the config change:

    python scripts/make_sample_feeds.py
"""

from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "src" / "evenews" / "sample" / "feeds"
OUT.mkdir(parents=True, exist_ok=True)

FEEDS = {
    "jiqizhixin": ("机器之心", "https://www.jiqizhixin.com/", [
        ("阿里开源 Qwen3.6-32B：单卡可跑，MMLU 83.4 分", "https://www.jiqizhixin.com/articles/2026-09-25-1",
         "9 月 25 日，阿里开源 Qwen3.6-32B 稠密模型，32B 参数在单张 48GB 显卡即可 4bit 推理。MMLU 得分 83.4，HumanEval 87.1，权重与推理代码同步上线。", "Fri, 25 Sep 2026 08:10:00 +0800"),
        ("DeepSeek 公布 V3.5 技术报告：训练成本再降 41%", "https://www.jiqizhixin.com/articles/2026-09-25-2",
         "DeepSeek 发布 V3.5 技术报告，采用稀疏专家与混合精度训练，同等能力下训练成本下降 41%，长上下文 128K 的推理延迟降低 27%。", "Fri, 25 Sep 2026 07:20:00 +0800"),
        ("GLM-4.6 上线：Agent 工具调用准确率提到 91%", "https://www.jiqizhixin.com/articles/2026-09-24-9",
         "智谱发布 GLM-4.6，重点强化智能体与代码能力，ToolBench 工具调用准确率从 84% 提升到 91%，并开放 128K 上下文定价。", "Thu, 24 Sep 2026 18:05:00 +0800"),
    ]),
    "qbitai": ("量子位", "https://www.qbitai.com/", [
        ("Kimi 发布 K2.5：Agent 跑完 120 步长任务不掉链子", "https://www.qbitai.com/2026/09/100201.html",
         "月之暗面开源 Kimi K2.5，官方称在 120 步以上的长链路智能体任务成功率 78%，比上一代高 19 个百分点，支持 256K 上下文。", "Fri, 25 Sep 2026 09:00:00 +0800"),
        ("国产多模态模型集体刷榜：OCR 与图表理解进入 95 分区间", "https://www.qbitai.com/2026/09/100188.html",
         "最新 OpenCompass 榜单显示，Qwen、GLM、DeepSeek 三家多模态模型在 OCR 与图表理解上均超过 95 分，与闭源旗舰差距缩小到 2 分以内。", "Fri, 25 Sep 2026 07:40:00 +0800"),
    ]),
    "huggingface": ("Hugging Face Blog", "https://huggingface.co/blog/", [
        ("Open weights week: 12 new models released under Apache 2.0", "https://huggingface.co/blog/open-weights-week",
         "This week the hub added 12 new open-weight models, most under Apache 2.0, including a 7B multimodal model and three distilled speech models with sub-200ms latency.", "Fri, 25 Sep 2026 02:00:00 +0000"),
        ("Leaderboard update: agentic tool-use splits from chat quality", "https://huggingface.co/blog/leaderboard-tool-use",
         "The tool-use leaderboard now reports multi-step reliability separately: only 4 of 38 models finish a 50-step task with more than 70% success.", "Thu, 24 Sep 2026 21:15:00 +0000"),
    ]),
    "openai": ("OpenAI News", "https://openai.com/news/", [
        ("Batch API price cut and 12-hour SLA for enterprise", "https://openai.com/news/batch-api-price-cut",
         "OpenAI cut Batch API pricing by 30% and added a 12-hour service level for enterprise customers, aiming at large offline evaluation and distillation jobs.", "Fri, 25 Sep 2026 01:30:00 +0000"),
    ]),
    "arxiv_cl": ("arXiv cs.CL", "https://arxiv.org/list/cs.CL/recent", [
        ("Sparse routing keeps accuracy at 40% of the compute", "https://arxiv.org/abs/2609.11201",
         "The paper reports a router that activates 40% of expert capacity during decoding while retaining 98.6% of dense-model accuracy on six reasoning benchmarks.", "Fri, 25 Sep 2026 00:05:00 +0000"),
        ("Long-context retrieval still fails at 200K on real documents", "https://arxiv.org/abs/2609.11244",
         "Evaluations on real 200K-token documents show retrieval-augmented pipelines losing 22 points versus synthetic needles, with mid-context positions the weakest.", "Thu, 24 Sep 2026 23:50:00 +0000"),
    ]),
    "infoq": ("InfoQ 中文", "https://www.infoq.cn/", [
        ("企业级 RAG 平台集中上新：向量库与知识图谱开始合体", "https://www.infoq.cn/article/AMPLE001",
         "近两周内 5 家厂商发布企业 RAG 新品，共同点是把向量检索与知识图谱融合，官方宣称问答准确率提升 15%-25%，落地成本增加约 10%。", "Fri, 25 Sep 2026 06:30:00 +0800"),
    ]),
    "ithome": ("IT之家", "https://www.ithome.com/", [
        ("高通峰会：骁龙 8 Gen 6 端侧跑 7B 模型，每秒 32 token", "https://www.ithome.com/0/889001.htm",
         "9 月 24 日高通骁龙峰会公布 8 Gen 6，NPU 算力 78 TOPS，端侧运行 7B 模型可达 32 token/秒，整机功耗增加不足 1.2W。", "Thu, 24 Sep 2026 20:15:00 +0800"),
        ("第二批手机端侧生成式 AI 备案公布，共 11 款产品过审", "https://www.ithome.com/0/889014.htm",
         "网信部门公布第二批手机端侧生成式 AI 服务备案，共 11 款产品通过，覆盖 6 家手机厂商，备案机型自 10 月起陆续推送端侧模型。", "Fri, 25 Sep 2026 09:15:00 +0800"),
        ("小米公布 AI PC 计划：本地 13B 模型 + 32GB 起步", "https://www.ithome.com/0/889022.htm",
         "小米公布 AI PC 路线，首批机型标配 32GB 内存，本地部署 13B 量化模型，官方称离线文档总结响应时间低于 2 秒。", "Fri, 25 Sep 2026 08:45:00 +0800"),
    ]),
    "ifanr": ("爱范儿", "https://www.ifanr.com/", [
        ("AI 眼镜开始拼重量：新品做到 38g，续航 6 小时", "https://www.ifanr.com/1680001",
         "新款 AI 眼镜整机 38g，双摄加麦克风阵列，连续语音对话续航 6 小时，售价 1899 元，首发 3 周出货约 5 万台。", "Fri, 25 Sep 2026 10:05:00 +0800"),
        ("具身智能数据公司融资 12 亿：一年卖出 40 万条操作轨迹", "https://www.ifanr.com/1680010",
         "一家具身智能数据公司完成 12 亿元 B 轮融资，累计交付 40 万条真机操作轨迹，客户覆盖 14 家机器人本体与 3 家车企。", "Fri, 25 Sep 2026 09:35:00 +0800"),
    ]),
    "leiphone": ("雷峰网", "https://www.leiphone.com/", [
        ("人形机器人量产提速：单厂月产 1200 台，成本降 26%", "https://www.leiphone.com/category/robot/9f2a.html",
         "头部人形机器人厂商透露月产能已达 1200 台，单机成本较年初下降 26%，主要来自行星滚珠丝杠与灵巧手国产化。", "Fri, 25 Sep 2026 08:55:00 +0800"),
        ("智驾芯片进入 5nm 竞争：单颗 2000 TOPS 算力报价下探", "https://www.leiphone.com/category/ai/7c11.html",
         "两家智驾芯片厂商同步发布 5nm 新品，单颗算力 2000 TOPS，报价同比下探约 18%，2027 年上半年量产上车。", "Thu, 24 Sep 2026 17:25:00 +0800"),
    ]),
    "semi": ("半导体行业观察", "http://www.semi.org.cn/", [
        ("昇腾 910C 超节点实测：7 万亿参数模型可单机训练", "http://www.semi.org.cn/a/770001.html",
         "第三方实测报告显示昇腾 910C 超节点在 7 万亿参数 MoE 模型上可单机完成预训练，等效算力利用率 58%，功耗较上一代降 12%。", "Fri, 25 Sep 2026 08:20:00 +0800"),
        ("HBM 扩产竞赛：三家存储厂明年产能翻倍", "http://www.semi.org.cn/a/770009.html",
         "存储大厂把 HBM3E 产能目标提高一倍，国内两家封测厂同步扩 CoWoS 类产线，预计 2027 年供给缺口收窄到 8% 以内。", "Fri, 25 Sep 2026 07:50:00 +0800"),
        ("国产 GPU 集群调度平台上线：万卡集群利用率提到 72%", "http://www.semi.org.cn/a/770015.html",
         "某智算中心发布自研调度平台，万卡异构集群平均利用率从 54% 提升到 72%，故障卡自动隔离时间缩短到 90 秒。", "Thu, 24 Sep 2026 19:10:00 +0800"),
    ]),
    "36kr": ("36氪", "https://36kr.com/", [
        ("AI 算力租赁价格三个月跌 18%：中小客户开始转按量计费", "https://36kr.com/p/3450001",
         "多地智算中心报价下滑，8 卡 A 级机型月租三个月内下降 18%，头部厂商把 60% 的算力改为按量计费以拉高上架率。", "Fri, 25 Sep 2026 09:25:00 +0800"),
        ("大模型应用公司通过港股上市聆讯：年营收 9.7 亿", "https://36kr.com/p/3450018",
         "一家大模型应用公司通过港交所上市聆讯，2025 年营收 9.7 亿元、毛利率 54%，其中 71% 来自企业订阅与私有化部署。", "Fri, 25 Sep 2026 08:05:00 +0800"),
    ]),
    "sspai": ("少数派", "https://sspai.com/", [
        ("智能手表的本地模型试验：离线语音转写准确率 96%", "https://sspai.com/post/101001",
         "有开发者在旗舰智能手表上部署 1.2B 语音模型，离线转写中文准确率 96%，续航影响约 8%，代码已开源。", "Fri, 25 Sep 2026 10:20:00 +0800"),
    ]),
    "huxiu": ("虎嗅", "https://www.huxiu.com/", [
        ("Token 工厂经济学：单卡日均产值首次跌破 40 元", "https://www.huxiu.com/article/880001.html",
         "多家推理服务商披露运营数据，单张推理卡日均 Token 产值跌破 40 元，同比降 34%，厂商开始用错峰与批处理拉平成本。", "Fri, 25 Sep 2026 09:50:00 +0800"),
        ("AI 制药进入闭环竞争：数据-模型-实验-再数据", "https://www.huxiu.com/article/880012.html",
         "多家科技巨头加码 AI 制药，竞争焦点从模型转向行业基础设施，能跑通数据到实验闭环的公司把研发周期压缩到 14 个月。", "Thu, 24 Sep 2026 21:40:00 +0800"),
    ]),
}

TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>{title}</title>
    <link>{link}</link>
    <description>{title} 样例订阅源（离线演示用）</description>
{items}
  </channel>
</rss>
"""


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


for slug, (name, site, entries) in FEEDS.items():
    rows = []
    for title, url, desc, published in entries:
        rows.append(
            "    <item>\n"
            f"      <title>{esc(title)}</title>\n"
            f"      <link>{url}</link>\n"
            f"      <guid isPermaLink=\"true\">{url}</guid>\n"
            f"      <pubDate>{published}</pubDate>\n"
            f"      <description>{esc(desc)}</description>\n"
            "    </item>"
        )
    (OUT / f"{slug}.xml").write_text(
        TEMPLATE.format(title=esc(name), link=site, items="\n".join(rows)), encoding="utf-8"
    )

print(f"wrote {len(FEEDS)} sample feeds -> {OUT}")

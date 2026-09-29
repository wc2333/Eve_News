from __future__ import annotations

from evenews.article import enrich_articles, html_to_text, material
from evenews.curator import _ask_model
from evenews.llm import MockLLM
from evenews.models import Article

PAGE = """
<html><head><style>p { color: red }</style><script>var tracking = 1;</script></head>
<body><nav>首页 频道 登录 注册</nav>
<p>这家公司在今天的发布会上正式公布了新一代模型的完整技术细节，包括训练数据规模、上下文长度以及三档推理配置的实测延迟与单价。</p>
<p>评测部分同时给出了数学、代码与多语言三类共四十个子任务的成绩，并与上一代以及三家同类开源模型逐项做了对比，最大差距出现在长文档检索上。</p>
<p>负责人在问答环节回应了社区关心的许可与安全评审问题，确认权重与评测代码会在本周内一并放出，企业用户可以直接接入自有推理集群。</p>
</body></html>
"""


def test_html_to_text_keeps_the_prose_and_drops_the_chrome():
    text = html_to_text(PAGE)
    assert "这家公司在今天的发布会上" in text
    assert "负责人在问答环节" in text
    assert "登录" not in text, "navigation must not count as article text"
    assert "color: red" not in text and "tracking" not in text


def test_only_thin_items_pay_for_a_page_fetch(tmp_path):
    page = tmp_path / "post.html"
    page.write_text(PAGE, encoding="utf-8")
    thin = Article(title="某模型发布", url=str(page), source="qbitai", raw_summary="只给了一句导语。")
    thick = Article(title="另一篇", url="https://never.fetched/x", source="qbitai", raw_summary="长" * 400)
    assert enrich_articles([thin, thick], timeout=5) == 1
    assert "评测部分" in thin.body
    assert thick.body == "", "a feed that already handed over the article is left alone"
    assert material(thin).startswith("这家公司")
    assert material(thick) == "长" * 400


def test_the_model_reads_the_fetched_body(config):
    captured: dict = {}

    class Spy(MockLLM):
        def json_task(self, task, payload):
            captured.update(payload)
            return super().json_task(task, payload)

    article = Article(title="某模型发布", url="https://a/1", source="qbitai", raw_summary="一句导语")
    article.body = "正文里的关键数字与时间点都在这里，模型应当读到这一段材料。"
    _ask_model(Spy(config.llm), config.sections[0], [(0, article)])
    assert "正文里的关键数字" in captured["candidates"][0]["summary"]


def test_parallel_enrich_dedupes_by_url_and_tolerates_dead_pages(monkeypatch):
    from evenews import article as article_module
    from evenews.article import enrich_articles
    from evenews.models import Article

    calls = []

    def fake_fetch(url, **kwargs):
        calls.append(url)
        if "dead.example" in url:
            raise OSError("dead page")
        return "并发抓回来的正文。"

    monkeypatch.setattr(article_module, "fetch_body", fake_fetch)
    arts = [
        Article(title="同页两转载", url="http://dup.example/x", source="s", raw_summary="短导语一"),
        Article(title="同页第二篇", url="http://dup.example/x", source="s", raw_summary="短导语二"),
        Article(title="死页面", url="http://dead.example/y", source="s", raw_summary="短导语三"),
    ]
    assert enrich_articles(arts) == 2
    assert calls.count("http://dup.example/x") == 1, "同一 URL 只抓一次"
    assert arts[2].body == "", "抓不到就沿用订阅摘要，不许炸整期"

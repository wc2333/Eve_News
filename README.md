# Eve_News · AI 每日资讯

每天早上把 AI 行业要点整理成一封报纸味道的邮件发到公司邮箱：**Windows 和 Ubuntu 都能跑**，板块可以勾选，采集与写作环节都走可替换的大模型配置。

版式对齐内部《AI 每日资讯》：报头 + 今日摘要 + 板块页 + 引用来源页脚。

## 默认板块（7 个，可勾选）

| id | 板块 | 关注点 |
| --- | --- | --- |
| `llm_oss` | 大模型与开源生态 | 模型发布、评测榜单、开源权重、API 价格 |
| `model_releases` | 新模型与开源权重速览 | 近期上榜的新模型：谁发的、多大、什么许可、能不能本地跑 |
| `edge_ai` | 端侧 AI 与芯片峰会 | 手机/PC 端侧模型、峰会发布、算法备案 |
| `domestic_compute` | 国产算力与集群 | 国产 GPU/NPU、智算中心、超节点、供应链 |
| `devices_robotics` | 端侧设备与具身智能 | 机器人、自动驾驶、AI 硬件 |
| `wearables` | 智能眼镜与可穿戴 | AI 眼镜、头显、手表耳机 |
| `industry_capital` | 行业商业 · 资本与算力 | 融资并购、财报产能、政策监管 |

```powershell
evenews sections            # 查看板块与开关
evenews disable wearables   # 不感兴趣就关掉（多个 id 用逗号分隔）
evenews enable wearables
```

板块本身也是普通 YAML：改标题、改关键词、调 `max_items`、加自定义板块都可以。

`model_releases` 是多出来的一块：新模型上榜一般比新闻慢几天，混在 `llm_oss` 里会被当天新闻挤掉，所以单开一页保证每天看得见；不需要就 `evenews disable model_releases`，或在设置页勾掉。

## 快速开始

```bash
git clone <你的仓库地址> Eve_News && cd Eve_News

# Ubuntu
python3 -m venv .venv && source .venv/bin/activate && pip install -e .
# Windows PowerShell
python -m venv .venv && .\.venv\Scripts\Activate.ps1 && pip install -e .

evenews init                     # 生成 config.yaml + .env.example
cp .env.example .env             # 填 SMTP 授权码与模型 API Key
evenews run --offline            # 不联网、不用密钥，先用内置样例看版式
evenews preview                  # 真实采集，只生成不发信
evenews test-email               # 单独验证邮件通道
evenews doctor --sources --model # 配置体检：来源连通、模型连通
evenews run                      # 正式生成并发送
```

每次运行在 `out/<日期>/` 得到 `digest.html` / `digest.md` / `digest.txt` / `digest.json`。

## 网页设置（推荐）

不想手改 YAML 就开本地设置页：板块勾选、模型、SMTP、发送时间、密钥都在网页里填，写完直接点「立即生成并发送」验证。

```bash
evenews web                            # 自动开浏览器，默认 http://127.0.0.1:8765
evenews web --port 9000 --no-browser   # 换端口 / 服务器上不自动开浏览器
```

| 页签 | 能改什么 |
| --- | --- |
| 板块勾选 | 7 个板块的开关、条数上限、关键词；板块和来源池的增删去「高级 YAML」 |
| 采集与模型 | `provider` / `base_url` / `model` / 各环节开关、过滤关键词、联网检索；带「测试模型连通」「测试所有来源」 |
| 邮件 | SMTP 主机端口与 security、收发件人、报头署名；一键「发测试邮件」 |
| 计划与密钥 | 每天几点发、时区、仅工作日；密钥写在这里，只落 `.env` |
| 运行与预览 | 离线试跑、生成预览、立即发送，页面内直接看最新一期 |
| 高级 YAML | 整份 `config.yaml` 直接编辑，保存前走一遍真实校验，不通过不落盘 |

- 默认只监听 `127.0.0.1`，别在生产机上 `--host 0.0.0.0` 开放到局域网。
- 密钥只写进 `.env`，接口只回「是否已设置 + 长度」，绝不回传明文；`config.yaml` 里只存变量名。
- 图形界面保存会重写 `config.yaml`（丢注释，注释版模板看 `config.example.yaml`），同时留一份 `config.yaml.bak` 兜底。

## 公司品牌

`brand` 段已经按 **凯铮寰宇 CTONE**（官网 www.kzhytech.com）配好，全部可在设置页「报头与署名」里改：

| 字段 | 作用 |
| --- | --- |
| `company` | 报头与页脚署名：凯铮寰宇 |
| `logo_file` | 报头图标。内置两枚取自官网：`brand-logo-kzhy.jpg`（公司标，/icon.jpg）、`brand-logo-ctone.png`（CTONE 字标，/images/logo.png）；也可以填本机绝对路径 |
| `logo_text` | 图标读不到、或邮件客户端不显示图片时的文字报头：CTONE |
| `site` | 页脚官网链接：https://www.kzhytech.com |
| `kicker` | 报头副标题：凯铮寰宇 CTONE · 算力驱动未来 |
| `theme` | 默认 `light`（纸白底 + 官网蓝）；想要官网那种近黑蓝底改成 `dark` 即可。设置页下拉切换时会把该主题的全套色值回填进下面的颜色框 |
| `background` / `card` / `text` / `body` / `muted` / `accent` / `label` | 逐个覆盖主题色，**留空即跟随 `theme` 的色板**。色板只在后端一处：`evenews.render.PALETTES`，邮件模板和设置页共用 |

- 图标以 `data:` URI 内嵌进落盘的 `digest.html`，本地直接双击打开也不掉图；超过 180 KB 自动不放图，报头退回文字，不会把邮件撑爆。
- 发信时 `email.attach_logo`（默认 `true`）改为把 logo 作为**内联附件**（`Content-ID: <evenews-logo>`）随邮件发出，正文里引用 `cid:evenews-logo`。桌面 Outlook / 企业邮客户端不用下载附件就能看到报头，也不会因为图片代理而掉图。
- 深色版式做了文字层级：正文用 `body`（深色下 `#dce6f3`）而不是纯白，标题 / 正文 / 元信息三级分明，条目之间 1px 分隔线、编辑点评带左边线。邮件外层 `<table>` 带 `bgcolor`，并声明 `color-scheme`，Outlook 与系统深色模式不会把配色刷花。
- 设置页跟着主题走：`/api/state` 里带 `palettes`，切 `theme` 时页面配色与表单配色框同时更新；深浅两套下输入框、按钮、状态徽章、日志框、提示气泡都各自有对比度合格的取值。
- 浏览器页签图标、页头 logo 和「报头与署名」里的预览都读同一个 `logo_file`（接口 `/api/brand-logo`）。
- 换公司只要改 `brand` 段，再把新图放进 `src/evenews/data/`（那里会被打进包里）。
- 改完代码要重启设置页才生效：端口被旧的 `evenews web` 占着时，新进程会直接退出并提示换端口，不会再静默地让你看旧页面。

## 每日定时

```bash
evenews daemon                      # 常驻进程，跨平台，最省事（Ctrl+C 退出）
evenews install-task                # Windows 任务计划程序（生成 run_daily.cmd + schtasks）
evenews install-cron                # Ubuntu crontab
evenews systemd                     # Ubuntu systemd service；加 --timer 用 oneshot+timer
```

时间来自 `config.yaml`：

```yaml
schedule:
  time: "08:00"
  timezone: Asia/Shanghai
  weekday_only: false     # true 则只在周一至周五发送
```

Windows / Ubuntu 的落地细节见 [docs/deployment.md](docs/deployment.md)。

## 信息搜集：模型配置方式

采集分两段，各自独立可配。

**来源池**（`sources` + 板块里的 `sources`）：RSS/Atom，用 `evenews sources` 逐个测试能抓到多少条。

**模型**（`llm`）：决定哪些条目值得进简报、摘要怎么写、导语怎么写。

```yaml
llm:
  provider: deepseek            # mock | openai | anthropic | ollama | deepseek | moonshot | dashscope | siliconflow
  base_url: https://api.deepseek.com/v1
  model: deepseek-chat
  api_key_env: EVE_NEWS_LLM_API_KEY
  temperature: 0.2
  tasks:                        # 每个环节单独开关，关掉即退回规则处理
    select: true                # 打分、排序、去重、剔除营销稿
    classify: true              # 判断条目属于哪个板块
    summarize: true             # 每条 300-400 字综合介绍
    lead: true                  # 今日摘要导语
```

任何 OpenAI 兼容网关都能直接用（`base_url` + `model` 决定一切）；本地模型填 `provider: ollama`、`base_url: http://127.0.0.1:11434`，不需要密钥；`provider: mock` 是内置的离线规则模型，用来验版式和跑单测。

每条资讯的介绍目标 **300-400 字**（`evenews.curator.SUMMARY_CHARS`），要求写成一段连贯中文：背景 → 今天发生了什么 → 关键数字/参数/时间点 → 各方回应或对比数据 → 对我们的意义。为了让模型有料可写，来源正文最多留 2400 字（每次给模型读前 1200 字）。来源本身只有一两句话时（不少 arXiv / InfoQ 订阅就是这样），提示词要求它**据实写短到 150 字左右**，并明令禁止用「材料未提及」「需进一步核实」「应关注官方口径」这类话凑篇幅 —— 宁可短，不要水。关掉 `tasks.summarize` 时走离线兜底：从 RSS 原文拼最多 9 句、约 360 字，不会退化成一句话。

上限会按 `llm.max_output_tokens` 与本批条数自动收敛（`curator.summary_rule`），永远不向模型要它一轮写不完的量。注意**上下文 256K 不等于能写很多**：单次输出另有 `max_tokens` 上限，而且推理型模型（Qwen3、DeepSeek 推理模式等）的思考 token 也计在这里 —— 实测某网关只处理 2 条候选，`completion_tokens` 就 8938（其中 8466 是思考），8000 的上限必然被掐断，所以默认给到 `max_output_tokens: 32000`。真被掐断时不再整批作废：

- 日志按 `finish_reason=length` 明确报「输出被掐断，调大 max_output_tokens 或调小 batch_size」；
- 半截 JSON 里已经写完的条目照样收下（`llm.salvage_truncated`）；
- 缺的条目自动拆小批再问一轮（`curator._collect`），补齐后每条仍是完整介绍，不会退成一行。

默认不关思考：日报一天一次，慢慢跑没关系，模型想清楚再写出来的介绍明显更好。真想省时间可以用 `llm.extra_body`（原样并进请求体，多数网关支持关掉思考，实测同一批输出从 8938 降到 3787 token，长度不变、但分析深度会打折）：

```yaml
llm:
  max_output_tokens: 32000   # 一天一次，宁可给足
  batch_size: 4              # 批越小，每条能写的字数越多，也越不容易被掐断
  # extra_body:              # 可选：只在这个任务赶时间时才考虑
  #   enable_thinking: false
```

想让模型自己上网检索补充信息：

```yaml
collection:
  mode: hybrid          # feeds 只用来源池 | llm 以模型检索为主 | hybrid 两者都跑
llm:
  search:
    provider: tavily    # none | tavily | serper
    api_key_env: EVE_NEWS_SEARCH_API_KEY
    queries_per_section: 2   # 每个板块让模型写几条检索词
```

## 邮件

```yaml
email:
  smtp_host: smtp.qq.com
  smtp_port: 465
  security: ssl          # ssl | starttls | none
  username: bot@example.com
  password_env: EVE_NEWS_SMTP_PASSWORD   # 只从环境变量 / .env 读，配置里不落明文
  from: "AI 每日资讯 <bot@example.com>"
  to: [team@example.com]
  subject_template: "{title} · {date}"
  attach_html: false     # 附件带一份自包含 digest.html
  attach_logo: true      # logo 作为内联附件（cid:evenews-logo）随信发出
```

QQ / 163 / 企业邮需要在邮箱设置里开启 SMTP 并生成**授权码**当密码。正文是 HTML + 纯文本双版本，手机端和纯文本客户端都能看。报头图片用内联附件时，若客户端把图片挡住，`alt` 会退回公司名 / `logo_text` 文字报头，版式不会塌。

## 目录结构

```
src/evenews/
  cli.py          命令行入口（run / preview / daemon / enable / doctor ...）
  web.py          本地网页设置台（浏览器改配置，密钥只写 .env）
  webui/          设置页 index.html（单文件，无前端框架、不引外部 CDN）
  config.py       YAML + 环境变量，板块与来源池解析
  feeds.py        RSS 采集（并发、时间窗、来源池去重）
  search.py       可选联网检索（Tavily / Serper）
  llm.py          模型接入：OpenAI 兼容 / Anthropic / Ollama / 内置 mock
  curator.py      规则先筛、模型再选、最后跨板块去重
  render.py       HTML / Markdown / 纯文本 / JSON
  templates/      digest.html.j2 等模板（版式都在这）
  mailer.py       SMTP 发送与重试
  scheduler.py    守护进程 + Windows/Ubuntu 定时任务生成
  state.py        记录发过的条目，默认 10 天内不重复推送
  data/config.example.yaml   evenews init 的模板
  sample/feeds/   离线演示用的样例订阅源
```

## 常见问题

- **跑出来是空的**：先 `evenews sources` 看来源能不能抓到；再查 `collection.lookback_hours`（默认只看最近 30 小时）与 `require_keywords`。
- **某个板块当天没料**：简报会自动跳过空板块，不会出现「今日该板块没有筛选出符合条件的内容」这种占位段落，版号按实际展示的板块连续排。整期一条都没有时直接跳过发信，并在运行报告里记 `本期没有任何入选条目`，避免给同事发一封白页。
- **同一天再跑一次就空了**：已修。历史去重只挡「更早日期」推送过的条目，当天标记的记录不会饿死重跑，改完来源随时可以 `evenews run` 重新生成。
- **同一篇新闻会不会出现在两个板块**：不会，`curator.dedupe_across_sections` 把一篇新闻留给打分最高的板块。
- **模型没配好会不会发不出去**：不会。模型调用失败时该环节自动退回规则打分，简报照常生成，失败原因写进日志。
- **想换版式**：改 `src/evenews/templates/digest.html.j2`，配色在 `brand` 段。
- **中文乱码**：Windows 控制台先 `chcp 65001`，或改看 `logs/daily.log`。
- **每条介绍太短**：模型写作环节的提示词已经要求 200-260 个汉字的综合分析（发生了什么 + 关键数字/时间点 + 一句影响）。没配密钥时走规则兜底，摘前 5 句拼成一段，长度约 130-260 字。想让模型写得更细，调大 `llm.batch_size`（一次塞给模型的条数，默认 8）与 `llm.max_output_tokens`（默认 8000）。
- **想接一个 JSON 接口当来源**：来源写 `type: json`，再用 `json:` 把字段映射成条目，模板里的 `modelscope`、`hf_trending` 就是两个例子。`items` 是数组在返回 JSON 里的位置（点路径，如 `Data.Articles`，顶层就是数组时留空）；`title` / `summary` / `url` / `date` 给字段名或候选链（`date` 支持秒级时间戳和 ISO 字符串，`summary` 能直接吃 tags 数组）；`base_url` 把相对链接和裸 id（`Qwen/xxx`）拼成可点开的地址；`facts` 把 likes、downloads 之类的结构化字段拼进材料，模型就有数字可写；`require` 既能写「必须为真的字段」（`IsPGC`），也能写阈值（`likes>=30`）。
- **模型榜上全是个人练手仓库**：`hf_trending` 用 `require: [likes>=30, trendingScore>=1]` 卡掉个人上传，只留新发布且有热度的模型；阈值想更严就调大。
- **某个来源的东西都比别的老**（模型榜、周报类接口上榜慢）：在**那个来源**里单独加 `lookback_hours: 336`（小时），只放宽它自己的时间窗，别的来源照旧跟 `collection.lookback_hours`。模板里的 `hf_trending` 就是这样设成 14 天的。
- **境外源换血**：`huggingface` 博客境内直连不稳，已 `enabled: false`；平台/机构内容改抓 **魔搭 ModelScope**（`modelscope`，JSON 来源，`require: [IsPGC]` 不抓个人帖），新模型发布改抓 **hf-mirror**（`hf_trending`，HuggingFace API 的境内镜像，直连可用，按热度阈值过滤个人仓库）。`sspai`、`juejin` 以个人体验帖为主，同样停了，`exclude_keywords` 里加了 新玩意 / 好物 / 开箱 / 购物清单。想要个人向内容就把对应来源的 `enabled` 改回 `true`。
- **觉得新闻不够实时**：日报读的是 `collection.lookback_hours`（默认 30 小时）窗口，早上发自然是「昨天到今天」。想更快：`collection.mode: hybrid` + `llm.search.provider`（模型现查），或把 `schedule.time` 挪到中午/晚上再装一个计划任务，一天多发。规则打分里当天条目会加分、昨天的扣分，旧闻不会占版面。
- **某个来源一直超时**：先 `evenews sources` 看谁挂了。默认先走系统代理、失败自动直连；代理回 403/429/5xx 同样算失败，也会自动改直连再试。境内站（魔搭、hf-mirror）本来不该绕境外代理出口，模板里已给它们写 `proxy: none` 强制直连；某个境外源想单独走代理就在来源里写 `proxy: http://127.0.0.1:7890`，全局开关是 `collection.proxy`。个别来源失败不会中断整期简报，失败清单会写进运行报告、设置页和简报页脚。
- **来源实测（2026-09-25）**：来源池共 22 个、默认启用 15 个。停用的 7 个里，机器之心、36氪、半导体行业观察、虎嗅 是公开 RSS 已失效或长期读超时；HuggingFace 博客境内直连不稳（同板块改用魔搭 ModelScope）；少数派、掘金 以个人体验帖为主，不适合公司日报。想开就在来源池把 `enabled` 改回 `true`，境外源记得配 `collection.proxy`。
- **离线试跑出来的不是新闻**：`evenews run --offline`（设置页的「离线试跑」）用的是内置样例，简报顶部会挂红色「离线演示」提示条，邮件主题自动加 `[演示]` 前缀，避免误发给同事。
- **完全不想碰命令行**：`evenews web` 打开设置页，板块、模型、SMTP、发送时间、密钥都能在网页里改，见「网页设置」。


## 开发

```bash
pip install -e ".[dev]"
pytest -q
```

测试覆盖配置解析、板块开关、采集时间窗、规则过滤、跨板块去重、历史去重、渲染、邮件报文与定时计算，全部离线运行（内置 mock 模型 + `sample/feeds`），不依赖网络与密钥。

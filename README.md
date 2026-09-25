# Eve_News · AI 每日资讯

每天早上把 AI 行业要点整理成一封报纸味道的邮件发到公司邮箱：**Windows 和 Ubuntu 都能跑**，板块可以勾选，采集与写作环节都走可替换的大模型配置。

版式对齐内部《AI 每日资讯》：报头 + 今日摘要 + 6 个板块 + 引用来源页脚。

## 6 个默认板块

| id | 板块 | 关注点 |
| --- | --- | --- |
| `llm_oss` | 大模型与开源生态 | 模型发布、评测榜单、开源权重、API 价格 |
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
| 板块勾选 | 6 个板块的开关、条数上限、关键词；板块和来源池的增删去「高级 YAML」 |
| 采集与模型 | `provider` / `base_url` / `model` / 各环节开关、过滤关键词、联网检索；带「测试模型连通」「测试所有来源」 |
| 邮件 | SMTP 主机端口与 security、收发件人、报头署名；一键「发测试邮件」 |
| 计划与密钥 | 每天几点发、时区、仅工作日；密钥写在这里，只落 `.env` |
| 运行与预览 | 离线试跑、生成预览、立即发送，页面内直接看最新一期 |
| 高级 YAML | 整份 `config.yaml` 直接编辑，保存前走一遍真实校验，不通过不落盘 |

- 默认只监听 `127.0.0.1`，别在生产机上 `--host 0.0.0.0` 开放到局域网。
- 密钥只写进 `.env`，接口只回「是否已设置 + 长度」，绝不回传明文；`config.yaml` 里只存变量名。
- 图形界面保存会重写 `config.yaml`（丢注释，注释版模板看 `config.example.yaml`），同时留一份 `config.yaml.bak` 兜底。

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
    summarize: true             # 80-140 字中文摘要
    lead: true                  # 今日摘要导语
```

任何 OpenAI 兼容网关都能直接用（`base_url` + `model` 决定一切）；本地模型填 `provider: ollama`、`base_url: http://127.0.0.1:11434`，不需要密钥；`provider: mock` 是内置的离线规则模型，用来验版式和跑单测。

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
  attach_html: false
```

QQ / 163 / 企业邮需要在邮箱设置里开启 SMTP 并生成**授权码**当密码。正文是 HTML + 纯文本双版本，手机端和纯文本客户端都能看。

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
- **同一篇新闻会不会出现在两个板块**：不会，`curator.dedupe_across_sections` 把一篇新闻留给打分最高的板块。
- **模型没配好会不会发不出去**：不会。模型调用失败时该环节自动退回规则打分，简报照常生成，失败原因写进日志。
- **想换版式**：改 `src/evenews/templates/digest.html.j2`，配色在 `brand` 段。
- **中文乱码**：Windows 控制台先 `chcp 65001`，或改看 `logs/daily.log`。
- **觉得新闻不够实时**：日报读的是 `collection.lookback_hours`（默认 30 小时）窗口，早上发自然是「昨天到今天」。想更快：`collection.mode: hybrid` + `llm.search.provider`（模型现查），或把 `schedule.time` 挪到中午/晚上再装一个计划任务，一天多发。规则打分里当天条目会加分、昨天的扣分，旧闻不会占版面。
- **某个来源一直超时**：先 `evenews sources` 看谁挂了；境外源把 `collection.proxy` 显式填成代理地址（或填 `none` 强制直连），确实不要就在来源池里加 `enabled: false`。个别来源失败不会中断整期简报，失败清单会写进运行报告、设置页和简报页脚。
- **来源实测（2026-09-25）**：机器之心、36氪、半导体行业观察、虎嗅 的公开 RSS 已失效或长期读超时，模板里已默认 `enabled: false`；补进 开源中国、Solidot、极客公园、钛媒体、掘金、Google AI 官方博客 六个可用来源，实测 17 个来源里 15 个能抓到内容（huggingface 需要代理可用，虎嗅已停用）。
- **离线试跑出来的不是新闻**：`evenews run --offline`（设置页的「离线试跑」）用的是内置样例，简报顶部会挂红色「离线演示」提示条，邮件主题自动加 `[演示]` 前缀，避免误发给同事。
- **完全不想碰命令行**：`evenews web` 打开设置页，板块、模型、SMTP、发送时间、密钥都能在网页里改，见「网页设置」。


## 开发

```bash
pip install -e ".[dev]"
pytest -q
```

测试覆盖配置解析、板块开关、采集时间窗、规则过滤、跨板块去重、历史去重、渲染、邮件报文与定时计算，全部离线运行（内置 mock 模型 + `sample/feeds`），不依赖网络与密钥。

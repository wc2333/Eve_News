# 部署：Windows 与 Ubuntu

三种定时方式选一种即可。发送时间统一读 `config.yaml` 的 `schedule.time` / `schedule.timezone`。

## 先填配置（网页最省事）

装定时器之前，先用设置页把 SMTP、模型、收件人、发送时间、密钥填完——三种定时方式读的都是同一份 `config.yaml`。

```bash
evenews web                    # 本机桌面：自动开浏览器
evenews web --no-browser       # 无图形界面的服务器
```

服务器上远程改配置：`evenews web --no-browser` 之后，在自己电脑上做 `ssh -L 8765:127.0.0.1:8765 user@host`，浏览器打开 `http://127.0.0.1:8765`。别直接把服务绑到 `0.0.0.0`。

## Windows（公司台式机 / 服务器）

```powershell
cd C:\path\to\Eve_News
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
evenews init
notepad .env                # 填 EVE_NEWS_SMTP_PASSWORD / EVE_NEWS_LLM_API_KEY
evenews run --offline       # 版式确认
evenews test-email          # 邮件通道确认
evenews install-task --dry-run
evenews install-task        # 写入任务计划程序（每天 schedule.time）
```

`install-task` 做两件事：在项目目录生成 `run_daily.cmd`（切到项目目录 → 跑 `evenews run` → 日志追加到 `logs/daily.log`），再调用 schtasks 建一个每天 `schedule.time` 触发的任务 `EveNews Daily Briefing`。

核对与调整：

```powershell
schtasks /Query /TN "EveNews Daily Briefing" /V /FO LIST
schtasks /Run /TN "EveNews Daily Briefing"       # 立即试跑
schtasks /Delete /TN "EveNews Daily Briefing" /F # 卸载
```

想无人值守：任务计划程序“常规”里选“不管用户是否登录都要运行”，“条件”里勾允许唤醒计算机运行此任务，“设置”里勾“如果错过了计划任务，请尽快启动任务”。

密钥不放环境变量也可以：`.env` 放在项目目录，`evenews` 启动时自动读取（不会覆盖真实环境变量）。

## Ubuntu（cron）

```bash
sudo mkdir -p /opt/eve_news && sudo chown $USER /opt/eve_news
git clone <你的仓库地址> /opt/eve_news && cd /opt/eve_news
python3 -m venv .venv
./.venv/bin/pip install -e .
./.venv/bin/evenews init
nano .env
./.venv/bin/evenews run --offline
./.venv/bin/evenews install-cron --dry-run
./.venv/bin/evenews install-cron
```

生成的行形如：

```cron
# evenews daily briefing
0 8 * * * cd /opt/eve_news && /opt/eve_news/.venv/bin/python -m evenews run --config /opt/eve_news/config.yaml >> /opt/eve_news/logs/daily.log 2>&1
```

时区注意：cron 用系统时区，先 `timedatectl` 确认；不一致就把 `schedule.timezone` 与系统时区对齐，或改用 systemd。

## Ubuntu（systemd）

常驻模式：

```bash
./.venv/bin/evenews systemd > evenews.service
sudo cp evenews.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now evenews
systemctl status evenews; journalctl -u evenews -f
```

定时器模式（不常驻）：`evenews systemd --timer` 会输出 oneshot 版 service 与 timer 两段，分别写到 `/etc/systemd/system/evenews.service` 和 `evenews.timer`，然后 `systemctl enable --now evenews.timer`。`Persistent=true` 让关机期间错过的任务在开机后补跑一次。密钥可以写进 `EnvironmentFile=/opt/eve_news/.env`（取消单元文件里那行注释）。

## 密钥与权限

- `.env`、`config.yaml`、`out/`、`state/`、`logs/`、`run_daily.cmd` 都在 `.gitignore` 里，不进仓库。
- 配置里只写变量名（`password_env` / `api_key_env` / `search.api_key_env`），值来自环境变量或 `.env`。
- 建议单独申请一个只用于群发的邮箱账号；QQ/163 用授权码当密码，授权码到期需要更换。
- 网页设置页保存密钥会直接改写 `.env`（非 Windows 下自动 `chmod 600`）；留空并保存 = 删掉那一行。

## 运维清单

```text
配置体检（来源 + 模型连通）   evenews doctor --sources --model
来源能不能抓到               evenews sources
只生成不发信                 evenews preview
补发某一天                   evenews run --date 2026-09-24
只跑某几个板块               evenews run --sections llm_oss,domestic_compute
重置“发过了”的记忆            删除 state/state.json
看发送日志                   logs/daily.log 或 journalctl -u evenews
```

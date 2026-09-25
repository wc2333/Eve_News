"""evenews command line interface."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from . import __version__
from .config import Config, ConfigError, write_default_config
from .feeds import fetch_source
from .llm import build_llm
from .mailer import MailError, send_digest
from .pipeline import run_once
from .render import render_text
from .scheduler import (
    cron_line,
    daemon_hint,
    install_cron,
    install_windows_task,
    systemd_service,
    systemd_timer,
    run_daemon,
)

log = logging.getLogger("evenews")


def _configure_console() -> None:
    """Force UTF-8 output so a cp1252/GBK console never kills a run."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):  # pragma: no cover - exotic streams
            pass


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _config(args: argparse.Namespace) -> Config:
    try:
        return Config.load(Path(args.config) if args.config else None)
    except ConfigError as exc:
        print(f"配置问题：{exc}", file=sys.stderr)
        raise SystemExit(2)


def _split(value: str | None) -> list[str] | None:
    return [part.strip() for part in value.split(",") if part.strip()] if value else None


def _print_problems(config: Config, need_email: bool) -> bool:
    problems = config.problems(need_email=need_email)
    for problem in problems:
        print(f"  ! {problem}")
    return not problems


def cmd_init(args: argparse.Namespace) -> int:
    target = Path(args.dir or ".") / "config.yaml"
    try:
        written = write_default_config(target, force=args.force)
    except ConfigError as exc:
        print(f"初始化失败：{exc}", file=sys.stderr)
        return 2
    env_example = Path(written).parent / ".env.example"
    if not env_example.exists():
        env_example.write_text(
            "# cp .env.example .env 后填写；.env 不要提交到 git\n"
            "EVE_NEWS_SMTP_PASSWORD=\n"
            "EVE_NEWS_LLM_API_KEY=\n"
            "EVE_NEWS_SEARCH_API_KEY=\n",
            encoding="utf-8",
        )
    print(f"已生成 {written}")
    print("下一步：")
    print(f"  1) 编辑 {written}：填 email 与 llm 两段")
    print(f"  2) cp {env_example.name} .env 并填入密钥")
    print("  3) evenews run --offline  # 先用离线样例看效果")
    print("  4) evenews run            # 真实采集并发送")
    print("  5) evenews daemon         # 或 evenews install-task / install-cron 挂到系统定时任务")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    config = _config(args)
    if not args.offline and not _print_problems(config, need_email=not args.dry_run):
        print("配置还有问题，先修一下（或加 --offline 先看效果）", file=sys.stderr)
        return 2
    report = run_once(
        config,
        when=args.date,
        only=_split(args.sections),
        offline=args.offline,
        fixtures=Path(args.fixtures) if args.fixtures else None,
        send=not args.dry_run,
        out_root=Path(args.out) if args.out else None,
    )
    print(report.summary())
    if report.errors:
        for error in report.errors:
            print(f"  ! {error}", file=sys.stderr)
    if report.files:
        print(f"HTML: {report.files.get('html')}")
    return 0 if report.sent or args.dry_run or not config.email.enabled else 1


def cmd_preview(args: argparse.Namespace) -> int:
    args.dry_run = True
    code = cmd_run(args)
    if getattr(args, "open", False) and code == 0:
        import webbrowser

        config = _config(args)
        latest = sorted((config.out_root).glob("*/digest.html"))
        if latest:
            webbrowser.open(latest[-1].as_uri())
            print(f"已在浏览器打开：{latest[-1]}")
    return code


def cmd_daemon(args: argparse.Namespace) -> int:
    config = _config(args)
    if not _print_problems(config, need_email=True):
        print("配置还有问题，daemon 不会启动", file=sys.stderr)
        return 2

    def job() -> None:
        report = run_once(config)
        log.info(report.summary())

    try:
        run_daemon(config, job)
    except KeyboardInterrupt:
        print("已停止")
    return 0


def cmd_sections(args: argparse.Namespace) -> int:
    config = _config(args)
    for section in config.sections:
        mark = "开" if section.enabled else "关"
        sources = "、".join(source.name for source in section.sources) or "（无来源）"
        print(f" [{mark}] {section.id:<18} {section.title}")
        print(f"       说明：{section.description or '-'}")
        print(f"       来源：{sources}")
    print()
    print("切换板块：evenews enable <id> / evenews disable <id>（多个用逗号分隔）")
    return 0


def cmd_toggle(args: argparse.Namespace, enabled: bool) -> int:
    config = _config(args)
    try:
        for section_id in _split(args.ids) or []:
            section = config.set_section_enabled(section_id, enabled)
            print(f"{'已开启' if enabled else '已关闭'}板块：{section.id}（{section.title}）")
        saved = config.save()
        print(f"写回 {saved}（注意：保存会重写文件，手写注释可能丢失）")
    except ConfigError as exc:
        print(f"操作失败：{exc}", file=sys.stderr)
        return 2
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    config = _config(args)
    print(f"配置文件：{config.path}")
    print(f"模型：provider={config.llm.provider} model={config.llm.model or '-'} base_url={config.llm.base_url or '-'}")
    print(f"检索：provider={(config.llm.search or {}).get('provider', 'none')} mode={config.collection.mode}")
    print(f"邮件：{config.email.smtp_host}:{config.email.smtp_port} ({config.email.security}) 收件人 {len(config.email.to) + len(config.email.cc)} 人")
    print(f"计划：每天 {config.schedule.time}（{config.schedule.timezone}）{'仅工作日' if config.schedule.weekday_only else ''}")
    print(f"板块：{len(config.enabled_sections())}/{len(config.sections)} 个已开启")
    ok = _print_problems(config, need_email=not args.no_email)
    if args.sources:
        print("\n来源连通性：")
        seen: set[str] = set()
        for section in config.enabled_sections():
            for source in section.sources:
                key = f"{source.name}|{source.url}"
                if key in seen:
                    continue
                seen.add(key)
                try:
                    items = fetch_source(source, config.collection)
                    print(f"  {'OK' if items else 'EMPTY':<5} {source.name} · {len(items)} 条")
                except Exception as exc:  # noqa: BLE001
                    print(f"  FAIL  {source.name} · {exc}")
    if args.model and config.llm.provider not in {"mock", "off"}:
        llm = build_llm(config.llm)
        try:
            data = llm.json_task("lead", {"date": datetime.now().date().isoformat(), "item_count": 1, "sections": [{"title": "测试", "count": 1, "headlines": ["连通性测试"]}],"rules": {"length": "20 字以内", "output": '{"lead":""}'}})
            print(f"模型连通：OK -> {str(data.get('lead') or data)[:60]}")
        except Exception as exc:  # noqa: BLE001
            ok = False
            print(f"模型连通：FAIL {exc}", file=sys.stderr)
    print("\n结论：" + ("配置可用" if ok else "存在需要处理的问题"))
    print(daemon_hint(config))
    return 0 if ok else 1


def cmd_sources(args: argparse.Namespace) -> int:
    config = _config(args)
    seen: set[str] = set()
    total = 0
    for section in config.enabled_sections():
        for source in section.sources:
            key = f"{source.name}|{source.url}|{source.type}"
            if key in seen:
                continue
            seen.add(key)
            try:
                items = fetch_source(source, config.collection)
                total += len(items)
                print(f" {'OK' if items else 'EMPTY':<5} {source.name:<14} {len(items):>3} 条  {source.url}")
                for item in items[:2]:
                    print(f"        · {item.title[:48]}")
            except Exception as exc:  # noqa: BLE001
                print(f" FAIL  {source.name:<14} {exc}")
    print(f"\n共 {len(seen)} 个来源，抓到 {total} 条候选")
    return 0


def cmd_test_email(args: argparse.Namespace) -> int:
    config = _config(args)
    recipients = _split(args.to) or None
    subject = f"[测试] {config.brand.title} 邮件通道检查"
    body = "这是一封 Eve_News 的测试邮件。收到即说明 SMTP 配置正确，接下来运行 evenews daemon 或系统定时任务即可。"
    try:
        sent_to = send_digest(config.email, subject=subject, html=f"<p>{body}</p>", text=body, to=recipients)
    except MailError as exc:
        print(f"发送失败：{exc}", file=sys.stderr)
        return 1
    print(f"测试邮件已发送：{', '.join(sent_to)}")
    return 0


def cmd_install_task(args: argparse.Namespace) -> int:
    config = _config(args)
    try:
        output = install_windows_task(config, apply=not args.dry_run)
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 1
    print(output)
    if args.dry_run:
        print("（上面是预览，去掉 --dry-run 即真正写入任务计划程序）")
    else:
        print(f"任务计划程序里应能看到：{output}")
        print("查看：schtasks /Query /TN \"EveNews Daily Briefing\" /V /FO LIST")
    return 0


def cmd_install_cron(args: argparse.Namespace) -> int:
    config = _config(args)
    try:
        output = install_cron(config, apply=not args.dry_run)
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 1
    print(output)
    print(("（预览，去掉 --dry-run 生效）" if args.dry_run else "已写入 crontab"))
    return 0


def cmd_systemd(args: argparse.Namespace) -> int:
    config = _config(args)
    print(systemd_timer(config) if args.timer else systemd_service(config))
    return 0


def cmd_version(args: argparse.Namespace) -> int:
    print(f"evenews {__version__} · Python {sys.version.split()[0]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="evenews", description="AI 每日资讯：定时聚合 + 模型筛选 + 邮件推送")
    parser.add_argument("-c", "--config", help="配置文件路径（默认在当前位置向上找 config.yaml）")
    parser.add_argument("-v", "--verbose", action="store_true", help="输出调试日志")
    sub = parser.add_subparsers(dest="command")

    init = sub.add_parser("init", help="生成 config.yaml 与 .env.example")
    init.add_argument("--dir", help="输出目录，默认当前目录")
    init.add_argument("--force", action="store_true", help="覆盖已有 config.yaml")
    init.set_defaults(func=cmd_init)

    def common(command: argparse.ArgumentParser, *, mail: bool = True) -> argparse.ArgumentParser:
        command.add_argument("--date", help="按指定日期运行 YYYY-MM-DD（用于补发/回放）")
        command.add_argument("--sections", help="只跑这些板块 id，逗号分隔")
        command.add_argument("--out", help="输出目录，默认 out/<日期>/")
        if mail:
            command.add_argument("--dry-run", action="store_true", help="只生成文件，不发邮件")
            command.add_argument("--offline", action="store_true", help="离线演示：mock 模型 + 内置样例来源")
            command.add_argument("--fixtures", help="本地 RSS 目录（配合 --offline 或单元测试）")
        return command

    run = common(sub.add_parser("run", help="立即生成并发送邮件"))
    run.set_defaults(func=cmd_run)
    preview = common(sub.add_parser("preview", help="只生成不发送（等价 run --dry-run）"))
    preview.add_argument("--open", action="store_true", help="生成后用系统浏览器打开 HTML")
    preview.set_defaults(func=cmd_preview)

    daemon = sub.add_parser("daemon", help="常驻进程，按 schedule.time 每天运行")
    daemon.set_defaults(func=cmd_daemon)

    sections = sub.add_parser("sections", help="列出板块与开关状态")
    sections.set_defaults(func=cmd_sections)

    enable = sub.add_parser("enable", help="开启板块：evenews enable llm_oss,edge_ai")
    enable.add_argument("ids", help="板块 id，逗号分隔")
    enable.set_defaults(func=lambda args: cmd_toggle(args, True))

    disable = sub.add_parser("disable", help="关闭板块：evenews disable wearables")
    disable.add_argument("ids", help="板块 id，逗号分隔")
    disable.set_defaults(func=lambda args: cmd_toggle(args, False))

    doctor = sub.add_parser("doctor", help="检查配置、密钥、来源与模型连通性")
    doctor.add_argument("--no-email", action="store_true", help="忽略邮件相关缺失项")
    doctor.add_argument("--sources", action="store_true", help="顺便测试每个来源")
    doctor.add_argument("--model", action="store_true", help="顺便测试模型连通性")
    doctor.set_defaults(func=cmd_doctor)

    sources = sub.add_parser("sources", help="测试每个来源能抓到多少条")
    sources.set_defaults(func=cmd_sources)

    mail = sub.add_parser("test-email", help="发一封测试邮件确认 SMTP 可用")
    mail.add_argument("--to", help="临时收件人，逗号分隔（默认用配置里的 to）")
    mail.set_defaults(func=cmd_test_email)

    task = sub.add_parser("install-task", help="Windows：写入任务计划程序（每天定时）")
    task.add_argument("--dry-run", action="store_true", help="只打印将要执行的 schtasks 命令")
    task.set_defaults(func=cmd_install_task)

    cron = sub.add_parser("install-cron", help="Ubuntu/Cron：写入 crontab（每天定时）")
    cron.add_argument("--dry-run", action="store_true", help="只打印 crontab 片段")
    cron.set_defaults(func=cmd_install_cron)

    systemd = sub.add_parser("systemd", help="Ubuntu/systemd：打印 service 与 timer 单元")
    systemd.add_argument("--timer", action="store_true", help="输出 oneshot + timer，而不是常驻 daemon")
    systemd.set_defaults(func=cmd_systemd)

    version = sub.add_parser("version", help="显示版本")
    version.set_defaults(func=cmd_version)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 1
    _configure_console()
    _setup_logging("DEBUG" if args.verbose else "INFO")
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        print("已取消")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""命令行入口：按分组 DSL 执行标注采集出来的流程。

用法：
    python main.py --list                       列出全部分组
    python main.py --group 御魂十一 --show       只看 DSL 解析结果，不执行
    python main.py --group 御魂十一 --init-dsl   按现有标注生成 flow.py 草稿
    python main.py --group 御魂十一 --times 10   跑 10 轮
    python main.py --group 御魂十一              无限循环，Ctrl-C 停

退出码：0 正常 / 1 流程异常 / 2 参数缺失 / 130 用户中断
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import settings  # noqa: E402
from core.errors import StaminaExhaustedError, YysError  # noqa: E402
from core.logger import get_logger  # noqa: E402
from runner.dsl import load_group_flow, write_scaffold  # noqa: E402
from runner.engine import build_runner  # noqa: E402
from runner.errors import DslError, GroupError, RunnerError  # noqa: E402
from runner.group import GroupRef, list_groups, load_group  # noqa: E402

log = get_logger("main")


def enable_debug() -> None:
    """把控制台也调到 DEBUG。"""
    logging.getLogger().setLevel(logging.DEBUG)
    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.StreamHandler) and handler.stream is sys.stdout:
            handler.setLevel(logging.DEBUG)


def print_groups(data_dir: Optional[Path]) -> int:
    """列出全部分组。"""
    groups = list_groups(data_dir)
    if not groups:
        print("还没有分组，先跑 python similarity/app.py 去采集页建一个")
        return 2
    print("{:<24} {:<26} {:>4} {:>4}  {}".format(
        "分组名", "key", "截图", "标注", "DSL"))
    for item in groups:
        dsl = Path(item["dir"]) / settings.RUNNER_DSL_FILENAME
        print("{:<24} {:<26} {:>4} {:>4}  {}".format(
            item["name"], item["key"], item["shots"], item["annotations"],
            "有" if dsl.is_file() else "无（--init-dsl 生成）"))
    return 0


def print_plan(group: GroupRef) -> int:
    """打印 DSL 解析结果。"""
    flow = load_group_flow(group)
    runner = build_runner(group, flow, dry_run=True)
    steps = runner.resolve()
    print("分组   : {}".format(group.describe()))
    print("DSL    : {}".format(flow.source))
    print("流程名 : {}".format(flow.name))
    print("钩子   : {}".format(", ".join(sorted(flow.hooks)) or "无"))
    print("整轮超时: {:.0f}s".format(runner.round_timeout))
    print("入口探测: {}".format(" → ".join(flow.entry) or "关（固定从第 1 步起跑）"))
    print("步骤（{} 步，跑完回到第 1 步）:".format(len(steps)))
    for index, item in enumerate(steps, 1):
        print("  {}. {}".format(index, item.describe()))
        print("     目标图 {}  采集时窗口 {}  标注坐标 {}".format(
            item.shot.image_path.name, item.shot.region,
            item.annotation.point if item.annotation else "无"))
    return 0


def check_model() -> None:
    """跑之前先确认模型可用。"""
    from similarity.llm_judge import OmniJudge

    info = OmniJudge().health()
    if not info["ok"]:
        raise RunnerError("模型不可用：{}".format(info["error"]))
    log.info("判定模型 %s 在线（%s）", info["model"], ", ".join(info["capabilities"]))


def run(args: argparse.Namespace, group: GroupRef) -> int:
    """执行主循环。"""
    flow = load_group_flow(group)
    if not args.dry_run:
        check_model()

    runner = build_runner(
        group,
        flow,
        times=args.times,
        round_timeout=args.round_timeout,
        continue_on_error=args.continue_on_error,
        dry_run=args.dry_run,
        humanize=not args.no_humanize,
    )
    if args.no_adaptive_wait:
        runner.timer.adaptive = False
    if not args.dry_run:
        log.info("窗口：%s", runner.session.describe_window())
    report = runner.run()
    print()
    print(report.summary())
    if report.failed and not report.completed:
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="按分组 DSL 执行标注流程（图像相似度识别）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
               "  python main.py --list\n"
               "  python main.py --group 御魂十一 --init-dsl\n"
               "  python main.py --group 御魂十一 --show\n"
               "  python main.py --group 御魂十一 --times 10\n")
    parser.add_argument("--group", help="分组名或 key")
    parser.add_argument("--times", type=int, default=None, help="跑多少轮，不给就无限循环")
    parser.add_argument("--data-dir", default=None, help="数据集目录，默认 similarity/dataset")
    parser.add_argument("--list", action="store_true", help="列出全部分组")
    parser.add_argument("--show", action="store_true", help="只打印 DSL 解析结果，不执行")
    parser.add_argument("--init-dsl", action="store_true", help="按现有标注生成 flow.py 草稿")
    parser.add_argument("--force", action="store_true", help="--init-dsl 时覆盖已有文件")
    parser.add_argument("--dry-run", action="store_true", help="解析并打印，但不截屏不点击")
    parser.add_argument("--round-timeout", type=float, default=None, help="整轮超时（秒）")
    parser.add_argument("--continue-on-error", action="store_true", help="某轮失败也继续下一轮")
    parser.add_argument("--model", default=None, help="覆盖 Ollama 模型名")
    parser.add_argument("--threshold", type=float, default=None, help="覆盖判定阈值")
    parser.add_argument("--no-adaptive-wait", action="store_true", help="关闭自适应等待")
    parser.add_argument("--no-humanize", action="store_true", help="关闭随机抖动与停顿")
    parser.add_argument("--debug", action="store_true", help="输出 DEBUG 级别日志")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.debug:
        enable_debug()
    if args.model:
        settings.OLLAMA_MODEL = args.model
    if args.threshold is not None:
        settings.SIMILARITY_MATCH_THRESHOLD = args.threshold

    data_dir = Path(args.data_dir) if args.data_dir else None
    try:
        if args.list:
            return print_groups(data_dir)
        if not args.group:
            print("缺少 --group（或用 --list 看有哪些分组）", file=sys.stderr)
            return 2

        group = load_group(args.group, data_dir)

        if args.init_dsl:
            path = write_scaffold(group, overwrite=args.force)
            print("已生成 DSL：{}".format(path))
            print("请按实际流程调整 steps 的顺序与超时，然后 --show 检查。")
            return 0

        if args.show:
            return print_plan(group)

        return run(args, group)
    except StaminaExhaustedError as exc:
        log.error("%s", exc)
        return settings.EXIT_CODE_ABORT
    except (DslError, GroupError) as exc:
        log.error("%s", exc)
        return 2
    except YysError as exc:
        log.error("%s", exc)
        return 1
    except KeyboardInterrupt:
        log.warning("用户中断")
        return 130


if __name__ == "__main__":
    sys.exit(main())

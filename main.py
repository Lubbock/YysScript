#!/usr/bin/env python3
"""YysScript 命令行入口。

用法：
    python main.py --list                 # 列出全部功能
    python main.py --check                # 自检：游戏窗口 + 模板图片
    python main.py --states               # 列出全部状态常量
    python main.py explore --times 10     # 自动探索 10 轮
    python main.py soul --times 30        # 自动御魂 30 次
    python main.py shard --times 10     # 式神碎片挑战循环
    python main.py awake --dungeon 4 --times 20
    python main.py breakthrough --times 3 # 3 轮结界突破（不传则无限循环）
    python main.py seal --times 50
    python main.py heart --times 10
    python main.py event-aband3t --times 20
    python main.py event-aj8fer --times 100
"""
from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from config import settings
from core.errors import StaminaExhaustedError, WindowNotFoundError, YysError
from core.logger import get_logger
from flows.registry import get_flow_class, list_flows

log = get_logger("main")

#: 各流程的循环次数参数名
_TIMES_KWARG = {
    "explore": "times",
    "soul": "times",
    "awake": "times",
    "shard": "times",
    "breakthrough": "rounds",
    "seal": "times",
    "heart": "times",
    "event-aband3t": "loops",
    "event-aj8fer": "loops",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yys",
        description="阴阳师自动化脚本（图像识别 + 拟人化操作）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="可用功能：\n" + "\n".join(
            "  {:<16}{}".format(name, desc) for name, desc in list_flows()
        ),
    )
    parser.add_argument("feature", nargs="?", help="要执行的功能名，见 --list")
    parser.add_argument("--list", action="store_true", help="列出全部功能后退出")
    parser.add_argument("--states", action="store_true", help="列出全部状态常量后退出")
    parser.add_argument("--check", action="store_true", help="自检窗口与模板图片后退出")
    parser.add_argument("--times", type=int, default=None, help="循环次数 / 轮数")
    parser.add_argument("--exp-only", action="store_true", help="探索时只打经验怪")
    parser.add_argument("--dungeon", type=int, default=4,
                        help="觉醒副本序号：1 火御魂 2 风麒麟 3 水麒麟 4 雷麒麟")
    parser.add_argument("--fullscreen", action="store_true",
                        help="不找游戏窗口，直接把整个屏幕当客户区")
    parser.add_argument("--no-humanize", action="store_true",
                        help="关闭随机抖动与停顿（调试用，不建议实战）")
    parser.add_argument("--align-window", action="store_true",
                        help="启动前把游戏窗口挪到屏幕左上角（替代旧 scripts/e0001.py）")
    parser.add_argument("--debug", action="store_true", help="输出 DEBUG 级别日志")
    return parser


# --------------------------------------------------------------------------- #
# 辅助命令
# --------------------------------------------------------------------------- #
def print_flows() -> None:
    print("可用功能：")
    for name, description in list_flows():
        print("  {:<16}{}".format(name, description))


def print_states() -> None:
    import states
    from states.base import StateKind

    for kind, title in ((StateKind.SCREEN, "界面状态"), (StateKind.MARKER, "定位标记")):
        print("{}（{} 个）：".format(title, len(states.all_states(kind))))
        for state in states.all_states(kind):
            print("  {:<24} {:<14} {} 阈值={}".format(
                state.key, state.label, ",".join(state.templates), state.threshold))


def run_check() -> int:
    """自检：定位游戏窗口 + 校验模板图片是否齐全。"""
    import states
    from actions.window import GameWindow

    problems: List[str] = []

    print("模板目录: {}".format(settings.TEMPLATE_DIR))
    missing = []
    for state in states.all_states():
        for template in state.templates:
            if not (settings.TEMPLATE_DIR / template).exists():
                missing.append("{} -> {}".format(state.key, template))
    if missing:
        problems.extend(missing)
        print("缺失模板 {} 个:".format(len(missing)))
        for item in missing:
            print("  - {}".format(item))
    else:
        print("模板图片齐全（{} 个状态）".format(len(states.REGISTRY)))

    print("基准客户区: {}x{}".format(*settings.BASE_CLIENT_SIZE))
    try:
        rect = GameWindow().refresh()
    except WindowNotFoundError as exc:
        problems.append(str(exc))
        print("窗口定位失败: {}".format(exc))
    except Exception as exc:  # pyautogui 未安装等
        problems.append(str(exc))
        print("窗口定位异常: {}".format(exc))
    else:
        print("窗口客户区: left={} top={} width={} height={}".format(
            rect.left, rect.top, rect.width, rect.height))
        scale = (rect.width / settings.BASE_CLIENT_SIZE[0],
                 rect.height / settings.BASE_CLIENT_SIZE[1])
        print("坐标缩放比例: x={:.3f} y={:.3f}".format(*scale))

    from actions.mouse import accessibility_trusted

    if not accessibility_trusted():
        problems.append("macOS 辅助功能权限未授予")
        print("辅助功能权限: 未授予 —— 合成点击会被系统静默丢弃，"
              "请到 系统设置 -> 隐私与安全性 -> 辅助功能 勾选你的终端")
    else:
        print("辅助功能权限: 已授予（合成点击可送达）")

    return 1 if problems else 0


# --------------------------------------------------------------------------- #
# 流程执行
# --------------------------------------------------------------------------- #
def build_flow(name: str, args: argparse.Namespace):
    """按命令行参数构造 Flow 实例。"""
    from actions.controller import GameController
    from actions.mouse import HumanMouse
    from actions.window import GameWindow, FullScreenFinder

    finder = FullScreenFinder() if args.fullscreen else None
    window = GameWindow(finder=finder) if finder else GameWindow()
    controller = GameController(
        window=window,
        mouse=HumanMouse(humanize=not args.no_humanize),
        debug=args.debug,
    )

    if args.align_window:
        # 替代旧 scripts/e0001.py：把游戏窗口挪到屏幕左上角，减少坐标偏差
        from config import coordinates as coords

        controller.refresh_window()
        controller.window.move_to_corner(*coords.WINDOW_DRAG_TARGET)

    flow_class = get_flow_class(name)
    kwargs = {}
    if args.times is not None:
        kwargs[_TIMES_KWARG[name]] = args.times
    if name == "explore":
        kwargs["exp_only"] = args.exp_only
    if name == "awake":
        kwargs["dungeon"] = args.dungeon
    return flow_class(controller=controller, **kwargs)


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if args.debug:
        import logging

        logging.getLogger().setLevel(logging.DEBUG)

    if args.list:
        print_flows()
        return 0
    if args.states:
        print_states()
        return 0
    if args.check:
        return run_check()
    if not args.feature:
        print_flows()
        return 2

    try:
        flow = build_flow(args.feature, args)
    except YysError as exc:
        log.error("%s", exc)
        return 1

    try:
        flow.execute()
    except StaminaExhaustedError as exc:
        log.error("%s", exc)
        return settings.EXIT_CODE_ABORT
    except YysError as exc:
        log.error("流程异常终止: %s", exc)
        return 1
    except KeyboardInterrupt:
        log.warning("用户中断")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())

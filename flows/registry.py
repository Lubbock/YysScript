"""流程注册表：命令行名字 -> Flow 类。

导入是惰性的，`main.py --list` 不需要安装 pyautogui 也能列出功能清单。
"""
from __future__ import annotations

from typing import Dict, List, Tuple, Type

#: name -> (模块路径, 类名, 说明)
FLOW_SPECS: Dict[str, Tuple[str, str, str]] = {
    "explore": ("flows.explore.explore_flow", "ExploreFlow", "自动探索（扫怪 / 换狗粮 / 领 Boss 奖励）"),
    "soul": ("flows.soul.soul_flow", "SoulFlow", "自动御魂"),
    "shard": ("flows.shard.shard_flow", "ShardFlow", "自动式神碎片（挑战循环，支持 iOS 镜像；--shard-mode chapter 走章节入口导航）"),
    "awake": ("flows.awake.awake_flow", "AwakeFlow", "自动觉醒材料"),
    "breakthrough": ("flows.breakthrough.breakthrough_flow", "BreakthroughFlow", "自动结界突破"),
    "seal": ("flows.seal.seal_flow", "SealFlow", "自动妖气封印（组队刷）"),
    "heart": ("flows.heart_dojo.heart_flow", "HeartDojoFlow", "自动御心道场"),
    "event-aband3t": ("flows.events.aband3t_flow", "Aband3tFlow", "活动事件 Aband3t 循环"),
    "event-aj8fer": ("flows.events.aj8fer_flow", "Aj8ferFlow", "活动事件 Aj8fer 循环（带耗时预测）"),
}


def list_flows() -> List[Tuple[str, str]]:
    """返回 (name, description) 列表。"""
    return [(name, spec[2]) for name, spec in sorted(FLOW_SPECS.items())]


def get_flow_class(name: str) -> Type:
    """按名字加载 Flow 类。"""
    import importlib

    from core.errors import ConfigError

    try:
        module_path, class_name, _ = FLOW_SPECS[name]
    except KeyError:
        raise ConfigError(
            "未知流程: {}（可用: {}）".format(name, ", ".join(sorted(FLOW_SPECS)))
        )
    module = importlib.import_module(module_path)
    return getattr(module, class_name)

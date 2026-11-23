"""状态注册表测试：一状态一文件、key 唯一、模板图片真实存在。"""
import importlib
import pkgutil
from pathlib import Path

import states
from config import settings
from states.base import REGISTRY, State, StateKind, all_states, get_state


def state_files():
    package_dir = Path(states.__file__).parent
    for info in pkgutil.iter_modules([str(package_dir)]):
        if info.name.startswith("_") or info.name in {"base", "machine"}:
            continue
        yield info.name


def test_every_state_file_defines_exactly_one_state():
    """约定：每个状态文件里只有一个 State 常量，且常量名 = 文件名大写。"""
    for name in state_files():
        module = importlib.import_module("states.{}".format(name))
        defined = [
            (const_name, value) for const_name, value in vars(module).items()
            if isinstance(value, State) and const_name.isupper()
        ]
        assert len(defined) == 1, \
            "{} 应该只定义一个 State 常量，实际 {} 个".format(name, len(defined))
        const_name, state = defined[0]
        assert state.key == const_name, \
            "{} 的常量名应与 key 一致: {} != {}".format(name, const_name, state.key)
        assert state.key.lower() == name, \
            "{} 的 key 应与文件名一致，实际 {}".format(name, state.key)


def test_registry_complete_and_unique():
    """注册表覆盖全部状态文件，且 key 不重复。"""
    files = set(state_files())
    assert len(REGISTRY) == len(files)
    keys = [state.key for state in REGISTRY.values()]
    assert len(keys) == len(set(keys))


def test_all_templates_exist_on_disk():
    """每个状态引用的模板图片都必须真实存在（防止中文文件名写错）。"""
    missing = []
    for state in all_states():
        for template in state.templates:
            if not (settings.TEMPLATE_DIR / template).exists():
                missing.append("{} -> {}".format(state.key, template))
    assert not missing, "缺失模板图片: {}".format(missing)


def test_templates_are_all_used():
    """模板目录里的图片都应被某个状态引用，避免遗漏迁移。"""
    used = {t for state in all_states() for t in state.templates}
    on_disk = {p.name for p in settings.TEMPLATE_DIR.glob("*.png")}
    unused = on_disk - used
    # scc.png 是旧脚本里注释掉的调试截图，不作为状态
    assert unused <= {"scc.png"}, "有模板未被任何状态引用: {}".format(sorted(unused))


def test_kind_classification():
    screens = all_states(StateKind.SCREEN)
    markers = all_states(StateKind.MARKER)
    assert screens and markers
    assert len(screens) + len(markers) == len(REGISTRY)
    assert all(s.is_screen for s in screens)
    assert not any(m.is_screen for m in markers)


def test_thresholds_in_valid_range():
    for state in all_states():
        assert 0 < state.threshold <= 1.0, "{} 阈值非法".format(state.key)


def test_get_state_and_str():
    assert get_state("HOME").label == "游戏首页"
    assert "HOME" in str(get_state("HOME"))


def test_get_state_unknown_raises():
    from core.errors import ConfigError

    try:
        get_state("NOT_EXIST")
    except ConfigError:
        pass
    else:  # pragma: no cover
        raise AssertionError("未知状态应抛 ConfigError")

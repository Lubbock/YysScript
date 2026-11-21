"""式神碎片入口面板（「章节入口」模式第二步）。"""
from states.base import State, StateKind

SHARD_FRAGMENT_ENTRY = State(
    key="SHARD_FRAGMENT_ENTRY",
    label="碎片入口面板",
    templates=("碎片入口面板.png",),
    kind=StateKind.MARKER,
    description="点完章节头像后弹出的「式神碎片」面板（带「挑战」页签）；"
                "命中即点击，进入碎片列表",
    # 阈值 0.85 而不是默认 0.7：这张模板是从外部截图裁的，比例约为当前镜像窗口的 2 倍，
    # 在尺度 1.0 上根本对不上（章节界面实测 0.479）。尺度收紧后它在**挑战界面**仍有
    # 0.79（x0.8~x0.9 的缩小匹配），照 0.7 就会在挑战界面上乱点面板位置。
    # TODO: 用 tools/asset_manager 从实时窗口重截这张模板，之后阈值可以回到 0.7。
    threshold=0.85,
)

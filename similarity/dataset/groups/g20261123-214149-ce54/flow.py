"""分组「雷麒麟」的执行顺序。

本文件按截图采集时间自动生成了链式顺序（一步接一步，跑完回到第 1 步），
请照着实际的游戏流程调整 steps 的顺序与超时。

step(target, click=None, shot=None, timeout=None, interval=None,
     blind_wait=None, settle=None, optional=False, on_match=None, on_timeout=None)
  target     期望出现的界面：标注名 / 截图备注 / 截图 id
  click      命中后点哪个标注，默认与 target 同名
  timeout    这一步最多等多少秒（默认 120）
  blind_wait 强制盲等秒数，覆盖自适应等待
  optional   True 时等不到就跳过，不算失败
"""

name = "雷麒麟"
round_timeout = 900

steps = [
    step("挑战"),  # 20261123-223014-602086
    step("完成"),  # 20261123-225335-876760
]


def on_step_timeout(ctx, st):
    """超时兜底：返回 True 表示已自愈，继续下一步。"""
    ctx.log.warning("步骤 %s 等不到，中止本轮", st.name)
    return False

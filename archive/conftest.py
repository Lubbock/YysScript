"""归档区：本目录下的测试一律不收集。

pytest.ini 已把 archive 列进 norecursedirs，这里再加一道保险，
这样即使有人显式 `pytest archive/` 也不会因为旧代码的依赖已移走而炸一片。
"""
collect_ignore_glob = ["*"]

"""数据采集与模型判定。

截屏 -> Web 标注 -> 分组落盘（`dataset/groups/<key>/`，每组可带 `flow.py` DSL）；
双图判定走本地 Ollama 多模态模型（`llm_judge.py`），不做 OpenCV 像素比对。
"""

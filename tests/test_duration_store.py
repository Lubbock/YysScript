"""存储层测试：耗时样本的写入、均值、裁剪（修掉旧 SqlScan 的 bug）。"""
import pytest

from storage.database import Database
from storage.duration_store import DurationStore


@pytest.fixture()
def store(tmp_path):
    return DurationStore(database=Database(tmp_path / "test.db"))


def test_average_is_none_without_samples(store):
    assert store.average("nothing") is None


def test_record_and_average(store):
    store.record("battle", 10)
    store.record("battle", 20)
    store.record("battle", 30)
    assert store.average("battle") == pytest.approx(20.0)
    assert store.count("battle") == 3


def test_samples_keep_insertion_order(store):
    for value in (5, 3, 9):
        store.record("k", value)
    assert store.samples("k") == [5.0, 3.0, 9.0]


def test_keys_are_isolated(store):
    store.record("a", 10)
    store.record("b", 99)
    assert store.average("a") == pytest.approx(10.0)
    assert store.average("b") == pytest.approx(99.0)
    assert store.count("a") == 1


def test_trim_keeps_most_recent(store):
    """旧代码 clear_kw(500) 少传参数必然 TypeError，这里验证裁剪真正生效。"""
    for value in range(10):
        store.record("k", value)
    deleted = store.trim("k", keep=4)
    assert deleted == 6
    assert store.samples("k") == [6.0, 7.0, 8.0, 9.0]


def test_trim_does_not_touch_other_keys(store):
    store.record("keep", 1)
    for value in range(5):
        store.record("trim", value)
    store.trim("trim", keep=2)
    assert store.count("keep") == 1


def test_auto_trim_when_over_limit(store, monkeypatch):
    """超过样本上限时自动裁剪，且新样本仍会写入（旧代码此处直接 return 丢数据）。"""
    from config import settings

    monkeypatch.setattr(settings, "DURATION_SAMPLE_LIMIT", 5)
    monkeypatch.setattr(settings, "DURATION_SAMPLE_KEEP", 2)
    for value in range(8):
        store.record("k", value)
    # 第 6 条写入后触发裁剪（保留最近 2 条 4、5），随后 6、7 正常写入
    assert store.samples("k") == [4.0, 5.0, 6.0, 7.0]
    assert store.count("k") == 4


def test_clear(store):
    store.record("k", 1)
    store.record("k", 2)
    assert store.clear("k") == 2
    assert store.count("k") == 0


def test_sql_injection_is_escaped(store):
    """参数化查询：恶意 key 不应破坏 SQL。"""
    evil = 'x"; DROP TABLE GAMETIME_RECORD; --'
    store.record(evil, 1)
    assert store.average(evil) == pytest.approx(1.0)
    store.record("normal", 2)
    assert store.average("normal") == pytest.approx(2.0)


def test_float_seconds_supported(store):
    store.record("k", 1.5)
    assert store.average("k") == pytest.approx(1.5)


def test_database_creates_parent_dir(tmp_path):
    db = Database(tmp_path / "nested" / "dir" / "x.db")
    with db.connect() as conn:
        conn.execute("SELECT 1")
    assert (tmp_path / "nested" / "dir" / "x.db").exists()


def test_keys_lists_distinct_sorted(store):
    store.record("soul:round", 1)
    store.record("soul:battle", 2)
    store.record("soul:round", 3)
    store.record("shard:round", 4)
    assert store.keys() == ["shard:round", "soul:battle", "soul:round"]


def test_keys_prefix_filter(store):
    store.record("soul:round", 1)
    store.record("soul:battle", 2)
    store.record("shard:round", 3)
    assert store.keys("soul:") == ["soul:battle", "soul:round"]
    assert store.keys("nothing:") == []


def test_keys_on_empty_store(store):
    assert store.keys() == []
    assert store.keys("soul:") == []


def test_keys_escapes_like_wildcards(store):
    """key 里的 % / _ 不能被当成 LIKE 通配符。"""
    store.record("a_b", 1)
    store.record("axb", 2)
    store.record("a%b", 3)
    assert store.keys("a_") == ["a_b"]
    assert store.keys("a%") == ["a%b"]

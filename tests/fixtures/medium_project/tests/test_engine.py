"""Tests for the core engine."""

from src.core import Engine


def test_engine_process():
    engine = Engine("hello\nworld")
    assert engine.process() == ["hello", "world"]


def test_engine_get_results():
    engine = Engine("test")
    engine.process()
    results = engine.get_results()
    assert results == ["test"]
    assert results is not engine._results  # should be a copy

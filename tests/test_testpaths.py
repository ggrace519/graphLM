"""Tests for the shared test-path predicate (``graphlm.testpaths.is_test_path``)."""

from __future__ import annotations

import pytest

from graphlm.testpaths import is_test_path


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_foo.py",
        "tests/fixtures/rust_project/src/bar.rs",
        "test/foo.py",
        "__tests__/foo.js",
        "pkg/__tests__/foo.js",
        "src/test/java/com/acme/AppTest.java",
        "test_foo.py",
        "foo_test.py",
        "foo.test.js",
        "foo.spec.ts",
        "test.py",  # bare "test" stem
        "a/b/tests/c.py",  # tests/ anywhere in the path
        "TESTS/Foo.py",  # case-insensitive
    ],
)
def test_recognised_as_test(path: str) -> None:
    assert is_test_path(path) is True


@pytest.mark.parametrize(
    "path",
    [
        "latest.py",  # merely contains "test"
        "contest.py",
        "testing.py",  # not test_ / _test / test
        "graphlm/scanner.py",
        "src/main/App.java",
        "attestation.py",
        "protest/rally.py",  # "protest" dir is not a test dir
    ],
)
def test_not_a_test(path: str) -> None:
    assert is_test_path(path) is False


def test_backslashes_folded() -> None:
    # Windows-style separators are normalised before matching.
    assert is_test_path(r"tests\fixtures\foo.py") is True
    assert is_test_path(r"src\main\App.java") is False

"""Tests for akaidoo.native_methods_index module."""

import pytest
from akaidoo.native_methods_index import get_native_methods, is_native_method


class TestGetNativeMethods:
    def test_known_version_returns_methods(self):
        """Loading a known version should return a non-empty set."""
        methods = get_native_methods("18.0")
        assert isinstance(methods, set)
        assert len(methods) > 0

    def test_known_versions_all_have_methods(self):
        """All supported versions should have methods."""
        for version in ["16.0", "17.0", "18.0", "19.0"]:
            methods = get_native_methods(version)
            assert len(methods) > 0, f"Version {version} should have native methods"

    def test_unknown_version_returns_empty(self):
        """An unknown version should return an empty set."""
        methods = get_native_methods("99.0")
        assert methods == set()

    def test_caching(self):
        """Repeated calls should return the same set (cached)."""
        m1 = get_native_methods("18.0")
        m2 = get_native_methods("18.0")
        assert m1 == m2  # Set equality, not identity (copy is returned)


class TestIsNativeMethod:
    def test_known_method(self):
        """A known method should be identified as native."""
        methods = get_native_methods("18.0")
        if methods:
            method = next(iter(methods))
            assert is_native_method("18.0", method) is True

    def test_unknown_method(self):
        """An unknown method should not be native."""
        assert is_native_method("18.0", "nonexistent_method_xyz") is False

    def test_unknown_version(self):
        """An unknown version should return False for any method."""
        assert is_native_method("99.0", "any_method") is False

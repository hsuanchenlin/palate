"""Shared pytest fixtures.

Disables the on-disk Places cache for every test by default so respx-mocked
HTTP paths actually run. Tests that want to exercise cache behavior create a
real PlacesCache against tmp_path and call cache.set_default() themselves.
"""

import pytest

from palate import cache as _cache_mod


@pytest.fixture(autouse=True)
def _disable_places_cache(tmp_path):
    original = _cache_mod._DEFAULT
    _cache_mod._DEFAULT = _cache_mod.PlacesCache(
        path=tmp_path / "disabled.sqlite3", disabled=True
    )
    yield
    _cache_mod._DEFAULT = original

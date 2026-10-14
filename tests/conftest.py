import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "heavy_pool: runs the real heavy-recompute worker process")
    config.addinivalue_line("markers", "auth: the test exercises the real authentication (the default for all other tests is XAU_AUTH=off)")


@pytest.fixture(autouse=True)
def _auth_off_unless_marked(request, monkeypatch):
    """The gateway's authentication is ON by default. Existing tests exercise other behaviour through the app object, so they run with it off;
    tests marked `auth` (tests/unit/test_auth.py) turn it on explicitly and use a temporary token file."""
    if request.node.get_closest_marker("heavy_pool") is None:
        monkeypatch.setenv("XAU_HEAVY_INPROC", "1")                        # tests monkeypatch compute_heavy in-process; test_heavy_pool.py exercises the real pool
    if request.node.get_closest_marker("auth") is None:
        monkeypatch.setenv("XAU_AUTH", "off")
    else:
        monkeypatch.delenv("XAU_AUTH", raising=False)
        monkeypatch.delenv("XAU_API_TOKEN", raising=False)
        monkeypatch.delenv("XAU_ALLOWED_HOSTS", raising=False)

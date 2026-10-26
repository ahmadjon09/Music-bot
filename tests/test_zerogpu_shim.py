"""The ZeroGPU shim must exist yet stay completely inert off ZeroGPU."""

import pytest

pytest.importorskip("spaces")


def test_warmup_registered_and_callable():
    import app as app_module

    assert callable(app_module._zerogpu_warmup)
    # Off ZeroGPU the decorator is a pass-through.
    assert app_module._zerogpu_warmup() == "ok"


def test_startup_report_is_safe_noop_off_zerogpu():
    import app as app_module

    app_module._report_zerogpu_startup()  # must not raise on plain CPU

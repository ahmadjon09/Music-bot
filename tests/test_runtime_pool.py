"""Runtime proxy modes: auto pool vs manual pinning + persistence."""

import asyncio
from pathlib import Path

from src.config import Settings
from src.db import Database
from src.runtime import Runtime


def _run(tmp_path: Path, scenario) -> None:
    async def wrapped():
        db = Database(tmp_path / "bot.db")
        await db.open()
        try:
            await scenario(db)
        finally:
            await db.close()

    asyncio.run(wrapped())


def test_auto_mode_uses_pool_manual_mode_pins(tmp_path: Path):
    async def scenario(db):
        runtime = Runtime(settings=Settings(), db=db)
        await runtime.load()
        assert runtime.proxy_mode == "auto"
        assert runtime.proxy_candidates() == []

        runtime.pool.set_healthy(["http://1.1.1.1:8080", "http://2.2.2.2:8080"])
        picked = runtime.proxy_candidates(2)
        assert set(picked) == {"http://1.1.1.1:8080", "http://2.2.2.2:8080"}

        await runtime.set_proxies("socks5://9.9.9.9:1080")
        assert runtime.proxy_mode == "manual"
        assert runtime.proxy_candidates(3) == ["socks5://9.9.9.9:1080"]
        assert runtime.pick_proxy() == "socks5://9.9.9.9:1080"

        await runtime.clear_proxies()
        assert runtime.proxy_mode == "auto"
        assert set(runtime.proxy_candidates(2)) == {"http://1.1.1.1:8080", "http://2.2.2.2:8080"}

    _run(tmp_path, scenario)


def test_pool_cache_survives_restart(tmp_path: Path):
    async def scenario(db):
        runtime = Runtime(settings=Settings(), db=db)
        await runtime.load()
        runtime.pool.set_healthy(["http://5.5.5.5:3128"])
        await runtime._persist_pool()

        restarted = Runtime(settings=Settings(), db=db)
        await restarted.load()
        assert restarted.pool.healthy_urls() == ["http://5.5.5.5:3128"]
        assert restarted.proxy_candidates(1) == ["http://5.5.5.5:3128"]

    _run(tmp_path, scenario)


def test_pool_stats_shape(tmp_path: Path):
    async def scenario(db):
        runtime = Runtime(settings=Settings(), db=db)
        await runtime.load()
        stats = runtime.pool_stats()
        assert stats["mode"] == "auto"
        assert stats["healthy"] == 0
        assert stats["auto_enabled"] is True
        assert "auto pool" not in runtime.proxy_label()  # nothing verified yet

    _run(tmp_path, scenario)

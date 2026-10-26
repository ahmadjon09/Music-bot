"""Auto proxy pool: ranking, cooldowns, scan waves (offline, faked probes)."""

import asyncio

from src.proxypool import ProxyPool


def test_candidates_ranking_and_limit():
    pool = ProxyPool(target_size=12)
    urls = [f"http://10.0.0.{i}:8080" for i in range(1, 9)]
    pool.set_healthy(urls)
    picked = pool.candidates(3)
    assert len(picked) == 3
    assert set(picked) <= set(urls)
    # healthy_urls is fastest-first (set_healthy assigns rising latency)
    assert pool.healthy_urls() == urls


def test_failure_cooldown_and_recovery():
    pool = ProxyPool()
    pool.set_healthy(["http://10.0.0.1:8080"])
    assert pool.candidates(1) == ["http://10.0.0.1:8080"]
    for _ in range(3):
        pool.report_failure("http://10.0.0.1:8080")
    assert pool.candidates(1) == []  # cooled down after repeated failures
    pool.report_success("http://10.0.0.1:8080")
    assert pool.candidates(1) == ["http://10.0.0.1:8080"]


def test_refresh_scans_top_down_and_ranks():
    pool = ProxyPool(target_size=2, concurrency=2, seeds=())
    candidates = [f"http://10.0.0.{i}:8080" for i in range(1, 7)]
    latencies = {candidates[0]: 300.0, candidates[2]: 120.0, candidates[4]: 50.0}

    async def fake_fetch():
        return candidates

    async def fake_test(url):
        return latencies.get(url)

    pool._fetch_candidates = fake_fetch  # type: ignore[method-assign]
    pool._test_one = fake_test  # type: ignore[method-assign]

    stats = asyncio.run(pool.refresh())
    assert stats["healthy"] >= 2
    assert stats["last_scanned"] >= 2
    ranked = pool.healthy_urls()
    assert ranked[0] in latencies
    # sorted by measured latency, fastest first
    assert [latencies[u] for u in ranked] == sorted(latencies[u] for u in ranked)
    assert ranked[0] == "http://10.0.0.5:8080" or ranked[0] == "http://10.0.0.3:8080"


def test_refresh_keeps_old_pool_when_scan_finds_nothing():
    pool = ProxyPool(target_size=2, concurrency=2, seeds=(), scan_limit=4)
    pool.set_healthy(["http://10.0.0.9:8080"])

    async def fake_fetch():
        return ["http://10.0.0.1:8080", "http://10.0.0.2:8080"]

    async def fake_test(url):
        return None  # everything dead — old pool must survive

    pool._fetch_candidates = fake_fetch  # type: ignore[method-assign]
    pool._test_one = fake_test  # type: ignore[method-assign]

    asyncio.run(pool.refresh())
    assert pool.healthy_urls() == ["http://10.0.0.9:8080"]


def test_stats_shape():
    pool = ProxyPool()
    pool.set_healthy(["socks5://user:secret@10.0.0.1:1080"])
    stats = pool.stats()
    assert stats["healthy"] == 1
    assert stats["top"][0]["proxy"] == "10.0.0.1:1080"  # credentials stripped

import unittest

from boxradar_site.cache import MetarCache
from boxradar_site.upstream import UpstreamError


class FakeClock:
    """Injected for both monotonic and wall-clock reads, so tests can move
    time without sleeping."""

    def __init__(self, t=1000.0):
        self.t = t

    def advance(self, dt):
        self.t += dt

    def __call__(self):
        return self.t


class FakeFetcher:
    def __init__(self):
        self.calls = []
        self.fail = False
        self.responses = {}

    def __call__(self, ids, timeout_s=20.0):
        self.calls.append(list(ids))
        if self.fail:
            raise UpstreamError("boom")
        return [self.responses[i] for i in ids if i in self.responses]


class CacheTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.fetcher = FakeFetcher()
        self.fetcher.responses = {
            "EGSS": {"icaoId": "EGSS", "wspd": 12},
            "EGGW": {"icaoId": "EGGW", "wspd": 8},
        }
        self.cache = MetarCache(self.fetcher, ttl_s=300, error_backoff_s=60,
                                monotonic=self.clock, wallclock=self.clock)


class TestFreshFetch(CacheTest):
    def test_first_call_fetches(self):
        obs, at, stale = self.cache.get(["EGSS"])
        self.assertEqual(self.fetcher.calls, [["EGSS"]])
        self.assertEqual(obs, [{"icaoId": "EGSS", "wspd": 12}])
        self.assertEqual(at, 1000)
        self.assertFalse(stale)

    def test_second_call_within_ttl_does_not_fetch(self):
        self.cache.get(["EGSS"])
        self.clock.advance(299)
        obs, _, stale = self.cache.get(["EGSS"])
        self.assertEqual(len(self.fetcher.calls), 1)
        self.assertEqual(len(obs), 1)
        self.assertFalse(stale)

    def test_call_after_ttl_refetches(self):
        self.cache.get(["EGSS"])
        self.clock.advance(301)
        self.cache.get(["EGSS"])
        self.assertEqual(len(self.fetcher.calls), 2)

    def test_ttl_bounds_upstream_calls_regardless_of_poll_rate(self):
        # A board polling every 60s for an hour must produce 12 calls, not 60.
        for _ in range(60):
            self.cache.get(["EGSS"])
            self.clock.advance(60)
        self.assertEqual(len(self.fetcher.calls), 12)


class TestBatching(CacheTest):
    def test_multiple_stations_are_one_upstream_call(self):
        self.cache.get(["EGSS", "EGGW"])
        self.assertEqual(self.fetcher.calls, [["EGSS", "EGGW"]])

    def test_only_expired_stations_are_refetched(self):
        self.cache.get(["EGSS"])
        self.clock.advance(100)
        self.cache.get(["EGSS", "EGGW"])
        # EGSS is still fresh, so only EGGW goes upstream.
        self.assertEqual(self.fetcher.calls, [["EGSS"], ["EGGW"]])

    def test_returns_every_station_it_holds(self):
        self.cache.get(["EGSS"])
        obs, _, _ = self.cache.get(["EGSS", "EGGW"])
        ids = sorted(o["icaoId"] for o in obs)
        self.assertEqual(ids, ["EGGW", "EGSS"])

    def test_oldest_entry_sets_the_timestamp(self):
        self.cache.get(["EGSS"])
        self.clock.advance(100)
        _, at, _ = self.cache.get(["EGSS", "EGGW"])
        self.assertEqual(at, 1000)  # EGSS's fetch time, not EGGW's


class TestUpstreamFailure(CacheTest):
    def test_failure_with_no_prior_data_returns_empty(self):
        self.fetcher.fail = True
        obs, at, stale = self.cache.get(["EGSS"])
        self.assertEqual(obs, [])
        self.assertEqual(at, 0)
        self.assertTrue(stale)

    def test_failure_serves_stale_data_flagged_stale(self):
        self.cache.get(["EGSS"])
        self.clock.advance(400)
        self.fetcher.fail = True
        obs, at, stale = self.cache.get(["EGSS"])
        self.assertEqual(obs, [{"icaoId": "EGSS", "wspd": 12}])
        self.assertEqual(at, 1000)
        self.assertTrue(stale)

    def test_backoff_suppresses_retries(self):
        self.fetcher.fail = True
        self.cache.get(["EGSS"])
        self.clock.advance(59)
        self.cache.get(["EGSS"])
        self.assertEqual(len(self.fetcher.calls), 1)

    def test_backoff_expires(self):
        self.fetcher.fail = True
        self.cache.get(["EGSS"])
        self.clock.advance(61)
        self.cache.get(["EGSS"])
        self.assertEqual(len(self.fetcher.calls), 2)

    def test_recovery_clears_stale(self):
        self.fetcher.fail = True
        self.cache.get(["EGSS"])
        self.clock.advance(61)
        self.fetcher.fail = False
        obs, at, stale = self.cache.get(["EGSS"])
        self.assertEqual(len(obs), 1)
        self.assertEqual(at, 1061)
        self.assertFalse(stale)


class TestMissingUpstreamStation(CacheTest):
    def test_station_the_api_does_not_know_is_not_cached_but_is_backed_off(self):
        # The API omits stations it has no observation for. Treat that as a
        # miss with backoff, so a typo'd ICAO cannot be polled at full rate.
        obs, _, stale = self.cache.get(["ZZZZ"])
        self.assertEqual(obs, [])
        self.assertTrue(stale)
        self.clock.advance(59)
        self.cache.get(["ZZZZ"])
        self.assertEqual(len(self.fetcher.calls), 1)


if __name__ == "__main__":
    unittest.main()

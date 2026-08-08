"""Run the site application.

    python3 -m boxradar_site --port 8081

Wiring only: argument parsing and construction. Everything testable lives in
the modules this imports.
"""

import argparse
import sys

from . import VERSION
from .cache import DEFAULT_ERROR_BACKOFF_S, DEFAULT_TTL_S, MetarCache
from .config import DEFAULT_PATH, load
from .server import make_server
from .upstream import fetch

DEFAULT_PORT = 8081


def main(argv=None):
    p = argparse.ArgumentParser(prog="boxradar-site")
    p.add_argument("--host", default="0.0.0.0",
                   help="bind address (default: all interfaces, LAN only)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--config", default=DEFAULT_PATH)
    p.add_argument("--ttl", type=int, default=DEFAULT_TTL_S,
                   help="seconds before a cached observation is refetched")
    p.add_argument("--backoff", type=int, default=DEFAULT_ERROR_BACKOFF_S,
                   help="seconds to wait after an upstream failure")
    p.add_argument("--version", action="version", version=VERSION)
    args = p.parse_args(argv)

    cfg = load(args.config)
    cache = MetarCache(fetch, ttl_s=args.ttl, error_backoff_s=args.backoff)
    httpd = make_server((args.host, args.port), cache, cfg)
    stations = ", ".join(sorted(cfg.runways)) or "none"
    print(f"boxradar-site {VERSION} on {args.host}:{args.port} "
          f"(ttl {args.ttl}s, runway tables: {stations})", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Run the configuration UI.

    python3 -m boxradar_config [--port 8082] [--host 0.0.0.0]

Flask's own server, not gunicorn. This is a single-user tool on a LAN that is
touched when a site is set up and otherwise idle, so a second dependency and a
second thing to configure would buy nothing. The service that has to stay up
under a board polling it every 60 seconds is boxradar-site, and that one is
stdlib http.server for the same reason.
"""

import argparse
import sys

from .app import create_app
from .settings import Settings


def main(argv=None):
    settings = Settings.from_env()
    p = argparse.ArgumentParser(prog="boxradar_config")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=settings.port)
    args = p.parse_args(argv)
    settings.port = args.port

    app = create_app(settings)
    print(f"boxradar-config {settings!r}", flush=True)
    app.run(host=args.host, port=args.port, threaded=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

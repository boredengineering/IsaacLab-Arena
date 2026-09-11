# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Launch one non-root local workbench API over a Unix socket only."""

import argparse
import signal
from contextlib import contextmanager
from pathlib import Path

import uvicorn

from .application import create_app
from .runtime import StateLease, UnixListener, validate_layout


class OwnedServer(uvicorn.Server):
    """Allow outer resource contexts to clean up before process exit on SIGTERM."""

    @contextmanager
    def capture_signals(self):
        # Uvicorn otherwise re-raises SIGTERM before the listener context can unlink its inode.
        previous = {sig: signal.signal(sig, self.handle_exit) for sig in (signal.SIGINT, signal.SIGTERM)}
        try:
            yield
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--origin", default="http://127.0.0.1:3000")
    parser.add_argument("--diagnostics", action="store_true", help="Enable test-only bounded diagnostic subprocesses")
    args = parser.parse_args()
    try:
        validate_layout(args.state_dir, args.socket)
        with StateLease(args.state_dir) as lease:
            app = create_app(args.state_dir, origin=args.origin, diagnostics=args.diagnostics, _state_lease=lease)
            with UnixListener(args.socket) as listener:
                config = uvicorn.Config(
                    app,
                    proxy_headers=False,
                    access_log=False,
                    lifespan="on",
                    timeout_graceful_shutdown=3,
                    server_header=False,
                )
                server = OwnedServer(config)
                server.run(sockets=[listener])
                if not server.started:
                    parser.exit(1, "Workbench API startup failed\n")
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(1, f"Workbench launch refused: {error}\n")


if __name__ == "__main__":
    main()

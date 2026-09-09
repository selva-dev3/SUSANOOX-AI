from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

from susanoox import __version__
from susanoox.app.application import run_application
from susanoox.config.paths import AppPaths
from susanoox.config.settings import CHAT_MODELS, load_settings
from susanoox.utils.errors import SusanooxError
from susanoox.utils.logging import configure_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="susanoox",
        description="Secure AI coding agent for the terminal.",
    )
    parser.add_argument("--version", action="version", version=f"Susanoox {__version__}")
    parser.add_argument("--model", choices=CHAT_MODELS, help="Chat model for this run.")
    parser.add_argument("--resume", metavar="SESSION", help="Resume a saved session.")
    parser.add_argument("--new", action="store_true", help="Start a new session.")
    parser.add_argument("--debug", action="store_true", help="Enable redacted debug logs.")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("config", help="Inspect or update configuration.")
    subparsers.add_parser("sessions", help="List saved sessions.")
    return parser


def _not_available(feature: str) -> NoReturn:
    print(f"{feature} will be available after session persistence is implemented.", file=sys.stderr)
    raise SystemExit(2)


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "config":
        _not_available("Configuration commands")
    if args.command == "sessions" or args.resume is not None:
        _not_available("Session management")

    try:
        settings = load_settings(
            project_path=Path.cwd(),
            model_override=args.model,
            debug=args.debug,
        )
        log_path = AppPaths.discover().log_dir / "susanoox.log"
        logging_available = configure_logging(log_path, debug=settings.debug)
        if not logging_available:
            print(
                "susanoox: warning: diagnostic logging is disabled because the log directory "
                "is not writable.",
                file=sys.stderr,
            )
        run_application(settings)
    except SusanooxError as error:
        parser.exit(1, f"susanoox: {error}\n")


if __name__ == "__main__":
    main()

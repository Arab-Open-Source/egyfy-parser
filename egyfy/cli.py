"""Command-line entry point for the local EgyFy Parser server."""

from __future__ import annotations

import argparse
import logging
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Sequence

from . import APP_NAME, APP_VERSION
from .engine import MAX_DPI, MAX_PAGE_LIMIT, MIN_DPI, Engine
from .server import create_handler


def _port(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def _threads(value: str) -> int:
    threads = int(value)
    if threads < 1:
        raise argparse.ArgumentTypeError("threads must be at least 1")
    return threads


def _dpi(value: str) -> float:
    dpi = float(value)
    if not MIN_DPI <= dpi <= MAX_DPI:
        raise argparse.ArgumentTypeError(
            f"dpi must be between {MIN_DPI:.0f} and {MAX_DPI:.0f}"
        )
    return dpi


def _page_limit(value: str) -> int:
    pages = int(value)
    if not 0 <= pages <= MAX_PAGE_LIMIT:
        raise argparse.ArgumentTypeError(
            f"max pages must be between 0 and {MAX_PAGE_LIMIT}"
        )
    return pages


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="egyfy-parser",
        description=f"{APP_NAME}: a local web interface for Indra OCR.",
    )
    parser.add_argument("--version", action="version", version=APP_VERSION)
    parser.add_argument("--host", default="127.0.0.1", help="bind address")
    parser.add_argument("--port", type=_port, default=8770, help="HTTP port")
    parser.add_argument(
        "--threads",
        type=_threads,
        default=4,
        help="ONNX Runtime worker threads per model",
    )
    parser.add_argument(
        "--dpi",
        type=_dpi,
        default=200.0,
        help="default PDF render resolution",
    )
    parser.add_argument(
        "--max-pages",
        type=_page_limit,
        default=20,
        help="default page limit; 0 processes all pages",
    )
    parser.add_argument(
        "--model-dir",
        default=None,
        help="local Indra model directory (overrides INDRA_OCR_MODEL_DIR)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    static_dir = Path(__file__).resolve().parent.parent / "static"
    engine = Engine(args.model_dir, args.threads, args.dpi, args.max_pages)
    server = ThreadingHTTPServer(
        (args.host, args.port), create_handler(engine, static_dir)
    )

    display_host = "localhost" if args.host in ("0.0.0.0", "127.0.0.1", "::1") else args.host
    print(f"{APP_NAME} {APP_VERSION}")
    print(f"Listening on http://{display_host}:{args.port}  ({args.threads} threads)")
    if args.host == "0.0.0.0":
        print("Warning: the API has no authentication. Use a trusted network only.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        server.server_close()
        engine.close()


if __name__ == "__main__":
    main()

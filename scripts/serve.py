"""Development static server. This is not a production backend."""
import argparse
import functools
import http.server
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    http.server.SimpleHTTPRequestHandler.extensions_map.update({".js": "text/javascript", ".mjs": "text/javascript", ".wasm": "application/wasm"})
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT / "web"))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"Nexus Archive: http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

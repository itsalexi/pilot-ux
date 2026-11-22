import functools
import http.server
import threading
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def site_url():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(FIX / "site"))
    handler.log_message = lambda *a, **k: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_port}/index.html"
    srv.shutdown()

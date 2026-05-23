import importlib.util
import os
import tempfile
import threading
import types
from contextlib import contextmanager
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = REPO_ROOT / "scripts" / "ollama-web-chat.py"


def _load_app_module(module_name: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, APP_PATH)
    if not spec or not spec.loader:
        raise RuntimeError("Failed to create import spec for ollama-web-chat.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def running_server(host: str = "127.0.0.1", api_key: str = "", extra_env: dict | None = None):
    with tempfile.TemporaryDirectory(prefix="ollama-librarian-routes-") as td:
        state_dir = Path(td)
        env_keys = {
            "OLLAMA_WEB_HOST": host,
            "OLLAMA_WEB_PORT": "8088",
            "OLLAMA_WEB_API_KEY": api_key,
            "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
            "OLLAMA_WEB_HISTORY_PATH": str(state_dir / "history.json"),
            "OLLAMA_WEB_STASH_PATH": str(state_dir / "stash.json"),
            "OLLAMA_WEB_PDF_INDEX_DB": str(state_dir / "pdf-rag.sqlite"),
            "OLLAMA_WEB_PDF_SOURCE": str(state_dir / "library"),
        }
        if extra_env:
            env_keys.update(extra_env)

        previous = {k: os.environ.get(k) for k in env_keys}
        os.environ.update(env_keys)

        server = None
        thread = None
        try:
            module_name = f"ollama_web_chat_routes_{os.getpid()}_{id(state_dir)}"
            app = _load_app_module(module_name)

            server = app.ThreadingHTTPServer((app.HOST, 0), app.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            bound_host, bound_port = server.server_address[0], server.server_address[1]
            base_url = f"http://{bound_host}:{bound_port}"
            yield app, base_url
        finally:
            if server is not None:
                server.shutdown()
                server.server_close()
            if thread is not None:
                thread.join(timeout=2)
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

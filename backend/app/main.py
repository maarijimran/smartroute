"""SmartRoute gateway application."""

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .api import analytics, auth, chat, documents, openai_compat, policy, registry
from .bootstrap import bootstrap
from .config import get_settings
from .core.privacy.scanner import get_scanner
from .core.retention import run_retention
from .db import create_all, session_scope

log = logging.getLogger("smartroute")
RETENTION_INTERVAL_S = 600


def _retention_loop(stop: threading.Event) -> None:
    while not stop.wait(RETENTION_INTERVAL_S):
        try:
            with session_scope() as db:
                run_retention(db)
        except Exception:
            log.exception("retention job failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings.validate_for_startup()
    create_all()
    with session_scope() as db:
        bootstrap(db)
    try:
        get_scanner().warm_up()
    except Exception:
        # Requests stay safe either way: a detector that cannot load makes every scan
        # fail, which blocks cloud dispatch. In production this is a misconfiguration.
        log.exception("privacy detectors failed to load; cloud dispatch will be blocked")
        if settings.is_production:
            raise
    stop = threading.Event()
    threading.Thread(target=_retention_loop, args=(stop,), daemon=True, name="retention").start()
    yield
    stop.set()


app = FastAPI(
    title="SmartRoute",
    version=__version__,
    description="Privacy-constrained contextual-bandit routing for hybrid local and cloud LLMs.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-SmartRoute-Event-Id", "X-SmartRoute-Model"],
)
for module in (auth, policy, registry, documents, chat, analytics, openai_compat):
    app.include_router(module.router)


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok", "version": __version__, "env": get_settings().env}

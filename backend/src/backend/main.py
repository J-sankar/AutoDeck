"""AutoDeck control-plane API."""

import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.registry import run_telemetry_setup
from backend.relay import publish

logger = logging.getLogger(__name__)
backend_logger = logging.getLogger("backend")
backend_logger.setLevel(logging.INFO)
if not backend_logger.handlers:
    backend_handler = logging.StreamHandler()
    backend_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s")
    )
    backend_logger.addHandler(backend_handler)
backend_logger.propagate = False

app = FastAPI(title="AutoDeck Control Plane")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def health() -> dict[str, str]:
    return {"service": "control-plane", "status": "healthy"}


@app.post("/registry/telemetry/setup")
def setup_telemetry() -> dict[str, object]:
    logger.info("Telemetry setup request received")
    try:
        logger.info("Telemetry setup started manifest-driven planning")
        result = run_telemetry_setup()
        logger.info(
            "Telemetry plan completed provider=%s targets=%s applied_files=%s restart_required=%s",
            result["provider"],
            len(result["targets"]),
            len(result["applied_files"]),
            result["restart_required"],
        )
    except (OSError, RuntimeError, ValueError) as error:
        logger.exception(
            "Telemetry setup failed error_type=%s",
            error.__class__.__name__,
        )
        publish(
            type="telemetry_setup_failed",
            service="registry",
            status="failed",
            message="Telemetry setup failed.",
            metadata={"error_type": error.__class__.__name__},
        )
        raise HTTPException(status_code=400, detail=str(error)) from error

    for target in result["targets"]:
        logger.info(
            "Telemetry target registered service=%s function=%s operation=%s dependency_count=%s",
            target["service"],
            target["function"],
            target["operation"],
            len(target["targets"]),
        )
        publish(
            type="service_registered",
            service=target["service"],
            status="registered",
            message="Service telemetry target registered.",
            metadata={"operation": target["operation"], "targets": target["targets"]},
        )
    publish(
        type="telemetry_setup_completed",
        service="registry",
        status="completed",
        message="Manifest-driven telemetry setup completed.",
        metadata={"provider": result["provider"], "applied_files": result["applied_files"]},
    )
    logger.info("Telemetry setup request completed status=%s", result["status"])
    return result

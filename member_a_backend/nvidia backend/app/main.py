import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.openapi import install_openapi
from app.public import PublicApplication
from app.routes import api, health
from app.routes.application_interfaces import install_application_interfaces
from app.routes.application_tasks import install_application_tasks
from app.routes.gateway import GatewayProtocolError, execution_router, protocol_error_handler
from app.routes.gateway import router as gateway_router
from app.routes.session import install_browser_auth
from app.routes.workflow import router as workflow_router

settings = get_settings()
logging.basicConfig(
    level=settings.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s"
)

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "Modular FastAPI backend foundation for an NVIDIA project. "
        "NVIDIA services are not called without configured credentials."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(health.router)
app.include_router(api.router)
app.add_exception_handler(GatewayProtocolError, protocol_error_handler)
app.include_router(gateway_router)
app.include_router(workflow_router)

app.include_router(execution_router)
install_browser_auth(app)
install_application_tasks(app)
install_application_interfaces(app)
install_openapi(app)
public_app = PublicApplication(app)

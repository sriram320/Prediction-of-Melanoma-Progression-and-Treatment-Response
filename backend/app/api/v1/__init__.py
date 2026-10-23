from fastapi import APIRouter

from app.api.v1 import admin, auth, health, hospital

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(admin.router)
api_router.include_router(hospital.router)

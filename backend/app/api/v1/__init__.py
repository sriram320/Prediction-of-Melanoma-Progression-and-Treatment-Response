from fastapi import APIRouter

from app.api.v1 import admin, analysis, auth, files, health, hospital, me, patients, records

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(admin.router)
api_router.include_router(hospital.router)
api_router.include_router(patients.router)
api_router.include_router(records.router)
api_router.include_router(files.router)
api_router.include_router(analysis.router)
api_router.include_router(me.router)

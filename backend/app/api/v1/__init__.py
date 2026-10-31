from fastapi import APIRouter

from app.api.v1 import (admin, analysis, audit, auth, files, health, hospital, me, monitoring, patients, records,
                        reports, reviews)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(admin.router)
api_router.include_router(monitoring.router)  # before hospital/reports: owns /reports/subgroup-performance
api_router.include_router(hospital.router)
api_router.include_router(patients.router)
api_router.include_router(records.router)
api_router.include_router(files.router)
api_router.include_router(analysis.router)
api_router.include_router(reviews.router)
api_router.include_router(reports.router)
api_router.include_router(me.router)
api_router.include_router(audit.router)

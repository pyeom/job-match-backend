import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.v1 import auth, jobs, swipes, applications, users, companies, notifications, filters
from app.api.v1 import websocket, media, documents, ai

app = FastAPI(
    title="Job Match API",
    description="FastAPI + ML backend for job matching application",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(users.router, prefix="/api/v1/users", tags=["Users"])
app.include_router(jobs.router, prefix="/api/v1/jobs", tags=["Jobs"])  # Job seeker endpoints (discover, view)
app.include_router(companies.router, prefix="/api/v1/companies", tags=["Companies"])  # Company endpoints with nested job management
app.include_router(swipes.router, prefix="/api/v1/swipes", tags=["Swipes"])
app.include_router(notifications.router, prefix="/api/v1/notifications", tags=["Notifications"])  # User notifications
app.include_router(filters.router, prefix="/api/v1/filters", tags=["Filters"])  # Filter presets and suggestions
# Applications endpoints: both user-specific (RESTful) and legacy (backward compatibility)
app.include_router(applications.router, prefix="/api/v1/users", tags=["User Applications"])  # User-specific applications
app.include_router(applications.router, prefix="/api/v1/applications", tags=["Applications (Legacy)"], deprecated=True)
# Document management endpoints
app.include_router(documents.router, prefix="/api/v1/documents", tags=["Documents"])
# WebSocket endpoint for real-time notifications
app.include_router(websocket.router, tags=["WebSocket"])
# Media serving endpoint for avatars and other files
app.include_router(media.router, prefix="/api/v1/media", tags=["Media"])
# AI-powered features (match explanations, insights)
app.include_router(ai.router, prefix="/api/v1/ai", tags=["AI Features"])


@app.get("/healthz")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok", "version": "1.0.0"}


@app.get("/")
async def root():
    """Root endpoint"""
    return {"message": "Job Match API", "docs": "/docs"}
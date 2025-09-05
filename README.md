# Job Match Backend

FastAPI + ML backend for the Job Match application implementing embeddings-based job recommendation system with hybrid scoring.

## Project Overview

This backend powers a swipe-based job matching mobile application using machine learning to deliver personalized job recommendations. The system combines semantic embeddings with rule-based scoring to rank jobs for users based on their skills, preferences, and interaction history.

## Tech Stack

- **API Framework**: FastAPI + Pydantic v2
- **Database**: PostgreSQL with pgvector extension for vector similarity searches
- **ORM/Migrations**: SQLAlchemy 2.0 + Alembic
- **Authentication**: JWT (access + refresh token pattern)
- **ML/Embeddings**: sentence-transformers (all-MiniLM-L6-v2 or e5-small)
- **Vector Search**: pgvector for efficient similarity searches with re-ranking

## Database Schema

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                  DATABASE SCHEMA                                       │
└─────────────────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────┐    ┌─────────────────────────────────────┐
│            users                 │    │               companies              │
├──────────────────────────────────┤    ├─────────────────────────────────────┤
│ id                   UUID    PK  │    │ id                  UUID       PK   │
│ email                VARCHAR(255)│    │ name                VARCHAR(255)     │
│ password_hash        VARCHAR(255)│    │ description         TEXT             │
│ created_at           TIMESTAMP   │    │ logo_url            VARCHAR(500)     │
│ updated_at           TIMESTAMP   │    │ website             VARCHAR(255)     │
│ skills               VARCHAR[]   │    │ location            VARCHAR(255)     │
│ preferred_locations  VARCHAR[]   │    │ size                VARCHAR(50)      │
│ seniority            seniority_enum│    │ industry            VARCHAR(100)     │
│ profile_embedding    VECTOR(384) │    │ founded_year        INTEGER          │
│ headline             TEXT        │    │ is_active           BOOLEAN          │
│ company_id           UUID     FK │    │ created_at          TIMESTAMP        │
│ is_active            BOOLEAN     │    │ updated_at          TIMESTAMP        │
└──────────────────────────────────┘    └─────────────────────────────────────┘
              │                                               │
              │ (optional employee                            │ 
              │  relationship)                                │
              └───────────────────┐       ┌───────────────────┘
                                  │       │
                                  ▼       ▼
                        ┌──────────────────────────────────────────────────┐
                        │                  jobs                            │
                        ├──────────────────────────────────────────────────┤
                        │ id                   UUID            PK         │
                        │ title                VARCHAR(255)   NOT NULL    │
                        │ company_id           UUID           FK → companies│
                        │ location             VARCHAR(255)   NOT NULL    │
                        │ tags                 VARCHAR[]      NOT NULL    │
                        │ seniority            seniority_enum NOT NULL    │
                        │ description          TEXT           NOT NULL    │
                        │ salary_min           INTEGER                    │
                        │ salary_max           INTEGER                    │
                        │ remote               BOOLEAN        DEFAULT false│
                        │ created_at           TIMESTAMP      NOT NULL    │
                        │ updated_at           TIMESTAMP      NOT NULL    │
                        │ job_embedding        VECTOR(384)    NOT NULL    │
                        │ is_active            BOOLEAN        DEFAULT true │
                        └──────────────────────────────────────────────────┘
              │                                               │
              │                                               │
              └───────────────────┐       ┌───────────────────┘
                                  │       │
                                  ▼       ▼
                    ┌─────────────────────────────────────┐
                    │             swipes                  │
                    ├─────────────────────────────────────┤
                    │ id           UUID         PK        │
                    │ user_id      UUID         FK → users│
                    │ job_id       UUID         FK → jobs │
                    │ direction    swipe_direction NOT NULL│
                    │ created_at   TIMESTAMP     NOT NULL │
                    └─────────────────────────────────────┘
                                  │
                                  │ (RIGHT swipe creates application)
                                  ▼
                    ┌─────────────────────────────────────┐
                    │          applications               │
                    ├─────────────────────────────────────┤
                    │ id           UUID         PK        │
                    │ user_id      UUID         FK → users│
                    │ job_id       UUID         FK → jobs │
                    │ status       app_status   NOT NULL  │
                    │ created_at   TIMESTAMP    NOT NULL  │
                    │ updated_at   TIMESTAMP    NOT NULL  │
                    │ score_at_apply INTEGER              │
                    └─────────────────────────────────────┘

                    ┌─────────────────────────────────────┐
                    │          interactions               │
                    ├─────────────────────────────────────┤
                    │ id              UUID      PK        │
                    │ user_id         UUID      FK → users│
                    │ job_id          UUID      FK → jobs │
                    │ score_at_view   INTEGER   NOT NULL  │
                    │ action          swipe_direction     │
                    │ created_at      TIMESTAMP NOT NULL  │
                    │ view_duration   INTEGER             │
                    └─────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                     ENUMS                                              │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│ seniority_enum: 'ENTRY', 'JUNIOR', 'MID', 'SENIOR', 'LEAD', 'PRINCIPAL'                │
│ swipe_direction: 'LEFT', 'RIGHT'                                                        │
│ app_status: 'SUBMITTED', 'WAITING_FOR_REVIEW', 'HR_MEETING',                           │
│             'TECHNICAL_INTERVIEW', 'FINAL_INTERVIEW', 'HIRED', 'REJECTED'              │
└─────────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                    INDEXES                                             │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│ CREATE INDEX job_embedding_ivfflat ON jobs USING ivfflat                              │
│   (job_embedding vector_cosine_ops) WITH (lists = 100);                               │
│                                                                                         │
│ CREATE INDEX user_profile_embedding_ivfflat ON users USING ivfflat                     │
│   (profile_embedding vector_cosine_ops) WITH (lists = 100);                           │
│                                                                                         │
│ CREATE INDEX idx_swipes_user_job ON swipes (user_id, job_id);                         │
│ CREATE INDEX idx_applications_user ON applications (user_id);                         │
│ CREATE INDEX idx_jobs_active_created ON jobs (is_active, created_at DESC);            │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

## Quick Start

**Note**: This project now uses Docker Compose for the complete development environment. All commands should be run from the project root directory (`/home/puyon/projects/job-match/`).

### 1. Environment Setup

Copy and configure environment variables:
```bash
# From project root
cp .env.example .env
# Edit .env with your configuration if needed
```

### 2. Start the Full Stack

Build and start all services (database, backend, and optional Redis):
```bash
# From project root  
docker compose up --build
```

This will:
- Build the FastAPI backend image with all ML dependencies
- Start PostgreSQL with pgvector extension
- Run database migrations automatically
- Start the backend API with hot reload for development

### 3. Verify Installation

Check that all services are running:
```bash
# Check service status
docker compose ps

# View logs
docker compose logs backend
docker compose logs db

# Test the API
curl http://localhost:8000/healthz
```

The API will be available at:
- **API**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs
- **Database**: localhost:5432

### 4. Database Migrations

Run migrations to create tables:
```bash
alembic upgrade head
```

### 5. Start API Server

```bash
uvicorn app.main:app --reload
```

The API will be available at:
- **API**: http://localhost:8000
- **Interactive Docs**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## API Endpoints

### Authentication
- `POST /api/v1/auth/register` - User registration
- `POST /api/v1/auth/login` - User login  
- `POST /api/v1/auth/refresh` - Refresh access token

### User Profile
- `GET /api/v1/me` - Get current user profile
- `PATCH /api/v1/me` - Update user profile

### Jobs & Discovery
- `GET /api/v1/jobs/{job_id}` - Get specific job details
- `GET /api/v1/jobs/discover?limit=20&cursor=` - Get personalized job recommendations

### Swipes & Applications
- `POST /api/v1/swipes` - Record swipe action (RIGHT creates application)
- `GET /api/v1/applications` - Get user's job applications  
- `GET /api/v1/applications/{id}` - Get specific application details

## ML Scoring System

### Embedding Flow

1. **Job Creation**: Generate `job_embedding` from (title + company + tags + description)
2. **User Profile**: Create `profile_embedding` from (headline + skills + preferences)  
3. **Dynamic Updates**: After ≥5 RIGHT swipes, recalculate user embedding:
   - Combine base profile embedding (30%) + average of RIGHT-swiped job embeddings (70%)

### Hybrid Scoring Algorithm

Jobs are scored using a weighted combination (0-100 scale):

```
Score = 0.55 × embedding_similarity + 
        0.20 × skill_overlap + 
        0.10 × seniority_match + 
        0.10 × recency_decay + 
        0.05 × location_match
```

**Components:**
- **Embedding Similarity**: Cosine similarity between user and job embeddings
- **Skill Overlap**: `#common_skills / #job_required_skills`
- **Seniority Match**: 1.0 (exact), 0.5 (adjacent level), 0.0 (other)
- **Recency Decay**: `exp(-hours_since_posted / 72)`
- **Location Match**: 1.0 if job location in user's preferred locations

### Vector Search Query

```sql
SELECT job.*, profile_embedding <-> job_embedding as similarity_score
FROM jobs job
WHERE job.id NOT IN (
  SELECT job_id FROM swipes WHERE user_id = $user_id
)
AND job.is_active = true
ORDER BY profile_embedding <-> job_embedding
LIMIT 300;
-- Re-rank in memory with hybrid scoring, then paginate
```

### Discover API Response

```json
{
  "items": [
    {
      "id": "uuid",
      "title": "Senior Backend Engineer",
      "company": "TechCorp",
      "location": "Remote",
      "seniority": "SENIOR", 
      "score": 87,
      "tags": ["Python", "FastAPI", "PostgreSQL"]
    }
  ],
  "nextCursor": "base64_encoded_pagination_token",
  "hasMore": true
}
```

## Development Commands

All development commands should be run from the project root directory.

### Running the Stack
```bash
# Start all services with build
docker compose up --build

# Start in detached mode
docker compose up -d

# Stop all services
docker compose down

# Restart specific service
docker compose restart backend

# View service logs
docker compose logs -f backend
```

### Database Management
```bash
# Run migrations (done automatically on startup, but can be run manually)
docker compose exec backend alembic upgrade head

# Create new migration
docker compose exec backend alembic revision --autogenerate -m "Add new table"

# Rollback migration
docker compose exec backend alembic downgrade -1

# Access database directly
docker compose exec db psql -U jobmatch -d jobmatch
```

### Code Quality & Testing
```bash
# Format code (run in backend container)
docker compose exec backend black .

# Type checking  
docker compose exec backend mypy .

# Run tests
docker compose exec backend pytest

# Install development dependencies
docker compose exec backend pip install -r requirements-dev.txt
```

### Client Generation
```bash
# Generate TypeScript client types for frontend
docker compose exec backend bash -c "
  openapi-typescript http://localhost:8000/openapi.json \
  -o /tmp/api.d.ts && cp /tmp/api.d.ts /app/../job-match-frontend/src/types/api.d.ts
"
```

### Debugging & Development
```bash
# Access backend container shell
docker compose exec backend bash

# Run specific commands in backend
docker compose exec backend python -c "print('Hello from backend')"

# Monitor resource usage
docker compose top

# Clean up volumes (removes all data!)
docker compose down -v
```

### Alternative: Local Development (Legacy)
If you prefer running without Docker:
```bash
# Create virtual environment (from backend directory)
cd job-match-backend
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start only database with Docker
docker compose up -d db

# Run migrations
alembic upgrade head

# Start API locally
uvicorn app.main:app --reload --port 8000
```

## Key Features

### Embedding Updates
- **Synchronous**: Job embeddings generated on creation (<300ms)
- **Asynchronous**: User profile embeddings updated after interaction patterns
- **Batch Processing**: Ready for RQ/Celery integration for high-volume scenarios

### Performance Optimizations
- pgvector IVFFLAT indexes for fast similarity search
- Cursor-based pagination for stable feed ordering
- Embedding caching strategies
- Connection pooling for database efficiency

### Metrics & Analytics
- Click-through rates by score deciles
- Embedding similarity distributions  
- Feed generation latency tracking
- User interaction patterns for model improvement

## Evolution Roadmap

- **Phase 1 (Current)**: Rule-based + embedding similarity
- **Phase 2**: Logistic regression on interaction data
- **Phase 3**: Advanced re-ranking (LightFM/collaborative filtering)
- **Phase 4**: Contextual personalization (time-based, dynamic preferences)

## Environment Variables

Key environment variables in `.env`:

```bash
# Database
DATABASE_URL=postgresql+psycopg://jobmatch:jobmatch@localhost:5432/jobmatch

# JWT
JWT_SECRET=your-secret-key
ACCESS_TOKEN_EXPIRES=900  # 15 minutes
REFRESH_TOKEN_EXPIRES=604800  # 7 days

# ML
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
EMBEDDING_DIMENSION=384

# API
API_PORT=8000
API_HOST=0.0.0.0
DEBUG=true
```
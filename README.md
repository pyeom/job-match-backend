# Job Match Backend

FastAPI backend with ML-powered job recommendations using embeddings and hybrid scoring.

## Tech Stack

- **API**: FastAPI + Pydantic v2
- **Database**: PostgreSQL + pgvector extension
- **ORM/Migrations**: SQLAlchemy 2.0 + Alembic
- **Auth**: JWT (access + refresh tokens)
- **ML**: sentence-transformers (all-MiniLM-L6-v2)

## Database Schema

**Core Tables:**
- `users` - User profiles with skills, preferences, and profile_embedding (VECTOR)
- `companies` - Company information
- `jobs` - Job listings with job_embedding (VECTOR) for similarity search
- `swipes` - User swipe actions (LEFT/RIGHT)
- `applications` - Job applications (created on RIGHT swipe)
- `interactions` - Tracking data for ML model improvements

**Key Indexes:**
- pgvector IVFFLAT indexes on embeddings for fast similarity search
- Compound indexes on swipes and applications for query performance

## Quick Start

Using Docker Compose (from project root):

```bash
# Start all services
docker compose up --build

# Access API
curl http://localhost:8000/healthz

# View logs
docker compose logs -f backend
```

**Endpoints:**
- API: http://localhost:8000
- API Docs: http://localhost:8000/docs
- Database: localhost:5432

## Authentication

**JWT Token System:**
- Access tokens: 15 minutes (used for API requests)
- Refresh tokens: 7 days (used to get new access tokens)
- Token rotation on refresh for security
- Blacklist system prevents token reuse after logout

**Auth Endpoints:**
- `POST /api/v1/auth/register` - Create new user account
- `POST /api/v1/auth/login` - Login with email/password
- `POST /api/v1/auth/refresh` - Refresh expired access token
- `POST /api/v1/auth/logout` - Logout and invalidate tokens

## API Endpoints

**User Profile:**
- `GET /api/v1/users/{user_id}` - Get user profile
- `PATCH /api/v1/users/{user_id}` - Update user profile

**Jobs & Discovery:**
- `GET /api/v1/jobs/{job_id}` - Get specific job details
- `GET /api/v1/jobs/discover?limit=20&cursor=` - Get personalized job recommendations

**Swipes & Applications:**
- `POST /api/v1/swipes` - Record swipe action (RIGHT creates application)
- `GET /api/v1/applications` - Get user's job applications
- `GET /api/v1/applications/{id}` - Get specific application details

See http://localhost:8000/docs for full interactive API documentation.

## ML Scoring System

Jobs are scored using hybrid algorithm (0-100 scale):

```
Score = 0.55 × embedding_similarity +
        0.20 × skill_overlap +
        0.10 × seniority_match +
        0.10 × recency_decay +
        0.05 × location_match
```

**Embedding Updates:**
- Job embeddings generated on creation
- User profile embeddings updated after ≥5 RIGHT swipes
- Combines base profile (30%) + swipe history (70%)

## Development Commands

```bash
# Run services
docker compose up -d              # Start in background
docker compose down               # Stop all services
docker compose logs -f backend    # View logs

# Database migrations
docker compose exec backend alembic upgrade head
docker compose exec backend alembic revision --autogenerate -m "Description"

# Access containers
docker compose exec backend bash
docker compose exec db psql -U jobmatch -d jobmatch
```

## Environment Variables

Key variables in `.env`:

```bash
# Database
DATABASE_URL=postgresql+psycopg://jobmatch:jobmatch@db:5432/jobmatch

# JWT
JWT_SECRET=your-secret-key-change-in-production
ACCESS_TOKEN_EXPIRES=900        # 15 minutes
REFRESH_TOKEN_EXPIRES=604800    # 7 days

# ML
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
EMBEDDING_DIMENSION=384

# API
API_PORT=8000
DEBUG=true
```

## Security Notes

- **Production**: Generate strong JWT_SECRET with `openssl rand -hex 32`
- **HTTPS**: Always use HTTPS/TLS in production
- **Passwords**: Hashed with bcrypt (automatic salt generation)
- **Tokens**: Store securely (never in localStorage without encryption)
- **CORS**: Configure `ALLOWED_ORIGINS` to specific domains only

See API docs for error codes and status handling.

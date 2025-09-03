# Job Match Backend

FastAPI + ML backend for the Job Match application implementing embeddings-based job recommendation system.

## Setup

1. Create and activate virtual environment:
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables:
```bash
cp .env.example .env
# Edit .env with your configuration
```

4. Set up PostgreSQL with pgvector extension:
```bash
# Using Docker (recommended)
docker run --name jobmatch-db -e POSTGRES_USER=jobmatch -e POSTGRES_PASSWORD=jobmatch -e POSTGRES_DB=jobmatch -p 5432:5432 -d pgvector/pgvector:pg16
```

5. Run database migrations:
```bash
alembic upgrade head
```

6. Start the API server:
```bash
uvicorn app.main:app --reload
```

The API will be available at http://localhost:8000 with docs at http://localhost:8000/docs

## Architecture

### ML Scoring System

The backend implements a hybrid recommendation system combining:
- **Semantic similarity**: Using sentence-transformers embeddings (all-MiniLM-L6-v2)
- **Rule-based scoring**: Skills overlap, seniority matching, location preferences
- **Temporal decay**: Newer jobs get higher scores

### API Endpoints

#### Authentication
- `POST /api/v1/auth/register` - User registration
- `POST /api/v1/auth/login` - User login
- `POST /api/v1/auth/refresh` - Refresh access token

#### User Profile
- `GET /api/v1/me` - Get current user profile
- `PATCH /api/v1/me` - Update user profile

#### Jobs
- `GET /api/v1/jobs/{job_id}` - Get specific job
- `GET /api/v1/jobs/discover` - Get personalized job recommendations

#### Interactions
- `POST /api/v1/swipes` - Record swipe action (creates application if RIGHT)
- `GET /api/v1/applications` - Get user's applications
- `GET /api/v1/applications/{id}` - Get specific application

### Database Models

- **User**: Profile with skills, preferences, and profile embedding
- **Job**: Job postings with tags, requirements, and job embedding  
- **Swipe**: User swipe actions (LEFT/RIGHT)
- **Application**: Job applications created from RIGHT swipes
- **Interaction**: Detailed interaction data for ML improvements

### Scoring Formula

```
Score (0-100) = 0.55 * embedding_similarity + 
                0.20 * skill_overlap + 
                0.10 * seniority_match + 
                0.10 * recency_decay + 
                0.05 * location_match
```

## Development Commands

```bash
# Run with auto-reload
uvicorn app.main:app --reload

# Generate new migration
alembic revision --autogenerate -m "description"

# Run migrations
alembic upgrade head

# Generate TypeScript client types
openapi-typescript http://localhost:8000/openapi.json -o ../job-match-frontend/src/types/api.d.ts
```
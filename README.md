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

## Authentication Architecture

### JWT Token System

The application uses JSON Web Tokens (JWT) for stateless authentication with a dual-token approach for security and user convenience.

**Token Generation:**
- Algorithm: HS256 (HMAC with SHA-256)
- Secret Key: Configured via `JWT_SECRET` environment variable
- Token Structure:
  ```json
  {
    "sub": "user-uuid-here",      // Subject: user identifier
    "exp": 1234567890,             // Expiration timestamp
    "iat": 1234567890,             // Issued at timestamp
    "type": "access" | "refresh"   // Token type
  }
  ```

**Token Expiration Times:**
- **Access Token**: 900 seconds (15 minutes)
  - Short-lived for security
  - Used for all authenticated API requests
  - Automatically refreshed by client before expiration
- **Refresh Token**: 604800 seconds (7 days)
  - Long-lived for user convenience
  - Used only to obtain new access tokens
  - Rotated on each refresh for enhanced security

**Client-Side Storage:**
- **Web Applications**: Store in httpOnly, Secure cookies
- **Mobile Applications**: Use secure storage (Keychain on iOS, Keystore on Android)
- **React Native**: Use AsyncStorage with encryption layer
- **Never store in**: localStorage without encryption, URL parameters, or browser history

### Token Lifecycle Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│                     JWT Authentication Flow                          │
└──────────────────────────────────────────────────────────────────────┘

Registration/Login
        │
        ▼
Generate access token (15min) + refresh token (7 days)
        │
        ▼
Client stores both tokens securely
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│  Normal API Request Pattern                                   │
│                                                                │
│  Client → API Request with Authorization: Bearer {access}     │
│           │                                                    │
│           ▼                                                    │
│  Server validates access token:                               │
│    ✓ Signature matches JWT_SECRET                            │
│    ✓ Token not expired (exp > now)                           │
│    ✓ Token not blacklisted                                   │
│    ✓ User exists in database                                 │
│           │                                                    │
│           ▼                                                    │
│  Return response with user data                               │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
Access token expires after 15 minutes
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│  Token Refresh Pattern                                        │
│                                                                │
│  Client receives 401 Unauthorized                             │
│           │                                                    │
│           ▼                                                    │
│  Client detects expired access token                          │
│           │                                                    │
│           ▼                                                    │
│  POST /auth/refresh with refresh token                        │
│           │                                                    │
│           ▼                                                    │
│  Server validates refresh token:                              │
│    ✓ Signature valid                                         │
│    ✓ Not expired (< 7 days)                                  │
│    ✓ Not blacklisted                                         │
│    ✓ User still exists                                       │
│           │                                                    │
│           ▼                                                    │
│  Blacklist old refresh token (prevent reuse)                  │
│           │                                                    │
│           ▼                                                    │
│  Generate NEW access + refresh tokens                         │
│           │                                                    │
│           ▼                                                    │
│  Client stores new tokens                                     │
│           │                                                    │
│           ▼                                                    │
│  Retry original failed API request with new access token      │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
Refresh token expires after 7 days OR user logs out
        │
        ▼
User must login again
```

### Token Refresh Flow

The refresh endpoint provides secure token rotation to maintain user sessions without requiring re-authentication.

**Endpoint**: `POST /api/v1/auth/refresh`

**Security Features:**
- **Token Rotation**: Each refresh issues new access AND refresh tokens
- **Blacklist Protection**: Old refresh tokens are immediately invalidated
- **User Validation**: Confirms user account still exists and is active
- **Reuse Prevention**: Blacklisted tokens cannot be reused even if not expired

**Request Format:**
```json
{
  "refresh_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."
}
```

**Response Format:**
```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
  "refresh_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
  "token_type": "bearer",
  "expires_in": 900
}
```

**Error Scenarios:**
- 401 Unauthorized: Invalid token signature, expired token, or blacklisted token
- 401 Unauthorized: User account not found or deactivated

### Token Validation in Protected Routes

All protected endpoints use dependency injection to validate tokens:

```python
from app.core.security import create_access_token, create_refresh_token

# Token generation example
access_token = create_access_token(data={"sub": str(user_id)})
refresh_token = create_refresh_token(data={"sub": str(user_id)})

# Token validation in dependencies
from app.api.deps import get_current_user

@router.get("/protected")
async def protected_route(current_user: User = Depends(get_current_user)):
    return {"user_id": current_user.id}
```

**Validation Process:**
1. Extract token from `Authorization: Bearer {token}` header
2. Verify JWT signature using `JWT_SECRET`
3. Check token has not expired (`exp` claim)
4. Verify token type matches expected type (access vs refresh)
5. Check token is not in blacklist
6. Retrieve user from database and verify account is active
7. Inject authenticated user into route handler

## API Endpoints

### Authentication

All authentication endpoints return JWT tokens that must be stored securely by the client. Tokens are used to authenticate subsequent API requests.

#### POST /api/v1/auth/register

Register a new job seeker user account.

**Request Body:**
```json
{
  "email": "user@example.com",
  "password": "secure_password_123",
  "full_name": "John Doe",
  "role": "job_seeker"
}
```

**Response (200 OK):**
```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJzdWIiOiI1NTBlODQwMC1lMjliLTQxZDQtYTcxNi00NDY2NTU0NDAwMDAiLCJleHAiOjE3MDkwNDc4MDAsInR5cGUiOiJhY2Nlc3MifQ...",
  "refresh_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJzdWIiOiI1NTBlODQwMC1lMjliLTQxZDQtYTcxNi00NDY2NTU0NDAwMDAiLCJleHAiOjE3MDk2NTI2MDAsInR5cGUiOiJyZWZyZXNoIn0...",
  "token_type": "bearer"
}
```

**Errors:**
- **400 Bad Request**: Email already registered
  ```json
  {
    "detail": "Email already registered"
  }
  ```
- **422 Unprocessable Entity**: Validation error (invalid email format, missing required fields)
  ```json
  {
    "detail": [
      {
        "loc": ["body", "email"],
        "msg": "value is not a valid email address",
        "type": "value_error.email"
      }
    ]
  }
  ```

#### POST /api/v1/auth/login

Authenticate an existing user and receive JWT tokens.

**Request Body:**
```json
{
  "email": "user@example.com",
  "password": "secure_password_123"
}
```

**Response (200 OK):**
```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
  "refresh_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
  "token_type": "bearer"
}
```

**Errors:**
- **401 Unauthorized**: Invalid email or password
  ```json
  {
    "detail": "Incorrect email or password"
  }
  ```

**Security Notes:**
- Passwords are hashed using bcrypt with automatic salt generation
- Failed login attempts do not reveal whether email exists (consistent error message)
- Login attempts are currently unlimited (rate limiting planned for Phase 2)

#### POST /api/v1/auth/refresh

Refresh an expired access token using a valid refresh token. This endpoint implements token rotation for enhanced security.

**Request Body:**
```json
{
  "refresh_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."
}
```

**Response (200 OK):**
```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
  "refresh_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
  "token_type": "bearer",
  "expires_in": 900
}
```

**Errors:**
- **401 Unauthorized**: Invalid or expired refresh token
  ```json
  {
    "detail": "Invalid or malformed refresh token"
  }
  ```
- **401 Unauthorized**: Refresh token has expired
  ```json
  {
    "detail": "Refresh token has expired"
  }
  ```
- **401 Unauthorized**: User account not found
  ```json
  {
    "detail": "User account not found or has been deactivated"
  }
  ```

**Implementation Details:**
- Old refresh token is blacklisted immediately upon successful refresh
- New access AND refresh tokens are issued (token rotation)
- Blacklisted tokens cannot be reused, even if not yet expired
- User account existence is validated before issuing new tokens

**Client Implementation Recommendations:**
```typescript
// Recommended client-side refresh flow
async function refreshTokens(refreshToken: string): Promise<TokenResponse> {
  const response = await fetch('/api/v1/auth/refresh', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken })
  });

  if (response.status === 401) {
    // Refresh token expired or invalid - redirect to login
    clearAuthTokens();
    redirectToLogin();
    throw new Error('Session expired');
  }

  const tokens = await response.json();
  storeAuthTokens(tokens);
  return tokens;
}
```

#### POST /api/v1/auth/logout

Logout the current user by invalidating their tokens on the server side.

**Headers:**
```
Authorization: Bearer {access_token}
```

**Request Body:**
None required.

**Response (200 OK):**
```json
{
  "message": "Successfully logged out",
  "detail": "Tokens have been invalidated. Please clear all tokens from client storage."
}
```

**Errors:**
- **401 Unauthorized**: Missing or invalid access token
  ```json
  {
    "detail": "Could not validate credentials"
  }
  ```

**Client Actions After Logout:**
1. Clear access token from storage
2. Clear refresh token from storage
3. Clear any user profile data from cache
4. Redirect to login page
5. Clear any authentication headers from API client

**Security Features:**
- Access token is immediately blacklisted on server
- Prevents token reuse after logout
- Server-side session invalidation
- Subsequent requests with blacklisted token will receive 401 error

#### POST /api/v1/auth/register-company

Register a new company user account with associated company entity. This endpoint creates both a user account and a company profile.

**Request Body:**
```json
{
  "email": "recruiter@techcorp.com",
  "password": "secure_password_123",
  "full_name": "Jane Recruiter",
  "role": "recruiter",
  "company_name": "TechCorp Inc",
  "company_description": "Leading technology company specializing in cloud solutions",
  "company_website": "https://techcorp.com",
  "company_industry": "Technology",
  "company_size": "100-500",
  "company_location": "San Francisco, CA"
}
```

**Role Mapping:**
- `"admin"` → COMPANY_ADMIN: Full access to company settings, jobs, and team management
- `"recruiter"` → COMPANY_RECRUITER: Can post jobs, review applications, manage hiring
- `"hr"` → COMPANY_RECRUITER: HR representatives get recruiter-level permissions

**Response (200 OK):**
```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
  "refresh_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
  "token_type": "bearer"
}
```

**Errors:**
- **400 Bad Request**: Email already registered
  ```json
  {
    "detail": "Email already registered"
  }
  ```
- **400 Bad Request**: Company exists but is not active
  ```json
  {
    "detail": "Company exists but is not active"
  }
  ```
- **422 Unprocessable Entity**: Invalid role or validation error
  ```json
  {
    "detail": [
      {
        "loc": ["body", "role"],
        "msg": "Company users must have one of these roles: admin, recruiter, hr. Got: invalid_role",
        "type": "value_error"
      }
    ]
  }
  ```

**Behavior:**
- If company with `company_name` already exists and is active, user is associated with existing company
- If company does not exist, new company entity is created
- Company admin can invite additional users to join the company (future feature)

### User Profile

All user profile endpoints require authentication via Bearer token in the Authorization header.

**Authentication Header Format:**
```
Authorization: Bearer {access_token}
```

#### GET /api/v1/users/{user_id}

Get user profile by ID. Users can only access their own profile (enforced by authorization check).

**Path Parameters:**
- `user_id` (UUID): The user's unique identifier

**Headers:**
```
Authorization: Bearer {access_token}
```

**Response (200 OK) - Job Seeker User:**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "user@example.com",
  "full_name": "John Doe",
  "headline": "Senior Backend Engineer specializing in Python and cloud architecture",
  "bio": "Passionate software engineer with 5+ years of experience building scalable systems",
  "phone": "+1-555-0123",
  "skills": ["Python", "FastAPI", "PostgreSQL", "Docker", "AWS"],
  "preferred_locations": ["Remote", "San Francisco", "New York"],
  "seniority": "SENIOR",
  "role": "job_seeker",
  "user_type": "job_seeker",
  "company_id": null,
  "company": null,
  "experience": [
    {
      "title": "Senior Backend Engineer",
      "company": "Tech Startup",
      "start_date": "2020-01-01",
      "end_date": null,
      "description": "Led backend development for core platform"
    }
  ],
  "education": [
    {
      "degree": "BS Computer Science",
      "institution": "University of California",
      "start_date": "2014-09-01",
      "end_date": "2018-06-01",
      "description": "Focus on distributed systems and algorithms"
    }
  ],
  "created_at": "2025-01-15T10:30:00Z",
  "updated_at": "2025-01-20T14:45:00Z"
}
```

**Response (200 OK) - Company User:**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440001",
  "email": "recruiter@techcorp.com",
  "full_name": "Jane Recruiter",
  "headline": null,
  "bio": null,
  "phone": null,
  "skills": null,
  "preferred_locations": null,
  "seniority": null,
  "role": "recruiter",
  "user_type": "company",
  "company_id": "660e8400-e29b-41d4-a716-446655440000",
  "company": {
    "id": "660e8400-e29b-41d4-a716-446655440000",
    "name": "TechCorp Inc",
    "description": "Leading technology company",
    "website": "https://techcorp.com",
    "location": "San Francisco, CA",
    "industry": "Technology",
    "size": "100-500",
    "logo_url": null,
    "founded_year": null,
    "is_active": true,
    "created_at": "2025-01-15T10:30:00Z",
    "updated_at": "2025-01-15T10:30:00Z"
  },
  "experience": null,
  "education": null,
  "created_at": "2025-01-15T10:30:00Z",
  "updated_at": "2025-01-20T14:45:00Z"
}
```

**Errors:**
- **401 Unauthorized**: Missing, invalid, or expired access token
  ```json
  {
    "detail": "Could not validate credentials"
  }
  ```
- **403 Forbidden**: Attempting to access another user's profile
  ```json
  {
    "detail": "You can only access your own profile"
  }
  ```

**Notes:**
- `user_type` is a computed field derived from `role` for frontend compatibility
- Job seekers have `user_type: "job_seeker"` and company users have `user_type: "company"`
- Company users include populated `company` object with full company details

#### PATCH /api/v1/users/{user_id}

Update user profile information. Users can only update their own profile.

**Path Parameters:**
- `user_id` (UUID): The user's unique identifier

**Headers:**
```
Authorization: Bearer {access_token}
```

**Request Body (Job Seeker Update):**
```json
{
  "full_name": "John Michael Doe",
  "headline": "Senior Backend Engineer & Cloud Architect",
  "bio": "Updated bio with more details about my expertise",
  "phone": "+1-555-0124",
  "skills": ["Python", "FastAPI", "PostgreSQL", "Docker", "AWS", "Kubernetes"],
  "preferred_locations": ["Remote", "Austin"],
  "seniority": "LEAD",
  "experience": [
    {
      "title": "Lead Backend Engineer",
      "company": "Tech Startup",
      "start_date": "2020-01-01",
      "end_date": null,
      "description": "Promoted to lead - managing team of 4 engineers"
    }
  ],
  "education": [
    {
      "degree": "BS Computer Science",
      "institution": "University of California",
      "start_date": "2014-09-01",
      "end_date": "2018-06-01",
      "description": "Focus on distributed systems"
    }
  ]
}
```

**Notes:**
- All fields are optional - only include fields you want to update
- Omitted fields will not be changed
- Arrays (skills, experience, education) completely replace existing values if provided

**Response (200 OK):**
Returns the updated user object in the same format as GET /users/{user_id}

**Errors:**
- **401 Unauthorized**: Authentication required
  ```json
  {
    "detail": "Could not validate credentials"
  }
  ```
- **403 Forbidden**: Cannot update other users' profiles
  ```json
  {
    "detail": "You can only update your own profile"
  }
  ```
- **422 Unprocessable Entity**: Validation error
  ```json
  {
    "detail": [
      {
        "loc": ["body", "seniority"],
        "msg": "Invalid seniority level",
        "type": "value_error"
      }
    ]
  }
  ```

**Valid Seniority Values:**
- `"ENTRY"` - Entry level position
- `"JUNIOR"` - Junior level (0-2 years)
- `"MID"` - Mid level (2-5 years)
- `"SENIOR"` - Senior level (5-8 years)
- `"LEAD"` - Lead/Staff level (8+ years)
- `"PRINCIPAL"` - Principal/Architect level (10+ years)

#### Legacy Endpoints (Deprecated)

The following endpoints are maintained for backward compatibility but are deprecated:

- **GET /api/v1/users/me** (deprecated) → Use GET /api/v1/users/{user_id}
- **PATCH /api/v1/users/me** (deprecated) → Use PATCH /api/v1/users/{user_id}

### Jobs & Discovery
- `GET /api/v1/jobs/{job_id}` - Get specific job details
- `GET /api/v1/jobs/discover?limit=20&cursor=` - Get personalized job recommendations

### Swipes & Applications
- `POST /api/v1/swipes` - Record swipe action (RIGHT creates application)
- `GET /api/v1/applications` - Get user's job applications
- `GET /api/v1/applications/{id}` - Get specific application details

## Error Handling & Status Codes

The API follows RESTful conventions and FastAPI's standard error response format. Understanding error handling is critical for building robust client applications.

### HTTP Status Codes

#### 200 OK
Request succeeded and response contains requested data.

#### 400 Bad Request
Request is syntactically valid but violates business logic rules.

**Common Causes:**
- Email already registered during signup
- Company name already exists
- Invalid state transitions
- Business constraint violations

**Example:**
```json
{
  "detail": "Email already registered"
}
```

#### 401 Unauthorized
Authentication required but missing, invalid, or expired.

**Common Causes:**
- Missing `Authorization` header
- Invalid JWT token signature
- Expired access token
- Blacklisted/revoked token after logout
- Token type mismatch (using refresh token for access endpoint)

**Client Response Strategy:**
```typescript
if (response.status === 401) {
  // Step 1: Check if we have a refresh token
  const refreshToken = getStoredRefreshToken();

  if (!refreshToken) {
    // No refresh token - redirect to login
    redirectToLogin();
    return;
  }

  // Step 2: Try to refresh the access token
  try {
    const newTokens = await refreshTokens(refreshToken);
    storeTokens(newTokens);

    // Step 3: Retry the original request with new access token
    return retryOriginalRequest(newTokens.access_token);
  } catch (refreshError) {
    // Refresh failed - redirect to login
    clearAllTokens();
    redirectToLogin();
  }
}
```

**Example Error Response:**
```json
{
  "detail": "Could not validate credentials"
}
```

#### 403 Forbidden
Request is authenticated but user lacks permission for the requested action.

**Common Causes:**
- User attempting to access another user's profile
- User attempting to update another user's data
- Insufficient role permissions (e.g., recruiter trying to access admin features)

**Client Response Strategy:**
- Do NOT retry with refresh token (permissions won't change)
- Display permission denied message to user
- Consider hiding UI elements that would result in 403 errors

**Example Error Response:**
```json
{
  "detail": "You can only access your own profile"
}
```

**Key Difference from 401:**
- **401**: "Who are you?" - authentication problem, retry with refresh
- **403**: "I know who you are, but you can't do that" - authorization problem, don't retry

#### 422 Unprocessable Entity
Request body fails Pydantic validation (malformed data, wrong types, missing required fields).

**Common Causes:**
- Invalid email format
- Missing required fields
- Wrong data types (string instead of integer)
- Values outside allowed ranges
- Invalid enum values

**Example Error Response:**
```json
{
  "detail": [
    {
      "loc": ["body", "email"],
      "msg": "value is not a valid email address",
      "type": "value_error.email"
    },
    {
      "loc": ["body", "password"],
      "msg": "ensure this value has at least 6 characters",
      "type": "value_error.any_str.min_length"
    },
    {
      "loc": ["body", "seniority"],
      "msg": "value is not a valid enumeration member; permitted: 'ENTRY', 'JUNIOR', 'MID', 'SENIOR', 'LEAD', 'PRINCIPAL'",
      "type": "type_error.enum"
    }
  ]
}
```

**Error Object Structure:**
- `loc`: Array indicating where the error occurred (e.g., ["body", "email"] means the email field in request body)
- `msg`: Human-readable error message
- `type`: Error classification for programmatic handling

**Client Handling:**
```typescript
if (response.status === 422) {
  const errors = await response.json();

  // Map validation errors to form fields
  errors.detail.forEach((error: ValidationError) => {
    const fieldPath = error.loc.slice(1).join('.'); // Remove 'body' prefix
    setFieldError(fieldPath, error.msg);
  });
}
```

#### 500 Internal Server Error
Unexpected server error (should be rare in production).

**Client Response:**
- Display generic error message to user
- Log error details for debugging
- Implement retry logic with exponential backoff
- Contact support if persistent

### Standard Error Response Format

All API errors follow FastAPI's standard format for consistency:

**Single Error (400, 401, 403):**
```json
{
  "detail": "Error message describing the issue"
}
```

**Validation Errors (422):**
```json
{
  "detail": [
    {
      "loc": ["body", "field_name"],
      "msg": "Field-specific error message",
      "type": "error_type_identifier"
    }
  ]
}
```

### Authentication Error Handling Flow

Comprehensive flow for handling authentication errors in client applications:

```
┌─────────────────────────────────────────────────────────────────┐
│                API Request Returns 401                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
              ┌───────────────────────────────┐
              │ Check: Refresh token exists?  │
              └───────────────────────────────┘
                     │                │
                    NO               YES
                     │                │
                     ▼                ▼
    ┌─────────────────────┐  ┌────────────────────────────┐
    │ Clear auth data     │  │ POST /auth/refresh         │
    │ Redirect to /login  │  │ with refresh_token         │
    └─────────────────────┘  └────────────────────────────┘
                                        │
                        ┌───────────────┴───────────────┐
                       200 OK                        401 Error
                        │                               │
                        ▼                               ▼
         ┌──────────────────────────┐  ┌────────────────────────────┐
         │ Store new access token   │  │ Refresh token invalid      │
         │ Store new refresh token  │  │ Clear all auth data        │
         │ Update Authorization hdr │  │ Redirect to /login         │
         └──────────────────────────┘  └────────────────────────────┘
                        │
                        ▼
         ┌──────────────────────────┐
         │ Retry original request   │
         │ with new access token    │
         └──────────────────────────┘
                        │
                        ▼
                  ┌─────────┐
                  │ Success │
                  └─────────┘
```

### Token Expiration Handling

**Recommended Implementation Pattern:**

```typescript
// API client with automatic token refresh
class ApiClient {
  private isRefreshing = false;
  private refreshPromise: Promise<TokenResponse> | null = null;

  async request(url: string, options: RequestOptions) {
    try {
      const response = await fetch(url, {
        ...options,
        headers: {
          ...options.headers,
          Authorization: `Bearer ${getAccessToken()}`
        }
      });

      if (response.status === 401) {
        // Token expired - refresh and retry
        const newTokens = await this.refreshAccessToken();

        // Retry original request with new token
        return fetch(url, {
          ...options,
          headers: {
            ...options.headers,
            Authorization: `Bearer ${newTokens.access_token}`
          }
        });
      }

      return response;
    } catch (error) {
      // Handle network errors
      throw error;
    }
  }

  private async refreshAccessToken(): Promise<TokenResponse> {
    // Prevent multiple simultaneous refresh requests
    if (this.isRefreshing && this.refreshPromise) {
      return this.refreshPromise;
    }

    this.isRefreshing = true;
    this.refreshPromise = fetch('/api/v1/auth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: getRefreshToken() })
    })
      .then(res => {
        if (res.status === 401) {
          // Refresh token expired - logout
          clearTokens();
          redirectToLogin();
          throw new Error('Session expired');
        }
        return res.json();
      })
      .then(tokens => {
        storeTokens(tokens);
        return tokens;
      })
      .finally(() => {
        this.isRefreshing = false;
        this.refreshPromise = null;
      });

    return this.refreshPromise;
  }
}
```

### Error Logging & Monitoring

**Client-Side Best Practices:**

```typescript
// Log authentication errors for debugging
function logAuthError(error: AuthError) {
  console.error('[Auth Error]', {
    status: error.status,
    detail: error.detail,
    endpoint: error.endpoint,
    timestamp: new Date().toISOString(),
    userId: getCurrentUserId() || 'anonymous'
  });

  // Send to monitoring service (e.g., Sentry)
  if (error.status === 500) {
    captureException(error);
  }
}

// Track token refresh metrics
function trackTokenRefresh(success: boolean, attempt: number) {
  analytics.track('token_refresh', {
    success,
    attempt,
    timestamp: Date.now()
  });
}
```

### Common Error Scenarios & Solutions

| Scenario | Status Code | Solution |
|----------|-------------|----------|
| Access token expired | 401 | Refresh token and retry request |
| Refresh token expired | 401 | Redirect to login, clear all tokens |
| Invalid email format | 422 | Show field validation error to user |
| Email already exists | 400 | Suggest login instead of register |
| Wrong password | 401 | Show generic "Invalid credentials" message |
| Missing required field | 422 | Highlight required fields in form |
| User views another's profile | 403 | Redirect to own profile or show error |
| Token blacklisted after logout | 401 | Clear tokens and redirect to login |

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

## Security Best Practices

### Token Security

#### Storage Recommendations

**Do NOT store tokens in:**
- URL parameters or query strings (visible in browser history and server logs)
- Browser localStorage without additional security measures
- Unencrypted cookies accessible to JavaScript
- Session storage without encryption (vulnerable to XSS)
- Plain text files or logs

**DO store tokens in:**

**Web Applications:**
```javascript
// Best practice: httpOnly, Secure cookies (set by backend)
// Backend sets cookie header:
Set-Cookie: access_token=xxx; HttpOnly; Secure; SameSite=Strict; Max-Age=900
Set-Cookie: refresh_token=xxx; HttpOnly; Secure; SameSite=Strict; Max-Age=604800

// JavaScript cannot access these cookies (httpOnly flag)
// Automatically sent with each request to same domain
```

**Mobile Applications (iOS/Android):**
```swift
// iOS: Use Keychain Services
import Security

func saveToken(_ token: String, forKey key: String) {
    let data = token.data(using: .utf8)!
    let query: [String: Any] = [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrAccount as String: key,
        kSecValueData as String: data,
        kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlock
    ]
    SecItemAdd(query as CFDictionary, nil)
}
```

```kotlin
// Android: Use EncryptedSharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKeys

val masterKeyAlias = MasterKeys.getOrCreate(MasterKeys.AES256_GCM_SPEC)

val sharedPreferences = EncryptedSharedPreferences.create(
    "secure_prefs",
    masterKeyAlias,
    context,
    EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
    EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
)

sharedPreferences.edit()
    .putString("access_token", token)
    .apply()
```

**React Native Applications:**
```typescript
// Use react-native-keychain or expo-secure-store
import * as SecureStore from 'expo-secure-store';

// Store tokens securely
async function saveTokens(accessToken: string, refreshToken: string) {
  await SecureStore.setItemAsync('access_token', accessToken);
  await SecureStore.setItemAsync('refresh_token', refreshToken);
}

// Retrieve tokens
async function getAccessToken(): Promise<string | null> {
  return await SecureStore.getItemAsync('access_token');
}

// Delete tokens on logout
async function clearTokens() {
  await SecureStore.deleteItemAsync('access_token');
  await SecureStore.deleteItemAsync('refresh_token');
}
```

#### Token Transmission

**Always use HTTPS in production:**
```nginx
# Nginx configuration - force HTTPS
server {
    listen 80;
    server_name api.jobmatch.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name api.jobmatch.com;

    ssl_certificate /etc/letsencrypt/live/api.jobmatch.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.jobmatch.com/privkey.pem;

    # Modern TLS configuration
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256...';
    ssl_prefer_server_ciphers off;

    location / {
        proxy_pass http://backend:8000;
    }
}
```

**Token transmission rules:**
- Production: Always HTTPS/TLS to encrypt token transmission
- Development: HTTP acceptable for localhost only
- Headers: Include tokens ONLY in Authorization header, never in URL
- Logging: Never log full tokens (mask or truncate)

**Example logging configuration:**
```python
import logging
import re

class TokenMaskingFormatter(logging.Formatter):
    """Formatter that masks JWT tokens in log messages"""

    TOKEN_PATTERN = re.compile(r'(eyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,})')

    def format(self, record):
        message = super().format(record)
        # Mask JWT tokens showing only first/last 10 chars
        return self.TOKEN_PATTERN.sub(
            lambda m: f"{m.group(0)[:10]}...{m.group(0)[-10:]}",
            message
        )
```

#### Token Validation

Every protected endpoint validates tokens through the following process:

**Validation Steps:**
1. **Signature Verification**: Token signature matches server's `JWT_SECRET`
2. **Expiration Check**: Token has not expired (`exp` claim > current time)
3. **Type Validation**: Token type matches expected type (access vs refresh)
4. **Blacklist Check**: Token has not been revoked/blacklisted
5. **User Validation**: User account exists in database and is active
6. **Claims Validation**: Required claims present (`sub`, `exp`, `type`)

**Implementation:**
```python
# In app/api/deps.py
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import verify_token
from app.core.database import get_db
from app.models.user import User
import uuid

security = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> User:
    """Dependency to get currently authenticated user"""
    token = credentials.credentials

    # Verify token signature, expiration, blacklist
    user_id = verify_token(token, token_type="access")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verify user exists and is active
    result = await db.execute(
        select(User).where(User.id == uuid.UUID(user_id))
    )
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive"
        )

    return user
```

### Token Lifecycle Management

#### Access Token
- **Expiration**: 15 minutes (900 seconds)
- **Purpose**: Short-lived to minimize exposure if compromised
- **Refresh**: Automatically refreshed by client before expiration
- **Storage**: Secure storage with short TTL
- **Usage**: Sent with every API request in Authorization header

#### Refresh Token
- **Expiration**: 7 days (604800 seconds)
- **Purpose**: Long-lived for user convenience without frequent re-login
- **Rotation**: Each refresh issues a NEW refresh token (old one blacklisted)
- **Storage**: Most secure storage available on platform
- **Usage**: Only used for /auth/refresh endpoint

**Token Rotation Benefits:**
- Prevents refresh token reuse attacks
- Limits damage if refresh token is compromised
- Provides audit trail of token refresh events
- Enables detection of stolen tokens (reuse attempts fail)

**Logout Behavior:**
```python
@router.post("/logout")
async def logout(
    request: Request,
    current_user: User = Depends(get_current_user)
):
    """Logout user by invalidating tokens"""
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        access_token = auth_header[7:]
        blacklist_token(access_token)  # Immediate server-side invalidation

    return {
        "message": "Successfully logged out",
        "detail": "Tokens have been invalidated. Clear all tokens from client storage."
    }
```

### Password Security

#### Hashing Algorithm

**Bcrypt with automatic salt generation:**
```python
from passlib.context import CryptContext

# Configure bcrypt context
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto"
)

# Hash password (automatic salt generation)
hashed_password = pwd_context.hash("user_password")
# Output: $2b$12$randomsalt...hashedpassword

# Verify password (constant-time comparison)
is_valid = pwd_context.verify("user_password", hashed_password)
```

**Configuration:**
- Algorithm: bcrypt
- Work factor: 12 rounds (adjustable via `PASSWORD_BCRYPT_ROUNDS` env var)
- Salt: Automatically generated per password
- Never store or return plaintext passwords
- Timing attack protection via constant-time comparison

#### Password Requirements

**Current validation:**
- Minimum length: 6 characters (configurable)
- Maximum length: 72 bytes (bcrypt limitation)
- Complexity: Enforced by frontend validation

**Recommended production requirements:**
```python
from pydantic import validator

class UserCreate(BaseModel):
    password: str

    @validator('password')
    def password_strength(cls, v):
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters')
        if not any(char.isdigit() for char in v):
            raise ValueError('Password must contain at least one digit')
        if not any(char.isupper() for char in v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not any(char.islower() for char in v):
            raise ValueError('Password must contain at least one lowercase letter')
        return v
```

**Password reset mechanism (future):**
- Email verification with time-limited token
- Token expires after 1 hour
- Single-use tokens (invalidated after use)
- Rate limiting on reset requests

### API Security Headers

Add security headers to all API responses to protect against common web vulnerabilities:

```python
# In app/main.py
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Add security headers to all responses"""
    response: Response = await call_next(request)

    # Prevent MIME type sniffing
    response.headers["X-Content-Type-Options"] = "nosniff"

    # Prevent clickjacking attacks
    response.headers["X-Frame-Options"] = "DENY"

    # Enable browser XSS protection
    response.headers["X-XSS-Protection"] = "1; mode=block"

    # Control referrer information
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

    # Content Security Policy (adjust for your needs)
    response.headers["Content-Security-Policy"] = "default-src 'self'"

    # Prevent exposing server information
    response.headers["X-Powered-By"] = ""

    return response
```

### Rate Limiting (Planned for Phase 2)

Prevent brute force attacks and API abuse:

```python
# Future implementation with slowapi
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)

# Login endpoint - prevent brute force
@app.post("/auth/login")
@limiter.limit("5/15minutes")  # 5 attempts per 15 minutes per IP
async def login(request: Request, user_credentials: UserLogin):
    # Login logic...
    pass

# Register endpoint - prevent bulk account creation
@app.post("/auth/register")
@limiter.limit("3/hour")  # 3 registrations per hour per IP
async def register(request: Request, user_data: UserCreate):
    # Registration logic...
    pass

# Refresh endpoint - allow normal usage
@app.post("/auth/refresh")
@limiter.limit("20/minute")  # 20 refreshes per minute per user
async def refresh(request: Request, refresh_request: RefreshTokenRequest):
    # Refresh logic...
    pass

# Handle rate limit errors
@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Too many requests. Please try again later.",
            "retry_after": exc.retry_after
        }
    )
```

### Environment Security

#### Development vs Production Configuration

**Development (.env):**
```bash
# Development environment
DEBUG=true
APP_ENV=development
JWT_SECRET=dev-secret-key-change-in-production
DATABASE_URL=postgresql://jobmatch:jobmatch@localhost:5432/jobmatch_dev
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:19006
```

**Production (.env.production):**
```bash
# Production environment
DEBUG=false
APP_ENV=production

# CRITICAL: Generate strong JWT secret (min 32 chars)
JWT_SECRET=<generate-with-openssl-rand-hex-32>

# Use environment-specific database
DATABASE_URL=postgresql://prod_user:strong_password@prod-host:5432/jobmatch_prod

# Specify exact allowed origins
ALLOWED_ORIGINS=https://jobmatch.com,https://www.jobmatch.com

# Token expiration (seconds)
ACCESS_TOKEN_EXPIRES=900     # 15 minutes
REFRESH_TOKEN_EXPIRES=604800 # 7 days

# Rate limiting (if implemented)
RATE_LIMIT_ENABLED=true
RATE_LIMIT_STORAGE=redis://redis:6379/1
```

#### Secret Management

**Generate secure JWT secret:**
```bash
# Generate cryptographically secure random secret
openssl rand -hex 32
# Output: 64-character hex string (32 bytes = 256 bits)
# Example: a7f3d9e2b1c8f4e6d3a9b7c2e5f1d8a4b9c6e3f2d7a1b8c5e4f3d2a9b6c7e1f4
```

**Best practices:**
- Never commit `.env` files to version control
- Use different secrets for dev/staging/production
- Rotate JWT_SECRET periodically (requires all users to re-login)
- Store secrets in environment variables or secret management service
- Use tools like AWS Secrets Manager, HashiCorp Vault in production

**Secret rotation procedure:**
```bash
# 1. Generate new secret
NEW_SECRET=$(openssl rand -hex 32)

# 2. Update environment variable
export JWT_SECRET=$NEW_SECRET

# 3. Restart application
docker compose restart backend

# 4. All users will need to login again (old tokens invalid)
# Consider implementing grace period with dual-secret validation
```

### CORS Configuration

Configure Cross-Origin Resource Sharing to prevent unauthorized frontend access:

```python
# In app/main.py
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings

app.add_middleware(
    CORSMiddleware,
    # Development: Allow local frontend
    allow_origins=settings.allowed_origins if settings.app_env != "production" else [
        "https://jobmatch.com",
        "https://www.jobmatch.com",
        "https://app.jobmatch.com"
    ],
    allow_credentials=True,  # Allow cookies/auth headers
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600  # Cache preflight requests for 10 minutes
)
```

**Security considerations:**
- Never use `allow_origins=["*"]` in production
- Specify exact origins, not wildcards
- Set `allow_credentials=True` only if needed
- Limit allowed methods to those actually used
- Validate origin in production environments

### Vulnerability Prevention

#### SQL Injection
**Protected by:** SQLAlchemy ORM with parameterized queries
```python
# SAFE: SQLAlchemy parameterizes automatically
user = await db.execute(
    select(User).where(User.email == user_input)
)

# UNSAFE: Raw SQL with string formatting (NEVER DO THIS)
# query = f"SELECT * FROM users WHERE email = '{user_input}'"
```

#### Cross-Site Scripting (XSS)
**Protected by:** FastAPI's automatic JSON encoding
```python
# FastAPI automatically escapes output
# User input "</script><script>alert('XSS')</script>"
# Returns: "<\/script><script>alert('XSS')<\/script>"
```

#### Cross-Site Request Forgery (CSRF)
**Protected by:** Stateless JWT tokens (no cookies for authentication)
- JWT in Authorization header (not automatically sent by browser)
- Same-origin policy enforced by CORS
- No session cookies = no CSRF vulnerability

#### Timing Attacks
**Protected by:** Constant-time password comparison
```python
# Passlib uses constant-time comparison internally
pwd_context.verify(plain_password, hashed_password)

# Prevents timing attacks that could reveal password information
# by measuring response time differences
```

#### Token Blacklist Management

**Current implementation (in-memory):**
```python
# In app/core/security.py
import hashlib
import threading

_token_blacklist: Set[str] = set()
_blacklist_lock = threading.Lock()

def blacklist_token(token: str) -> None:
    """Add token hash to blacklist"""
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with _blacklist_lock:
        _token_blacklist.add(token_hash)

def is_token_blacklisted(token: str) -> bool:
    """Check if token is blacklisted"""
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with _blacklist_lock:
        return token_hash in _token_blacklist
```

**Production recommendation (Redis):**
```python
# Use Redis with TTL for automatic cleanup
import redis
from app.core.config import settings

redis_client = redis.Redis.from_url(settings.redis_url)

def blacklist_token(token: str, expires_in: int) -> None:
    """Add token to Redis blacklist with expiration"""
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    redis_client.setex(
        f"blacklist:{token_hash}",
        time=expires_in,  # Automatically expires
        value="1"
    )

def is_token_blacklisted(token: str) -> bool:
    """Check if token is in Redis blacklist"""
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    return redis_client.exists(f"blacklist:{token_hash}") > 0
```

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
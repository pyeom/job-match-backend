#!/usr/bin/env python3
"""
Database Population Script for Job Match Backend

This script populates the database with realistic sample data for ML-driven job matching:
- 2 Complete Company Profiles with admin users + 1 recruiter each
- 6 Realistic Job Postings with embeddings (3 per company)
- 3 Job Seeker Profiles with different skill sets and embeddings
- 2 Teams per company with job assignments
- Realistic swipe patterns and application data with stage history
- Interaction data for ML training with scores

Features:
- Automatic embedding generation for jobs and users
- ML scoring for job-user matches
- Realistic application status progression with ApplicationStageHistory
- Multiple user personas for diverse testing
- Safe re-run capability (handles existing data)
- Full multi-tenant architecture compliance (teams, recruiters, pipeline templates)

Usage:
    python populate_database.py --reset-db --all
    python populate_database.py --companies-only
    python populate_database.py --jobs-only
    python populate_database.py --users-only
"""

import asyncio
import argparse
import sys
import os
import json
import logging
import random
import jwt
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import uuid

# Add the parent directory to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, text
from app.core.database import AsyncSessionLocal, engine, Base
from app.models.user import User, UserRole
from app.models.company import Company
from app.models.job import Job
from app.models.application import Application, RevealedApplication
from app.models.interaction import Interaction
from app.models.team import CompanyTeam, TeamMember, TeamJobAssignment
from app.models.pipeline import PipelineTemplate, ApplicationStageHistory
from app.core.config import settings
from app.services.embedding_service import embedding_service
from app.services.scoring_service import scoring_service

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('database_population.log')
    ]
)
logger = logging.getLogger(__name__)


class DatabasePopulationError(Exception):
    """Custom exception for database population errors"""
    pass


class APIClient:
    """HTTP client for API interactions with authentication"""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip('/')
        self.client = httpx.AsyncClient(timeout=30.0)
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()

    def _get_auth_headers(self) -> Dict[str, str]:
        """Get authentication headers if token is available"""
        if self.access_token:
            return {"Authorization": f"Bearer {self.access_token}"}
        return {}

    def _decode_jwt_get_user_id(self, token: str) -> Optional[str]:
        """Decode JWT token to extract user ID (without verification for simplicity)"""
        try:
            decoded = jwt.decode(token, options={"verify_signature": False})
            return decoded.get("sub")
        except Exception as e:
            logger.warning(f"Failed to decode JWT token: {e}")
            return None

    async def register_user(self, user_data: Dict) -> Dict:
        """Register a new job seeker user"""
        url = f"{self.base_url}/api/v1/auth/register"
        response = await self.client.post(url, json=user_data)

        if response.status_code != 200:
            logger.error(f"User registration failed: {response.text}")
            raise DatabasePopulationError(f"User registration failed: {response.text}")

        result = response.json()
        self.access_token = result.get("access_token")
        self.refresh_token = result.get("refresh_token")
        user_id = self._decode_jwt_get_user_id(self.access_token)
        result["user_id"] = user_id
        logger.info(f"✅ Registered user: {user_data['email']}")
        return result

    async def register_company_user(self, user_data: Dict) -> Dict:
        """Register a new company user (admin for new companies, recruiter for existing).

        Only fields accepted by CompanyUserCreate are forwarded to the API.
        company_founded_year and company_logo_url are NOT part of the registration
        schema — they must be set via a direct DB update after registration.
        """
        api_payload = {
            "email": user_data["email"],
            "password": user_data["password"],
            "full_name": user_data["full_name"],
            "role": user_data["role"],
            "company_name": user_data["company_name"],
        }
        # Optional company fields supported by CompanyUserCreate
        for field in ("company_description", "company_website", "company_industry",
                      "company_size", "company_location", "device_name", "platform"):
            if field in user_data:
                api_payload[field] = user_data[field]

        url = f"{self.base_url}/api/v1/auth/register-company"
        response = await self.client.post(url, json=api_payload)

        if response.status_code != 200:
            logger.error(f"Company user registration failed: {response.text}")
            raise DatabasePopulationError(f"Company user registration failed: {response.text}")

        result = response.json()
        self.access_token = result.get("access_token")
        self.refresh_token = result.get("refresh_token")
        user_id = self._decode_jwt_get_user_id(self.access_token)
        result["user_id"] = user_id
        logger.info(f"✅ Registered company user: {user_data['email']} for {user_data['company_name']}")
        return result

    async def login(self, email: str, password: str) -> Dict:
        """Login and get authentication tokens"""
        url = f"{self.base_url}/api/v1/auth/login"
        response = await self.client.post(url, json={"email": email, "password": password})

        if response.status_code != 200:
            logger.error(f"Login failed for {email}: {response.text}")
            raise DatabasePopulationError(f"Login failed for {email}: {response.text}")

        result = response.json()
        self.access_token = result.get("access_token")
        self.refresh_token = result.get("refresh_token")
        user_id = self._decode_jwt_get_user_id(self.access_token)
        result["user_id"] = user_id
        logger.info(f"✅ Logged in as: {email}")
        return result

    async def create_job(self, job_data: Dict, company_id: str) -> Dict:
        """Create a new job posting for a specific company"""
        url = f"{self.base_url}/api/v1/companies/{company_id}/jobs"
        headers = self._get_auth_headers()
        response = await self.client.post(url, json=job_data, headers=headers)

        if response.status_code != 200:
            logger.error(f"Job creation failed: {response.text}")
            raise DatabasePopulationError(f"Job creation failed: {response.text}")

        result = response.json()
        logger.info(f"✅ Created job: {job_data['title']}")
        return result

    async def get_user_profile(self, user_id: str = None) -> Dict:
        """Get user profile by ID or use /me endpoint"""
        if user_id:
            url = f"{self.base_url}/api/v1/users/{user_id}"
        else:
            url = f"{self.base_url}/api/v1/users/me"

        headers = self._get_auth_headers()
        response = await self.client.get(url, headers=headers)

        if response.status_code != 200:
            logger.error(f"Failed to get user profile: {response.text}")
            raise DatabasePopulationError(f"Failed to get user profile: {response.text}")

        return response.json()

    async def update_user_profile(self, profile_data: Dict, user_id: str = None) -> Dict:
        """Update user profile by ID or use /me endpoint"""
        if user_id:
            url = f"{self.base_url}/api/v1/users/{user_id}"
        else:
            url = f"{self.base_url}/api/v1/users/me"

        headers = self._get_auth_headers()
        response = await self.client.patch(url, json=profile_data, headers=headers)

        if response.status_code != 200:
            logger.error(f"Profile update failed: {response.text}")
            raise DatabasePopulationError(f"Profile update failed: {response.text}")

        return response.json()

    async def health_check(self) -> bool:
        """Check if the API is running"""
        try:
            url = f"{self.base_url}/healthz"
            response = await self.client.get(url)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False


class DatabasePopulator:
    """Main class for database population"""

    def __init__(self, api_client: APIClient):
        self.api_client = api_client
        self.company_tokens: Dict[str, Dict[str, str]] = {}
        self.job_seeker_tokens: Dict[str, str] = {}
        self.created_companies: List[Dict] = []
        self.created_jobs: List[Dict] = []
        self.created_users: List[Dict] = []
        self.created_recruiters: List[Dict] = []
        self.created_teams: List[Dict] = []

    async def reset_database(self) -> None:
        """Reset the database by removing all data.

        Deletion order respects foreign-key constraints:
          ApplicationStageHistory → RevealedApplication → Interaction → Application
          → TeamJobAssignment → TeamMember → CompanyTeam
          → PipelineTemplate → Job → User → Company
        """
        logger.info("🔄 Resetting database...")

        async with AsyncSessionLocal() as session:
            try:
                # Child tables first
                await session.execute(delete(ApplicationStageHistory))
                await session.execute(delete(RevealedApplication))
                await session.execute(delete(Interaction))
                await session.execute(delete(Application))
                await session.execute(delete(TeamJobAssignment))
                await session.execute(delete(TeamMember))
                await session.execute(delete(CompanyTeam))
                await session.execute(delete(PipelineTemplate))
                await session.execute(delete(Job))
                await session.execute(delete(User))
                await session.execute(delete(Company))

                await session.commit()
                logger.info("✅ Database reset completed")

            except Exception as e:
                await session.rollback()
                logger.error(f"❌ Database reset failed: {e}")
                raise DatabasePopulationError(f"Database reset failed: {e}")

    async def create_companies(self) -> List[Dict]:
        """Create the two company profiles with admin users.

        After API registration (which doesn't accept founded_year/logo_url),
        we patch those fields directly via SQLAlchemy.
        """
        logger.info("🏢 Creating company profiles...")

        companies_data = [
            {
                "company_name": "TechVision Solutions",
                "company_description": (
                    "A mid-size technology company specializing in AI/ML solutions and "
                    "innovative software development. We help businesses transform their "
                    "operations through cutting-edge artificial intelligence and machine "
                    "learning technologies."
                ),
                "company_website": "https://techvision.com",
                "company_industry": "Technology",
                "company_size": "201-1000",
                "company_location": "San Francisco, CA",
                # These are not in CompanyUserCreate — applied via direct DB update below
                "_founded_year": 2015,
                "_logo_url": "https://techvision.com/logo.png",
                "email": "admin@techvision.com",
                "password": "techvision_admin_2024",
                "full_name": "Sarah Chen",
                "role": "admin",
            },
            {
                "company_name": "DataFlow Innovations",
                "company_description": (
                    "A growing startup focused on data analytics and business intelligence "
                    "platforms. We empower organizations to make data-driven decisions "
                    "through intuitive analytics tools and real-time dashboards."
                ),
                "company_website": "https://dataflow.io",
                "company_industry": "Data Analytics",
                "company_size": "11-50",
                "company_location": "Austin, TX",
                "_founded_year": 2020,
                "_logo_url": "https://dataflow.io/assets/logo.svg",
                "email": "admin@dataflow.io",
                "password": "dataflow_admin_2024",
                "full_name": "Michael Rodriguez",
                "role": "admin",
            },
        ]

        created_companies = []

        for company_data in companies_data:
            try:
                result = await self.api_client.register_company_user(company_data)

                self.company_tokens[company_data["company_name"]] = {
                    "access_token": result["access_token"],
                    "refresh_token": result["refresh_token"],
                    "email": company_data["email"],
                    "password": company_data["password"],
                }

                user_id = result.get("user_id")
                profile = await self.api_client.get_user_profile(user_id)
                company_id = profile["company_id"]

                # Set founded_year and logo_url directly — not exposed by CompanyUpdate schema
                founded_year = company_data.get("_founded_year")
                logo_url = company_data.get("_logo_url")
                if founded_year or logo_url:
                    async with AsyncSessionLocal() as session:
                        db_company = await session.get(Company, uuid.UUID(company_id))
                        if db_company:
                            if founded_year:
                                db_company.founded_year = founded_year
                            if logo_url:
                                db_company.logo_url = logo_url
                            await session.commit()

                created_companies.append({
                    "company_name": company_data["company_name"],
                    "admin_email": company_data["email"],
                    "admin_name": company_data["full_name"],
                    "company_id": company_id,
                    "user_id": user_id,
                    "tokens": result,
                    "profile": profile,
                })

                logger.info(f"✅ Created company: {company_data['company_name']}")

            except Exception as e:
                logger.error(f"❌ Failed to create company {company_data['company_name']}: {e}")
                raise

        self.created_companies = created_companies
        return created_companies

    async def create_recruiters(self) -> List[Dict]:
        """Add one recruiter per company (second user — gets RECRUITER company_role automatically)."""
        logger.info("👔 Creating recruiter users...")

        if not self.created_companies:
            logger.warning("⚠️  No companies found. Skipping recruiter creation.")
            return []

        recruiters_data = [
            {
                "company_name": "TechVision Solutions",
                "email": "recruiter@techvision.com",
                "password": "techvision_recruiter_2024",
                "full_name": "James Park",
                "role": "recruiter",
            },
            {
                "company_name": "DataFlow Innovations",
                "email": "recruiter@dataflow.io",
                "password": "dataflow_recruiter_2024",
                "full_name": "Ana Lima",
                "role": "recruiter",
            },
        ]

        created_recruiters = []

        for recruiter_data in recruiters_data:
            try:
                result = await self.api_client.register_company_user(recruiter_data)
                user_id = result.get("user_id")

                created_recruiters.append({
                    "company_name": recruiter_data["company_name"],
                    "email": recruiter_data["email"],
                    "name": recruiter_data["full_name"],
                    "user_id": user_id,
                    "password": recruiter_data["password"],
                })

                logger.info(f"✅ Created recruiter: {recruiter_data['email']} at {recruiter_data['company_name']}")

            except Exception as e:
                logger.error(f"❌ Failed to create recruiter {recruiter_data['email']}: {e}")
                raise

        self.created_recruiters = created_recruiters
        return created_recruiters

    async def create_jobs(self) -> List[Dict]:
        """Create 6 realistic job postings (3 per company)"""
        logger.info("📝 Creating job postings...")

        jobs_data = [
            # TechVision Solutions Jobs
            {
                "company": "TechVision Solutions",
                "title": "Senior Machine Learning Engineer",
                "location": "Remote",
                "short_description": (
                    "Join our AI/ML team to build next-generation machine learning systems "
                    "that power our core products."
                ),
                "description": """Join our AI/ML team to build next-generation machine learning systems that power our core products. You'll work on large-scale ML pipelines, model optimization, and deployment strategies.

Key Responsibilities:
• Design and implement ML models for real-world applications
• Optimize model performance and scalability
• Collaborate with data engineers and product teams
• Mentor junior ML engineers
• Stay current with latest ML research and best practices

Requirements:
• 5+ years of experience in machine learning
• Strong proficiency in Python, TensorFlow/PyTorch
• Experience with cloud platforms (AWS, GCP, Azure)
• Knowledge of MLOps and model deployment
• Master's degree in Computer Science, Statistics, or related field

We offer competitive compensation, equity, comprehensive benefits, and the opportunity to work on cutting-edge AI technology that impacts millions of users.""",
                "tags": ["Python", "TensorFlow", "PyTorch", "Machine Learning", "MLOps", "AWS", "Docker", "Kubernetes", "Deep Learning", "Computer Vision"],
                "seniority": "Senior",
                "salary_min": 140000,
                "salary_max": 180000,
                "remote": True,
            },
            {
                "company": "TechVision Solutions",
                "title": "Full Stack Developer",
                "location": "San Francisco, CA",
                "short_description": (
                    "Build and maintain web applications that serve our growing user base "
                    "using modern technologies and agile methodologies."
                ),
                "description": """Build and maintain web applications that serve our growing user base. Work in a collaborative environment with modern technologies and agile methodologies.

Key Responsibilities:
• Develop responsive web applications using React and Node.js
• Design and implement RESTful APIs
• Work with databases and optimize queries
• Collaborate with UX/UI designers and product managers
• Participate in code reviews and maintain code quality
• Contribute to technical architecture decisions

Requirements:
• 3+ years of full-stack development experience
• Proficiency in JavaScript, React, Node.js
• Experience with PostgreSQL or similar databases
• Knowledge of cloud services and DevOps practices
• Strong problem-solving and communication skills
• Bachelor's degree in Computer Science or equivalent experience

Join our dynamic team and help shape the future of our platform while growing your skills in a supportive environment.""",
                "tags": ["JavaScript", "React", "Node.js", "PostgreSQL", "REST APIs", "HTML", "CSS", "Git", "Agile", "TypeScript"],
                "seniority": "Mid",
                "salary_min": 90000,
                "salary_max": 130000,
                "remote": False,
            },
            {
                "company": "TechVision Solutions",
                "title": "DevOps Engineer",
                "location": "Remote",
                "short_description": (
                    "Build and maintain scalable infrastructure for our AI/ML platform "
                    "using cutting-edge cloud technologies."
                ),
                "description": """Build and maintain scalable infrastructure for our AI/ML platform. Work with cutting-edge cloud technologies and automation tools to ensure reliable deployments and monitoring.

Key Responsibilities:
• Design and implement CI/CD pipelines
• Manage cloud infrastructure on AWS and GCP
• Monitor system performance and reliability
• Automate deployment and scaling processes
• Collaborate with development teams on infrastructure needs
• Implement security best practices and compliance measures

Requirements:
• 4+ years of DevOps or Infrastructure experience
• Strong experience with Docker, Kubernetes, and containerization
• Proficiency in AWS services (EC2, S3, RDS, Lambda)
• Experience with Infrastructure as Code (Terraform, CloudFormation)
• Knowledge of monitoring tools (Prometheus, Grafana, ELK stack)
• Bachelor's degree in Computer Science or related field

Work with a talented team building the future of AI infrastructure.""",
                "tags": ["AWS", "Docker", "Kubernetes", "Terraform", "Python", "CI/CD", "Prometheus", "Grafana", "Infrastructure", "DevOps"],
                "seniority": "Senior",
                "salary_min": 120000,
                "salary_max": 160000,
                "remote": True,
            },
            # DataFlow Innovations Jobs
            {
                "company": "DataFlow Innovations",
                "title": "Data Scientist",
                "location": "Remote",
                "short_description": (
                    "Drive data-driven insights and build predictive models that power "
                    "our analytics platform."
                ),
                "description": """Drive data-driven insights and build predictive models that power our analytics platform. Work with large datasets and cutting-edge analytics technologies.

Key Responsibilities:
• Analyze complex datasets to extract actionable insights
• Build and deploy predictive models and algorithms
• Create data visualizations and reports
• Collaborate with engineering teams on data infrastructure
• Present findings to stakeholders and leadership
• Develop automated reporting and monitoring systems

Requirements:
• 4+ years of experience in data science
• Strong skills in Python, R, and SQL
• Experience with machine learning libraries (scikit-learn, pandas)
• Knowledge of statistical analysis and hypothesis testing
• Experience with data visualization tools (Matplotlib, Plotly, Tableau)
• Master's degree in Data Science, Statistics, or related field

Be part of a growing team that's revolutionizing how businesses understand their data.""",
                "tags": ["Python", "R", "SQL", "Pandas", "Scikit-learn", "Machine Learning", "Statistics", "Data Visualization", "Tableau", "Apache Spark"],
                "seniority": "Senior",
                "salary_min": 110000,
                "salary_max": 150000,
                "remote": True,
            },
            {
                "company": "DataFlow Innovations",
                "title": "Frontend Developer",
                "location": "Austin, TX",
                "short_description": (
                    "Create beautiful and intuitive user interfaces for our data analytics "
                    "platform, working closely with designers and backend developers."
                ),
                "description": """Create beautiful and intuitive user interfaces for our data analytics platform. Work closely with designers and backend developers to deliver exceptional user experiences.

Key Responsibilities:
• Develop responsive web applications using modern JavaScript frameworks
• Implement interactive data visualizations and dashboards
• Optimize application performance and user experience
• Work with designers to implement pixel-perfect UI components
• Integrate with RESTful APIs and GraphQL endpoints
• Maintain and improve existing frontend codebase

Requirements:
• 2+ years of frontend development experience
• Proficiency in JavaScript, HTML, CSS
• Experience with React or Vue.js
• Knowledge of data visualization libraries (D3.js, Chart.js)
• Understanding of responsive design principles
• Bachelor's degree in Computer Science or related field

Join our fast-growing startup and help build the next generation of analytics tools.""",
                "tags": ["JavaScript", "React", "Vue.js", "HTML", "CSS", "D3.js", "Chart.js", "Data Visualization", "Responsive Design", "GraphQL"],
                "seniority": "Mid",
                "salary_min": 70000,
                "salary_max": 100000,
                "remote": False,
            },
            {
                "company": "DataFlow Innovations",
                "title": "Backend Engineer",
                "location": "Austin, TX",
                "short_description": (
                    "Build robust and scalable backend systems using microservices "
                    "architecture to handle large-scale data processing."
                ),
                "description": """Build robust and scalable backend systems that power our data analytics platform. Work with modern technologies and microservices architecture to handle large-scale data processing.

Key Responsibilities:
• Design and implement RESTful APIs and microservices
• Optimize database queries and data processing pipelines
• Integrate with third-party data sources and APIs
• Implement caching and performance optimization strategies
• Write comprehensive tests and maintain code quality
• Collaborate with frontend and data teams on feature development

Requirements:
• 3+ years of backend development experience
• Strong proficiency in Python, Java, or Go
• Experience with databases (PostgreSQL, MongoDB, Redis)
• Knowledge of message queues and event-driven architecture
• Experience with cloud platforms and containerization
• Bachelor's degree in Computer Science or equivalent experience

Join our growing engineering team and help scale our data platform to millions of users.""",
                "tags": ["Python", "Java", "Go", "PostgreSQL", "MongoDB", "Redis", "Microservices", "REST APIs", "Kafka", "Cloud"],
                "seniority": "Mid",
                "salary_min": 85000,
                "salary_max": 120000,
                "remote": False,
            },
        ]

        created_jobs = []

        for job_data in jobs_data:
            try:
                company_name = job_data["company"]
                company_tokens = self.company_tokens[company_name]

                login_result = await self.api_client.login(
                    company_tokens["email"],
                    company_tokens["password"],
                )
                user_id = login_result.get("user_id")
                profile = await self.api_client.get_user_profile(user_id)
                company_id = profile["company_id"]

                job_payload = {k: v for k, v in job_data.items() if k != "company"}
                result = await self.api_client.create_job(job_payload, company_id)

                created_jobs.append({
                    "company": company_name,
                    "job_data": result,
                    "original_data": job_data,
                })

                logger.info(f"✅ Created job: {job_data['title']} at {company_name}")

            except Exception as e:
                logger.error(f"❌ Failed to create job {job_data['title']}: {e}")
                raise

        self.created_jobs = created_jobs
        return created_jobs

    async def create_teams(self) -> List[Dict]:
        """Create one team per company with members and job assignments.

        Each company gets:
          - "Engineering" team — admin user + recruiter + all company jobs
        Teams and membership are created directly via SQLAlchemy to avoid
        requiring email verification for the team management endpoints.
        """
        logger.info("👥 Creating teams...")

        if not self.created_companies:
            logger.warning("⚠️  No companies found. Skipping team creation.")
            return []

        created_teams = []

        async with AsyncSessionLocal() as session:
            try:
                for company_info in self.created_companies:
                    company_id = uuid.UUID(company_info["company_id"])
                    company_name = company_info["company_name"]

                    # Collect all user IDs for this company
                    company_user_ids: List[uuid.UUID] = [uuid.UUID(company_info["user_id"])]
                    for rec in self.created_recruiters:
                        if rec["company_name"] == company_name:
                            company_user_ids.append(uuid.UUID(rec["user_id"]))

                    # Collect all job IDs for this company
                    company_job_ids = [
                        uuid.UUID(j["job_data"]["id"])
                        for j in self.created_jobs
                        if j["company"] == company_name
                    ]

                    # Create "Engineering" team
                    team = CompanyTeam(
                        id=uuid.uuid4(),
                        company_id=company_id,
                        name="Engineering",
                        description="Core engineering hiring team",
                    )
                    session.add(team)
                    await session.flush()

                    # Add members
                    for idx, uid in enumerate(company_user_ids):
                        member_role = "lead" if idx == 0 else "member"
                        session.add(TeamMember(
                            team_id=team.id,
                            user_id=uid,
                            role=member_role,
                        ))

                    # Assign all company jobs to this team
                    for job_id in company_job_ids:
                        session.add(TeamJobAssignment(
                            team_id=team.id,
                            job_id=job_id,
                        ))

                    created_teams.append({
                        "company_name": company_name,
                        "team_id": str(team.id),
                        "team_name": team.name,
                        "member_count": len(company_user_ids),
                        "job_count": len(company_job_ids),
                    })

                    logger.info(
                        f"✅ Created team '{team.name}' for {company_name} "
                        f"({len(company_user_ids)} members, {len(company_job_ids)} jobs)"
                    )

                await session.commit()

            except Exception as e:
                await session.rollback()
                logger.error(f"❌ Failed to create teams: {e}")
                raise DatabasePopulationError(f"Failed to create teams: {e}")

        self.created_teams = created_teams
        return created_teams

    async def create_job_seekers(self) -> List[Dict]:
        """Create multiple job seeker profiles with different backgrounds"""
        logger.info("👤 Creating job seeker profiles...")

        job_seekers_data = [
            {
                "user_data": {
                    "email": "alex.johnson@email.com",
                    "password": "jobseeker_2024",
                    "full_name": "Alex Johnson",
                    "role": "job_seeker",
                },
                "profile_data": {
                    "headline": "Full Stack Developer with 4 years experience in modern web technologies",
                    "bio": "Passionate developer with expertise in building scalable web applications. I enjoy working with modern frameworks and have a strong interest in machine learning applications.",
                    "skills": [
                        "JavaScript", "Python", "React", "Node.js", "PostgreSQL",
                        "MongoDB", "Docker", "AWS", "Git", "TypeScript", "Machine Learning",
                        "REST APIs", "GraphQL", "HTML", "CSS", "TensorFlow",
                    ],
                    "preferred_locations": ["Remote", "San Francisco, CA", "Austin, TX", "Seattle, WA"],
                    "seniority": "Mid",
                    "phone": "+1-555-0123",
                    "experience": [
                        {"title": "Full Stack Developer", "company": "TechCorp Inc.", "description": "Built scalable web apps using React, Node.js and PostgreSQL. Led a team of 3 engineers.", "start_date": "2021-03-01", "end_date": None},
                        {"title": "Junior Developer", "company": "Startup Studio", "description": "Developed REST APIs and frontend components for SaaS products.", "start_date": "2019-06-01", "end_date": "2021-02-28"},
                    ],
                    "education": [
                        {"degree": "B.Sc. Computer Science", "institution": "University of Texas", "description": "Focus on algorithms, distributed systems and databases.", "start_date": "2015-09-01", "end_date": "2019-05-31"},
                    ],
                },
            },
            {
                "user_data": {
                    "email": "sarah.devops@email.com",
                    "password": "devops_2024",
                    "full_name": "Sarah Martinez",
                    "role": "job_seeker",
                },
                "profile_data": {
                    "headline": "Senior DevOps Engineer specializing in cloud infrastructure and automation",
                    "bio": "Experienced DevOps professional with 6+ years in cloud platforms and container orchestration. I focus on building reliable, scalable infrastructure that enables development teams to deploy with confidence.",
                    "skills": [
                        "AWS", "Docker", "Kubernetes", "Terraform", "Python", "CI/CD",
                        "Prometheus", "Grafana", "Infrastructure", "DevOps", "Jenkins",
                        "Ansible", "CloudFormation", "Linux", "Monitoring",
                    ],
                    "preferred_locations": ["Remote", "San Francisco, CA", "New York, NY"],
                    "seniority": "Senior",
                    "phone": "+1-555-0456",
                    "experience": [
                        {"title": "Senior DevOps Engineer", "company": "CloudScale Solutions", "description": "Managed multi-cloud infrastructure (AWS/GCP) for 50+ microservices. Reduced deployment time by 70%.", "start_date": "2020-01-01", "end_date": None},
                        {"title": "DevOps Engineer", "company": "FinTech Dynamics", "description": "Built CI/CD pipelines with Jenkins and GitHub Actions. Containerized legacy apps with Docker/Kubernetes.", "start_date": "2017-04-01", "end_date": "2019-12-31"},
                        {"title": "Systems Administrator", "company": "Data Networks Ltd.", "description": "Linux server management, automation scripting and monitoring with Grafana/Prometheus.", "start_date": "2015-06-01", "end_date": "2017-03-31"},
                    ],
                    "education": [
                        {"degree": "B.Sc. Information Technology", "institution": "San Francisco State University", "description": "Networking, security and systems programming.", "start_date": "2011-09-01", "end_date": "2015-05-31"},
                    ],
                },
            },
            {
                "user_data": {
                    "email": "michael.datascience@email.com",
                    "password": "datascience_2024",
                    "full_name": "Michael Chen",
                    "role": "job_seeker",
                },
                "profile_data": {
                    "headline": "Data Scientist with expertise in ML model development and statistical analysis",
                    "bio": "PhD in Statistics with 5 years of industry experience building predictive models and deriving insights from complex datasets. Passionate about using data to solve real-world problems.",
                    "skills": [
                        "Python", "R", "SQL", "Pandas", "Scikit-learn", "Machine Learning",
                        "Statistics", "Data Visualization", "Tableau", "Apache Spark",
                        "TensorFlow", "PyTorch", "Jupyter", "NumPy", "Matplotlib",
                    ],
                    "preferred_locations": ["Remote", "Austin, TX", "Boston, MA", "Chicago, IL"],
                    "seniority": "Senior",
                    "phone": "+1-555-0789",
                    "experience": [
                        {"title": "Senior Data Scientist", "company": "Predictive Analytics Co.", "description": "Developed ML pipelines for churn prediction and revenue forecasting. Models served 2M+ users.", "start_date": "2020-07-01", "end_date": None},
                        {"title": "Data Scientist", "company": "HealthTech AI", "description": "Built classification models for medical image analysis using PyTorch and TensorFlow.", "start_date": "2018-01-01", "end_date": "2020-06-30"},
                    ],
                    "education": [
                        {"degree": "Ph.D. Statistics", "institution": "MIT", "description": "Research on Bayesian methods and causal inference. 4 published papers.", "start_date": "2013-09-01", "end_date": "2018-06-30"},
                        {"degree": "B.Sc. Mathematics", "institution": "Princeton University", "description": "Minor in Computer Science.", "start_date": "2009-09-01", "end_date": "2013-05-31"},
                    ],
                },
            },
        ]

        created_users = []

        for user_info in job_seekers_data:
            try:
                user_data = user_info["user_data"]
                profile_data = user_info["profile_data"]

                result = await self.api_client.register_user(user_data)
                user_id = result.get("user_id")
                updated_profile = await self.api_client.update_user_profile(profile_data, user_id)

                created_user = {
                    "email": user_data["email"],
                    "name": user_data["full_name"],
                    "password": user_data["password"],
                    "tokens": result,
                    "profile": updated_profile,
                }
                created_users.append(created_user)
                logger.info(f"✅ Created job seeker: {user_data['email']}")

                if not self.job_seeker_tokens:
                    self.job_seeker_tokens = {
                        "access_token": result["access_token"],
                        "refresh_token": result["refresh_token"],
                        "email": user_data["email"],
                        "password": user_data["password"],
                    }

            except Exception as e:
                logger.error(f"❌ Failed to create job seeker {user_info['user_data']['email']}: {e}")
                raise

        self.created_users = created_users
        return created_users

    async def create_sample_applications(self) -> List[Dict]:
        """Create sample applications with varied stages, statuses, and stage history."""
        logger.info("📋 Creating sample applications...")

        if not self.created_users or not self.created_jobs:
            logger.warning("⚠️  No users or jobs found. Skipping applications creation.")
            return []

        stages = ['SUBMITTED', 'REVIEW', 'INTERVIEW', 'TECHNICAL', 'DECISION']
        rejection_reasons = [
            'Not enough experience',
            'Skills mismatch',
            'Compensation expectations too high',
            'Position filled',
            'Not a cultural fit',
            'Candidate withdrew application',
        ]

        created_applications = []

        async with AsyncSessionLocal() as session:
            try:
                job_ids = [uuid.UUID(job["job_data"]["id"]) for job in self.created_jobs]
                user_ids = [uuid.UUID(user["profile"]["id"]) for user in self.created_users]

                for job_data in self.created_jobs:
                    job_id = uuid.UUID(job_data["job_data"]["id"])
                    num_applications = random.randint(2, 4)
                    selected_users = random.sample(user_ids, min(num_applications, len(user_ids)))

                    for user_id in selected_users:
                        # Distribute across stages realistically
                        stage_weights = [0.4, 0.25, 0.15, 0.1, 0.1]
                        stage = random.choices(stages, weights=stage_weights)[0]

                        if stage == 'DECISION':
                            status = random.choices(
                                ['ACTIVE', 'HIRED', 'REJECTED'], weights=[0.3, 0.4, 0.3]
                            )[0]
                        else:
                            status = random.choices(
                                ['ACTIVE', 'REJECTED'], weights=[0.85, 0.15]
                            )[0]

                        rejection_reason = None
                        if status == 'REJECTED':
                            rejection_reason = random.choice(rejection_reasons)

                        # Build stage_history JSONB — track path from SUBMITTED to current stage
                        stage_path = stages[:stages.index(stage) + 1]
                        stage_history_json = []
                        base_time = datetime.utcnow() - timedelta(days=random.randint(1, 60))
                        for i in range(len(stage_path) - 1):
                            stage_history_json.append({
                                "from_stage": stage_path[i],
                                "to_stage": stage_path[i + 1],
                                "timestamp": (base_time + timedelta(days=i + 1)).isoformat(),
                                "changed_by": None,
                            })

                        application = Application(
                            id=uuid.uuid4(),
                            user_id=user_id,
                            job_id=job_id,
                            stage=stage,
                            status=status,
                            stage_updated_at=datetime.utcnow() - timedelta(days=random.randint(0, 30)),
                            rejection_reason=rejection_reason,
                            stage_history=stage_history_json,
                            created_at=base_time,
                        )
                        session.add(application)
                        await session.flush()

                        # Create ApplicationStageHistory rows for each transition
                        for i, transition in enumerate(stage_history_json):
                            entered = datetime.fromisoformat(transition["timestamp"])
                            exited = (
                                datetime.fromisoformat(stage_history_json[i + 1]["timestamp"])
                                if i + 1 < len(stage_history_json)
                                else None
                            )
                            session.add(ApplicationStageHistory(
                                id=uuid.uuid4(),
                                application_id=application.id,
                                stage_order=stages.index(transition["to_stage"]) + 1,
                                stage_name=transition["to_stage"],
                                entered_at=entered,
                                exited_at=exited,
                            ))

                        created_applications.append({
                            "user_id": str(user_id),
                            "job_id": str(job_id),
                            "stage": stage,
                            "status": status,
                        })

                await session.commit()
                logger.info(f"✅ Created {len(created_applications)} sample applications")

            except Exception as e:
                await session.rollback()
                logger.error(f"❌ Failed to create applications: {e}")
                raise DatabasePopulationError(f"Failed to create applications: {e}")

        return created_applications

    async def validate_data(self) -> Dict:
        """Validate that all data was created successfully"""
        logger.info("🔍 Validating created data...")

        validation_results = {
            "companies": len(self.created_companies),
            "recruiters": len(self.created_recruiters),
            "jobs": len(self.created_jobs),
            "users": len(self.created_users),
            "teams": len(self.created_teams),
            "success": True,
            "errors": [],
        }

        if len(self.created_companies) != 2:
            validation_results["errors"].append(
                f"Expected 2 companies, found {len(self.created_companies)}"
            )
            validation_results["success"] = False

        if len(self.created_jobs) != 6:
            validation_results["errors"].append(
                f"Expected 6 jobs, found {len(self.created_jobs)}"
            )
            validation_results["success"] = False

        if len(self.created_users) != 3:
            validation_results["errors"].append(
                f"Expected 3 job seekers, found {len(self.created_users)}"
            )
            validation_results["success"] = False

        if validation_results["success"]:
            logger.info("✅ All data validation passed")
        else:
            logger.error(f"❌ Validation failed: {validation_results['errors']}")

        return validation_results

    async def generate_summary_report(self) -> Dict:
        """Generate a comprehensive summary report"""
        logger.info("📊 Generating summary report...")

        report = {
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "companies_created": len(self.created_companies),
                "recruiters_created": len(self.created_recruiters),
                "jobs_created": len(self.created_jobs),
                "users_created": len(self.created_users),
                "teams_created": len(self.created_teams),
            },
            "companies": [],
            "recruiters": [],
            "jobs": [],
            "users": [],
            "teams": [],
            "login_credentials": [],
        }

        for company in self.created_companies:
            report["companies"].append({
                "name": company["company_name"],
                "admin_email": company["admin_email"],
                "admin_name": company["admin_name"],
                "company_id": company["company_id"],
            })
            report["login_credentials"].append({
                "type": "Company Admin",
                "company": company["company_name"],
                "email": company["admin_email"],
                "password": self.company_tokens[company["company_name"]]["password"],
            })

        for rec in self.created_recruiters:
            report["recruiters"].append({
                "company": rec["company_name"],
                "name": rec["name"],
                "email": rec["email"],
            })
            report["login_credentials"].append({
                "type": "Company Recruiter",
                "company": rec["company_name"],
                "email": rec["email"],
                "password": rec["password"],
            })

        for job in self.created_jobs:
            report["jobs"].append({
                "title": job["job_data"]["title"],
                "company": job["company"],
                "location": job["job_data"]["location"],
                "seniority": job["job_data"]["seniority"],
                "salary_range": f"${job['job_data']['salary_min']:,} - ${job['job_data']['salary_max']:,}",
                "remote": job["job_data"]["remote"],
                "job_id": job["job_data"]["id"],
            })

        for user in self.created_users:
            report["users"].append({
                "email": user["email"],
                "name": user["name"],
                "skills": user["profile"]["skills"],
                "seniority": user["profile"]["seniority"],
                "preferred_locations": user["profile"]["preferred_locations"],
            })
            report["login_credentials"].append({
                "type": "Job Seeker",
                "email": user["email"],
                "password": user["password"],
            })

        for team in self.created_teams:
            report["teams"].append({
                "company": team["company_name"],
                "name": team["team_name"],
                "members": team["member_count"],
                "jobs": team["job_count"],
            })

        return report


async def main():
    """Main function with CLI interface"""
    parser = argparse.ArgumentParser(description="Database Population for Job Match Backend")
    parser.add_argument("--reset-db", action="store_true", help="Reset database before population")
    parser.add_argument("--all", action="store_true", help="Create all data (companies, jobs, users, teams)")
    parser.add_argument("--companies-only", action="store_true", help="Create only companies + recruiters")
    parser.add_argument("--jobs-only", action="store_true", help="Create only jobs (requires existing companies)")
    parser.add_argument("--users-only", action="store_true", help="Create only job seeker users")
    parser.add_argument("--validate-only", action="store_true", help="Only validate existing data")
    parser.add_argument("--api-url", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--output-file", help="Save summary report to file")

    args = parser.parse_args()

    if not any([args.all, args.companies_only, args.jobs_only, args.users_only, args.validate_only]):
        args.all = True

    async with APIClient(args.api_url) as api_client:
        if not await api_client.health_check():
            logger.error(f"❌ API is not running at {args.api_url}")
            logger.info("Please start the FastAPI server with: uvicorn app.main:app --reload")
            sys.exit(1)

        logger.info(f"✅ API is running at {args.api_url}")

        populator = DatabasePopulator(api_client)

        try:
            if args.reset_db:
                await populator.reset_database()

            if args.all or args.companies_only:
                await populator.create_companies()
                await populator.create_recruiters()

            if args.all or args.jobs_only:
                if not populator.created_companies and not args.jobs_only:
                    logger.error("❌ Cannot create jobs without companies. Use --companies-only first or --all")
                    sys.exit(1)
                await populator.create_jobs()

            if args.all or args.users_only:
                await populator.create_job_seekers()

            if args.all:
                await populator.create_teams()
                await populator.create_sample_applications()

            if not args.validate_only:
                validation = await populator.validate_data()
                if not validation["success"]:
                    logger.error("❌ Data validation failed")
                    for error in validation["errors"]:
                        logger.error(f"   {error}")
                    sys.exit(1)

            report = await populator.generate_summary_report()

            print("\n" + "=" * 80)
            print("🎉 DATABASE POPULATION COMPLETED SUCCESSFULLY!")
            print("=" * 80)
            print(f"Companies Created:  {report['summary']['companies_created']}")
            print(f"Recruiters Created: {report['summary']['recruiters_created']}")
            print(f"Jobs Created:       {report['summary']['jobs_created']}")
            print(f"Users Created:      {report['summary']['users_created']}")
            print(f"Teams Created:      {report['summary']['teams_created']}")

            print("\n🏢 CREATED COMPANIES:")
            for company in report["companies"]:
                print(f"  • {company['name']} — Admin: {company['admin_name']} ({company['admin_email']})")

            if report["recruiters"]:
                print("\n👔 CREATED RECRUITERS:")
                for rec in report["recruiters"]:
                    print(f"  • {rec['name']} ({rec['email']}) @ {rec['company']}")

            print("\n📝 CREATED JOBS:")
            for job in report["jobs"]:
                remote_label = "Remote" if job["remote"] else job["location"]
                print(f"  • {job['title']} at {job['company']}")
                print(f"    {remote_label} | {job['seniority']} | {job['salary_range']}")

            print("\n👤 CREATED USERS:")
            for user in report["users"]:
                print(f"  • {user['name']} ({user['email']}) — {user['seniority']}")
                print(f"    Skills: {', '.join((user['skills'] or [])[:5])}...")

            if report["teams"]:
                print("\n👥 CREATED TEAMS:")
                for team in report["teams"]:
                    print(f"  • {team['name']} @ {team['company']} — {team['members']} members, {team['jobs']} jobs")

            print("\n🔐 LOGIN CREDENTIALS:")
            for cred in report["login_credentials"]:
                label = cred.get("company", "")
                company_str = f" [{label}]" if label else ""
                print(f"  • {cred['type']}{company_str}: {cred['email']} / {cred['password']}")

            print(f"\nAPI Base URL:      {args.api_url}")
            print(f"API Documentation: {args.api_url}/docs")

            if args.output_file:
                with open(args.output_file, 'w') as f:
                    json.dump(report, f, indent=2, default=str)
                print(f"\n📄 Report saved to: {args.output_file}")

        except DatabasePopulationError as e:
            logger.error(f"❌ Population failed: {e}")
            sys.exit(1)
        except Exception as e:
            logger.error(f"❌ Unexpected error: {e}")
            raise


if __name__ == "__main__":
    asyncio.run(main())

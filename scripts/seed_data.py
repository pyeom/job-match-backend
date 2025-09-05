#!/usr/bin/env python3
"""
Database seeding script for Job Match application.
Creates sample jobs and a test user for development and testing.
"""

import asyncio
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import AsyncSessionLocal, engine, Base
from app.models.user import User
from app.models.job import Job
from app.core.security import get_password_hash
from app.services.embedding_service import generate_embedding
import uuid


# Sample job data
SAMPLE_JOBS = [
    {
        "title": "Senior Frontend Developer",
        "company": "Netflix",
        "location": "Los Gatos, CA",
        "description": "Join Netflix to build the next generation of streaming experiences. Work with React, TypeScript, and cutting-edge web technologies.",
        "tags": ["React", "TypeScript", "JavaScript", "CSS", "HTML", "Redux", "GraphQL"],
        "seniority": "Senior",
        "salary_min": 150000,
        "salary_max": 200000,
        "remote": False
    },
    {
        "title": "Full Stack Engineer",
        "company": "Google",
        "location": "Mountain View, CA",
        "description": "Build scalable web applications that serve billions of users. Work with modern tech stack and contribute to Google's core products.",
        "tags": ["Python", "JavaScript", "Go", "React", "Node.js", "PostgreSQL", "GCP"],
        "seniority": "Senior",
        "salary_min": 160000,
        "salary_max": 220000,
        "remote": True
    },
    {
        "title": "Backend Developer",
        "company": "Meta",
        "location": "Menlo Park, CA",
        "description": "Design and implement backend services for Facebook's social platform. Work with distributed systems at massive scale.",
        "tags": ["Python", "Java", "C++", "MySQL", "Redis", "Kubernetes", "Docker"],
        "seniority": "Mid",
        "salary_min": 130000,
        "salary_max": 170000,
        "remote": False
    },
    {
        "title": "Data Scientist",
        "company": "Airbnb",
        "location": "San Francisco, CA",
        "description": "Use machine learning to improve host and guest experiences. Analyze data to drive product decisions and optimize pricing.",
        "tags": ["Python", "R", "SQL", "Machine Learning", "TensorFlow", "Pandas", "Jupyter"],
        "seniority": "Senior",
        "salary_min": 140000,
        "salary_max": 180000,
        "remote": True
    },
    {
        "title": "Junior Frontend Developer",
        "company": "Stripe",
        "location": "Remote",
        "description": "Build beautiful and intuitive payment interfaces. Learn from experienced developers in a fast-growing fintech company.",
        "tags": ["React", "JavaScript", "TypeScript", "CSS", "HTML", "Jest"],
        "seniority": "Junior",
        "salary_min": 80000,
        "salary_max": 110000,
        "remote": True
    },
    {
        "title": "DevOps Engineer",
        "company": "Uber",
        "location": "San Francisco, CA",
        "description": "Manage infrastructure for millions of rides daily. Work with Kubernetes, AWS, and modern deployment technologies.",
        "tags": ["Kubernetes", "Docker", "AWS", "Terraform", "Python", "Linux", "CI/CD"],
        "seniority": "Mid",
        "salary_min": 120000,
        "salary_max": 160000,
        "remote": False
    },
    {
        "title": "Mobile Developer",
        "company": "Spotify",
        "location": "New York, NY",
        "description": "Build the mobile app that brings music to millions of users worldwide. Work with React Native and native iOS/Android.",
        "tags": ["React Native", "Swift", "Kotlin", "JavaScript", "TypeScript", "iOS", "Android"],
        "seniority": "Mid",
        "salary_min": 110000,
        "salary_max": 150000,
        "remote": True
    },
    {
        "title": "Lead Software Engineer",
        "company": "Shopify",
        "location": "Ottawa, Canada",
        "description": "Lead a team of engineers building e-commerce solutions for millions of merchants. Drive technical decisions and mentor developers.",
        "tags": ["Ruby", "Rails", "React", "GraphQL", "MySQL", "Redis", "Leadership"],
        "seniority": "Lead",
        "salary_min": 180000,
        "salary_max": 240000,
        "remote": True
    },
    {
        "title": "Product Manager",
        "company": "Discord",
        "location": "San Francisco, CA",
        "description": "Shape the future of online communities. Work with engineering and design teams to build features used by millions of gamers.",
        "tags": ["Product Management", "Analytics", "User Research", "Agile", "Roadmap Planning"],
        "seniority": "Senior",
        "salary_min": 140000,
        "salary_max": 180000,
        "remote": False
    },
    {
        "title": "UI/UX Designer",
        "company": "Figma",
        "location": "Remote",
        "description": "Design intuitive interfaces for the design tool used by millions of designers and developers worldwide.",
        "tags": ["UI Design", "UX Design", "Figma", "Prototyping", "User Research", "Design Systems"],
        "seniority": "Mid",
        "salary_min": 100000,
        "salary_max": 140000,
        "remote": True
    },
    {
        "title": "Machine Learning Engineer",
        "company": "OpenAI",
        "location": "San Francisco, CA",
        "description": "Build AI systems that push the boundaries of what's possible. Work on cutting-edge ML models and infrastructure.",
        "tags": ["Python", "PyTorch", "TensorFlow", "Machine Learning", "Deep Learning", "CUDA", "GPU"],
        "seniority": "Senior",
        "salary_min": 200000,
        "salary_max": 300000,
        "remote": False
    },
    {
        "title": "Cybersecurity Analyst",
        "company": "CrowdStrike",
        "location": "Austin, TX",
        "description": "Protect organizations from cyber threats. Analyze security incidents and develop threat detection systems.",
        "tags": ["Cybersecurity", "Python", "Linux", "Network Security", "Incident Response", "SIEM"],
        "seniority": "Mid",
        "salary_min": 90000,
        "salary_max": 130000,
        "remote": True
    },
    {
        "title": "Cloud Architect",
        "company": "Amazon",
        "location": "Seattle, WA",
        "description": "Design scalable cloud solutions for enterprise customers. Work with AWS services and help customers migrate to the cloud.",
        "tags": ["AWS", "Cloud Architecture", "Python", "Java", "Serverless", "Microservices", "Docker"],
        "seniority": "Senior",
        "salary_min": 170000,
        "salary_max": 230000,
        "remote": False
    },
    {
        "title": "QA Engineer",
        "company": "Tesla",
        "location": "Palo Alto, CA",
        "description": "Ensure the quality of software that powers Tesla vehicles and energy products. Develop automated testing frameworks.",
        "tags": ["Test Automation", "Python", "Selenium", "API Testing", "CI/CD", "Quality Assurance"],
        "seniority": "Mid",
        "salary_min": 100000,
        "salary_max": 140000,
        "remote": False
    },
    {
        "title": "Blockchain Developer",
        "company": "Coinbase",
        "location": "Remote",
        "description": "Build the future of finance with cryptocurrency and blockchain technology. Develop secure and scalable financial applications.",
        "tags": ["Blockchain", "Solidity", "Web3", "Ethereum", "JavaScript", "Cryptocurrency", "DeFi"],
        "seniority": "Mid",
        "salary_min": 120000,
        "salary_max": 170000,
        "remote": True
    }
]

# Test user data
TEST_USER = {
    "email": "test@example.com",
    "password": "password123",
    "full_name": "Test User",
    "headline": "Full Stack Developer passionate about building great products",
    "skills": ["JavaScript", "Python", "React", "Node.js", "PostgreSQL"],
    "preferred_locations": ["Remote", "San Francisco, CA", "New York, NY"],
    "seniority": "Mid"
}


async def create_tables():
    """Create all database tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ Database tables created")


async def seed_jobs():
    """Create sample job offers."""
    async with AsyncSessionLocal() as session:
        try:
            # Check if jobs already exist
            from sqlalchemy import select
            result = await session.execute(select(Job))
            existing_jobs = result.scalars().all()
            
            if existing_jobs:
                print(f"⚠️  Found {len(existing_jobs)} existing jobs. Skipping job creation.")
                return existing_jobs
            
            print("🏗️  Creating sample job offers...")
            created_jobs = []
            
            for job_data in SAMPLE_JOBS:
                # Generate embedding for the job
                job_text = f"{job_data['title']} at {job_data['company']}. {job_data['description']} Skills: {', '.join(job_data['tags'])}"
                embedding = await generate_embedding(job_text)
                
                # Create job object
                job = Job(
                    id=uuid.uuid4(),
                    title=job_data["title"],
                    company=job_data["company"],
                    location=job_data["location"],
                    description=job_data["description"],
                    tags=job_data["tags"],
                    seniority=job_data["seniority"],
                    salary_min=job_data["salary_min"],
                    salary_max=job_data["salary_max"],
                    remote=job_data["remote"],
                    job_embedding=embedding,
                    is_active=True
                )
                
                session.add(job)
                created_jobs.append(job)
                print(f"  📝 Created job: {job.title} at {job.company}")
            
            await session.commit()
            print(f"✅ Created {len(created_jobs)} sample jobs")
            return created_jobs
            
        except Exception as e:
            await session.rollback()
            print(f"❌ Error creating jobs: {str(e)}")
            raise


async def seed_user():
    """Create test user."""
    async with AsyncSessionLocal() as session:
        try:
            # Check if user already exists
            from sqlalchemy import select
            result = await session.execute(select(User).where(User.email == TEST_USER["email"]))
            existing_user = result.scalar_one_or_none()
            
            if existing_user:
                print(f"⚠️  User {TEST_USER['email']} already exists. Skipping user creation.")
                return existing_user
            
            print("👤 Creating test user...")
            
            # Generate profile embedding
            profile_text = f"{TEST_USER['headline']}. Skills: {', '.join(TEST_USER['skills'])}"
            profile_embedding = await generate_embedding(profile_text)
            
            # Create user with hashed password
            user = User(
                id=uuid.uuid4(),
                email=TEST_USER["email"],
                password_hash=get_password_hash(TEST_USER["password"]),
                full_name=TEST_USER["full_name"],
                headline=TEST_USER["headline"],
                skills=TEST_USER["skills"],
                preferred_locations=TEST_USER["preferred_locations"],
                seniority=TEST_USER["seniority"],
                profile_embedding=profile_embedding
            )
            
            session.add(user)
            await session.commit()
            
            print(f"✅ Created test user: {user.email}")
            print(f"   Password: {TEST_USER['password']}")
            return user
            
        except Exception as e:
            await session.rollback()
            print(f"❌ Error creating user: {str(e)}")
            raise


async def main():
    """Main seeding function."""
    print("🌱 Starting database seeding...")
    
    try:
        # Create tables
        await create_tables()
        
        # Seed user
        user = await seed_user()
        
        # Seed jobs
        jobs = await seed_jobs()
        
        print("\n🎉 Database seeding completed successfully!")
        print(f"   Created user: {user.email if user else 'Already existed'}")
        print(f"   Jobs in database: {len(jobs) if jobs else 'Already existed'}")
        print("\n📝 Login credentials:")
        print(f"   Email: {TEST_USER['email']}")
        print(f"   Password: {TEST_USER['password']}")
        
    except Exception as e:
        print(f"❌ Seeding failed: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
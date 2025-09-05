#!/usr/bin/env python3
"""
Seed script to populate the database with sample companies and jobs
"""
import sys
import os
from datetime import datetime

# Add the parent directory to sys.path to import the app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal, engine, Base
from app.models import Company, Job, User
import uuid

def create_tables():
    """Create all tables"""
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("Tables created successfully!")

def seed_companies():
    """Add sample companies to the database"""
    db = SessionLocal()
    
    try:
        # Check if companies already exist
        if db.query(Company).first():
            print("Companies already exist. Skipping seed...")
            return
            
        print("Seeding companies...")
        
        companies_data = [
            {
                "name": "TechCorp",
                "description": "A leading technology company focused on artificial intelligence and machine learning solutions.",
                "logo_url": "https://example.com/techcorp-logo.png",
                "website": "https://techcorp.example.com",
                "location": "San Francisco, CA",
                "size": "201-500",
                "industry": "Technology",
                "founded_year": 2015
            },
            {
                "name": "DataSoft Solutions",
                "description": "Data analytics and software development company serving enterprise clients worldwide.",
                "logo_url": "https://example.com/datasoft-logo.png",
                "website": "https://datasoft.example.com",
                "location": "New York, NY",
                "size": "51-200",
                "industry": "Software",
                "founded_year": 2012
            },
            {
                "name": "CloudTech Innovations",
                "description": "Cloud infrastructure and DevOps solutions provider for modern businesses.",
                "logo_url": "https://example.com/cloudtech-logo.png",
                "website": "https://cloudtech.example.com",
                "location": "Seattle, WA",
                "size": "11-50",
                "industry": "Cloud Computing",
                "founded_year": 2018
            },
            {
                "name": "StartupHub",
                "description": "Early-stage startup accelerator and venture capital firm.",
                "logo_url": "https://example.com/startuphub-logo.png",
                "website": "https://startuphub.example.com",
                "location": "Austin, TX",
                "size": "1-10",
                "industry": "Venture Capital",
                "founded_year": 2020
            },
            {
                "name": "Global Enterprises Inc",
                "description": "Fortune 500 multinational corporation with diverse business interests.",
                "logo_url": "https://example.com/globalent-logo.png",
                "website": "https://globalent.example.com",
                "location": "Chicago, IL",
                "size": "1000+",
                "industry": "Conglomerate",
                "founded_year": 1985
            }
        ]
        
        created_companies = []
        for company_data in companies_data:
            company = Company(**company_data)
            db.add(company)
            created_companies.append(company)
        
        db.commit()
        print(f"Created {len(created_companies)} companies")
        
        # Add some sample jobs for these companies
        print("Adding sample jobs...")
        
        jobs_data = [
            {
                "title": "Senior Python Developer",
                "company_id": created_companies[0].id,
                "location": "San Francisco, CA",
                "description": "We're looking for an experienced Python developer to join our AI/ML team.",
                "tags": ["Python", "FastAPI", "PostgreSQL", "Docker", "AI/ML"],
                "seniority": "Senior",
                "salary_min": 120000,
                "salary_max": 160000,
                "remote": False
            },
            {
                "title": "Frontend React Developer",
                "company_id": created_companies[1].id,
                "location": "New York, NY",
                "description": "Join our frontend team to build amazing user interfaces with React and TypeScript.",
                "tags": ["React", "TypeScript", "CSS", "JavaScript", "Redux"],
                "seniority": "Mid",
                "salary_min": 90000,
                "salary_max": 120000,
                "remote": True
            },
            {
                "title": "DevOps Engineer",
                "company_id": created_companies[2].id,
                "location": "Seattle, WA",
                "description": "Help us build and maintain cloud infrastructure at scale.",
                "tags": ["AWS", "Kubernetes", "Docker", "Terraform", "CI/CD"],
                "seniority": "Senior",
                "salary_min": 110000,
                "salary_max": 140000,
                "remote": True
            },
            {
                "title": "Full Stack Engineer",
                "company_id": created_companies[3].id,
                "location": "Austin, TX",
                "description": "Early-stage startup looking for a versatile full-stack engineer.",
                "tags": ["JavaScript", "Node.js", "React", "MongoDB", "AWS"],
                "seniority": "Mid",
                "salary_min": 80000,
                "salary_max": 110000,
                "remote": False
            },
            {
                "title": "Data Scientist",
                "company_id": created_companies[4].id,
                "location": "Chicago, IL",
                "description": "Analyze complex datasets to drive business insights and decisions.",
                "tags": ["Python", "R", "SQL", "Machine Learning", "Statistics"],
                "seniority": "Senior",
                "salary_min": 130000,
                "salary_max": 170000,
                "remote": False
            },
            {
                "title": "Junior Backend Developer",
                "company_id": created_companies[0].id,
                "location": "San Francisco, CA",
                "description": "Great opportunity for a junior developer to learn and grow with our team.",
                "tags": ["Python", "Django", "PostgreSQL", "REST APIs"],
                "seniority": "Junior",
                "salary_min": 70000,
                "salary_max": 90000,
                "remote": False
            }
        ]
        
        for job_data in jobs_data:
            job = Job(**job_data)
            db.add(job)
        
        db.commit()
        print(f"Created {len(jobs_data)} jobs")
        
        print("Seed data created successfully!")
        
    except Exception as e:
        print(f"Error seeding data: {e}")
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    print("Starting database seed process...")
    create_tables()
    seed_companies()
    print("Database seed completed!")
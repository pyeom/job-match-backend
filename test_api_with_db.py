#!/usr/bin/env python3
"""
Test script to validate the Company API endpoints work with the database
"""
import sys
import os
import requests

def test_company_endpoints():
    """Test Company API endpoints"""
    base_url = "http://localhost:8000"
    
    print("Testing Company API endpoints...")
    
    # Test companies list endpoint
    try:
        response = requests.get(f"{base_url}/api/v1/companies/")
        print(f"GET /api/v1/companies/ - Status: {response.status_code}")
        if response.status_code == 200:
            companies = response.json()
            print(f"Found {len(companies)} companies:")
            for company in companies[:3]:  # Show first 3 companies
                print(f"  - {company['name']} ({company['industry']}) - {company['job_count']} jobs")
            
            if companies:
                # Test individual company endpoint
                company_id = companies[0]["id"]
                response = requests.get(f"{base_url}/api/v1/companies/{company_id}")
                print(f"\nGET /api/v1/companies/{company_id} - Status: {response.status_code}")
                if response.status_code == 200:
                    company = response.json()
                    print(f"Company details: {company['name']} - {company['description'][:80]}...")
                
                # Test company jobs endpoint
                response = requests.get(f"{base_url}/api/v1/companies/{company_id}/jobs")
                print(f"GET /api/v1/companies/{company_id}/jobs - Status: {response.status_code}")
                if response.status_code == 200:
                    jobs = response.json()
                    print(f"Found {len(jobs)} jobs for {companies[0]['name']}")
                    for job in jobs[:2]:  # Show first 2 jobs
                        print(f"  - {job['title']} ({job['seniority']}) - ${job.get('salary_min', 0)}-${job.get('salary_max', 0)}")
        else:
            print(f"Error: {response.text}")
    except requests.exceptions.ConnectionError:
        print("Error: Cannot connect to API. Make sure FastAPI server is running on localhost:8000")
        print("Run: uvicorn app.main:app --reload")
    except Exception as e:
        print(f"Error testing endpoints: {e}")
    
    print("Company API tests completed!")

if __name__ == "__main__":
    test_company_endpoints()
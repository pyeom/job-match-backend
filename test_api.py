#!/usr/bin/env python3
"""
Simple test script to validate the FastAPI application works
"""
import sys
import os

# Add the current directory to sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient
from app.main import app

def test_basic_endpoints():
    """Test basic API endpoints"""
    client = TestClient(app)
    
    print("Testing FastAPI application...")
    
    # Test root endpoint
    response = client.get("/")
    print(f"GET / - Status: {response.status_code}")
    if response.status_code == 200:
        print(f"Response: {response.json()}")
    
    # Test health endpoint
    response = client.get("/healthz")
    print(f"GET /healthz - Status: {response.status_code}")
    if response.status_code == 200:
        print(f"Response: {response.json()}")
    
    # Test OpenAPI docs
    response = client.get("/docs")
    print(f"GET /docs - Status: {response.status_code}")
    
    # Test companies list endpoint (this might fail without DB)
    try:
        response = client.get("/api/v1/companies/")
        print(f"GET /api/v1/companies/ - Status: {response.status_code}")
        if response.status_code == 200:
            companies = response.json()
            print(f"Found {len(companies)} companies")
    except Exception as e:
        print(f"Companies endpoint failed (expected without DB): {e}")
    
    print("Basic tests completed!")

if __name__ == "__main__":
    test_basic_endpoints()
#!/usr/bin/env python3
"""
Build ESCO skill index for semantic skill matching.

Downloads ESCO skills taxonomy, encodes labels with the same embedding model
used by the rest of the app, and saves a pickled index for fast lookup.

Usage:
    python scripts/build_esco_index.py [--output PATH] [--csv PATH]
"""

import argparse
import csv
import io
import logging
import os
import pickle
import sys
from pathlib import Path
from typing import Dict, List

import numpy as np
import requests

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ESCO skills CSV endpoint (v1.1.1 — stable)
ESCO_SKILLS_URL = (
    "https://ec.europa.eu/esco/api/resource/skill"
    "?language=en&full=false&limit=5000&offset=0"
)

# Fallback: bundled CSV columns we expect
EXPECTED_COLUMNS = {"conceptUri", "preferredLabel", "skillType", "description"}

DEFAULT_OUTPUT = "app/data/esco/skills_index.pkl"

# ESCO skillType mapping to our categories
SKILL_TYPE_MAP = {
    "skill/competence": "technical",
    "knowledge": "technical",
    "transversal": "transversal",
    "language": "soft",
    "attitude": "soft",
}


def fetch_esco_skills_api() -> List[dict]:
    """Fetch skills from ESCO REST API with pagination."""
    skills = []
    offset = 0
    limit = 100

    logger.info("Fetching skills from ESCO API...")
    while True:
        url = (
            f"https://ec.europa.eu/esco/api/search?"
            f"text=*&type=skill&language=en&full=false"
            f"&limit={limit}&offset={offset}"
        )
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning(f"ESCO API request failed at offset {offset}: {e}")
            break

        results = data.get("_embedded", {}).get("results", [])
        if not results:
            break

        for item in results:
            skill_entry = {
                "uri": item.get("uri", ""),
                "label": item.get("title", ""),
                "skillType": item.get("skillType", "skill/competence"),
                "description": item.get("description", ""),
            }
            if skill_entry["label"]:
                skills.append(skill_entry)

        offset += limit
        total = data.get("total", 0)
        logger.info(f"  Fetched {min(offset, total)}/{total} skills...")

        if offset >= total:
            break

    return skills


def load_bundled_csv(csv_path: str) -> List[dict]:
    """Load skills from a bundled CSV file."""
    skills = []
    logger.info(f"Loading skills from CSV: {csv_path}")

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            label = row.get("preferredLabel", "").strip()
            if not label:
                continue
            skills.append({
                "uri": row.get("conceptUri", ""),
                "label": label,
                "skillType": row.get("skillType", "skill/competence"),
                "description": row.get("description", ""),
            })

    return skills


def generate_comprehensive_skills() -> List[dict]:
    """
    Generate a comprehensive skill set covering common technical and soft skills.
    Used as fallback when ESCO API is unavailable and no CSV is bundled.
    """
    logger.info("Generating comprehensive built-in skill set...")

    technical_skills = [
        # Programming Languages
        "Python", "JavaScript", "TypeScript", "Java", "C++", "C#", "Ruby", "Go",
        "Rust", "Swift", "Kotlin", "PHP", "Scala", "Perl", "R", "MATLAB", "Dart",
        "Lua", "Objective-C", "Groovy", "Clojure", "Elixir", "Haskell", "Erlang",
        "F#", "Julia", "Assembly", "COBOL", "Fortran", "Visual Basic",
        # Frontend frameworks
        "React", "Vue.js", "Angular", "Svelte", "Next.js", "Nuxt.js", "Gatsby",
        "Ember.js", "Backbone.js", "jQuery", "Alpine.js", "Solid.js", "Qwik",
        "Astro", "Remix", "HTML", "CSS", "SASS", "SCSS", "LESS", "Tailwind CSS",
        "Bootstrap", "Material UI", "Chakra UI", "Styled Components", "Emotion",
        "Ant Design", "Bulma", "Foundation",
        # Backend frameworks
        "Node.js", "Express.js", "FastAPI", "Django", "Flask", "Spring Boot",
        "Ruby on Rails", "ASP.NET", "Laravel", "Symfony", "NestJS", "Koa",
        "Hapi", "Fastify", "Gin", "Echo", "Fiber", "Phoenix", "Actix",
        # Databases
        "SQL", "MySQL", "PostgreSQL", "MongoDB", "Redis", "Elasticsearch",
        "DynamoDB", "Cassandra", "Oracle Database", "SQLite", "MariaDB", "Neo4j",
        "CouchDB", "Firebase", "Supabase", "InfluxDB", "TimescaleDB",
        "CockroachDB", "PlanetScale", "Memcached",
        # ORMs and query builders
        "Prisma", "Sequelize", "SQLAlchemy", "TypeORM", "Hibernate",
        "Entity Framework", "Drizzle", "Knex.js", "Mongoose",
        # Cloud platforms
        "Amazon Web Services", "Microsoft Azure", "Google Cloud Platform",
        "DigitalOcean", "Heroku", "Vercel", "Netlify", "Cloudflare Workers",
        "IBM Cloud", "Oracle Cloud",
        # DevOps and infrastructure
        "Docker", "Kubernetes", "Terraform", "Ansible", "Jenkins", "GitLab CI/CD",
        "GitHub Actions", "CircleCI", "Travis CI", "ArgoCD", "Helm",
        "Prometheus", "Grafana", "Datadog", "New Relic", "Nagios",
        "Nginx", "Apache HTTP Server", "HAProxy", "Traefik", "Envoy",
        # Version control
        "Git", "GitHub", "GitLab", "Bitbucket", "Subversion",
        # ML and Data Science
        "Machine Learning", "Deep Learning", "TensorFlow", "PyTorch", "Keras",
        "scikit-learn", "Pandas", "NumPy", "SciPy", "Matplotlib", "Seaborn",
        "Jupyter Notebook", "Apache Spark", "Hadoop", "Apache Kafka",
        "Apache Airflow", "MLflow", "Hugging Face Transformers",
        "Natural Language Processing", "Computer Vision", "OpenCV",
        "Reinforcement Learning", "Neural Networks", "Feature Engineering",
        "Data Preprocessing", "Statistical Analysis", "A/B Testing",
        "Recommendation Systems", "Time Series Analysis",
        # Mobile development
        "React Native", "Flutter", "SwiftUI", "Jetpack Compose", "Xamarin",
        "Ionic", "Cordova", "Expo", "Android Development", "iOS Development",
        # API and protocols
        "REST API", "GraphQL", "gRPC", "WebSocket", "SOAP", "OpenAPI",
        "Swagger", "Postman", "API Gateway",
        # Testing
        "Unit Testing", "Integration Testing", "End-to-End Testing", "Jest",
        "Mocha", "Pytest", "JUnit", "Selenium", "Cypress", "Playwright",
        "Test-Driven Development", "Behavior-Driven Development",
        # Security
        "Cybersecurity", "Penetration Testing", "OWASP", "OAuth", "JWT",
        "SSL/TLS", "Encryption", "Identity and Access Management",
        "Network Security", "Application Security", "Security Auditing",
        # Networking
        "TCP/IP", "DNS", "HTTP/HTTPS", "Load Balancing", "CDN",
        "VPN", "Firewall Configuration", "Network Administration",
        # Operating systems
        "Linux", "Unix", "Windows Server", "macOS", "Ubuntu", "CentOS",
        "Red Hat Enterprise Linux",
        # Build tools
        "Webpack", "Vite", "Parcel", "Babel", "Rollup", "esbuild",
        "Gradle", "Maven", "Make", "CMake",
        # Design tools
        "Figma", "Sketch", "Adobe XD", "Adobe Photoshop", "Adobe Illustrator",
        "InVision", "Zeplin", "Canva",
        # Messaging and streaming
        "RabbitMQ", "Apache Kafka", "Redis Pub/Sub", "Amazon SQS",
        "Google Pub/Sub", "NATS", "ZeroMQ",
        # Data formats
        "JSON", "XML", "YAML", "Protocol Buffers", "Apache Avro", "CSV",
        # Blockchain
        "Blockchain", "Ethereum", "Solidity", "Smart Contracts", "Web3",
        # Other technical
        "Microservices Architecture", "Serverless Computing",
        "Event-Driven Architecture", "Domain-Driven Design",
        "Service-Oriented Architecture", "Monolithic Architecture",
        "Continuous Integration", "Continuous Deployment",
        "Infrastructure as Code", "Site Reliability Engineering",
        "System Design", "Distributed Systems", "Concurrency",
        "Parallel Computing", "Caching Strategies",
        "Database Optimization", "Query Optimization",
        "Data Modeling", "ETL", "Data Warehousing",
        "Business Intelligence", "Power BI", "Tableau",
        "Looker", "Apache Superset",
        "Regular Expressions", "Shell Scripting", "Bash",
        "PowerShell", "Vim", "VS Code", "IntelliJ IDEA",
        "Eclipse", "Emacs",
    ]

    soft_skills = [
        "Leadership", "Communication", "Teamwork", "Problem Solving",
        "Analytical Thinking", "Critical Thinking", "Time Management",
        "Project Management", "Agile Methodology", "Scrum", "Kanban",
        "Collaboration", "Mentoring", "Coaching", "Presentation Skills",
        "Negotiation", "Conflict Resolution", "Adaptability",
        "Creativity", "Innovation", "Attention to Detail",
        "Decision Making", "Strategic Thinking", "Customer Service",
        "Interpersonal Skills", "Multitasking", "Organization",
        "Planning", "Prioritization", "Self-Motivation", "Initiative",
        "Emotional Intelligence", "Empathy", "Active Listening",
        "Public Speaking", "Written Communication",
        "Cross-functional Collaboration", "Stakeholder Management",
        "Risk Management", "Change Management", "Lean Methodology",
        "Design Thinking", "User Research", "Requirements Gathering",
        "Process Improvement", "Quality Assurance",
        "Client Relationship Management", "Vendor Management",
        "Budget Management", "Resource Planning",
        "Cultural Awareness", "Diversity and Inclusion",
        "Remote Team Management", "Performance Management",
    ]

    transversal_skills = [
        "Research", "Data Analysis", "Report Writing",
        "Documentation", "Training", "Knowledge Transfer",
        "Troubleshooting", "Root Cause Analysis",
        "Continuous Learning", "Self-Development",
        "Work Ethics", "Professionalism", "Reliability",
        "Flexibility", "Resilience", "Stress Management",
    ]

    skills = []

    for label in technical_skills:
        skills.append({
            "uri": f"builtin:technical:{label.lower().replace(' ', '_')}",
            "label": label,
            "skillType": "skill/competence",
            "description": "",
        })

    for label in soft_skills:
        skills.append({
            "uri": f"builtin:soft:{label.lower().replace(' ', '_')}",
            "label": label,
            "skillType": "transversal",
            "description": "",
        })

    for label in transversal_skills:
        skills.append({
            "uri": f"builtin:transversal:{label.lower().replace(' ', '_')}",
            "label": label,
            "skillType": "transversal",
            "description": "",
        })

    return skills


def categorize_skill(skill_type: str) -> str:
    """Map ESCO skillType to our category."""
    return SKILL_TYPE_MAP.get(skill_type, "technical")


def build_index(skills: List[dict], output_path: str):
    """Encode skill labels and save the index."""
    from sentence_transformers import SentenceTransformer

    labels = [s["label"] for s in skills]
    labels_lower = [l.lower() for l in labels]
    categories = [categorize_skill(s["skillType"]) for s in skills]

    logger.info(f"Encoding {len(labels)} skill labels...")
    model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    embeddings = model.encode(labels, show_progress_bar=True, batch_size=256)
    embeddings = np.array(embeddings, dtype=np.float32)

    # Normalize for cosine similarity via dot product
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1
    embeddings = embeddings / norms

    index = {
        "labels": labels,
        "labels_lower": labels_lower,
        "embeddings": embeddings,
        "categories": categories,
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "wb") as f:
        pickle.dump(index, f, protocol=pickle.HIGHEST_PROTOCOL)

    logger.info(
        f"Saved ESCO index: {len(labels)} skills, "
        f"embeddings shape {embeddings.shape} -> {output_path}"
    )


def main():
    parser = argparse.ArgumentParser(description="Build ESCO skill index")
    parser.add_argument(
        "--output", default=DEFAULT_OUTPUT,
        help="Output pickle path"
    )
    parser.add_argument(
        "--csv", default=None,
        help="Path to bundled ESCO CSV (skips API download)"
    )
    args = parser.parse_args()

    # Try sources in order: bundled CSV → ESCO API → built-in list
    skills = []

    if args.csv and os.path.exists(args.csv):
        skills = load_bundled_csv(args.csv)

    if not skills:
        try:
            skills = fetch_esco_skills_api()
        except Exception as e:
            logger.warning(f"ESCO API fetch failed: {e}")

    if not skills:
        skills = generate_comprehensive_skills()

    if not skills:
        logger.error("No skills data available. Cannot build index.")
        sys.exit(1)

    logger.info(f"Total skills collected: {len(skills)}")
    build_index(skills, args.output)


if __name__ == "__main__":
    main()

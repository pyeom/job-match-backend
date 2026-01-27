"""
Interview Question Predictor Service

AI-powered service for generating likely interview questions based on
job requirements, company profile, and role specifics.
"""

from typing import List, Optional
import logging
from app.models.job import Job
from app.models.company import Company
from app.schemas.interview_questions import (
    InterviewQuestion,
    InterviewQuestionsByCategory,
    InterviewQuestionsResponse
)

logger = logging.getLogger(__name__)


class InterviewPredictorService:
    """Service for predicting interview questions based on job and company data"""

    # Question templates by category
    BEHAVIORAL_TEMPLATES = [
        {
            "question": "Tell me about a time when you had to overcome a significant technical challenge.",
            "difficulty": "medium",
            "tip": "Use the STAR method (Situation, Task, Action, Result). Focus on your problem-solving process and what you learned.",
            "skills": []
        },
        {
            "question": "Describe a situation where you had to collaborate with a difficult team member. How did you handle it?",
            "difficulty": "medium",
            "tip": "Emphasize communication skills, empathy, and positive outcomes. Show emotional intelligence.",
            "skills": ["Communication", "Teamwork"]
        },
        {
            "question": "Give an example of a time when you failed at something. What did you learn?",
            "difficulty": "hard",
            "tip": "Be honest but strategic. Choose a real failure with a positive learning outcome. Show growth mindset.",
            "skills": []
        },
        {
            "question": "How do you prioritize tasks when working on multiple projects with tight deadlines?",
            "difficulty": "easy",
            "tip": "Discuss your time management strategies, prioritization frameworks (e.g., Eisenhower Matrix), and communication with stakeholders.",
            "skills": ["Time Management"]
        },
        {
            "question": "Tell me about a time when you had to learn a new technology or skill quickly for a project.",
            "difficulty": "medium",
            "tip": "Highlight your learning agility, resources you used, and how you applied the new knowledge effectively.",
            "skills": []
        }
    ]

    TECHNICAL_SKILL_QUESTIONS = {
        "Python": [
            {
                "question": "Explain the difference between synchronous and asynchronous programming in Python. When would you use async/await?",
                "difficulty": "medium",
                "tip": "Discuss event loops, I/O-bound vs CPU-bound tasks, and real-world use cases like API calls or database operations."
            },
            {
                "question": "What are Python decorators and how would you implement one?",
                "difficulty": "medium",
                "tip": "Explain higher-order functions, provide a practical example, and mention built-in decorators like @staticmethod or @property."
            },
            {
                "question": "How does Python's garbage collection work? What is reference counting?",
                "difficulty": "hard",
                "tip": "Discuss reference counting, cyclic garbage collection, and when memory issues might occur."
            }
        ],
        "FastAPI": [
            {
                "question": "What are the key advantages of FastAPI over Flask or Django REST Framework?",
                "difficulty": "easy",
                "tip": "Mention automatic API documentation, type hints, async support, and performance benefits."
            },
            {
                "question": "How would you implement authentication and authorization in a FastAPI application?",
                "difficulty": "medium",
                "tip": "Discuss OAuth2, JWT tokens, dependency injection, and security best practices."
            }
        ],
        "PostgreSQL": [
            {
                "question": "Explain the difference between INNER JOIN, LEFT JOIN, and FULL OUTER JOIN.",
                "difficulty": "easy",
                "tip": "Use Venn diagrams or examples to illustrate. Mention when each type is appropriate."
            },
            {
                "question": "How would you optimize a slow-running query in PostgreSQL?",
                "difficulty": "medium",
                "tip": "Discuss EXPLAIN ANALYZE, indexing strategies, query rewriting, and database statistics."
            },
            {
                "question": "What are database transactions and how do you ensure ACID properties?",
                "difficulty": "medium",
                "tip": "Define Atomicity, Consistency, Isolation, Durability. Discuss isolation levels and real-world scenarios."
            }
        ],
        "JavaScript": [
            {
                "question": "Explain the event loop in JavaScript and how asynchronous code execution works.",
                "difficulty": "hard",
                "tip": "Discuss call stack, callback queue, microtasks, and macrotasks. Provide examples with setTimeout and Promises."
            },
            {
                "question": "What is the difference between var, let, and const?",
                "difficulty": "easy",
                "tip": "Explain scope differences (function vs block), hoisting, and when to use each."
            }
        ],
        "React": [
            {
                "question": "Explain the difference between state and props in React.",
                "difficulty": "easy",
                "tip": "Discuss mutability, data flow, and when to use each. Mention hooks like useState."
            },
            {
                "question": "What are React hooks and why were they introduced?",
                "difficulty": "medium",
                "tip": "Explain useState, useEffect, and custom hooks. Discuss advantages over class components."
            }
        ],
        "Docker": [
            {
                "question": "Explain the difference between a Docker image and a Docker container.",
                "difficulty": "easy",
                "tip": "Use analogy (class vs instance). Discuss layers, immutability, and lifecycle."
            },
            {
                "question": "How would you optimize a Dockerfile for production use?",
                "difficulty": "medium",
                "tip": "Discuss multi-stage builds, layer caching, minimal base images, and security scanning."
            }
        ],
        "AWS": [
            {
                "question": "Explain the shared responsibility model in AWS.",
                "difficulty": "easy",
                "tip": "Clarify what AWS manages vs what customers manage. Provide examples for EC2, RDS, S3."
            },
            {
                "question": "How would you design a highly available and scalable architecture on AWS?",
                "difficulty": "hard",
                "tip": "Discuss load balancing, auto-scaling, multi-AZ deployment, and disaster recovery."
            }
        ],
        "Java": [
            {
                "question": "Explain the difference between abstract classes and interfaces in Java.",
                "difficulty": "medium",
                "tip": "Discuss when to use each, multiple inheritance, default methods, and design patterns."
            },
            {
                "question": "What is the Java garbage collector and how does it work?",
                "difficulty": "medium",
                "tip": "Explain heap memory, generational collection, and different GC algorithms (G1, ZGC)."
            }
        ],
        "TypeScript": [
            {
                "question": "What are the benefits of using TypeScript over plain JavaScript?",
                "difficulty": "easy",
                "tip": "Discuss type safety, IDE support, compile-time error detection, and better code documentation."
            },
            {
                "question": "Explain generics in TypeScript and provide a use case.",
                "difficulty": "medium",
                "tip": "Show how generics enable reusable, type-safe code. Provide a practical example like a generic function."
            }
        ],
        "Node.js": [
            {
                "question": "How does Node.js handle concurrency if it's single-threaded?",
                "difficulty": "medium",
                "tip": "Explain the event loop, non-blocking I/O, and worker threads for CPU-intensive tasks."
            }
        ],
        "MongoDB": [
            {
                "question": "When would you choose MongoDB over a relational database?",
                "difficulty": "medium",
                "tip": "Discuss schema flexibility, horizontal scaling, document model, and use cases like content management."
            }
        ],
        "Redis": [
            {
                "question": "What are common use cases for Redis in application architecture?",
                "difficulty": "easy",
                "tip": "Discuss caching, session storage, pub/sub messaging, rate limiting, and real-time analytics."
            }
        ],
        "Kubernetes": [
            {
                "question": "Explain the difference between a Deployment, StatefulSet, and DaemonSet in Kubernetes.",
                "difficulty": "medium",
                "tip": "Discuss use cases for each, stateless vs stateful applications, and pod identity."
            }
        ],
        "Git": [
            {
                "question": "Explain the difference between git merge and git rebase.",
                "difficulty": "medium",
                "tip": "Discuss commit history, when to use each, and potential pitfalls of rebasing."
            }
        ]
    }

    SITUATIONAL_TEMPLATES = {
        "general": [
            {
                "question": "You discover a critical bug in production that's affecting users. Walk me through your response process.",
                "difficulty": "hard",
                "tip": "Demonstrate incident response skills: assess impact, communicate with stakeholders, implement hotfix, root cause analysis, and prevention.",
                "skills": ["Problem-solving", "Communication"]
            },
            {
                "question": "Your team disagrees on the technical approach for a new feature. How would you resolve this?",
                "difficulty": "medium",
                "tip": "Show collaboration skills, data-driven decision making, and ability to build consensus while respecting different viewpoints.",
                "skills": ["Communication", "Leadership"]
            },
            {
                "question": "You're behind schedule on a project. How do you communicate this to stakeholders?",
                "difficulty": "medium",
                "tip": "Emphasize transparency, propose solutions (not just problems), and demonstrate accountability.",
                "skills": ["Communication", "Project Management"]
            }
        ],
        "backend": [
            {
                "question": "Your API is experiencing slow response times. How would you diagnose and fix the issue?",
                "difficulty": "hard",
                "tip": "Walk through systematic debugging: monitoring, profiling, database queries, caching, and load testing.",
                "skills": ["Performance Optimization", "Debugging"]
            },
            {
                "question": "You need to implement a new feature that requires changes to the database schema. How do you approach this?",
                "difficulty": "medium",
                "tip": "Discuss migration strategies, backward compatibility, testing, and rollback plans.",
                "skills": ["Database Design"]
            }
        ],
        "frontend": [
            {
                "question": "Users are reporting that your web application is slow on mobile devices. How would you investigate?",
                "difficulty": "medium",
                "tip": "Discuss performance profiling tools, bundle size optimization, lazy loading, and responsive design considerations.",
                "skills": ["Performance Optimization"]
            }
        ]
    }

    SENIORITY_QUESTIONS = {
        "Entry": [
            {
                "question": "What motivates you to work in software development?",
                "difficulty": "easy",
                "tip": "Be genuine and show passion. Connect your motivation to learning and growth.",
                "skills": []
            },
            {
                "question": "Describe a programming project you're proud of. What challenges did you face?",
                "difficulty": "easy",
                "tip": "Choose a project that demonstrates learning and problem-solving. Focus on your contributions.",
                "skills": []
            }
        ],
        "Junior": [
            {
                "question": "How do you stay current with new technologies and industry trends?",
                "difficulty": "easy",
                "tip": "Mention specific resources: blogs, courses, conferences, open source contributions.",
                "skills": []
            },
            {
                "question": "Describe your experience working in a professional development team.",
                "difficulty": "medium",
                "tip": "Highlight collaboration, code reviews, version control, and learning from senior developers.",
                "skills": ["Teamwork"]
            }
        ],
        "Mid": [
            {
                "question": "Tell me about a time when you mentored a junior developer. What approach did you take?",
                "difficulty": "medium",
                "tip": "Show leadership potential, patience, and ability to explain complex concepts simply.",
                "skills": ["Mentorship", "Communication"]
            },
            {
                "question": "How do you balance writing code quickly with ensuring code quality?",
                "difficulty": "medium",
                "tip": "Discuss testing, code reviews, technical debt, and pragmatic decision-making.",
                "skills": []
            }
        ],
        "Senior": [
            {
                "question": "Describe your experience with system design and architecture decisions.",
                "difficulty": "hard",
                "tip": "Provide specific examples with trade-offs considered, scalability concerns, and long-term maintenance.",
                "skills": ["System Design", "Architecture"]
            },
            {
                "question": "How do you influence technical direction and best practices across your team?",
                "difficulty": "hard",
                "tip": "Demonstrate thought leadership, documentation, code reviews, and building consensus.",
                "skills": ["Leadership", "Communication"]
            },
            {
                "question": "Tell me about a time when you had to make a difficult architectural decision with incomplete information.",
                "difficulty": "hard",
                "tip": "Show risk assessment, gathering data, considering trade-offs, and documenting decisions.",
                "skills": ["Decision Making", "Architecture"]
            }
        ],
        "Lead": [
            {
                "question": "How do you approach technical roadmap planning for your team?",
                "difficulty": "hard",
                "tip": "Discuss balancing business needs, technical debt, innovation, and team capacity.",
                "skills": ["Leadership", "Strategy"]
            },
            {
                "question": "Describe your experience managing technical conflicts within your team.",
                "difficulty": "hard",
                "tip": "Show emotional intelligence, facilitation skills, and ability to reach practical solutions.",
                "skills": ["Leadership", "Conflict Resolution"]
            }
        ],
        "Executive": [
            {
                "question": "How do you align engineering strategy with business objectives?",
                "difficulty": "hard",
                "tip": "Demonstrate understanding of business metrics, stakeholder management, and long-term vision.",
                "skills": ["Strategy", "Business Acumen"]
            },
            {
                "question": "How do you build and scale high-performing engineering teams?",
                "difficulty": "hard",
                "tip": "Discuss hiring, culture, retention, professional development, and organizational design.",
                "skills": ["Leadership", "People Management"]
            }
        ]
    }

    def _generate_technical_questions(
        self,
        job_tags: Optional[List[str]],
        count: int = 4
    ) -> List[InterviewQuestion]:
        """Generate technical questions based on job skills"""
        questions = []

        if not job_tags:
            return questions

        # Prioritize skills that have question templates
        available_skills = [
            skill for skill in job_tags
            if skill in self.TECHNICAL_SKILL_QUESTIONS
        ]

        # Generate questions for each matched skill
        for skill in available_skills[:count]:
            skill_questions = self.TECHNICAL_SKILL_QUESTIONS[skill]
            # Take first question for each skill
            if skill_questions:
                template = skill_questions[0]
                questions.append(InterviewQuestion(
                    question=template["question"],
                    category="technical",
                    difficulty=template["difficulty"],
                    tip=template["tip"],
                    related_skills=[skill]
                ))

        # If we need more questions, add from popular skills
        if len(questions) < count:
            popular_skills = ["Python", "JavaScript", "Docker", "PostgreSQL"]
            for skill in popular_skills:
                if skill not in available_skills and skill in self.TECHNICAL_SKILL_QUESTIONS:
                    skill_questions = self.TECHNICAL_SKILL_QUESTIONS[skill]
                    if skill_questions and len(questions) < count:
                        template = skill_questions[0]
                        questions.append(InterviewQuestion(
                            question=template["question"],
                            category="technical",
                            difficulty=template["difficulty"],
                            tip=template["tip"],
                            related_skills=[skill]
                        ))

        return questions[:count]

    def _generate_behavioral_questions(self, count: int = 3) -> List[InterviewQuestion]:
        """Generate behavioral interview questions"""
        questions = []

        for template in self.BEHAVIORAL_TEMPLATES[:count]:
            questions.append(InterviewQuestion(
                question=template["question"],
                category="behavioral",
                difficulty=template["difficulty"],
                tip=template["tip"],
                related_skills=template["skills"]
            ))

        return questions

    def _generate_situational_questions(
        self,
        job_tags: Optional[List[str]],
        count: int = 3
    ) -> List[InterviewQuestion]:
        """Generate situational questions based on role type"""
        questions = []

        # Determine role type from skills
        backend_skills = ["Python", "FastAPI", "Django", "Node.js", "PostgreSQL", "MongoDB", "Redis"]
        frontend_skills = ["React", "JavaScript", "TypeScript", "Vue", "Angular"]

        is_backend = any(skill in (job_tags or []) for skill in backend_skills)
        is_frontend = any(skill in (job_tags or []) for skill in frontend_skills)

        # Add role-specific questions
        if is_backend and "backend" in self.SITUATIONAL_TEMPLATES:
            for template in self.SITUATIONAL_TEMPLATES["backend"][:2]:
                questions.append(InterviewQuestion(
                    question=template["question"],
                    category="situational",
                    difficulty=template["difficulty"],
                    tip=template["tip"],
                    related_skills=template["skills"]
                ))

        if is_frontend and "frontend" in self.SITUATIONAL_TEMPLATES:
            for template in self.SITUATIONAL_TEMPLATES["frontend"][:1]:
                questions.append(InterviewQuestion(
                    question=template["question"],
                    category="situational",
                    difficulty=template["difficulty"],
                    tip=template["tip"],
                    related_skills=template["skills"]
                ))

        # Fill remaining with general questions
        remaining = count - len(questions)
        for template in self.SITUATIONAL_TEMPLATES["general"][:remaining]:
            questions.append(InterviewQuestion(
                question=template["question"],
                category="situational",
                difficulty=template["difficulty"],
                tip=template["tip"],
                related_skills=template["skills"]
            ))

        return questions[:count]

    def _generate_seniority_questions(
        self,
        seniority: Optional[str],
        count: int = 2
    ) -> List[InterviewQuestion]:
        """Generate questions based on seniority level"""
        questions = []

        if not seniority:
            seniority = "Mid"

        # Normalize seniority
        seniority_normalized = seniority.capitalize()
        if seniority_normalized not in self.SENIORITY_QUESTIONS:
            seniority_normalized = "Mid"

        templates = self.SENIORITY_QUESTIONS[seniority_normalized]
        for template in templates[:count]:
            questions.append(InterviewQuestion(
                question=template["question"],
                category="behavioral",
                difficulty=template["difficulty"],
                tip=template["tip"],
                related_skills=template["skills"]
            ))

        return questions

    def _generate_company_questions(
        self,
        company_name: str,
        count: int = 3
    ) -> List[InterviewQuestion]:
        """Generate company-specific questions"""
        questions = [
            InterviewQuestion(
                question=f"What interests you most about working at {company_name}?",
                category="company_specific",
                difficulty="easy",
                tip=f"Research {company_name}'s mission, values, recent news, and products. Show genuine interest and align your values with theirs.",
                related_skills=[]
            ),
            InterviewQuestion(
                question=f"What do you know about {company_name}'s products/services?",
                category="company_specific",
                difficulty="easy",
                tip=f"Demonstrate that you've done your homework. Mention specific products, their market position, or recent launches.",
                related_skills=[]
            ),
            InterviewQuestion(
                question="Why do you want to leave your current position?",
                category="company_specific",
                difficulty="medium",
                tip="Frame positively - focus on what you're moving toward (growth, challenges, learning) rather than what you're leaving behind.",
                related_skills=[]
            )
        ]

        return questions[:count]

    def _generate_preparation_tips(
        self,
        job_title: str,
        job_tags: Optional[List[str]],
        seniority: Optional[str],
        company_name: str
    ) -> List[str]:
        """Generate personalized preparation tips"""
        tips = []

        # Skill-specific tips
        if job_tags:
            primary_skills = ", ".join(job_tags[:3])
            tips.append(f"Review core concepts and best practices for {primary_skills}")

            if "Python" in job_tags and "FastAPI" in job_tags:
                tips.append("Practice implementing RESTful APIs with FastAPI, including async operations and dependency injection")
            elif "React" in job_tags:
                tips.append("Prepare to discuss component lifecycle, state management, and React best practices")

            if any(db in job_tags for db in ["PostgreSQL", "MongoDB", "MySQL"]):
                tips.append("Be ready to discuss database design, optimization, and query performance")

        # Seniority-specific tips
        if seniority and seniority.lower() in ["senior", "lead", "executive"]:
            tips.append("Prepare examples demonstrating leadership, mentorship, and system design experience")
            tips.append("Be ready to discuss architectural decisions, trade-offs, and technical strategy")
        else:
            tips.append("Prepare examples of projects showing your technical growth and problem-solving abilities")

        # Company research
        tips.append(f"Research {company_name}'s recent news, product launches, and company culture")

        # General tips
        tips.append("Practice explaining technical concepts clearly to non-technical audiences")
        tips.append(f"Prepare thoughtful questions about the {job_title} role, team structure, and growth opportunities")
        tips.append("Review your resume and be ready to discuss each project in detail")

        return tips[:6]  # Return top 6 tips

    def _generate_summary(
        self,
        job_title: str,
        company_name: str,
        job_tags: Optional[List[str]],
        seniority: Optional[str]
    ) -> str:
        """Generate interview summary"""

        skills_str = "technical skills"
        if job_tags and len(job_tags) > 0:
            if len(job_tags) <= 3:
                skills_str = ", ".join(job_tags)
            else:
                skills_str = ", ".join(job_tags[:3]) + ", and more"

        seniority_str = seniority if seniority else "your experience level"

        summary = (
            f"Based on the {job_title} position at {company_name}, expect a comprehensive interview "
            f"focusing on {skills_str}. The interview will likely assess your {seniority_str} capabilities "
            f"through technical questions, behavioral scenarios, and problem-solving exercises. "
            f"Be prepared to discuss your past projects, demonstrate your technical expertise, "
            f"and show cultural fit with the organization."
        )

        return summary

    def generate_interview_questions(
        self,
        job: Job,
        company: Company
    ) -> InterviewQuestionsResponse:
        """
        Generate AI-powered interview question predictions for a specific job.

        Analyzes the job requirements, required skills, seniority level, and company
        information to predict likely interview questions across multiple categories.

        Args:
            job: Job model instance with requirements and skills
            company: Company model instance

        Returns:
            InterviewQuestionsResponse with categorized questions and preparation tips
        """

        try:
            # Generate questions by category
            technical_questions = self._generate_technical_questions(
                job_tags=job.tags,
                count=4
            )

            behavioral_questions = self._generate_behavioral_questions(count=3)

            seniority_questions = self._generate_seniority_questions(
                seniority=job.seniority,
                count=2
            )

            # Combine behavioral and seniority questions
            all_behavioral = behavioral_questions + seniority_questions

            situational_questions = self._generate_situational_questions(
                job_tags=job.tags,
                count=3
            )

            company_questions = self._generate_company_questions(
                company_name=company.name,
                count=3
            )

            # Organize by category
            questions_by_category = InterviewQuestionsByCategory(
                behavioral=all_behavioral,
                technical=technical_questions,
                situational=situational_questions,
                company_specific=company_questions
            )

            # Generate preparation tips
            preparation_tips = self._generate_preparation_tips(
                job_title=job.title,
                job_tags=job.tags,
                seniority=job.seniority,
                company_name=company.name
            )

            # Generate summary
            summary = self._generate_summary(
                job_title=job.title,
                company_name=company.name,
                job_tags=job.tags,
                seniority=job.seniority
            )

            # Calculate total questions
            total_questions = (
                len(all_behavioral) +
                len(technical_questions) +
                len(situational_questions) +
                len(company_questions)
            )

            return InterviewQuestionsResponse(
                job_id=job.id,
                job_title=job.title,
                company_name=company.name,
                summary=summary,
                questions=questions_by_category,
                total_questions=total_questions,
                preparation_tips=preparation_tips
            )

        except Exception as e:
            logger.error(f"Error generating interview questions for job {job.id}: {e}")
            raise


# Global instance
interview_predictor_service = InterviewPredictorService()

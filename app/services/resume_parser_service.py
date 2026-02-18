"""
Re-export shim for backward compatibility.

All resume parsing logic has moved to app.services.resume_parser package.
This module re-exports the public API so existing imports continue to work.
"""

from app.services.resume_parser import resume_parser_service
from app.services.resume_parser.coordinator import ResumeParserCoordinator as ResumeParserService

__all__ = ["resume_parser_service", "ResumeParserService"]

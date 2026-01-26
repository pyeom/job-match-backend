"""
Document parsing service for extracting text from PDF and DOC/DOCX files.
"""
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class DocumentParser:
    """Service for parsing and extracting text from documents."""

    def extract_text(self, file_content: bytes, mime_type: str) -> Optional[str]:
        """
        Extract text from document content.

        Args:
            file_content: Document content as bytes
            mime_type: MIME type of the document

        Returns:
            Extracted text or None if extraction fails
        """
        try:
            if mime_type == "application/pdf":
                return self._extract_from_pdf(file_content)
            elif mime_type in [
                "application/msword",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ]:
                return self._extract_from_doc(file_content, mime_type)
            else:
                logger.warning(f"Unsupported MIME type for text extraction: {mime_type}")
                return None
        except Exception as e:
            logger.error(f"Error extracting text from document: {e}")
            return None

    def _extract_from_pdf(self, file_content: bytes) -> Optional[str]:
        """
        Extract text from PDF using PyPDF2.

        Args:
            file_content: PDF content as bytes

        Returns:
            Extracted text or None if extraction fails
        """
        try:
            from PyPDF2 import PdfReader
            from io import BytesIO

            pdf_file = BytesIO(file_content)
            reader = PdfReader(pdf_file)

            text_parts = []
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    text_parts.append(text)

            extracted_text = "\n\n".join(text_parts)
            return extracted_text.strip() if extracted_text else None

        except ImportError:
            logger.warning("PyPDF2 not installed. PDF text extraction disabled.")
            return None
        except Exception as e:
            logger.error(f"Error extracting text from PDF: {e}")
            return None

    def _extract_from_doc(self, file_content: bytes, mime_type: str) -> Optional[str]:
        """
        Extract text from DOC/DOCX using python-docx.

        Args:
            file_content: Document content as bytes
            mime_type: MIME type (to differentiate DOC from DOCX)

        Returns:
            Extracted text or None if extraction fails
        """
        try:
            from io import BytesIO

            # DOCX extraction (modern format)
            if mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
                try:
                    from docx import Document

                    doc_file = BytesIO(file_content)
                    document = Document(doc_file)

                    text_parts = []
                    for paragraph in document.paragraphs:
                        if paragraph.text:
                            text_parts.append(paragraph.text)

                    extracted_text = "\n\n".join(text_parts)
                    return extracted_text.strip() if extracted_text else None

                except ImportError:
                    logger.warning("python-docx not installed. DOCX text extraction disabled.")
                    return None

            # DOC extraction (legacy format)
            elif mime_type == "application/msword":
                try:
                    import textract

                    # textract can handle DOC files
                    text = textract.process(BytesIO(file_content))
                    return text.decode('utf-8').strip() if text else None

                except ImportError:
                    logger.warning("textract not installed. DOC text extraction disabled.")
                    return None
                except Exception as e:
                    logger.error(f"Error extracting text from DOC: {e}")
                    # DOC extraction can be unreliable, return None gracefully
                    return None

        except Exception as e:
            logger.error(f"Error extracting text from document: {e}")
            return None

    def extract_metadata(self, file_content: bytes, mime_type: str) -> dict:
        """
        Extract metadata from document (title, author, etc.).

        Args:
            file_content: Document content as bytes
            mime_type: MIME type of the document

        Returns:
            Dictionary of metadata
        """
        metadata = {}

        try:
            if mime_type == "application/pdf":
                metadata = self._extract_pdf_metadata(file_content)
            elif mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
                metadata = self._extract_docx_metadata(file_content)
        except Exception as e:
            logger.error(f"Error extracting metadata: {e}")

        return metadata

    def _extract_pdf_metadata(self, file_content: bytes) -> dict:
        """Extract metadata from PDF."""
        try:
            from PyPDF2 import PdfReader
            from io import BytesIO

            pdf_file = BytesIO(file_content)
            reader = PdfReader(pdf_file)

            metadata = {}
            if reader.metadata:
                metadata = {
                    'title': reader.metadata.get('/Title', ''),
                    'author': reader.metadata.get('/Author', ''),
                    'subject': reader.metadata.get('/Subject', ''),
                    'creator': reader.metadata.get('/Creator', ''),
                }

            metadata['num_pages'] = len(reader.pages)
            return metadata

        except Exception as e:
            logger.error(f"Error extracting PDF metadata: {e}")
            return {}

    def _extract_docx_metadata(self, file_content: bytes) -> dict:
        """Extract metadata from DOCX."""
        try:
            from docx import Document
            from io import BytesIO

            doc_file = BytesIO(file_content)
            document = Document(doc_file)

            metadata = {}
            core_properties = document.core_properties

            metadata = {
                'title': core_properties.title or '',
                'author': core_properties.author or '',
                'subject': core_properties.subject or '',
                'keywords': core_properties.keywords or '',
            }

            return metadata

        except Exception as e:
            logger.error(f"Error extracting DOCX metadata: {e}")
            return {}


# Singleton instance
document_parser = DocumentParser()

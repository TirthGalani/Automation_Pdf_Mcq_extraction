from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from app.validation.models import ValidationIssue


class ValidationContext:
    """Carries environment and global batch/result context for validators."""
    def __init__(
        self,
        file_name: str = "",
        total_pages: int = 1,
        source_language: str = "Original",
        target_language: str = "Original",
        all_questions: Optional[List[Any]] = None,
        images_dir: Optional[str] = None,
        expected_option_labels: Optional[List[str]] = None,
    ):
        self.file_name = file_name
        self.total_pages = total_pages
        self.source_language = source_language
        self.target_language = target_language
        self.all_questions = all_questions or []
        self.images_dir = images_dir
        self.expected_option_labels = expected_option_labels or ["A", "B", "C", "D"]
        self.image_hashes: Dict[str, List[str]] = {}  # hash -> list of question numbers
        self.seen_texts: Dict[str, str] = {}  # normalized text -> question number


class BaseValidator(ABC):
    """Abstract base class for all independent question validators."""

    @abstractmethod
    def validate(self, question: Any, context: ValidationContext) -> List[ValidationIssue]:
        """Validates a single question against specific rules and returns detected issues."""
        pass

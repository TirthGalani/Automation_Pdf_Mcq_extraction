from typing import Dict, List, Optional, Any, Union
from enum import Enum
from pydantic import BaseModel, Field


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


class QualityStatus(str, Enum):
    PERFECT = "PERFECT"
    WARNING = "WARNING"
    FAULT = "FAULT"
    CRITICAL = "CRITICAL"


class ErrorCode(str, Enum):
    # Question Structure & Text
    QUESTION_MISSING = "QUESTION_MISSING"
    QUESTION_EMPTY = "QUESTION_EMPTY"
    QUESTION_INCOMPLETE = "QUESTION_INCOMPLETE"
    QUESTION_TRUNCATED = "QUESTION_TRUNCATED"
    QUESTION_OCR_ERROR = "QUESTION_OCR_ERROR"
    QUESTION_TEXT_SUSPICIOUS = "QUESTION_TEXT_SUSPICIOUS"

    # Question Number & Sequence
    QUESTION_NUMBER_MISSING = "QUESTION_NUMBER_MISSING"
    QUESTION_NUMBER_DUPLICATE = "QUESTION_NUMBER_DUPLICATE"
    QUESTION_NUMBER_FORMAT_ERROR = "QUESTION_NUMBER_FORMAT_ERROR"
    EXTRA_QUESTION = "EXTRA_QUESTION"
    MISSING_QUESTION = "MISSING_QUESTION"

    # MCQ & Options
    MISSING_OPTION = "MISSING_OPTION"
    EMPTY_OPTION = "EMPTY_OPTION"
    DUPLICATE_OPTION = "DUPLICATE_OPTION"
    INVALID_OPTION_LABEL = "INVALID_OPTION_LABEL"
    OPTION_ORDER_ERROR = "OPTION_ORDER_ERROR"
    OPTION_MIXING_ERROR = "OPTION_MIXING_ERROR"

    # Answer Validation
    ANSWER_MISSING = "ANSWER_MISSING"
    INVALID_ANSWER = "INVALID_ANSWER"

    # LaTeX
    LATEX_UNCLOSED = "LATEX_UNCLOSED"
    LATEX_BRACE_ERROR = "LATEX_BRACE_ERROR"
    LATEX_DELIMITER_ERROR = "LATEX_DELIMITER_ERROR"
    LATEX_RENDER_ERROR = "LATEX_RENDER_ERROR"
    LATEX_SUSPICIOUS = "LATEX_SUSPICIOUS"

    # Image & Diagrams
    IMAGE_MISSING = "IMAGE_MISSING"
    IMAGE_EXTRACTION_ERROR = "IMAGE_EXTRACTION_ERROR"
    IMAGE_CROP_INVALID = "IMAGE_CROP_INVALID"
    IMAGE_CROP_TOO_SMALL = "IMAGE_CROP_TOO_SMALL"
    IMAGE_CROP_TOO_LARGE = "IMAGE_CROP_TOO_LARGE"
    IMAGE_CROP_OUT_OF_BOUNDS = "IMAGE_CROP_OUT_OF_BOUNDS"
    IMAGE_CROP_MOSTLY_BLANK = "IMAGE_CROP_MOSTLY_BLANK"
    IMAGE_CROP_SUSPICIOUS = "IMAGE_CROP_SUSPICIOUS"
    IMAGE_ASSOCIATION_WARNING = "IMAGE_ASSOCIATION_WARNING"
    EXTRA_IMAGE = "EXTRA_IMAGE"
    DUPLICATE_IMAGE = "DUPLICATE_IMAGE"
    POSSIBLE_DUPLICATE_IMAGE = "POSSIBLE_DUPLICATE_IMAGE"

    # OCR & Duplication
    OCR_SUSPICIOUS = "OCR_SUSPICIOUS"
    DUPLICATE_QUESTION = "DUPLICATE_QUESTION"
    POSSIBLE_DUPLICATE_QUESTION = "POSSIBLE_DUPLICATE_QUESTION"

    # Solution
    SOLUTION_MISSING = "SOLUTION_MISSING"
    SOLUTION_MIXING = "SOLUTION_MIXING"
    SOLUTION_TRUNCATED = "SOLUTION_TRUNCATED"

    # Translation
    TRANSLATION_MISSING = "TRANSLATION_MISSING"
    TRANSLATION_INCOMPLETE = "TRANSLATION_INCOMPLETE"


class ValidationIssue(BaseModel):
    code: str
    severity: str = "ERROR"  # CRITICAL, ERROR, WARNING, INFO
    field: str = "question"
    message: str
    details: Optional[Dict[str, Any]] = None


class ValidationChecks(BaseModel):
    question: bool = True
    mcq: bool = True
    latex: bool = True
    image: bool = True
    answer: bool = True
    solution: bool = True
    translation: bool = True


class QuestionValidation(BaseModel):
    status: str = "PERFECT"  # PERFECT, WARNING, FAULT, CRITICAL
    score: float = 100.0
    checks: ValidationChecks = Field(default_factory=ValidationChecks)
    errors: List[ValidationIssue] = Field(default_factory=list)


class ValidationSummary(BaseModel):
    total_questions: int = 0
    perfect_questions: int = 0
    warning_questions: int = 0
    faulty_questions: int = 0
    critical_questions: int = 0

    missing_questions: int = 0
    missing_question_numbers: List[Union[str, int]] = Field(default_factory=list)
    extra_questions: int = 0
    extra_question_numbers: List[Union[str, int]] = Field(default_factory=list)

    mcq_faults: int = 0
    missing_options: int = 0
    missing_options_breakdown: Dict[str, int] = Field(
        default_factory=lambda: {"A": 0, "B": 0, "C": 0, "D": 0}
    )
    empty_options: int = 0
    empty_options_breakdown: Dict[str, int] = Field(
        default_factory=lambda: {"A": 0, "B": 0, "C": 0, "D": 0}
    )
    duplicate_options: int = 0
    invalid_answers: int = 0

    latex_questions: int = 0
    valid_latex: int = 0
    latex_faults: int = 0
    latex_unclosed: int = 0
    latex_brace_errors: int = 0
    latex_delimiter_errors: int = 0
    latex_render_errors: int = 0

    total_images_expected_or_found: int = 0
    valid_images: int = 0
    image_faults: int = 0
    missing_images: int = 0
    image_crop_errors: int = 0
    image_extraction_errors: int = 0
    extra_images: int = 0
    duplicate_images: int = 0

    ocr_warnings: int = 0
    duplicate_questions: int = 0

    quality_score: float = 100.0

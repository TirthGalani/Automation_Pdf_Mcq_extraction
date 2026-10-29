from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field


class OptionDetail(BaseModel):
    original: Optional[str] = ""
    translated: Optional[str] = ""
    has_image: bool = False
    image_url: Optional[str] = None
    image_box: Optional[Any] = None
    page_number: Optional[int] = None


class TopicItem(BaseModel):
    id: Union[str, int]
    chapter_number: Optional[Union[str, int]] = ""
    chapter_name: Optional[str] = ""
    topic: str
    description: Optional[str] = ""


class QuestionItem(BaseModel):
    question_number: str = "1"
    page_number: Optional[int] = 1
    original_question: str = ""
    translated_question: str = ""
    original_language: Optional[str] = ""
    target_language: Optional[str] = ""
    options: Optional[Dict[str, Optional[OptionDetail]]] = Field(
        default_factory=lambda: {
            "A": OptionDetail(),
            "B": OptionDetail(),
            "C": OptionDetail(),
            "D": OptionDetail(),
        }
    )
    answer: Optional[str] = None
    solution: Optional[str] = ""
    question_type: str = "MCQ"  # MCQ, TRUE_FALSE, MATCH_THE_COLUMN, NUMERIC, ASSERTION_REASON
    has_question_image: bool = False
    image_url: Optional[str] = None
    image_box: Optional[Any] = None
    has_solution_image: bool = False
    solution_image_url: Optional[str] = None
    solution_image_box: Optional[Any] = None
    solution_page_number: Optional[int] = None
    answer_image_url: Optional[str] = None
    difficulty: int = 0  # 0: Easy, -1: Medium, 1: Hard
    marks: int = 4  # 4 Marks default for questions
    status: str = "complete"  # complete, matching_error
    topic_id: Optional[Union[str, int]] = None
    topic: Optional[str] = None
    chapter_number: Optional[Union[str, int]] = None
    chapter_name: Optional[str] = None
    subject: Optional[str] = None
    # Paragraph / Comprehension Passage Type fields (JEE Advanced)
    paragraph: Optional[str] = ""
    paragraph_id: Optional[str] = None
    is_paragraph_head: bool = False
    paragraph_image_url: Optional[str] = None
    paragraph_image_box: Optional[Any] = None
    # Matching Column Type fields (JEE Advanced)
    column_i: Optional[str] = ""
    column_ii: Optional[str] = ""
    column_i_a_image_url: Optional[str] = None
    column_i_b_image_url: Optional[str] = None
    column_i_c_image_url: Optional[str] = None
    column_i_d_image_url: Optional[str] = None
    # Solution Matching & Verification fields
    matched_solution_file: Optional[str] = None
    solution_verified: bool = False
    verification_status: str = "unverified"  # verified, matched, mismatch, no_solution
    verification_details: Optional[str] = None


class ExtractionResult(BaseModel):
    file_name: str
    chapter_number: Optional[Union[str, int]] = ""
    chapter_name: Optional[str] = ""
    subject: Optional[str] = ""
    topics: List[TopicItem] = []
    total_questions: int = 0
    total_pages_scanned: int = 1
    questions: List[QuestionItem] = []
    source_language: str = "Gujarati"
    target_language: str = "English"
    processing_time_seconds: float = 0.0
    status: str = "completed"  # completed, partial, failed
    is_partial: bool = False   # True when processing stopped due to model quota exhaustion
    error_message: Optional[str] = None
    model_used: Optional[str] = None
    is_advance: bool = False   # True if detected as JEE Advanced (qualifies for 3 Excel files)
    matching_errors: int = 0   # Number of solutions that could not be matched to questions
    skipped_questions: List[Dict[str, Any]] = []  # Deprecated: Zero questions are skipped; retained for schema compatibility
    textbook_filename: Optional[str] = None
    has_textbook: bool = False
    # Solution & Verification metadata
    matched_solution_filename: Optional[str] = None
    has_solution: bool = False
    total_solutions: int = 0
    verified_solutions_count: int = 0
    unmatched_solutions_count: int = 0
    verification_rate: Optional[float] = 0.0


class BatchJobProgress(BaseModel):
    job_id: str
    total_files: int
    processed_files: int = 0
    current_file: Optional[str] = None
    current_page: Optional[int] = 0
    total_pages: Optional[int] = 0
    extracted_questions_count: Optional[int] = 0
    progress_message: Optional[str] = None
    status: str = "queued"  # queued, processing, completed, failed, partial
    results: List[ExtractionResult] = []
    created_at: str
    completed_at: Optional[str] = None
    error: Optional[str] = None
    # Model tracking fields
    active_model: Optional[str] = None          # Currently active model name
    fallback_model: Optional[str] = None        # Configured fallback model name
    model_status: Optional[str] = None          # e.g. "Flash active", "Pro active", "Both exhausted"
    warnings: List[str] = []                    # List of warning messages (quota switches, matching errors, etc.)
    matching_errors: int = 0                    # Total count of solution matching failures
    textbook_filename: Optional[str] = None
    has_textbook: bool = False
    extracted_topics_count: int = 0
    solution_filename: Optional[str] = None
    has_solution: bool = False
    solution_count: int = 0
    pairwise_verification: List[Dict[str, Any]] = []


class HealthResponse(BaseModel):
    status: str
    api_key_configured: bool
    version: str


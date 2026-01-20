"""LLM package"""

from .client import ClaudeClient, estimate_tokens, estimate_image_tokens
from .prompts_multi import (
    IMAGE_CLASSIFICATION_SYSTEM_PROMPT,
    IMAGE_CLASSIFICATION_USER_PROMPT,
    METADATA_ONLY_SYSTEM_PROMPT,
    METADATA_ONLY_USER_PROMPT,
    SEMANTIC_GROUPING_SYSTEM_PROMPT,
    SEMANTIC_GROUPING_USER_PROMPT,
    METADATA_EXTRACTION_SYSTEM_PROMPT,
    METADATA_EXTRACTION_USER_PROMPT,
    DYNAMIC_SECTION_EXTRACTION_SYSTEM_PROMPT,
    DYNAMIC_SECTION_EXTRACTION_USER_PROMPT,
    format_image_classification_prompt,
)
from .image_classifier import ImageClassifier, classify_images
from .kb_generator import MultiCallKBGenerator, generate_knowledge_base

__all__ = [
    "ClaudeClient",
    "estimate_tokens",
    "estimate_image_tokens",
    "IMAGE_CLASSIFICATION_SYSTEM_PROMPT",
    "IMAGE_CLASSIFICATION_USER_PROMPT",
    "METADATA_ONLY_SYSTEM_PROMPT",
    "METADATA_ONLY_USER_PROMPT",
    "SEMANTIC_GROUPING_SYSTEM_PROMPT",
    "SEMANTIC_GROUPING_USER_PROMPT",
    "METADATA_EXTRACTION_SYSTEM_PROMPT",
    "METADATA_EXTRACTION_USER_PROMPT",
    "DYNAMIC_SECTION_EXTRACTION_SYSTEM_PROMPT",
    "DYNAMIC_SECTION_EXTRACTION_USER_PROMPT",
    "format_image_classification_prompt",
    "ImageClassifier",
    "classify_images",
    "MultiCallKBGenerator",
    "generate_knowledge_base",
]

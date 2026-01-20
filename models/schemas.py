"""
Pydantic models for consistent JSON schema

These models ensure all output follows a strict, consistent structure
that can be easily transformed into other formats.
"""

from typing import Optional, List, Any
from pydantic import BaseModel, Field
from datetime import datetime


# ============================================================================
# Image Models
# ============================================================================

class ImageInfo(BaseModel):
    """Basic image information from mapping.json"""
    index: int
    src: str
    alt: str = ""
    title: str = ""
    width: Optional[int] = None
    height: Optional[int] = None
    local_path: str
    download_status: str = "success"
    file_size: int = 0
    file_type: Optional[str] = None


class FilteredImage(BaseModel):
    """Image after pre-filtering"""
    index: int
    local_path: str
    src: str
    alt: str = ""
    width: Optional[int] = None
    height: Optional[int] = None
    file_size: int = 0
    file_type: str = ""


class SkippedImage(BaseModel):
    """Image that was skipped during filtering"""
    index: int
    local_path: str
    skip_reason: str
    pattern_matched: Optional[str] = None
    dimensions: Optional[str] = None


class ImageDescription(BaseModel):
    """Image with classification and description from Claude"""
    image_id: str
    local_path: str
    category: str
    description: str
    extracted_text: Optional[str] = None
    stats: Optional[List[dict]] = None
    suggested_section: Optional[str] = None


class ExcludedImage(BaseModel):
    """Image excluded by Claude classification"""
    image_id: str
    local_path: str
    category: str
    exclusion_reason: str


class SectionImage(BaseModel):
    """Image reference within a section"""
    image_id: str
    local_path: str
    category: str
    description: str


# ============================================================================
# Preprocessing Output Models
# ============================================================================

class CleaningStats(BaseModel):
    """Statistics from HTML cleaning"""
    original_dom_size: int
    cleaned_dom_size: int
    estimated_tokens: int
    elements_removed: dict = Field(default_factory=dict)


class ImageFilteringStats(BaseModel):
    """Statistics from image filtering"""
    total_original: int
    passed_filter: int
    skipped: int
    skipped_reasons: dict = Field(default_factory=dict)


class SourceInfo(BaseModel):
    """Source page information"""
    url: str
    page_title: str
    scraped_at: str


class PreprocessedData(BaseModel):
    """Output of Step 1: Local preprocessing"""
    source: SourceInfo
    cleaning_stats: CleaningStats
    image_filtering: ImageFilteringStats
    filtered_images: List[FilteredImage]
    skipped_images: List[SkippedImage] = Field(default_factory=list)
    cleaned_dom_path: str


# ============================================================================
# Image Classification Output Models
# ============================================================================

class ProcessingMetadata(BaseModel):
    """Metadata about image processing"""
    source_url: str
    model: str
    processed_at: str
    batches_processed: int
    total_images_evaluated: int
    images_included: int
    images_excluded: int


class ImageDescriptionsOutput(BaseModel):
    """Output of Step 2: Image classification and description"""
    processing_metadata: ProcessingMetadata
    included_images: List[ImageDescription]
    excluded_images: List[ExcludedImage]


# ============================================================================
# Knowledge Base Output Models
# ============================================================================

class KBMetadata(BaseModel):
    """Knowledge base metadata"""
    source_url: str
    page_title: str
    product: Optional[str] = None
    target_audience: Optional[str] = None
    data_segment: str
    generated_at: str
    model: str
    total_sections: int = 0
    total_images_included: int = 0


class SectionData(BaseModel):
    """Type-specific data for a section"""
    type: str
    # Additional fields depend on type - using dict for flexibility
    # Types: packages, pricing, statistics, ratings, awards, 
    #        testimonials, faq, contact, resources, disclaimers
    
    class Config:
        extra = "allow"


class Section(BaseModel):
    """A section in the knowledge base - recursive structure"""
    id: str
    title: str
    level: int
    summary: str
    content: Optional[str] = None
    key_points: List[str] = Field(default_factory=list)
    images: List[SectionImage] = Field(default_factory=list)
    subsections: List["Section"] = Field(default_factory=list)
    data: Optional[dict] = None  # Type-specific data


# Enable recursive model
Section.model_rebuild()


class AllImagesSummary(BaseModel):
    """Summary of all images processed"""
    total_evaluated: int
    included: int
    excluded: int


class KnowledgeBase(BaseModel):
    """Output of Step 3: Complete knowledge base"""
    metadata: KBMetadata
    document_summary: str
    key_value_proposition: Optional[str] = None
    sections: List[Section]
    all_images_summary: AllImagesSummary
    last_updated: str


# ============================================================================
# API Response Models (for parsing Claude's responses)
# ============================================================================

class ImageClassificationResponse(BaseModel):
    """Expected response format from image classification prompt"""
    image_id: str
    include: bool
    category: str
    description: Optional[str] = None
    extracted_text: Optional[str] = None
    stats: Optional[List[dict]] = None
    exclusion_reason: Optional[str] = None
    suggested_section: Optional[str] = None


class ImageBatchResponse(BaseModel):
    """Response for a batch of images"""
    images: List[ImageClassificationResponse]


# ============================================================================
# Helper Functions
# ============================================================================

def create_empty_section(
    id: str,
    title: str,
    level: int = 1,
    summary: str = ""
) -> Section:
    """Create an empty section with all required fields"""
    return Section(
        id=id,
        title=title,
        level=level,
        summary=summary,
        content=None,
        key_points=[],
        images=[],
        subsections=[],
        data=None
    )


def create_kb_metadata(
    source_url: str,
    page_title: str,
    data_segment: str,
    model: str,
    product: Optional[str] = None,
    target_audience: Optional[str] = None
) -> KBMetadata:
    """Create knowledge base metadata"""
    return KBMetadata(
        source_url=source_url,
        page_title=page_title,
        product=product,
        target_audience=target_audience,
        data_segment=data_segment,
        generated_at=datetime.now().isoformat(),
        model=model
    )

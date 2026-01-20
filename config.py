"""
Configuration and constants for HTML Knowledge Base Extractor
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

# ============================================================================
# API Configuration
# ============================================================================

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DEFAULT_MODEL = "claude-sonnet-4-20250514"

# Rate limiting
API_DELAY_SECONDS = 2.0  # Delay between API calls
MAX_RETRIES = 5  # Increased retries
RETRY_DELAY_SECONDS = 60.0  # Wait 60 seconds on rate limit (token bucket refills)

# Token limits (Claude Sonnet 4)
MAX_INPUT_TOKENS = 30000  # Per minute limit
MAX_OUTPUT_TOKENS = 8000
SAFE_INPUT_TOKENS = 25000  # Leave buffer

# ============================================================================
# Image Processing Configuration
# ============================================================================

# Image filtering rules
IMAGE_FILTER_CONFIG = {
    # Skip images with these dimensions (tracking pixels)
    "min_width": 50,
    "min_height": 50,
    
    # Skip images smaller than this file size (likely icons)
    "min_file_size_bytes": 500,
    
    # URL patterns to skip (UI elements, tracking)
    "skip_url_patterns": [
        "icn-close",
        "icn-nav-",
        "icn-carousel",
        "rlcdn.com",
        "analytics",
        "bat.bing",
        "t.co/i/adsct",
        "facebook.com/tr",
        "googleadservices",
        "doubleclick.net",
    ],
    
    # Alt text patterns indicating decorative images
    "skip_alt_patterns": [
        "logo",
        "icon",
        "arrow",
        "close",
        "menu",
    ],
}

# Image batch size for API calls
IMAGE_BATCH_SIZE = 10

# Image categories for classification
IMAGE_CATEGORIES = [
    "product_ui",       # Screenshots of product interface
    "feature_icon",     # Icons representing features
    "stats_data",       # Infographics with statistics
    "testimonial_photo", # Photos of customers giving testimonials
    "decorative_people", # Stock photos of people (exclude)
    "branding",         # Logos and brand elements (exclude)
    "decorative_other", # Other decorative images (exclude)
]

INCLUDE_CATEGORIES = ["product_ui", "feature_icon", "stats_data", "testimonial_photo"]
EXCLUDE_CATEGORIES = ["decorative_people", "branding", "decorative_other"]

# ============================================================================
# HTML Cleaning Configuration
# ============================================================================

HTML_CLEAN_CONFIG = {
    # Tags to completely remove (including content)
    "remove_tags_with_content": [
        "script",
        "style",
        "noscript",
        "iframe",
        "head",
        "meta",
        "link",
    ],
    
    # Tags to remove but keep content
    "unwrap_tags": [
        "span",
        "font",
        "center",
    ],
    
    # Attributes to remove from all tags
    "remove_attributes": [
        "style",
        "class",
        "id",
        "data-*",
        "onclick",
        "onload",
        "onerror",
    ],
    
    # Elements to remove by class/id patterns (navigation, footer, etc.)
    "remove_by_pattern": [
        "nav",
        "navbar",
        "navigation",
        "footer",
        "cookie",
        "popup",
        "modal",
        "advertisement",
        "sidebar",
    ],
}

# ============================================================================
# Data Segment Configuration
# ============================================================================

DATA_SEGMENTS = [
    "General",
    "Comparison",
    "HRO",
    "Small Business",
    "Mid-Size Business",
    "Large Business",
    "Industry Vertical",
    "Partner Vertical",
]

# URL patterns to detect data segment
SEGMENT_URL_PATTERNS = {
    "1-49": "Small Business",
    "small-business": "Small Business",
    "50-999": "Mid-Size Business",
    "mid-size": "Mid-Size Business",
    "midsize": "Mid-Size Business",
    "1000": "Large Business",
    "enterprise": "Large Business",
    "large-business": "Large Business",
    "hro": "HRO",
    "industry": "Industry Vertical",
    "partner": "Partner Vertical",
    "comparison": "Comparison",
}

# ============================================================================
# Output Configuration
# ============================================================================

@dataclass
class OutputConfig:
    """Configuration for output files"""
    output_dir: Path = field(default_factory=lambda: Path("./output"))
    save_intermediate: bool = True  # Save cleaned HTML, image classifications
    
    # File names
    cleaned_html_file: str = "cleaned_dom.html"
    preprocessed_data_file: str = "preprocessed_data.json"
    image_descriptions_file: str = "image_descriptions.json"
    knowledge_base_file: str = "knowledge_base.json"
    
    def __post_init__(self):
        self.output_dir = Path(self.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)


# ============================================================================
# Main Configuration Class
# ============================================================================

@dataclass
class Config:
    """Main configuration class"""
    api_key: str = ANTHROPIC_API_KEY
    model: str = DEFAULT_MODEL
    api_delay: float = API_DELAY_SECONDS
    max_retries: int = MAX_RETRIES
    image_batch_size: int = IMAGE_BATCH_SIZE
    output: OutputConfig = field(default_factory=OutputConfig)
    skip_image_processing: bool = False  # Skip Step 2 (image classification) to save API costs
    use_screenshot_for_grouping: bool = True  # Use full-page screenshot for semantic grouping
    
    def validate(self) -> bool:
        """Validate configuration"""
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable not set")
        return True


# Default configuration instance
default_config = Config()

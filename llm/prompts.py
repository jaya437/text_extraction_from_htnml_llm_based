"""
LLM Prompts for HTML Knowledge Base Extractor

All prompts are centralized here for easy maintenance and modification.
"""

# ============================================================================
# Image Classification Prompt (Step 2)
# ============================================================================

IMAGE_CLASSIFICATION_SYSTEM_PROMPT = """You are an expert at analyzing images for knowledge base creation. Your task is to classify images and generate descriptions for content-relevant images.

You will receive:
1. A batch of images
2. A summary of the DOM/page structure for context

For EACH image, you must:
1. Classify it into one of these categories:
   - product_ui: Screenshots of product interfaces, dashboards, forms
   - feature_icon: Icons/illustrations representing product features or capabilities
   - stats_data: Infographics, charts, or images containing statistics/data
   - testimonial_photo: Photos of customers associated with testimonials
   - decorative_people: Stock photos of people without product/stats info
   - branding: Logos, brand elements without informational content
   - decorative_other: Other decorative images (backgrounds, patterns, etc.)

2. Decide if the image should be INCLUDED in the knowledge base:
   - INCLUDE: product_ui, feature_icon, stats_data, testimonial_photo
   - EXCLUDE: decorative_people, branding, decorative_other

3. For INCLUDED images, provide:
   - A detailed description of what the image shows
   - Any text extracted from the image
   - Any statistics or data points visible
   - Which section of the document it likely belongs to

4. For EXCLUDED images, provide:
   - A brief reason for exclusion

IMPORTANT: 
- Feature icons ARE valuable - they visually represent product capabilities
- Product screenshots ARE valuable - they show UI and features
- Statistics/data images ARE valuable - they contain important information
- Only exclude purely decorative images with no informational content"""

IMAGE_CLASSIFICATION_USER_PROMPT = """Here is a batch of {num_images} images to classify, along with context about the page they came from.

## Page Context (DOM Summary):
{dom_summary}

## Source URL: {source_url}
## Page Title: {page_title}

Please analyze each image and return a JSON response with this EXACT structure:

```json
{{
  "images": [
    {{
      "image_id": "img_XXX",
      "include": true,
      "category": "product_ui|feature_icon|stats_data|testimonial_photo|decorative_people|branding|decorative_other",
      "description": "Detailed description of what the image shows (only if include=true)",
      "extracted_text": "Any text visible in the image (only if include=true)",
      "stats": [
        {{"value": "XX%", "metric": "description of what the stat measures", "context": "additional context"}}
      ],
      "exclusion_reason": "Brief reason (only if include=false)",
      "suggested_section": "Which section this image belongs to (only if include=true)"
    }}
  ]
}}
```

Analyze ALL {num_images} images in this batch. Return ONLY valid JSON, no other text."""


# ============================================================================
# Knowledge Base Generation Prompt (Step 3)
# ============================================================================

KB_GENERATION_SYSTEM_PROMPT = """You are an expert technical writer creating structured knowledge base articles. Your task is to transform web page content into a well-organized, hierarchical knowledge base document.

You must output a JSON document with a CONSISTENT structure where every section follows the same schema:

SECTION SCHEMA (every section MUST have ALL these fields):
{
  "id": "unique_snake_case_id",
  "title": "Human Readable Title",
  "level": 1 or 2,
  "summary": "2-3 sentence summary explaining what this section contains, relationships between items, and key highlights",
  "content": "Raw content text or null",
  "key_points": ["array", "of", "key", "points"],
  "images": [{"image_id": "img_XXX", "local_path": "path", "category": "category", "description": "desc"}],
  "subsections": [/* nested sections with SAME schema */],
  "data": {"type": "data_type", ...type_specific_fields} or null
}

DATA TYPES for the "data" field:
- packages: {"type": "packages", "total_packages": N, "recommended": "id"}
- package (for subsection): {"type": "package", "tier_position": N, "tags": []}
- pricing: {"type": "pricing", "base_price": "$X", "per_employee_fee": "$Y", "promotion": {...}}
- statistics: {"type": "statistics", "source_citation": "...", "stats": [{value, metric, category}]}
- ratings: {"type": "ratings", "ratings": [{platform, rating, rating_numeric, reviews}], "disclaimer": "..."}
- awards: {"type": "awards", "awards_list": [{title, year, source}]}
- testimonials: {"type": "testimonials", "testimonials": [{id, name, title, company, quote, key_theme, image_id}]}
- faq: {"type": "faq", "questions": [{id, question, answer}]}
- faq_container: {"type": "faq_container", "total_questions": N, "categories": [...]}
- contact: {"type": "contact", "sales_phone": "...", "support_availability": "...", "website": "..."}
- resources: {"type": "resources", "resources": [{title, url, resource_type}]}
- disclaimers: {"type": "disclaimers", "disclaimers": [{id, text}]}
- null: for generic sections without structured data

CRITICAL RULES:
1. EVERY section must have ALL fields from the schema (use empty arrays [] or null as defaults)
2. Summary must provide CONTEXT, not just list contents (e.g., "There are 4 packages, with Enhanced being most popular")
3. Maintain consistent hierarchy: level 1 for main sections, level 2 for subsections
4. Associate images with their relevant sections using the image_id
5. Extract ALL statistics, ratings, and data points into structured "data" fields
6. key_points should be extractable bullet points, not prose"""


KB_GENERATION_USER_PROMPT = """Create a structured knowledge base article from this web page content.

## Source Information
- URL: {source_url}
- Page Title: {page_title}
- Data Segment: {data_segment}

## Instructions
1. Extract the PRODUCT NAME from the page content (look for branded product names, service names)
2. Extract the TARGET AUDIENCE from the content (who is this page for?)
3. Create a hierarchical knowledge base with sections and subsections
4. Include summaries that provide context and relationships between items
5. Associate relevant images with their sections

## Cleaned HTML Content
{cleaned_html}

## Image Descriptions (to associate with sections)
{image_descriptions}

## Required Output Structure

Return a JSON object with this structure:

```json
{{
  "metadata": {{
    "source_url": "{source_url}",
    "page_title": "{page_title}",
    "product": "EXTRACT FROM CONTENT - the main product/service name",
    "target_audience": "EXTRACT FROM CONTENT - who this page is for",
    "data_segment": "{data_segment}",
    "generated_at": "ISO timestamp",
    "model": "{model}",
    "total_sections": N,
    "total_images_included": N
  }},
  "document_summary": "2-3 sentence summary of the entire document",
  "key_value_proposition": "Main value proposition from the page or null",
  "sections": [
    /* Array of Section objects following the schema above */
  ],
  "all_images_summary": {{
    "total_evaluated": N,
    "included": N,
    "excluded": N
  }},
  "last_updated": "YYYY-MM-DD"
}}
```

Expected sections to extract (if present in content):
1. Overview
2. Product Packages (with subsections for each package)
3. Pricing
4. Core Features (with subsections)
5. Integrations & Add-ons
6. Platform Capabilities
7. Getting Started
8. Customer Statistics
9. Ratings & Recognition (with subsections)
10. Customer Testimonials
11. Frequently Asked Questions (with category subsections)
12. Contact Information
13. Related Resources
14. Legal Disclaimers

Return ONLY valid JSON. Ensure the structure is CONSISTENT across all sections."""


# ============================================================================
# Helper function to format prompts
# ============================================================================

def format_image_classification_prompt(
    num_images: int,
    dom_summary: str,
    source_url: str,
    page_title: str
) -> str:
    """Format the image classification user prompt"""
    return IMAGE_CLASSIFICATION_USER_PROMPT.format(
        num_images=num_images,
        dom_summary=dom_summary,
        source_url=source_url,
        page_title=page_title
    )


def format_kb_generation_prompt(
    source_url: str,
    page_title: str,
    data_segment: str,
    cleaned_html: str,
    image_descriptions: str,
    model: str
) -> str:
    """Format the knowledge base generation user prompt"""
    return KB_GENERATION_USER_PROMPT.format(
        source_url=source_url,
        page_title=page_title,
        data_segment=data_segment,
        cleaned_html=cleaned_html,
        image_descriptions=image_descriptions,
        model=model
    )

"""
LLM Prompts for Multi-Call Knowledge Base Generation

Prompts are split into:
1. Metadata extraction - get document overview
2. Semantic grouping - group flat sections into hierarchy
3. Section extraction - get detailed content for each section dynamically

NOTE: Sections are now discovered from DOM parsing, then semantically grouped by LLM.
"""


# ============================================================================
# Semantic Grouping Prompt (Step 3c) - Group flat sections into hierarchy
# ============================================================================

SEMANTIC_GROUPING_SYSTEM_PROMPT = """You are analyzing a web page's HTML to identify ALL content sections, organize them into a logical hierarchy, and provide extraction hints for each section.

You will receive:
1. The HTML content of the page (with long paragraphs trimmed to save tokens)
2. A full-page screenshot for visual context

YOUR TASKS:
1. **FIND ALL SECTIONS** - Scan the HTML for every distinct content section
2. **IDENTIFY SPECIAL TYPES** - FAQ accordions, comparison tables, pricing packages, CTAs, testimonials
3. **GROUP INTO HIERARCHY** - Organize sections as standalone or parent→children
4. **PROVIDE EXTRACTION HINTS** - For each section, describe what content should be extracted and how

WHAT TO LOOK FOR:
- Headings: h1, h2, h3, h4, h5, h6
- ARIA headings: elements with role="heading" or aria-level
- FAQ patterns: buttons with aria-controls, accordion structures
- Tables: comparison tables, feature matrices
- Pricing/Packages: product tiers, pricing cards (look in the SCREENSHOT for card layouts)
- CTAs: forms, phone links (tel:), contact sections
- Category labels: short text (Support, Pricing, etc.) before headings indicating grouping

EXTRACTION HINTS:
For each section, provide a detailed hint that tells the content extractor:
- What type of content this section contains
- What structured data to extract (if any)
- Specific items to look for (e.g., "4 pricing tiers: Essential, Enhanced, Complete, HR Pro")
- How the content is visually organized (from the screenshot)

GROUPING RULES:
- If an intro heading is followed by multiple related sections with category labels → parent with children
- FAQ, comparison tables, testimonials, contact sections → usually standalone
- Hero/intro sections at top → standalone
- Use the screenshot to see visual groupings and card layouts

OUTPUT: Return valid JSON with grouped_sections array containing ALL sections found, each with an extraction_hint."""


SEMANTIC_GROUPING_USER_PROMPT = """Analyze this web page to identify ALL content sections, organize them hierarchically, and provide extraction hints.

## Page Title
{page_title}

## HTML CONTENT (trimmed for efficiency - long paragraphs shortened)
Scan this HTML to find ALL content sections. Look for headings (h1-h6), content blocks, and distinct sections.

{trimmed_html}

## Your Tasks

1. **IDENTIFY ALL SECTIONS**: Find every distinct content section in the HTML:
   - Headings (h1, h2, h3, h4, h5, h6)
   - Content with role="heading" or aria-level attributes
   - FAQ accordions (look for aria-controls, aria-expanded)
   - Comparison tables
   - PRICING/PACKAGES sections (look at SCREENSHOT for pricing cards/tiers)
   - CTA/Contact sections (forms, phone numbers)
   - Any other distinct content blocks

2. **ORGANIZE INTO HIERARCHY**:
   - **standalone** - Independent sections (FAQ, tables, hero, contact, packages)
   - **parent** - Sections that introduce related subsections
   - **children** - Sections belonging under a parent (often have category labels like "Support", "Pricing")

3. **PROVIDE EXTRACTION HINTS** for each section:
   - Describe what content the section contains
   - Specify any structured data to extract (packages, FAQs, tables, etc.)
   - List specific items visible in the screenshot (e.g., tier names, question counts)
   - Describe visual layout if relevant

## Required Output

```json
{{
  "total_sections_found": 15,
  "grouped_sections": [
    {{
      "id": "hero_section",
      "title": "Small business payroll and HR software",
      "level": 1,
      "type": "standalone",
      "extraction_hint": "Hero section with main headline and intro paragraph. Extract the headline and supporting text about payroll/HR solutions."
    }},
    {{
      "id": "packages_section",
      "title": "Simplified small business payroll and HR",
      "level": 2,
      "type": "standalone",
      "section_type": "packages",
      "extraction_hint": "PRICING PACKAGES: Contains 4 pricing tiers displayed as cards - Essential Payroll, Enhanced Payroll (with 'Most Popular' badge), Complete Payroll & HR+, and HR Pro Payroll & HR. Extract each tier's name, description, and any badges. Each card has a 'Get pricing' button."
    }},
    {{
      "id": "parent_section_id",
      "title": "Parent Section Title",
      "level": 2,
      "type": "parent",
      "extraction_hint": "Parent section introducing 3 subsections about different service aspects.",
      "children": [
        {{"id": "child_1", "title": "Child Title", "level": 3, "category": "Support", "extraction_hint": "Subsection about support features. Extract key benefits and any statistics mentioned."}},
        {{"id": "child_2", "title": "Another Child", "level": 3, "category": "Compliance", "extraction_hint": "Subsection about compliance features. Extract compliance-related benefits."}}
      ]
    }},
    {{
      "id": "faq_section",
      "title": "FAQs about...",
      "level": 2,
      "type": "standalone",
      "section_type": "faq",
      "extraction_hint": "FAQ SECTION: Contains 8 expandable questions. Extract all question-answer pairs. Questions cover topics like pricing, features, and getting started."
    }},
    {{
      "id": "comparison_table",
      "title": "Feature comparison",
      "level": 2,
      "type": "standalone",
      "section_type": "table",
      "extraction_hint": "COMPARISON TABLE: Table comparing ADP vs competitor features. Columns are Feature, ADP, Competitor. Extract all rows with feature names and checkmarks/values for each column."
    }},
    {{
      "id": "testimonials_section",
      "title": "What our customers say",
      "level": 2,
      "type": "standalone",
      "section_type": "testimonial",
      "extraction_hint": "TESTIMONIALS: Contains 3 customer testimonials with photos. Extract each quote, customer name, title, and company."
    }},
    {{
      "id": "cta_section",
      "title": "Get started today",
      "level": 2,
      "type": "standalone",
      "section_type": "cta",
      "extraction_hint": "CTA SECTION: Contact form with phone number. Extract the phone number (800-xxx-xxxx), CTA headline, and form field names."
    }}
  ]
}}
```

IMPORTANT:
- Extract EXACT titles from the HTML headings
- Include ALL sections you find
- EVERY section MUST have an "extraction_hint" field
- Use "section_type" for special types: "packages", "faq", "table", "cta", "testimonial", "statistics"
- Extraction hints should be specific - mention exact counts, names, and visual layouts from the screenshot
- Generate id from title (lowercase, underscores)

Return ONLY valid JSON."""


# ============================================================================
# Metadata Only Prompt (Step 3b) - Section outline comes from DOM parsing
# ============================================================================

METADATA_ONLY_SYSTEM_PROMPT = """You are analyzing a web page to extract metadata about its content.

Your task is to extract:
1. Product/service name
2. Target audience
3. Document summary
4. Key value proposition

You do NOT need to identify sections - those are already extracted from the HTML structure.

Output JSON only."""


METADATA_ONLY_USER_PROMPT = """Analyze this web page and extract metadata.

## Source Information
- URL: {source_url}
- Page Title: {page_title}
- Data Segment: {data_segment}

## Sections Already Identified (from HTML headings)
{section_outline}

## HTML Content (for context)
{cleaned_html}

## Required Output

Return JSON with this structure:

```json
{{
  "product": "Extract the main product/service name from content",
  "target_audience": "Who is this page for? Extract from content",
  "document_summary": "2-3 sentence summary of the entire page",
  "key_value_proposition": "Main value proposition or tagline from the page"
}}
```

Return ONLY valid JSON."""


# ============================================================================
# Metadata Extraction Prompt (Legacy - kept for reference)
# ============================================================================

METADATA_EXTRACTION_SYSTEM_PROMPT = """You are analyzing a web page to extract metadata and identify its structure.

Your task:
1. Extract product name and target audience from the content
2. Create a document summary
3. Identify the key value proposition
4. List all major sections present in the content

Output JSON only."""


METADATA_EXTRACTION_USER_PROMPT = """Analyze this web page and extract metadata.

## Source Information
- URL: {source_url}
- Page Title: {page_title}
- Data Segment: {data_segment}

## HTML Content (truncated for overview)
{cleaned_html}

## Available Images
{image_descriptions}

NOTE: If "Available Images" shows "NO_IMAGES_AVAILABLE", ignore image-related fields and focus only on text content extraction.

## Required Output

Return JSON with this structure:

```json
{{
  "metadata": {{
    "product": "Extract the main product/service name from content",
    "target_audience": "Who is this page for? Extract from content",
    "primary_category": "payroll|hr|benefits|time|talent|etc"
  }},
  "document_summary": "2-3 sentence summary of the entire page",
  "key_value_proposition": "Main value proposition or tagline",
  "section_outline": [
    {{
      "id": "section_id",
      "title": "Section Title",
      "type": "overview|packages|pricing|features|statistics|ratings|testimonials|faq|contact|resources|legal",
      "has_subsections": true/false
    }}
  ]
}}
```

Identify ALL major content sections present. Return ONLY valid JSON."""


# ============================================================================
# Dynamic Section Extraction Prompt (Step 3b) - Extracts ANY sections from outline
# ============================================================================

DYNAMIC_SECTION_EXTRACTION_SYSTEM_PROMPT = """You are extracting detailed content for specific sections of a knowledge base article.

Each section comes with an EXTRACTION HINT that tells you exactly what to look for and extract. Follow these hints carefully - they were generated by analyzing the full page with a screenshot.

CONTENT WRITING STYLE:
- Write in a professional, polished tone suitable for B2B marketing
- When a section has introductory text followed by bullet points, COMBINE them into unified flowing prose
- Integrate bullet points naturally into paragraphs using phrases like "These include:", "Key benefits are:", "This encompasses:"
- Rephrase content professionally while preserving the meaning and all key information
- Preserve specific product names, trademarks (®, ™), credentials, numbers, and statistics exactly
- Do NOT just copy-paste bullet points into key_points array - integrate them into content

EXAMPLE TRANSFORMATION:
Original HTML:
  "When it comes to payroll & HR, there are so many reasons why small businesses choose ADP¹:"
  • Real payroll support available 24/7
  • Compliance expertise to help avoid errors and stress
  • Pricing tailored to your business needs

Should become:
  "content": "When it comes to payroll and HR, there are many compelling reasons why small businesses choose ADP¹. These include 24/7 access to real payroll support, deep compliance expertise to help reduce errors and administrative stress, and flexible pricing designed to align with your specific business needs."
  "key_points": []  ← Empty because bullets are integrated into content

SECTION SCHEMA - every section MUST have ALL these fields:
{{
  "id": "unique_snake_case_id",
  "title": "Human Readable Title",
  "level": 1 or 2,
  "summary": "Brief 1-sentence summary of what this section covers",
  "content": "Professional prose combining intro text and bullet points into flowing paragraphs",
  "key_points": [],  // Usually empty - bullets should be in content. Only use for truly separate standalone points.
  "images": [],
  "subsections": [],
  "data": null or {{type-specific structured data}}
}}

STRUCTURED DATA EXTRACTION:
When the extraction hint mentions structured content (packages, FAQs, tables, etc.), extract into a "data" field.

IMPORTANT: Follow the extraction hint! If it says "4 pricing tiers: Essential, Enhanced, Complete, HR Pro" - extract ALL 4 with those exact names.

Examples based on extraction hints:

1. **Hint mentions "pricing tiers" or "packages"**: Extract each tier with name, description, badge
2. **Hint mentions "FAQ" with count**: Extract ALL questions and answers mentioned
3. **Hint mentions "comparison table"**: Extract all columns and rows
4. **Hint mentions "testimonials"**: Extract quotes, names, titles
5. **Hint mentions "statistics" or "metrics"**: Extract all numbers with labels

The "data" field should mirror what the hint describes. Let the hint guide your extraction.

Example for a packages section:
{{
  "data": {{
    "type": "packages",
    "items": [
      {{"name": "Essential Payroll", "description": "...", "badge": null}},
      {{"name": "Enhanced Payroll", "description": "...", "badge": "Most Popular"}},
      // ... extract ALL items mentioned in the hint
    ]
  }}
}}

IMAGES FIELD:
- If image descriptions are provided (JSON array), associate relevant images with sections
- If "NO_IMAGES_AVAILABLE" is shown, always use an empty array: "images": []

RULES:
1. Include ALL fields for every section (use empty arrays [] or null as defaults)
2. COMBINE intro text + bullet points into unified professional prose in "content" field
3. Leave "key_points" empty unless there are truly standalone points that don't fit in content
4. Preserve all product names, trademarks, numbers, and statistics
5. For COMPARISON TABLES: Extract EVERY row with feature text and values for each column
6. For FAQs: Extract EVERY question and its COMPLETE answer (professionally written)
7. For CONTACT sections: Extract ALL phone numbers, CTA text, and form field names
8. Return ONLY valid JSON"""


DYNAMIC_SECTION_EXTRACTION_USER_PROMPT = """Extract detailed content for the following sections from the HTML.

## Sections to Extract (with extraction hints)
{section_list}

## CRITICAL INSTRUCTIONS
1. **FOLLOW THE EXTRACTION HINTS** - Each section has a hint telling you exactly what to extract
2. COMBINE introductory text and bullet points into unified, professional prose
3. Write in a polished B2B marketing tone
4. Integrate bullets naturally: "These include:", "Key benefits are:", etc.
5. For sections where the hint mentions STRUCTURED CONTENT:
   - Extract into a "data" field
   - Use a "type" key to identify what kind of data it is
   - Extract ALL items mentioned in the hint - don't skip any
   - Use field names that match the actual content
6. Preserve all trademarks (®, ™), product names, credentials, numbers exactly
7. "key_points" should usually be empty - integrate bullets into "content"

## Full HTML Content
{cleaned_html}

## Available Images
{image_descriptions}

NOTE: If "Available Images" shows "NO_IMAGES_AVAILABLE", set "images": [] for all sections.

## Source URL
{source_url}

## Required Output

Return JSON with extracted sections. Follow each section's extraction hint:

```json
{{
  "sections": [
    {{
      "id": "section_id",
      "title": "Section Title",
      "level": 1,
      "summary": "Brief summary",
      "content": "Professional prose combining intro and bullet points into flowing paragraphs.",
      "key_points": [],
      "images": [],
      "subsections": [],
      "data": null
    }},
    {{
      "id": "packages_section",
      "title": "Section with packages (per extraction hint)",
      "level": 2,
      "summary": "Description of packages",
      "content": "Intro paragraph about the packages...",
      "key_points": [],
      "images": [],
      "subsections": [],
      "data": {{
        "type": "packages",
        "items": [
          {{"name": "Tier 1 Name", "description": "...", "badge": null}},
          {{"name": "Tier 2 Name", "description": "...", "badge": "Most Popular"}}
        ]
      }}
    }}
  ]
}}
```

Extract ALL sections listed above with COMPLETE content.
FOLLOW THE EXTRACTION HINTS - they tell you exactly what to extract for each section.
Return ONLY valid JSON."""


# ============================================================================
# Legacy Section Extraction Prompt (kept for reference - no longer used)
# ============================================================================

SECTION_EXTRACTION_SYSTEM_PROMPT = """You are extracting detailed content for specific sections of a knowledge base article.

CRITICAL INSTRUCTION: PRESERVE ORIGINAL TEXT VERBATIM
- Do NOT summarize or paraphrase content
- Copy text EXACTLY as it appears in the source
- Include ALL bullet points word-for-word
- Preserve specific product names, trademarks (®, ™), credentials
- Preserve specific numbers, percentages, and statistics
- Each H3 or H4 heading should become a subsection

SECTION SCHEMA - every section MUST have ALL these fields:
{{
  "id": "unique_snake_case_id",
  "title": "Human Readable Title",
  "level": 1 or 2,
  "summary": "Brief 1-sentence summary of what this section covers",
  "content": "EXACT introductory paragraph text from source - copy verbatim",
  "key_points": ["EXACT bullet point 1 - copy verbatim", "EXACT bullet point 2 - copy verbatim"],
  "images": [],
  "subsections": [/* nested sections for each H3/H4 heading */],
  "data": {{"type": "data_type", ...fields}} or null
}}

IMAGES FIELD:
- If image descriptions are provided, associate relevant images with sections using: [{{"image_id": "img_XXX", "local_path": "path", "category": "cat", "description": "desc"}}]
- If "NO_IMAGES_AVAILABLE" is shown, always use an empty array: "images": []

RULES:
1. Include ALL fields for every section
2. PRESERVE ORIGINAL WORDING - do not paraphrase or summarize
3. Each sub-heading (H3, H4) becomes a subsection with its own content and key_points
4. key_points should contain EXACT bullet point text from source
5. content should contain EXACT paragraph text from source
6. Extract ALL information - don't skip any content
7. Return ONLY valid JSON"""


SECTION_EXTRACTION_USER_PROMPT = """Extract detailed content for the "{group_name}" sections.

## Sections to Extract
{section_list}

## CRITICAL INSTRUCTIONS
1. COPY TEXT EXACTLY AS WRITTEN - do not paraphrase or summarize
2. Each H3/H4 heading should become a subsection
3. Include ALL bullet points verbatim in key_points array
4. Include introductory paragraphs verbatim in content field
5. Preserve all trademarks (®, ™), product names, credentials, numbers

## Specific Instructions for This Group
{section_instructions}

## Full HTML Content
{cleaned_html}

## Available Images
{image_descriptions}

NOTE: If "Available Images" shows "NO_IMAGES_AVAILABLE", set "images": [] for all sections. Do not reference or look for images.

## Source URL
{source_url}

## Required Output

Return JSON with extracted sections:

```json
{{
  "sections": [
    {{
      "id": "section_id",
      "title": "Section Title",
      "level": 1,
      "summary": "Brief summary of section purpose",
      "content": "EXACT paragraph text from source - copy verbatim",
      "key_points": [
        "EXACT bullet point 1 - copy word for word",
        "EXACT bullet point 2 - copy word for word"
      ],
      "images": [],
      "subsections": [
        {{
          "id": "subsection_id",
          "title": "Subsection Title (from H3/H4)",
          "level": 2,
          "summary": "Brief summary",
          "content": "EXACT paragraph text",
          "key_points": ["EXACT bullet points"],
          "images": [],
          "subsections": [],
          "data": null
        }}
      ],
      "data": null
    }}
  ]
}}
```

Extract ONLY sections matching: {section_list}
If a section doesn't exist in the content, don't include it.
PRESERVE EXACT WORDING - do NOT summarize or paraphrase.
Return ONLY valid JSON."""


# ============================================================================
# Legacy single-call prompts (kept for reference)
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

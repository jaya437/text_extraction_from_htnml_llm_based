# hmtl_text_extractor_llm_based
# HTML Knowledge Base Extractor - Flow Diagram

## Overview

This tool extracts structured knowledge bases from HTML web pages using a combination of local processing and LLM calls. The key innovation is using a single screenshot analysis to generate extraction hints, reducing vision API costs by ~85%.

---

## Flow Diagram

```
+------------------------------------------------------------------+
|                        INPUT FILES                                |
|  - cleaned_dom.html (scraped page)                               |
|  - mapping.json (image metadata)                                 |
|  - full_page_screenshot.jpg                                      |
+------------------------------------------------------------------+
                                |
                                v
+------------------------------------------------------------------+
|                  STEP 1: HTML CLEANING (Local)                   |
|------------------------------------------------------------------|
|  Remove scripts, styles, navigation, and footer elements.        |
|  Output: Cleaned HTML ready for processing.                      |
+------------------------------------------------------------------+
                                |
                                v
+------------------------------------------------------------------+
|                 STEP 2: IMAGE FILTERING (Local)                  |
|------------------------------------------------------------------|
|  Filter out tracking pixels, tiny icons, and SVG files.          |
|  Output: List of content-relevant images for classification.     |
+------------------------------------------------------------------+
                                |
                                v
+------------------------------------------------------------------+
|           STEP 3: IMAGE CLASSIFICATION (LLM - Optional)          |
|------------------------------------------------------------------|
|  Classify images into categories and generate descriptions.      |
|  Categories: product_ui, feature_icon, stats_data, testimonial.  |
|  Output: image_descriptions.json                                 |
+------------------------------------------------------------------+
                                |
                                v
+------------------------------------------------------------------+
|              STEP 4: DOM SECTION PARSING (Local)                 |
|------------------------------------------------------------------|
|  Parse headings, FAQ accordions, tables, and CTAs from HTML.     |
|  Output: Flat list of sections found in the document.            |
+------------------------------------------------------------------+
                                |
                                v
+------------------------------------------------------------------+
|           STEP 5: METADATA EXTRACTION (LLM - Text only)          |
|------------------------------------------------------------------|
|  Extract product name, target audience, and document summary.    |
|  Output: Metadata object with key page information.              |
+------------------------------------------------------------------+
                                |
                                v
+------------------------------------------------------------------+
|    STEP 6: SEMANTIC GROUPING + EXTRACTION HINTS (LLM + Image)    |
|------------------------------------------------------------------|
|  Analyze full page with screenshot to identify all sections.     |
|  Generate specific extraction hints for each section.            |
|  Output: Grouped sections with detailed extraction instructions. |
+------------------------------------------------------------------+
                                |
                                v
+------------------------------------------------------------------+
|         STEP 7: SECTION CONTENT EXTRACTION (LLM - Text only)     |
|------------------------------------------------------------------|
|  Extract content for each section using the extraction hints.    |
|  Process in batches of 4 sections per LLM call.                  |
|  Output: Fully extracted section content with structured data.   |
+------------------------------------------------------------------+
                                |
                                v
+------------------------------------------------------------------+
|           STEP 8: MERGE & RECONSTRUCT HIERARCHY (Local)          |
|------------------------------------------------------------------|
|  Combine extracted content with grouped structure.               |
|  Build parent/child relationships between sections.              |
|  Output: Complete hierarchical knowledge base.                   |
+------------------------------------------------------------------+
                                |
                                v
+------------------------------------------------------------------+
|                     OUTPUT: knowledge_base.json                  |
|  - metadata (product, audience, segment)                         |
|  - document_summary                                              |
|  - sections[] (hierarchical with structured data)                |
+------------------------------------------------------------------+
```

---

## LLM Call Summary

| Step | Type | Description |
|------|------|-------------|
| Step 3 | Vision (batched) | Image classification - OPTIONAL |
| Step 5 | Text only | Metadata extraction |
| Step 6 | Vision (1 call) | Semantic grouping with screenshot |
| Step 7 | Text only (batched) | Section content extraction |

**Cost Optimization:** Screenshot is only sent once in Step 6. Extraction hints from Step 6 guide Step 7, eliminating the need for multiple vision calls.

---

## Prompts Reference

### Step 3: Image Classification

**Purpose:** Classify images into categories and decide which to include in the knowledge base.

#### System Prompt
```
You are an image classifier for a knowledge base extraction system.

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
- Only exclude purely decorative images with no informational content
```

#### User Prompt
```
Here is a batch of {num_images} images to classify, along with context about the page they came from.

## Page Context (DOM Summary):
{dom_summary}

## Source URL: {source_url}
## Page Title: {page_title}

Please analyze each image and return a JSON response with this EXACT structure:

{
  "images": [
    {
      "image_id": "img_XXX",
      "include": true,
      "category": "product_ui|feature_icon|stats_data|testimonial_photo|decorative_people|branding|decorative_other",
      "description": "Detailed description of what the image shows (only if include=true)",
      "extracted_text": "Any text visible in the image (only if include=true)",
      "stats": [
        {"value": "XX%", "metric": "description of what the stat measures", "context": "additional context"}
      ],
      "exclusion_reason": "Brief reason (only if include=false)",
      "suggested_section": "Which section this image belongs to (only if include=true)"
    }
  ]
}

Analyze ALL {num_images} images in this batch. Return ONLY valid JSON, no other text.
```

---

### Step 5: Metadata Extraction

**Purpose:** Extract high-level metadata about the page without processing individual sections.

#### System Prompt
```
You are analyzing a web page to extract metadata about its content.

Your task is to extract:
1. Product/service name
2. Target audience
3. Document summary
4. Key value proposition

You do NOT need to identify sections - those are already extracted from the HTML structure.

Output JSON only.
```

#### User Prompt
```
Analyze this web page and extract metadata.

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

{
  "product": "Extract the main product/service name from content",
  "target_audience": "Who is this page for? Extract from content",
  "document_summary": "2-3 sentence summary of the entire page",
  "key_value_proposition": "Main value proposition or tagline from the page"
}

Return ONLY valid JSON.
```

---

### Step 6: Semantic Grouping + Extraction Hints

**Purpose:** Analyze the full page visually to identify sections and generate detailed extraction hints for each.

#### System Prompt
```
You are analyzing a web page's HTML to identify ALL content sections, organize them into a logical hierarchy, and provide extraction hints for each section.

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

OUTPUT: Return valid JSON with grouped_sections array containing ALL sections found, each with an extraction_hint.
```

#### User Prompt
```
Analyze this web page to identify ALL content sections, organize them hierarchically, and provide extraction hints.

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

{
  "total_sections_found": 15,
  "grouped_sections": [
    {
      "id": "hero_section",
      "title": "Small business payroll and HR software",
      "level": 1,
      "type": "standalone",
      "extraction_hint": "Hero section with main headline and intro paragraph. Extract the headline and supporting text about payroll/HR solutions."
    },
    {
      "id": "packages_section",
      "title": "Simplified small business payroll and HR",
      "level": 2,
      "type": "standalone",
      "section_type": "packages",
      "extraction_hint": "PRICING PACKAGES: Contains 4 pricing tiers displayed as cards - Essential Payroll, Enhanced Payroll (with 'Most Popular' badge), Complete Payroll & HR+, and HR Pro Payroll & HR. Extract each tier's name, description, and any badges. Each card has a 'Get pricing' button."
    },
    {
      "id": "faq_section",
      "title": "FAQs about...",
      "level": 2,
      "type": "standalone",
      "section_type": "faq",
      "extraction_hint": "FAQ SECTION: Contains 8 expandable questions. Extract all question-answer pairs. Questions cover topics like pricing, features, and getting started."
    }
  ]
}

IMPORTANT:
- Extract EXACT titles from the HTML headings
- Include ALL sections you find
- EVERY section MUST have an "extraction_hint" field
- Use "section_type" for special types: "packages", "faq", "table", "cta", "testimonial", "statistics"
- Extraction hints should be specific - mention exact counts, names, and visual layouts from the screenshot
- Generate id from title (lowercase, underscores)

Return ONLY valid JSON.
```

---

### Step 7: Section Content Extraction

**Purpose:** Extract detailed content for each section using the extraction hints generated in Step 6.

#### System Prompt
```
You are extracting detailed content for specific sections of a knowledge base article.

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
{
  "id": "unique_snake_case_id",
  "title": "Human Readable Title",
  "level": 1 or 2,
  "summary": "Brief 1-sentence summary of what this section covers",
  "content": "Professional prose combining intro text and bullet points into flowing paragraphs",
  "key_points": [],
  "images": [],
  "subsections": [],
  "data": null or {type-specific structured data}
}

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
{
  "data": {
    "type": "packages",
    "items": [
      {"name": "Essential Payroll", "description": "...", "badge": null},
      {"name": "Enhanced Payroll", "description": "...", "badge": "Most Popular"}
    ]
  }
}

RULES:
1. Include ALL fields for every section (use empty arrays [] or null as defaults)
2. COMBINE intro text + bullet points into unified professional prose in "content" field
3. Leave "key_points" empty unless there are truly standalone points that don't fit in content
4. Preserve all product names, trademarks, numbers, and statistics
5. For COMPARISON TABLES: Extract EVERY row with feature text and values for each column
6. For FAQs: Extract EVERY question and its COMPLETE answer (professionally written)
7. For CONTACT sections: Extract ALL phone numbers, CTA text, and form field names
8. Return ONLY valid JSON
```

#### User Prompt
```
Extract detailed content for the following sections from the HTML.

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

{
  "sections": [
    {
      "id": "section_id",
      "title": "Section Title",
      "level": 1,
      "summary": "Brief summary",
      "content": "Professional prose combining intro and bullet points into flowing paragraphs.",
      "key_points": [],
      "images": [],
      "subsections": [],
      "data": null
    },
    {
      "id": "packages_section",
      "title": "Section with packages (per extraction hint)",
      "level": 2,
      "summary": "Description of packages",
      "content": "Intro paragraph about the packages...",
      "key_points": [],
      "images": [],
      "subsections": [],
      "data": {
        "type": "packages",
        "items": [
          {"name": "Tier 1 Name", "description": "...", "badge": null},
          {"name": "Tier 2 Name", "description": "...", "badge": "Most Popular"}
        ]
      }
    }
  ]
}

Extract ALL sections listed above with COMPLETE content.
FOLLOW THE EXTRACTION HINTS - they tell you exactly what to extract for each section.
Return ONLY valid JSON.
```

---

## Output Schema

The final `knowledge_base.json` follows this structure:

```json
{
  "metadata": {
    "source_url": "https://example.com/page",
    "page_title": "Page Title",
    "product": "Product Name",
    "target_audience": "Target audience description",
    "data_segment": "Small Business",
    "generated_at": "2024-01-01T00:00:00",
    "model": "claude-sonnet-4-20250514",
    "total_sections": 24,
    "total_images_included": 5
  },
  "document_summary": "Summary of the entire document...",
  "key_value_proposition": "Main value proposition...",
  "sections": [
    {
      "id": "section_id",
      "title": "Section Title",
      "level": 1,
      "summary": "Brief summary",
      "content": "Professional prose content...",
      "key_points": [],
      "images": [],
      "subsections": [],
      "data": {
        "type": "packages",
        "items": [...]
      }
    }
  ],
  "all_images_summary": {
    "total_evaluated": 50,
    "included": 5,
    "excluded": 45
  }
}
```

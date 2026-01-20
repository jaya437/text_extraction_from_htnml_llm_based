"""
Knowledge Base Generator - Step 3 (Multi-Call Version with Semantic Grouping)

Generates structured knowledge base JSON from cleaned HTML and image descriptions
using multiple API calls to avoid truncation and preserve full detail.

Strategy:
1. LOCAL: Parse HTML to extract flat section list (no LLM)
2. LLM Call 1: Extract metadata (product, audience, summary)
3. LLM Call 2: Semantic grouping - group flat sections into hierarchy (with optional screenshot)
4. LLM Calls 3-N: Extract detailed content for each section batch
5. LOCAL: Merge all sections into complete KB
"""

import os
import json
from typing import Optional, List, Dict, Any
from datetime import datetime

from models import (
    ImageDescriptionsOutput,
    KnowledgeBase,
    KBMetadata,
    Section,
    AllImagesSummary,
    SectionImage,
)
from llm.client import ClaudeClient
from llm.prompts_multi import (
    METADATA_ONLY_SYSTEM_PROMPT,
    METADATA_ONLY_USER_PROMPT,
    SEMANTIC_GROUPING_SYSTEM_PROMPT,
    SEMANTIC_GROUPING_USER_PROMPT,
    DYNAMIC_SECTION_EXTRACTION_SYSTEM_PROMPT,
    DYNAMIC_SECTION_EXTRACTION_USER_PROMPT,
)
from processors.section_parser import SectionParser, parse_sections_from_html


class MultiCallKBGenerator:
    """Generates structured knowledge base using multiple API calls"""
    
    def __init__(self, client: ClaudeClient):
        self.client = client
    
    def generate(
        self,
        cleaned_html: str,
        image_descriptions: ImageDescriptionsOutput,
        source_url: str,
        page_title: str,
        data_segment: str,
        full_page_screenshot_path: Optional[str] = None
    ) -> KnowledgeBase:
        """
        Generate knowledge base from HTML and image descriptions using multiple calls.
        
        Args:
            cleaned_html: Cleaned HTML content
            image_descriptions: Output from image classification step
            source_url: Source page URL
            page_title: Source page title
            data_segment: Data segment classification
            full_page_screenshot_path: Optional path to full-page screenshot for semantic grouping
            
        Returns:
            KnowledgeBase object
        """
        # Format image descriptions for prompts
        image_desc_json = self._format_image_descriptions(image_descriptions)
        
        # ====================================================================
        # Step 3a: LOCAL - Parse flat section list from DOM (NO LLM)
        # ====================================================================
        print("  Step 3a: Parsing sections from DOM (local)...")
        
        flat_sections, parse_stats = parse_sections_from_html(cleaned_html)
        
        print(f"    ✓ Found {len(flat_sections)} sections from DOM")
        print(f"    ✓ Stats: headings={parse_stats.get('headings', 0)}, faq={parse_stats.get('faq_sections', 0)}, tables={parse_stats.get('tables', 0)}, cta={parse_stats.get('cta_sections', 0)}")
        
        # ====================================================================
        # Step 3b: LLM - Extract metadata only (product, audience, summary)
        # ====================================================================
        print("  Step 3b: Extracting metadata (LLM call)...")
        
        metadata_result = self._extract_metadata_only(
            cleaned_html=cleaned_html,
            section_outline=flat_sections,
            source_url=source_url,
            page_title=page_title,
            data_segment=data_segment
        )
        
        print(f"    ✓ Product: {metadata_result.get('product', 'Unknown')}")
        print(f"    ✓ Target Audience: {metadata_result.get('target_audience', 'Unknown')[:50]}...")
        
        # ====================================================================
        # Step 3c: LLM - Semantic grouping (group flat sections into hierarchy)
        # ====================================================================
        if full_page_screenshot_path:
            print(f"  Step 3c: Semantic grouping with screenshot (LLM call)...")
        else:
            print("  Step 3c: Semantic grouping (LLM call)...")
        
        grouped_sections = self._semantic_grouping(
            flat_sections=flat_sections,
            cleaned_html=cleaned_html,
            page_title=page_title,
            screenshot_path=full_page_screenshot_path
        )
        
        # Count standalone vs grouped
        standalone_count = sum(1 for s in grouped_sections if s.get('type') == 'standalone')
        parent_count = sum(1 for s in grouped_sections if s.get('type') == 'parent')
        child_count = sum(len(s.get('children', [])) for s in grouped_sections if s.get('type') == 'parent')
        
        print(f"    ✓ Grouped into: {standalone_count} standalone, {parent_count} parents with {child_count} children")
        
        # ====================================================================
        # Step 3d: LLM - Extract section content in batches (using grouped structure)
        # ====================================================================
        print("  Step 3d: Extracting section content (LLM calls)...")
        
        all_sections = []
        
        if not grouped_sections:
            print("    ⚠ No sections found, creating single main section...")
            grouped_sections = [{"id": "main_content", "title": "Main Content", "type": "standalone", "level": 1}]
        
        # Flatten grouped sections for batch processing, but preserve hierarchy info
        sections_to_process = self._flatten_grouped_sections(grouped_sections)
        
        # Group sections into batches to avoid token limits
        SECTIONS_PER_BATCH = 4
        section_batches = []
        
        for i in range(0, len(sections_to_process), SECTIONS_PER_BATCH):
            batch = sections_to_process[i:i + SECTIONS_PER_BATCH]
            section_batches.append(batch)
        
        print(f"    Processing {len(sections_to_process)} sections in {len(section_batches)} batches...")
        
        extracted_sections = {}  # Store by ID for later hierarchy reconstruction
        
        for i, batch in enumerate(section_batches):
            batch_titles = [s.get('title', s.get('id', 'Unknown'))[:30] for s in batch]
            print(f"    Batch {i+1}/{len(section_batches)}: {', '.join(batch_titles)}...")
            
            try:
                sections = self._extract_sections_batch(
                    cleaned_html=cleaned_html,
                    image_desc_json=image_desc_json,
                    sections_to_extract=batch,
                    source_url=source_url
                )
                
                if sections:
                    for section in sections:
                        extracted_sections[section.id] = section
                    print(f"      ✓ Extracted {len(sections)} sections")
                else:
                    print(f"      - No sections extracted")
                    
            except Exception as e:
                print(f"      ✗ Error: {e}")
                # Create placeholder sections for failed batch
                for s in batch:
                    placeholder = Section(
                        id=s.get('id', 'unknown'),
                        title=s.get('title', 'Unknown'),
                        level=s.get('level', 1),
                        summary=f"Error extracting section: {str(e)[:100]}",
                        content=None,
                        key_points=[],
                        images=[],
                        subsections=[],
                        data=None
                    )
                    extracted_sections[placeholder.id] = placeholder
                continue
        
        # Reconstruct hierarchy from grouped_sections structure
        all_sections = self._reconstruct_hierarchy(grouped_sections, extracted_sections)
        
        # ====================================================================
        # Step 3e: LOCAL - Merge into final KB
        # ====================================================================
        print("  Step 3e: Merging into final knowledge base...")
        
        kb = self._merge_into_kb(
            metadata_result=metadata_result,
            sections=all_sections,
            image_descriptions=image_descriptions,
            source_url=source_url,
            page_title=page_title,
            data_segment=data_segment
        )
        
        print(f"    ✓ Final KB: {kb.metadata.total_sections} sections, {kb.metadata.total_images_included} images")
        
        return kb
    
    def _format_image_descriptions(self, image_descriptions: ImageDescriptionsOutput) -> str:
        """Format image descriptions for the prompt"""
        included = []
        
        for img in image_descriptions.included_images:
            included.append({
                "image_id": img.image_id,
                "local_path": img.local_path,
                "category": img.category,
                "description": img.description,
                "extracted_text": img.extracted_text,
                "stats": img.stats,
                "suggested_section": img.suggested_section
            })
        
        if not included:
            return "NO_IMAGES_AVAILABLE"
        
        return json.dumps(included, indent=2)
    
    def _has_images(self, image_descriptions: ImageDescriptionsOutput) -> bool:
        """Check if there are any images to process"""
        return len(image_descriptions.included_images) > 0
    
    def _extract_metadata_only(
        self,
        cleaned_html: str,
        section_outline: List[Dict[str, Any]],
        source_url: str,
        page_title: str,
        data_segment: str
    ) -> Dict[str, Any]:
        """Extract document metadata only (no section outline - we have it from DOM)"""
        
        # Format section outline for context
        section_list = "\n".join([
            f"- {s.get('title', 'Unknown')} (level {s.get('level', 1)})"
            for s in section_outline[:20]  # First 20 sections for context
        ])
        
        user_prompt = METADATA_ONLY_USER_PROMPT.format(
            source_url=source_url,
            page_title=page_title,
            data_segment=data_segment,
            section_outline=section_list,
            cleaned_html=cleaned_html[:40000],  # First 40K chars for overview
        )
        
        response = self.client.call_text_only(
            system_prompt=METADATA_ONLY_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=2048
        )
        
        return self.client.parse_json_response(response)
    
    def _semantic_grouping(
        self,
        flat_sections: List[Dict[str, Any]],
        cleaned_html: str,
        page_title: str,
        screenshot_path: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Use LLM to semantically group flat sections into hierarchy"""
        
        # Create trimmed DOM for semantic grouping (reduces tokens while preserving structure)
        trimmed_html = self._create_trimmed_dom(cleaned_html)
        
        print(f"    Trimmed DOM: {len(cleaned_html):,} → {len(trimmed_html):,} chars ({len(trimmed_html)*100//len(cleaned_html)}%)")
        
        # Build prompt with trimmed DOM
        user_prompt = SEMANTIC_GROUPING_USER_PROMPT.format(
            page_title=page_title,
            trimmed_html=trimmed_html
        )
        
        # Call with or without screenshot
        if screenshot_path and os.path.exists(screenshot_path):
            print(f"    Using screenshot: {os.path.basename(screenshot_path)}")
            response = self.client.call_with_image(
                system_prompt=SEMANTIC_GROUPING_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                image_path=screenshot_path,
                max_tokens=4096
            )
        else:
            response = self.client.call_text_only(
                system_prompt=SEMANTIC_GROUPING_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                max_tokens=4096
            )
        
        result = self.client.parse_json_response(response)
        grouped = result.get('grouped_sections', [])
        
        # Log total sections found
        total_found = result.get('total_sections_found', len(grouped))
        print(f"    LLM found {total_found} sections in HTML")
        
        # If grouping failed, return flat sections as standalone (fallback to DOM parsing)
        if not grouped:
            print("    Warning: LLM returned no sections, falling back to DOM parsing")
            return [{"id": s.get('id'), "title": s.get('title'), "type": "standalone", **s} for s in flat_sections]
        
        # Process LLM results - these are the authoritative sections now
        processed_sections = []
        for group in grouped:
            section = {
                'id': group.get('id', self._generate_id(group.get('title', 'unknown'))),
                'title': group.get('title', 'Unknown'),
                'level': group.get('level', 2),
                'type': group.get('type', 'standalone'),
                'section_type': group.get('section_type'),  # faq, table, cta, etc.
                'category': group.get('category'),
            }
            
            # Process children if parent
            if group.get('type') == 'parent' and group.get('children'):
                children = []
                for child in group.get('children', []):
                    children.append({
                        'id': child.get('id', self._generate_id(child.get('title', 'unknown'))),
                        'title': child.get('title', 'Unknown'),
                        'level': child.get('level', section['level'] + 1),
                        'category': child.get('category'),
                        'section_type': child.get('section_type'),
                    })
                section['children'] = children
            
            processed_sections.append(section)
        
        return processed_sections
    
    def _create_trimmed_dom(self, cleaned_html: str, max_para_length: int = 500) -> str:
        """
        Create a trimmed version of the DOM for semantic grouping.
        Preserves structure but truncates long paragraph text to save tokens.
        
        Args:
            cleaned_html: The full cleaned HTML
            max_para_length: Maximum characters to keep in each paragraph
            
        Returns:
            Trimmed HTML with truncated paragraphs
        """
        from bs4 import BeautifulSoup
        
        soup = BeautifulSoup(cleaned_html, 'lxml')
        
        # Tags that contain text content to trim
        text_tags = ['p', 'li', 'td', 'th', 'span', 'div']
        
        for tag in soup.find_all(text_tags):
            # Only process leaf nodes (no nested tags with significant content)
            # Get direct text content
            text = tag.get_text(strip=True)
            
            if len(text) > max_para_length:
                # Check if this tag has child elements (not just text)
                has_child_elements = any(child.name for child in tag.children if hasattr(child, 'name') and child.name)
                
                if not has_child_elements:
                    # This is a text-only element, truncate it
                    truncated = text[:max_para_length] + "..."
                    tag.string = truncated
        
        # Also trim any long text nodes that aren't in specific tags
        for element in soup.find_all(string=True):
            if element.parent.name not in ['script', 'style']:
                text = str(element).strip()
                if len(text) > max_para_length:
                    # Check if parent has multiple children
                    parent = element.parent
                    if parent and len(list(parent.children)) == 1:
                        element.replace_with(text[:max_para_length] + "...")
        
        return str(soup)
    
    def _generate_id(self, title: str) -> str:
        """Generate a section ID from title"""
        import re
        # Convert to lowercase, replace spaces and special chars with underscores
        id_str = re.sub(r'[^a-z0-9]+', '_', title.lower())
        # Remove leading/trailing underscores
        id_str = id_str.strip('_')
        return id_str or 'section'
    
    def _flatten_grouped_sections(self, grouped_sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Flatten grouped sections for batch processing, preserving hierarchy info"""
        flat = []
        
        for section in grouped_sections:
            # Add parent/standalone section
            section_copy = {**section}
            section_copy.pop('children', None)  # Remove children from copy
            flat.append(section_copy)
            
            # Add children if present
            if section.get('type') == 'parent':
                for child in section.get('children', []):
                    child_copy = {**child}
                    child_copy['parent_id'] = section.get('id')
                    child_copy['level'] = section.get('level', 1) + 1
                    flat.append(child_copy)
        
        return flat
    
    def _reconstruct_hierarchy(
        self,
        grouped_sections: List[Dict[str, Any]],
        extracted_sections: Dict[str, Section]
    ) -> List[Section]:
        """Reconstruct section hierarchy from grouped structure and extracted content"""
        result = []
        
        for group in grouped_sections:
            section_id = group.get('id', 'unknown')
            section = extracted_sections.get(section_id)
            
            if not section:
                # Try to find by title match
                for ext_id, ext_section in extracted_sections.items():
                    if ext_section.title.lower() == group.get('title', '').lower():
                        section = ext_section
                        break
            
            if not section:
                # Create placeholder
                section = Section(
                    id=section_id,
                    title=group.get('title', 'Unknown'),
                    level=group.get('level', 1),
                    summary="",
                    content=None,
                    key_points=[],
                    images=[],
                    subsections=[],
                    data=None
                )
            
            # Add children as subsections if this is a parent
            if group.get('type') == 'parent' and group.get('children'):
                subsections = []
                for child in group.get('children', []):
                    child_id = child.get('id', 'unknown')
                    child_section = extracted_sections.get(child_id)
                    
                    if not child_section:
                        # Try title match
                        for ext_id, ext_section in extracted_sections.items():
                            if ext_section.title.lower() == child.get('title', '').lower():
                                child_section = ext_section
                                break
                    
                    if child_section:
                        # Add category if present
                        if child.get('category'):
                            child_section = Section(
                                id=child_section.id,
                                title=child_section.title,
                                level=child_section.level,
                                summary=child_section.summary,
                                content=child_section.content,
                                key_points=child_section.key_points,
                                images=child_section.images,
                                subsections=child_section.subsections,
                                data={**(child_section.data or {}), "category": child.get('category')} if child_section.data or child.get('category') else {"category": child.get('category')} if child.get('category') else None
                            )
                        subsections.append(child_section)
                    else:
                        # Create placeholder child
                        subsections.append(Section(
                            id=child_id,
                            title=child.get('title', 'Unknown'),
                            level=group.get('level', 1) + 1,
                            summary="",
                            content=None,
                            key_points=[],
                            images=[],
                            subsections=[],
                            data={"category": child.get('category')} if child.get('category') else None
                        ))
                
                # Update section with subsections
                section = Section(
                    id=section.id,
                    title=section.title,
                    level=section.level,
                    summary=section.summary,
                    content=section.content,
                    key_points=section.key_points,
                    images=section.images,
                    subsections=subsections,
                    data=section.data
                )
            
            result.append(section)
        
        return result
    
    def _extract_sections_batch(
        self,
        cleaned_html: str,
        image_desc_json: str,
        sections_to_extract: List[Dict[str, Any]],
        source_url: str
    ) -> List[Section]:
        """Extract a batch of sections based on the outline and extraction hints"""
        
        # Build section list for prompt with extraction hints
        section_list = []
        for s in sections_to_extract:
            title = s.get('title', 'Unknown')
            level = s.get('level', 1)
            section_type = s.get('section_type', '')
            extraction_hint = s.get('extraction_hint', '')
            
            # Build section info with extraction hint
            section_info = f"### {title}\n"
            section_info += f"- Level: {level}\n"
            if section_type:
                section_info += f"- Type: {section_type}\n"
            if extraction_hint:
                section_info += f"- EXTRACTION HINT: {extraction_hint}\n"
            else:
                section_info += f"- EXTRACTION HINT: Standard section. Extract intro text and any bullet points as unified prose.\n"
            
            section_list.append(section_info)
        
        section_list_str = "\n".join(section_list)
        
        user_prompt = DYNAMIC_SECTION_EXTRACTION_USER_PROMPT.format(
            section_list=section_list_str,
            cleaned_html=cleaned_html,
            image_descriptions=image_desc_json,
            source_url=source_url
        )
        
        # Text-only call - extraction hints from 3c provide the visual context
        response = self.client.call_text_only(
            system_prompt=DYNAMIC_SECTION_EXTRACTION_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=8192
        )
        
        result = self.client.parse_json_response(response)
        sections_data = result.get('sections', [])
        
        # Convert to Section objects
        sections = []
        for section_dict in sections_data:
            section = self._parse_section(section_dict)
            sections.append(section)
        
        return sections
    
    def _parse_section(self, section_dict: dict) -> Section:
        """Parse a section dictionary into Section object"""
        
        # Parse images
        images = []
        for img_dict in section_dict.get("images", []):
            images.append(SectionImage(
                image_id=img_dict.get("image_id", ""),
                local_path=img_dict.get("local_path", ""),
                category=img_dict.get("category", ""),
                description=img_dict.get("description", "")
            ))
        
        # Parse subsections recursively
        subsections = []
        for sub_dict in section_dict.get("subsections", []):
            subsections.append(self._parse_section(sub_dict))
        
        return Section(
            id=section_dict.get("id", ""),
            title=section_dict.get("title", ""),
            level=section_dict.get("level", 1),
            summary=section_dict.get("summary", ""),
            content=section_dict.get("content"),
            key_points=section_dict.get("key_points", []),
            images=images,
            subsections=subsections,
            data=section_dict.get("data")
        )
    
    def _merge_into_kb(
        self,
        metadata_result: Dict[str, Any],
        sections: List[Section],
        image_descriptions: ImageDescriptionsOutput,
        source_url: str,
        page_title: str,
        data_segment: str
    ) -> KnowledgeBase:
        """Merge all extracted parts into final KnowledgeBase"""
        
        metadata = KBMetadata(
            source_url=source_url,
            page_title=page_title,
            product=metadata_result.get('product'),
            target_audience=metadata_result.get('target_audience'),
            data_segment=data_segment,
            generated_at=datetime.now().isoformat(),
            model=self.client.model,
            total_sections=self._count_sections(sections),
            total_images_included=image_descriptions.processing_metadata.images_included
        )
        
        # Build images summary
        images_summary = AllImagesSummary(
            total_evaluated=image_descriptions.processing_metadata.total_images_evaluated,
            included=image_descriptions.processing_metadata.images_included,
            excluded=image_descriptions.processing_metadata.images_excluded
        )
        
        return KnowledgeBase(
            metadata=metadata,
            document_summary=metadata_result.get('document_summary', ''),
            key_value_proposition=metadata_result.get('key_value_proposition'),
            sections=sections,
            all_images_summary=images_summary,
            last_updated=datetime.now().strftime("%Y-%m-%d")
        )
    
    def _count_sections(self, sections: List[Section]) -> int:
        """Count total sections including subsections"""
        count = len(sections)
        for section in sections:
            count += self._count_sections(section.subsections)
        return count


def generate_knowledge_base(
    client: ClaudeClient,
    cleaned_html: str,
    image_descriptions: ImageDescriptionsOutput,
    source_url: str,
    page_title: str,
    data_segment: str,
    full_page_screenshot_path: Optional[str] = None
) -> KnowledgeBase:
    """
    Convenience function to generate knowledge base using multi-call approach.
    
    Args:
        client: ClaudeClient instance
        cleaned_html: Cleaned HTML content
        image_descriptions: Output from image classification step
        source_url: Source page URL
        page_title: Source page title
        data_segment: Data segment classification
        full_page_screenshot_path: Optional path to full-page screenshot for semantic grouping
        
    Returns:
        KnowledgeBase object
    """
    generator = MultiCallKBGenerator(client)
    return generator.generate(
        cleaned_html=cleaned_html,
        image_descriptions=image_descriptions,
        source_url=source_url,
        page_title=page_title,
        data_segment=data_segment,
        full_page_screenshot_path=full_page_screenshot_path
    )

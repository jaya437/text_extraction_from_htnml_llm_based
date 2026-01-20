"""
Section Parser - Local DOM Section Extraction

Extracts section hierarchy from HTML without using LLM.
Handles:
- H1-H6 headings
- FAQ accordions (button elements)
- Comparison tables
- CTA/Contact sections
- Forms with contact info
"""

import re
from typing import List, Dict, Any, Optional, Tuple
from bs4 import BeautifulSoup, Tag
from dataclasses import dataclass, field


@dataclass
class ParsedSection:
    """Represents a section extracted from DOM"""
    id: str
    title: str
    level: int
    section_type: str  # heading, faq, table, cta, testimonial
    tag: str  # h1, h2, button, table, etc.
    content_preview: str = ""
    has_list: bool = False
    has_subsections: bool = False
    has_table: bool = False
    estimated_content_length: int = 0
    extra_data: Dict[str, Any] = field(default_factory=dict)
    children: List["ParsedSection"] = field(default_factory=list)


class SectionParser:
    """Parses HTML to extract section hierarchy locally"""
    
    def __init__(self):
        self.stats = {
            "total_sections": 0,
            "headings": 0,
            "faq_sections": 0,
            "tables": 0,
            "cta_sections": 0,
            "testimonials": 0,
        }
    
    def parse(self, html_content: str) -> Tuple[List[ParsedSection], Dict[str, Any]]:
        """
        Parse HTML and extract all content sections.
        
        Args:
            html_content: Cleaned HTML string
            
        Returns:
            Tuple of (sections_list, stats)
        """
        # Reset stats
        self.stats = {k: 0 for k in self.stats}
        
        soup = BeautifulSoup(html_content, 'lxml')
        
        sections = []
        seen_ids = set()
        
        # 1. Extract heading-based sections (H1-H4) - includes FAQ accordions and tables within sections
        heading_sections = self._extract_heading_sections(soup, seen_ids)
        sections.extend(heading_sections)
        
        # 2. Extract standalone CTA/Contact sections (phone numbers, forms not under headings)
        cta_sections = self._extract_cta_sections(soup, seen_ids)
        sections.extend(cta_sections)
        
        # 3. Extract standalone testimonial sections
        testimonial_sections = self._extract_testimonial_sections(soup, seen_ids)
        sections.extend(testimonial_sections)
        
        self.stats["total_sections"] = len(sections)
        
        return sections, self.stats
    
    def _extract_heading_sections(self, soup: BeautifulSoup, seen_ids: set) -> List[ParsedSection]:
        """Extract sections based on H1-H4 headings"""
        sections = []
        
        headings = soup.find_all(['h1', 'h2', 'h3', 'h4'])
        
        for heading in headings:
            title = heading.get_text(strip=True)
            if not title or len(title) < 2:
                continue
            
            # Skip navigation/menu headings
            if self._is_navigation_heading(title, heading):
                continue
            
            level = int(heading.name[1])
            section_id = self._generate_unique_id(title, seen_ids)
            
            content_preview, has_list, content_length = self._get_content_preview(heading)
            has_table = self._has_sibling_table(heading)
            
            # Check if this section contains FAQ accordion
            faq_data = self._extract_faq_from_section(heading)
            
            # Check if this section contains a comparison table
            table_data = self._extract_table_from_section(heading)
            
            # Determine section type
            section_type = "heading"
            extra_data = {}
            
            if faq_data:
                section_type = "faq"
                extra_data = {"faq_items": faq_data, "count": len(faq_data)}
                self.stats["faq_sections"] += 1
            elif table_data:
                section_type = "table"
                extra_data = {"table_data": table_data}
                self.stats["tables"] += 1
            
            section = ParsedSection(
                id=section_id,
                title=title,
                level=level,
                section_type=section_type,
                tag=heading.name,
                content_preview=content_preview,
                has_list=has_list,
                has_table=has_table or bool(table_data),
                estimated_content_length=content_length,
                extra_data=extra_data
            )
            
            sections.append(section)
            self.stats["headings"] += 1
        
        return sections
    
    def _extract_faq_from_section(self, heading: Tag) -> List[Dict[str, str]]:
        """Check if heading's section contains FAQ accordion and extract Q&A pairs"""
        faq_items = []
        
        # Get the parent section or container
        parent = heading.find_parent(['section', 'div'])
        if not parent:
            # Look at siblings instead
            parent = heading.parent
        
        if not parent:
            return faq_items
        
        # Look for accordion buttons within this section
        accordion_buttons = parent.find_all('button', attrs={'aria-controls': True})
        
        if not accordion_buttons:
            # Try alternative - buttons with aria-expanded
            accordion_buttons = parent.find_all('button', attrs={'aria-expanded': True})
        
        for button in accordion_buttons:
            question = button.get_text(strip=True)
            if not question or len(question) < 10:
                continue
            
            # Find the answer (usually in sibling div with role="region")
            answer = ""
            answer_div = button.find_next_sibling('div')
            if answer_div:
                answer = answer_div.get_text(strip=True)
            else:
                # Try parent's next sibling
                button_parent = button.parent
                if button_parent:
                    answer_div = button_parent.find('div', attrs={'role': 'region'})
                    if answer_div:
                        answer = answer_div.get_text(strip=True)
            
            if question and (answer or '?' in question):
                faq_items.append({
                    "question": question,
                    "answer": answer
                })
        
        return faq_items
    
    def _extract_table_from_section(self, heading: Tag) -> Optional[Dict[str, Any]]:
        """Check if heading's section contains a table and extract it"""
        # Look for table in siblings
        sibling = heading.find_next_sibling()
        while sibling:
            if sibling.name in ['h1', 'h2', 'h3', 'h4']:
                break
            
            table = None
            if sibling.name == 'table':
                table = sibling
            else:
                table = sibling.find('table')
            
            if table:
                return self._parse_table(table)
            
            sibling = sibling.find_next_sibling()
        
        return None
    
    def _extract_cta_sections(self, soup: BeautifulSoup, seen_ids: set) -> List[ParsedSection]:
        """Extract CTA/Contact sections with phone numbers, forms"""
        sections = []
        
        # Find phone numbers
        phone_pattern = re.compile(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b')
        phone_links = soup.find_all('a', href=re.compile(r'^tel:'))
        
        cta_data = {
            "phone_numbers": [],
            "forms": [],
            "cta_buttons": []
        }
        
        # Extract phone numbers
        seen_phones = set()
        for link in phone_links:
            phone = link.get_text(strip=True)
            href = link.get('href', '')
            
            # Get context (parent text)
            parent = link.find_parent(['p', 'div', 'section'])
            context = ""
            if parent:
                context = parent.get_text(strip=True)[:100]
            
            if phone and phone not in seen_phones:
                seen_phones.add(phone)
                cta_data["phone_numbers"].append({
                    "number": phone,
                    "href": href,
                    "context": context
                })
        
        # Find forms with contact/quote requests
        forms = soup.find_all('form')
        for form in forms:
            form_text = form.get_text(strip=True)[:200]
            
            # Check if it's a contact/quote form
            if any(word in form_text.lower() for word in ['quote', 'contact', 'pricing', 'demo', 'email', 'phone']):
                # Get form fields
                inputs = form.find_all(['input', 'select', 'textarea'])
                fields = []
                for inp in inputs:
                    field_name = inp.get('name') or inp.get('placeholder') or inp.get('aria-label', '')
                    if field_name:
                        fields.append(field_name)
                
                # Get form heading
                form_heading = ""
                prev_heading = form.find_previous(['h1', 'h2', 'h3', 'h4', 'p'])
                if prev_heading:
                    heading_text = prev_heading.get_text(strip=True)
                    if 'role' in str(prev_heading.attrs) or len(heading_text) < 100:
                        form_heading = heading_text
                
                cta_data["forms"].append({
                    "heading": form_heading,
                    "fields": fields,
                    "preview": form_text[:100]
                })
        
        # Find CTA headings (role="heading" pattern often used for CTAs)
        cta_headings = soup.find_all(['p', 'div'], attrs={'role': 'heading'})
        for cta in cta_headings:
            text = cta.get_text(strip=True)
            if text and len(text) > 5:
                cta_data["cta_buttons"].append({"text": text})
        
        # Only create section if we found CTA content
        if cta_data["phone_numbers"] or cta_data["forms"]:
            section_id = self._generate_unique_id("contact_cta", seen_ids)
            section = ParsedSection(
                id=section_id,
                title="Contact & CTA Information",
                level=2,
                section_type="cta",
                tag="cta",
                content_preview=f"{len(cta_data['phone_numbers'])} phone numbers, {len(cta_data['forms'])} forms",
                estimated_content_length=500,
                extra_data=cta_data
            )
            sections.append(section)
            self.stats["cta_sections"] += 1
        
        return sections
    
    def _extract_testimonial_sections(self, soup: BeautifulSoup, seen_ids: set) -> List[ParsedSection]:
        """Extract testimonial/quote sections"""
        sections = []
        
        # Find testimonial containers
        testimonial_keywords = ['testimonial', 'quote', 'client', 'customer', 'hear from', 'what people say']
        
        testimonials = []
        
        # Look for blockquotes
        blockquotes = soup.find_all('blockquote')
        for quote in blockquotes:
            text = quote.get_text(strip=True)
            if text and len(text) > 20:
                testimonials.append({"quote": text, "source": "blockquote"})
        
        # Look for elements with testimonial in class
        for keyword in ['testimonial', 'quote', 'review']:
            elements = soup.find_all(class_=re.compile(keyword, re.I))
            for el in elements:
                text = el.get_text(strip=True)
                if text and len(text) > 50 and text not in [t['quote'] for t in testimonials]:
                    testimonials.append({"quote": text[:500], "source": keyword})
        
        if testimonials:
            section_id = self._generate_unique_id("testimonials", seen_ids)
            section = ParsedSection(
                id=section_id,
                title="Testimonials & Quotes",
                level=2,
                section_type="testimonial",
                tag="testimonial",
                content_preview=f"{len(testimonials)} testimonials found",
                estimated_content_length=sum(len(t['quote']) for t in testimonials),
                extra_data={"testimonials": testimonials}
            )
            sections.append(section)
            self.stats["testimonials"] += 1
        
        return sections
    
    def _parse_table(self, table: Tag) -> Dict[str, Any]:
        """Parse a table into structured data"""
        result = {
            "columns": [],
            "rows": [],
            "categories": []
        }
        
        # Get headers
        headers = table.find_all('th')
        if headers:
            for th in headers:
                header_text = th.get_text(strip=True)
                # Check for images (like logo)
                img = th.find('img')
                if img and not header_text:
                    header_text = img.get('alt', 'Column')
                if header_text:
                    result["columns"].append(header_text)
        
        # Remove duplicates and empty from columns
        result["columns"] = [c for c in result["columns"] if c and c.strip()]
        
        # Get rows
        rows = table.find_all('tr')
        current_category = None
        
        for row in rows:
            cells = row.find_all(['td', 'th'])
            if not cells:
                continue
            
            row_data = []
            is_category_row = False
            
            for cell in cells:
                cell_text = cell.get_text(strip=True)
                
                # Check if cell contains checkmark image
                img = cell.find('img')
                if img:
                    alt = img.get('alt', '').lower()
                    if 'check' in alt or 'offered' in alt or 'yes' in alt:
                        cell_text = "✓ YES"
                    elif 'x' in alt or 'no' in alt:
                        cell_text = "✗ NO"
                
                # Check for "not offered" text
                if 'not offered' in cell_text.lower():
                    cell_text = "✗ NOT OFFERED"
                
                row_data.append(cell_text)
            
            # Check if this is a category header row (like "Payroll", "HR & Business")
            if len(row_data) >= 1 and cells[0].name == 'th':
                first_cell = row_data[0]
                if first_cell and len(first_cell) < 50 and not any(x in first_cell for x in ['✓', '✗']):
                    current_category = first_cell
                    result["categories"].append(current_category)
                    is_category_row = True
            
            if not is_category_row and row_data and any(row_data):
                result["rows"].append({
                    "category": current_category,
                    "cells": row_data
                })
        
        return result
    
    def _get_table_title(self, table: Tag) -> str:
        """Get the title/heading for a table"""
        # Check preceding siblings
        prev = table.find_previous(['h1', 'h2', 'h3', 'h4', 'p'])
        if prev:
            text = prev.get_text(strip=True)
            if len(text) < 200:
                return text
        
        # Check parent section
        parent = table.find_parent('section')
        if parent:
            heading = parent.find(['h1', 'h2', 'h3'])
            if heading:
                return heading.get_text(strip=True)
        
        return ""
    
    def _is_navigation_heading(self, title: str, heading: Tag) -> bool:
        """Check if heading is likely a navigation/menu item"""
        title_lower = title.lower()
        
        if len(title) <= 3:
            return True
        
        nav_patterns = [
            "menu", "nav", "skip to", "jump to", "back to",
            "close", "open", "toggle", "expand", "collapse",
            "sign in", "log in", "search"
        ]
        for pattern in nav_patterns:
            if pattern in title_lower:
                return True
        
        # Check if inside nav/header
        for parent in heading.parents:
            if parent.name in ['nav', 'header', 'footer']:
                return True
        
        return False
    
    def _generate_unique_id(self, title: str, seen_ids: set) -> str:
        """Generate a unique slug ID"""
        slug = title.lower()
        slug = re.sub(r'[®™©]', '', slug)
        slug = re.sub(r'[^\w\s-]', '', slug)
        slug = re.sub(r'[\s-]+', '_', slug)
        slug = slug.strip('_')[:50] or "section"
        
        base_id = slug
        counter = 1
        while slug in seen_ids:
            slug = f"{base_id}_{counter}"
            counter += 1
        
        seen_ids.add(slug)
        return slug
    
    def _get_content_preview(self, heading: Tag) -> Tuple[str, bool, int]:
        """Get preview of content after a heading"""
        content_parts = []
        has_list = False
        total_length = 0
        
        sibling = heading.find_next_sibling()
        
        while sibling:
            if sibling.name and sibling.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                break
            
            if sibling.name in ['ul', 'ol']:
                has_list = True
            
            if hasattr(sibling, 'get_text'):
                text = sibling.get_text(strip=True)
                if text:
                    total_length += len(text)
                    if len(' '.join(content_parts)) < 200:
                        content_parts.append(text)
            
            sibling = sibling.find_next_sibling()
        
        preview = ' '.join(content_parts)[:200]
        if len(preview) >= 200:
            preview += "..."
        
        return preview, has_list, total_length
    
    def _has_sibling_table(self, heading: Tag) -> bool:
        """Check if heading has a table as sibling"""
        sibling = heading.find_next_sibling()
        while sibling:
            if sibling.name in ['h1', 'h2', 'h3', 'h4']:
                break
            if sibling.name == 'table':
                return True
            if sibling.find('table'):
                return True
            sibling = sibling.find_next_sibling()
        return False
    
    def get_sections_for_extraction(
        self,
        sections: List[ParsedSection],
        min_content_length: int = 10
    ) -> List[Dict[str, Any]]:
        """Get sections formatted for LLM extraction"""
        result = []
        
        for section in sections:
            # Include all section types
            section_dict = {
                "id": section.id,
                "title": section.title,
                "level": section.level,
                "type": section.section_type,
                "has_subsections": section.has_subsections,
                "has_list": section.has_list,
                "has_table": section.has_table,
                "content_preview": section.content_preview,
            }
            
            # Include extra data for special sections
            if section.extra_data:
                section_dict["extra_data"] = section.extra_data
            
            result.append(section_dict)
        
        return result
    
    def print_hierarchy(self, sections: List[ParsedSection]) -> str:
        """Print section hierarchy as formatted string"""
        lines = []
        for section in sections:
            indent = "  " * (section.level - 1)
            type_marker = f"[{section.section_type}]"
            extra = ""
            if section.has_table:
                extra += " [TABLE]"
            if section.has_list:
                extra += " [LIST]"
            if section.extra_data:
                extra += f" [DATA: {list(section.extra_data.keys())}]"
            
            lines.append(f"{indent}{section.tag.upper()}: {section.title} {type_marker}{extra}")
        return "\n".join(lines)


def parse_sections_from_html(html_content: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Convenience function to parse sections from HTML.
    
    Returns:
        Tuple of (sections_for_extraction, stats)
    """
    parser = SectionParser()
    sections, stats = parser.parse(html_content)
    
    extraction_sections = parser.get_sections_for_extraction(sections)
    
    return extraction_sections, stats


if __name__ == "__main__":
    # Test with sample HTML
    sample_html = """
    <body>
        <h1>Product Comparison</h1>
        <p>Compare our product with competitors.</p>
        
        <h2>Feature Comparison</h2>
        <table>
            <tr><th>Feature</th><th>Us</th><th>Competitor</th></tr>
            <tr><td>24/7 Support</td><td><img alt="offered"/></td><td>not offered</td></tr>
            <tr><td>Mobile App</td><td><img alt="offered"/></td><td><img alt="offered"/></td></tr>
        </table>
        
        <h2>FAQs</h2>
        <button aria-expanded="false" aria-controls="panel1">How does pricing work?</button>
        <div id="panel1">Our pricing is based on number of employees.</div>
        
        <button aria-expanded="false" aria-controls="panel2">Is there a free trial?</button>
        <div id="panel2">Yes, 30-day free trial available.</div>
        
        <p>Get a quote: <a href="tel:+18001234567">800-123-4567</a></p>
        
        <form>
            <input name="email" placeholder="Your email"/>
            <input name="phone" placeholder="Phone number"/>
            <button>Get Quote</button>
        </form>
    </body>
    """
    
    parser = SectionParser()
    sections, stats = parser.parse(sample_html)
    
    print("=" * 60)
    print("SECTION HIERARCHY")
    print("=" * 60)
    print(parser.print_hierarchy(sections))
    
    print("\n" + "=" * 60)
    print("STATS")
    print("=" * 60)
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    print("\n" + "=" * 60)
    print("SECTIONS FOR EXTRACTION")
    print("=" * 60)
    extraction_sections = parser.get_sections_for_extraction(sections)
    import json
    print(json.dumps(extraction_sections, indent=2))

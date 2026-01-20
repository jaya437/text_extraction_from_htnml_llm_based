"""
HTML Cleaner - Step 1a

Cleans DOM HTML by removing scripts, styles, comments, and unnecessary elements.
Prepares clean HTML for LLM processing.
"""

import re
from typing import Tuple, List
from bs4 import BeautifulSoup, Comment, NavigableString
from pathlib import Path

from config import HTML_CLEAN_CONFIG


class HTMLCleaner:
    """Cleans HTML for knowledge base extraction"""
    
    def __init__(self, config: dict = None):
        self.config = config or HTML_CLEAN_CONFIG
        self.stats = {
            "scripts": 0,
            "styles": 0,
            "comments": 0,
            "hidden_elements": 0,
            "nav_elements": 0,
            "footer_elements": 0,
            "other_removed": 0,
        }
    
    def clean(self, html_content: str) -> Tuple[str, dict]:
        """
        Clean HTML content and return cleaned HTML with stats.
        
        Args:
            html_content: Raw HTML string
            
        Returns:
            Tuple of (cleaned_html, stats_dict)
        """
        # Reset stats
        self.stats = {k: 0 for k in self.stats}
        
        # Parse HTML
        soup = BeautifulSoup(html_content, 'lxml')
        
        # Step 1: Remove tags with content (scripts, styles, etc.)
        self._remove_tags_with_content(soup)
        
        # Step 2: Remove comments
        self._remove_comments(soup)
        
        # Step 3: Remove elements by tag name only (nav, footer)
        # More conservative - only match exact tag names
        self._remove_by_tag_name(soup)
        
        # Step 4: Remove hidden elements
        self._remove_hidden_elements(soup)
        
        # Step 5: Clean attributes
        self._clean_attributes(soup)
        
        # Step 6: Unwrap unnecessary tags
        self._unwrap_tags(soup)
        
        # Step 7: Extract body content only
        body = soup.find('body')
        if body:
            cleaned_html = self._clean_whitespace(str(body))
        else:
            cleaned_html = self._clean_whitespace(str(soup))
        
        return cleaned_html, self.stats.copy()
    
    def _remove_tags_with_content(self, soup: BeautifulSoup) -> None:
        """Remove specified tags and their content"""
        tags_to_remove = self.config.get("remove_tags_with_content", [])
        
        for tag_name in tags_to_remove:
            for tag in soup.find_all(tag_name):
                if tag_name == "script":
                    self.stats["scripts"] += 1
                elif tag_name == "style":
                    self.stats["styles"] += 1
                else:
                    self.stats["other_removed"] += 1
                tag.decompose()
    
    def _remove_comments(self, soup: BeautifulSoup) -> None:
        """Remove HTML comments"""
        comments = soup.find_all(string=lambda text: isinstance(text, Comment))
        for comment in comments:
            self.stats["comments"] += 1
            comment.extract()
    
    def _remove_by_tag_name(self, soup: BeautifulSoup) -> None:
        """
        Remove elements by exact tag name only.
        More conservative than pattern matching on classes.
        """
        # Only remove by exact tag names - not class patterns
        tags_to_remove = ['nav', 'footer', 'aside', 'noscript']
        
        for tag_name in tags_to_remove:
            for tag in soup.find_all(tag_name):
                if tag_name == "nav":
                    self.stats["nav_elements"] += 1
                elif tag_name == "footer":
                    self.stats["footer_elements"] += 1
                else:
                    self.stats["other_removed"] += 1
                tag.decompose()
    
    def _remove_hidden_elements(self, soup: BeautifulSoup) -> None:
        """Remove elements with display:none or hidden attribute"""
        # Elements with hidden attribute
        for tag in soup.find_all(attrs={"hidden": True}):
            self.stats["hidden_elements"] += 1
            tag.decompose()
        
        # Elements with aria-hidden="true" - but be careful not to remove important content
        # Only remove if it's a small element (likely decorative)
        for tag in soup.find_all(attrs={"aria-hidden": "true"}):
            # Don't remove if it contains significant text
            text = tag.get_text(strip=True)
            if len(text) < 50:  # Only remove small hidden elements
                self.stats["hidden_elements"] += 1
                tag.decompose()
        
        # Elements with inline style display:none
        for tag in soup.find_all(style=re.compile(r'display\s*:\s*none', re.I)):
            self.stats["hidden_elements"] += 1
            tag.decompose()
    
    def _clean_attributes(self, soup: BeautifulSoup) -> None:
        """Remove unnecessary attributes from all tags"""
        remove_attrs = self.config.get("remove_attributes", [])
        
        for tag in soup.find_all(True):
            # Get list of attributes to remove
            attrs_to_remove = []
            for attr in list(tag.attrs.keys()):
                # Check direct match
                if attr in remove_attrs:
                    attrs_to_remove.append(attr)
                # Check pattern match (e.g., data-*)
                elif any(attr.startswith(p.replace("*", "")) for p in remove_attrs if "*" in p):
                    attrs_to_remove.append(attr)
            
            # Remove attributes
            for attr in attrs_to_remove:
                del tag[attr]
    
    def _unwrap_tags(self, soup: BeautifulSoup) -> None:
        """Remove tags but keep their content"""
        tags_to_unwrap = self.config.get("unwrap_tags", [])
        
        for tag_name in tags_to_unwrap:
            for tag in soup.find_all(tag_name):
                tag.unwrap()
    
    def _clean_whitespace(self, html: str) -> str:
        """Clean excessive whitespace while preserving structure"""
        # Replace multiple spaces with single space
        html = re.sub(r' +', ' ', html)
        
        # Replace multiple newlines with double newline
        html = re.sub(r'\n\s*\n', '\n\n', html)
        
        # Remove leading/trailing whitespace from lines
        lines = [line.strip() for line in html.split('\n')]
        html = '\n'.join(line for line in lines if line)
        
        return html.strip()
    
    def get_text_content(self, html_content: str) -> str:
        """Extract just the text content from HTML"""
        soup = BeautifulSoup(html_content, 'lxml')
        
        # Get text with proper spacing
        text = soup.get_text(separator='\n', strip=True)
        
        # Clean up whitespace
        text = re.sub(r'\n\s*\n', '\n\n', text)
        
        return text
    
    def create_dom_summary(self, html_content: str, max_length: int = 4000) -> str:
        """
        Create a summary of DOM structure for image context.
        
        Args:
            html_content: Cleaned HTML
            max_length: Maximum length of summary
            
        Returns:
            Text summary of DOM structure
        """
        soup = BeautifulSoup(html_content, 'lxml')
        
        summary_parts = []
        
        # Extract headings with hierarchy
        for level in range(1, 7):
            for heading in soup.find_all(f'h{level}'):
                text = heading.get_text(strip=True)
                if text:
                    summary_parts.append(f"{'#' * level} {text}")
        
        # Extract main content sections
        main_content = soup.find('main') or soup.find('body') or soup
        
        # Get first paragraph of each section
        for section in main_content.find_all(['section', 'article', 'div'], recursive=False):
            first_p = section.find('p')
            if first_p:
                text = first_p.get_text(strip=True)[:200]
                if text:
                    summary_parts.append(f"Content: {text}...")
        
        summary = '\n'.join(summary_parts)
        
        # Truncate if too long
        if len(summary) > max_length:
            summary = summary[:max_length] + "..."
        
        return summary


def clean_html_file(input_path: str, output_path: str = None) -> Tuple[str, dict]:
    """
    Convenience function to clean an HTML file.
    
    Args:
        input_path: Path to input HTML file
        output_path: Optional path to save cleaned HTML
        
    Returns:
        Tuple of (cleaned_html, stats)
    """
    input_path = Path(input_path)
    
    with open(input_path, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    cleaner = HTMLCleaner()
    cleaned_html, stats = cleaner.clean(html_content)
    
    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(cleaned_html)
    
    return cleaned_html, stats


if __name__ == "__main__":
    # Test with sample HTML
    sample_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Test Page</title>
        <style>.hidden { display: none; }</style>
        <script>console.log('test');</script>
    </head>
    <body>
        <nav>Navigation here</nav>
        <main>
            <h1>Main Title</h1>
            <p>This is the main content.</p>
            <!-- This is a comment -->
            <div class="hidden" style="display:none">Hidden content</div>
            <section>
                <h2>Section Title</h2>
                <p>Section content here.</p>
            </section>
        </main>
        <footer>Footer content</footer>
    </body>
    </html>
    """
    
    cleaner = HTMLCleaner()
    cleaned, stats = cleaner.clean(sample_html)
    
    print("=== Cleaned HTML ===")
    print(cleaned)
    print("\n=== Stats ===")
    print(stats)

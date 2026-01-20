"""
Data Segment Detection

Generic utility for extracting basic metadata from URLs.
Product name, target audience, and detailed segment info should be 
extracted by Claude from the actual page content.
"""

from typing import Optional
from urllib.parse import urlparse, unquote
import re


def get_page_slug(url: str) -> str:
    """
    Extract the page slug/name from URL.
    
    Args:
        url: Page URL
        
    Returns:
        Page slug (e.g., "payroll-for-1-49-employees")
    """
    parsed = urlparse(url)
    path = parsed.path
    
    # Remove file extension
    path = re.sub(r'\.[a-zA-Z]+$', '', path)
    
    # Get last path segment
    segments = [s for s in path.split('/') if s]
    if segments:
        return unquote(segments[-1])
    
    return ""


def get_domain(url: str) -> str:
    """
    Extract domain from URL.
    
    Args:
        url: Page URL
        
    Returns:
        Domain name (e.g., "www.adp.com")
    """
    parsed = urlparse(url)
    return parsed.netloc


def detect_data_segment(url: str, title: str = "", segment: str = None) -> str:
    """
    Return data segment for the page.
    
    If segment is provided (via CLI or config), use that.
    Otherwise, return "General" - let Claude infer from content.
    
    Args:
        url: Page URL (unused, kept for compatibility)
        title: Page title (unused, kept for compatibility)
        segment: User-provided segment (optional)
        
    Returns:
        Segment name
    """
    if segment:
        return segment
    return "General"


if __name__ == "__main__":
    # Test URL parsing
    test_urls = [
        "https://www.adp.com/what-we-offer/payroll/payroll-for-1-49-employees.aspx",
        "https://www.example.com/products/enterprise-solution.html",
        "https://www.company.com/services/hr-management",
    ]
    
    print("URL Parsing Tests:")
    for url in test_urls:
        print(f"  URL: {url}")
        print(f"    Domain: {get_domain(url)}")
        print(f"    Slug: {get_page_slug(url)}")
        print(f"    Segment: {detect_data_segment(url)}")
        print()

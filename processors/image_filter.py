"""
Image Filter - Step 1b

Filters images from mapping.json to remove:
- Tracking pixels (1x1)
- Tiny icons (<50px)
- Known UI patterns (close, nav, carousel icons)
- Analytics/tracking images
- Unsupported image formats (only allow jpg/jpeg/png)
- Anything without a file extension
"""

import re
from typing import List, Tuple, Dict, Any
from pathlib import Path

from config import IMAGE_FILTER_CONFIG, IMAGE_BATCH_SIZE
from models import FilteredImage, SkippedImage


class ImageFilter:
    """Filters images to identify content-relevant images"""

    def __init__(self, config: dict = None):
        self.config = config or IMAGE_FILTER_CONFIG
        self.stats = {
            "total": 0,
            "passed": 0,
            "skipped": 0,
            "skip_reasons": {}
        }

    def filter_images(self, images: List[Dict[str, Any]]) -> Tuple[List[FilteredImage], List[SkippedImage]]:
        """
        Filter images based on configuration rules + allowed file types.

        Args:
            images: List of image dictionaries from mapping.json

        Returns:
            Tuple of (passed_images, skipped_images)
        """
        # Reset stats
        self.stats = {
            "total": len(images),
            "passed": 0,
            "skipped": 0,
            "skip_reasons": {}
        }

        passed: List[FilteredImage] = []
        skipped: List[SkippedImage] = []

        allowed_ext = {"jpg", "jpeg", "png"}

        for img in images:
            # Determine file type from local path (mandatory)
            local_path = img.get("local_path") or ""  # Ensure it's never None
            file_type = Path(local_path).suffix.lstrip('.').lower() if local_path else ""

            # Skip images without a valid local path
            if not local_path:
                skip_reason = "missing_local_path"
                self.stats["skipped"] += 1
                self.stats["skip_reasons"][skip_reason] = self.stats["skip_reasons"].get(skip_reason, 0) + 1
                skipped.append(SkippedImage(
                    index=img.get("index", 0),
                    local_path="unknown",
                    skip_reason=skip_reason,
                    pattern_matched=img.get("src", "no_src")[:100],
                    dimensions=None
                ))
                continue

            # Skip anything without an extension OR not allowed
            if not file_type or file_type not in allowed_ext:
                skip_reason = "unsupported_format"

                self.stats["skipped"] += 1
                self.stats["skip_reasons"][skip_reason] = self.stats["skip_reasons"].get(skip_reason, 0) + 1

                skipped.append(SkippedImage(
                    index=img.get("index", 0),
                    local_path=local_path,
                    skip_reason=skip_reason,
                    pattern_matched=file_type or "no_extension",
                    dimensions=None
                ))
                continue

            # Existing filters
            skip_reason, pattern = self._should_skip(img)

            if skip_reason:
                self.stats["skipped"] += 1
                self.stats["skip_reasons"][skip_reason] = self.stats["skip_reasons"].get(skip_reason, 0) + 1

                skipped.append(SkippedImage(
                    index=img.get("index", 0),
                    local_path=local_path,
                    skip_reason=skip_reason,
                    pattern_matched=pattern,
                    dimensions=f"{img.get('width', 0)}x{img.get('height', 0)}" if skip_reason == "tracking_pixel" else None
                ))
            else:
                self.stats["passed"] += 1

                passed.append(FilteredImage(
                    index=img.get("index", 0),
                    local_path=local_path,
                    src=img.get("src", ""),
                    alt=img.get("alt", ""),
                    width=img.get("width"),
                    height=img.get("height"),
                    file_size=img.get("file_size", 0),
                    file_type=file_type
                ))

        return passed, skipped

    def _should_skip(self, img: Dict[str, Any]) -> Tuple[str, str]:
        """
        Check if an image should be skipped.

        Returns:
            Tuple of (skip_reason, pattern_matched) or (None, None) if should include
        """
        width = img.get("width") or 0
        height = img.get("height") or 0
        file_size = img.get("file_size", 0)
        src = img.get("src", "").lower()
        alt = img.get("alt", "").lower()
        local_path = img.get("local_path", "").lower()

        # Check for SVG files - Claude Vision API doesn't support SVG
        if local_path.endswith('.svg') or src.endswith('.svg'):
            return "svg_not_supported", "SVG format not supported by Vision API"

        # Check for tracking pixels (1x1 or very small)
        if width <= 2 and height <= 2:
            return "tracking_pixel", f"{width}x{height}"

        # Check minimum dimensions
        min_width = self.config.get("min_width", 50)
        min_height = self.config.get("min_height", 50)

        if width and height and width < min_width and height < min_height:
            return "tiny_icon", f"{width}x{height} < {min_width}x{min_height}"

        # Check minimum file size
        min_file_size = self.config.get("min_file_size_bytes", 500)
        if file_size > 0 and file_size < min_file_size:
            return "tiny_file", f"{file_size} < {min_file_size} bytes"

        # Check URL patterns to skip
        skip_url_patterns = self.config.get("skip_url_patterns", [])
        for pattern in skip_url_patterns:
            if pattern.lower() in src:
                return "ui_pattern", pattern

        # Check for analytics/tracking domains
        tracking_domains = [
            "rlcdn.com",
            "analytics",
            "bat.bing",
            "t.co",
            "facebook.com/tr",
            "googleadservices",
            "doubleclick",
            "pixel",
        ]
        for domain in tracking_domains:
            if domain in src:
                return "tracking_url", domain

        # Check alt text patterns (but be careful - some valid images have these)
        skip_alt_patterns = self.config.get("skip_alt_patterns", [])

        # Only skip if alt exactly matches a skip pattern (not partial match)
        # This prevents skipping "ADP logo" but allows "Dashboard showing logo placement"
        if alt:
            alt_words = alt.split()
            if len(alt_words) <= 2:  # Only check very short alt texts
                for pattern in skip_alt_patterns:
                    if alt == pattern or alt == f"{pattern} icon":
                        return "alt_pattern", pattern

        # Check local path for icon patterns
        icon_patterns = ["icn-", "icon-", "/icons/", "\\icons\\"]
        for pattern in icon_patterns:
            if pattern in local_path:
                # But don't skip feature icons (they're larger and meaningful)
                if width and height and (width > 100 or height > 100):
                    continue
                return "icon_path", pattern

        return None, None

    def get_stats(self) -> dict:
        """Get filtering statistics"""
        return self.stats.copy()

    def batch_images(
        self,
        images: List[FilteredImage],
        batch_size: int = None
    ) -> List[List[FilteredImage]]:
        """
        Split images into batches for API processing.

        Args:
            images: List of filtered images
            batch_size: Number of images per batch (default from config)

        Returns:
            List of image batches
        """
        batch_size = batch_size or IMAGE_BATCH_SIZE

        batches = []
        for i in range(0, len(images), batch_size):
            batches.append(images[i:i + batch_size])

        return batches


def filter_images_from_mapping(mapping_data: dict) -> Tuple[List[FilteredImage], List[SkippedImage], dict]:
    """
    Convenience function to filter images from mapping.json data.

    Args:
        mapping_data: Parsed mapping.json dictionary

    Returns:
        Tuple of (passed_images, skipped_images, stats)
    """
    images = mapping_data.get("images", [])

    img_filter = ImageFilter()
    passed, skipped = img_filter.filter_images(images)
    stats = img_filter.get_stats()

    return passed, skipped, stats


if __name__ == "__main__":
    # Test with sample image data
    sample_images = [
        {
            "index": 0,
            "src": "https://example.com/logo.svg",
            "alt": "logo",
            "width": 100,
            "height": 50,
            "local_path": "images/img_000.svg",
            "file_size": 1000
        },
        {
            "index": 1,
            "src": "https://example.com/tracking.gif",
            "alt": "",
            "width": 1,
            "height": 1,
            "local_path": "images/img_001.gif",
            "file_size": 43
        },
        {
            "index": 2,
            "src": "https://example.com/icn-close.svg",
            "alt": "",
            "width": 20,
            "height": 20,
            "local_path": "images/img_002.svg",
            "file_size": 500
        },
        {
            "index": 3,
            "src": "https://example.com/hero-image.png",
            "alt": "Product dashboard",
            "width": 800,
            "height": 600,
            "local_path": "images/img_003.png",
            "file_size": 50000
        },
        {
            "index": 4,
            "src": "https://example.com/feature-icon.svg",
            "alt": "Tax compliance",
            "width": 400,
            "height": 400,
            "local_path": "images/img_004.svg",
            "file_size": 15000
        },
        {
            "index": 5,
            "src": "https://example.com/noext?id=123",
            "alt": "No extension",
            "width": 300,
            "height": 200,
            "local_path": "images/img_005",
            "file_size": 12000
        },
        {
            "index": 6,
            "src": "https://example.com/photo.jpeg",
            "alt": "Valid jpeg",
            "width": 640,
            "height": 480,
            "local_path": "images/img_006.jpeg",
            "file_size": 42000
        },
    ]

    img_filter = ImageFilter()
    passed, skipped = img_filter.filter_images(sample_images)

    print("=== Passed Images ===")
    for img in passed:
        print(f"  {img.index}: {img.local_path} ({img.width}x{img.height}) [{img.file_type}]")

    print("\n=== Skipped Images ===")
    for img in skipped:
        print(f"  {img.index}: {img.local_path} - {img.skip_reason} ({img.pattern_matched})")

    print("\n=== Stats ===")
    print(img_filter.get_stats())

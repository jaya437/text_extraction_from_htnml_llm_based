#!/usr/bin/env python3
"""
HTML Knowledge Base Extractor - Main Entry Point (Batch Processing Version)

Processes multiple scraped HTML folders and creates structured knowledge base articles.

Usage:
    python main.py

Configuration:
    Edit DOM_FOLDER and other settings in the main() function.

Input structure:
    DOMFolder/
    ├── General__data-privacy/
    │   ├── data-privacy_dom.html
    │   ├── data-privacy_mapping.json
    │   └── images/
    ├── General__data-security/
    │   ├── data-security_dom.html
    │   ├── data-security_mapping.json
    │   └── images/
    └── ...

Output:
    Saves output files to the SAME directory as input:
    DOMFolder/
    ├── General__data-privacy/
    │   ├── data-privacy_dom.html
    │   ├── data-privacy_mapping.json
    │   ├── images/
    │   ├── kb_cleaned_dom.html        (generated)
    │   ├── kb_preprocessed_data.json  (generated)
    │   ├── kb_image_descriptions.json (generated)
    │   └── kb_knowledge_base.json     (generated)
    └── ...

Environment:
    ANTHROPIC_API_KEY: Your Claude API key
"""

import os
import sys
import glob
import time
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from config import Config, OutputConfig, IMAGE_BATCH_SIZE
from models import (
    PreprocessedData,
    SourceInfo,
    CleaningStats,
    ImageFilteringStats,
)
from processors import HTMLCleaner, ImageFilter
from llm import ClaudeClient, classify_images, generate_knowledge_base
from utils import (
    load_json,
    save_json,
    load_text,
    save_text,
    ensure_dir,
    detect_data_segment,
)


# ==============================================================================
# Progress Report Manager
# ==============================================================================

class ProgressReport:
    """Manages processing progress report"""
    
    def __init__(self, report_path: str):
        self.report_path = Path(report_path)
        self.data = self._load_or_create()
    
    def _load_or_create(self) -> Dict[str, Any]:
        """Load existing report or create new one"""
        if self.report_path.exists():
            try:
                with open(self.report_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        
        return {
            "created_at": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat(),
            "summary": {
                "total_folders": 0,
                "processed": 0,
                "failed": 0,
                "skipped": 0,
                "pending": 0
            },
            "folders": {}
        }
    
    def save(self) -> None:
        """Save report to file"""
        self.data["last_updated"] = datetime.now().isoformat()
        with open(self.report_path, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
    
    def is_processed(self, folder_name: str) -> bool:
        """Check if folder was already successfully processed"""
        folder_data = self.data["folders"].get(folder_name, {})
        return folder_data.get("status") == "success"
    
    def mark_started(self, folder_name: str) -> None:
        """Mark folder as started processing"""
        self.data["folders"][folder_name] = {
            "status": "processing",
            "started_at": datetime.now().isoformat(),
            "completed_at": None,
            "error": None,
            "result": None
        }
        self.save()
    
    def mark_success(self, folder_name: str, result: Dict[str, Any]) -> None:
        """Mark folder as successfully processed"""
        self.data["folders"][folder_name] = {
            "status": "success",
            "started_at": self.data["folders"].get(folder_name, {}).get("started_at"),
            "completed_at": datetime.now().isoformat(),
            "error": None,
            "result": {
                "source_url": result.get("source_url", ""),
                "page_title": result.get("page_title", ""),
                "sections": result.get("sections", 0),
                "images_included": result.get("images_included", 0),
                "kb_path": result.get("kb_path", "")
            }
        }
        self._update_summary()
        self.save()
    
    def mark_failed(self, folder_name: str, error: str) -> None:
        """Mark folder as failed"""
        self.data["folders"][folder_name] = {
            "status": "failed",
            "started_at": self.data["folders"].get(folder_name, {}).get("started_at"),
            "completed_at": datetime.now().isoformat(),
            "error": error,
            "result": None
        }
        self._update_summary()
        self.save()
    
    def mark_skipped(self, folder_name: str, reason: str) -> None:
        """Mark folder as skipped"""
        self.data["folders"][folder_name] = {
            "status": "skipped",
            "started_at": None,
            "completed_at": datetime.now().isoformat(),
            "error": reason,
            "result": None
        }
        self._update_summary()
        self.save()
    
    def _update_summary(self) -> None:
        """Update summary counts"""
        statuses = [f.get("status") for f in self.data["folders"].values()]
        self.data["summary"] = {
            "total_folders": len(statuses),
            "processed": statuses.count("success"),
            "failed": statuses.count("failed"),
            "skipped": statuses.count("skipped"),
            "pending": statuses.count("processing") + statuses.count(None)
        }
    
    def set_total_folders(self, count: int) -> None:
        """Set total folder count"""
        self.data["summary"]["total_folders"] = count
        self.save()
    
    def get_summary_string(self) -> str:
        """Get summary as formatted string"""
        s = self.data["summary"]
        return f"Processed: {s['processed']}/{s['total_folders']} | Failed: {s['failed']} | Skipped: {s['skipped']}"


# ==============================================================================
# HTML Knowledge Base Extractor (with rate limit handling)
# ==============================================================================

class HTMLKnowledgeBaseExtractor:
    """Main class for extracting knowledge base from HTML"""
    
    def __init__(self, config: Config = None):
        self.config = config or Config()
        self.config.validate()
        
        self.client = ClaudeClient(
            api_key=self.config.api_key,
            model=self.config.model,
            api_delay=self.config.api_delay,
            max_retries=self.config.max_retries
        )
    
    def process(
        self,
        input_folder: str,
        output_folder: str = None
    ) -> dict:
        """
        Process a scraped page folder and generate knowledge base.
        
        Args:
            input_folder: Path to folder with HTML, mapping, and images
            output_folder: Path for output files (default: same as input_folder)
            
        Returns:
            Dictionary with processing results
        """
        input_path = Path(input_folder)
        # Output to same folder as input
        output_path = Path(output_folder) if output_folder else input_path
        ensure_dir(output_path)
        
        # Get base name for output files (from folder name)
        folder_name = input_path.name
        
        print("=" * 60)
        print("HTML KNOWLEDGE BASE EXTRACTOR")
        print("=" * 60)
        print(f"Processing: {folder_name}")
        print(f"Input:  {input_path}")
        print(f"Output: {output_path}")
        print()
        
        # ====================================================================
        # STEP 1: Local Preprocessing
        # ====================================================================
        print("STEP 1: Local Preprocessing")
        print("-" * 40)
        
        # Find input files
        html_files = glob.glob(str(input_path / "*_dom.html"))
        mapping_files = glob.glob(str(input_path / "*_mapping.json"))
        
        if not html_files:
            raise FileNotFoundError(f"No *_dom.html file found in {input_path}")
        if not mapping_files:
            raise FileNotFoundError(f"No *_mapping.json file found in {input_path}")
        
        html_file = html_files[0]
        mapping_file = mapping_files[0]
        images_folder = input_path / "images"
        
        # Extract base name from HTML file (e.g., "data-privacy" from "data-privacy_dom.html")
        html_base_name = Path(html_file).stem.replace("_dom", "")
        
        print(f"  HTML file:    {Path(html_file).name}")
        print(f"  Mapping file: {Path(mapping_file).name}")
        print(f"  Images folder: {images_folder}")
        
        # Load mapping data
        mapping_data = load_json(mapping_file)
        source_url = mapping_data.get("url", "")
        page_title = mapping_data.get("page_title", "")
        
        print(f"\n  Source URL: {source_url}")
        print(f"  Page Title: {page_title}")
        
        # Detect segment from folder name (e.g., "General" from "General__data-privacy")
        if "__" in folder_name:
            data_segment = folder_name.split("__")[0]
        else:
            data_segment = detect_data_segment(source_url, page_title)
        
        print(f"  Data Segment: {data_segment}")
        print(f"  (Product name and target audience will be extracted from content)")
        
        # Clean HTML
        print("\n  Cleaning HTML...")
        html_content = load_text(html_file)
        original_size = len(html_content)
        
        cleaner = HTMLCleaner()
        cleaned_html, cleaning_stats = cleaner.clean(html_content)
        cleaned_size = len(cleaned_html)
        
        print(f"    Original: {original_size:,} bytes")
        print(f"    Cleaned:  {cleaned_size:,} bytes ({100 * cleaned_size / original_size:.1f}%)")
        print(f"    Removed: {cleaning_stats}")
        
        # Save cleaned HTML with kb_ prefix
        cleaned_html_path = output_path / f"kb_{html_base_name}_cleaned_dom.html"
        save_text(cleaned_html, cleaned_html_path)
        
        # Create DOM summary for image context
        dom_summary = cleaner.create_dom_summary(cleaned_html)
        
        # Filter images
        print("\n  Filtering images...")
        images = mapping_data.get("images", [])
        
        image_filter = ImageFilter()
        filtered_images, skipped_images = image_filter.filter_images(images)
        filter_stats = image_filter.get_stats()
        
        print(f"    Total: {filter_stats['total']}")
        print(f"    Passed: {filter_stats['passed']}")
        print(f"    Skipped: {filter_stats['skipped']}")
        print(f"    Reasons: {filter_stats['skip_reasons']}")
        
        # Create batches
        batches = image_filter.batch_images(filtered_images, self.config.image_batch_size)
        print(f"    Batches: {len(batches)} (size {self.config.image_batch_size})")
        
        # Save preprocessing data
        preprocessed = PreprocessedData(
            source=SourceInfo(
                url=source_url,
                page_title=page_title,
                scraped_at=mapping_data.get("scraped_at", "")
            ),
            cleaning_stats=CleaningStats(
                original_dom_size=original_size,
                cleaned_dom_size=cleaned_size,
                estimated_tokens=cleaned_size // 4,
                elements_removed=cleaning_stats
            ),
            image_filtering=ImageFilteringStats(
                total_original=filter_stats['total'],
                passed_filter=filter_stats['passed'],
                skipped=filter_stats['skipped'],
                skipped_reasons=filter_stats['skip_reasons']
            ),
            filtered_images=filtered_images,
            skipped_images=skipped_images,
            cleaned_dom_path=str(cleaned_html_path)
        )
        
        if self.config.output.save_intermediate:
            save_json(preprocessed, output_path / f"kb_{html_base_name}_preprocessed_data.json")
        
        print("\n  ✓ Step 1 complete")
        
        # ====================================================================
        # STEP 2: Image Classification (Optional - can be skipped to save costs)
        # ====================================================================
        print("\nSTEP 2: Image Classification")
        print("-" * 40)
        
        if self.config.skip_image_processing:
            print("  ⏭ SKIPPED (skip_image_processing=True)")
            print("  Creating empty image descriptions...")
            
            # Create empty image descriptions
            from models import ProcessingMetadata, ImageDescriptionsOutput
            image_descriptions = ImageDescriptionsOutput(
                processing_metadata=ProcessingMetadata(
                    source_url=source_url,
                    model=self.config.model,
                    processed_at=datetime.now().isoformat(),
                    batches_processed=0,
                    total_images_evaluated=0,
                    images_included=0,
                    images_excluded=0
                ),
                included_images=[],
                excluded_images=[]
            )
        else:
            image_descriptions = classify_images(
                client=self.client,
                filtered_images=filtered_images,
                dom_summary=dom_summary,
                source_url=source_url,
                page_title=page_title,
                base_path=str(input_path),
                batch_size=self.config.image_batch_size
            )
            
            print(f"\n  Summary:")
            print(f"    Evaluated: {image_descriptions.processing_metadata.total_images_evaluated}")
            print(f"    Included:  {image_descriptions.processing_metadata.images_included}")
            print(f"    Excluded:  {image_descriptions.processing_metadata.images_excluded}")
        
        # Save image descriptions
        if self.config.output.save_intermediate:
            save_json(image_descriptions, output_path / f"kb_{html_base_name}_image_descriptions.json")
        
        print("\n  ✓ Step 2 complete")
        
        # ====================================================================
        # STEP 3: Knowledge Base Generation
        # ====================================================================
        print("\nSTEP 3: Knowledge Base Generation")
        print("-" * 40)
        
        # Find full-page screenshot if available and enabled
        full_page_screenshot = None
        if self.config.use_screenshot_for_grouping:
            screenshots_folder = input_path / "screenshots"
            if screenshots_folder.exists():
                # Look for full_page screenshot - prioritize exact name match
                # Priority order: exact match first, then wildcards
                full_page_patterns = [
                    # Exact matches first
                    f"{html_base_name}_full_page.jpg",
                    f"{html_base_name}_full_page.png",
                    f"{html_base_name}-full_page.jpg",
                    f"{html_base_name}-full_page.png",
                    # Then patterns starting with base name
                    f"{html_base_name}*full_page*.jpg",
                    f"{html_base_name}*full_page*.png",
                ]
                
                for pattern in full_page_patterns:
                    matches = list(screenshots_folder.glob(pattern))
                    if matches:
                        full_page_screenshot = str(matches[0])
                        print(f"  Found full-page screenshot: {Path(full_page_screenshot).name}")
                        break
                
                # If no exact match, try any full_page file (fallback)
                if not full_page_screenshot:
                    fallback_patterns = ["*_full_page.jpg", "*_full_page.png"]
                    for pattern in fallback_patterns:
                        matches = list(screenshots_folder.glob(pattern))
                        if matches:
                            full_page_screenshot = str(matches[0])
                            print(f"  Found full-page screenshot (fallback): {Path(full_page_screenshot).name}")
                            break
                
                if not full_page_screenshot:
                    print("  No full-page screenshot found in screenshots folder")
            else:
                print("  No screenshots folder found")
        
        knowledge_base = generate_knowledge_base(
            client=self.client,
            cleaned_html=cleaned_html,
            image_descriptions=image_descriptions,
            source_url=source_url,
            page_title=page_title,
            data_segment=data_segment,
            full_page_screenshot_path=full_page_screenshot
        )
        
        print(f"\n  Summary:")
        print(f"    Sections: {knowledge_base.metadata.total_sections}")
        print(f"    Images:   {knowledge_base.metadata.total_images_included}")
        
        # Save knowledge base
        kb_path = output_path / f"kb_{html_base_name}_knowledge_base.json"
        save_json(knowledge_base, kb_path)
        
        print(f"\n  ✓ Step 3 complete")
        
        # ====================================================================
        # Summary
        # ====================================================================
        print("\n" + "=" * 60)
        print("PROCESSING COMPLETE")
        print("=" * 60)
        print(f"\nOutput files in {output_path}:")
        if self.config.output.save_intermediate:
            print(f"  ├── kb_{html_base_name}_cleaned_dom.html")
            print(f"  ├── kb_{html_base_name}_preprocessed_data.json")
            print(f"  ├── kb_{html_base_name}_image_descriptions.json")
        print(f"  └── kb_{html_base_name}_knowledge_base.json")
        
        return {
            "success": True,
            "input_folder": str(input_path),
            "output_folder": str(output_path),
            "source_url": source_url,
            "page_title": page_title,
            "data_segment": data_segment,
            "sections": knowledge_base.metadata.total_sections,
            "images_included": knowledge_base.metadata.total_images_included,
            "kb_path": str(kb_path)
        }


# ==============================================================================
# Batch Processing Functions
# ==============================================================================

def discover_folders(dom_folder: str) -> List[Path]:
    """
    Discover all subfolders containing DOM files to process.
    
    Args:
        dom_folder: Parent folder containing subdirectories
        
    Returns:
        List of folder paths to process
    """
    dom_path = Path(dom_folder)
    folders = []
    
    for item in sorted(dom_path.iterdir()):
        if item.is_dir():
            # Check if folder contains required files
            html_files = list(item.glob("*_dom.html"))
            mapping_files = list(item.glob("*_mapping.json"))
            
            if html_files and mapping_files:
                folders.append(item)
            else:
                print(f"  ⚠ Skipping {item.name}: missing _dom.html or _mapping.json")
    
    return folders


def process_with_rate_limit_retry(
    extractor: HTMLKnowledgeBaseExtractor,
    folder: Path,
    max_retries: int = 3,
    rate_limit_wait: int = 60
) -> Dict[str, Any]:
    """
    Process a folder with rate limit retry handling.
    
    Args:
        extractor: HTMLKnowledgeBaseExtractor instance
        folder: Folder to process
        max_retries: Maximum number of retries on rate limit
        rate_limit_wait: Seconds to wait when rate limited
        
    Returns:
        Processing result dictionary
    """
    for attempt in range(max_retries):
        try:
            result = extractor.process(
                input_folder=str(folder),
                output_folder=str(folder)  # Output to same folder
            )
            return result
            
        except Exception as e:
            error_str = str(e).lower()
            
            # Check if it's a rate limit error
            if "rate" in error_str or "limit" in error_str or "429" in error_str or "token" in error_str:
                if attempt < max_retries - 1:
                    print(f"\n⚠ Rate limit hit. Waiting {rate_limit_wait} seconds before retry...")
                    print(f"  Attempt {attempt + 1}/{max_retries}")
                    time.sleep(rate_limit_wait)
                    continue
            
            # Re-raise if not rate limit or max retries exceeded
            raise
    
    raise Exception(f"Failed after {max_retries} retries due to rate limiting")


def process_all_folders(
    dom_folder: str,
    config: Config,
    report: ProgressReport,
    skip_processed: bool = True,
    rate_limit_wait: int = 60
) -> None:
    """
    Process all folders in the DOM folder.
    
    Args:
        dom_folder: Parent folder containing subdirectories
        config: Configuration object
        report: Progress report manager
        skip_processed: Whether to skip already processed folders
        rate_limit_wait: Seconds to wait when rate limited
    """
    # Discover folders
    print("\n" + "=" * 70)
    print("BATCH PROCESSING - HTML KNOWLEDGE BASE EXTRACTOR")
    print("=" * 70)
    print(f"\nDOM Folder: {dom_folder}")
    print("\nDiscovering folders to process...")
    
    folders = discover_folders(dom_folder)
    
    if not folders:
        print("No folders found to process!")
        return
    
    print(f"\nFound {len(folders)} folders to process:")
    for i, folder in enumerate(folders, 1):
        status = "✓ done" if report.is_processed(folder.name) else "○ pending"
        print(f"  {i:2}. {folder.name} [{status}]")
    
    report.set_total_folders(len(folders))
    
    # Create extractor
    extractor = HTMLKnowledgeBaseExtractor(config)
    
    # Process each folder
    print("\n" + "-" * 70)
    print("STARTING BATCH PROCESSING")
    print("-" * 70)
    
    for i, folder in enumerate(folders, 1):
        folder_name = folder.name
        
        print(f"\n[{i}/{len(folders)}] Processing: {folder_name}")
        print(f"    {report.get_summary_string()}")
        
        # Skip if already processed
        if skip_processed and report.is_processed(folder_name):
            print(f"    ⏭ Skipping (already processed)")
            continue
        
        # Mark as started
        report.mark_started(folder_name)
        
        try:
            # Process with rate limit retry
            result = process_with_rate_limit_retry(
                extractor=extractor,
                folder=folder,
                max_retries=3,
                rate_limit_wait=rate_limit_wait
            )
            
            # Mark success
            report.mark_success(folder_name, result)
            print(f"\n    ✅ Success: {result['sections']} sections, {result['images_included']} images")
            
        except FileNotFoundError as e:
            report.mark_skipped(folder_name, str(e))
            print(f"\n    ⏭ Skipped: {e}")
            
        except Exception as e:
            report.mark_failed(folder_name, str(e))
            print(f"\n    ❌ Failed: {e}")
            import traceback
            traceback.print_exc()
        
        # Small delay between folders to avoid rate limits
        if i < len(folders):
            print(f"\n    Waiting 5 seconds before next folder...")
            time.sleep(5)
    
    # Final summary
    print("\n" + "=" * 70)
    print("BATCH PROCESSING COMPLETE")
    print("=" * 70)
    print(f"\n{report.get_summary_string()}")
    print(f"\nProgress report saved to: {report.report_path}")


# ==============================================================================
# Main Entry Point
# ==============================================================================

def main():
    """
    Script entry point
    Process multiple folders and generate knowledge bases
    """
    
    # =========================================================================
    # CONFIGURATION - Edit these settings
    # =========================================================================
    
    # Parent folder containing all subfolders to process
    DOM_FOLDER = "./DOMFolder"
    
    # Progress report file (saved in DOM_FOLDER)
    REPORT_FILE = "./DOMFolder/kb_processing_report.json"
    
    # Model settings
    MODEL = "claude-sonnet-4-20250514"
    BATCH_SIZE = IMAGE_BATCH_SIZE
    API_DELAY = 2.0
    
    # Processing settings
    SKIP_PROCESSED = True  # Skip folders that were already successfully processed
    RATE_LIMIT_WAIT = 60   # Seconds to wait when rate limited
    SAVE_INTERMEDIATE = True  # Save intermediate files (cleaned_dom, preprocessed, etc.)
    SKIP_IMAGE_PROCESSING = True  # Set to True to skip image classification (Step 2) - saves API costs
    
    # =========================================================================
    # Setup
    # =========================================================================
    
    # Get API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: Set ANTHROPIC_API_KEY environment variable")
        sys.exit(1)
    
    # Validate DOM folder
    if not os.path.isdir(DOM_FOLDER):
        print(f"\n❌ Error: DOM folder not found: {DOM_FOLDER}")
        sys.exit(1)
    
    # Create config
    config = Config(
        api_key=api_key,
        model=MODEL,
        api_delay=API_DELAY,
        image_batch_size=BATCH_SIZE,
        output=OutputConfig(
            save_intermediate=SAVE_INTERMEDIATE
        ),
        skip_image_processing=SKIP_IMAGE_PROCESSING
    )
    
    # Initialize progress report
    report = ProgressReport(REPORT_FILE)
    
    # =========================================================================
    # Process
    # =========================================================================
    
    try:
        process_all_folders(
            dom_folder=DOM_FOLDER,
            config=config,
            report=report,
            skip_processed=SKIP_PROCESSED,
            rate_limit_wait=RATE_LIMIT_WAIT
        )
        
    except KeyboardInterrupt:
        print("\n\n⚠ Processing interrupted by user")
        print(f"Progress saved to: {REPORT_FILE}")
        sys.exit(0)
        
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

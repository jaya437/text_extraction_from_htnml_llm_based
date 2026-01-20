"""
Image Classifier - Step 2

Sends batches of images to Claude for classification and description.
"""

import json
from typing import List, Dict, Any, Tuple
from datetime import datetime
from pathlib import Path

from models import (
    FilteredImage,
    ImageDescription,
    ExcludedImage,
    ProcessingMetadata,
    ImageDescriptionsOutput,
)
from llm.client import ClaudeClient
from llm.prompts_multi import (
    IMAGE_CLASSIFICATION_SYSTEM_PROMPT,
    format_image_classification_prompt,
)
from config import INCLUDE_CATEGORIES


class ImageClassifier:
    """Classifies and describes images using Claude"""
    
    def __init__(self, client: ClaudeClient, base_path: str = ""):
        """
        Initialize image classifier.
        
        Args:
            client: ClaudeClient instance
            base_path: Base directory for image files
        """
        self.client = client
        self.base_path = base_path
    
    def classify_batch(
        self,
        images: List[FilteredImage],
        dom_summary: str,
        source_url: str,
        page_title: str
    ) -> Tuple[List[ImageDescription], List[ExcludedImage]]:
        """
        Classify a batch of images.
        
        Args:
            images: List of filtered images to classify
            dom_summary: Summary of DOM for context
            source_url: Source page URL
            page_title: Source page title
            
        Returns:
            Tuple of (included_images, excluded_images)
        """
        if not images:
            return [], []
        
        # Build image paths list with image IDs for reference
        image_paths = []
        image_id_map = {}
        
        for img in images:
            local_path = img.local_path.replace("\\", "/")
            image_paths.append(local_path)
            image_id = f"img_{img.index:03d}"
            image_id_map[image_id] = img
        
        # Create prompt with image IDs listed
        image_list_text = "\n".join([
            f"- Image {i+1}: img_{img.index:03d} (file: {img.local_path}, {img.width}x{img.height}, {img.file_type})"
            for i, img in enumerate(images)
        ])
        
        user_prompt = format_image_classification_prompt(
            num_images=len(images),
            dom_summary=dom_summary + f"\n\n## Image Files (in order):\n{image_list_text}",
            source_url=source_url,
            page_title=page_title
        )
        
        # Make API call with images
        response = self.client.call_with_images(
            system_prompt=IMAGE_CLASSIFICATION_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            image_paths=image_paths,
            base_path=self.base_path,
            max_tokens=4096
        )
        
        # Parse response
        result = self.client.parse_json_response(response)
        
        # Process classifications
        included = []
        excluded = []
        
        classifications = result.get("images", [])
        
        for classification in classifications:
            image_id = classification.get("image_id", "")
            
            # Find matching image from our list
            if image_id in image_id_map:
                img = image_id_map[image_id]
            else:
                # Try to match by index if ID format differs
                for key, img in image_id_map.items():
                    if str(img.index) in image_id:
                        break
                else:
                    print(f"Warning: Could not find image for ID {image_id}")
                    continue
            
            include = classification.get("include", False)
            category = classification.get("category", "decorative_other")
            
            # Override: Always include if category is in INCLUDE_CATEGORIES
            if category in INCLUDE_CATEGORIES:
                include = True
            
            if include:
                included.append(ImageDescription(
                    image_id=f"img_{img.index:03d}",
                    local_path=img.local_path,
                    category=category,
                    description=classification.get("description", ""),
                    extracted_text=classification.get("extracted_text"),
                    stats=classification.get("stats"),
                    suggested_section=classification.get("suggested_section")
                ))
            else:
                excluded.append(ExcludedImage(
                    image_id=f"img_{img.index:03d}",
                    local_path=img.local_path,
                    category=category,
                    exclusion_reason=classification.get("exclusion_reason", "Classified as decorative")
                ))
        
        return included, excluded
    
    def classify_all(
        self,
        image_batches: List[List[FilteredImage]],
        dom_summary: str,
        source_url: str,
        page_title: str
    ) -> ImageDescriptionsOutput:
        """
        Classify all image batches.
        
        Args:
            image_batches: List of image batches
            dom_summary: Summary of DOM for context
            source_url: Source page URL
            page_title: Source page title
            
        Returns:
            ImageDescriptionsOutput with all classifications
        """
        all_included = []
        all_excluded = []
        total_images = sum(len(batch) for batch in image_batches)
        
        print(f"Classifying {total_images} images in {len(image_batches)} batches...")
        
        for i, batch in enumerate(image_batches):
            print(f"  Processing batch {i + 1}/{len(image_batches)} ({len(batch)} images)...")
            
            try:
                included, excluded = self.classify_batch(
                    images=batch,
                    dom_summary=dom_summary,
                    source_url=source_url,
                    page_title=page_title
                )
                all_included.extend(included)
                all_excluded.extend(excluded)
                
                print(f"    ✓ {len(included)} included, {len(excluded)} excluded")
                
            except Exception as e:
                print(f"    ✗ Error processing batch: {e}")
                # Add all images as excluded on error
                for img in batch:
                    all_excluded.append(ExcludedImage(
                        image_id=f"img_{img.index:03d}",
                        local_path=img.local_path,
                        category="error",
                        exclusion_reason=f"Processing error: {str(e)}"
                    ))
        
        # Create output
        return ImageDescriptionsOutput(
            processing_metadata=ProcessingMetadata(
                source_url=source_url,
                model=self.client.model,
                processed_at=datetime.now().isoformat(),
                batches_processed=len(image_batches),
                total_images_evaluated=total_images,
                images_included=len(all_included),
                images_excluded=len(all_excluded)
            ),
            included_images=all_included,
            excluded_images=all_excluded
        )


def classify_images(
    client: ClaudeClient,
    filtered_images: List[FilteredImage],
    dom_summary: str,
    source_url: str,
    page_title: str,
    base_path: str = "",
    batch_size: int = 10
) -> ImageDescriptionsOutput:
    """
    Convenience function to classify images.
    
    Args:
        client: ClaudeClient instance
        filtered_images: List of pre-filtered images
        dom_summary: Summary of DOM for context
        source_url: Source page URL
        page_title: Source page title
        base_path: Base directory for image files
        batch_size: Number of images per batch
        
    Returns:
        ImageDescriptionsOutput
    """
    from processors.image_filter import ImageFilter
    
    # Create batches
    filter = ImageFilter()
    batches = filter.batch_images(filtered_images, batch_size)
    
    # Classify
    classifier = ImageClassifier(client, base_path)
    return classifier.classify_all(
        image_batches=batches,
        dom_summary=dom_summary,
        source_url=source_url,
        page_title=page_title
    )

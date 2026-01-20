"""
Anthropic API Client Wrapper

Handles API calls with retry logic, rate limiting, and error handling.
"""

import time
import json
import base64
import re
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path

import anthropic

from config import (
    DEFAULT_MODEL,
    API_DELAY_SECONDS,
    MAX_RETRIES,
    RETRY_DELAY_SECONDS,
    SAFE_INPUT_TOKENS,
)


class ClaudeClient:
    """Wrapper for Anthropic Claude API"""
    
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        api_delay: float = API_DELAY_SECONDS,
        max_retries: int = MAX_RETRIES
    ):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.api_delay = api_delay
        self.max_retries = max_retries
        self.last_call_time = 0
    
    def _wait_for_rate_limit(self) -> None:
        """Wait if needed to respect rate limits"""
        elapsed = time.time() - self.last_call_time
        if elapsed < self.api_delay:
            time.sleep(self.api_delay - elapsed)
    
    def _encode_image(self, image_path: str) -> Tuple[str, str]:
        """
        Encode an image file to base64.
        
        Returns:
            Tuple of (base64_data, media_type)
        """
        path = Path(image_path)
        
        # Determine media type
        suffix = path.suffix.lower()
        media_types = {
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.gif': 'image/gif',
            '.webp': 'image/webp',
            '.svg': 'image/svg+xml',
        }
        media_type = media_types.get(suffix, 'image/png')
        
        # For non-SVG images, check if resizing is needed
        if media_type != 'image/svg+xml':
            try:
                from PIL import Image
                import io
                
                with Image.open(path) as img:
                    width, height = img.size
                    max_dimension = 7500  # Stay under 8000 limit
                    
                    # Check if resizing is needed
                    if width > max_dimension or height > max_dimension:
                        # Calculate new dimensions maintaining aspect ratio
                        if width > height:
                            new_width = max_dimension
                            new_height = int(height * (max_dimension / width))
                        else:
                            new_height = max_dimension
                            new_width = int(width * (max_dimension / height))
                        
                        print(f"    Resizing image from {width}x{height} to {new_width}x{new_height}")
                        
                        # Resize image
                        img_resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                        
                        # Convert to bytes
                        buffer = io.BytesIO()
                        # Save in original format
                        if suffix in ['.jpg', '.jpeg']:
                            img_resized.save(buffer, format='JPEG', quality=85)
                        elif suffix == '.png':
                            img_resized.save(buffer, format='PNG')
                        elif suffix == '.webp':
                            img_resized.save(buffer, format='WEBP', quality=85)
                        else:
                            img_resized.save(buffer, format='PNG')
                        
                        buffer.seek(0)
                        data = base64.standard_b64encode(buffer.read()).decode('utf-8')
                        return data, media_type
                        
            except ImportError:
                print("    Warning: PIL not installed, cannot resize large images")
            except Exception as e:
                print(f"    Warning: Failed to check/resize image: {e}")
        
        # Read and encode (original size)
        with open(path, 'rb') as f:
            data = base64.standard_b64encode(f.read()).decode('utf-8')
        
        return data, media_type
    
    def _build_image_content(
        self,
        image_paths: List[str],
        base_path: str = ""
    ) -> List[Dict[str, Any]]:
        """
        Build content array with images for API call.
        
        Args:
            image_paths: List of image file paths
            base_path: Base directory for relative paths
            
        Returns:
            List of content blocks for API
        """
        content = []
        
        for img_path in image_paths:
            # Handle relative paths
            if base_path and not Path(img_path).is_absolute():
                full_path = Path(base_path) / img_path
            else:
                full_path = Path(img_path)
            
            if not full_path.exists():
                print(f"Warning: Image not found: {full_path}")
                continue
            
            try:
                data, media_type = self._encode_image(str(full_path))
                
                # For SVG, we may need to handle differently
                if media_type == 'image/svg+xml':
                    # Claude can handle SVG as text or image
                    # Using image format for consistency
                    content.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": data
                        }
                    })
                else:
                    content.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": data
                        }
                    })
            except Exception as e:
                print(f"Warning: Failed to encode image {full_path}: {e}")
                continue
        
        return content
    
    def call_with_images(
        self,
        system_prompt: str,
        user_prompt: str,
        image_paths: List[str],
        base_path: str = "",
        max_tokens: int = 4096
    ) -> str:
        """
        Make an API call with images.
        
        Args:
            system_prompt: System message
            user_prompt: User message
            image_paths: List of image file paths
            base_path: Base directory for relative paths
            max_tokens: Maximum tokens in response
            
        Returns:
            Response text from Claude
        """
        self._wait_for_rate_limit()
        
        # Build content with images first, then text
        content = self._build_image_content(image_paths, base_path)
        content.append({"type": "text", "text": user_prompt})
        
        for attempt in range(self.max_retries):
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    system=system_prompt,
                    messages=[
                        {"role": "user", "content": content}
                    ]
                )
                
                self.last_call_time = time.time()
                return response.content[0].text
                
            except anthropic.RateLimitError as e:
                print(f"Rate limit hit, waiting {RETRY_DELAY_SECONDS}s (attempt {attempt + 1}/{self.max_retries})")
                time.sleep(RETRY_DELAY_SECONDS)
                
            except anthropic.APIError as e:
                print(f"API error: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(RETRY_DELAY_SECONDS)
                else:
                    raise
        
        raise Exception(f"Failed after {self.max_retries} attempts")
    
    def call_with_image(
        self,
        system_prompt: str,
        user_prompt: str,
        image_path: str,
        max_tokens: int = 4096
    ) -> str:
        """
        Make an API call with a single image.
        
        Args:
            system_prompt: System message
            user_prompt: User message
            image_path: Path to single image file
            max_tokens: Maximum tokens in response
            
        Returns:
            Response text from Claude
        """
        return self.call_with_images(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            image_paths=[image_path],
            base_path="",
            max_tokens=max_tokens
        )
    
    def call_text_only(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 8192
    ) -> str:
        """
        Make a text-only API call (no images).
        
        Args:
            system_prompt: System message
            user_prompt: User message
            max_tokens: Maximum tokens in response
            
        Returns:
            Response text from Claude
        """
        self._wait_for_rate_limit()
        
        for attempt in range(self.max_retries):
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    system=system_prompt,
                    messages=[
                        {"role": "user", "content": user_prompt}
                    ]
                )
                
                self.last_call_time = time.time()
                return response.content[0].text
                
            except anthropic.RateLimitError as e:
                print(f"Rate limit hit, waiting {RETRY_DELAY_SECONDS}s (attempt {attempt + 1}/{self.max_retries})")
                time.sleep(RETRY_DELAY_SECONDS)
                
            except anthropic.APIError as e:
                print(f"API error: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(RETRY_DELAY_SECONDS)
                else:
                    raise
        
        raise Exception(f"Failed after {self.max_retries} attempts")
    
    def parse_json_response(self, response: str) -> Dict[str, Any]:
        """
        Parse JSON from Claude's response.
        
        Handles responses that may include markdown code blocks,
        truncated output, or common JSON formatting issues.
        
        Args:
            response: Raw response text from Claude
            
        Returns:
            Parsed JSON dictionary
        """
        # Try to find JSON in code blocks first
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', response)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Try to find raw JSON object
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                json_str = json_match.group(0)
            else:
                raise ValueError(f"No JSON found in response: {response[:500]}...")
        
        json_str = json_str.strip()
        
        # Attempt 1: Direct parse
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            pass
        
        # Attempt 2: Fix common issues
        try:
            fixed_json = self._repair_json(json_str)
            return json.loads(fixed_json)
        except json.JSONDecodeError as e:
            pass
        
        # Attempt 3: Try to find the last complete object
        try:
            # Find where the JSON breaks and truncate there
            truncated = self._truncate_to_valid_json(json_str)
            if truncated:
                return json.loads(truncated)
        except json.JSONDecodeError:
            pass
        
        raise ValueError(f"Failed to parse JSON after repair attempts.\nError location: char ~{len(json_str)}\nContent tail: ...{json_str[-200:] if len(json_str) > 200 else json_str}")
    
    def _repair_json(self, json_str: str) -> str:
        """Attempt to repair common JSON issues"""
        # Remove trailing commas before closing brackets
        json_str = re.sub(r',\s*}', '}', json_str)
        json_str = re.sub(r',\s*]', ']', json_str)
        
        # Fix unescaped newlines in strings (common issue)
        # This is tricky - only do basic fixes
        
        # Remove any trailing incomplete content after last complete structure
        # Find the last proper closing of the main object
        
        return json_str
    
    def _truncate_to_valid_json(self, json_str: str) -> Optional[str]:
        """
        Try to truncate JSON to last valid point.
        Useful when response was cut off.
        """
        # Count brackets to find where we can safely close
        depth_brace = 0
        depth_bracket = 0
        in_string = False
        escape_next = False
        last_valid_pos = 0
        
        for i, char in enumerate(json_str):
            if escape_next:
                escape_next = False
                continue
            
            if char == '\\':
                escape_next = True
                continue
            
            if char == '"' and not escape_next:
                in_string = not in_string
                continue
            
            if in_string:
                continue
            
            if char == '{':
                depth_brace += 1
            elif char == '}':
                depth_brace -= 1
                if depth_brace == 0 and depth_bracket == 0:
                    last_valid_pos = i + 1
            elif char == '[':
                depth_bracket += 1
            elif char == ']':
                depth_bracket -= 1
        
        if last_valid_pos > 0:
            return json_str[:last_valid_pos]
        
        # Try to close unclosed structures
        if depth_brace > 0 or depth_bracket > 0:
            # Find a reasonable truncation point
            # Look for last complete array item or object
            truncated = json_str
            
            # Remove any trailing incomplete content
            truncated = re.sub(r',\s*"[^"]*$', '', truncated)  # Incomplete key
            truncated = re.sub(r',\s*\{[^}]*$', '', truncated)  # Incomplete object
            truncated = re.sub(r',\s*\[[^\]]*$', '', truncated)  # Incomplete array
            
            # Close remaining structures
            truncated += ']' * depth_bracket
            truncated += '}' * depth_brace
            
            return truncated
        
        return None


def estimate_tokens(text: str) -> int:
    """
    Rough estimate of token count.
    
    Claude typically uses ~4 characters per token for English text.
    This is a rough estimate - actual count may vary.
    """
    return len(text) // 4


def estimate_image_tokens(file_size_bytes: int) -> int:
    """
    Estimate tokens for an image.
    
    Base64 encoding increases size by ~33%.
    Claude charges roughly 1 token per 750 bytes of base64 data.
    """
    base64_size = file_size_bytes * 1.33
    return int(base64_size / 750)


if __name__ == "__main__":
    # Test token estimation
    print("Token estimation test:")
    print(f"  1000 chars ≈ {estimate_tokens('x' * 1000)} tokens")
    print(f"  50KB image ≈ {estimate_image_tokens(50000)} tokens")

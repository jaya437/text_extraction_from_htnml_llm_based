"""
File Utilities

Helper functions for file I/O operations.
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional, Union

from pydantic import BaseModel


def load_json(file_path: Union[str, Path]) -> Dict[str, Any]:
    """Load JSON file and return dictionary"""
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(
    data: Union[Dict[str, Any], BaseModel],
    file_path: Union[str, Path],
    indent: int = 2
) -> None:
    """
    Save data to JSON file.
    
    Args:
        data: Dictionary or Pydantic model to save
        file_path: Output file path
        indent: JSON indentation level
    """
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    if isinstance(data, BaseModel):
        json_str = data.model_dump_json(indent=indent)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(json_str)
    else:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)


def load_text(file_path: Union[str, Path]) -> str:
    """Load text file and return contents"""
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()


def save_text(content: str, file_path: Union[str, Path]) -> None:
    """Save text content to file"""
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)


def ensure_dir(dir_path: Union[str, Path]) -> Path:
    """Ensure directory exists, create if not"""
    dir_path = Path(dir_path)
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path


def get_file_size(file_path: Union[str, Path]) -> int:
    """Get file size in bytes"""
    return Path(file_path).stat().st_size


def file_exists(file_path: Union[str, Path]) -> bool:
    """Check if file exists"""
    return Path(file_path).exists()


def resolve_path(
    file_path: str,
    base_path: Optional[str] = None
) -> Path:
    """
    Resolve a potentially relative path.
    
    Args:
        file_path: File path (may be relative)
        base_path: Base directory for relative paths
        
    Returns:
        Resolved Path object
    """
    path = Path(file_path.replace("\\", "/"))
    
    if path.is_absolute():
        return path
    
    if base_path:
        return Path(base_path) / path
    
    return path


def normalize_path(path: str) -> str:
    """Normalize path separators to forward slashes"""
    return path.replace("\\", "/")

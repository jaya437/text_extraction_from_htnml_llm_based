"""Utils package"""

from .file_utils import (
    load_json,
    save_json,
    load_text,
    save_text,
    ensure_dir,
    get_file_size,
    file_exists,
    resolve_path,
    normalize_path,
)
from .segment_detector import (
    get_page_slug,
    get_domain,
    detect_data_segment,
)

__all__ = [
    "load_json",
    "save_json",
    "load_text",
    "save_text",
    "ensure_dir",
    "get_file_size",
    "file_exists",
    "resolve_path",
    "normalize_path",
    "get_page_slug",
    "get_domain",
    "detect_data_segment",
]

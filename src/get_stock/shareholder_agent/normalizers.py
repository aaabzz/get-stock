import re
import unicodedata


def normalize_shareholder_name(value: str) -> str:
    """Apply conservative normalization without fuzzy-merging legal entities."""
    normalized = unicodedata.normalize("NFKC", value).strip()
    return re.sub(r"\s+", " ", normalized)

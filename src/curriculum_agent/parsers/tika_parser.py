from __future__ import annotations

from unstructured.partition.auto import partition


def parse_file(file_path: str) -> str:
    """Extract plain text from PDF/DOCX/XLSX via Unstructured."""
    elements = partition(filename=file_path)
    return "\n".join(str(el) for el in elements)

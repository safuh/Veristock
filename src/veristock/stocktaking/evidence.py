"""Private local storage primitives for stocktake image evidence."""

import hashlib
import pathlib
import uuid


ALLOWED_IMAGE_TYPES = {
    "image/jpeg": (".jpg", b"\xff\xd8\xff"),
    "image/png": (".png", b"\x89PNG\r\n\x1a\n"),
    "image/webp": (".webp", b"RIFF"),
}


class EvidenceValidationError(ValueError):
    """Raised when an uploaded evidence image is invalid."""


def inspect_image(content: bytes, declared_type: str) -> tuple[str, str]:
    """Validate a supported image signature and return its canonical type and suffix."""
    if not content:
        raise EvidenceValidationError("Evidence image is empty")
    if declared_type not in ALLOWED_IMAGE_TYPES:
        raise EvidenceValidationError("Only JPEG, PNG and WebP evidence images are accepted")
    suffix, signature = ALLOWED_IMAGE_TYPES[declared_type]
    if not content.startswith(signature):
        raise EvidenceValidationError("Image content does not match the declared media type")
    if declared_type == "image/webp" and content[8:12] != b"WEBP":
        raise EvidenceValidationError("Invalid WebP image signature")
    return declared_type, suffix


def evidence_path(root: pathlib.Path, storage_key: str) -> pathlib.Path:
    """Resolve a generated storage key without permitting path traversal."""
    candidate = (root / storage_key).resolve()
    resolved_root = root.resolve()
    if candidate.parent != resolved_root or pathlib.Path(storage_key).name != storage_key:
        raise EvidenceValidationError("Invalid evidence storage key")
    return candidate


def persist_image(root: pathlib.Path, content: bytes, suffix: str) -> tuple[str, str]:
    """Persist bytes under a random name and return storage key and SHA-256 digest."""
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    storage_key = f"{uuid.uuid4().hex}{suffix}"
    destination = evidence_path(root, storage_key)
    destination.write_bytes(content)
    destination.chmod(0o600)
    return storage_key, hashlib.sha256(content).hexdigest()
# foundry: kind=service domain=client-intelligence-platform touches=integration
"""Document library connector — a tenant's documents as a first-class source.

Contract: docs/DOCUMENT-SOURCE-CONTRACT.md (CIP-SPEC-014).
"""
from .connector import (
    CONNECTOR_ID,
    DEFAULT_SOURCE_KIND,
    ClassifiedFile,
    DocumentLibrary,
    DocumentLibraryConnector,
    ObjectStore,
    StoredObject,
    sha256_of,
)
from .mapper import DocumentLibraryMapper

__all__ = [
    "CONNECTOR_ID",
    "DEFAULT_SOURCE_KIND",
    "ClassifiedFile",
    "DocumentLibrary",
    "DocumentLibraryConnector",
    "DocumentLibraryMapper",
    "ObjectStore",
    "StoredObject",
    "sha256_of",
]

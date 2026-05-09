# foundry: kind=test domain=client-intelligence-platform
"""Shared test-harness helpers for foundry-cip.

Modules here are consumed by ``conftest.py`` files across the test tree
to avoid duplicating provisioning / fixture-setup logic. Add a new helper
module rather than re-deriving the same pattern in a third conftest.
"""

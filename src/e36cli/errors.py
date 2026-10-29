"""Root of the e36cli exception taxonomy (STANDARDS.md STD-03).

Every error the package raises on purpose derives from `E36Error`; each layer
defines its own subclasses next to the code that raises them. How each class
is *treated* (retry, reconnect, fatal) is decided in one place: `policy.py`.
Anything that is not an `E36Error` reaching the CLI is a bug.
"""

from __future__ import annotations


class E36Error(Exception):
    """Base for every deliberate e36cli error."""

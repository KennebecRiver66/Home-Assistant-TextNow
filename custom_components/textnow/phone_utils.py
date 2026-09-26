"""Phone number utilities for TextNow integration."""
from __future__ import annotations

import re
from typing import Any

_phone_pattern = re.compile(r'[^\d]')


def format_phone_number(phone: str) -> str:
    """Format phone number to +1XXXXXXXXXX format.
    
    Args:
        phone: Phone number input (can contain any characters)
        
    Returns:
        Formatted phone number with +1 prefix
        
    Raises:
        ValueError: If phone number is not 10 digits after cleaning
    """
    # Remove all non-digit characters
    digits = _phone_pattern.sub('', phone)
    
    # Remove leading 1 if present (US country code)
    if digits.startswith('1') and len(digits) == 11:
        digits = digits[1:]
    
    # Validate it's exactly 10 digits
    if len(digits) != 10:
        raise ValueError(f"Phone number must be exactly 10 digits, got {len(digits)} digits")
    
    # Format as +1XXXXXXXXXX
    return f"+1{digits}"


def readable_phone_number(phone: str) -> str:
    """Return a number the way a person writes it: (555) 123-4567.

    Storage keeps +1XXXXXXXXXX because that is what TextNow expects, which is
    not what anyone wants to read in a list of their own contacts.
    """
    digits = _phone_pattern.sub("", phone or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return phone or ""
    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"


def validate_phone_number(phone: str) -> bool:
    """Validate phone number format.
    
    Args:
        phone: Phone number to validate
        
    Returns:
        True if valid, False otherwise
    """
    try:
        format_phone_number(phone)
        return True
    except ValueError:
        return False


"""
Built-in validators for slot data in conversation flows.

Provides validation and normalization for common hotel data types:
- Phone numbers (E.164 format)
- Dates (ISO format with future date checks)
- Email addresses
- Numbers (with min/max limits)
- Cross-field validation (e.g., check-out after check-in)
"""

import re
from datetime import datetime, date
from typing import Any, Optional, Tuple
from dataclasses import dataclass


@dataclass
class ValidationResult:
    """Result of a validation check."""
    is_valid: bool
    normalized_value: Any
    error_message: Optional[str] = None
    suggestions: Optional[list[str]] = None


class SlotValidators:
    """Collection of built-in validators for common hotel data types."""
    
    @staticmethod
    def validate_phone(value: str, require_country_code: bool = False) -> ValidationResult:
        """
        Validate and normalize phone number to E.164 format.
        
        Accepts various formats:
        - (555) 123-4567
        - 555-123-4567
        - +1 555 123 4567
        - 5551234567
        """
        if not value:
            return ValidationResult(False, value, "Please provide a phone number.")
        
        digits = re.sub(r'\D', '', value)
        
        if len(digits) == 10:
            normalized = f"+1{digits}"
            return ValidationResult(True, normalized)
        elif len(digits) == 11 and digits[0] == '1':
            normalized = f"+{digits}"
            return ValidationResult(True, normalized)
        elif len(digits) >= 10 and len(digits) <= 15:
            normalized = f"+{digits}"
            return ValidationResult(True, normalized)
        else:
            return ValidationResult(
                False, 
                value, 
                "Please provide a valid phone number with area code.",
                ["A US number should have 10 digits like 555-123-4567"]
            )
    
    @staticmethod
    def validate_email(value: str) -> ValidationResult:
        """Validate email address format."""
        if not value:
            return ValidationResult(False, value, "Please provide an email address.")
        
        email = value.strip().lower()
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        
        if re.match(pattern, email):
            return ValidationResult(True, email)
        else:
            return ValidationResult(
                False, 
                value, 
                "That doesn't look like a valid email address.",
                ["Please provide an email like name@example.com"]
            )
    
    @staticmethod
    def validate_date(
        value: str, 
        require_future: bool = True,
        min_days_ahead: int = 0,
        max_days_ahead: int = 365
    ) -> ValidationResult:
        """
        Validate and normalize date to ISO format (YYYY-MM-DD).
        
        Handles various formats and relative dates:
        - December 15, 2024
        - 12/15/2024
        - 2024-12-15
        - tomorrow
        - next week
        """
        if not value:
            return ValidationResult(False, value, "Please provide a date.")
        
        value_lower = value.lower().strip()
        today = date.today()
        
        if value_lower in ["today", "tonight"]:
            parsed_date = today
        elif value_lower == "tomorrow":
            from datetime import timedelta
            parsed_date = today + timedelta(days=1)
        else:
            date_formats = [
                "%Y-%m-%d",
                "%m/%d/%Y",
                "%m-%d-%Y",
                "%d/%m/%Y",
                "%B %d, %Y",
                "%B %d %Y",
                "%b %d, %Y",
                "%b %d %Y",
                "%d %B %Y",
                "%d %b %Y",
            ]
            
            parsed_date = None
            for fmt in date_formats:
                try:
                    parsed_date = datetime.strptime(value, fmt).date()
                    break
                except ValueError:
                    continue
            
            if not parsed_date:
                try:
                    parts = re.split(r'[/\-\s]+', value_lower)
                    month_names = {
                        'january': 1, 'jan': 1, 'february': 2, 'feb': 2,
                        'march': 3, 'mar': 3, 'april': 4, 'apr': 4,
                        'may': 5, 'june': 6, 'jun': 6, 'july': 7, 'jul': 7,
                        'august': 8, 'aug': 8, 'september': 9, 'sep': 9, 'sept': 9,
                        'october': 10, 'oct': 10, 'november': 11, 'nov': 11,
                        'december': 12, 'dec': 12
                    }
                    
                    month = None
                    day = None
                    year = today.year
                    
                    for part in parts:
                        part_clean = part.rstrip(',').rstrip('st').rstrip('nd').rstrip('rd').rstrip('th')
                        if part_clean in month_names:
                            month = month_names[part_clean]
                        elif part_clean.isdigit():
                            num = int(part_clean)
                            if num > 31:
                                year = num
                            elif day is None:
                                day = num
                    
                    if month and day:
                        parsed_date = date(year, month, day)
                        if parsed_date < today:
                            parsed_date = date(year + 1, month, day)
                except:
                    pass
            
            if not parsed_date:
                return ValidationResult(
                    False, 
                    value, 
                    "I couldn't understand that date format.",
                    ["Please say the date like December 15th or 12/15/2024"]
                )
        
        if require_future and parsed_date < today:
            return ValidationResult(
                False, 
                value, 
                "The date needs to be in the future.",
                ["Please provide a date that hasn't passed yet"]
            )
        
        from datetime import timedelta
        min_date = today + timedelta(days=min_days_ahead)
        max_date = today + timedelta(days=max_days_ahead)
        
        if parsed_date < min_date:
            return ValidationResult(
                False, 
                value, 
                f"The date must be at least {min_days_ahead} days from now.",
                [f"Please choose a date on or after {min_date.strftime('%B %d, %Y')}"]
            )
        
        if parsed_date > max_date:
            return ValidationResult(
                False, 
                value, 
                f"We can only book up to {max_days_ahead} days in advance.",
                [f"Please choose a date before {max_date.strftime('%B %d, %Y')}"]
            )
        
        return ValidationResult(True, parsed_date.isoformat())
    
    @staticmethod
    def validate_number(
        value: Any, 
        min_value: Optional[int] = None, 
        max_value: Optional[int] = None,
        allow_decimal: bool = False
    ) -> ValidationResult:
        """Validate numeric input with optional range limits."""
        if value is None or value == "":
            return ValidationResult(False, value, "Please provide a number.")
        
        try:
            if allow_decimal:
                num = float(str(value))
            else:
                text_value = str(value).lower().strip()
                word_to_num = {
                    'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
                    'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10
                }
                if text_value in word_to_num:
                    num = word_to_num[text_value]
                else:
                    num = int(float(value))
        except (ValueError, TypeError):
            return ValidationResult(
                False, 
                value, 
                "Please provide a valid number.",
                ["Say a number like 2 or two"]
            )
        
        if min_value is not None and num < min_value:
            return ValidationResult(
                False, 
                value, 
                f"The number must be at least {min_value}.",
                [f"Please provide a number of {min_value} or more"]
            )
        
        if max_value is not None and num > max_value:
            return ValidationResult(
                False, 
                value, 
                f"The number cannot exceed {max_value}.",
                [f"Please provide a number of {max_value} or less"]
            )
        
        return ValidationResult(True, num)
    
    @staticmethod
    def validate_text(
        value: str, 
        min_length: int = 1, 
        max_length: int = 500,
        pattern: Optional[str] = None
    ) -> ValidationResult:
        """Validate text input with optional constraints."""
        if not value or not value.strip():
            return ValidationResult(False, value, "Please provide a response.")
        
        text = value.strip()
        
        if len(text) < min_length:
            return ValidationResult(
                False, 
                value, 
                f"Your response is too short. Please provide at least {min_length} characters."
            )
        
        if len(text) > max_length:
            return ValidationResult(
                False, 
                value, 
                f"Your response is too long. Please keep it under {max_length} characters."
            )
        
        if pattern:
            if not re.match(pattern, text):
                return ValidationResult(False, value, "Your response doesn't match the expected format.")
        
        return ValidationResult(True, text)
    
    @staticmethod
    def validate_time(value: str) -> ValidationResult:
        """Validate and normalize time input to 24-hour format (HH:MM)."""
        if not value:
            return ValidationResult(False, value, "Please provide a time.")
        
        value_lower = value.lower().strip()
        
        time_patterns = [
            (r'^(\d{1,2}):(\d{2})\s*(am|pm)?$', True),
            (r'^(\d{1,2})\s*(am|pm)$', False),
            (r'^(\d{1,2}):(\d{2})$', True),
        ]
        
        for pattern, has_minutes in time_patterns:
            match = re.match(pattern, value_lower)
            if match:
                groups = match.groups()
                hour = int(groups[0])
                minutes = int(groups[1]) if has_minutes else 0
                am_pm = groups[-1] if groups[-1] in ['am', 'pm'] else None
                
                if am_pm == 'pm' and hour < 12:
                    hour += 12
                elif am_pm == 'am' and hour == 12:
                    hour = 0
                
                if 0 <= hour <= 23 and 0 <= minutes <= 59:
                    normalized = f"{hour:02d}:{minutes:02d}"
                    return ValidationResult(True, normalized)
        
        return ValidationResult(
            False, 
            value, 
            "I couldn't understand that time.",
            ["Please say the time like 3 PM or 15:00"]
        )
    
    @staticmethod
    def validate_choice(value: str, choices: list[str]) -> ValidationResult:
        """Validate that a value matches one of the allowed choices."""
        if not value:
            return ValidationResult(False, value, "Please make a selection.")
        
        value_lower = value.lower().strip()
        
        for choice in choices:
            if choice.lower() == value_lower:
                return ValidationResult(True, choice)
        
        for choice in choices:
            if value_lower in choice.lower() or choice.lower() in value_lower:
                return ValidationResult(True, choice)
        
        choice_list = ", ".join(choices)
        return ValidationResult(
            False, 
            value, 
            f"Please choose from: {choice_list}",
            [f"Your options are: {choice_list}"]
        )


class CrossFieldValidators:
    """Validators that check relationships between multiple fields."""
    
    @staticmethod
    def validate_date_range(
        check_in: str, 
        check_out: str,
        min_nights: int = 1,
        max_nights: int = 30
    ) -> ValidationResult:
        """Validate that check-out is after check-in with reasonable stay length."""
        try:
            check_in_date = date.fromisoformat(check_in)
            check_out_date = date.fromisoformat(check_out)
        except (ValueError, TypeError):
            return ValidationResult(
                False, 
                None, 
                "Please provide valid dates for check-in and check-out."
            )
        
        nights = (check_out_date - check_in_date).days
        
        if nights < min_nights:
            return ValidationResult(
                False, 
                None, 
                f"Check-out must be at least {min_nights} night(s) after check-in.",
                ["Your check-out date should be after your check-in date"]
            )
        
        if nights > max_nights:
            return ValidationResult(
                False, 
                None, 
                f"Reservations cannot exceed {max_nights} nights.",
                [f"For stays longer than {max_nights} nights, please contact the front desk"]
            )
        
        return ValidationResult(True, {"check_in": check_in, "check_out": check_out, "nights": nights})
    
    @staticmethod
    def validate_guest_count_for_room(
        guest_count: int,
        room_type: str
    ) -> ValidationResult:
        """Validate guest count is appropriate for room type."""
        room_capacities = {
            "standard": 2,
            "deluxe": 3,
            "suite": 4,
            "family": 6,
            "presidential": 6,
        }
        
        room_lower = room_type.lower()
        max_guests = room_capacities.get(room_lower, 4)
        
        if guest_count > max_guests:
            return ValidationResult(
                False, 
                None, 
                f"A {room_type} room can accommodate up to {max_guests} guests.",
                ["You may need to book multiple rooms or upgrade to a larger room type"]
            )
        
        return ValidationResult(True, {"guest_count": guest_count, "room_type": room_type})


def validate_slot(
    slot_type: str, 
    value: Any, 
    validation_config: Optional[dict] = None
) -> ValidationResult:
    """
    Main validation entry point. Validates a value based on its slot type.
    
    Args:
        slot_type: Type of slot (text, phone, email, date, number, time, choice)
        value: The value to validate
        validation_config: Optional config with type-specific settings
    
    Returns:
        ValidationResult with is_valid, normalized_value, and error_message
    """
    config = validation_config or {}
    
    if slot_type == "phone":
        return SlotValidators.validate_phone(value)
    
    elif slot_type == "email":
        return SlotValidators.validate_email(value)
    
    elif slot_type == "date":
        return SlotValidators.validate_date(
            value,
            require_future=config.get("requireFuture", True),
            min_days_ahead=config.get("minDaysAhead", 0),
            max_days_ahead=config.get("maxDaysAhead", 365)
        )
    
    elif slot_type == "number":
        return SlotValidators.validate_number(
            value,
            min_value=config.get("min"),
            max_value=config.get("max"),
            allow_decimal=config.get("allowDecimal", False)
        )
    
    elif slot_type == "time":
        return SlotValidators.validate_time(value)
    
    elif slot_type == "choice":
        choices = config.get("choices", [])
        return SlotValidators.validate_choice(value, choices)
    
    elif slot_type == "text":
        return SlotValidators.validate_text(
            value,
            min_length=config.get("minLength", 1),
            max_length=config.get("maxLength", 500),
            pattern=config.get("pattern")
        )
    
    else:
        return ValidationResult(True, value)

"""User-facing errors.

Curator raises UserError for problems the person using it can understand and act on
("Choose a valid Mage default"). Only UserError messages are shown as written. Any
other exception, including a ValueError from the standard library such as a JSON or
base64 decoding error, is logged and replaced with a generic message, so internal
details never reach the browser and real bugs are not mistaken for validation errors.

UserError subclasses ValueError, so existing `except ValueError` handlers still catch it.
"""


class UserError(ValueError):
    pass


def user_message(error, fallback, limit=None):
    """The error's own text if it was written for users, otherwise the fallback."""
    message = str(error) if isinstance(error, UserError) else fallback
    return message[:limit] if limit else message

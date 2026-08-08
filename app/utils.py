import secrets
import string

BASE62_ALPHABET = string.ascii_letters + string.digits

def generate_short_code(length: int = 6) -> str:
    """
    Generate a cryptographically secure pseudorandom short code using Base62 characters.
    
    With length=6, there are 62^6 = 56,800,235,584 (~56.8 billion) possible unique codes.
    """
    return "".join(secrets.choice(BASE62_ALPHABET) for _ in range(length))

"""Portable Windows output filename validation, shared by UI and worker."""
import re

# Windows filename components allow 255 UTF-16 units. Reserve the suffix used
# by the worker so a valid final name also has a valid incomplete name.
EXPORT_ID_LENGTH = 12
MAX_OUTPUT_NAME_UNITS = 255 - len('.incomplete-') - EXPORT_ID_LENGTH


def validate_output_name(name):
    try:
        units = len(name.encode('utf-16-le')) // 2
    except UnicodeEncodeError:
        raise ValueError('The filename contains an unsupported character.') from None
    if units > MAX_OUTPUT_NAME_UNITS:
        raise ValueError('The filename is too long for a temporary export. Choose a shorter filename.')
    if (not name or re.search(r'[<>:"/\\|?*\x00-\x1f]', name) or
            name.endswith((' ', '.')) or name in ('.','..')):
        raise ValueError('Enter a filename without folders or special characters.')
    stem = name.split('.')[0].rstrip(' ').upper()
    if (stem in {'CON','PRN','AUX','NUL','CONIN$','CONOUT$'} or
            re.fullmatch(r'(COM|LPT)[1-9¹²³]',stem)):
        raise ValueError('This filename is reserved by Windows. Choose another name.')
    if not name.lower().endswith('.ova'):
        raise ValueError('The filename must end with .ova.')
    return name

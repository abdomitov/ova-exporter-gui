"""Portable Windows output filename validation, shared by UI and worker."""
import re


def validate_output_name(name):
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

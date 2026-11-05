"""Extract useful OVF Tool errors without displaying XML wrapper tags."""
import html
import re


def machine_error_messages(lines):
    text = '\n'.join(re.sub(r'^\+\s?', '', line) for line in lines)
    messages = []
    for tag in ('LocalizedMsg', 'Message', 'Msg', 'Description'):
        pattern = rf'<(?:\w+:)?{tag}(?:\s[^>]*)?>(.*?)</(?:\w+:)?{tag}>'
        for match in re.findall(pattern, text, re.I | re.S):
            value = html.unescape(re.sub(r'<[^>]*>', '', match)).strip()
            value = re.sub(r'\s+', ' ', value)
            if value and value not in messages:
                messages.append(value)
        if messages:
            break
    if not messages:
        for line in text.splitlines():
            if re.search(r'\b(error|failed|cannot|unable|unsupported|denied)\b', line, re.I) and '<' not in line:
                if line.strip().upper() not in ('ERROR', 'ERRORS', 'RESULT', 'FAILED'):
                    messages.append(line.strip())
    return messages

"""Raise the app version everywhere it is stored, or check that the copies agree.

    python tools/bump_version.py 2.5.0     # update src/metadata.py and packaging/windows.iss
    python tools/bump_version.py --check   # exit 1 if the copies differ

Merging the bump to main is what releases it: the CI/CD workflow notices a new version.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
METADATA = ROOT / 'src' / 'metadata.py'
INSTALLER = ROOT / 'packaging' / 'windows.iss'
METADATA_PATTERN = re.compile(r"^VERSION = '(\d{1,5}\.\d{1,5}\.\d{1,5})'$", re.M)
INSTALLER_PATTERN = re.compile(r'^(\s*#define AppVersion ")(\d{1,5}\.\d{1,5}\.\d{1,5})(")$', re.M)


def parts(text):
    return tuple(int(piece) for piece in text.split('.'))


def current_versions():
    app = METADATA_PATTERN.search(METADATA.read_text(encoding='utf-8'))
    installer = INSTALLER_PATTERN.search(INSTALLER.read_text(encoding='utf-8'))
    if not app or not installer:
        raise ValueError('Could not find the version lines.')
    return app.group(1), installer.group(2)


def check():
    app, installer = current_versions()
    if app != installer:
        raise ValueError(f'src/metadata.py says {app} but packaging/windows.iss says {installer}.')
    return app


def bump(new):
    if not re.fullmatch(r'\d{1,5}\.\d{1,5}\.\d{1,5}', new):
        raise ValueError('Use three numbers, for example 2.5.0.')
    old = check()
    if parts(new) <= parts(old):
        raise ValueError(f'{new} is not higher than the current {old}.')
    METADATA.write_text(METADATA_PATTERN.sub(f"VERSION = '{new}'", METADATA.read_text(encoding='utf-8')), encoding='utf-8')
    INSTALLER.write_text(INSTALLER_PATTERN.sub(lambda match: match.group(1) + new + match.group(3),
                                               INSTALLER.read_text(encoding='utf-8')), encoding='utf-8')
    return old, new


def main(argv):
    try:
        if argv == ['--check']:
            print('Version', check(), 'is consistent.')
        elif len(argv) == 1 and not argv[0].startswith('-'):
            old, new = bump(argv[0])
            print(f'Raised {old} -> {new}. Commit, open a pull request and merge it to release.')
        else:
            print(__doc__)
            return 2
    except ValueError as error:
        print('Error:', error)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))

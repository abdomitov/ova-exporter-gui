"""Collect license texts for the exact Python/Tcl/Tk/OpenSSL build being bundled."""
from pathlib import Path
import shutil
import re
import ssl
import sys
import tkinter
import urllib.request
import urllib.error


def license_urls(tcl_version, tk_version, openssl_version):
    for version in (tcl_version, tk_version):
        if not re.fullmatch(r'\d+\.\d+(?:\.\d+)?', version):
            raise ValueError('A stable Tcl/Tk runtime version is required for license collection.')
    if not re.fullmatch(r'\d+\.\d+\.\d+[a-z]?', openssl_version):
        raise ValueError('Unsupported OpenSSL license version.')
    return {
        'TCL.txt':f'https://raw.githubusercontent.com/tcltk/tcl/core-{tcl_version.replace(".", "-")}/license.terms',
        'TK.txt':f'https://raw.githubusercontent.com/tcltk/tk/core-{tk_version.replace(".", "-")}/license.terms',
        'OPENSSL.txt':f'https://raw.githubusercontent.com/openssl/openssl/openssl-{openssl_version}/LICENSE.txt',
        'OPENSSL-NOTICE.txt':f'https://raw.githubusercontent.com/openssl/openssl/openssl-{openssl_version}/NOTICE.md',
    }


def collect(destination):
    target=Path(destination)
    target.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(Path(sys.base_prefix)/'LICENSE.txt',target/'PYTHON.txt')
    interpreter=tkinter.Tcl()
    tcl_version=interpreter.eval('info patchlevel')
    try:
        tk_version=interpreter.eval('package require Tk')
    finally:
        if interpreter.eval('info commands wm'):
            interpreter.eval('wm withdraw .')
            interpreter.eval('destroy .')
    openssl_version=ssl.OPENSSL_VERSION.split()[1]
    urls=license_urls(tcl_version,tk_version,openssl_version)
    for name,url in urls.items():
        try:
            with urllib.request.urlopen(url,timeout=30) as response:
                data=response.read(1_000_000)
        except urllib.error.HTTPError as error:
            if name=='OPENSSL-NOTICE.txt' and error.code==404:
                continue  # Older upstream releases have no separate NOTICE file.
            raise
        if len(data)<100:
            raise RuntimeError('Unexpected runtime license response: '+name)
        (target/name).write_bytes(data)
    print('Collected Python, Tcl/Tk and OpenSSL runtime licenses')


if __name__=='__main__':collect(sys.argv[1])

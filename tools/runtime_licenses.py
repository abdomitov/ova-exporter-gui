"""Collect license texts for the exact Python/Tcl/Tk/OpenSSL build being bundled."""
from pathlib import Path
import shutil
import ssl
import sys
import tkinter
import urllib.request
import urllib.error


def collect(destination):
    target=Path(destination)
    target.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(Path(sys.base_prefix)/'LICENSE.txt',target/'PYTHON.txt')
    tk_license=next((Path(sys.base_prefix)/'tcl').glob('tk*/license.terms'))
    shutil.copyfile(tk_license,target/'TK.txt')
    tcl_version=tkinter.Tcl().eval('info patchlevel').replace('.','-')
    openssl_version=ssl.OPENSSL_VERSION.split()[1]
    urls={
        'TCL.txt':f'https://raw.githubusercontent.com/tcltk/tcl/core-{tcl_version}/license.terms',
        'OPENSSL.txt':f'https://raw.githubusercontent.com/openssl/openssl/openssl-{openssl_version}/LICENSE.txt',
        'OPENSSL-NOTICE.txt':f'https://raw.githubusercontent.com/openssl/openssl/openssl-{openssl_version}/NOTICE.md',
    }
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

# Third-party software

The MIT license covers this project's application code and documentation only.

VMware OVF Tool is a separate Broadcom/VMware dependency. Obtain it from the
[official download page](https://developer.broadcom.com/tools/open-virtualization-format-ovf-tool/latest/)
and follow the license supplied with that download. It is not relicensed by this
project. Do not upload your installed `ovftool` directory, VMware DLLs, executables
or vendor documentation with the public source release. A private local copy is
supported for existing installations.

The Windows installer bundles Python, Tcl/Tk and OpenSSL; their license texts
are shipped in the installed `licenses` directory. They retain their respective
licenses. Source users install Python separately. PyInstaller builds the frozen
executable under its bootloader exception; see https://pyinstaller.org/en/stable/license.html.
Pillow is used only to build the original geometric icon, not by the runtime.
This project draws its own UI assets and does not use VMware logos.

VMware, vSphere, vCenter and ESXi are product names belonging to their respective
owners. References describe compatibility; this is an independent project.

Option Explicit
Dim shell, fso, folder, executable, entry, version, base, candidate
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
executable = ""

' Prefer the windowed Python launcher, then a windowed Python on PATH.
For Each candidate In Array("pyw.exe", "pythonw.exe")
    For Each entry In Split(shell.ExpandEnvironmentStrings("%PATH%"), ";")
        entry = Replace(entry, Chr(34), "")
        If Len(entry) > 0 Then
            If fso.FileExists(fso.BuildPath(entry, candidate)) Then
                executable = fso.BuildPath(entry, candidate)
                Exit For
            End If
        End If
    Next
    If Len(executable) > 0 Then Exit For
Next

' Standard installers register Python even when it is absent from PATH.
If Len(executable) = 0 Then
    On Error Resume Next
    For Each version In Array("3.14", "3.13", "3.12", "3.11", "3.10")
        For Each base In Array("HKCU", "HKLM")
            Err.Clear
            entry = shell.RegRead(base & "\Software\Python\PythonCore\" & version & "\InstallPath\")
            If Err.Number = 0 Then
                candidate = fso.BuildPath(entry, "pythonw.exe")
                If fso.FileExists(candidate) Then
                    executable = candidate
                    Exit For
                End If
            End If
        Next
        If Len(executable) > 0 Then Exit For
    Next
    On Error GoTo 0
End If
If Len(executable) = 0 Then
    MsgBox "Python 3.10 or newer with Tkinter is required. Install Python with its launcher, or use Start OVA Exporter.cmd for details.", 16, "OVA Exporter GUI"
    WScript.Quit 1
End If
shell.CurrentDirectory = folder
entry = Chr(34) & executable & Chr(34)
If LCase(fso.GetFileName(executable)) = "pyw.exe" Then entry = entry & " -3"
shell.Run entry & " " & Chr(34) & folder & "\launch.pyw" & Chr(34), 1, False

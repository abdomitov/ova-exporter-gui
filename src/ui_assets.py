"""Small code-drawn assets; no external fonts, images, or downloads."""
import tkinter as tk


def configure_checkboxes(root, style, palette=None):
    """Use a slim, antialiased check mark instead of a chunky pixel stroke."""
    palette = palette or {'border':'#c8d1dc', 'muted':'#64748b', 'accent':'#087f8c', 'field':'#ffffff', 'bg':'#f3f6fa'}
    existing = getattr(root._root(), '_ova_check_images', [])
    size = max(16, round(13 * float(root.tk.call('tk', 'scaling'))))
    images = []
    for selected, disabled in ((False, False), (True, False), (False, True), (True, True)):
        border = palette['border'] if disabled else palette['muted']
        background = (palette['muted'] if disabled else palette['accent']) if selected else (palette['bg'] if disabled else palette['field'])
        pixels = [[border if x in (0, size-1) or y in (0, size-1) else background
                   for x in range(size)] for y in range(size)]
        if selected:
            points = [(size*x, size*y) for x,y in ((0.22,0.54),(0.43,0.75),(0.81,0.20))]
            segments = []
            for start,end in zip(points,points[1:]):
                dx,dy = end[0]-start[0],end[1]-start[1]
                segments.append((start[0],start[1],dx,dy,dx*dx+dy*dy))
            radius_squared = (size*0.038)**2
            base = tuple(int(background[index:index+2],16) for index in (1,3,5))
            offsets = (0.125,0.375,0.625,0.875)
            for y in range(1,size-1):
                for x in range(1,size-1):
                    covered = 0
                    for oy in offsets:
                        for ox in offsets:
                            for ax,ay,dx,dy,length_squared in segments:
                                t = max(0,min(1,((x+ox-ax)*dx+(y+oy-ay)*dy)/length_squared))
                                if (x+ox-ax-t*dx)**2 + (y+oy-ay-t*dy)**2 <= radius_squared:
                                    covered += 1
                                    break
                    if covered:
                        alpha = covered/16
                        pixels[y][x] = '#' + ''.join(f'{round(channel+(255-channel)*alpha):02x}' for channel in base)
        image = existing[len(images)] if existing else tk.PhotoImage(master=root, width=size, height=size)
        image.put(' '.join('{' + ' '.join(row) + '}' for row in pixels))
        images.append(image)
    root._root()._ova_check_images = images  # Retain images for this Tcl interpreter.
    off, on, off_disabled, on_disabled = images
    if not existing:
        style.element_create('OvaCheck.indicator', 'image', off,
                             ('disabled', 'selected', on_disabled), ('disabled', off_disabled), ('selected', on),
                             width=size + round(size / 2), sticky='w')
    style.layout('Ova.TCheckbutton', [('Checkbutton.padding', {'sticky': 'nswe', 'children': [
        ('OvaCheck.indicator', {'side': 'left', 'sticky': ''}),
        ('Checkbutton.focus', {'side': 'left', 'sticky': 'w', 'children': [
            ('Checkbutton.label', {'sticky': 'nswe'})]})]})])
    style.configure('Ova.TCheckbutton', padding=(0, 2), indicatorspace=5)

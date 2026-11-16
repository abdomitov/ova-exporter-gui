"""Scrollable bodies and one wheel router per window."""
import tkinter as tk
from tkinter import ttk


def install_mousewheel(root):
    """Route wheel events to the nearest scrolling widget in this window."""
    def wheel(event):
        try:
            widget = root.winfo_containing(event.x_root, event.y_root) or event.widget
        except (tk.TclError, KeyError):
            return
        delta = getattr(event, 'delta', 0)
        units = -int(delta / 120) if abs(delta) >= 120 else (-1 if delta > 0 else 1)
        if getattr(event, 'num', None) in (4, 5):
            units = -1 if event.num == 4 else 1
        horizontal = bool(getattr(event, 'state', 0) & 1)
        node = widget
        while node is not None:
            if isinstance(node, ScrollBody):
                if horizontal:
                    return
                view = node.canvas.yview()
                if (units < 0 and view[0] > 0) or (units > 0 and view[1] < 1):
                    node.canvas.yview_scroll(units * 3, 'units')
                    return 'break'
            elif hasattr(node, 'wheel_units'):
                if not horizontal and node.wheel_units(units * 3):
                    return 'break'
            elif isinstance(node, (ttk.Treeview, tk.Text)):
                view = node.xview() if horizontal else node.yview()
                if (units < 0 and view[0] > 0) or (units > 0 and view[1] < 1):
                    (node.xview_scroll if horizontal else node.yview_scroll)(units * 3, 'units')
                    return 'break'
            node = getattr(node, 'master', None)
        return 'break'

    # A leading bindtag handles a wheel over labels, graphs and nested frames
    # before the Tk widget's default binding can scroll a second time.
    tag = f'Wheel_{id(root)}'
    for sequence in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
        root.bind_class(tag, sequence, wheel)
    def focused(event):
        try:
            if root.focus_get() is not event.widget:
                return  # Tk also emits ancestor FocusIn notifications.
        except tk.TclError:
            return
        node = getattr(event.widget, 'master', None)
        while node is not None:
            if isinstance(node, ScrollBody):
                node.after_idle(lambda body=node, widget=event.widget: body.reveal(widget))
                break
            node = getattr(node, 'master', None)
    root.bind_class(tag, '<FocusIn>', focused)
    def attach(widget):
        if tag not in widget.bindtags():
            widget.bindtags((tag,) + widget.bindtags())
        for child in widget.winfo_children():
            attach(child)
    attach(root)
    return lambda: attach(root)


class ScrollBody(ttk.Frame):
    def __init__(self, parent, tone='', padding=(10, 8)):
        super().__init__(parent, style=tone + 'TFrame')
        self.tone = tone
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0, width=1, height=1)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        self.scroll = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview,
                                    style=('Surface.' if tone == 'Surface.' else '') + 'Vertical.TScrollbar')
        self.scroll.grid(row=0, column=1, sticky='ns')
        self.inner = ttk.Frame(self.canvas, padding=padding, style=tone + 'TFrame')
        self.window = self.canvas.create_window(0, 0, anchor='nw', window=self.inner)
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.pending = None
        self.canvas.bind('<Configure>', self.schedule)
        self.inner.bind('<Configure>', self.schedule)
        theme = getattr(self._root(), '_ova_theme', None)
        if theme:
            theme.register(self)

    def apply_theme(self, colors):
        key = {'': 'bg', 'Surface.': 'surface', 'Sunken.': 'sunken'}[self.tone]
        self.canvas.configure(background=colors[key])

    def schedule(self, event=None):
        if self.pending is None:
            self.pending = self.after_idle(self.fit)

    def reveal(self, widget):
        """Keep a keyboard-focused descendant inside the visible viewport."""
        try:
            if not widget.winfo_ismapped() or not self.winfo_ismapped():
                return
            y = widget.winfo_rooty()-self.inner.winfo_rooty()
            bottom = y+widget.winfo_height()
            top = self.canvas.canvasy(0)
            height = self.canvas.winfo_height()
            target = y-8 if y < top+8 else bottom+8-height if bottom > top+height-8 else top
            self.canvas.yview_moveto(max(0,target)/max(1,self.inner.winfo_height()))
        except tk.TclError:
            pass  # Focus can change while the setup window is closing.

    def fit(self):
        self.pending = None
        width = max(1, self.canvas.winfo_width())
        height = max(self.inner.winfo_reqheight(), self.canvas.winfo_height())
        self.canvas.itemconfigure(self.window, width=width, height=height)
        self.canvas.configure(scrollregion=(0, 0, width, height))
        # Show the bar only while there is something to scroll to.
        if height > self.canvas.winfo_height() > 1:
            self.scroll.grid()
        else:
            self.scroll.grid_remove()

    def destroy(self):
        if self.pending is not None:
            self.after_cancel(self.pending)
            self.pending = None
        super().destroy()

# -*- coding: utf-8 -*-
"""Clean UIA reader: print '<X1>\t<Y1>\t<banner>' from the Graphic Viewer readout.
Run as a SEPARATE process (no tkinter/COM) so UIA can traverse the readout.

    python pak_read_y1.py [runtag]
"""
import sys, time
import uiautomation as auto
runtag = sys.argv[1] if len(sys.argv) > 1 else ""

def read():
    win = None
    for w in auto.GetRootControl().GetChildren():
        try:
            if w.ControlTypeName=="WindowControl" and "graphic viewer" in (w.Name or "").lower():
                win=w; break
        except Exception: pass
    if not win: return None, None, ""
    labels={}; edits=[]; banner=""
    def walk(c, d=0):
        nonlocal banner
        for ch in c.GetChildren():
            try:
                ct=ch.ControlTypeName; nm=ch.Name or ""; r=ch.BoundingRectangle
                if ct=="TextControl" and nm in ("X1:","Y1:"): labels[nm[:-1]]=r
                elif ct=="TextControl" and nm.startswith("Project:"): banner=nm
                elif ct=="EditControl":
                    try: v=ch.GetValuePattern().Value or ""
                    except Exception: v=""
                    edits.append((r.left,r.top,v))
            except Exception: pass
            if d<10: walk(ch,d+1)
    walk(win)
    def near(l):
        if l not in labels: return None
        r=labels[l]; best=None; bd=1e9
        for (x,y,v) in edits:
            if abs(y-r.top)<20 and x>=r.left-2 and (x-r.left)<bd: bd=x-r.left; best=v
        return best
    return near("X1"), near("Y1"), banner

x1=y1=None; banner=""
for _ in range(15):
    x1,y1,banner = read()
    ok = y1 and any(c.isdigit() for c in y1) and (runtag in banner if runtag else True)
    if ok: break
    time.sleep(0.3)
print("%s\t%s\t%s" % (x1, y1, banner))

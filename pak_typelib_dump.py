# -*- coding: utf-8 -*-
"""Load PAK's COM type library from the registry and dump member names.
Reveals exact property names (stat parameter, weighting, averaging, etc.)."""
import winreg
import pythoncom

CLSID = "{8F2D7527-92B1-11D4-9526-00C04F672C13}"

def reg_get(root, path, name=""):
    try:
        k = winreg.OpenKey(root, path)
        v, _ = winreg.QueryValueEx(k, name)
        return v
    except Exception:
        return None

def subkeys(root, path):
    out = []
    try:
        k = winreg.OpenKey(root, path)
        i = 0
        while True:
            try:
                out.append(winreg.EnumKey(k, i)); i += 1
            except OSError:
                break
    except Exception:
        pass
    return out

# 1) LIBID from CLSID
libid = reg_get(winreg.HKEY_CLASSES_ROOT, r"CLSID\%s\TypeLib" % CLSID)
ver   = reg_get(winreg.HKEY_CLASSES_ROOT, r"CLSID\%s\Version" % CLSID)
print("LIBID:", libid, "Version:", ver)

tlb = None
if libid:
    vers = [ver] if ver else subkeys(winreg.HKEY_CLASSES_ROOT, r"TypeLib\%s" % libid)
    for vv in vers:
        try:
            major, minor = (int(x) for x in vv.split("."))
        except Exception:
            major, minor = 1, 0
        # try path first (win64/win32)
        for sub in ("win64", "win32"):
            p = reg_get(winreg.HKEY_CLASSES_ROOT, r"TypeLib\%s\%s\0\%s" % (libid, vv, sub))
            if p:
                try:
                    tlb = pythoncom.LoadTypeLib(p); print("loaded typelib from", p); break
                except Exception as e:
                    print("LoadTypeLib fail", p, e)
        if tlb: break
        try:
            tlb = pythoncom.LoadRegTypeLib(libid, major, minor, 0)
            print("LoadRegTypeLib ok", vv); break
        except Exception as e:
            print("LoadRegTypeLib fail", vv, e)

if tlb is None:
    print("Could not load PAK typelib.")
    raise SystemExit

def dump(tinfo, tname):
    names = []
    try:
        ta = tinfo.GetTypeAttr()
        for j in range(ta.cFuncs):
            fd = tinfo.GetFuncDesc(j)
            nm = tinfo.GetNames(fd.memid)
            if nm: names.append(nm[0])
        for j in range(ta.cVars):
            vd = tinfo.GetVarDesc(j)
            nm = tinfo.GetNames(vd.memid)
            if nm: names.append(nm[0])
    except Exception:
        pass
    return sorted(set(names))

n = tlb.GetTypeInfoCount()
print("typeinfos:", n)
KEYS = ("stat","avg","average","mittel","reduce","regress","weight","fweight","bewert")
for i in range(n):
    try:
        name = tlb.GetDocumentation(i)[0]
        tinfo = tlb.GetTypeInfo(i)
    except Exception:
        continue
    ms = dump(tinfo, name)
    low = (name or "").lower()
    if any(k in low for k in ("track","datentyp","datatyp","datatype","tracking")):
        print("\n===== %s : ALL =====" % name)
        print(ms)
    hits = [m for m in ms if any(k in m.lower() for k in KEYS)]
    if hits:
        print("\n----- %s : keyword hits -----" % name)
        print(hits)
print("\ndone.")

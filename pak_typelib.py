"""Generate PAK early-binding wrapper and extract Item/weighting signatures."""
import os, re, glob
import win32com.client as win32
from win32com.client import gencache

print("Generating type library (makepy) for Pak.Application.1 ...")
try:
    app = gencache.EnsureDispatch("Pak.Application.1")
    print("EnsureDispatch OK ->", type(app))
except Exception as e:
    print("EnsureDispatch failed:", e)
    app = win32.Dispatch("Pak.Application.1")

# Locate the generated gen_py cache files
gp = win32.gencache.GetGeneratePath()
print("gen_py path:", gp)
pyfiles = glob.glob(os.path.join(gp, "*.py")) + glob.glob(os.path.join(gp, "**", "*.py"), recursive=True)
# pick the largest recently-modified file (the PAK typelib module)
pyfiles = [f for f in pyfiles if os.path.basename(f) != "__init__.py"]
pyfiles.sort(key=lambda f: os.path.getmtime(f), reverse=True)
print("candidate modules:", [os.path.basename(f) for f in pyfiles[:6]])

def scan(path):
    txt = open(path, encoding="mbcs", errors="replace").read()
    print("\n===== scanning %s (%d bytes) =====" % (os.path.basename(path), len(txt)))
    # class definitions
    classes = re.findall(r"^class\s+(\w+)", txt, re.M)
    keyclasses = [c for c in classes if any(k in c.lower() for k in ("graphdef","item","datatyp","datentyp","track"))]
    print("key classes:", keyclasses[:20])
    # Item-related defs/properties
    for kw in ("Item", "GraphicOutput", "Graphicoutput"):
        for m in re.finditer(r".{0,4}\b%s\b.{0,60}" % re.escape(kw), txt):
            line = m.group(0).replace("\n"," ").strip()
            if "def " in line or "dispid" in line.lower() or "=" in line:
                print("  [%s] %s" % (kw, line[:100]))
    # weighting props
    for m in re.finditer(r"def\s+(\w*[Ww]eight\w*|\w*[Ff]weight\w*)\b", txt):
        print("  [WEIGHT def] ", m.group(0))
    for m in re.finditer(r'"(\w*[Ww]eight\w*|\w*[Ff]weight\w*)"', txt):
        print("  [WEIGHT name]", m.group(1))

for f in pyfiles[:4]:
    try:
        scan(f)
    except Exception as e:
        print("scan err", f, e)

# Now try early-bound Item access
try:
    gd = app.GraphDef
    print("\nGraphDef type (early):", type(gd))
    print("trying gd.Item(1) early-bound ...")
    it = gd.Item(1)
    print("  Item(1) OK ->", type(it))
except Exception as e:
    print("  Item(1) early-bound FAILED:", e)

print("\ndone.")

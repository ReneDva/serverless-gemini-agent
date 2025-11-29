# introspect_genai.py
import sys
try:
    from google import genai as g
    mod = g
    print("Imported: google.genai")
except Exception as e:
    print("Import failed:", e)
    sys.exit(1)

print("\nModule file:", getattr(mod, "__file__", "<built-in>"))
print("\nTop-level names:")
print([n for n in dir(mod) if not n.startswith("_")])

if hasattr(mod, "Models"):
    print("\nNames on genai.Models:")
    print([n for n in dir(mod.Models) if not n.startswith("_")])
else:
    print("\ngenai.Models not present")

from google import genai
import inspect
print("genai module file:", genai.__file__)
print("\nTop-level names:", [n for n in dir(genai) if not n.startswith("_")])
print("\nmodels members:")
try:
    import google.genai.models as m
    print([n for n in dir(m) if not n.startswith("_")])
except Exception as e:
    print("cannot import google.genai.models:", e)

from google import genai
import inspect, sys

print("genai module:", genai.__file__)
print("\nTop-level names:", [n for n in dir(genai) if not n.startswith("_")])

import google.genai.models as m
print("\nmodels members:", [n for n in dir(m) if not n.startswith("_")])

# אם יש מחלקה Models, הדפס את המתוודות שלה
if hasattr(m, "Models"):
    print("\nMembers of models.Models:")
    print([n for n in dir(m.Models) if not n.startswith("_")])

# בדוק client
if hasattr(genai, "Client"):
    Client = genai.Client
    print("\nClient members:", [n for n in dir(Client) if not n.startswith("_")])

from google import genai
import inspect
import google.genai.models as m
print("module:", m)
if hasattr(m, "Models"):
    sig = inspect.signature(m.Models.generate_content)
    print("Signature for models.Models.generate_content:", sig)
else:
    # אם אין Models, בדוק ישירות את הפונקציה במודול
    if hasattr(m, "generate_content"):
        sig = inspect.signature(m.generate_content)
        print("Signature for models.generate_content:", sig)
    else:
        print("generate_content not found on models module")
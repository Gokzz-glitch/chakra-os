import os, glob
from google import genai
from google.genai import types

PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "girpolypposframesrealcolon")
client = genai.Client(vertexai=True, project=PROJECT, location="global")

BUILDERS = [
    ("gemini-4-hydrogen", "UI/UX & fast everyday coding (Black & White Gmail-style UI)"),
    ("gemini-4-neon", "Systems architecture, WebSocket/GCS streaming & open-source model combinations"),
    ("gemini-3.8-flash", "Clinical workflow, ABDM FHIR R4, Tamil/English discharge & MedGemma/MedASR hybrid"),
    ("gemini-3.6-flash", "Multimodal video/frame handling & clinician HUD ergonomics"),
]
CRITICS = [
    ("gemini-4-carbon", "Deep root-cause bugs, race conditions & latency flaws"),
    ("gemini-4-argon", "Security red-teaming: XSS, path traversal, DPDP PHI leaks"),
    ("gemini-3.1-pro-preview", "Clinical & CDSCO Class B safety (Standby gate, PENDING pathology, Apache 2.0 licensing)"),
    ("gemini-3.5-flash-lite", "JSON schema integrity & zero-PHI compliance"),
    ("gemini-3.1-flash-lite", "Cloud Run scaling & FinOps token-cost traps"),
]

def load_code():
    chunks = []
    for f in ["main.py", "clinical_pipeline.py"]:
        if os.path.exists(f):
            chunks.append(f"=== {f} ===\n" + open(f, encoding="utf-8").read()[:12000])
    return "\n\n".join(chunks)

def ask(model, prompt):
    try:
        r = client.models.generate_content(model=model, contents=prompt, config=types.GenerateContentConfig(temperature=0.2))
        return r.text or ""
    except Exception as e:
        return f"[Fallback/Error on {model}: {e}]"

code_ctx = load_code()
history = ""

for rnd in range(1, 16):
    print(f"\n--- ROUND {rnd}: 4 BUILDERS ---")
    proposals = []
    for m, role in BUILDERS:
        p = f"Role: {role}. Audit CHAKRA V2 code below. Evaluate what works now vs open-source combos (RF-DETR-Small, ByteTrack, OSABPS, MedASR, MedGemma 1.5 4B, AlloyDB ScaNN, GCS streaming). Propose concrete fixes.\nPrev critiques:\n{history[-4000:]}\n\n{code_ctx}"
        out = ask(m, p)
        proposals.append(f"### Builder {m}\n{out[:2500]}")
        print(f"  + {m} done")

    print(f"--- ROUND {rnd}: 5 CRITICS ---")
    critiques = []
    prop_text = "\n".join(proposals)
    for m, lens in CRITICS:
        p = f"Role: Critic ({lens}). Find ONLY Blocker or Major flaws in these proposals + current code. Be concise.\n\n{prop_text[:10000]}"
        out = ask(m, p)
        critiques.append(f"### Critic {m}\n{out[:1800]}")
        print(f"  - {m} done")

    crit_text = "\n".join(critiques)
    history += f"\n# ROUND {rnd}\n{prop_text}\n{crit_text}\n"

    # 6th Critic: Gatekeeper check
    gate = ask("gemini-3.5-flash-lite", f"Reply ONLY 'CLEAN' if zero Blocker/Major flaws remain, else 'ITERATE':\n{crit_text[:6000]}")
    print(f"  [Gatekeeper Round {rnd}]: {gate.strip()}")
    if rnd >= 6 and "CLEAN" in gate.upper():
        break

with open("ADVERSARIAL_REVIEW_REPORT.md", "w", encoding="utf-8") as f:
    f.write(history)
print("\nSaved full 10-model consensus to ADVERSARIAL_REVIEW_REPORT.md")


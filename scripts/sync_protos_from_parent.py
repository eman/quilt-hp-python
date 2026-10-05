#!/usr/bin/env python3
"""Copy ../proto/cleaned/*.proto into proto/cleaned/, stripping reverse-engineering provenance.

The research repo's protos annotate fields with decompiler class names and app-build sources
(e.g. "APK 271 (ce2)", "C4363kK.java", "iOS KMP 1.0.26"). This package's protos keep the
semantic comments but not that provenance. Structure is copied verbatim.

usage: scripts/sync_protos_from_parent.py [--report]
  --report  print every comment line the sanitizer changed, for review
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
SRC = PKG.parent / "proto" / "cleaned"
DST = PKG / "proto" / "cleaned"
FILES = [
    "quilt_hds.proto",
    "quilt_services.proto",
    "quilt_notifier.proto",
    "quilt_system.proto",
    "quilt_device_pairing.proto",
    "quilt_device_config.proto",
    "quilt_actions.proto",
]

# (pattern, replacement) applied to comments in order. Decompiler class names are deleted;
# build/source references become neutral "the app" wording.
SUBS = [
    (r"\s*\(APK \d{3}: [^)]*\)", ""),  # (APK 271: a27/c27, ...)
    (r"\s*\(271 classes in$", "."),
    (r"^parentheses\)\.\s*", ""),
    (
        r"\bNM\.smali is a DIFFERENT message \(WifiState for established connections\)\.",
        "Not to be confused with WifiState (used for established connections).",
    ),
    (r"\bAndroid C\d{3,5}[a-zA-Z]{1,2}\b", "the app"),
    (r"\s*\((?:from )?\w+\.java[^)]*\)", ""),  # (C4363kK.java ...)
    (r"\s*(?:from |in )?\b[A-Z]\w*\.java\b", ""),  # from OJ.java
    (r"\b\w+\.smali is a DIFFERENT message\b", "Not to be confused with"),
    (r"\s*\(\w+\.smali\)|\b\w+\.smali\b", ""),
    (r"\s*\[\d{3}: [^\]]*\]", ""),  # [271: qn7]
    (r"\s*\(\d{3}: [^)]*\)", ""),  # (271: ce2), (271: zn2): ...
    (r"\b\d{3}: [a-z]{1,3}\d?[a-z0-9]?\$?\w*\b(?: — | \()?", ""),  # 271: vb2 —
    (r"\s*\((?:C\d{3,5}[a-zA-Z]{1,2}|[A-Z]{2})\)", ""),  # (C2132aK) (YJ)
    (r"\s*\((?:[a-z]{1,3}\d[a-z0-9]?|[a-z]{2,3}\d?)\)", ""),  # (ld3) (gb) (a28)
    (r"\s*//\s*(?:[a-z]{1,3}\d[a-z0-9]?)\b", ""),
    (r"\b(?:enum |message )?class [A-Za-z]\w*\b", ""),
    (r"\b[A-Z0-9_]+_FIELD_NUMBER\s*=\s*\d+\s*", ""),
    (r"\b[A-Z0-9_]+_FIELD_NUMBER\b", ""),
    (r"\bAndroid (?:APK )?(?:DEX|smali)\b", "the app"),
    (r"\bAndroid proto\b", "app proto"),
    (r"\bAndroid-confirmed\b", "Confirmed against the app"),
    (r"\bAndroid APK\b|\bAndroid\b(?= stub)", "app"),
    (r"\bAPK[- ]confirmed\b", "confirmed against the app"),
    (r"\bAPK names?\b", "app names"),
    (r"\bAPK 255\+271\b|\bAPK 255 and 271\b", "app 1.0.31+"),
    (r"\bAPK 271\b", "app 1.0.33"),
    (r"\bAPK 255\b", "app 1.0.31"),
    (r"\bAPK\b", "app"),
    (r"\bcom\.quilt\.android (\d\.\d+\.\d+)", r"app \1"),
    (r"\bcom\.quilt\.android\b", "the app"),
    (r"\bversionCode 271\b", "1.0.33"),
    (r"\bversionCode 255\b", "1.0.31"),
    (r"\biOS KMP\b", "iOS app"),
    (r"\bKMP\b", "iOS app"),
    (r"\bjadx\b|\bDEX\b", ""),
    (r"\breference/android/\S+|\bprotoaudit\.py\b", ""),
    (r"\bthe (?:the|app) app\b", "the app"),
    (r"\bthe app app\b", "the app"),
    (
        r"^[a-z]{1,3}\d[a-z0-9]?(?:\$\w+)?(?=\s*(?:$|—|\(|,))\s*—?\s*",
        "",
    ),  # leading class tag: "jj2 — ..."
    (r"^(?:[a-z]{1,3}\d[a-z0-9]?/)+[a-z]{1,3}\d[a-z0-9]?\b\s*", ""),  # "wn2 / xn2 / vn2"
    (r"\s*\((?:[a-z]{1,3}\d[a-z0-9]?\s*/\s*)+[a-z]{1,3}\d[a-z0-9]?\)", ""),  # (wn2 / xn2 / vn2)
    (r";\s*enum [a-z]{1,3}\d[a-z0-9]? in \d{3}\)", ")"),  # (255+; enum ty4 in 271)
    # tidy what the deletions leave behind
    (r"\(\s*app\s*[;,]\s*", "("),
    (r",\s*\)", ")"),
    (r"\(\s*\)", ""),
    (r"^app\s*:?\s*[;.]?\s*", ""),
    (r":\s*,\s*\.$", "."),
    (r":\s*—", " —"),
    (r"\s+by\s*\.?$", "."),
    (r"\s+;", ";"),
]
SUB_RE = [(re.compile(a), b) for a, b in SUBS]
MARKER = re.compile(
    r"APK|\.java|KMP|jadx|smali|\b\d{3}: [a-z]{1,3}\d|versionCode|com\.quilt\.android|FIELD_NUMBER|\(C\d{3,5}"
)
JUNK = re.compile(r"^[\s,;:()\-—/.+]*$")


def clean_comment(text: str) -> str | None:
    out = text
    for r, rep in SUB_RE:
        out = r.sub(rep, out)
    out = re.sub(r"\(\s*\)", "", out)
    out = re.sub(r"\s{2,}", " ", out).strip()
    if out == text:
        return text
    out = re.sub(r"^[;,:—\-\s]+|[;,:—\-\s]+$", "", out)
    if JUNK.match(out) or len(out) < 4:
        return None
    return out


HEADERS = {
    "quilt_hds.proto": """// quilt_hds.proto
// Home Datastore (HDS) messages — objects managed by the gRPC API, plus the notifier
// payloads (HdsNotification / HomeDatastoreObjectDiff).
// Field numbers and wire types confirmed against the Quilt app and live captures.
""",
    "quilt_services.proto": """// quilt_services.proto
// gRPC app-service definitions (package core.protos.app).
//
// NOTE: SystemService lives in package core.protos.system — see quilt_system.proto.
""",
    "quilt_notifier.proto": """// quilt_notifier.proto
// NotifierService — bidirectional streaming subscription service.
// Confirmed gRPC path: /core.protos.notifier.NotifierService/Subscribe
//
// Message layout:
//   SubscribeRequest   (oneof: append=2 | remove=3, each a TopicsMessage)
//   SubscribeResponse  (event=1, a single SubscribeEvent)
//   SubscribeEvent     (notifier_events=1, control_events=2, system_events=3)
//   NotifierEvent      (topic=1 string, payload=2 google.protobuf.Any)
//   ControlEvent       (topics=1 repeated string, type=2 ControlEventType)
//   SystemEvent        (system_event_type=1)
// NotifierEvent.payload carries a core.protos.home_datastore.HdsNotification (quilt_hds.proto).
""",
    "quilt_system.proto": """// quilt_system.proto
// SystemService lives in package core.protos.system on the wire path. The server implements
// Get/Create/Update/Delete/ListSystems; the Quilt app itself calls only DeleteSystem and creates
// systems via MobileAppService/CreateAndConfigureSystem.
""",
    "quilt_device_pairing.proto": """// quilt_device_pairing.proto
// BLE/WiFi device pairing protocol — serialized over Bluetooth, and also the payloads of
// DeviceConfigurationService (quilt_device_config.proto).
// Used during initial setup of Quilt Smart Module (QSM) and Controller devices.
""",
    "quilt_device_config.proto": """// quilt_device_config.proto
// DeviceConfigurationService — plaintext gRPC provisioning API a QSM/Dial exposes on port 50051
// while in setup mode (169.254.1.1 on its provisioning hotspot).
// Wire path: /core.protos.common.DeviceConfigurationService/<Method>.
""",
    "quilt_actions.proto": """// quilt_actions.proto
// HomeActionService — unified "submit an action" control API.
// Wire path: /core.protos.actions.HomeActionService/SubmitAction
// Fields marked `optional` have explicit presence: omit them to leave a setting unchanged.
""",
}


def replace_header(src: str, name: str) -> str:
    idx = src.index("\nsyntax = ")
    return HEADERS[name] + src[idx:]


def sanitize(src: str, report: list[str], name: str) -> str:
    src = replace_header(src, name)
    lines = []
    for ln in src.splitlines():
        m = re.match(r"^(\s*)//(.*)$", ln)
        if m:  # whole-line comment
            c = clean_comment(m.group(2).strip())
            if c != m.group(2).strip():
                report.append(f"{name}: {m.group(2).strip()!r} -> {c!r}")
            if c is None:
                continue
            lines.append(f"{m.group(1)}// {c}" if c else f"{m.group(1)}//")
            continue
        code, sep, com = ln.partition("//")
        if sep and '"' not in code:  # trailing comment
            c = clean_comment(com.strip())
            if c != com.strip():
                report.append(f"{name}: {com.strip()!r} -> {c!r}")
            lines.append(code.rstrip() + (f"  // {c}" if c else ""))
        else:
            lines.append(ln)
    text = "\n".join(lines) + "\n"
    return re.sub(r"\n{3,}", "\n\n", text)


def main() -> None:
    report: list[str] = []
    for f in FILES:
        out = sanitize((SRC / f).read_text(), report, f)
        left = [line for line in out.splitlines() if MARKER.search(line)]
        if left:
            sys.exit(f"{f}: provenance left after sanitizing:\n  " + "\n  ".join(left))
        (DST / f).write_text(out)
        print(f"synced {f}")
    if "--report" in sys.argv:
        print("\n".join(report))


if __name__ == "__main__":
    main()

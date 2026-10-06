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
from collections.abc import Callable
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
_OBF = r"(?!f\d)[a-z]{1,3}\d[a-z0-9]?"  # obfuscated class tag (e.g. ce2, a28); never a field tag like f15

SUBS: list[tuple[str, str | Callable[[re.Match[str]], str]]] = [
    # whole provenance phrases first
    (r"\(APK \d{3}: \w+; (wire bytes [^)]*)\)", r"(\1)"),
    (r"\s*\(APK \d{3}: [^)]*\)", ""),  # (APK 271: a27/c27, ...)
    (r"\s*\(271 classes in$", "."),
    (rf"^(\d{{3}}): {_OBF} — new$", r"new in \1"),  # "271: jg2 — new"
    (
        r"^(?:APK|Android)-confirmed (values|field \d+|field layout)\b",
        lambda m: f"{m.group(1)[0].upper()}{m.group(1)[1:]} confirmed against the app",
    ),
    (r"\bAPK-confirmed (field \d+)\b", r"\1, confirmed against the app"),
    (r"^APK-confirmed\b", "Confirmed against the app"),
    (r"^parentheses\)\.\s*", ""),
    (
        r"\bNM\.smali is a DIFFERENT message \(WifiState for established connections\)\.",
        "Not to be confused with WifiState (used for established connections).",
    ),
    (
        r"\bConfirmed by (?:Android|app) proto Java enum \w+ \(implements ProtocolMessageEnum\)\.?",
        "Confirmed against the app.",
    ),
    (r"\bJava enum [A-Z]\w*", "enum"),
    (r";?\s*classes are \d{3}\.?", "."),
    (r"\bconfirmed Android C\d{3,5}[a-zA-Z]{1,2}\b", "confirmed against the app"),
    (r"\bAndroid C\d{3,5}[a-zA-Z]{1,2}\b", "the app"),
    # file / class references
    (r"\s*\((?:from )?\w+\.java[^)]*\)", ""),  # (C4363kK.java ...)
    (r"\s*(?:from |in )?\b[A-Z]\w*\.java\b", ""),  # from OJ.java
    (r"\s*\(\w+\.kt\)|\s*\b\w+\.kt\b", ""),  # (WifiScan.kt)
    (r"\b\w+\.smali is a DIFFERENT message\b", "Not to be confused with"),
    (r"\s*\(\w+\.smali\)|\b\w+\.smali\b", ""),
    (r"\s*\[\d{3}: [^\]]*\]", ""),  # [271: qn7]
    (r"\s*\(\d{3}: [^)]*\)", ""),  # (271: ce2), (271: zn2): ...
    (rf"\b\d{{3}}: {_OBF}\$?\w*\b(?: — | \()?", ""),  # 271: vb2 —
    (r"\s*\((?:C\d{3,5}[a-zA-Z]{1,2}|[A-Z]{2})\)", ""),  # (C2132aK) (YJ)
    (rf"\s*\({_OBF}\)", ""),  # (ld3) (a28)
    (r"(?<=\b(?:255|271)) \([a-z]{2,3}\)", ""),  # "in 255 (da) and 271 (gb)"
    (rf"\s*//\s*{_OBF}\b", ""),
    (r"\b(?:enum |message )?class (?:C\d{3,5}\w*|[A-Z]{1,3}\b|[a-z]{1,3}\d\w*)", ""),
    (r"\b[A-Z0-9_]+_FIELD_NUMBER\s*=\s*\d+\s*", ""),
    (r"\b[A-Z0-9_]+_FIELD_NUMBER\b", ""),
    # source names -> neutral wording
    (r"\bAndroid (?:APK )?(?:DEX|smali)\b", "the app"),
    (r"\bAndroid proto\b", "app proto"),
    (r"\bAndroid-confirmed\b", "Confirmed against the app"),
    (r"\bAndroid APK\b|\bAndroid\b(?= stub)", "app"),
    (r"\bAPK[- ]confirmed\b", "confirmed against the app"),
    (r"\bAPK name\b", "app name"),
    (r"\bAPK names\b", "app names"),
    (r"\bAPK 255\+271\b|\bAPK 255 and 271\b", "app 1.0.31+"),
    (r"\bKMP-only\b", "iOS-app-only"),
    (r"\bAPK\b", "app"),
    (r"\bcom\.quilt\.android (\d\.\d+\.\d+)", r"app \1"),
    (r"\bcom\.quilt\.android\b", "the app"),
    (r"\bversionCode (\d{3})\b", r"\1"),
    (r"\biOS KMP\b", "iOS app"),
    (r"\bKMP\b", "iOS app"),
    (r"\bjadx\b|\bDEX\b", ""),
    (r"\breference/android/\S+|\bprotoaudit\.py\b", ""),
    (r"\bthe (?:the|app) app\b", "the app"),
    (rf"^{_OBF}(?:\$\w+)?(?=\s*(?:$|—|\(|,))\s*—?\s*", ""),  # leading class tag: "jj2 — ..."
    (rf"^(?:{_OBF}/)+{_OBF}\b\s*", ""),  # "wn2 / xn2 / vn2"
    (rf"\s*\((?:{_OBF}\s*/\s*)+{_OBF}\)", ""),  # (wn2 / xn2 / vn2)
    (rf";\s*enum {_OBF} in \d{{3}}\)", ")"),  # (255+; enum ty4 in 271)
    # Android build numbers -> app versions (last, after the class-tag rules above)
    (r"\b271\b", "1.0.33"),
    (r"\b255\b", "1.0.31"),
    (r"\b242\b", "1.0.29"),
    (r"^app$", "called by the Quilt app"),  # RPC tag; the others say "server-only"
    (r"^app proto$", "confirmed against the app"),
    # tidy what the deletions leave behind
    (r"\(\s*app\s*[;,]\s*", "("),
    (r",\s*\)", ")"),
    (r"(?<![\w)\]])\(\s*\)", ""),  # empty parens left by a deletion, not a call like Foo()
    (r"^app\s*[:;.]\s*", ""),  # leftover "app:" — never the start of "append"
    (r":\s*,\s*\.$", "."),
    (r":\s*—", " —"),
    (r"\s+by\s*\.?$", "."),
    (r"\s+;", ";"),
    (r"\.\.$", "."),
]
SUB_RE = [(re.compile(a), b) for a, b in SUBS]
MARKER = re.compile(
    r"APK|\.java|\.kt\b|KMP|jadx|smali|Java enum|ProtocolMessageEnum|\b\d{3}: [a-z]{1,3}\d"
    r"|versionCode|com\.quilt\.android|FIELD_NUMBER|\(C\d{3,5}|\b(?:242|255|271)\b"
)
JUNK = re.compile(r"^[\s,;:()\-—/.+]*$")
# Words a substitution may legitimately drop; anything else lost is reported for review.
_PROVENANCE_WORDS = re.compile(
    r"^(?:APK|APK-confirmed|KMP-only|Android|KMP|iOS|DEX|smali|jadx|Java|enum|class|confirmed|Confirmed|from|in|by|"
    r"the|app|proto|versionCode|com|quilt|android|implements|ProtocolMessageEnum|classes|are|"
    r"\d+|\d+\+|[A-Z0-9_]+_FIELD_NUMBER|[a-z]{1,3}\d\w*|C\d+\w*|[A-Z]{1,3}|\w+\.(?:java|kt|smali))$"
)


def lost_words(before: str, after: str) -> list[str]:
    """Ordinary words present before sanitizing but missing after (likely garbling)."""

    def words(text: str) -> list[str]:
        return [w.strip(".:,;()") for w in re.findall(r"[\w.+-]+", text) if w.strip(".:,;()")]

    words_after = {w.lower() for w in words(after)}
    return [
        w for w in words(before) if w.lower() not in words_after and not _PROVENANCE_WORDS.match(w)
    ]


def clean_comment(text: str) -> str | None:
    out = text
    for r, rep in SUB_RE:
        out = r.sub(rep, out)
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
// payloads (Notification / HomeDatastoreObjectDiff).
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
// NotifierEvent.payload carries a core.protos.home_datastore.Notification (quilt_hds.proto).
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


def _check_lost(name: str, before: str, after: str | None, lost: list[str]) -> None:
    words = lost_words(before, after or "")
    if words:
        lost.append(f"{name}: dropped {words} from {before!r} -> {after!r}")


def sanitize(src: str, report: list[str], name: str, lost: list[str]) -> str:
    src = replace_header(src, name)
    lines = []
    for ln in src.splitlines():
        m = re.match(r"^(\s*)//(.*)$", ln)
        if m:  # whole-line comment
            c = clean_comment(m.group(2).strip())
            if c != m.group(2).strip():
                report.append(f"{name}: {m.group(2).strip()!r} -> {c!r}")
                _check_lost(name, m.group(2).strip(), c, lost)
            if c is None:
                continue
            lines.append(f"{m.group(1)}// {c}" if c else f"{m.group(1)}//")
            continue
        code, sep, com = ln.partition("//")
        if sep and '"' not in code:  # trailing comment
            c = clean_comment(com.strip())
            if c != com.strip():
                report.append(f"{name}: {com.strip()!r} -> {c!r}")
                _check_lost(name, com.strip(), c, lost)
            lines.append(code.rstrip() + (f"  // {c}" if c else ""))
        else:
            lines.append(ln)
    text = "\n".join(lines) + "\n"
    return re.sub(r"\n{3,}", "\n\n", text)


def main() -> None:
    report: list[str] = []
    lost: list[str] = []
    for f in FILES:
        out = sanitize((SRC / f).read_text(), report, f, lost)
        left = [line for line in out.splitlines() if MARKER.search(line)]
        if left:
            sys.exit(f"{f}: provenance left after sanitizing:\n  " + "\n  ".join(left))
        (DST / f).write_text(out)
        print(f"synced {f}")
    if "--report" in sys.argv:
        print("\n".join(report))
    if lost:  # heuristic: review each one; fix the rule if real text was lost
        print("review: sanitizer dropped words that may not be provenance:", file=sys.stderr)
        print("  " + "\n  ".join(lost), file=sys.stderr)


if __name__ == "__main__":
    main()

"""The kaos-lib support window every step checks at start (PRD novelcore/kaos#1147).

The operator publishes the newest kaos-lib release's metadata in the pipeline-context as
`kaosLib.support` (release.json: version, supported, deprecated...). The enhancer passes it to
every step as env KAOS_LIB_SUPPORT; kaos-lib's `kaos_lib.support.check` reads it at step start
and fails the step only when its version is unsupported.
"""
import json

ENV = "KAOS_LIB_SUPPORT"


def support_value(ctx: dict) -> str:
    """KAOS_LIB_SUPPORT for ctx: the JSON, compact; "" when the context carries none."""
    support = (ctx.get("kaosLib") or {}).get("support") if isinstance(ctx.get("kaosLib"), dict) else None
    if not support:
        return ""
    if isinstance(support, str):
        return support.strip()
    return json.dumps(support, sort_keys=True, separators=(",", ":"))

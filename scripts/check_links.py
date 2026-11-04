#!/usr/bin/env python3
"""Check links in every Markdown file: relative files, #anchors, optionally external URLs."""
import pathlib, re, subprocess, sys, time, urllib.request, urllib.error

ROOT = pathlib.Path(__file__).resolve().parent.parent
LINK = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)|!\[[^\]]*\]\(([^)\s]+)\)|<(https?://[^>\s]+)>")
SKIP = ("mailto:", "tel:")


def files():
    out = subprocess.run(["git", "ls-files", "*.md"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    return [ROOT / f for f in out if (ROOT / f).exists()]


def slug(h):
    h = re.sub(r"`|\*|<[^>]+>", "", h).strip().lower()
    h = re.sub(r"[^\w\- ]", "", h)
    return re.sub(r"\s", "-", h)


def anchors(path):
    text = re.sub(r"```.*?```", "", path.read_text(), flags=re.S)
    return {slug(m.group(1)) for m in re.finditer(r"^#{1,6}\s+(.*?)\s*$", text, re.M)}


def strip_code(text):
    return re.sub(r"`[^`\n]*`", "", re.sub(r"```.*?```", "", text, flags=re.S))


def external_ok(url):
    for attempt in range(3):
        for method in ("HEAD", "GET"):
            try:
                req = urllib.request.Request(url, method=method, headers={"User-Agent": "docs-check"})
                with urllib.request.urlopen(req, timeout=20) as r:
                    return r.status < 400
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    time.sleep(3 * (attempt + 1)); break
                if method == "GET":
                    return False
            except Exception:
                if method == "GET":
                    return False
    return True  # 429 stays unknown, not a failure


def main():
    external = "--external" in sys.argv
    bad, n, ext = [], 0, {}
    for f in files():
        text = strip_code(f.read_text())
        for m in LINK.finditer(text):
            target = next(g for g in m.groups() if g)
            if target.startswith(SKIP):
                continue
            n += 1
            if target.startswith("http"):
                ext.setdefault(target, []).append(f)
                continue
            path, _, frag = target.partition("#")
            dest = f if not path else (f.parent / path).resolve()
            if not dest.exists():
                bad.append(f"{f.relative_to(ROOT)}: missing file {target}"); continue
            if frag and dest.suffix == ".md" and frag not in anchors(dest):
                bad.append(f"{f.relative_to(ROOT)}: missing anchor {target}")
    if external:
        for url, fs in sorted(ext.items()):
            if not external_ok(url):
                bad.append(f"{fs[0].relative_to(ROOT)}: external link failed {url}")
    print(f"checked {n} links ({len(ext)} external{'' if external else ', not fetched'}); {len(bad)} broken")
    for b in bad:
        print("  " + b)
    return 1 if bad else 0


sys.exit(main())

#!/usr/bin/env python3
"""Build a Markdown context file (text + images) from an Azure DevOps work item URL.

Usage:
    AZURE_DEVOPS_PAT=<token> python us_context.py <work-item-url> [--out-dir DIR]

The PAT needs the "Work Items (Read)" scope. It is read only from the environment and never
written to disk. Output goes to <out-dir>/US<id>/context.md (+ images/), default out-dir is
.ai/us-context. Standard library only.
"""
import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

API = "7.1"
URL_RE = re.compile(r"https?://dev\.azure\.com/([^/]+)/([^/]+)/_workitems/edit/(\d+)", re.I)
LEGACY_URL_RE = re.compile(r"https?://([^./]+)\.visualstudio\.com/([^/]+)/_workitems/edit/(\d+)", re.I)

RICH_FIELDS = [
    ("System.Description", "Description"),
    ("Microsoft.VSTS.Common.AcceptanceCriteria", "Acceptance criteria"),
    ("Microsoft.VSTS.TCM.ReproSteps", "Repro steps"),
    ("Microsoft.VSTS.TCM.SystemInfo", "System info"),
]


def parse_url(url):
    for rx in (URL_RE, LEGACY_URL_RE):
        m = rx.match(url.strip())
        if m:
            org, project, wid = m.groups()
            return urllib.parse.unquote(org), urllib.parse.unquote(project), int(wid)
    sys.exit("Unsupported URL. Expected https://dev.azure.com/<org>/<project>/_workitems/edit/<id>")


class Client:
    def __init__(self, org, project, pat):
        self.base = f"https://dev.azure.com/{urllib.parse.quote(org)}/{urllib.parse.quote(project)}"
        token = base64.b64encode(f":{pat}".encode()).decode()
        self.headers = {"Authorization": f"Basic {token}"}

    def _open(self, url):
        return urllib.request.urlopen(urllib.request.Request(url, headers=self.headers), timeout=60)

    def get_json(self, url):
        try:
            with self._open(url) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                sys.exit(f"HTTP {e.code}: PAT missing, expired, or without 'Work Items (Read)' scope.")
            if e.code == 404:
                sys.exit("HTTP 404: work item or project not found (check the URL and PAT organization).")
            raise

    def get_bytes(self, url):
        # Attachment URLs are on the same host; never forward the PAT elsewhere.
        if urllib.parse.urlparse(url).netloc.lower() != "dev.azure.com":
            return None, None
        try:
            with self._open(url) as r:
                return r.read(), r.headers.get("Content-Type", "")
        except urllib.error.URLError:
            return None, None


class HtmlToMd(HTMLParser):
    """Small HTML -> Markdown converter for Azure DevOps rich-text fields."""

    def __init__(self, image_resolver):
        super().__init__(convert_charrefs=True)
        self.out, self.lists, self.href, self.resolve = [], [], None, image_resolver
        self.in_pre = False

    def _nl(self, n=1):
        text = "".join(self.out)
        trail = len(text) - len(text.rstrip("\n"))
        self.out.append("\n" * max(0, n - trail))

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("p", "div", "section"):
            self._nl(2)
        elif tag == "br":
            self.out.append("\n")
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._nl(2)
            self.out.append("#" * min(6, int(tag[1]) + 2) + " ")
        elif tag in ("ul", "ol"):
            self.lists.append([tag, 0])
            self._nl(1)
        elif tag == "li":
            self._nl(1)
            depth = max(0, len(self.lists) - 1)
            if self.lists and self.lists[-1][0] == "ol":
                self.lists[-1][1] += 1
                marker = f"{self.lists[-1][1]}."
            else:
                marker = "-"
            self.out.append("  " * depth + marker + " ")
        elif tag in ("strong", "b"):
            self.out.append("**")
        elif tag in ("em", "i"):
            self.out.append("_")
        elif tag == "code":
            self.out.append("`")
        elif tag == "pre":
            self.in_pre = True
            self._nl(2)
            self.out.append("```\n")
        elif tag == "a":
            self.href = a.get("href")
            self.out.append("[")
        elif tag == "img":
            src = a.get("src")
            if src:
                self.out.append(f"![{a.get('alt') or 'image'}]({self.resolve(src)})")
        elif tag == "tr":
            self._nl(1)
            self.out.append("| ")
        elif tag in ("td", "th"):
            pass

    def handle_endtag(self, tag):
        if tag in ("p", "div", "section", "h1", "h2", "h3", "h4", "h5", "h6"):
            self._nl(2)
        elif tag in ("ul", "ol"):
            if self.lists:
                self.lists.pop()
            self._nl(1 if self.lists else 2)
        elif tag in ("strong", "b"):
            self.out.append("**")
        elif tag in ("em", "i"):
            self.out.append("_")
        elif tag == "code":
            self.out.append("`")
        elif tag == "pre":
            self.in_pre = False
            self._nl(1)
            self.out.append("```\n")
        elif tag == "a":
            self.out.append(f"]({self.href})" if self.href else "]")
            self.href = None
        elif tag in ("td", "th"):
            self.out.append(" | ")

    def handle_data(self, data):
        self.out.append(data if self.in_pre else re.sub(r"\s+", " ", data))

    def markdown(self):
        text = "".join(self.out)
        text = re.sub(r"[ \t]+\n", "\n", text)
        return re.sub(r"\n{3,}", "\n\n", text).strip()


def slugify(text, max_words=5):
    words = re.findall(r"[a-z0-9]+", re.sub(r"[^\x00-\x7f]", lambda m: _fold(m.group()), text.lower()))
    return "-".join(words[:max_words]) or "change"


def _fold(ch):
    import unicodedata
    return unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url")
    ap.add_argument("--out-dir", default=".ai/us-context")
    args = ap.parse_args()

    pat = os.environ.get("AZURE_DEVOPS_PAT")
    if not pat:
        sys.exit("Set AZURE_DEVOPS_PAT (Work Items: Read) in the environment. It is never stored.")

    org, project, wid = parse_url(args.url)
    client = Client(org, project, pat)
    item = client.get_json(f"{client.base}/_apis/wit/workitems/{wid}?$expand=all&api-version={API}")
    f = item.get("fields", {})

    out = Path(args.out_dir) / f"US{wid}"
    img_dir = out / "images"
    out.mkdir(parents=True, exist_ok=True)
    saved = {}

    def save_image(src):
        """Download an authenticated image once; return the relative Markdown path or the original URL."""
        if src in saved:
            return saved[src]
        data, ctype = client.get_bytes(src)
        if not data:
            saved[src] = src
            return src
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(src).query)
        name = (qs.get("fileName") or [urllib.parse.urlparse(src).path.rsplit("/", 1)[-1]])[0]
        name = re.sub(r"[^\w.\-]", "_", name) or "image"
        if "." not in name and ctype.startswith("image/"):
            name += "." + ctype.split("/")[1].split(";")[0]
        img_dir.mkdir(parents=True, exist_ok=True)
        target = img_dir / f"{len(saved) + 1:02d}-{name}"
        target.write_bytes(data)
        saved[src] = f"images/{target.name}"
        return saved[src]

    def to_md(html):
        p = HtmlToMd(save_image)
        p.feed(html)
        return p.markdown()

    title = f.get("System.Title", f"Work item {wid}")
    wtype = f.get("System.WorkItemType", "")
    assigned = f.get("System.AssignedTo")
    assigned = assigned.get("displayName") if isinstance(assigned, dict) else assigned
    branch_type = "fix" if wtype.lower() == "bug" else "feature"
    slug = slugify(title)

    lines = [
        f"# US{wid} — {title}",
        "",
        f"- **Type:** {wtype}",
        f"- **State:** {f.get('System.State', '')}",
        f"- **Area:** {f.get('System.AreaPath', '')}",
        f"- **Iteration:** {f.get('System.IterationPath', '')}",
        f"- **Assigned to:** {assigned or '—'}",
        f"- **Tags:** {f.get('System.Tags', '') or '—'}",
        f"- **Source:** {args.url}",
        f"- **Suggested branch:** `{branch_type}/US{wid}-{slug}`",
        "",
    ]
    for key, label in RICH_FIELDS:
        if f.get(key):
            lines += [f"## {label}", "", to_md(f[key]), ""]

    related = []
    for rel in item.get("relations") or []:
        attrs, url = rel.get("attributes", {}), rel.get("url", "")
        if rel.get("rel") == "AttachedFile":
            name = attrs.get("name", "attachment")
            if re.search(r"\.(png|jpe?g|gif|bmp|webp|svg)$", name, re.I):
                path = save_image(url + ("&" if "?" in url else "?") + "fileName=" + urllib.parse.quote(name))
                related.append(f"- Attachment: ![{name}]({path})")
            else:
                related.append(f"- Attachment (not downloaded): {name} — {url}")
        elif rel.get("rel", "").startswith("System.LinkTypes") or rel.get("rel") == "ArtifactLink":
            related.append(f"- {attrs.get('name') or rel.get('rel')}: {url}")
    if related:
        lines += ["## Attachments and links", ""] + related + [""]

    comments = client.get_json(
        f"{client.base}/_apis/wit/workItems/{wid}/comments?api-version=7.1-preview.4"
    ).get("comments", [])
    if comments:
        lines += ["## Discussion", ""]
        for c in sorted(comments, key=lambda c: c.get("createdDate", "")):
            who = (c.get("createdBy") or {}).get("displayName", "unknown")
            lines += [f"**{who}** ({c.get('createdDate', '')[:10]}):", "", to_md(c.get("text", "")), ""]

    (out / "context.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"Wrote {out / 'context.md'} ({len(saved)} image(s))")
    print(f"Suggested branch: {branch_type}/US{wid}-{slug}")


if __name__ == "__main__":
    main()

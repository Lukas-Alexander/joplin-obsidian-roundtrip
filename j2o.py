# -*- coding: utf-8 -*-
"""
j2o.py — Lossless Bi-directional Joplin ⇄ Obsidian Sync-Engine

Copyright (C) 2026 Lukas Alexander <https://github.com/Lukas-Alexander>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU General Public License for more details.
"""

"""
OVERVIEW
A standalone utility for seamless, lossless round-tripping of notes between 
Joplin's raw Markdown/Frontmatter export and Obsidian vault structures. 
Built for users who require platform flexibility without compromising 
note integrity, attachment handling, or folder metadata.

KEY FEATURES
- Automated Detection: Recognizes Joplin-native structures (_resources, _folder.yml).
- Lossless Sync: Maintains metadata parity via `joplin_raw_manifest` in `_index.md`.
- Metadata Persistence: Preserves folder icons (Emoji/DataURL) across platforms.
- OS-Agnostic Sanitization: Profiles for NTFS, exFAT, APFS, and cloud-synced filesystems.
- Attachment Integrity: Implements content-hashing to prevent duplicate assets.
- Structural Fidelity: Handles empty-folder placeholders for consistent imports.
- Drift Remediation: Dedicated cleanup mode to resolve state discrepancies.

PROJECT LINKS
Repository: https://github.com/Lukas-Alexander

ACKNOWLEDGEMENTS & TRANSPARENCY
AI tools were leveraged for:
- Logic verification and test coverage.
- Complex regex construction and optimization.
- Documentation and code-commenting for maintainability.
- Formatting of technical output and project documentation.
"""
import os, re, sys, yaml, shutil, hashlib, uuid, argparse, mimetypes
from urllib.parse import unquote

DEFAULT_ATTACHMENT_DIR = "_resources"
INDEX_FILE_NAME = "_index.md"
INDEX_FILE_NAME_HIDDEN = ".index.md"
SEPARATOR = " - "

FS_PROFILES = {
    "ntfs":    {"max_path": 255, "max_total": 240, "illegal": r'[\/\\:\*\?"\<\|\>\(\)]'},
    "exfat":   {"max_path": 255, "max_total": 240, "illegal": r'[\/\\:\*\?"\<\|\>]'},
    "linux":   {"max_path": 255, "max_total": 4096, "illegal": r'[\/]'},
    "zfs":     {"max_path": 255, "max_total": 4096, "illegal": r'[\/]'},
    "apfs":    {"max_path": 255, "max_total": 1024, "illegal": r'[\/\:]'},
    "hfs":     {"max_path": 255, "max_total": 1024, "illegal": r'[\/\:]'},
    "cloud":   {"max_path": 140, "max_total": 220, "illegal": r'[\/\\:\*\?"\<\|\>\.\~]'}
}

SANITIZE_PROFILES = {
    "win":     r'[\/\\:\*\?"\<\|\>]',  # Retain parenthesis to keep folder grouping intact
    "mac":     r'[\/\:]',
    "ios":     r'[\/\:]',
    "android": r'[\/\\:\*\?"\<\|\>]',
    "linux":   r'[\/]',
    "cloud":   r'[\/\\:\*\?"\<\|\>\.\~\#\%]',
}

EPILOG_TEXT = """
ARCHITECTURAL FLOW & BEHAVIOR:
  to-obsidian:
    Auto-detects Joplin raw exports (looks for _resources + _folder.yml
    footprint). When detected, reads each folder's _folder.yml manifest
    and embeds the COMPLETE raw manifest into the generated _index.md
    file (under the 'joplin_raw_manifest' frontmatter key). This makes
    the _index.md a lossless container for round-tripping back to Joplin.

    With --icons, folder paths on disk are prefixed visually
    (e.g. "📂 - My Folder"). Without --icons, disk paths stay clean
    but the icon info is STILL preserved inside _index.md for later
    restoration.

  to-joplin:
    Re-compiles your Obsidian vault to a Joplin-ingestible structure.
    Folder paths on disk are STRIPPED of any emoji prefixes (matching
    Joplin's native raw-export convention). A fresh _folder.yml is
    written inside every subfolder, using the embedded joplin_raw_manifest
    when available (lossless restore) or reconstructing one from the
    available metadata.

    With --icons, icon entries are preserved in the generated _folder.yml.
    Without --icons, the icon entries are dropped, giving a clean slate.

  cleanup:
    Remediation pass for files that drifted through earlier script versions
    or other tools. Walks the input tree and writes a normalized copy to
    output_dir. Mode-agnostic — works on Obsidian vaults, Joplin export
    folders, or any markdown collection. Does NOT touch folder structure;
    only fixes file content.

    Specifically:
      * Removes 'id:' field from front matter. This is the only fix that
        addresses an actual functional bug: a present 'id:' makes Joplin's
        importer reject the YAML block and render it as visible body text.
      * Normalizes timestamps from '+00:00' offset form back to 'Z' suffix
        (Joplin's native format). Cosmetic — Joplin tolerates both.
      * Strips UTF-8 BOM if present at file start.
      * Normalizes CRLF line endings to LF.
      * Strips trailing whitespace on each line.

    Default behavior is to write to output_dir, leaving the source untouched.
    Pass --in-place to overwrite files in input_dir directly (no output_dir
    argument needed in that case).

EXAMPLES:
  1. Joplin -> Obsidian (preserve icons visually on disk):
     python %(prog)s to-obsidian "Joplin Business" "Business" --icons

  2. Joplin -> Obsidian (clean disk paths, icons still preserved in _index.md):
     python %(prog)s to-obsidian "Joplin Business" "Business"

  3. Obsidian -> Joplin (lossless round-trip with icons restored):
     python %(prog)s to-joplin "Business" "Joplin Imported" --icons

  4. Cross-platform safe (Windows / NTFS, with sanitisation):
     python %(prog)s to-obsidian "Joplin Business" "Business" -fs ntfs -sanitize win --icons

  5. Weave semantic [[wikilinks]] across the vault:
     python %(prog)s to-obsidian "Joplin Business" "Business" --icons --semantic-graph

  6. Cleanup drift from old script versions (safe, output to new directory):
     python %(prog)s cleanup "My Vault" "My Vault Cleaned"

  7. Cleanup in place (overwrite source — make a backup first!):
     python %(prog)s cleanup "My Vault" --in-place

  8. Hash attachments for cloud-sync safety:
     python %(prog)s to-obsidian "Joplin" "Cloud Vault" --icons --hash-attachments -fs cloud

  9. Hide folder manifests from Obsidian's file explorer:
     python %(prog)s to-obsidian "Joplin" "Vault" --icons --hide-manifests

  10. Obsidian -> Joplin, preserving empty placeholder folders:
      python %(prog)s to-joplin "Vault" "Joplin Import" --icons --preserve-empty-dirs

  11. Non-destructive orphan scan (moves to _orphaned_resources/ for review):
      python %(prog)s cleanup "My Vault" --in-place --clean

  12. Destructive orphan scan (delete orphans permanently):
      python %(prog)s cleanup "My Vault" --in-place --clean-purge

LICENSE & PROJECT:
  Copyright (C) 2026 Lukas Alexander
  Licensed under the GNU General Public License v2.0 (or later).
  Source & issue tracker: https://github.com/Lukas-Alexander
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def generate_joplin_id():
    return uuid.uuid4().hex


def parse_front_matter(content):
    """Robust parser that isolates YAML block from markdown body content.

    Defensively strips:
      - UTF-8 BOM (U+FEFF) — some editors/exporters prepend it.
      - Any leading whitespace including non-breaking space (U+00A0) which
        Python's str.lstrip() *does* strip, but BOM it does not.
      - Carriage returns left over from CRLF normalization.

    Without these defences, an invisible byte before the opening '---' makes
    Joplin's (and most parsers') front-matter detection silently fail, causing
    the YAML block to render as visible note body on import.
    """
    # Strip BOM if present at the very start
    if content.startswith('\ufeff'):
        content = content[1:]
    # Normalize line endings, then strip leading whitespace
    content = content.replace('\r\n', '\n').replace('\r', '\n').lstrip()
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            try:
                meta = yaml.safe_load(parts[1]) or {}
                body = parts[2].lstrip()
                return meta, body
            except yaml.YAMLError:
                pass
    return {}, content


def parse_front_matter_raw(content):
    """Fidelity-preserving parser: returns (raw_yaml_text, body).

    Unlike parse_front_matter, this does NOT load the YAML into Python
    objects — it keeps the original scalar text exactly as authored. Use
    this when you need to round-trip a note without normalizing timestamps,
    losing float precision, or re-quoting strings.
    """
    if content.startswith('\ufeff'):
        content = content[1:]
    content = content.replace('\r\n', '\n').replace('\r', '\n').lstrip()
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            return parts[1], parts[2].lstrip()
    return "", content


_FM_KEY_RE = re.compile(r'^([A-Za-z_][\w\-]*)\s*:\s*(.*)$')


def _yaml_quote_if_needed(s):
    """Wrap a string in single quotes if it contains any character that would
    confuse a naïve YAML scalar reader (colons, leading dash, leading special)."""
    if not s:
        return "''"
    needs_quote = (
        ':' in s or s.lstrip() != s or s.rstrip() != s
        or s.startswith(('-', '?', '!', '&', '*', '|', '>', '{', '[', '#', '@', '`'))
        or s.lower() in {'yes', 'no', 'true', 'false', 'on', 'off', 'null', '~'}
    )
    if not needs_quote:
        return s
    return "'" + s.replace("'", "''") + "'"


def patch_raw_front_matter(raw_yaml, updates):
    """Apply targeted key=value edits to raw front-matter text in place,
    preserving every other byte (timestamps, float precision, comments).

    - `raw_yaml` is the text BETWEEN the opening and closing '---' markers
      (i.e. what parse_front_matter_raw returns as the first element).
    - `updates` is a dict of {key: new_string_value} for keys to overwrite.
      Existing keys are replaced inline; new keys are appended at the end.
    - Keys absent from `updates` are left exactly as they were.

    Only handles flat top-level scalar keys, which covers every Joplin
    front-matter field (title, created, updated, latitude, longitude,
    altitude, id, source, source_url, todo_completed, etc).
    """
    lines = raw_yaml.split('\n')
    seen = set()
    out_lines = []
    for line in lines:
        m = _FM_KEY_RE.match(line)
        if m and m.group(1) in updates:
            key = m.group(1)
            new_val = updates[key]
            out_lines.append(f"{key}: {new_val}")
            seen.add(key)
        else:
            out_lines.append(line)
    for key, new_val in updates.items():
        if key not in seen:
            # Insert before any trailing blank lines
            while out_lines and out_lines[-1].strip() == "":
                out_lines.pop()
            out_lines.append(f"{key}: {new_val}")
            out_lines.append("")
    return '\n'.join(out_lines)


def write_front_matter(meta, body):
    """Cleanly serialize front matter without leakage into body space.

    - Ensures the title is a single line (collapses internal newlines).
    - Preserves key order using sort_keys=False.
    - Ensures a blank line between frontmatter and body.
    """
    if not meta:
        return body.lstrip()
    if "title" in meta and isinstance(meta["title"], str):
        meta["title"] = re.sub(r'\s+', ' ', meta["title"]).strip()
    # width=10000 prevents PyYAML from line-wrapping long values, which would
    # break Joplin's front-matter parser and cause the YAML block to render as
    # visible text inside the note body after a round-trip.
    yaml_str = yaml.dump(meta, default_flow_style=False, allow_unicode=True,
                         sort_keys=False, width=10000)
    return f"---\n{yaml_str}---\n\n{body.lstrip()}"


def assemble_note(raw_yaml, body, updates=None):
    """Re-assemble a note's full text from (raw_yaml, body), optionally
    patching specific keys via `updates`. Preserves YAML byte-fidelity for
    untouched keys. Guarantees the file begins with the literal '---' so
    Joplin's front-matter parser recognizes it on import.

    If raw_yaml is empty/missing, falls back to synthesizing minimal front
    matter from `updates` (or no front matter at all if updates is empty).
    """
    body = (body or "").lstrip()
    if raw_yaml:
        yaml_block = patch_raw_front_matter(raw_yaml, updates or {})
        # raw_yaml usually starts with a newline (since '---' was on its own line);
        # normalize to exactly one leading newline and one trailing newline.
        yaml_block = '\n' + yaml_block.strip('\n') + '\n'
        return f"---{yaml_block}---\n\n{body}"
    if updates:
        return write_front_matter(updates, body)
    return body


def print_progress(current, total, prefix='Progress', suffix='Complete', bar_length=40):
    percent = float(current) / total
    hashes = '#' * int(round(percent * bar_length))
    spaces = ' ' * (bar_length - len(hashes))
    sys.stdout.write(f"\r{prefix}: [{hashes}{spaces}] {int(round(percent * 100))}% ({current}/{total}) {suffix}")
    sys.stdout.flush()


def is_emoji_prefixed(name):
    """Strict detector: matches only the canonical SEPARATOR pattern we emit.
    Used when round-tripping our own output."""
    if not name or SEPARATOR not in name:
        return False
    return ord(name[0]) > 127


def split_emoji_prefix(name):
    """Strict splitter, paired with is_emoji_prefixed."""
    parts = name.split(SEPARATOR, 1)
    return parts[0], parts[1].strip()


# Permissive icon-extraction for arbitrary inbound vaults.
# Matches a leading run of non-ASCII characters (the "icon") followed by an
# optional delimiter (whitespace, dash, em-dash, pipe, underscore, colon,
# bullet) and then the rest of the name. Variation Selector-16 (U+FE0F) and
# Zero-Width Joiner (U+200D) are kept inside the icon run so multi-codepoint
# emoji like 🧑🏼‍🎓 and 🗺️ survive intact.
_INBOUND_ICON_PATTERN = re.compile(
    r'^(?P<icon>[^\x00-\x7F\u200D\uFE0F]+(?:[\u200D\uFE0F][^\x00-\x7F\u200D\uFE0F]*)*[\uFE0F\u200D]?)'
    r'(?P<delim>[\s\-\u2013\u2014|_:•·]*)'
    r'(?P<rest>.*)$'
)


def extract_inbound_icon(name):
    """Try to detect an icon-prefixed folder name from any inbound vault style.

    Returns (icon, clean_name) if a leading non-ASCII icon run is found, else
    (None, name). The clean_name is what should appear as Joplin's `title`,
    and `icon` is what should populate `icon: {type: emoji, emoji: <icon>}`.

    Examples this handles:
        "📂 - Folder Name"   -> ("📂",   "Folder Name")
        "📂 — Folder Name"   -> ("📂",   "Folder Name")    # em-dash
        "📂 | Folder Name"   -> ("📂",   "Folder Name")
        "📂 Folder Name"     -> ("📂",   "Folder Name")
        "📂Folder Name"      -> ("📂",   "Folder Name")    # no delimiter
        "🗺️ - Maps"          -> ("🗺️",  "Maps")           # VS-16
        "🧑🏼‍🎓 - Student"     -> ("🧑🏼‍🎓", "Student")        # ZWJ sequence
        "001 - Numbered"     -> (None,   "001 - Numbered") # ASCII = leave alone
        "Plain Folder"       -> (None,   "Plain Folder")
    """
    if not name:
        return None, name
    # ASCII first char -> not an icon, leave the name fully alone.
    if ord(name[0]) < 128:
        return None, name
    m = _INBOUND_ICON_PATTERN.match(name)
    if not m:
        return None, name
    icon = m.group("icon")
    rest = m.group("rest").strip()
    if not icon or not rest:
        # Either no icon part or no remaining name; treat as not icon-prefixed
        # to avoid losing data.
        return None, name
    return icon, rest


def apply_sanitization(filename, illegal_regex, max_len=180):
    name, ext = os.path.splitext(filename)
    clean_name = re.sub(illegal_regex, '', name).strip(" .")
    if len(clean_name) > max_len:
        clean_name = clean_name[:max_len]
    return f"{clean_name}{ext}" if clean_name else f"note_{generate_joplin_id()[:8]}{ext}"


# ---------------------------------------------------------------------------
# Attachment naming & dedup helpers
# ---------------------------------------------------------------------------

# Extensions we recognize as attachments. Lookup is case-insensitive.
ATTACHMENT_EXTS = {
    '.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.bmp', '.tiff', '.ico',
    '.mp4', '.webm', '.mov', '.mkv', '.avi', '.mp3', '.wav', '.ogg', '.m4a', '.flac',
    '.pdf', '.docx', '.doc', '.xlsx', '.xls', '.pptx', '.ppt', '.odt', '.ods', '.odp',
    '.txt', '.csv', '.tsv', '.json', '.xml', '.yaml', '.yml',
    '.zip', '.tar', '.gz', '.7z', '.rar',
}


def file_content_hash(path, algorithm='md5'):
    """Compute hex hash of a file's bytes. Reads in chunks for large files."""
    h = hashlib.new(algorithm)
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def hash_length_for_fs(fs_cfg=None):
    """Determine a sensible hash-string length given the target filesystem.

    Pragmatic policy:
      - No FS profile given      -> md5 (32 hex chars)
      - max_path <= 64           -> md5 (32 hex chars)   [exotic / very tight]
      - max_path <= 200          -> sha224 (56 hex chars)
      - max_path <= 1024         -> sha256 (64 hex chars)
      - Anything beyond          -> sha256 (64 hex chars) -- no benefit going wider
    """
    if not fs_cfg:
        return 'md5', 32
    max_path = fs_cfg.get('max_path', 255)
    if max_path <= 64:
        return 'md5', 32
    if max_path <= 200:
        return 'sha224', 56
    return 'sha256', 64


def hash_for_attachment(path, fs_cfg=None):
    """Return the hex hash of a file's content, sized appropriately for the
    target filesystem."""
    algorithm, length = hash_length_for_fs(fs_cfg)
    full = file_content_hash(path, algorithm)
    return full[:length]


def detect_extension_from_bytes(path):
    """Best-effort file-type detection without external deps.

    Strategy:
      1. mimetypes.guess_extension() based on path (cheap).
      2. Magic-byte sniff for common formats we care about.
      3. Return None if we can't tell.
    """
    # Try mimetypes first (uses the file extension if it has one)
    mime, _ = mimetypes.guess_type(path)
    if mime:
        ext = mimetypes.guess_extension(mime)
        if ext:
            return ext

    # Magic-byte fallback for common attachment formats
    try:
        with open(path, 'rb') as f:
            head = f.read(16)
    except Exception:
        return None
    if not head:
        return None
    # PNG
    if head.startswith(b'\x89PNG\r\n\x1a\n'):
        return '.png'
    # JPEG
    if head.startswith(b'\xff\xd8\xff'):
        return '.jpg'
    # GIF
    if head.startswith(b'GIF87a') or head.startswith(b'GIF89a'):
        return '.gif'
    # WebP
    if head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return '.webp'
    # PDF
    if head.startswith(b'%PDF-'):
        return '.pdf'
    # ZIP family (also docx, xlsx, pptx, odt — extension matters more there)
    if head.startswith(b'PK\x03\x04') or head.startswith(b'PK\x05\x06'):
        return '.zip'
    # SVG (text-based, check for opening tag)
    if b'<svg' in head or b'<?xml' in head:
        return '.svg'
    return None


def resolve_md_name(alt_text, current_path, fs_cfg=None, sanitize_regex=None):
    """For --use-md-name mode: derive the target filename from the markdown
    alt text, falling back to the current filename when alt is missing.

    Rules (in order):
      1. If alt is empty -> use current filename basename.
      2. If alt already equals current filename basename -> no-op (return current).
      3. If alt has no extension -> detect from file bytes and append.
      4. Sanitize for the target FS profile.
    """
    current_basename = os.path.basename(current_path)
    if not alt_text or not alt_text.strip():
        return current_basename

    alt_text = alt_text.strip()
    if alt_text == current_basename:
        return current_basename

    # Does alt already have a recognizable extension?
    _, alt_ext = os.path.splitext(alt_text)
    if not alt_ext or alt_ext.lower() not in ATTACHMENT_EXTS:
        detected = detect_extension_from_bytes(current_path)
        if detected:
            alt_text = alt_text + detected
        else:
            # Couldn't detect; just append the original extension
            _, orig_ext = os.path.splitext(current_basename)
            alt_text = alt_text + orig_ext

    # Sanitize
    if sanitize_regex:
        alt_text = apply_sanitization(alt_text, sanitize_regex)
    elif fs_cfg:
        alt_text = apply_sanitization(alt_text, fs_cfg['illegal'])

    return alt_text or current_basename


def disambiguate_filename(target_name, dest_dir, src_path, dedup=True):
    """Resolve filename collisions in dest_dir, Obsidian-style.

    Returns the final filename to use. Behaviour:
      - If <dest_dir>/<target_name> doesn't exist, return target_name.
      - If it exists AND contents match src_path AND dedup is on,
        return target_name (caller can skip the copy; reference is shared).
      - If it exists with different content (or dedup off), append " 1",
        " 2", ... until a free slot is found, matching Obsidian's pattern.
    """
    target_path = os.path.join(dest_dir, target_name)
    if not os.path.exists(target_path):
        return target_name

    # File exists at target. Compare content if dedup is on.
    if dedup:
        try:
            existing_hash = file_content_hash(target_path)
            new_hash = file_content_hash(src_path)
            if existing_hash == new_hash:
                # Identical content - safe to share
                return target_name
        except Exception:
            pass  # fall through to disambiguation

    # Conflict: pick a new name with " N" suffix (Obsidian convention)
    stem, ext = os.path.splitext(target_name)
    n = 1
    while True:
        candidate = f"{stem} {n}{ext}"
        candidate_path = os.path.join(dest_dir, candidate)
        if not os.path.exists(candidate_path):
            return candidate
        if dedup:
            try:
                if file_content_hash(candidate_path) == file_content_hash(src_path):
                    return candidate
            except Exception:
                pass
        n += 1
        if n > 9999:
            # Sanity: give up and use a uuid suffix
            return f"{stem} {uuid.uuid4().hex[:8]}{ext}"


def is_joplin_export(src_dir):
    """Heuristic auto-detection: a Joplin raw export contains both a
    _resources (or resources) directory AND at least one _folder.yml file."""
    res_exists = (os.path.exists(os.path.join(src_dir, "_resources")) or
                  os.path.exists(os.path.join(src_dir, "resources")))
    if not res_exists:
        return False
    for root, dirs, files in os.walk(src_dir):
        if "_folder.yml" in files:
            return True
    return False


def map_joplin_folder_manifests(src_dir):
    """Ingest the raw local Joplin _folder.yml contents for cross-referencing."""
    folder_manifests = {}
    for root, dirs, files in os.walk(src_dir):
        if "_folder.yml" in files:
            yml_path = os.path.join(root, "_folder.yml")
            try:
                with open(yml_path, "r", encoding="utf-8", errors="replace") as f:
                    meta = yaml.safe_load(f)
                    if meta:
                        folder_manifests[os.path.abspath(root)] = meta
            except Exception:
                pass
    return folder_manifests


# ---------------------------------------------------------------------------
# Semantic graph weaver
# ---------------------------------------------------------------------------

def build_vocabulary_map(dest_dir):
    vocab = {}
    for root, dirs, files in os.walk(dest_dir):
        for file in files:
            if file.endswith('.md') and file not in (INDEX_FILE_NAME, INDEX_FILE_NAME_HIDDEN):
                title = os.path.splitext(file)[0]
                if len(title) > 3 and not title.isdigit():
                    vocab[title.lower()] = title
    return sorted(vocab.keys(), key=len, reverse=True), vocab


def weave_semantic_links(note_body, sorted_titles, vocab_map, current_note_title):
    protected_blocks = []

    def protect(match):
        protected_blocks.append(match.group(0))
        return f"___PROTECTED_BLOCK_{len(protected_blocks)-1}___"

    modified_body = re.sub(
        r'(```[\s\S]*?```|`[^`]+`|\[\[.*?\]\]|!\[\[.*?\]\])',
        protect, note_body
    )

    for title_lower in sorted_titles:
        exact_case_target = vocab_map[title_lower]
        if exact_case_target.lower() == current_note_title.lower():
            continue
        pattern = re.compile(rf'\b({re.escape(title_lower)})\b', re.IGNORECASE)

        def replace_with_link(match):
            matched_text = match.group(1)
            link = f"[[{exact_case_target}|{matched_text}]]"
            protected_blocks.append(link)
            return f"___PROTECTED_BLOCK_{len(protected_blocks)-1}___"

        modified_body = pattern.sub(replace_with_link, modified_body)

    for idx, block in enumerate(protected_blocks):
        modified_body = modified_body.replace(f"___PROTECTED_BLOCK_{idx}___", block)
    return modified_body


def de_weave_semantic_links(note_body):
    """Convert text-mode wikilinks back to plain text. Embeds (![[file]])
    are LEFT ALONE — they're attachment references and must survive to be
    rewritten by the attachment-handling pass that follows."""
    # (?<!!) is a negative lookbehind: don't match if preceded by '!'
    clean_body = re.sub(r'(?<!!)\[\[[^\]|]+\|([^\]]+)\]\]', r'\1', note_body)
    return re.sub(r'(?<!!)\[\[([^\]|]+)\]\]', r'\1', clean_body)


# ---------------------------------------------------------------------------
# Joplin -> Obsidian
# ---------------------------------------------------------------------------

def convert_to_obsidian(src_dir, dest_dir, resource_folder_name, fs_cfg, sanitize_regex,
                        use_icons, run_semantic_graph,
                        hash_attachments=False, use_md_name=False, no_dedup=False,
                        hide_manifests=False):
    """Convert a Joplin raw export to an Obsidian-friendly vault.

    Attachment-naming flags (same semantics as to-joplin):
      hash_attachments: rename every attachment to <hash>.<ext>; hash length
        follows -fs profile (md5/32 if none given).
      use_md_name: rename each attachment to the alt text of its FIRST
        reference in the source notes. Useful for cloud sync where
        human-readable filenames matter more than original Joplin names.
      no_dedup: keep cross-note copies separate via " N" suffixes even when
        content is identical (Obsidian-native paste behaviour).

    hash_attachments and use_md_name are mutually exclusive (caller enforces).
    """
    print("Auto-inspecting source environment...")
    joplin_res_dir = os.path.join(src_dir, "_resources")
    if not os.path.exists(joplin_res_dir):
        alt_dir = os.path.join(src_dir, "resources")
        if os.path.exists(alt_dir):
            joplin_res_dir = alt_dir

    joplin_mode = is_joplin_export(src_dir)
    if joplin_mode:
        print("--> Confirmed: Joplin raw export detected (auto-switched to Joplin mode).")
    else:
        print("--> Generic markdown directory tree detected.")

    joplin_manifests = map_joplin_folder_manifests(src_dir) if joplin_mode else {}

    md_files = [
        os.path.join(r, f)
        for r, d, fs in os.walk(src_dir)
        for f in fs
        if f.endswith(".md") and "_resources" not in r and "resources" not in r
    ]
    total_files = len(md_files)
    if total_files == 0:
        return print("No markdown notes found.")

    os.makedirs(dest_dir, exist_ok=True)

    # ----- Pre-pass for --use-md-name: walk every source note's body and
    # record the FIRST alt text we see for each referenced filename. The
    # bulk-copy loop will then know what target name to use for each file.
    md_name_lookup = {}  # source_basename -> first alt text seen
    if use_md_name:
        for md_path in md_files:
            try:
                with open(md_path, "r", encoding="utf-8", errors="replace") as f:
                    body = f.read()
            except Exception:
                continue
            for m in re.finditer(
                    r'!\[(?P<alt>[^\]]*)\]\((?P<path>(?:(?!!\[)[^)])*?)(?:\s+"[^"]*")?\)',
                    body):
                alt = m.group("alt").strip()
                path = unquote(m.group("path"))
                base = os.path.basename(path)
                if base and base not in md_name_lookup and alt:
                    md_name_lookup[base] = alt

    # ----- Bulk-copy _resources/ to the vault root. Folder *depth* is
    # preserved by our conversion (only folder *names* change), so the
    # relative paths in note bodies remain valid as long as the resource
    # files land at the same root-level _resources/ location.
    vault_res_dir = os.path.join(dest_dir, "_resources")
    resource_renames = {}  # original_name -> final_name (drives body rewrites)
    if os.path.isdir(joplin_res_dir):
        os.makedirs(vault_res_dir, exist_ok=True)
        copied = 0
        for fname in os.listdir(joplin_res_dir):
            src_attach = os.path.join(joplin_res_dir, fname)
            if not os.path.isfile(src_attach):
                continue

            # Decide on the target filename based on flags. Priority order:
            # 1. hash_attachments wins absolutely (mutex with use_md_name).
            # 2. use_md_name if we have a recorded alt text for this file.
            # 3. Plain pass-through with sanitization.
            if hash_attachments:
                h = hash_for_attachment(src_attach, fs_cfg)
                ext = os.path.splitext(fname)[1]
                target_name = f"{h}{ext}"
            elif use_md_name and fname in md_name_lookup:
                target_name = resolve_md_name(
                    md_name_lookup[fname], src_attach, fs_cfg, sanitize_regex)
            else:
                target_name = fname

            # Apply sanitization regardless of naming mode (illegal chars
            # in the chosen name still need scrubbing).
            if sanitize_regex:
                target_name = apply_sanitization(target_name, sanitize_regex)
            elif fs_cfg:
                target_name = apply_sanitization(target_name, fs_cfg['illegal'])

            # Disambiguate against anything already in the destination.
            # With no_dedup, force a " N" suffix; otherwise reuse identical
            # content. Bulk-copy is a single pass, so collisions here mean
            # two source files want the same target name (e.g. two distinct
            # files that hashed to the same name — should not happen with
            # content hashing, but possible with --use-md-name when two
            # source files first-appeared with the same alt text).
            final_name = disambiguate_filename(
                target_name, vault_res_dir, src_attach, dedup=not no_dedup)

            if final_name != fname:
                resource_renames[fname] = final_name

            dst_attach = os.path.join(vault_res_dir, final_name)
            # Skip the copy when dedup already pointed us at an identical file.
            if not os.path.exists(dst_attach):
                try:
                    shutil.copy2(src_attach, dst_attach)
                    copied += 1
                except Exception as e:
                    print(f"  [warn] could not copy resource {fname}: {e}")
            else:
                copied += 1  # counted as handled
        if copied:
            mode_label = ""
            if hash_attachments:
                mode_label = " (content-hashed)"
            elif use_md_name:
                mode_label = " (md-named)"
            print(f"--> Copied {copied} attachment(s) to {vault_res_dir}{mode_label}")

    # ----- Empty-directory pre-creation pass.
    # Joplin's raw export uses _folder.yml as the "this folder exists" marker.
    # Some folders contain ONLY a _folder.yml (placeholder folders like Inbox,
    # Outbox, an empty year-bucket, etc.) — they have no .md notes inside.
    # The per-note loop below only creates destination folders as a side effect
    # of writing notes, so these placeholder folders would silently vanish on
    # `to-obsidian`. We pre-create them here using the same naming rules the
    # note loop would apply, so the folder hierarchy round-trips intact.
    def _compute_dest_segment(src_part, abs_key):
        """Apply the same per-segment transform the note loop uses: emoji
        prefix when --icons + manifest, plus optional sanitization."""
        current = src_part
        if joplin_mode and abs_key in joplin_manifests:
            manifest_data = joplin_manifests[abs_key]
            original_title = manifest_data.get("title", current)
            icon_data = manifest_data.get("icon", {}) or {}
            if use_icons and isinstance(icon_data, dict):
                if icon_data.get("type") == "emoji" and icon_data.get("emoji"):
                    emoji = icon_data["emoji"]
                    current = f"{emoji}{SEPARATOR}{original_title.lstrip('- ')}"
        if sanitize_regex:
            current = re.sub(sanitize_regex, '', current).strip()
        return current

    empty_folders_created = 0
    empty_indices_written = 0
    for src_root, src_dirs, src_files in os.walk(src_dir):
        # Skip resource folders entirely
        if any(seg in ("_resources", "resources") for seg in src_root.split(os.sep)):
            continue
        # Only act on folders that have a _folder.yml marker (proper Joplin folders)
        if "_folder.yml" not in src_files:
            continue
        # Skip folders that contain at least one .md note — those will be
        # handled by the per-note loop below, which writes _index.md when
        # needed and creates the directory as a side-effect.
        if any(f.endswith(".md") for f in src_files):
            continue
        # Compute the destination path segment by segment, applying the
        # same emoji/sanitize transforms as the note loop.
        rel = os.path.relpath(src_root, src_dir)
        if rel == ".":
            dest_path = dest_dir
        else:
            parts = rel.split(os.sep)
            current_src = os.path.abspath(src_dir)
            dest_parts = []
            for part in parts:
                current_src = os.path.join(current_src, part)
                dest_parts.append(_compute_dest_segment(part, current_src))
            dest_path = os.path.join(dest_dir, *dest_parts)
        if not os.path.exists(dest_path):
            os.makedirs(dest_path, exist_ok=True)
            empty_folders_created += 1
        # When --icons is on AND this folder has a manifest, write an
        # _index.md so the icon/manifest survives the round-trip. We
        # cannot rely on the per-note loop to do this for empty folders.
        abs_key = os.path.abspath(src_root)
        if use_icons and abs_key in joplin_manifests:
            manifest = joplin_manifests[abs_key]
            index_name = INDEX_FILE_NAME_HIDDEN if hide_manifests else INDEX_FILE_NAME
            index_path = os.path.join(dest_path, index_name)
            if not os.path.exists(index_path):
                # Original (clean Joplin) name is the title from the manifest.
                # Falls back to the source folder name if the manifest didn't
                # have one, which would itself be the clean name (Joplin's
                # exports don't put emojis in folder paths on disk).
                clean_title = manifest.get("title") if isinstance(manifest, dict) else None
                if not clean_title:
                    clean_title = os.path.basename(src_root)
                front_matter = {
                    "type": "folder_index",
                    "original_name": clean_title,
                    "joplin_raw_manifest": manifest,
                }
                try:
                    with open(index_path, "w", encoding="utf-8", newline='\n') as f:
                        f.write(write_front_matter(front_matter, ""))
                    empty_indices_written += 1
                except Exception as e:
                    print(f"  [warn] could not write index {index_path}: {e}")
    if empty_folders_created or empty_indices_written:
        msg = f"--> Created {empty_folders_created} folder placeholder(s)"
        if empty_indices_written:
            msg += f", {empty_indices_written} index manifest(s)"
        print(msg + ".")

    for idx, src_file_path in enumerate(md_files, 1):
        rel_path = os.path.relpath(src_file_path, src_dir)
        path_parts = rel_path.split(os.sep)
        icon_meta_to_write = []
        clean_parts = []

        current_src_accumulation = os.path.abspath(src_dir)

        for part in path_parts:
            current_part = part
            if part != path_parts[-1]:  # Directory segment
                current_src_accumulation = os.path.join(current_src_accumulation, part)
                abs_key = os.path.abspath(current_src_accumulation)

                if joplin_mode and abs_key in joplin_manifests:
                    manifest_data = joplin_manifests[abs_key]
                    original_joplin_title = manifest_data.get("title", current_part)
                    icon_data = manifest_data.get("icon", {}) or {}

                    if use_icons and isinstance(icon_data, dict):
                        if icon_data.get("type") == "emoji" and icon_data.get("emoji"):
                            emoji = icon_data["emoji"]
                            current_part = f"{emoji}{SEPARATOR}{original_joplin_title.lstrip('- ')}"
                            icon_meta_to_write.append(
                                (clean_parts.copy(), "emoji", emoji,
                                 current_part, original_joplin_title, manifest_data))
                        elif icon_data.get("type") == "dataurl" and icon_data.get("dataurl"):
                            icon_meta_to_write.append(
                                (clean_parts.copy(), "dataurl", icon_data["dataurl"],
                                 current_part, original_joplin_title, manifest_data))
                        else:
                            icon_meta_to_write.append(
                                (clean_parts.copy(), "plain", None,
                                 current_part, original_joplin_title, manifest_data))
                    else:
                        # Even when icons are not visually applied on disk,
                        # store the FULL Joplin manifest in the _index.md so
                        # round-tripping back to Joplin is lossless.
                        icon_meta_to_write.append(
                            (clean_parts.copy(), "plain", None,
                             current_part, original_joplin_title, manifest_data))

                elif use_icons and is_emoji_prefixed(current_part):
                    emoji, plain_name = split_emoji_prefix(current_part)
                    icon_meta_to_write.append(
                        (clean_parts.copy(), "emoji", emoji, current_part, plain_name,
                         {"title": plain_name, "icon": {"type": "emoji", "emoji": emoji}}))

            if sanitize_regex:
                if current_part.endswith(".md"):
                    current_part = apply_sanitization(current_part, sanitize_regex)
                else:
                    current_part = re.sub(sanitize_regex, '', current_part).strip()
            clean_parts.append(current_part)

        dest_file_path = os.path.join(dest_dir, *clean_parts)
        note_dest_dir = os.path.dirname(dest_file_path)
        os.makedirs(note_dest_dir, exist_ok=True)

        # Build the _index.md tracking file for each directory along the chain
        for structural_history, i_type, raw_val, complete_orig_string, clean_joplin_title, complete_manifest in icon_meta_to_write:
            if sanitize_regex:
                sanitized_history = [re.sub(sanitize_regex, '', p).strip() for p in structural_history]
                sanitized_orig_string = re.sub(sanitize_regex, '', complete_orig_string).strip()
            else:
                sanitized_history = list(structural_history)
                sanitized_orig_string = complete_orig_string

            target_index_dir = os.path.join(dest_dir, *sanitized_history, sanitized_orig_string)
            os.makedirs(target_index_dir, exist_ok=True)
            _idx_name = INDEX_FILE_NAME_HIDDEN if hide_manifests else INDEX_FILE_NAME
            index_note_path = os.path.join(target_index_dir, _idx_name)

            if not os.path.exists(index_note_path):
                front_matter = {
                    "type": "folder_index",
                    "original_name": clean_joplin_title,
                    "obsidian_displayed_folder": complete_orig_string,
                    "joplin_raw_manifest": complete_manifest,  # Lossless seal
                }
                body_content = (f"# Structural Index: {clean_joplin_title}\n\n"
                                f"Tracks metadata parameters for structural serialization patterns.")
                if i_type == "dataurl":
                    body_content = (f'<img src="{raw_val}" width="64" height="64" '
                                    f'alt="Folder Icon" style="border-radius: 8px; margin-bottom: 10px;"/>\n\n'
                                    + body_content)
                with open(index_note_path, "w", encoding="utf-8", newline='\n') as idx_f:
                    idx_f.write(write_front_matter(front_matter, body_content))

        # Process the note itself. Use raw passthrough so that the original
        # YAML scalars (timestamps, float precision, key order) survive the
        # trip into Obsidian untouched, ready for a lossless round-trip back.
        with open(src_file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        raw_yaml, body = parse_front_matter_raw(content)

        # If sanitization OR --hash-attachments OR --use-md-name renamed any
        # resource files, rewrite the matching references in the body.
        #
        # Tricky bit: paths in Joplin's export are often URL-encoded
        # (spaces -> %20) but resource_renames keys are decoded basenames.
        # We can't rsplit the encoded path by a decoded name — they don't
        # match. Instead we locate the basename by the last '/' in the path
        # and replace only that segment.
        if resource_renames:
            def _rewrite_renamed(m):
                full = m.group(0)
                path = m.group("path")
                base_decoded = unquote(os.path.basename(path))
                if base_decoded not in resource_renames:
                    return full
                last_slash = path.rfind('/')
                if last_slash >= 0:
                    new_path = path[:last_slash + 1] + resource_renames[base_decoded]
                else:
                    new_path = resource_renames[base_decoded]
                return full.replace(path, new_path)
            body = re.sub(
                r'!\[[^\]]*\]\((?P<path>(?:(?!!\[)[^)])*?)(?:\s+"[^"]*")?\)',
                _rewrite_renamed, body,
            )

        # Legacy handler: convert any leftover Joplin :/<hash> references to
        # standard markdown relative paths. Real Joplin MD-Frontmatter exports
        # don't contain these (we verified empirically), but a hand-edited or
        # API-exported note might. Resolve the hash to a real filename by
        # searching the source _resources/ for a matching prefix.
        found_resources = re.findall(r'!?\[[^\]]*?\]\((:/([a-f0-9]{32}))\)', body)
        rel_to_vault_res = os.path.relpath(
            vault_res_dir, os.path.dirname(dest_file_path)).replace(os.sep, '/')
        for full_match, resource_hash in found_resources:
            matched_file = None
            if os.path.exists(joplin_res_dir):
                for res_file in os.listdir(joplin_res_dir):
                    if res_file.startswith(resource_hash):
                        matched_file = res_file
                        break
            if matched_file:
                final_name = resource_renames.get(matched_file, matched_file)
                body = body.replace(
                    f"(:/{resource_hash})",
                    f"({rel_to_vault_res}/{final_name})",
                )

        with open(dest_file_path, "w", encoding="utf-8", newline='\n') as f:
            f.write(assemble_note(raw_yaml, body))

        if idx % 5 == 0 or idx == total_files:
            print_progress(idx, total_files, prefix='Converting Notes')

    if run_semantic_graph:
        print("\n\nWeaving graph edges...")
        sorted_titles, vocab_map = build_vocabulary_map(dest_dir)
        all_dest_mds = [
            os.path.join(r, f)
            for r, d, fs in os.walk(dest_dir)
            for f in fs
            if f.endswith(".md") and f not in (INDEX_FILE_NAME, INDEX_FILE_NAME_HIDDEN)
        ]
        total_weaves = len(all_dest_mds)
        for w_idx, target_note_path in enumerate(all_dest_mds, 1):
            current_note_title = os.path.splitext(os.path.basename(target_note_path))[0]
            with open(target_note_path, "r", encoding="utf-8") as f:
                content = f.read()
            raw_yaml, body = parse_front_matter_raw(content)
            compiled_body = weave_semantic_links(body, sorted_titles, vocab_map, current_note_title)
            with open(target_note_path, "w", encoding="utf-8", newline='\n') as f:
                f.write(assemble_note(raw_yaml, compiled_body))
            if w_idx % 5 == 0 or w_idx == total_weaves:
                print_progress(w_idx, total_weaves, prefix='Weaving Graph')
    print("\nDone!")


# ---------------------------------------------------------------------------
# Obsidian -> Joplin
# ---------------------------------------------------------------------------

def convert_to_joplin(src_dir, dest_dir, use_icons, keep_metadata,
                      fs_cfg=None, sanitize_regex=None,
                      hash_attachments=False, use_md_name=False, no_dedup=False,
                      preserve_empty_dirs=False):
    """Convert an Obsidian vault to a Joplin-ingestible structure.

    Attachment-naming behaviour is controlled by three opt-in flags:
      hash_attachments: rename every attachment to <hash>.<ext>, where the
        hash length follows the target FS profile (md5/32 if none given).
      use_md_name: when references have meaningful alt text, rename the
        on-disk file to match the alt text. Detects missing extensions via
        magic bytes / mimetypes.
      no_dedup: force per-reference file copies instead of sharing identical
        content. Useful when duplicating notebooks for testing.

    Empty-folder behaviour:
      preserve_empty_dirs: drops a "_folder-guardian-it-is-safe-to-delete-me.md"
        stub into every mirrored empty folder so that Joplin's importer
        (which skips empty directories on import) preserves the structure.
        The user is expected to bulk-delete the guardian notes after import.

    hash_attachments and use_md_name are mutually exclusive (caller enforces).
    """
    print("Scanning Obsidian Vault...")
    md_files = []
    folder_metadata_registry = {}
    # Vault-wide attachment index: basename (lowercased) -> list of absolute
    # paths. Obsidian's wikilink syntax references by basename only; identical
    # basenames in different folders are legitimate. We collect all candidates
    # and disambiguate per-reference using proximity to the referencing note.
    attachment_index = {}

    # Pass 1: catalogue every _index.md (the lossless state containers) AND
    # build the vault-wide attachment index. Both '_index.md' and '.index.md'
    # are recognized — the latter is what --hide-manifests produced.
    INDEX_NAMES = (INDEX_FILE_NAME, INDEX_FILE_NAME_HIDDEN)
    for root, dirs, files in os.walk(src_dir):
        if ".obsidian" in root:
            continue
        for idx_name in INDEX_NAMES:
            if idx_name in files:
                try:
                    with open(os.path.join(root, idx_name), "r", encoding="utf-8", errors="replace") as f:
                        meta, _ = parse_front_matter(f.read())
                        if meta.get("type") == "folder_index":
                            folder_metadata_registry[os.path.abspath(root)] = meta
                except Exception:
                    pass
                break  # Found one index file; don't look for the other

        for file in files:
            if file.endswith(".md") and file not in INDEX_NAMES:
                md_files.append(os.path.join(root, file))
            else:
                ext = os.path.splitext(file)[1].lower()
                if ext in ATTACHMENT_EXTS:
                    # Case-insensitive lookup key; preserve original-case path.
                    key = file.lower()
                    attachment_index.setdefault(key, []).append(
                        os.path.join(root, file))

    total_files = len(md_files)
    if total_files == 0:
        return print("No files discovered.")

    os.makedirs(dest_dir, exist_ok=True)
    global_res_dir = os.path.join(dest_dir, "_resources")
    os.makedirs(global_res_dir, exist_ok=True)

    handled_manifest_paths = set()

    # Pass 2: process individual notes; strip visual layout from disk paths
    for idx, src_file_path in enumerate(md_files, 1):
        rel_path = os.path.relpath(src_file_path, src_dir)
        path_parts = rel_path.split(os.sep)

        current_walk_accumulation = src_dir
        clean_joplin_parts = []

        for part in path_parts[:-1]:
            current_walk_accumulation = os.path.join(current_walk_accumulation, part)
            abs_folder_key = os.path.abspath(current_walk_accumulation)

            if abs_folder_key in folder_metadata_registry:
                # We have a registered _index.md — its original_name wins.
                reg_meta = folder_metadata_registry[abs_folder_key]
                clean_name = reg_meta.get("original_name", part)
                # Defensive: strip an emoji prefix that might still be inside
                # the registered name (any inbound style, not just SEPARATOR).
                _, clean_name = extract_inbound_icon(clean_name)
                clean_joplin_parts.append(clean_name)
            else:
                # No _index.md — permissively detect any inbound icon pattern
                # (emoji+dash, emoji+space, emoji+pipe, glued emoji, etc.).
                _, clean_name = extract_inbound_icon(part)
                clean_joplin_parts.append(clean_name)

        clean_joplin_parts.append(path_parts[-1])
        dest_file_path = os.path.join(dest_dir, *clean_joplin_parts)
        dest_note_dir = os.path.dirname(dest_file_path)
        os.makedirs(dest_note_dir, exist_ok=True)

        # Pass 3 (interleaved): generate _folder.yml inside every subfolder
        current_src_walk = src_dir
        for p_idx, part in enumerate(path_parts[:-1]):
            current_src_walk = os.path.join(current_src_walk, part)
            abs_src_folder = os.path.abspath(current_src_walk)

            corresponding_dest_dir = os.path.join(dest_dir, *clean_joplin_parts[:p_idx + 1])
            abs_dest_manifest_key = os.path.abspath(corresponding_dest_dir)

            if abs_dest_manifest_key in handled_manifest_paths:
                continue

            reg_meta = folder_metadata_registry.get(abs_src_folder, {})
            yml_output_path = os.path.join(corresponding_dest_dir, "_folder.yml")
            raw_manifest_payload = reg_meta.get("joplin_raw_manifest", {})

            if raw_manifest_payload:
                # Lossless restoration from sealed manifest
                joplin_yml_payload = dict(raw_manifest_payload)  # copy
                title_val = joplin_yml_payload.get("title", "")
                if isinstance(title_val, str):
                    _, joplin_yml_payload["title"] = extract_inbound_icon(title_val)

                # Drop the icon if the user explicitly requested a clean slate
                if not use_icons and "icon" in joplin_yml_payload:
                    del joplin_yml_payload["icon"]
            else:
                # Fallback reconstruction: derive title + icon from disk name.
                # Try the registered original_name first, then fall back to the
                # current on-disk folder segment. Either way, run it through
                # the permissive inbound-icon extractor.
                raw_title = reg_meta.get("original_name") or part
                detected_icon, clean_title = extract_inbound_icon(raw_title)

                joplin_yml_payload = {"title": clean_title}
                if use_icons and detected_icon:
                    joplin_yml_payload["icon"] = {
                        "type": "emoji",
                        "emoji": detected_icon,
                    }

            try:
                os.makedirs(corresponding_dest_dir, exist_ok=True)
                with open(yml_output_path, "w", encoding="utf-8", newline='\n') as yf:
                    yaml.dump(joplin_yml_payload, yf, default_flow_style=False,
                              allow_unicode=True, sort_keys=False, width=10000)
                handled_manifest_paths.add(abs_dest_manifest_key)
            except Exception:
                pass

        # Read the note. We use BOTH parsers:
        #   - parse_front_matter (typed): only to read the title for the
        #     duplicate-title-strip heuristic.
        #   - parse_front_matter_raw (verbatim): the actual bytes we will
        #     write back, preserving Joplin's original scalar formatting
        #     (e.g. `2025-06-26 10:25:51Z` rather than `2025-06-26 10:25:51+00:00`,
        #     `52.22967560` rather than `52.2296756`, `0.0000` rather than `0.0`).
        with open(src_file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        meta, _ = parse_front_matter(content)
        raw_yaml, body = parse_front_matter_raw(content)

        if not keep_metadata:
            body = de_weave_semantic_links(body)

        # Determine the title for the duplicate-header strip heuristic.
        note_title = meta.get("title", "")
        if not (isinstance(note_title, str) and note_title.strip()):
            note_title = os.path.splitext(os.path.basename(src_file_path))[0]

        # Strip a duplicate first-line title-header from the body when it
        # mirrors the metadata title (prevents the double-title artifact).
        if note_title.strip():
            normalized_title = re.escape(note_title.strip())
            body = re.sub(
                r'^\s*#{1,6}\s*' + normalized_title + r'\s*\n+',
                '', body, count=1
            )

        # === Attachment handling ===
        # Reference forms in the source vault:
        #   (a) ![[file.ext]]            -- Obsidian wikilink embed
        #   (b) ![[file.ext|alt text]]   -- wikilink embed with display text
        #   (c) ![alt](path/to/file.ext) -- standard markdown (relative path)
        # Each is resolved to an actual file on disk, that file is copied into
        # Joplin's global _resources/ folder, and the reference is rewritten to
        # a standard markdown relative-path form (matching Joplin's native
        # MD-Frontmatter export format).
        #
        # The on-disk filename in _resources/ is chosen by:
        #   hash_attachments=True -> <hash>.<ext> (size determined by fs_cfg)
        #   use_md_name=True      -> derived from the markdown alt text
        #   otherwise             -> the source file's original basename
        # Collisions disambiguated per `no_dedup` (Obsidian-style " N" suffix
        # when content differs; share filename when content is identical).

        # Memo: src_abs_path -> final destination filename, per note. Ensures
        # multiple references to the same source within one note all rewrite
        # to the same destination.
        local_attachment_mapping = {}

        def _resolve_target_name(src_abs, alt_text):
            """Decide on-disk filename in _resources/ for this attachment."""
            if hash_attachments:
                h = hash_for_attachment(src_abs, fs_cfg)
                ext = os.path.splitext(src_abs)[1]
                return f"{h}{ext}"
            if use_md_name:
                return resolve_md_name(alt_text, src_abs, fs_cfg, sanitize_regex)
            # Default: original basename
            return os.path.basename(src_abs)

        # Filenames this note has already written to _resources/ in this run.
        # Used to keep dedup scoped per-note: when a different note has
        # already deposited an identically-named file, we add a " N" suffix
        # rather than sharing it across notes.
        per_note_written = set()

        def _copy_and_register(src_abs, alt_text):
            """Copy src_abs into global_res_dir under the appropriate name,
            handle dedup/collision, return the final filename used.

            Dedup scope rules:
              - WITHIN a note: identical src_abs always returns the same
                destination name (via local_attachment_mapping memo).
                Multiple references to the same source from one note share
                a single file in _resources/.
              - ACROSS notes: each note gets its own copy. If another note
                has already written 'cat.png', this note's reference becomes
                'cat 1.png' (etc.) even when bytes are identical. This
                preserves the user's per-note autonomy (editing/deleting
                in one note never affects another).
              - With no_dedup=True: skips even the within-note memo so every
                reference site gets a fresh copy.
            """
            if not no_dedup and src_abs in local_attachment_mapping:
                return local_attachment_mapping[src_abs]

            target_name = _resolve_target_name(src_abs, alt_text)
            # Optionally sanitize for target FS
            if sanitize_regex:
                target_name = apply_sanitization(target_name, sanitize_regex)
            elif fs_cfg:
                target_name = apply_sanitization(target_name, fs_cfg['illegal'])

            # Cross-note collision rule: if a file with this name already
            # exists in _resources/ AND it wasn't written by *this* note in
            # this run, force a " N" suffix even when content is identical.
            # We pass dedup=False to disambiguate_filename for the cross-note
            # path to skip its content-equality short-circuit.
            target_path = os.path.join(global_res_dir, target_name)
            is_cross_note_collision = (
                os.path.exists(target_path) and target_name not in per_note_written
            )
            if is_cross_note_collision:
                final_name = disambiguate_filename(
                    target_name, global_res_dir, src_abs, dedup=False)
            else:
                # No collision OR collision is within this note's own writes.
                final_name = disambiguate_filename(
                    target_name, global_res_dir, src_abs, dedup=not no_dedup)
            final_path = os.path.join(global_res_dir, final_name)

            # Copy unless we've ended up sharing an existing file via dedup.
            if not os.path.exists(final_path):
                try:
                    shutil.copy2(src_abs, final_path)
                except Exception as e:
                    print(f"\n  [warn] could not copy attachment "
                          f"{src_abs}: {e}")
                    return None
            local_attachment_mapping[src_abs] = final_name
            per_note_written.add(final_name)
            return final_name

        def _proximity_resolve(basename, ref_note_path):
            """Given a basename and the path of the note making the reference,
            pick the candidate from attachment_index that is closest to the
            note (Obsidian's shortest-path-from-current rule)."""
            candidates = attachment_index.get(basename.lower(), [])
            if not candidates:
                return None
            if len(candidates) == 1:
                return candidates[0]
            ref_dir = os.path.dirname(ref_note_path)
            # Distance = number of '..' steps + descent steps in relative path
            def _distance(candidate):
                try:
                    rel = os.path.relpath(candidate, ref_dir)
                except ValueError:
                    return 10**6  # different drive on Windows
                return rel.count(os.sep) + rel.count('..')
            return min(candidates, key=_distance)

        # Compute relative path from this note to global _resources/
        rel_to_resources = os.path.relpath(
            global_res_dir, os.path.dirname(dest_file_path))
        # Normalize separators for markdown (always forward slashes)
        rel_to_resources_md = rel_to_resources.replace(os.sep, '/')

        # Pass A: wikilink embeds ![[file]] and ![[file|alt]]
        def _replace_wikilink_embed(m):
            target = m.group("target").strip()
            target_base = os.path.basename(target)
            src_abs = _proximity_resolve(target_base, src_file_path)
            if not src_abs or not os.path.exists(src_abs):
                # Broken reference: file isn't in the vault. Leave visible AND
                # warn so the user notices instead of silently shipping a
                # broken link to Joplin.
                print(f"\n  [warn] {os.path.relpath(src_file_path, src_dir)}: "
                      f"wikilink target not found in vault: {target_base!r}")
                return m.group(0)
            alt = (m.group("alt") or "").strip()
            # In Obsidian wikilink embeds, the "alt text" position carries the
            # display label. For --use-md-name we use it as the target name.
            # If absent, fall back to the wikilink target itself.
            effective_alt = alt or target_base
            final_name = _copy_and_register(src_abs, effective_alt)
            if not final_name:
                return m.group(0)
            display = alt or final_name
            return f"![{display}]({rel_to_resources_md}/{final_name})"

        body = re.sub(
            r'!\[\[(?P<target>[^\]|]+?)(?:\|(?P<alt>[^\]]*))?\]\]',
            _replace_wikilink_embed,
            body,
        )

        # Pass B: standard-markdown attachment links — ![alt](path)
        # We also handle Joplin's :/<hash> internal scheme on the off chance
        # the input vault has unconverted Joplin references mixed in.
        def _process_md_link(m):
            full_path = m.group("path")
            alt = m.group("alt") or ""

            # Joplin's :/<hash> internal scheme - resolve via attachment_index
            # by hash prefix (Joplin's exports normally use real filenames so
            # this is a rare case, but we handle it).
            if full_path.startswith(':/'):
                return m.group(0)  # leave alone; we don't have hash->path map

            # External URL? Leave it alone.
            if re.match(r'^[a-z][a-z0-9+\-.]*://', full_path, re.IGNORECASE):
                return m.group(0)

            decoded_path = unquote(full_path)
            decoded_basename = os.path.basename(decoded_path)
            # Strip URL fragment if any (e.g. #page=3)
            if '#' in decoded_basename:
                decoded_basename = decoded_basename.split('#', 1)[0]

            # Try relative-to-note first
            candidate = os.path.normpath(
                os.path.join(os.path.dirname(src_file_path), decoded_path))
            if not os.path.exists(candidate):
                # Fall back to vault-wide proximity lookup
                candidate = _proximity_resolve(decoded_basename, src_file_path)
            if not candidate or not os.path.exists(candidate):
                # Only warn if this looked attachment-shaped (extension match
                # or no extension at all with use_md_name on). Avoid warning
                # on the relpath-to-note false-negatives that are actually
                # URLs/anchors handled elsewhere.
                ext_l = os.path.splitext(decoded_basename)[1].lower()
                if ext_l in ATTACHMENT_EXTS or (not ext_l and use_md_name):
                    print(f"\n  [warn] {os.path.relpath(src_file_path, src_dir)}: "
                          f"attachment not found: {decoded_path!r}")
                return m.group(0)  # leave broken ref visible

            # Only treat as attachment if extension is recognized — unless
            # --use-md-name is active, in which case the user has signalled
            # they want extension detection / repair anyway.
            ext = os.path.splitext(candidate)[1].lower()
            if ext not in ATTACHMENT_EXTS and not use_md_name:
                return m.group(0)

            effective_alt = alt or decoded_basename
            final_name = _copy_and_register(candidate, effective_alt)
            if not final_name:
                return m.group(0)
            return f"![{alt}]({rel_to_resources_md}/{final_name})"

        # Match ![alt](path) and [alt](path) variants. Captures groups: alt, path.
        # Path captures lazily up to the closing ) or the optional title attr,
        # which lets us handle filenames with literal spaces (common on Windows
        # and from real-world Obsidian vaults: "My Document - Final.pdf").
        # The (?!!\[) guard prevents the lazy match from spanning a missing
        # close-paren in malformed source and fusing two image references
        # into one impossible path.
        body = re.sub(
            r'!\[(?P<alt>[^\]]*)\]\((?P<path>(?:(?!!\[)[^)])*?)(?:\s+"[^"]*")?\)',
            _process_md_link,
            body,
        )

        # Detect probable malformed references: ![...]( followed by content
        # that contains '![' before any close paren — indicates a missing ')'
        # in the source. Warn so the user can fix the source manually; we
        # left those refs verbatim (couldn't safely guess where to insert).
        for m in re.finditer(r'!\[[^\]]*\]\([^)]*?!\[', body):
            snippet = m.group(0)[:80]
            print(f"\n  [warn] {os.path.relpath(src_file_path, src_dir)}: "
                  f"malformed image reference (missing close paren?): "
                  f"{snippet!r}")

        # Assemble the final file. If the source had a YAML front-matter block,
        # preserve its raw text verbatim (timestamps, float precision, key order
        # all survive untouched). Otherwise synthesize minimal front matter.
        #
        # Crucially: we do NOT inject an `id:` field. Joplin's import logic
        # treats a present `id:` as a reference to an existing database UUID;
        # if the UUID doesn't exist, the import silently fails to recognize
        # the front matter and the whole `--- ... ---` block renders as
        # visible body text. Joplin assigns a fresh UUID on import when
        # `id:` is absent, which is the correct behavior.
        updates = {}
        if raw_yaml and "title" not in meta:
            updates["title"] = _yaml_quote_if_needed(note_title)
        out = assemble_note(raw_yaml, body, updates if updates else None)
        if not raw_yaml and not out.startswith("---"):
            # No front matter at all in source — give it at least a title.
            out = write_front_matter({"title": note_title}, body)

        with open(dest_file_path, "w", encoding="utf-8", newline='\n') as f:
            f.write(out)

        if idx % 5 == 0 or idx == total_files:
            print_progress(idx, total_files, prefix='Compiling Vault')

    # Empty-folder mirror pass: walk the Obsidian source for any folder that
    # is empty (or contains only _index.md / .index.md / attachments) and
    # ensure a matching destination directory + _folder.yml exists in the
    # Joplin output. Without this pass, placeholder folders (Inbox, Outbox,
    # bucket-year folders) silently vanish on round-trip.
    empty_dirs_mirrored = 0
    for src_root, src_dirs, src_files in os.walk(src_dir):
        if ".obsidian" in src_root or "_resources" in src_root or "resources" in src_root:
            continue
        # Skip if this folder has any real notes (handled by main loop).
        has_notes = any(
            f.endswith(".md") and f not in (INDEX_FILE_NAME, INDEX_FILE_NAME_HIDDEN)
            for f in src_files
        )
        if has_notes:
            continue
        # Compute clean Joplin-side path: strip emoji prefixes from each segment.
        rel = os.path.relpath(src_root, src_dir)
        if rel == ".":
            dest_folder = dest_dir
        else:
            parts = rel.split(os.sep)
            clean_parts = []
            current_src_walk = src_dir
            for part in parts:
                current_src_walk = os.path.join(current_src_walk, part)
                abs_key = os.path.abspath(current_src_walk)
                name = None
                if abs_key in folder_metadata_registry:
                    name = folder_metadata_registry[abs_key].get("original_name")
                if not name:
                    # Either no registry entry OR original_name is empty/None.
                    # Fall back to extracting any inbound icon from the
                    # Obsidian-displayed name.
                    _, name = extract_inbound_icon(part)
                clean_parts.append(name)
            dest_folder = os.path.join(dest_dir, *clean_parts)

        if not os.path.exists(dest_folder):
            os.makedirs(dest_folder, exist_ok=True)
            empty_dirs_mirrored += 1

        # Write _folder.yml if not already there (main loop handles non-empty).
        manifest_path = os.path.join(dest_folder, "_folder.yml")
        if not os.path.exists(manifest_path):
            abs_src_key = os.path.abspath(src_root)
            # Prefer the manifest registered from _index.md (preserves icons)
            if abs_src_key in folder_metadata_registry:
                reg = folder_metadata_registry[abs_src_key]
                payload = reg.get("joplin_raw_manifest") or {
                    "title": reg.get("original_name", os.path.basename(src_root)),
                }
                if not use_icons and isinstance(payload, dict) and "icon" in payload:
                    payload = {k: v for k, v in payload.items() if k != "icon"}
            else:
                # Synthesize a minimal manifest from the folder name
                _, name = extract_inbound_icon(os.path.basename(src_root))
                payload = {"title": name or os.path.basename(src_root)}
            try:
                with open(manifest_path, "w", encoding="utf-8", newline='\n') as f:
                    yaml.safe_dump(payload, f, allow_unicode=True, sort_keys=False)
            except Exception as e:
                print(f"  [warn] could not write {manifest_path}: {e}")

        # Optional guardian stub: Joplin's importer skips empty directories
        # on MD-Frontmatter import. Dropping a tiny .md stub into each empty
        # folder makes Joplin recognize and preserve the structure. The user
        # is expected to bulk-delete the guardian notes after import (search
        # for "_folder-guardian-it-is-safe-to-delete-me" in Joplin, select
        # all, delete).
        if preserve_empty_dirs:
            guardian_name = "_folder-guardian-it-is-safe-to-delete-me.md"
            guardian_path = os.path.join(dest_folder, guardian_name)
            if not os.path.exists(guardian_path):
                try:
                    with open(guardian_path, "w", encoding="utf-8", newline='\n') as f:
                        f.write(
                            "---\n"
                            "title: _folder-guardian-it-is-safe-to-delete-me\n"
                            "---\n\n"
                            "This note exists only to make Joplin's importer "
                            "preserve an otherwise-empty folder. After import, "
                            "search Joplin for "
                            "`_folder-guardian-it-is-safe-to-delete-me`, "
                            "select all matches, and delete.\n"
                        )
                except Exception as e:
                    print(f"  [warn] could not write guardian {guardian_path}: {e}")
    if empty_dirs_mirrored:
        print(f"--> Mirrored {empty_dirs_mirrored} empty placeholder folder(s).")
    print("Done!")


# ---------------------------------------------------------------------------
# Cleanup (mode-agnostic drift remediation)
# ---------------------------------------------------------------------------

# Matches '+00:00' offset on a datetime line in YAML frontmatter and rewrites
# it to a 'Z' suffix to match Joplin's native export format. Cosmetic only.
_TIMESTAMP_OFFSET_RE = re.compile(
    r'(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})\+00:00\b'
)


def cleanup_yaml_block(raw_yaml):
    """Remediate a raw YAML front-matter block.

    Returns a 3-tuple: (cleaned_yaml, n_id_stripped, n_ts_normalized).
    Operations:
      * Remove any 'id:' line (the actual Joplin-breaking bug).
      * Rewrite datetime values from '+00:00' offset form to 'Z' suffix.
      * Strip trailing whitespace from each line.
    Preserves everything else byte-for-byte.
    """
    if not raw_yaml:
        return raw_yaml, 0, 0
    n_id = 0
    n_ts = 0
    out_lines = []
    for line in raw_yaml.split('\n'):
        # Strip 'id:' lines completely
        m = _FM_KEY_RE.match(line)
        if m and m.group(1) == 'id':
            n_id += 1
            continue
        # Normalize '+00:00' -> 'Z' on timestamp lines
        new_line, sub_count = _TIMESTAMP_OFFSET_RE.subn(r'\1Z', line)
        n_ts += sub_count
        # Strip trailing whitespace
        new_line = new_line.rstrip()
        out_lines.append(new_line)
    return '\n'.join(out_lines), n_id, n_ts


def cleanup_file(src_path, dst_path):
    """Apply remediation to a single .md or .yml file.

    Returns a dict of counters describing what was changed:
      {id_stripped, ts_normalized, bom_stripped, crlf_normalized}
    """
    stats = {"id_stripped": 0, "ts_normalized": 0,
             "bom_stripped": 0, "crlf_normalized": 0}
    with open(src_path, "rb") as f:
        raw_bytes = f.read()

    # Strip BOM
    if raw_bytes.startswith(b'\xef\xbb\xbf'):
        raw_bytes = raw_bytes[3:]
        stats["bom_stripped"] = 1

    try:
        content = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        content = raw_bytes.decode("utf-8", errors="replace")

    # Normalize line endings
    if '\r\n' in content or '\r' in content:
        content = content.replace('\r\n', '\n').replace('\r', '\n')
        stats["crlf_normalized"] = 1

    # If this looks like a markdown file with YAML front matter, remediate it
    if src_path.endswith(".md"):
        raw_yaml, body = parse_front_matter_raw(content)
        if raw_yaml:
            cleaned_yaml, n_id, n_ts = cleanup_yaml_block(raw_yaml)
            stats["id_stripped"] = n_id
            stats["ts_normalized"] = n_ts
            content = assemble_note(cleaned_yaml, body)

    # _folder.yml: also strip id: lines and normalize timestamps if any
    elif src_path.endswith(".yml") or src_path.endswith(".yaml"):
        cleaned_yaml, n_id, n_ts = cleanup_yaml_block(content)
        stats["id_stripped"] = n_id
        stats["ts_normalized"] = n_ts
        # Preserve a trailing newline for yml files
        if not cleaned_yaml.endswith('\n'):
            cleaned_yaml += '\n'
        content = cleaned_yaml

    os.makedirs(os.path.dirname(dst_path) or ".", exist_ok=True)
    with open(dst_path, "w", encoding="utf-8", newline='\n') as f:
        f.write(content)
    return stats


def deep_ref_scan(target_dir):
    """Walk all .md files under target_dir, extract every attachment reference,
    and identify orphans in any _resources/ (or resources/) folders.

    Returns (referenced_set, orphans_list) where:
      - referenced_set is the set of absolute paths actually referenced
      - orphans_list is files in _resources/ that nothing references
    """
    referenced = set()
    res_dirs = set()

    # Discover resource directories under target_dir
    for root, dirs, files in os.walk(target_dir):
        for d in dirs:
            if d in ("_resources", "resources"):
                res_dirs.add(os.path.join(root, d))

    # Walk all markdown files; collect every attachment-shaped reference
    for root, dirs, files in os.walk(target_dir):
        if ".obsidian" in root:
            continue
        for fname in files:
            if not fname.endswith(".md"):
                continue
            md_path = os.path.join(root, fname)
            try:
                with open(md_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except Exception:
                continue

            # Standard markdown links: ![alt](path) — path may contain spaces;
            # guard against embedded '![' to avoid fusing two refs on
            # malformed source missing a close-paren.
            for m in re.finditer(
                    r'!\[[^\]]*\]\(((?:(?!!\[)[^)])*?)(?:\s+"[^"]*")?\)', content):
                full_path = unquote(m.group(1))
                # Skip URLs and Joplin internal scheme
                if re.match(r'^[a-z][a-z0-9+\-.]*://', full_path, re.IGNORECASE):
                    continue
                if full_path.startswith(':/'):
                    continue
                # Strip URL fragment
                if '#' in full_path:
                    full_path = full_path.split('#', 1)[0]
                resolved = os.path.normpath(
                    os.path.join(os.path.dirname(md_path), full_path))
                referenced.add(os.path.abspath(resolved))

            # Wikilink embeds: ![[target]] or ![[target|alt]]
            for m in re.finditer(
                    r'!\[\[([^\]|]+?)(?:\|[^\]]*)?\]\]', content):
                target = m.group(1).strip()
                target_base = os.path.basename(target)
                # Search every resource dir + parent of note for this basename
                search_locations = list(res_dirs) + [os.path.dirname(md_path)]
                for loc in search_locations:
                    candidate = os.path.join(loc, target_base)
                    if os.path.exists(candidate):
                        referenced.add(os.path.abspath(candidate))
                        break

    # Find all attachment-shaped files in resource dirs
    on_disk = set()
    for res_dir in res_dirs:
        if not os.path.isdir(res_dir):
            continue
        for fname in os.listdir(res_dir):
            ext = os.path.splitext(fname)[1].lower()
            if ext in ATTACHMENT_EXTS:
                on_disk.add(os.path.abspath(os.path.join(res_dir, fname)))

    orphans = sorted(on_disk - referenced)
    return referenced, orphans


def cleanup_directory(src_dir, dst_dir, in_place=False, clean_mode=None):
    """Walk src_dir, remediate every .md and .yml file, write to dst_dir.

    When in_place is True, dst_dir is ignored and files are overwritten in
    src_dir directly. Non-md/non-yml files are copied through unchanged
    when writing to a separate output directory.

    clean_mode controls orphan handling after the file remediation pass:
      None         : skip orphan handling entirely (default)
      'clean'      : non-destructive — move orphans to _orphaned_resources/
                     alongside the existing _resources/. User reviews and
                     deletes manually.
      'clean-purge': destructive — delete orphans permanently. Equivalent to
                     the previous --deep-ref-scan behaviour.
    """
    if in_place:
        dst_dir = src_dir
        print(f"Cleaning up in place: {src_dir}")
    else:
        print(f"Cleaning up: {src_dir} -> {dst_dir}")
        os.makedirs(dst_dir, exist_ok=True)

    # Gather targets
    all_files = []
    for root, dirs, files in os.walk(src_dir):
        if ".obsidian" in root:
            continue
        for fname in files:
            all_files.append(os.path.join(root, fname))

    total = len(all_files)
    if total == 0:
        return print("No files found.")

    totals = {"id_stripped": 0, "ts_normalized": 0,
              "bom_stripped": 0, "crlf_normalized": 0,
              "files_touched": 0, "files_processed": 0}

    for idx, src_path in enumerate(all_files, 1):
        rel = os.path.relpath(src_path, src_dir)
        dst_path = os.path.join(dst_dir, rel)
        totals["files_processed"] += 1

        if src_path.endswith((".md", ".yml", ".yaml")):
            try:
                stats = cleanup_file(src_path, dst_path)
                if any(stats.values()):
                    totals["files_touched"] += 1
                for k, v in stats.items():
                    totals[k] += v
            except Exception as e:
                print(f"\n  [warn] could not clean {src_path}: {e}")
        elif not in_place:
            # Copy non-markdown files (attachments, etc.) through unchanged
            os.makedirs(os.path.dirname(dst_path) or ".", exist_ok=True)
            try:
                shutil.copy2(src_path, dst_path)
            except Exception as e:
                print(f"\n  [warn] could not copy {src_path}: {e}")

        if idx % 5 == 0 or idx == total:
            print_progress(idx, total, prefix='Cleaning Files')

    print("\n")
    print(f"  Files processed:       {totals['files_processed']}")
    print(f"  Files modified:        {totals['files_touched']}")
    print(f"  'id:' fields stripped: {totals['id_stripped']}")
    print(f"  Timestamps normalized: {totals['ts_normalized']}")
    print(f"  BOMs stripped:         {totals['bom_stripped']}")
    print(f"  CRLF normalized:       {totals['crlf_normalized']}")

    # Optional orphan-handling pass (--clean or --clean-purge)
    if clean_mode in ("clean", "clean-purge"):
        action_label = "Moving" if clean_mode == "clean" else "Deleting"
        print(f"\nOrphan scan: building reference graph...")
        _referenced, orphans = deep_ref_scan(dst_dir)
        if not orphans:
            print(f"  No orphans found. {len(_referenced)} reference(s) resolved.")
        else:
            print(f"  Found {len(orphans)} orphan file(s).")
            if clean_mode == "clean":
                # Mirror the on-disk layout of each orphan under
                # <dst_dir>/_orphaned_resources/, preserving subfolder
                # structure so the user can identify where each came from.
                orphan_root = os.path.join(dst_dir, "_orphaned_resources")
                os.makedirs(orphan_root, exist_ok=True)
                moved = 0
                for orph in orphans:
                    rel = os.path.relpath(orph, dst_dir)
                    target = os.path.join(orphan_root, rel)
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    try:
                        shutil.move(orph, target)
                        moved += 1
                    except Exception as e:
                        print(f"  [warn] could not move {orph}: {e}")
                print(f"  Moved {moved} orphan(s) to {orphan_root}")
                print(f"  Review and delete manually when ready.")
            else:  # clean-purge
                removed = 0
                for orph in orphans:
                    try:
                        os.remove(orph)
                        removed += 1
                    except Exception as e:
                        print(f"  [warn] could not remove {orph}: {e}")
                print(f"  Permanently removed {removed} orphan(s).")

    print("Done!")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Lossless Bi-directional Joplin/Obsidian Sync-Engine.",
        epilog=EPILOG_TEXT,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument('mode', choices=['to-obsidian', 'to-joplin', 'cleanup'],
                        help="Direction of conversion, or 'cleanup' to remediate "
                             "drift in existing files.")
    parser.add_argument('input_dir', help="Source directory.")
    parser.add_argument('output_dir', nargs='?', default=None,
                        help="Destination directory. Required for to-obsidian and "
                             "to-joplin; optional for cleanup when --in-place is set.")
    parser.add_argument('resource_folder', nargs='?', default=DEFAULT_ATTACHMENT_DIR,
                        help=f"Per-note attachment folder name. (Default: {DEFAULT_ATTACHMENT_DIR})")

    parser.add_argument('-fs',
                        choices=['ntfs', 'exfat', 'linux', 'zfs', 'apfs', 'hfs', 'cloud'],
                        default=None,
                        help="Target filesystem profile (controls path/length "
                             "rules). When omitted, no FS-specific shrinking; "
                             "--hash-attachments uses md5/32 chars.")
    parser.add_argument('-sanitize',
                        choices=['win', 'mac', 'ios', 'android', 'linux', 'cloud'],
                        default=None,
                        help="Strip OS-illegal characters for the target platform.")

    parser.add_argument('--icons', action='store_true',
                        help="Preserve folder icons (emojis/dataurl) across the round-trip.")
    parser.add_argument('--semantic-graph', action='store_true',
                        help="Weave [[wikilink]] connections between notes in the destination vault.")
    parser.add_argument('--keep-metadata', action='store_true',
                        help="Retain semantic [[links]] inside note bodies when recompiling to Joplin.")
    parser.add_argument('--in-place', action='store_true',
                        help="(cleanup mode only) Overwrite source files instead of "
                             "writing a remediated copy to output_dir. Make a backup first.")

    # Attachment-naming flags (apply to to-obsidian AND to-joplin). Mutually
    # exclusive pair plus an orthogonal dedup toggle.
    parser.add_argument('--hash-attachments', action='store_true',
                        help="Rename every attachment to <hash>.<ext>. Hash "
                             "length follows the target -fs profile (md5/32 "
                             "if none given). Mutually exclusive with "
                             "--use-md-name.")
    parser.add_argument('--use-md-name', action='store_true',
                        help="Use the markdown alt-text as the on-disk "
                             "filename when meaningful. Detects missing "
                             "extensions. Mutually exclusive with "
                             "--hash-attachments.")
    parser.add_argument('--no-dedup', action='store_true',
                        help="Force a separate file copy per reference, even "
                             "when bytes are identical. Default is dedup-on.")
    parser.add_argument('--hide-manifests', action='store_true',
                        help="(to-obsidian) Write folder manifest files as "
                             "'.index.md' instead of '_index.md'. Obsidian "
                             "hides dot-prefixed files by default, giving a "
                             "cleaner file explorer. Round-trips correctly.")

    # to-joplin: workaround for Joplin's importer skipping empty directories
    parser.add_argument('--preserve-empty-dirs', action='store_true',
                        help="(to-joplin) Drop a "
                             "'_folder-guardian-it-is-safe-to-delete-me.md' "
                             "stub into every empty folder so Joplin's "
                             "importer preserves the structure. After import, "
                             "search Joplin for "
                             "'_folder-guardian-it-is-safe-to-delete-me', "
                             "select all, and delete to clean up the stubs.")

    # Cleanup extras (orphan handling — mutually exclusive)
    parser.add_argument('--clean', action='store_true',
                        help="(cleanup mode) Non-destructive orphan scan: move "
                             "unreferenced files from _resources/ to "
                             "_orphaned_resources/ for manual review.")
    parser.add_argument('--clean-purge', action='store_true',
                        help="(cleanup mode) Destructive orphan scan: "
                             "permanently delete unreferenced files from "
                             "_resources/. Mutually exclusive with --clean.")
    # Deprecated alias for --clean-purge (kept for backward compat).
    parser.add_argument('--deep-ref-scan', action='store_true',
                        help=argparse.SUPPRESS)

    # If no args, print full help with examples
    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)

    args = parser.parse_args()

    fs_cfg = FS_PROFILES.get(args.fs) if args.fs else None
    sanitize_regex = SANITIZE_PROFILES.get(args.sanitize) if args.sanitize else None

    # Mutual exclusion: --hash-attachments and --use-md-name want different
    # things from the same on-disk filename.
    if args.hash_attachments and args.use_md_name:
        parser.error("--hash-attachments and --use-md-name are mutually exclusive; "
                     "pick one (or neither for the default Joplin-native naming).")

    # Mutual exclusion: --clean (move orphans) and --clean-purge (delete orphans).
    if args.clean and args.clean_purge:
        parser.error("--clean and --clean-purge are mutually exclusive; "
                     "use --clean to move orphans for review, --clean-purge "
                     "to delete them permanently.")

    # Honour the deprecated alias: --deep-ref-scan still maps to --clean-purge.
    if args.deep_ref_scan and not (args.clean or args.clean_purge):
        print("Note: --deep-ref-scan is deprecated; use --clean-purge instead.")
        args.clean_purge = True

    # Resolve clean_mode for cleanup_directory.
    clean_mode = "clean" if args.clean else ("clean-purge" if args.clean_purge else None)

    # Defensive: verify the input directory actually exists before any mode
    # silently no-ops on a misspelled path or wrong working directory.
    if not os.path.isdir(args.input_dir):
        parser.error(f"input_dir does not exist or is not a directory: "
                     f"{args.input_dir!r} (resolved from cwd: {os.getcwd()})")

    if args.mode == "to-obsidian":
        if not args.output_dir:
            parser.error("to-obsidian requires output_dir")
        convert_to_obsidian(
            args.input_dir, args.output_dir, args.resource_folder,
            fs_cfg, sanitize_regex, args.icons, args.semantic_graph,
            hash_attachments=args.hash_attachments,
            use_md_name=args.use_md_name,
            no_dedup=args.no_dedup,
            hide_manifests=args.hide_manifests,
        )
    elif args.mode == "to-joplin":
        if not args.output_dir:
            parser.error("to-joplin requires output_dir")
        convert_to_joplin(
            args.input_dir, args.output_dir, args.icons, args.keep_metadata,
            fs_cfg=fs_cfg, sanitize_regex=sanitize_regex,
            hash_attachments=args.hash_attachments,
            use_md_name=args.use_md_name,
            no_dedup=args.no_dedup,
            preserve_empty_dirs=args.preserve_empty_dirs,
        )
    elif args.mode == "cleanup":
        if not args.in_place and not args.output_dir:
            parser.error("cleanup requires either output_dir or --in-place")
        if args.in_place and args.output_dir:
            print("Note: --in-place is set; output_dir argument will be ignored.")
        cleanup_directory(args.input_dir, args.output_dir, in_place=args.in_place,
                          clean_mode=clean_mode)

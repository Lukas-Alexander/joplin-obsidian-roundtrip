# joplin-obsidian-roundtrip

### A lossless, bidirectional sync engine between Joplin and Obsidian.

<sub>Built for the people who refuse to pick a side — and refuse to lose their notes along the way.</sub>

<br>

[![License: GPL v2](https://img.shields.io/badge/License-GPLv2-blue.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Platform: Desktop](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)]()

</div>

---

## Why this exists

You start a project in **Joplin** on your Windows desktop. Folder icons everywhere, structured the way you like it, attachments where they belong. Then the Joplin iOS app breaks for three weeks (it happens), and you need to keep working: so you open **Obsidian** on your iPad. Two weeks later, you want everything back in Joplin.

That's when you discover the available conversion tools all miss something:

- One preserves notes but **loses folder icons**.
- Another keeps icons but **flattens your folder structure**.
- A third converts beautifully one way, then has **no way back**.
- A fourth handles text but **breaks every image link**.
- A fifth ignores empty placeholder folders entirely, **silently dropping** your `Inbox`, `Outbox`, year-bucket structure.

After enough rounds of that frustration, I built my own. This is it.

It works between any Joplin and Obsidian platform combination — Joplin Windows → Obsidian iOS, Obsidian Android → Joplin macOS, Joplin Linux → Obsidian Windows, in any direction. It is built for **desktop use** (where you have a real filesystem and Python), but its **output** drops cleanly into any platform's vault folder.

---

## What survives the round-trip

<table>
<tr><th>Element</th><th>Joplin → Obsidian</th><th>Obsidian → Joplin</th></tr>

<tr><td><b>Note bodies</b></td><td>✅ Byte-fidelity preserved</td><td>✅ Byte-fidelity preserved</td></tr>
<tr><td><b>YAML front-matter</b></td><td>✅ Timestamps, floats, key order all preserved verbatim</td><td>✅ Original scalar text restored exactly (no <code>+00:00</code> drift, no float renormalization)</td></tr>
<tr><td><b>Folder hierarchy</b></td><td>✅ Full depth, all subfolders</td><td>✅ Clean Joplin-native paths on disk</td></tr>
<tr><td><b>Folder icons (emoji)</b></td><td>✅ Applied to disk paths visually (<code>📂 - Folder</code>) OR preserved invisibly in <code>_index.md</code></td><td>✅ Restored to <code>_folder.yml</code> via embedded manifest</td></tr>
<tr><td><b>Folder icons (custom dataurl)</b></td><td>✅ Preserved in <code>_index.md</code> (Obsidian doesn't render them, but they survive)</td><td>✅ Restored to <code>_folder.yml</code> exactly as Joplin had them</td></tr>
<tr><td><b>Attachments</b></td><td>✅ Bulk-copied to <code>_resources/</code>, references rewritten</td><td>✅ Collected from anywhere in the vault into Joplin's global <code>_resources/</code></td></tr>
<tr><td><b>Empty placeholder folders</b></td><td>✅ Pre-created with manifest</td><td>✅ Mirrored with <code>--preserve-empty-dirs</code> guardian stubs</td></tr>
<tr><td><b>Wikilinks (<code>[[link]]</code>)</b></td><td>—</td><td>✅ Stripped to plain text by default; preserved with <code>--keep-metadata</code></td></tr>
<tr><td><b>Embed wikilinks (<code>![[file]]</code>)</b></td><td>—</td><td>✅ Rewritten to standard markdown image syntax</td></tr>
</table>

### The philosophy

**What CAN be preserved natively in the target format, IS.**

**What CAN'T is preserved in special sidecar files** (`_index.md` on the Obsidian side, `_folder.yml` on the Joplin side) so that when you go *home* — back to the originating tool — the full original state is restored. You always retain full editing capability in whichever tool you're currently in.

A custom dataurl icon assigned in Joplin won't *render* in Obsidian (Obsidian doesn't paint folder icons that way), but it's still there in the metadata. Go back to Joplin and the icon reappears, untouched.

---

## Quick start

### Requirements

- Python **3.8 or newer**
- One dependency: `PyYAML`

```bash
pip install pyyaml
```

That's it. No virtualenv ceremony, no Node modules, no compiled binaries.

### The three modes

```bash
# Joplin (raw export) -> Obsidian vault
python j2o.py to-obsidian  <joplin_export_dir>  <obsidian_vault_dir>  [options]

# Obsidian vault -> Joplin (raw, importable)
python j2o.py to-joplin    <obsidian_vault_dir> <joplin_import_dir>   [options]

# Cleanup mode (drift remediation on any existing vault)
python j2o.py cleanup      <vault_dir>          [output_dir | --in-place]  [options]
```

### Common workflows

<details>
<summary><b>1. Joplin → Obsidian, preserve folder icons visually</b></summary>

```bash
python j2o.py to-obsidian "Joplin Export" "My Vault" --icons
```

Folder icons become visible disk prefixes (`📂 - Folder`). Use this when you want to see icons in Obsidian's file explorer.
</details>

<details>
<summary><b>2. Obsidian → Joplin round-trip, including empty folders</b></summary>

```bash
python j2o.py to-joplin "My Vault" "Joplin Import" --icons --preserve-empty-dirs
```

The `--preserve-empty-dirs` flag drops a tiny `_folder-guardian-it-is-safe-to-delete-me.md` stub into every empty placeholder folder, because Joplin's importer skips empty directories. After import, search Joplin for `folder-guardian`, select all matches, delete.
</details>

<details>
<summary><b>3. Cloud-sync-safe filenames (Dropbox, OneDrive, iCloud)</b></summary>

```bash
python j2o.py to-obsidian "Joplin Export" "Cloud Vault" --icons --hash-attachments -fs cloud
```

Attachments get renamed to content hashes (sha224, 56 chars), short enough to fit in cloud-sync filename length limits. Identical content deduplicates automatically.
</details>

<details>
<summary><b>4. Windows / NTFS — strip illegal characters</b></summary>

```bash
python j2o.py to-obsidian "Joplin Export" "Vault" --icons -fs ntfs -sanitize win
```

Strips characters Windows can't have in filenames (`< > : " | ? *`), respects NTFS path length rules.
</details>

<details>
<summary><b>5. Hidden folder manifests (cleaner Obsidian file explorer)</b></summary>

```bash
python j2o.py to-obsidian "Joplin Export" "Vault" --icons --hide-manifests
```

Writes `.index.md` instead of `_index.md`. Obsidian's file explorer hides dot-prefixed files by default, giving you a much cleaner sidebar. Round-trips correctly.
</details>

<details>
<summary><b>6. Cleanup: find orphan attachments (safe, non-destructive)</b></summary>

```bash
python j2o.py cleanup "My Vault" --in-place --clean
```

Walks every `.md` reference, identifies attachments in `_resources/` that nothing points to, **moves** them to `_orphaned_resources/` for manual review. Add `--clean-purge` instead of `--clean` to delete them permanently.
</details>

<details>
<summary><b>7. Full option reference</b></summary>

```bash
python j2o.py --help
```

Prints the complete flag list with twelve worked examples covering filesystem profiles, sanitization modes, attachment naming strategies, and cleanup operations.
</details>

---

## Platform combinations tested

| From → To | Status |
|---|---|
| Joplin Windows → Obsidian Windows | ✅ Tested with 241 notes, 886 attachments |
| Joplin Windows → Obsidian iPad/iOS | ✅ Via cloud sync, use `-fs cloud` |
| Joplin Linux → Obsidian Linux | ✅ |
| Obsidian Windows → Joplin Windows | ✅ Lossless round-trip verified |
| Obsidian macOS → Joplin macOS | ✅ Use `-sanitize mac` |
| Obsidian Android → Joplin Linux | ⚙️ Run the script on Linux against the synced folder |

The script itself is **desktop-only** for now: it needs a real Python runtime and a real filesystem. The **vaults it produces** are universal: drop them into any Obsidian instance (mobile or desktop) or import them into any Joplin instance (mobile or desktop). A future port to mobile may be possible, but iOS and Android both impose significant sandboxing restrictions that need testing.

---

## How it works (the short version)

The key insight: when a tool **can't** natively represent something from the other tool's world (like Joplin's custom dataurl icons in Obsidian), you don't have to *throw it away*. You can store it in a structured sidecar file that survives the round-trip invisibly.

- **Joplin → Obsidian**: every Joplin `_folder.yml` becomes an `_index.md` (or `.index.md` with `--hide-manifests`) inside the corresponding Obsidian folder. The `_index.md` contains a `joplin_raw_manifest:` block — the *full* original Joplin manifest, embedded verbatim. Obsidian doesn't care about it; Joplin reads it back on the return trip.

- **Obsidian → Joplin**: the converter looks for these `_index.md` sidecars first. When found, it reconstructs the exact original `_folder.yml`. When absent (a folder created fresh in Obsidian), it synthesizes one from the folder name, detecting any leading emoji prefix you might have typed.

- **Front-matter byte-fidelity**: a separate raw-YAML passthrough preserves Joplin's exact original scalar formatting — timestamps stay as `2025-06-26 10:25:51Z` (not `+00:00`), float precision stays at `52.22967560` (not `52.2296756`), key order stays intact. This is what makes the round-trip *byte-identical* for notes without attachments.

- **Attachments**: handled by a vault-wide index with proximity resolution (Obsidian's "shortest-path-from-current" wikilink rule) and content-hash deduplication. References are rewritten to standard markdown paths matching Joplin's native export format.

---

## About the author

I'm a Senior Advisor and Enterprise Architect by trade, specializing in **GRC, AI, and Security** at the enterprise level. The day job is large-scale: governance frameworks, compliance architectures, AI-risk strategies for organizations with thousands of stakeholders.

In my spare time, I build small, sharp tools for the small, sharp problems that nobody else seems to want to solve. My GitHub presence is recent: I've accumulated a library of these utilities over the years and only lately started sharing them. The first one I published was a [Pulse Effects → Easy Effects converter](https://github.com/Lukas-Alexander/pulse-effects-2-easy-effects-converter), born of the same instinct: my favorite audio tool was renamed and rewritten, and I had 100+ saved presets that the new tool couldn't read. Nobody had built a migration script. So I built one.

This Joplin/Obsidian script is in the same spirit. Not a promise to publish more, just a note: there will be more. Tools I actually use, shared because someone else might want them too.

Find me on GitHub: [Lukas-Alexander](https://github.com/Lukas-Alexander)

---

## License

GPL-2.0-or-later. See [LICENSE](LICENSE) for the full text.

In plain English: you can use this, modify it, share modifications, and even sell services based on it. What you **cannot** do is take this code, modify it, and ship a closed-source product based on it without releasing your modifications under GPL-2.0 as well. The license forces transparency, not gratitude.

---

## Contributing

Issues and pull requests are welcome. If you hit a Joplin or Obsidian quirk this script doesn't handle yet, open an issue with:

1. The platform combination (e.g. "Joplin Windows → Obsidian macOS")
2. A minimal reproduction (a small note + folder structure that triggers the problem)
3. The script's full console output

If you're contributing a fix, please include a test case in the PR description.

---

<div align="center">
<sub>Built because the alternative was losing everything that made my notes mine..</sub>
</div>

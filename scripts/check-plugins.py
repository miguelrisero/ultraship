#!/usr/bin/env python3
"""Check marketplace packaging and the small Markdown frontmatter used here."""
import argparse
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MODELS = {
    'gpt-6-astra', 'gpt-6-sol', 'gpt-5.6-sol', 'gpt-6-luna', 'cf-glm-5.3',
    'cf-glm-5.3-flash', 'cf-deepseek-v4-pro', 'cf-deepseek-v4-flash',
    'kimi-k3', 'claude-fable-5-1', 'claude-opus-5-5', 'claude-sonnet-5', 'inherit',
}
EFFORTS = {'low', 'medium', 'high', 'xhigh', 'max'}


def frontmatter(text):
    """Read top-level scalar fields; CLI validation owns full YAML validation."""
    if not text.startswith('---\n'):
        raise ValueError('frontmatter must start on line 1')
    head, sep, _ = text[4:].partition('\n---')
    if not sep:
        raise ValueError('frontmatter closing fence missing')
    fields = {}
    key = None
    for line in head.splitlines():
        match = re.match(r'^([\w-]+):\s*(.*)$', line)
        if match:
            key, value = match.groups()
            fields[key] = '' if value in ('|', '>', '|-', '>-') else value.strip('\"\'')
        elif line[:1].isspace() and key:
            fields[key] += ' ' + line.strip()
    return {key: value.strip() for key, value in fields.items()}


def inspect_text(text, path):
    errors = []
    try:
        fields = frontmatter(text)
    except ValueError as exc:
        return [str(exc)]
    if not fields.get('description'):
        errors.append('description missing')
    if len(fields.get('description', '')) > 500:
        errors.append('description exceeds 500 characters')
    if path.name == 'SKILL.md' and not fields.get('name'):
        errors.append('skill name missing')
    if fields.get('model', 'inherit') not in MODELS:
        errors.append('unsupported model: ' + fields['model'])
    if path.parent.name == 'agents':
        if not fields.get('name'):
            errors.append('agent name missing')
        if 'allowed-tools' in fields:
            errors.append('agent definitions use tools, not allowed-tools')
        if fields.get('effort', 'high') not in EFFORTS:
            errors.append('unsupported effort: ' + fields['effort'])
        if fields['name'].startswith('writer--') and 'Agent' not in fields.get('disallowedTools', ''):
            errors.append('writers must disallow Agent')
    if '${SKILL_DIR}' in text:
        errors.append('use ${CLAUDE_SKILL_DIR} for bundled skill paths')
    return errors


def version_error(local, registered, previous=None):
    if local != registered:
        return 'manifest and marketplace versions differ'
    if not re.fullmatch(r'\d+\.\d+\.\d+', local):
        return 'version must be numeric semver'
    if previous is not None and tuple(map(int, local.split('.'))) <= tuple(map(int, previous.split('.'))):
        return 'changed plugin requires a version increase'
    return None


def check(base=None):
    errors = []
    registry = json.loads((ROOT / '.claude-plugin/marketplace.json').read_text())
    entries = registry['plugins']
    by_path = {entry['source'].removeprefix('./'): entry for entry in entries}
    if len(by_path) != len(entries):
        errors.append('duplicate plugin source')
    changed = set()
    if base:
        diff = subprocess.check_output(['git', 'diff', '--name-only', base, '--', 'plugins'], cwd=ROOT, text=True)
        untracked = subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard', 'plugins'], cwd=ROOT, text=True)
        changed = {p.split('/')[1] for p in (diff + untracked).splitlines() if len(p.split('/')) > 1}
    ship = ROOT / 'plugins/ship'
    ship_names = {p.stem for p in (ship / 'agents').glob('*.md')} | {p.name for p in (ship / 'skills').iterdir()}
    plugin_dirs = {p.relative_to(ROOT).as_posix() for p in (ROOT / 'plugins').iterdir() if p.is_dir()}
    for missing in sorted(set(by_path) - plugin_dirs):
        errors.append(missing + ': registered source missing')
    for source in sorted(plugin_dirs):
        plugin = ROOT / source
        entry = by_path.get(source)
        manifest = plugin / '.claude-plugin/plugin.json'
        if not manifest.exists() or entry is None:
            errors.append(source + ': manifest or registration missing')
            continue
        data = json.loads(manifest.read_text())
        if data['name'] != entry['name']:
            errors.append(source + ': manifest and marketplace names differ')
        previous = None
        if base and plugin.name in changed:
            old = subprocess.run(['git', 'show', f'{base}:{source}/.claude-plugin/plugin.json'], cwd=ROOT, capture_output=True, text=True)
            if old.returncode == 0:
                previous = json.loads(old.stdout)['version']
        error = version_error(data['version'], entry['version'], previous)
        if error:
            errors.append(source + ': ' + error)
        for path in plugin.rglob('*.md'):
            text = path.read_text()
            if path.name == 'SKILL.md' or path.parent.name in ('agents', 'commands'):
                errors.extend(f'{path.relative_to(ROOT)}: {error}' for error in inspect_text(text, path))
            for ref in re.findall(r'`ship:([\w*-]+)', text):
                if '*' not in ref and ref not in ship_names:
                    errors.append(f'{path.relative_to(ROOT)}: unknown agent or skill ship:{ref}')
            for chain in re.findall(r'^\| `ship:[^|]+\|[^|]+\|[^|]+\|[^|]+\|([^|]+)\|$', text, re.M):
                for ref in re.findall(r'`([\w-]+--[\w-]+)`', chain):
                    if ref not in ship_names:
                        errors.append(f'{path.relative_to(ROOT)}: unknown fallback {ref}')
            # Only concrete relative links are checked; URLs, anchors and templates are external contracts.
            for target in re.findall(r'(?<!!)\[[^\]]+\]\(([^)\s]+)\)', text):
                if re.match(r'^(?:[a-z]+:|#|/|~|\$)', target) or any(c in target for c in '<>{}*'):
                    continue
                local = target.split('#')[0]
                if local and not (path.parent / local).exists():
                    errors.append(f'{path.relative_to(ROOT)}: missing link {target}')
    return errors


def self_test():
    text = '---\nname: test\ndescription: Short trigger.\nmodel: gpt-6-astra\n---\n'
    assert inspect_text(text, Path('agents/test.md')) == []
    assert inspect_text(text.replace('Short trigger.', 'x' * 501), Path('SKILL.md'))
    assert inspect_text(text.replace('gpt-6-astra', 'unknown-model'), Path('agents/test.md'))
    assert inspect_text(text.replace('model:', 'effort: huge\nmodel:'), Path('agents/test.md'))
    assert inspect_text(text.replace('name: test', 'name: writer--x'), Path('agents/test.md'))
    assert not inspect_text(text.replace('name: test', 'name: writer--x\ndisallowedTools: Agent'), Path('agents/test.md'))
    assert inspect_text('prefix\n' + text, Path('SKILL.md'))
    assert frontmatter('---\nname: test\ndescription: >\n  A narrow\n  trigger.\n---\n')['description'] == 'A narrow trigger.'
    assert version_error('1.0.1', '1.0.0')
    assert version_error('1.0.0', '1.0.0', '1.0.0')
    assert version_error('1.0.1', '1.0.1', '1.0.0') is None


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', help='Git ref used for changed-plugin version checks')
    args = parser.parse_args()
    self_test()
    failures = check(args.base)
    for failure in failures:
        print('FAIL:', failure)
    if not failures:
        print('PASS: plugin packaging, descriptions, models, efforts, agent references, and local links')
    raise SystemExit(bool(failures))

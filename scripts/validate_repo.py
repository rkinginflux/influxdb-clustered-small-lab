#!/usr/bin/env python3
"""Offline documentation/example validation; never contacts Kubernetes."""
import json
from pathlib import Path
import re
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
SKIP = {'.git', '.private', '.local', '.venv', '.tools', '__pycache__', 'charts'}
CHECKS = {
    'private key material': r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    'GitHub token': r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b',
    'cloud access key': r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b',
    'private IPv4 address': r'\b(?:192\.168|10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b',
    'machine-specific home path': r'/home/[A-Za-z0-9_.-]+/',
    'literal credential-bearing PostgreSQL URL': r'postgres(?:ql)?://[A-Za-z0-9_.-]+:[A-Za-z0-9_!%+.-]{8,}@',
}


def main():
    errors, totals = [], {'text_files': 0, 'yaml_documents': 0, 'json_files': 0, 'python_files': 0, 'shell_blocks': 0, 'images': 0}
    for path in sorted(ROOT.rglob('*')):
        relative = path.relative_to(ROOT)
        if any(p in SKIP for p in relative.parts) or not path.is_file():
            continue
        if path.suffix == '.png':
            assert path.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'), relative
            totals['images'] += 1
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            errors.append(f'{relative}: unexpected binary file')
            continue
        totals['text_files'] += 1
        # The scanner's own pattern definitions are intentionally recognizable.
        if path != Path(__file__).resolve():
            for label, pattern in CHECKS.items():
                if re.search(pattern, text):
                    errors.append(f'{relative}: {label}; review privately')
        try:
            if path.suffix in ['.yaml', '.yml']:
                totals['yaml_documents'] += len(list(yaml.safe_load_all(text)))
            elif path.suffix == '.json':
                json.loads(text)
                totals['json_files'] += 1
            elif path.suffix == '.py':
                compile(text, str(relative), 'exec')
                totals['python_files'] += 1
            elif path.suffix == '.md':
                for target in re.findall(r'!?\[[^\]]*\]\(([^\s)]+)(?:\s+[^)]*)?\)', text):
                    if '://' in target or target.startswith(('#', 'mailto:')):
                        continue
                    target = target.split('#', 1)[0]
                    if target and not (path.parent / target).exists():
                        errors.append(f'{relative}: missing relative link {target}')
                for code in re.findall(r'^```(?:bash|sh)\n(.*?)^```', text, re.M | re.S):
                    result = subprocess.run(['bash', '-n'], input=code, text=True, capture_output=True)
                    if result.returncode:
                        errors.append(f'{relative}: invalid shell block')
                    totals['shell_blocks'] += 1
        except (ValueError, SyntaxError, yaml.YAMLError) as exc:
            errors.append(f'{relative}: invalid syntax ({type(exc).__name__})')
    if errors:
        print('\n'.join(errors))
        return 1
    print('PASS: offline syntax, links, PNG headers and basic publication-safety checks')
    print(json.dumps(totals, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())

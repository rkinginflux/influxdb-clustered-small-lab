#!/usr/bin/env python3
"""Build ignored influxctl profiles without logging tokens; no cluster access."""
import argparse
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['management', 'data'])
    args = parser.parse_args()
    local = Path(__file__).resolve().parent / '.local'
    local.mkdir(mode=0o700, exist_ok=True)
    local.chmod(0o700)
    # These endpoint defaults match the guide's localhost-only TLS forwarding.
    text = ('[[profile]]\nname = "default"\nproduct = "clustered"\n'
            'host = "localhost"\nport = "8443"\n')
    if args.mode == 'data':
        response = json.loads((local / 'data-token.json').read_text())
        token = response.get('token')
        if not isinstance(token, str) or not token:
            raise ValueError('Token response lacks a nonempty token string')
        text += 'database = "lab_smoke"\ntoken = ' + json.dumps(token) + '\n'
    text += '\n[profile.tls]\nca = ' + json.dumps(str(local / 'tls.crt')) + '\n'
    # The pinned Clustered CLI also initializes management authentication for
    # data commands. Actual database access still uses the scoped token above.
    text += ('\n[profile.auth.token]\ntoken_file = '
             + json.dumps(str(local / 'admin-token.json')) + '\n')
    fd = os.open(local / (args.mode + '.toml'),
                 os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(text)
    print('Generated private ' + args.mode + ' profile (not connected).')


if __name__ == '__main__':
    main()

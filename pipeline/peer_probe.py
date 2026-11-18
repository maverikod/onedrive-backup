'''Probe that runs INSIDE a disposable peer container of proxy_peer_auth and proxy_trust_independent (never on the host).

argv: <server-host> <requests-json-file>. Every request is {id, method, path, headers, body}; the answer is printed as one
JSON list of {id, status, body} (the first 300 bytes of the body). A transport failure prints status 0 and its text. Only
the standard library is used. The CA and the client certificate pair are read from the read-only mount /probe.
'''

from __future__ import annotations

import http.client
import json
import ssl
import sys


def send(context: ssl.SSLContext, host: str, item: dict) -> dict:
    '''Send one request over mTLS and return its {id, status, body}.'''
    conn = None
    try:
        conn = http.client.HTTPSConnection(host, 8050, context=context, timeout=20)
        body = item.get('body')
        conn.request(item['method'], item['path'], body=body.encode('utf-8') if body is not None else None,
                     headers=item.get('headers') or {})
        reply = conn.getresponse()
        return {'id': item['id'], 'status': reply.status, 'body': reply.read()[:300].decode('utf-8', 'replace')}
    except Exception as exc:
        return {'id': item['id'], 'status': 0, 'body': '%s: %s' % (type(exc).__name__, exc)}
    finally:
        if conn is not None:
            conn.close()


def main() -> int:
    host = sys.argv[1]
    with open(sys.argv[2], encoding='utf-8') as handle:
        requests = json.load(handle)
    context = ssl.create_default_context(cafile='/probe/ca.crt')
    context.load_cert_chain('/probe/client.crt', '/probe/client.key')
    print(json.dumps([send(context, host, item) for item in requests]))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

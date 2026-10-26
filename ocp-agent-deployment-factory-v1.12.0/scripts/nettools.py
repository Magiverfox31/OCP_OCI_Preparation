"""Network helpers that work when the usual tools are missing or blocked.

Locked-down bastions often lack `dig`/`curl`/`nc`, block ICMP (ping), or allow only TCP/53. These helpers use
only the Python standard library (Python 3.9+) so the factory's checks still run:

  * dns_query()   - small DNS client (UDP, with TCP fallback) used when `dig` is unavailable or forced off.
  * urllib_fetch() - HTTP(S) client with proxy, CA bundle and basic-auth support, used when `curl` is unavailable.

Nothing here uses ICMP. Reachability is always tested with TCP connections or real application requests.
"""
import base64
import ipaddress
import random
import socket
import ssl
import struct
import time
import urllib.error
import urllib.parse
import urllib.request

RCODES = {0: 'NOERROR', 1: 'FORMERR', 2: 'SERVFAIL', 3: 'NXDOMAIN', 4: 'NOTIMP', 5: 'REFUSED'}
QTYPES = {'A': 1, 'NS': 2, 'CNAME': 5, 'PTR': 12, 'AAAA': 28}
TYPE_NAMES = {v: k for k, v in QTYPES.items()}


class DnsError(Exception):
    pass


class _IdMismatch(DnsError):
    pass


class FetchError(Exception):
    """Transport-level HTTP failure (DNS, connect, TLS, timeout). The message mimics curl's wording."""


# ----------------------------------------------------------------------------- DNS wire format
def _encode_name(name):
    out = bytearray()
    for label in name.rstrip('.').split('.'):
        raw = label.encode('ascii')
        if not 0 < len(raw) < 64:
            raise DnsError('invalid DNS label in %r' % name)
        out.append(len(raw))
        out += raw
    out.append(0)
    return bytes(out)


def build_query(name, rtype, qid):
    """Standard recursive query: header (RD set), one question, class IN."""
    return struct.pack('!HHHHHH', qid, 0x0100, 1, 0, 0, 0) + _encode_name(name) + struct.pack('!HH', QTYPES[rtype], 1)


def _read_name(msg, pos):
    """Decode a (possibly compressed) name at pos. Returns (name, position after the name field)."""
    labels = []
    end = None
    hops = 0
    while True:
        if pos >= len(msg):
            raise DnsError('truncated name')
        n = msg[pos]
        if n == 0:
            pos += 1
            break
        if n & 0xC0 == 0xC0:
            if pos + 1 >= len(msg):
                raise DnsError('truncated compression pointer')
            if end is None:
                end = pos + 2
            hops += 1
            if hops > 20:
                raise DnsError('compression pointer loop')
            pos = ((n & 0x3F) << 8) | msg[pos + 1]
            continue
        if n & 0xC0:
            raise DnsError('unsupported label type')
        pos += 1
        if pos + n > len(msg):
            raise DnsError('truncated label')
        labels.append(msg[pos:pos + n].decode('ascii', 'replace'))
        pos += n
    return '.'.join(labels), (end if end is not None else pos)


def parse_response(msg, qid):
    """Parse a DNS response into {'status', 'answers': [(TYPE, value)], 'truncated'}."""
    if len(msg) < 12:
        raise DnsError('response shorter than a DNS header')
    rid, flags, qd, an = struct.unpack('!HHHH', msg[:8])
    if rid != qid:
        raise _IdMismatch('transaction id mismatch')
    if not flags & 0x8000:
        raise DnsError('not a response')
    pos = 12
    for _ in range(qd):
        _, pos = _read_name(msg, pos)
        pos += 4
    answers = []
    for _ in range(an):
        _, pos = _read_name(msg, pos)
        if pos + 10 > len(msg):
            raise DnsError('truncated resource record')
        rtype, _rclass, _ttl, rdlen = struct.unpack('!HHIH', msg[pos:pos + 10])
        pos += 10
        if pos + rdlen > len(msg):
            raise DnsError('truncated record data')
        tname = TYPE_NAMES.get(rtype)
        val = None
        if tname == 'A' and rdlen == 4:
            val = socket.inet_ntoa(msg[pos:pos + 4])
        elif tname == 'AAAA' and rdlen == 16:
            val = socket.inet_ntop(socket.AF_INET6, msg[pos:pos + 16])
        elif tname in ('PTR', 'CNAME', 'NS'):
            val = _read_name(msg, pos)[0].lower()
        if val is not None:
            answers.append((tname, val))
        pos += rdlen
    rcode = flags & 0xF
    return {'status': RCODES.get(rcode, 'RCODE%d' % rcode), 'answers': answers, 'truncated': bool(flags & 0x0200)}


# ----------------------------------------------------------------------------- DNS transports
def _udp_exchange(server, port, payload, qid, timeout):
    family = socket.AF_INET6 if ':' in server else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_DGRAM)
    try:
        sock.sendto(payload, (server, port))
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise socket.timeout()
            sock.settimeout(remaining)
            data, addr = sock.recvfrom(65535)
            if addr[0] != server:
                continue  # reply from an unexpected source; ignore like a real resolver
            try:
                return parse_response(data, qid)
            except _IdMismatch:
                continue
    finally:
        sock.close()


def _recv_exact(sock, n):
    buf = b''
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise DnsError('connection closed before the full response arrived')
        buf += chunk
    return buf


def _tcp_exchange(server, port, payload, qid, timeout):
    with socket.create_connection((server, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(struct.pack('!H', len(payload)) + payload)
        (length,) = struct.unpack('!H', _recv_exact(sock, 2))
        return parse_response(_recv_exact(sock, length), qid)


def dns_query(server, name, rtype, timeout=3, transport='auto', port=53, reverse=False):
    """Query one DNS server. Returns {'status','answers','via'} or {'error': text}.

    transport: 'udp', 'tcp', or 'auto' (UDP first; TCP when UDP gets no reply or the answer is truncated).
    reverse=True treats `name` as an IP address and asks for its PTR record.
    """
    try:
        if reverse:
            name = ipaddress.ip_address(name).reverse_pointer
        qid = random.randint(0, 65535)
        payload = build_query(name, rtype, qid)
    except (DnsError, ValueError, UnicodeEncodeError) as exc:
        return {'error': 'cannot build DNS query: %s' % exc}
    order = {'udp': ['udp'], 'tcp': ['tcp'], 'auto': ['udp', 'tcp']}[transport]
    errors = []
    for index, proto in enumerate(order):
        try:
            if proto == 'udp':
                res = _udp_exchange(server, port, payload, qid, timeout)
            else:
                res = _tcp_exchange(server, port, payload, qid, timeout)
        except socket.timeout:
            errors.append((proto, 'no reply from server (timeout, routing or firewall)'))
            continue
        except ConnectionRefusedError:
            errors.append((proto, 'connection refused by %s port %d (no DNS service listening or blocked)' % (server, port)))
            continue
        except DnsError as exc:
            errors.append((proto, 'invalid DNS response: %s' % exc))
            continue
        except OSError as exc:
            errors.append((proto, '%s' % (exc.strerror or exc)))
            continue
        if res['truncated'] and proto == 'udp' and 'tcp' in order[index + 1:]:
            errors.append((proto, 'answer truncated, retrying over TCP'))
            continue
        res['via'] = proto
        return res
    messages = [m for _, m in errors]
    if len(set(messages)) == 1 or len(errors) == 1:
        return {'error': messages[-1]}
    return {'error': '; '.join('%s: %s' % (proto.upper(), m) for proto, m in errors)}


# ----------------------------------------------------------------------------- HTTP
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # a redirect is an HTTP answer: the server is reachable


def _describe(reason, host):
    if isinstance(reason, socket.gaierror):
        return 'Could not resolve host: %s' % host
    if isinstance(reason, (socket.timeout, TimeoutError)):
        return 'Operation timed out'
    if isinstance(reason, ssl.SSLCertVerificationError):
        return 'SSL certificate problem: %s' % (getattr(reason, 'verify_message', None) or reason)
    if isinstance(reason, ssl.SSLError):
        return 'SSL connect error: %s' % reason
    if isinstance(reason, ConnectionRefusedError):
        return 'Failed to connect to %s: Connection refused' % host
    return str(reason)


def urllib_fetch(url, method='GET', timeout=10, proxy='', ca_bundle='', verify=True,
                 user='', password='', headers=None, max_body=4 * 1024 * 1024, direct=False):
    """HTTP(S) request without curl. Returns (status_code, body_text).

    Any HTTP status (including 3xx/4xx/5xx) is returned, not raised. Redirects are not followed.
    Transport problems raise FetchError. An empty proxy uses the standard http_proxy/https_proxy/no_proxy variables.
    """
    handlers = [_NoRedirect()]
    if proxy:
        handlers.append(urllib.request.ProxyHandler({'http': proxy, 'https': proxy}))
    elif direct:  # ignore http_proxy/https_proxy environment variables
        handlers.append(urllib.request.ProxyHandler({}))
    if url.lower().startswith('https://'):
        if verify:
            ctx = ssl.create_default_context(cafile=ca_bundle or None)
        else:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        handlers.append(urllib.request.HTTPSHandler(context=ctx))
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url, method=method, headers=dict(headers or {}))
    if user:
        token = base64.b64encode(('%s:%s' % (user, password)).encode('utf-8')).decode('ascii')
        req.add_header('Authorization', 'Basic ' + token)
    host = urllib.parse.urlparse(url).hostname or url
    try:
        resp = opener.open(req, timeout=timeout)
        try:
            return resp.status, resp.read(max_body).decode('utf-8', 'replace')
        finally:
            resp.close()
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(max_body).decode('utf-8', 'replace')
        except Exception:
            body = ''
        return exc.code, body
    except urllib.error.URLError as exc:
        raise FetchError(_describe(exc.reason, host))
    except (socket.timeout, TimeoutError):
        raise FetchError('Operation timed out')
    except ssl.SSLError as exc:
        raise FetchError(_describe(exc, host))
    except OSError as exc:
        raise FetchError(str(exc.strerror or exc))

import asyncio
import builtins
import re
import socket
import sys
import urllib.parse
from contextlib import contextmanager
from functools import wraps

import aiohttp

max_tries = 10


def convert_unit(s):
    """Convert sizes like 1M, 10k.

    >>> convert_unit('1')
    1
    >>> convert_unit('1B')
    1
    >>> convert_unit('10k')
    10240
    >>> convert_unit('1M') == 1024 * 1024
    True
    """
    num, unit = re.match(r'(\d+)([BKMG]?)', s, re.I).groups()
    units = {'B': 1, 'K': 1024, 'M': 1024 * 1024, 'G': 1024 * 1024 * 1024}
    return int(num) * units.get(unit.upper(), 1)


class HttpRange:
    """Class for iterating subrange.

    >>> r = HttpRange(0, 5)
    >>> r
    [0, 5]
    >>> list(r.iter_subrange(2))
    [[0, 1], [2, 3], [4, 5]]
    >>> list(HttpRange(0, 4).iter_subrange(2))
    [[0, 1], [2, 3], [4, 4]]
    >>> list(HttpRange(0, 1).iter_subrange(1))
    [[0, 0], [1, 1]]
    >>> list(HttpRange(1, 1).iter_subrange(1))
    [[1, 1]]
    >>> HttpRange.from_str('bytes=12-34', 35)
    [12, 34]
    >>> HttpRange.from_str('bytes=12-', 35)
    [12, 34]
    """
    pattern = re.compile(r'bytes=(\d+)-(\d*)')

    def __init__(self, begin, end):
        self.begin = begin
        self.end = end

    def __repr__(self):
        return '[{0.begin}, {0.end}]'.format(self)

    def size(self):
        return self.end - self.begin + 1

    @classmethod
    def from_str(cls, range_str, content_length):
        match = cls.pattern.match(range_str)
        if not match:
            raise ValueError
        begin, end = match.groups()
        begin = int(begin)
        end = int(end) if end else content_length - 1
        if begin > end:
            raise ValueError
        if end >= content_length:
            end = content_length - 1
        return cls(begin, end)

    def subranges(self, size):
        begin = self.begin
        end = begin + size - 1
        while begin <= self.end:
            if end >= self.end:
                end = self.end
            yield self.__class__(begin, end)
            begin = end + 1
            end += size


class RangeNotSupportedError(Exception):
    def __init__(self):
        # BaseException.__str__ returns the first argument
        # passed to BaseException.__init__.
        super().__init__('Range requests are not supported by the server.')


def retry(coro_func):
    @wraps(coro_func)
    async def wrapper(*args, **kwargs):
        tried = 0
        while True:
            tried += 1
            try:
                return await coro_func(*args, **kwargs)
            except (aiohttp.ClientError, socket.gaierror) as exc:
                try:
                    msg = f'{exc.status} {exc.message}'
                    # For 4xx client errors, it's no use to try again :)
                    if 400 <= exc.status < 500:
                        print(msg)
                        raise
                except AttributeError:
                    msg = str(exc) or exc.__class__.__name__

                if tried <= max_tries:
                    sec = tried / 2
                    print(f'{coro_func.__name__}() failed: {msg}, retry in '
                          f'{sec:.1f} seconds ({tried}/{max_tries})')
                    await asyncio.sleep(sec)
                else:
                    print(f'{coro_func.__name__}() failed after '
                          f'{max_tries} tries: {msg}')
                    raise

            except asyncio.TimeoutError:
                # Usually server has a fixed TCP timeout to clean dead
                # connections, so you can see a lot of timeouts appear
                # at the same time. I don't think this is an error,
                # So retry it without checking the max retries.
                print(f'{coro_func.__name__}() timed out, retry in 1 second')
                await asyncio.sleep(1)

    return wrapper


@contextmanager
def hook_print(print):
    save = builtins.print
    builtins.print = print
    try:
        yield
    finally:
        builtins.print = save


def load_browser_cookies(browser, url):
    if browser is None:
        return None

    # browsercookie can't get Chrome's cookie on Linux
    if sys.platform.startswith('linux') and (browser == 'chrome'
                                             or browser == 'chromium'):
        from pycookiecheat import chrome_cookies
        return chrome_cookies(url, browser=browser)
    else:
        import browsercookie
        from aiohttp.cookiejar import CookieJar

        def _is_domain_match(domain, hostname):
            # In aiohttp, this is done in previous steps.
            if domain.startswith('.'):
                domain = domain[1:]
            return CookieJar._is_domain_match(domain, hostname)

        with hook_print(lambda *_: None):
            jar = getattr(browsercookie, browser)()
        host = urllib.parse.urlsplit(url).netloc
        return {
            cookie.name: cookie.value
            for cookie in jar if _is_domain_match(cookie.domain, host)
        }

import asyncio
import builtins
import functools
import re
import socket
import sys
from contextlib import contextmanager

import aiohttp

# FIXME
max_tries = 10


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
    >>> HttpRange.from_str('bytes=12-34')
    [12, 34]
    >>> HttpRange.from_str('bytes=12-', 34)
    [12, 33]
    """
    pattern = re.compile(r'bytes=(\d+)-(\d*)')

    def __init__(self, begin, end):
        self.begin = begin
        self.end = end

    @classmethod
    def from_str(cls, range_str, content_length=None):
        begin, end = cls.pattern.match(range_str).groups()
        begin = int(begin)
        end = int(end) if end else content_length - 1
        if begin > end:
            raise ValueError
        return cls(begin, end)

    def __repr__(self):
        return '[{0.begin}, {0.end}]'.format(self)

    def __iter__(self):
        yield self.begin
        yield self.end

    def iter_subrange(self, size):
        begin = self.begin
        end = begin + size - 1
        if end >= self.end:
            yield self.__class__(begin, self.end)
            return
        while True:
            yield self.__class__(begin, end)
            begin = end + 1
            end += size
            if end >= self.end:
                yield self.__class__(begin, self.end)
                return

    def size(self):
        return self.end - self.begin + 1


def retry(coro_func):
    @functools.wraps(coro_func)
    async def wrapper(*args, **kwargs):
        tried = 0
        while True:
            tried += 1
            try:
                return await coro_func(*args, **kwargs)
            except (aiohttp.ClientError, socket.gaierror) as exc:
                try:
                    msg = '%d %s' % (exc.code, exc.message)
                    # For 4xx client errors, it's no use to try again :)
                    if 400 <= exc.code < 500:
                        print(msg)
                        raise
                except AttributeError:
                    msg = str(exc) or exc.__class__.__name__
                if tried <= max_tries:
                    sec = tried / 2
                    print(
                        '%s() failed: %s, retry in %.1f seconds (%d/%d)' %
                        (coro_func.__name__, msg,
                         sec, tried, max_tries)
                    )
                    await asyncio.sleep(sec)
                else:
                    print(
                        '%s() failed after %d tries: %s ' %
                        (coro_func.__name__, max_tries, msg)
                    )
                    raise
            except asyncio.TimeoutError:
                # Usually server has a fixed TCP timeout to clean dead
                # connections, so you can see a lot of timeouts appear
                # at the same time. I don't think this is an error,
                # So retry it without checking the max retries.
                print('%s() timeout, retry in 1 second' % coro_func.__name__)
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

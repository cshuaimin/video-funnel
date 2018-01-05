import asyncio
import functools
import re
import socket

import aiohttp
from aiohttp import web

url = None
max_tries = None
block_size = None
piece_size = None
timeout = None
loop = asyncio.get_event_loop()
session = None


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


class Funnel:
    def __init__(self, url, range, headers):
        self.url = url
        self.range = range
        self.headers = headers
        self.q = asyncio.Queue(maxsize=2)

    async def __aenter__(self):
        self.producer = asyncio.ensure_future(self.produce_blocks())
        return self

    async def __aexit__(self, *_):
        self.producer.cancel()
        while not self.q.empty():
            self.q.get_nowait()
        await self.producer

    # needs Python 3.6
    async def __aiter__(self):
        while not (self.producer.done() and self.q.empty()):
            chunk = await self.q.get()
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk

    @retry
    async def request_range(self, range):
        headers = self.headers.copy()
        headers['Range'] = 'bytes={}-{}'.format(*range)
        async with session.get(self.url, headers=headers,
                               timeout=timeout) as resp:
            resp.raise_for_status()
            assert resp.status == 206
            data = await resp.read()
            print(f'  Piece {range} done.')
            return data

    async def produce_blocks(self):
        for block in self.range.iter_subrange(block_size):
            print(f'Start to download {block.size()} bytes...')
            futures = [
                asyncio.ensure_future(self.request_range(r))
                for r in block.iter_subrange(piece_size)
            ]
            try:
                results = await asyncio.gather(*futures)
                await self.q.put(b''.join(results))
                print('done')
            except (asyncio.CancelledError, aiohttp.ClientError) as exc:
                for f in futures:
                    f.cancel()
                # Notify the consumer to leave
                # -- which is waiting at the end of this queue!
                await self.q.put(exc)
                return


async def handle_get(request):
    async with session.head(url, allow_redirects=True) as resp:
        if resp.status >= 400:
            return web.Response(status=resp.status, headers=resp.headers)
        upstream_headers = dict(resp.headers)
    #  del request.headers['Host']  # FIXME
    content_length = int(upstream_headers['Content-Length'])
    range = request.headers.get('Range')
    if range is None:
        # not a Range request - the whole file
        range = HttpRange(0, content_length - 1)
        status = 200
    else:
        try:
            range = HttpRange.from_str(range, content_length)
        except ValueError:
            # From RFC7233:
            # A server generating a 416 (Range Not Satisfiable) response to a
            # byte-range request SHOULD send a Content-Range header field with
            # an unsatisfied-range value, as in the following example:
            # Content-Range: bytes */1234
            upstream_headers['Content-Range'] = f'*/{content_length}'
            del upstream_headers['Content-Length']
            return web.Response(status=416, headers=upstream_headers)
        else:
            status = 206
            upstream_headers['Content-Range'] = \
                f'bytes {range.begin}-{range.end}/{content_length}'
    resp = web.StreamResponse(status=status, headers=upstream_headers)
    await resp.prepare(request)
    async with Funnel(url, range, request.headers) as funnel:
        try:
            async for chunk in funnel:
                resp.write(chunk)
                await resp.drain()
        except aiohttp.ClientError as exc:
            print(str(exc))
            return web.Response(status=exc.code)
        return resp


async def handle_head(request):
    r = await session.head(url, headers=request.headers)
    return web.Response(status=r.status, headers=r.headers)


def start_server(args):
    global url, block_size, piece_size, max_tries, timeout, session
    url = args.url
    block_size = args.block_size
    piece_size = args.piece_size
    max_tries = args.max_tries
    timeout = args.timeout
    session = aiohttp.ClientSession(loop=loop)

    app = web.Application()
    app.router.add_get('/', handle_get, allow_head=False)
    app.router.add_head('/', handle_head)
    try:
        web.run_app(app, loop=loop)
    except KeyboardInterrupt:
        pass
    finally:
        session.close()
        loop.stop()
        loop.run_forever()
        loop.close()

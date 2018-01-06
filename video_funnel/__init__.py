import asyncio

import aiohttp
from aiohttp import web
from .utils import HttpRange, retry


class Funnel:
    def __init__(self, session, url, range, block_size, piece_size, timeout):
        self.session = session
        self.url = url
        self.range = range
        self.block_size = block_size
        self.piece_size = piece_size
        self.timeout = timeout
        self.q = asyncio.Queue(maxsize=2)

    async def __aenter__(self):
        self.producer = asyncio.ensure_future(self.produce_blocks())
        return self

    async def __aexit__(self, type, value, tb):
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
        headers = {'Range': 'bytes={}-{}'.format(*range)}
        async with self.session.get(self.url, headers=headers,
                                    timeout=self.timeout) as resp:
            resp.raise_for_status()
            if resp.status != 206:
                raise aiohttp.ClientError(f'Server returned {resp.status} for '
                                          'a range request (should be 206).')
            data = await resp.read()
            print(f'  Piece {range} done.')
            return data

    async def produce_blocks(self):
        for block in self.range.iter_subrange(self.block_size):
            print(f'Start to download {block.size()} bytes...')
            futures = [
                asyncio.ensure_future(self.request_range(r))
                for r in block.iter_subrange(self.piece_size)
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


routes = web.RouteTableDef()


@routes.get('/')
async def funnel(request):
    if request.app['session'] is None:
        del request.headers['Host']
        request.app['session'] = aiohttp.ClientSession(headers=request.headers)

    url = request.query.get('url')
    if url is None:
        url = request.app['args'].url
    if url is None:
        return web.Response(status=422, text='No URL')
    async with request.app['session'].head(url, allow_redirects=True) as resp:
        if resp.status == 409:
            print('409:', url, resp.request_info)
        if resp.status >= 400 or request.method == 'HEAD':
            return web.Response(status=resp.status, headers=resp.headers)

    headers = dict(resp.headers)
    content_length = int(headers['Content-Length'])
    range = headers.get('Range')
    if range is None:
        # not a Range request - the whole file
        range = HttpRange(0, content_length - 1)
        status = 200
    else:
        try:
            range = HttpRange.from_str(range, content_length)
        except ValueError:
            del headers['Content-Length']
            headers['Content-Range'] = f'*/{content_length}'
            return web.Response(status=416, headers=headers)
        else:
            status = 206
            headers['Content-Range'] = \
                f'bytes {range.begin}-{range.end}/{content_length}'
    resp = web.StreamResponse(status=status, headers=headers)
    await resp.prepare(request)
    args = request.app['args']
    async with Funnel(request.app['session'], url, range,
                      block_size=args.block_size,
                      piece_size=args.piece_size,
                      timeout=args.timeout) as funnel:
        try:
            async for chunk in funnel:
                resp.write(chunk)
                await resp.drain()
            return resp
        except aiohttp.ClientError as exc:
            print(exc)
            return web.Response(status=exc.code)
        except asyncio.CancelledError:
            print('Cancelled')
            raise

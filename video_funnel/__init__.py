import asyncio
from contextlib import suppress

import aiohttp
from aiohttp import web
from tqdm import tqdm

from .utils import HttpRange, hook_print, load_browser_cookies, retry


class Funnel:
    def __init__(self, session, url, range,
                 block_size, piece_size, timeout, disable_bar):
        self.session = session
        self.url = url
        self.range = range
        self.block_size = block_size
        self.piece_size = piece_size
        self.timeout = timeout
        self.disable_bar = disable_bar
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
    async def request_range(self, range, bar):
        headers = {'Range': 'bytes={}-{}'.format(*range)}
        async with self.session.get(self.url, headers=headers,
                                    timeout=self.timeout) as resp:
            resp.raise_for_status()
            if resp.status != 206:
                raise aiohttp.ClientError(f'Server returned {resp.status} for '
                                          'a range request (should be 206).')
            data = b''
            async for chunk in resp.content.iter_any():
                bar.update(len(chunk))
                data += chunk
            return data

    async def produce_blocks(self):
        for nr, block in enumerate(self.range.iter_subrange(self.block_size)):
            with tqdm(disable=self.disable_bar, desc=f'Block #{nr}',
                      leave=False, dynamic_ncols=True,
                      total=block.size(),
                      unit='B', unit_scale=True, unit_divisor=1024
                      ) as bar, hook_print(bar.write):
                futures = [
                    asyncio.ensure_future(self.request_range(r, bar))
                    for r in block.iter_subrange(self.piece_size)
                ]
                try:
                    results = await asyncio.gather(*futures)
                    await self.q.put(b''.join(results))
                except (asyncio.CancelledError, aiohttp.ClientError) as exc:
                    for f in futures:
                        f.cancel()
                    # Notify the consumer to leave
                    # -- which is waiting at the end of this queue!
                    await self.q.put(exc)
                    return


async def handler(request):
    args = request.app['args']
    range = request.headers.get('Range')

    if request.app['session'] is None:
        with suppress(KeyError):
            del request.headers['Host']
            del request.headers['Range']
        if args.with_cookies:
            cookies = load_browser_cookies(args.with_cookies, args.url)
        else:
            cookies = None
        del request.headers['user-agent']
        request.app['session'] = aiohttp.ClientSession(
            headers=request.headers,
            cookies=cookies
        )

    url = args.url
    async with request.app['session'].head(url, allow_redirects=True) as resp:
        headers = dict(resp.headers)
        if resp.status >= 400 or request.method == 'HEAD':
            del headers['Content-Length']
            return web.Response(status=resp.status, headers=headers)

    # Prevent downloading if we open <localhost:8080> in the browser.
    with suppress(KeyError):
        del headers['Content-Disposition']
    content_length = int(headers['Content-Length'])
    del headers['Content-Length']
    # Note that there are two headers:
    #   1. request.headers is sent by the player
    #   2. headers is the remote server replied to us.
    if range is None:
        # not a Range request - the whole file
        range = HttpRange(0, content_length - 1)
        status = 200
    else:
        try:
            range = HttpRange.from_str(range, content_length)
        except ValueError:
            headers['Content-Type'] = 'text/html'
            headers['Content-Range'] = f'*/{content_length}'
            return web.Response(
                status=416, headers=headers,
                text='<html>416 Requested Range Not Satisfiable</html>'
            )
        else:
            status = 206
            headers['Content-Range'] = \
                f'bytes {range.begin}-{range.end}/{content_length}'
    resp = web.StreamResponse(status=status, headers=headers)
    await resp.prepare(request)
    async with Funnel(request.app['session'], url, range,
                      block_size=args.block_size,
                      piece_size=args.piece_size,
                      timeout=args.timeout,
                      disable_bar=args.disable_bar) as funnel:
        try:
            async for chunk in funnel:
                await resp.write(chunk)
            return resp
        except aiohttp.ClientError as exc:
            print(exc)
            return web.Response(status=exc.code)
        except asyncio.CancelledError:
            print('Cancelled')
            raise

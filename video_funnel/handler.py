import asyncio

import aiohttp
from aiohttp import web

from .funnel import Funnel
from .utils import HttpRange, Not206Error


async def handler(request):
    base_headers = {
        'Content-Length': request.app['content_length'],
        'Content-Type': request.app['content_type']
    }
    content_length = int(request.app['content_length'])
    range = request.headers.get('Range')
    if range is None:
        # not a Range request - the whole file
        range = HttpRange(0, content_length - 1)
        resp = web.StreamResponse(
            status=200, headers={
                **base_headers, 'Accept-Ranges': 'bytes'
            })
    else:
        try:
            range = HttpRange.from_str(range, content_length)
        except ValueError:
            return web.Response(
                status=416, headers={'Content-Range': f'*/{content_length}'})
        else:
            resp = web.StreamResponse(
                status=206,
                headers={
                    **base_headers, 'Content-Range':
                    f'bytes {range.begin}-{range.end}/{content_length}'
                })

    if request.method == 'HEAD':
        return resp

    await resp.prepare(request)
    args = request.app['args']
    async with Funnel(
            args.url,
            range,
            request.app['session'],
            args.block_size,
            args.piece_size,
    ) as funnel:
        try:
            async for chunk in funnel:
                await resp.write(chunk)
            return resp
        except (aiohttp.ClientError, Not206Error) as exc:
            print(exc)
            return web.Response(status=exc.code)
        except asyncio.CancelledError:
            print('Cancelled')
            raise

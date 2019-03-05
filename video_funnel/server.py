import asyncio
import sys

import aiohttp
from aiohttp import web

from .funnel import Funnel
from .utils import HttpRange, Not206Error, load_browser_cookies


async def make_response(request, url, block_size, piece_size, original_url):
    session = request.app['session']
    async with session.head(url, allow_redirects=True) as resp:
        if resp.headers.get('Accept-Ranges') != 'bytes':
            print(
                'Range requests are not supported by the server.',
                file=sys.stderr,
            )
            return
        if not original_url:
            url = resp.url
        content_length = int(resp.headers['Content-Length'])

    range = request.headers.get('Range')
    if range is None:
        # not a Range request - the whole file
        range = HttpRange(0, content_length - 1)
        resp = web.StreamResponse(
            status=200,
            headers={
                'Content-Length': f'{content_length}',
                'Accept-Ranges': 'bytes'
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
                    'Content-Range':
                    f'bytes {range.begin}-{range.end}/{content_length}'
                })

    if request.method == 'HEAD':
        return resp

    await resp.prepare(request)
    args = request.app['args']
    async with Funnel(
            url,
            range,
            session,
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


routes = web.RouteTableDef()


@routes.get('/')
@routes.get('/{_:https?://.+}')
async def cli(request):
    args = request.app['args']
    url = request.raw_path[1:] or args.url
    return await make_response(
        request,
        url,
        args.block_size,
        args.piece_size,
        args.original_url,
    )


@routes.get('/api')
async def api(request):
    args = request.app['args']
    query = request.query
    return await make_response(
        request,
        query.get('url', args.url),
        query.get('block_size', args.block_size),
        query.get('piece_size', args.piece_size),
        query.get('original_url', args.original_url),
    )


async def make_app(args):
    app = web.Application()
    app.add_routes(routes)
    app['args'] = args

    async def session(app):
        app['session'] = aiohttp.ClientSession(
            raise_for_status=True,
            cookies=load_browser_cookies(args.cookies, args.url))
        yield
        await app['session'].close()

    app.cleanup_ctx.append(session)

    return app

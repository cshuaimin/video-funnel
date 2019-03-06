import asyncio

import aiohttp
from aiohttp import web

from .funnel import Funnel
from .utils import (
    HttpRange,
    RangeNotSupportedError,
    load_browser_cookies,
    retry,
    convert_unit,
)


async def make_response(request, url, block_size, piece_size, cookies_from,
                        use_original_url):
    session = request.app['session']
    session.cookie_jar.update_cookies(load_browser_cookies(cookies_from, url))

    @retry
    async def get_content_length():
        nonlocal url
        async with session.head(url, allow_redirects=True) as resp:
            if resp.headers.get('Accept-Ranges') != 'bytes':
                raise RangeNotSupportedError
            if not use_original_url:
                url = resp.url
            return int(resp.headers['Content-Length'])

    try:
        content_length = await get_content_length()
    except RangeNotSupportedError as exc:
        msg = str(exc)
        print(msg)
        return web.Response(status=501, text=msg)
    except aiohttp.ClientError as exc:
        print(exc)
        return web.Response(status=exc.status)

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
    async with Funnel(
            url,
            range,
            session,
            block_size,
            piece_size,
    ) as funnel:
        try:
            async for chunk in funnel:
                await resp.write(chunk)
            return resp
        except (aiohttp.ClientError, RangeNotSupportedError) as exc:
            print(exc)
            return web.Response(status=exc.status)
        except asyncio.CancelledError:
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
        args.cookies_from,
        args.use_original_url,
    )


@routes.get('/api')
async def api(request):
    args = request.app['args']
    query = request.query
    block_size = convert_unit(query.get('block_size', args.block_size))
    piece_size = convert_unit(query.get('piece_size', args.piece_size))
    return await make_response(
        request,
        query.get('url', args.url),
        block_size,
        piece_size,
        query.get('cookies_from', args.cookies_from),
        query.get('use_original_url', args.use_original_url),
    )


async def make_app(args):
    app = web.Application()
    app.add_routes(routes)
    app['args'] = args

    async def session(app):
        app['session'] = aiohttp.ClientSession(raise_for_status=True)
        yield
        await app['session'].close()

    app.cleanup_ctx.append(session)

    return app

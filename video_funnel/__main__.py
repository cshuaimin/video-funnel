import asyncio
import re
from argparse import ArgumentParser
from sys import stderr

from aiohttp import ClientSession, web

from .handler import handler
from .utils import load_browser_cookies


def convert_unit(s):
    num, unit = re.match(r'(\d+)([BKMG]?)', s, re.I).groups()
    units = {'B': 1, 'K': 1024, 'M': 1024 * 1024, 'G': 1024 * 1024 * 1024}
    return int(num) * units[unit.upper() or 'B']


def make_args():
    ap = ArgumentParser(
        description='Video Funnel -- Use multiple connections to request the '
        'video, then feed the combined data to the player.')

    ap.add_argument('url', metavar='URL', help='the video url')
    ap.add_argument('--port', type=int, default=2345, help='port to listen')
    ap.add_argument(
        '--block-size',
        '-b',
        metavar='N',
        type=convert_unit,
        default='4M',
        help='size of one block')
    ap.add_argument(
        '--piece-size',
        '-p',
        metavar='N',
        type=convert_unit,
        default='1M',
        help='size of one piece')
    ap.add_argument(
        '--max-tries',
        '-r',
        type=int,
        metavar='N',
        default=10,
        help='Limit retries on network errors.')
    ap.add_argument(
        '--load-cookies',
        '-c',
        choices=['chrome', 'chromium', 'firefox'],
        help='load browser cookies')
    ap.add_argument(
        '--original-url',
        '-g',
        action='store_true',
        help='always use the original URL '
        '(no optimization for 3XX response code)')

    return ap.parse_args()


async def main():
    args = make_args()
    app = web.Application()
    app.router.add_get('/', handler)
    app['args'] = args

    app['session'] = session = ClientSession(
        raise_for_status=True,
        cookies=load_browser_cookies(args.load_cookies, args.url))

    async with session.head(args.url, allow_redirects=True) as resp:
        if resp.headers.get('Accept-Ranges') != 'bytes':
            print(
                'Range requests are not supported by the server.',
                file=stderr,
            )
            return
        if not args.original_url:
            args.url = resp.url

        app['content_length'] = resp.headers['Content-Length']
        app['content_type'] = resp.headers['Content-Type']

    async def close_session(app):
        await session.close()

    app.on_cleanup.append(close_session)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', args.port)
    await site.start()
    print(f'* Listening at port {args.port} ...')
    try:
        await asyncio.sleep(float('inf'))
    finally:
        await runner.cleanup()


try:
    asyncio.run(main())
except KeyboardInterrupt:
    pass

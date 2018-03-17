import asyncio
import re
from argparse import ArgumentParser

from aiohttp import web

from .__init__ import handler


def convert_unit(s):
    n, u = re.match(r'(\d+)([BKMG]?)', s, re.I).groups()
    units = {'B': 1, 'K': 1024, 'M': 1024 * 1024, 'G': 1024 * 1024 * 1024}
    return int(n) * units[u.upper() or 'B']


def main():
    ap = ArgumentParser(description='Funnel -- Use multiple connections to request the video, then feed the combined data to the player.')
    ap.add_argument('url', metavar='URL', help='the video url')
    ap.add_argument('--port', type=int, help='port to listen')
    ap.add_argument('--block-size', '-b', metavar='N', type=convert_unit, default='4M',
                    help='size of one block')
    ap.add_argument('--piece-size', '-p', metavar='N', type=convert_unit, default='1M',
                    help='size of one piece')
    ap.add_argument('--disable-bar', '-q', action='store_true',
                    help="Don't show the progress bar for each block")
    ap.add_argument('--timeout', '-t', type=int, metavar='N', default=60,
                    help='timeout in request')
    ap.add_argument('--max-tries', '-r', type=int, metavar='N', default=10,
                    help='Limit retries on network errors.')
    ap.add_argument('--with-cookies', '-c', choices=['chrome', 'firefox'],
                    help="Choose one browser to load cookies (usually combining two browsers' cookies does not work).")
    args = ap.parse_args()

    app = web.Application()
    app.router.add_get('/', handler)
    app['args'] = args
    app['session'] = None
    try:
        print(f'* Listening at port {args.port or 8080} ...')
        web.run_app(
            app,
            print=None,
            port=args.port,
            loop=asyncio.get_event_loop()
        )
    except KeyboardInterrupt:
        pass
    finally:
        try:
            app['session'].close()
        except AttributeError:
            pass
        loop = asyncio.get_event_loop()
        loop.stop()
        loop.run_forever()
        loop.close()


if __name__ == '__main__':
    main()

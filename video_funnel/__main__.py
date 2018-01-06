import asyncio
import re

from aiohttp import web
from argparse import ArgumentParser
from .__init__ import routes


def convert_unit(s):
    n, u = re.match(r'(\d+)([BKMG]?)', s, re.I).groups()
    units = {'B': 1, 'K': 1024, 'M': 1024 * 1024, 'G': 1024 * 1024 * 1024}
    return int(n) * units[u.upper() or 'B']


def main():
    ap = ArgumentParser(description='Funnel -- Use multiple connections to request the video, then feed the combined data to the player.')
    ap.add_argument('--url', '-u', help='the video url')
    ap.add_argument('--block-size', '-b', type=convert_unit, default='8M',
                    help='size of one block')
    ap.add_argument('--piece-size', '-p', type=convert_unit, default='1M',
                    help='size of one piece')
    ap.add_argument('--timeout', '-t', type=int, default=60,
                    help='timeout in request')
    ap.add_argument('--max-tries', '-r', type=int, default=10,
                    help='Limit retries on network errors.')
    args = ap.parse_args()

    app = web.Application(debug=True)
    app.router.add_routes(routes)
    app['args'] = args
    app['session'] = None
    #  import aiohttp_debugtoolbar
    #  aiohttp_debugtoolbar.setup(app)
    try:
        web.run_app(app, loop=asyncio.get_event_loop())
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

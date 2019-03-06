from argparse import ArgumentParser

from aiohttp import web

from .server import make_app


def make_args():
    ap = ArgumentParser(
        description='Video Funnel -- Use multiple connections to request the '
        'video, then feed the combined data to the player.')

    ap.add_argument(
        '--url',
        '-u',
        help='the video url, omitting it to run VF in WebUI mode '
        '(in this mode, http://127.0.0.1:8080 returns the WebUI '
        'instead of the video stream)')
    ap.add_argument('--port', type=int, default=8080, help='port to listen')
    ap.add_argument(
        '--block-size',
        '-b',
        metavar='N',
        default='4M',
        help='size of one block')
    ap.add_argument(
        '--piece-size',
        '-p',
        metavar='N',
        default='1M',
        help='size of one piece')
    ap.add_argument(
        '--cookies-from',
        '-c',
        choices=['chrome', 'chromium', 'firefox'],
        help='load browser cookies')
    ap.add_argument(
        '--use-original-url',
        '-g',
        action='store_true',
        help='always use the original URL '
        '(no optimization for 3XX response code)')

    return ap.parse_args()


def main():
    args = make_args()
    print(f'* Listening at port {args.port} ...')
    web.run_app(make_app(args), print=None, port=args.port)


if __name__ == '__main__':
    main()

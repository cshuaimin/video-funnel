import re
from argparse import ArgumentParser
from .__init__ import start_server


def convert_unit(s):
    n, u = re.match(r'(\d+)([BKMG]?)', s, re.I).groups()
    units = {'B': 1, 'K': 1024, 'M': 1024 * 1024, 'G': 1024 * 1024 * 1024}
    return int(n) * units[u.upper() or 'B']


ap = ArgumentParser(description='Funnel')
ap.add_argument('url', help='the movie url')
ap.add_argument('--block-size', '-b', type=convert_unit, default='8M',
                help='size of one block')
ap.add_argument('--piece-size', '-p', type=convert_unit, default='1M',
                help='size of one piece')
ap.add_argument('--timeout', '-t', type=int, default=60,
                help='timeout in request')
ap.add_argument('--max-tries', '-r', type=int, default=10,
                help='Limit retries on network errors.')


def main():
    args = ap.parse_args()
    start_server(args)


if __name__ == '__main__':
    main()

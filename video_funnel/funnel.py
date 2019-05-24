import asyncio
from io import BytesIO

import aiohttp
from tqdm import tqdm

from .utils import RangeNotSupportedError, hook_print, retry


class Funnel:
    def __init__(self, url, range, session, block_size, piece_size):
        self.url = url
        self.range = range
        self.session = session
        self.block_size = block_size
        self.piece_size = piece_size
        self.blocks = asyncio.Queue(maxsize=2)

    async def __aenter__(self):
        self.producer = asyncio.ensure_future(self.produce_blocks())
        return self

    async def __aexit__(self, type, value, tb):
        self.producer.cancel()
        while not self.blocks.empty():
            self.blocks.get_nowait()
        await self.producer

    # needs Python 3.6
    async def __aiter__(self):
        while not (self.producer.done() and self.blocks.empty()):
            chunk = await self.blocks.get()
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk

    @retry
    async def request_range(self, range, bar):
        headers = {'Range': 'bytes={0.begin}-{0.end}'.format(range)}
        async with self.session.get(self.url, headers=headers) as resp:
            if resp.status != 206:
                raise RangeNotSupportedError
            async for chunk in resp.content.iter_any():
                self.buffer.seek(range.begin)
                self.buffer.write(chunk)
                bar.update(len(chunk))
                range.begin += len(chunk)

    async def produce_blocks(self):
        for nr, block in enumerate(self.range.subranges(self.block_size)):
            with tqdm(
                    desc=f'Block #{nr}',
                    leave=False,
                    dynamic_ncols=True,
                    total=block.size(),
                    unit='B',
                    unit_scale=True,
                    unit_divisor=1024) as bar, hook_print(bar.write):

                self.buffer = BytesIO()
                futures = [
                    asyncio.ensure_future(self.request_range(r, bar))
                    for r in block.subranges(self.piece_size)
                ]
                try:
                    await asyncio.gather(*futures)
                    await self.blocks.put(self.buffer.getvalue())
                except (asyncio.CancelledError, aiohttp.ClientError) as exc:
                    for f in futures:
                        f.cancel()
                    #  Notify the consumer to leave
                    #  -- which is waiting at the end of this queue!
                    await self.blocks.put(exc)
                    return

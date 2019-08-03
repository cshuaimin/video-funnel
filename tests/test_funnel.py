import asyncio
from io import BytesIO
from random import getrandbits

from aiohttp import web

from video_funnel.funnel import Funnel
from video_funnel.utils import HttpRange


async def test_funnel(tmp_path, aiohttp_client):
    tmp_file = tmp_path / 'test'
    data = bytes(getrandbits(8) for _ in range(16))
    tmp_file.write_bytes(data)

    async def serve_file(request):
        # FileResponse supports range requests.
        return web.FileResponse(tmp_file)

    app = web.Application()
    app.router.add_get('/', serve_file)
    session = await aiohttp_client(app)

    async def test(block_size, piece_size):
        r = HttpRange(0, len(data) - 1)
        buf = BytesIO()
        async with Funnel(
                url='/',
                range=r,
                session=session,
                block_size=block_size,
                piece_size=piece_size) as funnel:
            async for block in funnel:
                buf.write(block)
        assert buf.getvalue() == data

    tests = []
    for block_size in range(1, len(data) + 1):
        for piece_size in range(1, block_size + 1):
            tests.append(asyncio.create_task(test(block_size, piece_size)))
    await asyncio.gather(*tests)

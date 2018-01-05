<p align="center"><img src="funnel.png" /></p>
<h1 align="center">Video Funnel</h1>
<p align="center"><a href="https://badge.fury.io/py/video_funnel"><img src="https://badge.fury.io/py/video_funnel.svg" alt="PyPI version" height="18"></a></p>
<p align="center">让你在线看视频也能达到多线程下载的速度</p>

***

#### 马上使用：

1. 从 [PyPI](https://pypi.python.org/pypi/video_funnel) 安装：
```bash
$ pip(3) install --user video_funnel
# or
$ sudo pip(3) install video_funnel
```

2. 启动 `video_funnel` 的服务器：
```bash
$ vf http://tulip.ink/test.mp4 &
======== Running on http://0.0.0.0:8080 ========
(Press CTRL+C to quit)
```

3. 用 `mpv` 播放：
```bash
$ mpv http://localhost:8080
```

#### 动机：

众所周知，百度网盘之类产品的视频在线播放非常模糊，下载吧又限速，于是我写了 [aiodl](https://github.com/cshuaimin/aiodl) 这个下载器，通过 [EX-百度云盘](https://github.com/gxvv/ex-baiduyunpan/) 获取的直链来“多线程”下载。可是每次都要下载完才能看又十分不爽，直接用 mpv 之类的播放器播放直链又因为限速的原因根本没法看，遂有了本项目。

#### 实现思路：

1. 先将视频按照一定大小分块。块的大小根据视频的清晰度而异，以下载完一个块后视频可以播放为准。可通过命令行参数 `--block-size/-b` 来指定，默认为 8MB 。
2. 对于上一步中的一个块，再次分块——为区别改叫切片，启动多个协程来下载这些切片，以实现“多线程”提速的目的。块和切片大小一起决定了有多少个连接在同时下载。切片的大小通过 `--piece-size/-p` 来指定，默认为 1MB 。
3. 一个块中的切片全部下载完后，就可以将数据传给播放器了。当播放器播放这一块的时候，回到第 2 步下载下一块数据。为节省内存，设置了在内存中最多存在 2 个下载完而又没有传给播放器的块。

#### 一些细节：

1. 该如何把数据传给播放器呢？我最初的设想是通过标准输出，这样简单好写。但 stdio 是无法 seek 的，这就意味着你只能从视频的开头看起，无法快进 :P
如你所见，现在的解决方案是用 HTTP 协议与播放器传输数据。需要快进的时候播放器发送 HTTP Range 请求，video_funnel 将请求中的范围经过分块、切片后“多线程”下载。但这样就又带来了两个问题：
    1. 需要播放器支持从 URL 播放。mplayer、mpv 之类的命令行播放器大多都支持，但一些 Windows 的播放器就不得而知了 :P 不过可以使用 HTML 的 video 标签在浏览器播放。
    2. 怎么就没有处理 Range 请求的包啊，自己处理很麻烦的好吗～

2. 由于下载的部分是用异步 IO 写的，与播放器交互的服务器部分就不能使用 Flask 之类阻塞的框架了，幸好 aiohttp 居然同时支持客户端和服务端。

3. 说起来简单，实际写起来处处是坑啊 :(

<p align="center"><img src="funnel.png" /></p>
<h1 align="center">Video Funnel</h1>
<p align="center"><a href="https://badge.fury.io/py/video-funnel"><img src="https://badge.fury.io/py/video-funnel.svg" alt="PyPI version" height="18"></a></p>
<p align="center">让你在线看视频也能达到多线程下载的速度</p>

***
> 最近百度网盘的外链不带登录 cookie 访问总会返回 4xx 错误，`video_funnel` 新增命令行参数 `--with-cookies`。

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
* Listening at port 8080 ...
```

3. 用 `vlc` 播放：
```bash
$ vlc http://localhost:8080
```
`mpv` 播放时会出现 `Seek failed` 的错误，原因未知（如果有路过的大神遇见过类似情况，请一定给我解释下～） #2

#### 动机：

众所周知，百度网盘之类产品的视频在线播放非常模糊，下载吧又限速，于是我写了 [aiodl](https://github.com/cshuaimin/aiodl) 这个下载器，通过 [EX-百度云盘](https://github.com/gxvv/ex-baiduyunpan/) 获取的直链来“多线程”下载。可是每次都要下载完才能看又十分不爽，直接用 mpv 之类的播放器播放直链又因为限速的原因根本没法看，遂有了本项目。

#### 实现思路：

1. 先将视频按照一定大小分块。块的大小根据视频的清晰度而异，以下载完一个块后视频可以播放为准。可通过命令行参数 `--block-size/-b` 来指定，默认为 4MB 。
2. 对于上一步中的一个块，再次分块——为区别改叫切片，启动多个协程来下载这些切片，以实现“多线程”提速的目的。块和切片大小一起决定了有多少个连接在同时下载。切片的大小通过 `--piece-size/-p` 来指定，默认为 1MB 。
3. 一个块中的切片全部下载完后，就可以将数据传给播放器了。当播放器播放这一块的时候，回到第 2 步下载下一块数据。为节省内存，设置了在内存中最多存在 2 个下载完而又没有传给播放器的块。
4. 该如何把数据传给播放器呢？我最初的设想是通过标准输出，这样简单好写。但 stdio 是无法 seek 的，这就意味着你只能从视频的开头看起，无法快进 :P
现在的解决方案是用 HTTP 协议与播放器传输数据。需要快进的时候播放器发送 HTTP Range 请求，video_funnel 将请求中的范围经过分块、切片后“多线程”下载。

import yt_dlp

def fetch_video_info(url):
    ydl_opts = {}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        return {
            "title": info.get('title'),
            "url": url,
            "duration": info.get('duration'),
            "uploader": info.get('uploader')
        }

import yt_dlp
from PIL import Image
import os

def download_yt(url, quality='720'):
    # quality can be 144, 360, 720, 1080, 2160 (4K)
    ydl_opts = {
        'format': f'bestvideo[height<={quality}]+bestaudio/best',
        'outtmpl': 'downloads/%(title)s.%(ext)s',
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)

def images_to_pdf(image_list, output_path="output.pdf"):
    imgs = [Image.open(i).convert('RGB') for i in image_list]
    if imgs:
        imgs[0].save(output_path, save_all=True, append_images=imgs[1:])
        return output_path
    return None

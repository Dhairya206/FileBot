import yt_dlp
from PIL import Image
import os

def download_yt(url, quality='best'):
    ydl_opts = {
        'format': f'bestvideo[height<={quality[:-1]}]+bestaudio/best' if 'p' in quality else 'best',
        'outtmpl': 'downloads/%(title)s.%(ext)s',
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)

def images_to_pdf(image_list, output_path):
    images = [Image.open(img).convert('RGB') for img in image_list]
    if images:
        images[0].save(output_path, save_all=True, append_images=images[1:])
        return output_path
    return None

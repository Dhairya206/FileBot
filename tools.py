import os
import yt_dlp
import img2pdf
from PIL import Image
from cryptography.fernet import Fernet
import io

# 1. ENCRYPTION TOOL
# Generate this once and save it in your Railway Environment Variables as 'ENCRYPTION_KEY'
def get_cipher():
    key = os.getenv("ENCRYPTION_KEY").encode()
    return Fernet(key)

def encrypt_file(file_data):
    """Encrypts raw bytes before sending to Telegram."""
    cipher = get_cipher()
    return cipher.encrypt(file_data)

def decrypt_file(encrypted_data):
    """Decrypts bytes downloaded from Telegram."""
    cipher = get_cipher()
    return cipher.decrypt(encrypted_data)

# 2. YOUTUBE TOOL
def download_youtube_video(url, quality='best'):
    """
    Downloads YouTube video. 
    Qualities: '144', '360', '720', '1080', 'best'
    """
    # Map your commands to yt-dlp formats
    format_map = {
        '144': 'bestvideo[height<=144]+bestaudio/best',
        '720': 'bestvideo[height<=720]+bestaudio/best',
        '1080': 'bestvideo[height<=1080]+bestaudio/best',
        'best': 'bestvideo+bestaudio/best'
    }
    
    ydl_opts = {
        'format': format_map.get(quality, 'best'),
        'outtmpl': 'downloads/%(title)s.%(ext)s',
        'merge_output_format': 'mp4',
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)

# 3. PDF TOOL
def images_to_pdf(image_list, output_name="converted.pdf"):
    """
    Converts a list of image file paths into a single PDF.
    """
    processed_images = []
    for img_path in image_list:
        # Open and convert to RGB (required for PDF)
        img = Image.open(img_path).convert('RGB')
        img.save(img_path) # Overwrite with RGB version
        processed_images.append(img_path)
    
    with open(output_name, "wb") as f:
        f.write(img2pdf.convert(processed_images))
    
    return output_name

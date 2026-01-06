import os
import logging
import qrcode
from io import BytesIO
from pytube import YouTube
from moviepy.editor import VideoFileClip
from PIL import Image, ImageDraw, ImageFont
import tempfile
import img2pdf
from PyPDF2 import PdfMerger, PdfReader, PdfWriter
import asyncio
from datetime import datetime, timedelta
from cryptography.fernet import Fernet
import random
import string
import json
import hashlib
from typing import Optional, List, Tuple, Dict, Union
import aiofiles
import aiofiles.os

logger = logging.getLogger(__name__)

# ==================== ENCRYPTION TOOLS ====================
class EncryptionTool:
    """Encryption utilities for file security"""
    
    def __init__(self, encryption_key: Optional[bytes] = None):
        """Initialize encryption tool with key"""
        if encryption_key:
            try:
                self.fernet = Fernet(encryption_key)
            except Exception as e:
                logger.error(f"Invalid encryption key: {e}")
                # Generate new key
                self.fernet = Fernet.generate_key()
                self.fernet = Fernet(self.fernet)
        else:
            # Generate new key
            self.fernet = Fernet.generate_key()
            self.fernet = Fernet(self.fernet)
    
    def encrypt_data(self, data: bytes) -> Optional[bytes]:
        """Encrypt file data"""
        try:
            return self.fernet.encrypt(data)
        except Exception as e:
            logger.error(f"Encryption error: {e}")
            return None
    
    def decrypt_data(self, encrypted_data: bytes) -> Optional[bytes]:
        """Decrypt file data"""
        try:
            return self.fernet.decrypt(encrypted_data)
        except Exception as e:
            logger.error(f"Decryption error: {e}")
            return None
    
    @staticmethod
    def generate_key() -> bytes:
        """Generate a new encryption key"""
        return Fernet.generate_key()
    
    @staticmethod
    def calculate_file_hash(file_data: bytes) -> str:
        """Calculate SHA256 hash of file data"""
        return hashlib.sha256(file_data).hexdigest()

# ==================== QR CODE GENERATOR ====================
class QRCodeGenerator:
    """QR code generation utilities"""
    
    @staticmethod
    def generate_upi_qr(upi_id: str, amount: Optional[float] = None, 
                       name: str = "Payment", currency: str = "INR") -> Optional[BytesIO]:
        """Generate UPI QR code for payment"""
        try:
            # Create UPI payment string
            upi_string = f"upi://pay?pa={upi_id}"
            if amount:
                upi_string += f"&am={amount}"
            upi_string += f"&pn={name}&cu={currency}"
            
            # Generate QR code
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_H,
                box_size=15,
                border=4,
            )
            qr.add_data(upi_string)
            qr.make(fit=True)
            
            # Create QR code image
            qr_image = qr.make_image(fill_color="black", back_color="white")
            
            # Add UPI ID text below QR
            img_with_text = Image.new('RGB', (qr_image.size[0], qr_image.size[1] + 50), 'white')
            img_with_text.paste(qr_image, (0, 0))
            
            # Add text
            draw = ImageDraw.Draw(img_with_text)
            try:
                font = ImageFont.truetype("arial.ttf", 20)
            except:
                font = ImageFont.load_default()
            
            # Draw UPI ID
            text = f"UPI: {upi_id}"
            if amount:
                text += f" | Amount: ₹{amount}"
            
            text_width = draw.textlength(text, font=font)
            text_position = ((img_with_text.width - text_width) // 2, qr_image.size[1] + 10)
            draw.text(text_position, text, fill="black", font=font)
            
            # Convert to bytes
            bio = BytesIO()
            img_with_text.save(bio, 'PNG', quality=95)
            bio.seek(0)
            
            return bio
        except Exception as e:
            logger.error(f"QR generation error: {e}")
            return None
    
    @staticmethod
    def generate_text_qr(text: str, title: Optional[str] = None) -> Optional[BytesIO]:
        """Generate QR code for any text"""
        try:
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_H,
                box_size=12,
                border=4,
            )
            qr.add_data(text)
            qr.make(fit=True)
            
            qr_image = qr.make_image(fill_color="black", back_color="white")
            
            # Add title if provided
            if title:
                img_with_text = Image.new('RGB', (qr_image.size[0], qr_image.size[1] + 40), 'white')
                img_with_text.paste(qr_image, (0, 0))
                
                draw = ImageDraw.Draw(img_with_text)
                try:
                    font = ImageFont.truetype("arial.ttf", 16)
                except:
                    font = ImageFont.load_default()
                
                text_width = draw.textlength(title, font=font)
                text_position = ((img_with_text.width - text_width) // 2, qr_image.size[1] + 10)
                draw.text(text_position, title, fill="black", font=font)
                
                qr_image = img_with_text
            
            bio = BytesIO()
            qr_image.save(bio, 'PNG', quality=95)
            bio.seek(0)
            
            return bio
        except Exception as e:
            logger.error(f"Text QR generation error: {e}")
            return None
    
    @staticmethod
    def generate_wifi_qr(ssid: str, password: str, encryption: str = "WPA") -> Optional[BytesIO]:
        """Generate WiFi QR code for easy connection"""
        try:
            wifi_string = f"WIFI:T:{encryption};S:{ssid};P:{password};;"
            return QRCodeGenerator.generate_text_qr(wifi_string, f"WiFi: {ssid}")
        except Exception as e:
            logger.error(f"WiFi QR generation error: {e}")
            return None
    
    @staticmethod
    def generate_contact_qr(name: str, phone: str, email: Optional[str] = None) -> Optional[BytesIO]:
        """Generate contact vCard QR code"""
        try:
            vcard = f"BEGIN:VCARD\nVERSION:3.0\nFN:{name}\nTEL:{phone}"
            if email:
                vcard += f"\nEMAIL:{email}"
            vcard += "\nEND:VCARD"
            
            return QRCodeGenerator.generate_text_qr(vcard, f"Contact: {name}")
        except Exception as e:
            logger.error(f"Contact QR generation error: {e}")
            return None

# ==================== YOUTUBE DOWNLOADER ====================
class YouTubeDownloader:
    """YouTube video download utilities with multiple qualities"""
    
    @staticmethod
    async def download_video(url: str, quality: str = '720p') -> Tuple[Optional[str], Optional[str]]:
        """Download YouTube video in specified quality"""
        try:
            yt = YouTube(url)
            
            # Get available streams
            streams = yt.streams
            
            # Available quality mapping
            quality_map = {
                '144': '144p',
                '240': '240p', 
                '360': '360p',
                '480': '480p',
                '720': '720p',
                '1080': '1080p',
                '1440': '1440p',
                '2160': '2160p'  # 4K
            }
            
            requested_quality = quality_map.get(quality, quality)
            
            # Try to get progressive stream (video + audio)
            stream = streams.filter(
                res=requested_quality, 
                progressive=True, 
                file_extension='mp4'
            ).first()
            
            # If progressive not available, try adaptive
            if not stream:
                stream = streams.filter(
                    res=requested_quality,
                    file_extension='mp4'
                ).first()
            
            if not stream:
                # Get available qualities
                available = sorted(set([s.resolution for s in streams if s.resolution]))
                return None, f"Quality '{quality}' not available. Available: {', '.join(available)}"
            
            # Download to temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as tmp:
                stream.download(output_path=tmp.name)
                temp_path = tmp.name
            
            return temp_path, yt.title
        except Exception as e:
            logger.error(f"YouTube download error: {e}")
            return None, str(e)
    
    @staticmethod
    async def get_video_info(url: str) -> Optional[Dict]:
        """Get YouTube video information"""
        try:
            yt = YouTube(url)
            
            # Get all available streams
            streams = yt.streams
            
            # Get video qualities
            video_qualities = []
            for stream in streams.filter(progressive=True, file_extension='mp4'):
                if stream.resolution:
                    video_qualities.append({
                        'quality': stream.resolution,
                        'filesize': stream.filesize,
                        'fps': stream.fps
                    })
            
            # Get audio qualities
            audio_streams = streams.filter(only_audio=True, file_extension='mp4')
            audio_available = len(audio_streams) > 0
            
            # Calculate duration in readable format
            duration_seconds = yt.length
            hours = duration_seconds // 3600
            minutes = (duration_seconds % 3600) // 60
            seconds = duration_seconds % 60
            
            if hours > 0:
                duration_str = f"{hours}:{minutes:02d}:{seconds:02d}"
            else:
                duration_str = f"{minutes}:{seconds:02d}"
            
            info = {
                'title': yt.title,
                'author': yt.author,
                'duration': duration_str,
                'duration_seconds': duration_seconds,
                'views': f"{yt.views:,}",
                'publish_date': yt.publish_date.strftime('%d %b %Y') if yt.publish_date else 'Unknown',
                'description': yt.description[:300] + '...' if yt.description and len(yt.description) > 300 else yt.description,
                'thumbnail': yt.thumbnail_url,
                'qualities': video_qualities,
                'has_audio': audio_available,
                'rating': yt.rating,
                'keywords': yt.keywords
            }
            
            return info
        except Exception as e:
            logger.error(f"YouTube info error: {e}")
            return None
    
    @staticmethod
    async def download_audio(url: str, quality: str = 'high') -> Tuple[Optional[str], Optional[str]]:
        """Download YouTube audio only"""
        try:
            yt = YouTube(url)
            
            # Get audio streams
            streams = yt.streams.filter(only_audio=True)
            
            # Filter by quality
            if quality == 'high':
                stream = streams.order_by('abr').desc().first()
            else:  # low
                stream = streams.order_by('abr').first()
            
            if not stream:
                return None, "No audio stream available"
            
            # Download to temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp:
                stream.download(output_path=tmp.name)
                temp_path = tmp.name
            
            return temp_path, yt.title
        except Exception as e:
            logger.error(f"YouTube audio download error: {e}")
            return None, str(e)
    
    @staticmethod
    async def extract_slides(url: str, interval_seconds: int = 10, 
                           quality: str = 'medium') -> Tuple[Optional[List], Optional[str]]:
        """Extract slides/frames from YouTube video"""
        try:
            yt = YouTube(url)
            
            # Get the best quality stream
            if quality == 'high':
                stream = yt.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').desc().first()
            elif quality == 'low':
                stream = yt.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').first()
            else:  # medium
                stream = yt.streams.filter(progressive=True, file_extension='mp4', res="720p").first()
                if not stream:
                    stream = yt.streams.filter(progressive=True, file_extension='mp4').first()
            
            if not stream:
                return None, "No suitable video stream found"
            
            # Download video
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as tmp:
                stream.download(output_path=tmp.name)
                video_path = tmp.name
            
            # Extract frames
            clip = VideoFileClip(video_path)
            duration = int(clip.duration)
            
            frames = []
            frame_count = 0
            
            for t in range(0, duration, interval_seconds):
                try:
                    frame = clip.get_frame(t)
                    img = Image.fromarray(frame)
                    
                    # Resize if too large
                    max_size = (1280, 720)
                    if img.size[0] > max_size[0] or img.size[1] > max_size[1]:
                        img.thumbnail(max_size, Image.Resampling.LANCZOS)
                    
                    # Convert to BytesIO
                    bio = BytesIO()
                    img.save(bio, 'PNG', optimize=True)
                    bio.seek(0)
                    
                    frames.append({
                        'time': t,
                        'time_str': f"{t//60:02d}:{t%60:02d}",
                        'image': bio,
                        'filename': f'slide_{frame_count+1:03d}.png'
                    })
                    
                    frame_count += 1
                    
                    # Limit to 50 frames max
                    if frame_count >= 50:
                        break
                        
                except Exception as frame_error:
                    logger.error(f"Frame extraction error at {t}s: {frame_error}")
                    continue
            
            clip.close()
            
            # Cleanup temporary video file
            try:
                os.unlink(video_path)
            except:
                pass
            
            if not frames:
                return None, "No frames extracted"
            
            return frames, f"Extracted {len(frames)} slides at {interval_seconds}s intervals"
        except Exception as e:
            logger.error(f"Slide extraction error: {e}")
            return None, str(e)

# ==================== PDF TOOLS ====================
class PDFTools:
    """PDF creation and manipulation utilities"""
    
    @staticmethod
    async def images_to_pdf(images: List[Union[BytesIO, bytes]], 
                          output_filename: str = 'document.pdf',
                          page_size: str = 'A4',
                          orientation: str = 'portrait',
                          margins: tuple = (20, 20, 20, 20)) -> Tuple[Optional[BytesIO], Optional[str]]:
        """Convert multiple images to PDF"""
        try:
            temp_images = []
            
            for i, img_data in enumerate(images):
                try:
                    if isinstance(img_data, BytesIO):
                        img = Image.open(img_data)
                    elif isinstance(img_data, bytes):
                        img = Image.open(BytesIO(img_data))
                    else:
                        continue
                    
                    # Convert to RGB if needed (required for JPEG)
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    
                    # Resize to fit page
                    page_sizes = {
                        'A4': (595, 842),  # Points at 72 DPI
                        'Letter': (612, 792),
                        'Legal': (612, 1008)
                    }
                    
                    page_width, page_height = page_sizes.get(page_size, (595, 842))
                    
                    if orientation == 'landscape':
                        page_width, page_height = page_height, page_width
                    
                    # Apply margins
                    usable_width = page_width - margins[1] - margins[3]
                    usable_height = page_height - margins[0] - margins[2]
                    
                    # Calculate scaling
                    img_ratio = img.width / img.height
                    page_ratio = usable_width / usable_height
                    
                    if img_ratio > page_ratio:
                        # Image is wider, fit to width
                        new_width = usable_width
                        new_height = int(usable_width / img_ratio)
                    else:
                        # Image is taller, fit to height
                        new_height = usable_height
                        new_width = int(usable_height * img_ratio)
                    
                    # Resize image
                    img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                    
                    # Create blank page
                    page = Image.new('RGB', (page_width, page_height), 'white')
                    
                    # Calculate position to center image
                    x_offset = margins[3] + (usable_width - new_width) // 2
                    y_offset = margins[0] + (usable_height - new_height) // 2
                    
                    # Paste image onto page
                    page.paste(img, (x_offset, y_offset))
                    
                    # Save as temporary file
                    temp_path = tempfile.mktemp(suffix=f'_page_{i+1}.jpg')
                    page.save(temp_path, 'JPEG', quality=85, optimize=True)
                    temp_images.append(temp_path)
                    
                    img.close()
                    page.close()
                    
                except Exception as img_error:
                    logger.error(f"Image processing error: {img_error}")
                    continue
            
            if not temp_images:
                return None, "No valid images provided"
            
            # Create PDF from images
            pdf_bytes = img2pdf.convert(temp_images)
            
            # Cleanup temporary files
            for temp_path in temp_images:
                try:
                    if os.path.exists(temp_path):
                        os.unlink(temp_path)
                except:
                    pass
            
            return BytesIO(pdf_bytes), output_filename
        except Exception as e:
            logger.error(f"Images to PDF error: {e}")
            return None, str(e)
    
    @staticmethod
    async def merge_pdfs(pdf_files: List[Union[BytesIO, bytes, str]], 
                       output_filename: str = 'merged.pdf') -> Tuple[Optional[BytesIO], Optional[str]]:
        """Merge multiple PDFs into one"""
        try:
            merger = PdfMerger()
            
            for pdf_data in pdf_files:
                try:
                    if isinstance(pdf_data, BytesIO):
                        merger.append(pdf_data)
                    elif isinstance(pdf_data, bytes):
                        merger.append(BytesIO(pdf_data))
                    elif isinstance(pdf_data, str) and os.path.exists(pdf_data):
                        merger.append(pdf_data)
                except Exception as merge_error:
                    logger.error(f"Error merging PDF: {merge_error}")
                    continue
            
            if not len(merger.pages):
                merger.close()
                return None, "No valid PDFs to merge"
            
            # Write to BytesIO
            output = BytesIO()
            merger.write(output)
            output.seek(0)
            merger.close()
            
            return output, output_filename
        except Exception as e:
            logger.error(f"Merge PDFs error: {e}")
            return None, str(e)
    
    @staticmethod
    async def split_pdf(pdf_data: Union[BytesIO, bytes], 
                      pages_per_split: int = 1) -> Tuple[Optional[List[Dict]], Optional[str]]:
        """Split PDF into multiple files"""
        try:
            if isinstance(pdf_data, BytesIO):
                reader = PdfReader(pdf_data)
            elif isinstance(pdf_data, bytes):
                reader = PdfReader(BytesIO(pdf_data))
            else:
                return None, "Invalid PDF data"
            
            total_pages = len(reader.pages)
            split_files = []
            
            for start in range(0, total_pages, pages_per_split):
                end = min(start + pages_per_split, total_pages)
                
                writer = PdfWriter()
                for page_num in range(start, end):
                    writer.add_page(reader.pages[page_num])
                
                split_output = BytesIO()
                writer.write(split_output)
                split_output.seek(0)
                writer.close()
                
                split_files.append({
                    'data': split_output,
                    'filename': f'split_{start+1}_to_{end}.pdf',
                    'pages': f'{start+1}-{end}',
                    'page_count': end - start
                })
            
            reader.stream.close()
            
            if not split_files:
                return None, "Failed to split PDF"
            
            return split_files, f"Split into {len(split_files)} files"
        except Exception as e:
            logger.error(f"Split PDF error: {e}")
            return None, str(e)
    
    @staticmethod
    async def extract_text(pdf_data: Union[BytesIO, bytes]) -> Tuple[Optional[str], Optional[str]]:
        """Extract text from PDF"""
        try:
            if isinstance(pdf_data, BytesIO):
                reader = PdfReader(pdf_data)
            elif isinstance(pdf_data, bytes):
                reader = PdfReader(BytesIO(pdf_data))
            else:
                return None, "Invalid PDF data"
            
            text = ""
            for page in reader.pages:
                text += page.extract_text() + "\n\n"
            
            reader.stream.close()
            
            return text.strip(), "Text extracted successfully"
        except Exception as e:
            logger.error(f"PDF text extraction error: {e}")
            return None, str(e)
    
    @staticmethod
    async def compress_pdf(pdf_data: Union[BytesIO, bytes], 
                         compression_level: str = 'medium') -> Tuple[Optional[BytesIO], Optional[str]]:
        """Compress PDF file size"""
        try:
            if isinstance(pdf_data, BytesIO):
                reader = PdfReader(pdf_data)
            elif isinstance(pdf_data, bytes):
                reader = PdfReader(BytesIO(pdf_data))
            else:
                return None, "Invalid PDF data"
            
            writer = PdfWriter()
            
            # Copy pages with compression
            for page in reader.pages:
                # Compress page content
                page.compress_content_streams()
                writer.add_page(page)
            
            # Set compression level
            if compression_level == 'high':
                # More aggressive compression
                for page in writer.pages:
                    page.compress_content_streams()
            
            output = BytesIO()
            writer.write(output)
            output.seek(0)
            
            reader.stream.close()
            writer.close()
            
            return output, f"compressed_{compression_level}.pdf"
        except Exception as e:
            logger.error(f"PDF compression error: {e}")
            return None, str(e)

# ==================== FILE CONVERTER ====================
class FileConverter:
    """File format conversion utilities"""
    
    @staticmethod
    async def convert_image_format(image_data: Union[BytesIO, bytes], 
                                 output_format: str = 'PNG',
                                 quality: int = 85) -> Tuple[Optional[BytesIO], Optional[str]]:
        """Convert image to different format"""
        try:
            if isinstance(image_data, BytesIO):
                img = Image.open(image_data)
                original_format = img.format
            elif isinstance(image_data, bytes):
                img = Image.open(BytesIO(image_data))
                original_format = img.format
            else:
                return None, "Invalid image data"
            
            # Convert to RGB if needed for JPEG
            if output_format.upper() in ['JPG', 'JPEG'] and img.mode != 'RGB':
                img = img.convert('RGB')
            
            output = BytesIO()
            
            save_kwargs = {'format': output_format}
            if output_format.upper() in ['JPG', 'JPEG']:
                save_kwargs['quality'] = quality
                save_kwargs['optimize'] = True
            elif output_format.upper() == 'PNG':
                save_kwargs['optimize'] = True
            elif output_format.upper() == 'WEBP':
                save_kwargs['quality'] = quality
                save_kwargs['method'] = 6  # Best compression
            
            img.save(output, **save_kwargs)
            output.seek(0)
            
            original_size = len(image_data) if isinstance(image_data, bytes) else image_data.getbuffer().nbytes
            new_size = output.getbuffer().nbytes
            
            img.close()
            
            return output, f'converted.{output_format.lower()}'
        except Exception as e:
            logger.error(f"Image conversion error: {e}")
            return None, str(e)
    
    @staticmethod
    async def compress_image(image_data: Union[BytesIO, bytes], 
                           quality: int = 75,
                           max_dimension: Optional[int] = None) -> Tuple[Optional[BytesIO], Optional[str], float]:
        """Compress image by reducing quality and size"""
        try:
            if isinstance(image_data, BytesIO):
                img = Image.open(image_data)
                original_format = img.format or 'JPEG'
            elif isinstance(image_data, bytes):
                img = Image.open(BytesIO(image_data))
                original_format = img.format or 'JPEG'
            else:
                return None, "Invalid image data", 0
            
            # Resize if max dimension specified
            if max_dimension and (img.width > max_dimension or img.height > max_dimension):
                if img.width > img.height:
                    new_width = max_dimension
                    new_height = int(max_dimension * img.height / img.width)
                else:
                    new_height = max_dimension
                    new_width = int(max_dimension * img.width / img.height)
                
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # Convert to RGB for JPEG
            if original_format.upper() in ['JPG', 'JPEG'] and img.mode != 'RGB':
                img = img.convert('RGB')
            
            output = BytesIO()
            
            save_kwargs = {'format': original_format}
            if original_format.upper() in ['JPG', 'JPEG', 'WEBP']:
                save_kwargs['quality'] = quality
                save_kwargs['optimize'] = True
            elif original_format.upper() == 'PNG':
                save_kwargs['optimize'] = True
            
            img.save(output, **save_kwargs)
            output.seek(0)
            
            original_size = len(image_data) if isinstance(image_data, bytes) else image_data.getbuffer().nbytes
            new_size = output.getbuffer().nbytes
            compression_ratio = ((original_size - new_size) / original_size) * 100 if original_size > 0 else 0
            
            img.close()
            
            return output, f'compressed_{quality}q.{original_format.lower()}', compression_ratio
        except Exception as e:
            logger.error(f"Image compression error: {e}")
            return None, str(e), 0

# ==================== STORAGE CALCULATOR ====================
class StorageCalculator:
    """Storage and file size calculations"""
    
    @staticmethod
    def format_size(bytes_size: int) -> str:
        """Format bytes to human readable size"""
        if bytes_size == 0:
            return "0 B"
        
        size_names = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
        i = 0
        
        while bytes_size >= 1024 and i < len(size_names) - 1:
            bytes_size /= 1024.0
            i += 1
        
        return f"{bytes_size:.2f} {size_names[i]}"
    
    @staticmethod
    def parse_size(size_str: str) -> int:
        """Parse human readable size to bytes"""
        size_str = size_str.upper().strip()
        
        units = {
            'B': 1,
            'KB': 1024,
            'MB': 1024**2,
            'GB': 1024**3,
            'TB': 1024**4,
            'PB': 1024**5
        }
        
        for unit, multiplier in units.items():
            if size_str.endswith(unit):
                try:
                    number = float(size_str[:-len(unit)].strip())
                    return int(number * multiplier)
                except ValueError:
                    pass
        
        # Try to parse as plain number
        try:
            return int(float(size_str))
        except ValueError:
            return 0
    
    @staticmethod
    def calculate_storage_usage(files: List[tuple]) -> Dict:
        """Calculate storage usage from files"""
        total_size = 0
        type_breakdown = {}
        
        for file in files:
            # Assuming file structure: (id, user_id, filename, file_type, file_size, ...)
            if len(file) > 4:
                file_size = file[4]  # file_size column
                file_type = file[3]  # file_type column
                
                total_size += file_size
                
                if file_type not in type_breakdown:
                    type_breakdown[file_type] = {'count': 0, 'size': 0}
                
                type_breakdown[file_type]['count'] += 1
                type_breakdown[file_type]['size'] += file_size
        
        return {
            'total_size': total_size,
            'type_breakdown': type_breakdown,
            'formatted_total': StorageCalculator.format_size(total_size)
        }
    
    @staticmethod
    def calculate_progress(current: int, total: int) -> Dict:
        """Calculate progress percentage and bar"""
        if total == 0:
            return {
                'percentage': 0,
                'progress_bar': '[░░░░░░░░░░]',
                'remaining': 0
            }
        
        percentage = (current / total) * 100
        
        # Create progress bar
        bar_length = 10
        filled_length = int(bar_length * percentage // 100)
        bar = '█' * filled_length + '░' * (bar_length - filled_length)
        progress_bar = f'[{bar}]'
        
        return {
            'percentage': round(percentage, 1),
            'progress_bar': progress_bar,
            'remaining': total - current,
            'formatted_remaining': StorageCalculator.format_size(total - current)
        }

# ==================== TEXT PROCESSOR ====================
class TextProcessor:
    """Text processing utilities"""
    
    @staticmethod
    def extract_text_from_pdf(pdf_data: Union[BytesIO, bytes]) -> Tuple[Optional[str], Optional[str]]:
        """Extract text from PDF"""
        try:
            from PyPDF2 import PdfReader
            
            if isinstance(pdf_data, BytesIO):
                reader = PdfReader(pdf_data)
            elif isinstance(pdf_data, bytes):
                reader = PdfReader(BytesIO(pdf_data))
            else:
                return None, "Invalid PDF data"
            
            text = ""
            for i, page in enumerate(reader.pages, 1):
                page_text = page.extract_text()
                if page_text:
                    text += f"--- Page {i} ---\n{page_text}\n\n"
            
            reader.stream.close()
            
            return text.strip(), "Text extracted successfully"
        except Exception as e:
            logger.error(f"PDF text extraction error: {e}")
            return None, str(e)
    
    @staticmethod
    def summarize_text(text: str, max_sentences: int = 3) -> str:
        """Summarize text to specified number of sentences"""
        try:
            # Split into sentences (simple approach)
            sentences = text.replace('!', '.').replace('?', '.').split('.')
            sentences = [s.strip() for s in sentences if s.strip()]
            
            if len(sentences) <= max_sentences:
                return text
            
            # Take first few sentences (simple summarization)
            summary = '. '.join(sentences[:max_sentences]) + '.'
            
            return summary
        except Exception as e:
            logger.error(f"Text summarization error: {e}")
            return text[:500] + '...' if len(text) > 500 else text
    
    @staticmethod
    def count_words(text: str) -> Dict:
        """Count words, characters, and sentences"""
        try:
            # Count words
            words = text.split()
            word_count = len(words)
            
            # Count characters
            char_count = len(text)
            char_no_space_count = len(text.replace(' ', ''))
            
            # Count sentences (approximate)
            sentences = text.replace('!', '.').replace('?', '.').split('.')
            sentence_count = len([s for s in sentences if s.strip()])
            
            # Calculate reading time (average 200 words per minute)
            reading_time = max(1, word_count // 200)
            
            return {
                'words': word_count,
                'characters': char_count,
                'characters_no_spaces': char_no_space_count,
                'sentences': sentence_count,
                'reading_time': f"{reading_time} min"
            }
        except Exception as e:
            logger.error(f"Word count error: {e}")
            return {'words': 0, 'characters': 0, 'characters_no_spaces': 0, 'sentences': 0, 'reading_time': '0 min'}

# ==================== AUDIO VIDEO TOOLS ====================
class AudioVideoTools:
    """Audio and video utilities"""
    
    @staticmethod
    async def extract_audio_from_video(video_path: str) -> Tuple[Optional[str], Optional[str]]:
        """Extract audio from video file"""
        try:
            from moviepy.editor import VideoFileClip
            
            clip = VideoFileClip(video_path)
            audio = clip.audio
            
            if audio is None:
                clip.close()
                return None, "No audio track found"
            
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp:
                audio.write_audiofile(tmp.name, verbose=False, logger=None)
                temp_audio_path = tmp.name
            
            clip.close()
            audio.close()
            
            return temp_audio_path, "Audio extracted successfully"
        except Exception as e:
            logger.error(f"Audio extraction error: {e}")
            return None, str(e)
    
    @staticmethod
    async def get_video_duration(video_path: str) -> int:
        """Get duration of video file in seconds"""
        try:
            from moviepy.editor import VideoFileClip
            
            clip = VideoFileClip(video_path)
            duration = int(clip.duration)
            clip.close()
            
            return duration
        except Exception as e:
            logger.error(f"Get video duration error: {e}")
            return 0
    
    @staticmethod
    async def get_video_resolution(video_path: str) -> Tuple[Optional[int], Optional[int]]:
        """Get video resolution"""
        try:
            from moviepy.editor import VideoFileClip
            
            clip = VideoFileClip(video_path)
            width, height = clip.size
            clip.close()
            
            return width, height
        except Exception as e:
            logger.error(f"Get video resolution error: {e}")
            return None, None
    
    @staticmethod
    async def convert_video_format(video_path: str, output_format: str = 'mp4') -> Tuple[Optional[str], Optional[str]]:
        """Convert video to different format"""
        try:
            from moviepy.editor import VideoFileClip
            
            clip = VideoFileClip(video_path)
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{output_format}') as tmp:
                clip.write_videofile(tmp.name, verbose=False, logger=None)
                temp_video_path = tmp.name
            
            clip.close()
            
            return temp_video_path, f"Converted to {output_format}"
        except Exception as e:
            logger.error(f"Video conversion error: {e}")
            return None, str(e)

# ==================== SECURITY TOOLS ====================
class SecurityTools:
    """Security and validation utilities"""
    
    @staticmethod
    def generate_random_string(length: int = 8, 
                             use_uppercase: bool = True,
                             use_lowercase: bool = True,
                             use_digits: bool = True,
                             use_special: bool = False) -> str:
        """Generate random string for passwords/codes"""
        characters = ''
        
        if use_uppercase:
            characters += string.ascii_uppercase
        if use_lowercase:
            characters += string.ascii_lowercase
        if use_digits:
            characters += string.digits
        if use_special:
            characters += '!@#$%^&*()_+-=[]{}|;:,.<>?'
        
        if not characters:
            characters = string.ascii_letters + string.digits
        
        return ''.join(random.choice(characters) for _ in range(length))
    
    @staticmethod
    def validate_email(email: str) -> bool:
        """Validate email address format"""
        import re
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, email))
    
    @staticmethod
    def validate_phone(phone: str) -> bool:
        """Validate phone number format"""
        import re
        # Simple validation for Indian numbers
        pattern = r'^[6-9]\d{9}$'
        return bool(re.match(pattern, phone))
    
    @staticmethod
    def validate_upi(upi_id: str) -> bool:
        """Validate UPI ID format"""
        import re
        pattern = r'^[a-zA-Z0-9.\-_]{2,49}@[a-zA-Z]{2,}$'
        return bool(re.match(pattern, upi_id))

# ==================== FILE VALIDATOR ====================
class FileValidator:
    """File validation utilities"""
    
    # Common file signatures (magic numbers)
    FILE_SIGNATURES = {
        'pdf': b'%PDF',
        'jpg': b'\xff\xd8\xff',
        'jpeg': b'\xff\xd8\xff',
        'png': b'\x89PNG\r\n\x1a\n',
        'gif': b'GIF87a',
        'gif': b'GIF89a',
        'bmp': b'BM',
        'zip': b'PK\x03\x04',
        'mp3': b'ID3',
        'wav': b'RIFF',
        'mp4': b'ftyp',
        'avi': b'RIFF',
    }
    
    @staticmethod
    def validate_file_type(file_data: bytes, expected_type: str) -> bool:
        """Validate file type using magic numbers"""
        if expected_type not in FileValidator.FILE_SIGNATURES:
            return True  # Can't validate unknown type
        
        signature = FileValidator.FILE_SIGNATURES[expected_type]
        return file_data.startswith(signature)
    
    @staticmethod
    def get_file_type(file_data: bytes) -> Optional[str]:
        """Detect file type from magic numbers"""
        for file_type, signature in FileValidator.FILE_SIGNATURES.items():
            if file_data.startswith(signature):
                return file_type
        return None
    
    @staticmethod
    def validate_file_size(file_data: bytes, max_size_mb: int) -> bool:
        """Validate file size"""
        max_size_bytes = max_size_mb * 1024 * 1024
        return len(file_data) <= max_size_bytes

# ==================== TEMPLATE GENERATOR ====================
class TemplateGenerator:
    """Template and report generation utilities"""
    
    @staticmethod
    async def generate_invoice(user_data: Dict, subscription_data: Dict) -> Optional[BytesIO]:
        """Generate invoice PDF"""
        try:
            # This is a simplified version
            # In production, use a proper PDF generation library like reportlab
            
            invoice_text = f"""
            INVOICE
            ========================
            
            Invoice ID: INV-{datetime.now().strftime('%Y%m%d%H%M%S')}
            Date: {datetime.now().strftime('%d %b %Y')}
            
            Customer Information:
            ---------------------
            Name: {user_data.get('name', 'N/A')}
            Username: @{user_data.get('username', 'N/A')}
            User ID: {user_data.get('id', 'N/A')}
            
            Subscription Details:
            ---------------------
            Plan: {subscription_data.get('plan', 'N/A').upper()}
            Amount: ₹{subscription_data.get('amount', 0)}
            Validity: {subscription_data.get('days', 0)} days
            Payment Method: {subscription_data.get('payment_method', 'N/A')}
            Transaction ID: {subscription_data.get('transaction_id', 'N/A')}
            
            Thank you for your business!
            """
            
            # Convert to PDF (simplified - would use proper PDF generation)
            output = BytesIO()
            output.write(invoice_text.encode())
            output.seek(0)
            
            return output
        except Exception as e:
            logger.error(f"Invoice generation error: {e}")
            return None
    
    @staticmethod
    async def generate_report(report_data: Dict, report_type: str = 'summary') -> Optional[BytesIO]:
        """Generate various reports"""
        try:
            if report_type == 'summary':
                report_text = f"""
                BOT USAGE REPORT
                ========================
                
                Generated: {datetime.now().strftime('%d %b %Y, %I:%M %p')}
                
                User Statistics:
                ----------------
                Total Users: {report_data.get('total_users', 0)}
                Active Subscriptions: {report_data.get('active_subs', 0)}
                Storage Used: {report_data.get('storage_used', '0 B')}
                
                File Statistics:
                ----------------
                Total Files: {report_data.get('total_files', 0)}
                Documents: {report_data.get('documents', 0)}
                Images: {report_data.get('images', 0)}
                Videos: {report_data.get('videos', 0)}
                Audio: {report_data.get('audio', 0)}
                
                Revenue Summary:
                ----------------
                Total Revenue: ₹{report_data.get('revenue', 0)}
                Monthly Active: ₹{report_data.get('monthly_rev', 0)}
                Yearly Active: ₹{report_data.get('yearly_rev', 0)}
                """
            
            output = BytesIO()
            output.write(report_text.encode())
            output.seek(0)
            
            return output
        except Exception as e:
            logger.error(f"Report generation error: {e}")
            return None

# ==================== UTILITY FUNCTIONS ====================
class Utilities:
    """General utility functions"""
    
    @staticmethod
    def format_datetime(dt: datetime, format_str: str = '%d %b %Y, %I:%M %p') -> str:
        """Format datetime to string"""
        return dt.strftime(format_str)
    
    @staticmethod
    def parse_datetime(date_str: str, format_str: str = '%Y-%m-%d %H:%M:%S') -> Optional[datetime]:
        """Parse string to datetime"""
        try:
            return datetime.strptime(date_str, format_str)
        except:
            return None
    
    @staticmethod
    def calculate_days_between(start_date: datetime, end_date: datetime) -> int:
        """Calculate days between two dates"""
        return (end_date - start_date).days
    
    @staticmethod
    def is_date_in_future(date: datetime, days: int = 0) -> bool:
        """Check if date is in future (with optional offset)"""
        return date > datetime.now() + timedelta(days=days)
    
    @staticmethod
    def get_file_extension(filename: str) -> str:
        """Get file extension from filename"""
        return os.path.splitext(filename)[1].lower().replace('.', '')
    
    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """Sanitize filename to remove unsafe characters"""
        # Remove directory traversal attempts
        filename = os.path.basename(filename)
        # Replace unsafe characters
        unsafe_chars = ['<', '>', ':', '"', '|', '?', '*', '\\', '/']
        for char in unsafe_chars:
            filename = filename.replace(char, '_')
        return filename

# ==================== ASYNC FILE OPERATIONS ====================
class AsyncFileOperations:
    """Async file operations"""
    
    @staticmethod
    async def read_file_async(filepath: str) -> Optional[bytes]:
        """Read file asynchronously"""
        try:
            async with aiofiles.open(filepath, 'rb') as f:
                return await f.read()
        except Exception as e:
            logger.error(f"Async file read error: {e}")
            return None
    
    @staticmethod
    async def write_file_async(filepath: str, data: bytes) -> bool:
        """Write file asynchronously"""
        try:
            async with aiofiles.open(filepath, 'wb') as f:
                await f.write(data)
            return True
        except Exception as e:
            logger.error(f"Async file write error: {e}")
            return False
    
    @staticmethod
    async def delete_file_async(filepath: str) -> bool:
        """Delete file asynchronously"""
        try:
            await aiofiles.os.remove(filepath)
            return True
        except Exception as e:
            logger.error(f"Async file delete error: {e}")
            return False
    
    @staticmethod
    async def file_exists_async(filepath: str) -> bool:
        """Check if file exists asynchronously"""
        try:
            return await aiofiles.os.path.exists(filepath)
        except Exception as e:
            logger.error(f"Async file exists check error: {e}")
            return False

# Create global instances for easy access
encryption_tool = EncryptionTool()
qr_generator = QRCodeGenerator()
youtube_downloader = YouTubeDownloader()
pdf_tools = PDFTools()
file_converter = FileConverter()
storage_calculator = StorageCalculator()
text_processor = TextProcessor()
audio_video_tools = AudioVideoTools()
security_tools = SecurityTools()
file_validator = FileValidator()
template_generator = TemplateGenerator()
utilities = Utilities()
async_file_ops = AsyncFileOperations()
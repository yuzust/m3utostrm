import re
import os
import uuid
import logging
import hashlib
import urllib.parse
from datetime import datetime

logger = logging.getLogger(__name__)

class M3UChannel:
    """Represents a single channel in an M3U playlist"""
    def __init__(self, info_line="", url=""):
        self.info_line = info_line
        self.url = url
        self.attributes = self._parse_attributes(info_line)
        self.tvg_id = self.attributes.get('tvg-id', '')
        self.tvg_name = self.attributes.get('tvg-name', '')
        self.tvg_logo = self.attributes.get('tvg-logo', '')
        self.group_title = self.attributes.get('group-title', '')
        self.tvg_chno = self.attributes.get('tvg-chno', '')
        # Extract channel name (text after the last comma)
        self.name = self._extract_name(info_line)

    def _parse_attributes(self, info_line):
        """Extract attributes from the EXTINF line"""
        attributes = {}
        if not info_line.startswith('#EXTINF:'):
            return attributes
        
        # Match attributes in format: key="value"
        attr_pattern = re.compile(r'([a-zA-Z0-9-]+)="([^"]*)"')
        matches = attr_pattern.findall(info_line)
        for key, value in matches:
            attributes[key] = value
            
        return attributes
    
    def _extract_name(self, info_line):
        """Extract channel name from the EXTINF line"""
        if not info_line.startswith('#EXTINF:'):
            return ""
        
        # Find the last comma and get everything after it
        last_comma_idx = info_line.rfind(',')
        if last_comma_idx != -1:
            return info_line[last_comma_idx + 1:].strip()
        return ""
    
    def optimize_name(self, options=None):
        """Optimize channel name based on options"""
        if options is None:
            options = {
                'remove_country_prefix': True,
                'remove_quality_prefix': True,
                'remove_symbols': True,
                'remove_brackets': True,
                'fix_spacing': True,
                'remove_special_chars': True,
                'remove_suffixes': True
            }
        
        name = self.name
        
        # Remove country prefix (e.g., "US: ", "UK - ")
        if options.get('remove_country_prefix', True):
            name = re.sub(r'^[A-Z]{2}[\s:-]+', '', name)
        
        # Remove quality prefixes (e.g., "HD: ", "4K - ", "FHD |")
        if options.get('remove_quality_prefix', True):
            name = re.sub(r'^(HD|SD|FHD|UHD|4K|1080p|720p)[\s:|-]+', '', name, flags=re.IGNORECASE)
        
        # Remove text in brackets
        if options.get('remove_brackets', True):
            name = re.sub(r'\([^)]*\)|\[[^\]]*\]|\{[^}]*\}', '', name)
        
        # Remove special characters like ᵁᴴᴰ
        if options.get('remove_special_chars', True):
            name = re.sub(r'[^\x00-\x7F]+', '', name)
        
        # Remove suffixes (quality indicators, version numbers, country codes)
        if options.get('remove_suffixes', True):
            # Remove quality suffixes (HD, SD, FHD, UHD, 4K, UHDHDR, etc.)
            name = re.sub(r'\s+(HD|SD|FHD|UHD|4K|UHDHDR|1080p|720p)(\s+|$)', ' ', name, flags=re.IGNORECASE)
            
            # Remove version suffixes (V1, V2, etc.)
            name = re.sub(r'\s+V\d+(\s+|$)', ' ', name, flags=re.IGNORECASE)
            
            # Remove country code suffixes (2-letter codes at the end like FI, RO, UK, etc.)
            name = re.sub(r'\s+[A-Z]{2}$', '', name)
        
        # Remove symbols
        if options.get('remove_symbols', True):
            name = re.sub(r'[^\w\s]', '', name)
        
        # Fix spacing (multiple spaces to single space)
        if options.get('fix_spacing', True):
            name = re.sub(r'\s+', ' ', name).strip()
        
        self.name = name
        return name
    
    def set_channel_number(self, number):
        """Set the channel number"""
        self.tvg_chno = str(number)
        self.attributes['tvg-chno'] = str(number)
        return self
    
    def to_extinf_line(self):
        """Convert back to EXTINF line format"""
        # Start with the duration part
        duration_match = re.search(r'#EXTINF:([-0-9.]+)', self.info_line)
        duration = "-1" if not duration_match else duration_match.group(1)
        
        # Build attributes string
        attr_str = ""
        for key, value in self.attributes.items():
            if key == 'tvg-name':
                value = self.name  # Use the potentially modified name
            attr_str += f' {key}="{value}"'
        
        # Construct the full EXTINF line
        return f'#EXTINF:{duration}{attr_str}, {self.name}'


class M3UEditor:
    def __init__(self, m3u_content=None, m3u_file=None, m3u_url=None):
        """Initialize the M3U editor with content from file, string, or URL"""
        self.headers = []
        self.channels = []
        self.m3u_url = m3u_url
        self.id = str(uuid.uuid4())
        self.created_at = datetime.now()
        self.original_content = ""
        
        if m3u_content:
            self.original_content = m3u_content
            self.parse_content(m3u_content)
        elif m3u_file and os.path.exists(m3u_file):
            with open(m3u_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                self.original_content = content
                self.parse_content(content)
    
    def parse_content(self, content):
        """Parse M3U file content into headers and channels"""
        self.headers = []
        self.channels = []
        
        # Split content into lines
        lines = content.strip().split('\n')
        
        # First line should be #EXTM3U
        if not lines or not lines[0].startswith('#EXTM3U'):
            logger.warning("Content does not start with #EXTM3U, may not be a valid M3U file")
            if lines and lines[0]:
                self.headers.append(lines[0])
            else:
                self.headers.append('#EXTM3U')
        else:
            self.headers.append(lines[0])
        
        # Parse the rest of the file
        i = 1
        while i < len(lines):
            line = lines[i].strip()
            
            # Skip empty lines
            if not line:
                i += 1
                continue
            
            # If this is a header line (not channel info), add to headers
            if line.startswith('#') and not line.startswith('#EXTINF:'):
                self.headers.append(line)
                i += 1
                continue
            
            # If this is an EXTINF line, then the next line should be the URL
            if line.startswith('#EXTINF:'):
                if i + 1 < len(lines):
                    url = lines[i + 1].strip()
                    if url and not url.startswith('#'):
                        channel = M3UChannel(line, url)
                        self.channels.append(channel)
                    i += 2
                else:
                    # EXTINF line with no URL (incomplete entry)
                    i += 1
            else:
                # This line is neither a header nor an EXTINF, might be a URL without EXTINF
                i += 1
                
        logger.info(f"Parsed M3U content: {len(self.headers)} headers, {len(self.channels)} channels")
    
    def is_vod_channel(self, channel):
        """Determine if a channel is VOD content (not live)"""
        # Check URL for common VOD extensions
        vod_extensions = ['.mp4', '.mkv', '.avi', '.mpg', '.mpeg', '.mov']
        for ext in vod_extensions:
            if channel.url.lower().endswith(ext):
                return True
        
        # Check group title for VOD indicators
        vod_keywords = ['vod', 'movie', 'film', 'series', 'show', 'episode']
        if channel.group_title:
            group_lower = channel.group_title.lower()
            for keyword in vod_keywords:
                if keyword in group_lower:
                    return True
        
        # If tvg-id contains movie or series identifiers
        if channel.tvg_id and any(x in channel.tvg_id.lower() for x in ['movie', 'film', 'series']):
            return True
        
        return False

    def filter_vod_content(self, keep_live_only=True):
        """Filter out VOD content, keeping only live channels"""
        original_count = len(self.channels)
        
        if keep_live_only:
            # Keep only live channels (non-VOD)
            self.channels = [c for c in self.channels if not self.is_vod_channel(c)]
        else:
            # Keep only VOD channels
            self.channels = [c for c in self.channels if self.is_vod_channel(c)]
        
        logger.info(f"VOD filtering: {original_count - len(self.channels)} channels filtered out")
        return self
    
    def optimize_channel_names(self, options=None):
        """Optimize all channel names based on options"""
        for channel in self.channels:
            channel.optimize_name(options)
        return self
    
    def renumber_channels(self, start_number=1, by_group=False):
        """Add channel numbers, optionally by group"""
        if by_group:
            # Get all unique groups
            groups = sorted(set(channel.group_title for channel in self.channels if channel.group_title))
            
            current_number = start_number
            for group in groups:
                for channel in [c for c in self.channels if c.group_title == group]:
                    channel.set_channel_number(current_number)
                    current_number += 1
        else:
            # Simple sequential numbering
            for i, channel in enumerate(self.channels, start=start_number):
                channel.set_channel_number(i)
                
        return self
    
    def filter_channels(self, group=None, name_contains=None):
        """Filter channels by group and/or name"""
        filtered_channels = self.channels
        
        if group:
            filtered_channels = [c for c in filtered_channels if c.group_title == group]
            
        if name_contains:
            filtered_channels = [c for c in filtered_channels if name_contains.lower() in c.name.lower()]
            
        # Create a new editor with the filtered channels
        new_editor = M3UEditor()
        new_editor.headers = self.headers.copy()
        new_editor.channels = filtered_channels
        new_editor.m3u_url = self.m3u_url
        
        return new_editor
    
    def get_groups(self):
        """Get a list of all groups in the M3U"""
        groups = {}
        for channel in self.channels:
            group = channel.group_title
            if group in groups:
                groups[group] += 1
            else:
                groups[group] = 1
        
        return [(group, count) for group, count in groups.items()]
    
    def save_to_file(self, filepath):
        """Save the current M3U to a file"""
        content = self.export_to_string()
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            logger.info(f"Saved M3U to file: {filepath}")
            return True
        except Exception as e:
            logger.error(f"Error saving M3U to file: {str(e)}")
            return False
    
    def export_to_string(self):
        """Export the M3U as a string"""
        lines = self.headers.copy()
        
        for channel in self.channels:
            lines.append(channel.to_extinf_line())
            lines.append(channel.url)
        
        return '\n'.join(lines)
    
    def generate_proxy_id(self, host=None):
        """Generate a unique ID for this M3U for proxying"""
        # Use existing ID if available
        if hasattr(self, 'id'):
            return self.id
            
        # Generate a unique ID based on content and timestamp
        content_hash = hashlib.md5(self.export_to_string().encode()).hexdigest()[:8]
        timestamp = int(datetime.now().timestamp())
        self.id = f"{content_hash}-{timestamp}"
        
        return self.id
        
    def generate_proxy_url(self, host, secure=True):
        """Generate a proxy URL for this M3U"""
        protocol = "https" if secure else "http"
        proxy_id = self.generate_proxy_id()
        
        # Clean up host if it includes protocol
        if "://" in host:
            host = host.split("://")[1]
            
        return f"{protocol}://{host}/proxy/m3u/{proxy_id}/playlist.m3u"


class M3UProxyManager:
    """Manages M3U proxy instances and their storage"""
    
    def __init__(self, storage_dir="data/m3u_proxy"):
        self.storage_dir = storage_dir
        if not os.path.exists(storage_dir):
            os.makedirs(storage_dir, exist_ok=True)
    
    def save_m3u(self, m3u_editor, name=None):
        """Save an M3U editor instance for proxying"""
        proxy_id = m3u_editor.generate_proxy_id()
        
        # Create storage directory for this M3U
        m3u_dir = os.path.join(self.storage_dir, proxy_id)
        if not os.path.exists(m3u_dir):
            os.makedirs(m3u_dir, exist_ok=True)
        
        # Save the M3U content
        m3u_path = os.path.join(m3u_dir, "playlist.m3u")
        m3u_editor.save_to_file(m3u_path)
        
        # Save metadata
        metadata = {
            "id": proxy_id,
            "name": name or f"Proxy M3U {proxy_id}",
            "original_url": m3u_editor.m3u_url,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "channel_count": len(m3u_editor.channels)
        }
        
        metadata_path = os.path.join(m3u_dir, "metadata.json")
        import json
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f)
        
        return proxy_id
    
    def get_m3u(self, proxy_id):
        """Get an M3U editor instance by proxy ID"""
        m3u_path = os.path.join(self.storage_dir, proxy_id, "playlist.m3u")
        
        if not os.path.exists(m3u_path):
            return None
        
        m3u_editor = M3UEditor(m3u_file=m3u_path)
        m3u_editor.id = proxy_id
        
        # Load metadata
        metadata_path = os.path.join(self.storage_dir, proxy_id, "metadata.json")
        if os.path.exists(metadata_path):
            import json
            with open(metadata_path, 'r') as f:
                metadata = json.load(f)
                m3u_editor.m3u_url = metadata.get("original_url")
        
        return m3u_editor
    
    def get_all_m3us(self):
        """Get metadata for all saved M3Us"""
        m3us = []
        
        for proxy_id in os.listdir(self.storage_dir):
            metadata_path = os.path.join(self.storage_dir, proxy_id, "metadata.json")
            if os.path.exists(metadata_path):
                import json
                with open(metadata_path, 'r') as f:
                    try:
                        metadata = json.load(f)
                        m3us.append(metadata)
                    except json.JSONDecodeError:
                        logger.error(f"Error reading metadata for M3U {proxy_id}")
        
        # Sort by created date (newest first)
        m3us.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return m3us
    
    def delete_m3u(self, proxy_id):
        """Delete an M3U proxy by ID"""
        m3u_dir = os.path.join(self.storage_dir, proxy_id)
        
        if not os.path.exists(m3u_dir):
            return False
        
        import shutil
        try:
            shutil.rmtree(m3u_dir)
            return True
        except Exception as e:
            logger.error(f"Error deleting M3U {proxy_id}: {str(e)}")
            return False
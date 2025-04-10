import re
import os
import json
from flask import Blueprint, request, jsonify, url_for, current_app
from m3u_editor import M3UProxyManager, M3UEditor

# Create blueprint
proxy_api = Blueprint('proxy_api', __name__)

@proxy_api.route('/api/proxies', methods=['GET'])
def get_proxies():
    """API endpoint to get all M3U proxies"""
    try:
        proxy_manager = M3UProxyManager()
        m3us = proxy_manager.get_all_m3us()
        
        return jsonify({
            'status': 'success',
            'm3us': m3us
        })
    except Exception as e:
        current_app.logger.error(f"Error retrieving proxies: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'Failed to retrieve proxies: {str(e)}'
        }), 500

@proxy_api.route('/api/optimize-channels', methods=['POST'])
def optimize_channels():
    """API endpoint to optimize channel names with custom regex patterns"""
    try:
        data = request.get_json()
        proxy_id = data.get('proxy_id')
        standard_options = data.get('standard_options', {})
        custom_patterns = data.get('custom_patterns', [])
        
        if not proxy_id:
            return jsonify({
                'status': 'error',
                'message': 'No proxy ID provided'
            }), 400
        
        # Get the M3U data
        proxy_manager = M3UProxyManager()
        m3u = proxy_manager.get_m3u(proxy_id)
        
        if not m3u:
            return jsonify({
                'status': 'error',
                'message': 'M3U not found'
            }), 404
        
        # Apply standard optimizations first
        m3u.optimize_channel_names(standard_options)
        
        # Apply custom regex patterns
        for pattern_data in custom_patterns:
            try:
                if not pattern_data.get('pattern'):
                    continue
                
                pattern = pattern_data['pattern']
                replacement = pattern_data.get('replacement', '')
                
                # Compile regex for performance
                regex = re.compile(pattern)
                
                # Apply regex to all channel names
                for channel in m3u.channels:
                    channel.name = regex.sub(replacement, channel.name)
            except re.error as e:
                return jsonify({
                    'status': 'error',
                    'message': f'Invalid regex pattern: {pattern} - {str(e)}'
                }), 400
        
        # Save changes
        proxy_manager.save_m3u(m3u)
        
        return jsonify({
            'status': 'success',
            'message': 'Channel names optimized with custom patterns',
            'channel_count': len(m3u.channels)
        })
    except Exception as e:
        current_app.logger.error(f"Error optimizing channels: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'Error optimizing channels: {str(e)}'
        }), 500

@proxy_api.route('/api/preview-optimization', methods=['POST'])
def preview_optimization():
    """API endpoint to preview channel name optimization without saving changes"""
    try:
        data = request.get_json()
        proxy_id = data.get('proxy_id')
        standard_options = data.get('standard_options', {})
        custom_patterns = data.get('custom_patterns', [])
        
        if not proxy_id:
            return jsonify({
                'status': 'error',
                'message': 'No proxy ID provided'
            }), 400
        
        # Get the M3U data
        proxy_manager = M3UProxyManager()
        m3u = proxy_manager.get_m3u(proxy_id)
        
        if not m3u:
            return jsonify({
                'status': 'error',
                'message': 'M3U not found'
            }), 404
        
        # Clone channels to avoid modifying the original
        preview_results = []
        
        # Process a sample of channels (limit to 50 to avoid performance issues)
        sample_channels = m3u.channels[:50]
        
        for channel in sample_channels:
            original_name = channel.name
            optimized_name = original_name
            
            # Create temporary channel object to apply optimizations
            temp_channel = M3UChannel(info_line=f'#EXTINF:-1 tvg-name="{original_name}"', url="")
            
            # Apply standard optimizations
            temp_channel.optimize_name(standard_options)
            optimized_name = temp_channel.name
            
            # Apply custom regex patterns
            for pattern_data in custom_patterns:
                try:
                    if not pattern_data.get('pattern'):
                        continue
                    
                    pattern = pattern_data['pattern']
                    replacement = pattern_data.get('replacement', '')
                    
                    # Compile regex for performance
                    regex = re.compile(pattern)
                    
                    # Apply regex to the optimized name
                    optimized_name = regex.sub(replacement, optimized_name)
                except re.error as e:
                    return jsonify({
                        'status': 'error',
                        'message': f'Invalid regex pattern: {pattern} - {str(e)}'
                    }), 400
            
            # Add to preview results
            preview_results.append({
                'original': original_name,
                'optimized': optimized_name
            })
        
        return jsonify({
            'status': 'success',
            'preview_results': preview_results
        })
    except Exception as e:
        current_app.logger.error(f"Error previewing optimization: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'Error previewing optimization: {str(e)}'
        }), 500

# Helper class for the preview functionality
class M3UChannel:
    """Simplified version of M3UChannel for preview calculations"""
    def __init__(self, info_line="", url=""):
        self.info_line = info_line
        self.url = url
        self.name = self._extract_name(info_line)

    def _extract_name(self, info_line):
        """Extract channel name from the EXTINF line"""
        if 'tvg-name="' in info_line:
            return re.search(r'tvg-name="([^"]*)"', info_line).group(1)
        elif ',' in info_line:
            return info_line.split(',', 1)[1].strip()
        return ""
    
    def optimize_name(self, options=None):
        """Optimize channel name based on options"""
        if options is None:
            options = {}
        
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

# Register the blueprint
def register_proxy_api(app):
    app.register_blueprint(proxy_api)
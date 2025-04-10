import os
from datetime import datetime
from flask import render_template, send_from_directory
from channel_api import channel_api

# This function should be used to add the channel_api blueprint to your Flask app
def setup_channel_manager(app):
    """
    Set up the Channel Manager feature by registering the API blueprint
    and adding the channel manager route
    """
    # Register the channel_api blueprint
    app.register_blueprint(channel_api)
    
    # Add route for channel images directory if needed
    @app.route('/channel-images/<path:filename>')
    def channel_image(filename):
        return send_from_directory(os.path.join(app.static_folder, 'channel_images'), filename)
    
    # Add route for the channel manager UI
    @app.route('/proxy/manage-channels/<proxy_id>')
    def channel_manager(proxy_id):
        # Load the M3U metadata to get the name
        metadata_path = os.path.join('data/m3u_proxy', proxy_id, 'metadata.json')
        m3u_name = f"M3U Proxy {proxy_id[:8]}"
        
        try:
            if os.path.exists(metadata_path):
                import json
                with open(metadata_path, 'r') as f:
                    metadata = json.load(f)
                    m3u_name = metadata.get('name', m3u_name)
        except Exception as e:
            app.logger.error(f"Error reading M3U metadata: {str(e)}")
        
        # Get app configuration
        config = {}
        try:
            from db import load_config
            config = load_config()
        except Exception as e:
            app.logger.error(f"Error loading config: {str(e)}")
            
        # Get M3U object to get groups and other info
        m3u = None
        try:
            from m3u_editor import M3UProxyManager
            proxy_manager = M3UProxyManager()
            m3u = proxy_manager.get_m3u(proxy_id)
            groups = m3u.get_groups() if m3u else []
        except Exception as e:
            app.logger.error(f"Error loading M3U data: {str(e)}")
            groups = []
        
        # Render the channel manager template
        return render_template(
            'channel_manager.html',
            proxy_id=proxy_id,
            m3u_name=m3u_name,
            m3u=m3u,  # Pass the m3u object to the template
            groups=groups,
            theme=config.get('ui_theme', 'dark')
        )
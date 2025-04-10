import os
import re
import json
import uuid
import sqlite3
from flask import Blueprint, request, jsonify, current_app, url_for, send_from_directory
from werkzeug.utils import secure_filename

# Create blueprint
channel_api = Blueprint('channel_api', __name__)

# Database helper functions
def dict_factory(cursor, row):
    """Convert SQL row to dictionary with column names as keys"""
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

def get_db_connection():
    """Get a connection to the database with row factory set to dict_factory"""
    conn = sqlite3.connect('data/m3u_converter.db')
    conn.row_factory = dict_factory
    return conn

# Initialize the database tables if they don't exist
def init_channel_manager_db():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Create user categories table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        ''')
        
        # Create channel images table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS channel_images (
            channel_id TEXT PRIMARY KEY,
            proxy_id TEXT NOT NULL,
            image_path TEXT,
            image_url TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(channel_id, proxy_id)
        )
        ''')
        
        # Create channel to user category mapping table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS channel_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT NOT NULL,
            proxy_id TEXT NOT NULL,
            category_id INTEGER NOT NULL,
            added_at TEXT NOT NULL,
            UNIQUE(channel_id, proxy_id, category_id),
            FOREIGN KEY (category_id) REFERENCES user_categories (id) ON DELETE CASCADE
        )
        ''')
        
        conn.commit()

# Ensure upload directory exists
def ensure_upload_dir():
    upload_dir = os.path.join(current_app.static_folder, 'channel_images')
    if not os.path.exists(upload_dir):
        os.makedirs(upload_dir)
    return upload_dir

# Helper for handling image uploads
def handle_image_upload(file):
    if file:
        # Generate a unique filename
        filename = secure_filename(file.filename)
        filename = f"{uuid.uuid4()}_{filename}"
        
        # Save the file
        upload_dir = ensure_upload_dir()
        file_path = os.path.join(upload_dir, filename)
        file.save(file_path)
        
        # Return the relative path
        return os.path.join('channel_images', filename)
    return None

# API Routes

@channel_api.route('/api/channels', methods=['GET'])
def get_channels():
    """Get channels with pagination, filtering, and sorting"""
    proxy_id = request.args.get('proxy_id')
    if not proxy_id:
        return jsonify({"error": "proxy_id is required"}), 400
    
    # Parse query parameters
    page = int(request.args.get('page', 1))
    page_size = int(request.args.get('pageSize', 25))
    search = request.args.get('search', '')
    category = request.args.get('category', '')
    sort_by = request.args.get('sortBy', 'name')
    sort_dir = request.args.get('sortDirection', 'asc')
    
    # Validate sorting parameters to prevent SQL injection
    if sort_by not in ['name', 'number', 'group']:
        sort_by = 'name'
    if sort_dir not in ['asc', 'desc']:
        sort_dir = 'asc'
    
    # Get the M3U data
    m3u_path = os.path.join('data/m3u_proxy', proxy_id, 'playlist.m3u')
    if not os.path.exists(m3u_path):
        return jsonify({"error": "M3U file not found"}), 404
    
    # Parse the M3U file
    channels = parse_m3u_channels(m3u_path)
    
    # Apply search filter
    if search:
        search_lower = search.lower()
        channels = [c for c in channels if search_lower in c['name'].lower()]
    
    # Apply category filter
    if category:
        channels = [c for c in channels if c['group'] == category]
    
    # Get total count before pagination
    total_channels = len(channels)
    
    # Apply sorting
    reverse = sort_dir == 'desc'
    if sort_by == 'name':
        channels.sort(key=lambda x: x['name'].lower(), reverse=reverse)
    elif sort_by == 'number':
        channels.sort(key=lambda x: x['number'] or 0, reverse=reverse)
    elif sort_by == 'group':
        channels.sort(key=lambda x: x['group'].lower(), reverse=reverse)
    
    # Add image URLs to channels
    channels = add_channel_images(channels, proxy_id)
    
    # Apply pagination
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    paginated_channels = channels[start_idx:end_idx]
    
    # Calculate total pages
    total_pages = (total_channels + page_size - 1) // page_size
    
    return jsonify({
        "channels": paginated_channels,
        "totalChannels": total_channels,
        "totalPages": total_pages,
        "currentPage": page
    })

@channel_api.route('/api/categories', methods=['GET'])
def get_categories():
    """Get all categories from an M3U"""
    proxy_id = request.args.get('proxy_id')
    if not proxy_id:
        return jsonify({"error": "proxy_id is required"}), 400
    
    # Get the M3U data
    m3u_path = os.path.join('data/m3u_proxy', proxy_id, 'playlist.m3u')
    if not os.path.exists(m3u_path):
        return jsonify({"error": "M3U file not found"}), 404
    
    # Parse the M3U file and extract unique categories
    channels = parse_m3u_channels(m3u_path)
    categories = sorted(list(set(c['group'] for c in channels if c['group'])))
    
    return jsonify(categories)

@channel_api.route('/api/user-categories', methods=['GET'])
def get_user_categories():
    """Get all user-created categories"""
    proxy_id = request.args.get('proxy_id')
    if not proxy_id:
        return jsonify({"error": "proxy_id is required"}), 400
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Get all categories with channel counts
        cursor.execute('''
        SELECT c.*, COUNT(cc.id) as channel_count
        FROM user_categories c
        LEFT JOIN channel_categories cc ON c.id = cc.category_id AND cc.proxy_id = ?
        GROUP BY c.id
        ORDER BY c.name
        ''', (proxy_id,))
        
        categories = cursor.fetchall()
        
        return jsonify(categories)

@channel_api.route('/api/user-categories', methods=['POST'])
def create_user_category():
    """Create a new user category"""
    proxy_id = request.json.get('proxy_id')
    name = request.json.get('name')
    
    if not proxy_id:
        return jsonify({"error": "proxy_id is required"}), 400
    if not name:
        return jsonify({"error": "name is required"}), 400
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Insert new category
        cursor.execute('''
        INSERT INTO user_categories (name, created_at, updated_at)
        VALUES (?, ?, ?)
        ''', (name, now, now))
        
        conn.commit()
        
        # Get the inserted category
        cursor.execute('''
        SELECT * FROM user_categories WHERE id = ?
        ''', (cursor.lastrowid,))
        
        category = cursor.fetchone()
        
        return jsonify(category), 201

@channel_api.route('/api/user-categories/<int:category_id>', methods=['PUT'])
def update_user_category(category_id):
    """Update a user category"""
    name = request.json.get('name')
    
    if not name:
        return jsonify({"error": "name is required"}), 400
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Update category
        cursor.execute('''
        UPDATE user_categories
        SET name = ?, updated_at = ?
        WHERE id = ?
        ''', (name, now, category_id))
        
        conn.commit()
        
        if cursor.rowcount == 0:
            return jsonify({"error": "Category not found"}), 404
        
        # Get the updated category
        cursor.execute('''
        SELECT * FROM user_categories WHERE id = ?
        ''', (category_id,))
        
        category = cursor.fetchone()
        
        return jsonify(category)

@channel_api.route('/api/user-categories/<int:category_id>', methods=['DELETE'])
def delete_user_category(category_id):
    """Delete a user category"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Delete category
        cursor.execute('''
        DELETE FROM user_categories
        WHERE id = ?
        ''', (category_id,))
        
        conn.commit()
        
        if cursor.rowcount == 0:
            return jsonify({"error": "Category not found"}), 404
        
        return jsonify({"message": "Category deleted successfully"})

@channel_api.route('/api/user-categories/<int:category_id>/channels', methods=['POST'])
def add_channel_to_category(category_id):
    """Add a channel to a category"""
    proxy_id = request.json.get('proxy_id')
    channel_id = request.json.get('channel_id')
    
    if not proxy_id:
        return jsonify({"error": "proxy_id is required"}), 400
    if not channel_id:
        return jsonify({"error": "channel_id is required"}), 400
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Check if category exists
        cursor.execute('''
        SELECT * FROM user_categories WHERE id = ?
        ''', (category_id,))
        
        category = cursor.fetchone()
        if not category:
            return jsonify({"error": "Category not found"}), 404
        
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        try:
            # Add channel to category
            cursor.execute('''
            INSERT INTO channel_categories (channel_id, proxy_id, category_id, added_at)
            VALUES (?, ?, ?, ?)
            ''', (channel_id, proxy_id, category_id, now))
            
            conn.commit()
            
            return jsonify({"message": "Channel added to category successfully"})
        except sqlite3.IntegrityError:
            # Channel already in category
            return jsonify({"message": "Channel already in category"}), 200

@channel_api.route('/api/user-categories/<int:category_id>/channels/<channel_id>', methods=['DELETE'])
def remove_channel_from_category(category_id, channel_id):
    """Remove a channel from a category"""
    proxy_id = request.args.get('proxy_id')
    
    if not proxy_id:
        return jsonify({"error": "proxy_id is required"}), 400
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Delete channel from category
        cursor.execute('''
        DELETE FROM channel_categories
        WHERE channel_id = ? AND proxy_id = ? AND category_id = ?
        ''', (channel_id, proxy_id, category_id))
        
        conn.commit()
        
        return jsonify({"message": "Channel removed from category successfully"})

@channel_api.route('/api/channels/<channel_id>/image', methods=['PUT'])
def set_channel_image(channel_id):
    """Set an image for a channel (URL or upload)"""
    proxy_id = request.form.get('proxy_id')
    image_url = request.form.get('image_url')
    
    if not proxy_id:
        return jsonify({"error": "proxy_id is required"}), 400
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        image_path = None
        
        # Handle file upload if present
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename:
                image_path = handle_image_upload(file)
        
        # Check if the channel already has an image
        cursor.execute('''
        SELECT * FROM channel_images
        WHERE channel_id = ? AND proxy_id = ?
        ''', (channel_id, proxy_id))
        
        existing_image = cursor.fetchone()
        
        if existing_image:
            # Update existing image
            cursor.execute('''
            UPDATE channel_images
            SET image_path = ?, image_url = ?, updated_at = ?
            WHERE channel_id = ? AND proxy_id = ?
            ''', (image_path, image_url, now, channel_id, proxy_id))
        else:
            # Insert new image record
            cursor.execute('''
            INSERT INTO channel_images (channel_id, proxy_id, image_path, image_url, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ''', (channel_id, proxy_id, image_path, image_url, now, now))
        
        conn.commit()
        
        # Generate image URL for response
        image_url_response = None
        if image_path:
            image_url_response = url_for('static', filename=image_path, _external=True)
        elif image_url:
            image_url_response = image_url
        
        return jsonify({
            "message": "Channel image updated successfully",
            "imageUrl": image_url_response
        })

@channel_api.route('/api/channels/<channel_id>/image', methods=['GET'])
def get_channel_image(channel_id):
    """Get a channel's image"""
    proxy_id = request.args.get('proxy_id')
    
    if not proxy_id:
        return jsonify({"error": "proxy_id is required"}), 400
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Get the channel image
        cursor.execute('''
        SELECT * FROM channel_images
        WHERE channel_id = ? AND proxy_id = ?
        ''', (channel_id, proxy_id))
        
        image = cursor.fetchone()
        
        if not image:
            return jsonify({"error": "Image not found"}), 404
        
        # Generate image URL for response
        image_url_response = None
        if image['image_path']:
            image_url_response = url_for('static', filename=image['image_path'], _external=True)
        elif image['image_url']:
            image_url_response = image['image_url']
        
        return jsonify({
            "imageUrl": image_url_response
        })

# Helper functions

def parse_m3u_channels(m3u_path):
    """Parse an M3U file and extract channels"""
    channels = []
    
    with open(m3u_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
    
    channel_id = 0
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        if line.startswith('#EXTINF:'):
            channel_id += 1
            
            # Extract channel properties
            # tvg-id, tvg-name, tvg-logo, group-title, tvg-chno
            tvg_id_match = re.search(r'tvg-id="([^"]*)"', line)
            tvg_name_match = re.search(r'tvg-name="([^"]*)"', line)
            tvg_logo_match = re.search(r'tvg-logo="([^"]*)"', line)
            group_match = re.search(r'group-title="([^"]*)"', line)
            tvg_chno_match = re.search(r'tvg-chno="([^"]*)"', line)
            
            # Extract channel name (everything after the last comma)
            name_parts = line.split(',')
            name = name_parts[-1].strip() if len(name_parts) > 1 else ""
            
            # Get the URL from the next line
            if i + 1 < len(lines):
                url = lines[i + 1].strip()
                
                channel = {
                    'id': str(channel_id),
                    'name': name,
                    'url': url,
                    'group': group_match.group(1) if group_match else "",
                    'number': int(tvg_chno_match.group(1)) if tvg_chno_match else channel_id,
                    'tvg_id': tvg_id_match.group(1) if tvg_id_match else "",
                    'tvg_name': tvg_name_match.group(1) if tvg_name_match else name,
                    'tvg_logo': tvg_logo_match.group(1) if tvg_logo_match else ""
                }
                
                channels.append(channel)
                i += 2  # Skip the URL line
            else:
                i += 1
        else:
            i += 1
    
    return channels

def add_channel_images(channels, proxy_id):
    """Add image URLs to channels from the database"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Get all channel images for this proxy
        cursor.execute('''
        SELECT channel_id, image_path, image_url FROM channel_images
        WHERE proxy_id = ?
        ''', (proxy_id,))
        
        images = cursor.fetchall()
        
        # Convert to dict for easy lookup
        image_dict = {img['channel_id']: img for img in images}
        
        # Add image URLs to channels
        for channel in channels:
            channel['imageUrl'] = None
            
            if channel['id'] in image_dict:
                img = image_dict[channel['id']]
                if img['image_path']:
                    channel['imageUrl'] = url_for('static', filename=img['image_path'], _external=True)
                elif img['image_url']:
                    channel['imageUrl'] = img['image_url']
    
    return channels

# Initialize the database when blueprint is registered
@channel_api.record
def record_params(setup_state):
    app = setup_state.app
    with app.app_context():
        init_channel_manager_db()
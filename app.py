from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, make_response
import os
import aiohttp
import asyncio
import urllib.request
from werkzeug.utils import secure_filename
import streamClasses
import logger
from logger import LogLevel
import tools
import db
import notifications
from apscheduler.schedulers.background import BackgroundScheduler
import atexit
import json
import time
import re
from datetime import datetime
import logging
from processing_monitor import processing_monitor
from sse_notifications import get_sse_response, send_notification
import uuid
import threading
import m3u_editor
from channel_manager import setup_channel_manager
from proxy_api import register_proxy_api

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # Change this to a random string

# Configure upload folder
UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Configure allowed extensions
ALLOWED_EXTENSIONS = {'m3u'}

# Ensure directories exist
os.makedirs('data', exist_ok=True)
os.makedirs('logs', exist_ok=True)
os.makedirs('content', exist_ok=True)

# Ensure static folder exists
STATIC_FOLDER = 'static'
if not os.path.exists(STATIC_FOLDER):
    os.makedirs(STATIC_FOLDER)
if not os.path.exists(os.path.join(STATIC_FOLDER, 'css')):
    os.makedirs(os.path.join(STATIC_FOLDER, 'css'))
if not os.path.exists(os.path.join(STATIC_FOLDER, 'js')):
    os.makedirs(os.path.join(STATIC_FOLDER, 'js'))

# Initialize scheduler
scheduler = BackgroundScheduler()
scheduler.start()

# Initialize proxy
proxy_manager = m3u_editor.M3UProxyManager()
register_proxy_api(app)

# Initialize Channel Manager
setup_channel_manager(app)

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

async def async_download_m3u(url, save_path):
    """Download M3U file from URL with browser-like behavior and longer timeouts"""
    try:
        logger.info(f'Downloading M3U from URL: {url}')
        
        # Browser-like headers to avoid being blocked
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'max-age=0',
        }
        
        # Create a TCP connector with longer timeouts
        connector = aiohttp.TCPConnector(
            ssl=False,  # Allow for non-SSL connections
            limit=10,   # Limit number of connections
            ttl_dns_cache=300,  # Cache DNS resolutions
            force_close=False,  # Keep connections alive when possible
        )
        
        # Extend timeouts significantly
        timeout = aiohttp.ClientTimeout(
            total=180,        # 3 minutes total timeout
            connect=60,       # 60 seconds to establish connection
            sock_read=60,     # 60 seconds to read data
            sock_connect=60   # 60 seconds to connect to peer
        )
        
        # Start the download
        async with aiohttp.ClientSession(headers=headers, connector=connector, timeout=timeout) as session:
            # Manually handle redirects to avoid potential issues
            max_redirects = 10
            current_url = url
            redirect_count = 0
            
            while redirect_count < max_redirects:
                logger.info(f'Trying URL: {current_url} (redirect {redirect_count})')
                
                try:
                    async with session.get(current_url, allow_redirects=False) as response:
                        # Handle redirects manually
                        if response.status in (301, 302, 303, 307, 308):
                            if 'Location' in response.headers:
                                current_url = response.headers['Location']
                                # Make URL absolute if it's relative
                                if not current_url.startswith(('http://', 'https://')):
                                    # Join with base URL
                                    parsed_url = urllib.parse.urlparse(url)
                                    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
                                    current_url = urllib.parse.urljoin(base_url, current_url)
                                    
                                logger.info(f'Following redirect to: {current_url}')
                                redirect_count += 1
                                continue
                            else:
                                logger.error('Redirect without Location header')
                                return {
                                    'status': 'error',
                                    'message': 'Redirect without Location header'
                                }
                        
                        # If we got here, it's either a success or an error (not a redirect)
                        logger.info(f'Response status code: {response.status}')
                        
                        if response.status == 200:
                            content = await response.read()
                            logger.info(f'Downloaded content size: {len(content)} bytes')
                            
                            # Save the content
                            with open(save_path, 'wb') as f:
                                f.write(content)
                                
                            logger.info(f'M3U file saved to: {save_path}')
                            
                            return {
                                'status': 'success',
                                'message': f'Downloaded M3U file from URL: {url}',
                                'path': save_path,
                                'size': len(content)
                            }
                        else:
                            error_text = await response.text()
                            logger.error(f'Error downloading M3U file: HTTP {response.status} - {error_text[:200]}')
                            return {
                                'status': 'error',
                                'message': f'Error downloading M3U file: HTTP {response.status} - Server response: {error_text[:100]}...'
                            }
                except aiohttp.ClientError as ce:
                    logger.error(f'Client error at URL {current_url}: {str(ce)}')
                    return {
                        'status': 'error',
                        'message': f'Connection error: {str(ce)}'
                    }
            
            # If we got here, we reached the max number of redirects
            return {
                'status': 'error',
                'message': f'Too many redirects (max: {max_redirects})'
            }
                
    except asyncio.TimeoutError:
        logger.error(f'Timeout error downloading from URL: {url}')
        return {
            'status': 'error',
            'message': f'Timeout error downloading M3U file. The server took too long to respond. Try increasing the timeout or check server availability.'
        }
    except Exception as e:
        logger.error(f'Error downloading M3U file: {str(e)}', exc_info=True)
        return {
            'status': 'error',
            'message': f'Error downloading M3U file: {str(e)}'
        }

def download_m3u(url, save_path):
    """Synchronous wrapper for async_download_m3u with better error handling"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(async_download_m3u(url, save_path))
        finally:
            loop.close()
    except Exception as e:
        logger.error(f'Error in download_m3u: {str(e)}', exc_info=True)
        return {
            'status': 'error',
            'message': f'Unexpected error during download: {str(e)}'
        }

async def async_process_m3u(file_path, user_path=None, url=None, job_id=None):
    """Process an M3U file asynchronously with enhanced error handling and debugging"""
    logger.info(f'Starting optimized M3U processing: {file_path}')
    
    # Verify file exists and has content (keep this part from original)
    if not os.path.exists(file_path):
        error_msg = f"Error: M3U file not found at {file_path}"
        logger.error(error_msg)
        return {
            'status': 'error',
            'message': error_msg
        }
        
    file_size = os.path.getsize(file_path)
    if file_size == 0:
        error_msg = f"Error: M3U file is empty ({file_path})"
        logger.error(error_msg)
        return {
            'status': 'error',
            'message': error_msg
        }
        
    logger.info(f'M3U file exists and has size: {file_size} bytes')
    
    try:
        # Handle custom output path (keep this part from original)
        if user_path and os.path.exists(user_path):
            config = db.load_config()
            config["output_path"] = user_path
            db.save_config(config)
            logger.info(f'Using custom output path: {user_path}')
        else:
            config = db.load_config()
            logger.info(f'Using default output path: {config.get("output_path", "content")}')
            
        # Verify the output directory exists and is writable
        content_path = config.get("output_path", "content")
        if not os.path.exists(content_path):
            try:
                logger.info(f'Creating output directory: {content_path}')
                os.makedirs(content_path, exist_ok=True)
            except Exception as e:
                error_msg = f"Error creating output directory: {str(e)}"
                logger.error(error_msg)
                return {
                    'status': 'error',
                    'message': error_msg
                }
        
        # Import optimized processor
        from m3u_optimizer import process_m3u_optimized
        
        # Process the M3U file using optimized processor
        logger.info('Starting optimized M3U processing')
        try:
            # Get batch size from config (add this to your settings UI)
            batch_size = config.get("processing_batch_size", 100)
            
            # Process using optimized method
            stats = await process_m3u_optimized(file_path, content_path, url, batch_size)
            
            logger.info(f'Processing completed with stats: {stats}')
            
            # Count content directories (keep this part from original)
            movie_path = os.path.join(content_path, 'Movies')
            tv_shows_path = os.path.join(content_path, 'TV Shows')
            
            movie_count = sum(1 for f in os.listdir(movie_path) if os.path.isdir(os.path.join(movie_path, f))) if os.path.exists(movie_path) else 0
            tv_count = sum(1 for f in os.listdir(tv_shows_path) if os.path.isdir(os.path.join(tv_shows_path, f))) if os.path.exists(tv_shows_path) else 0
            
            logger.info(f'Found {movie_count} movies and {tv_count} TV shows in content directory')
            
            # Build result
            result = {
                'status': 'success',
                'message': f'Processed M3U file: {os.path.basename(file_path)}',
                'movies': movie_count,
                'tv_shows': tv_count,
                'skipped': stats.get('skip_count', 0),
                'processed_movies': stats.get('movies_count', 0),
                'processed_tv': stats.get('tv_count', 0)
            }
            
            # Send a summary notification
            webhook_config = db.load_config()
            if webhook_config.get("notifications_enabled", False):
                webhook_url = webhook_config.get("discord_webhook_url", "")
                # Use the summary notification with collected changes
                changes = stats.get('changes', {})
                await notifications.notify_summary(webhook_url, url, changes)
            
            return result
        except Exception as process_error:
            logger.error(f'Error during optimized M3U processing: {str(process_error)}', exc_info=True)
            
            # Try to extract more detailed error information
            error_details = str(process_error)
            if hasattr(process_error, '__cause__') and process_error.__cause__:
                error_details += f" Caused by: {str(process_error.__cause__)}"
                
            return {
                'status': 'error',
                'message': f'Error processing M3U file: {error_details}'
            }
    except Exception as e:
        logger.error(f'Unexpected error processing M3U file: {str(e)}', exc_info=True)
        
        # Send error notification
        webhook_config = db.load_config()
        if webhook_config.get("notifications_enabled", False):
            webhook_url = webhook_config.get("discord_webhook_url", "")
            await notifications.notify_error(webhook_url, str(e), url)
        
        return {
            'status': 'error',
            'message': f'Unexpected error processing M3U file: {str(e)}'
        }

def process_m3u(file_path, user_path=None, url=None, job_id=None):
    """Synchronous wrapper for async_process_m3u with better error handling"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(async_process_m3u(file_path, user_path, url, job_id))
        finally:
            loop.close()
    except Exception as e:
        logger.error(f'Error in process_m3u: {str(e)}', exc_info=True)
        return {
            'status': 'error',
            'message': f'Unexpected error during M3U processing: {str(e)}'
        }

async def async_check_m3u_update(url, filename, output_path=None):
    """Check if M3U file needs to be updated asynchronously"""
    logger.info(f'Checking for updates to M3U file: {url}')
    
    save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    download_result = await async_download_m3u(url, save_path)
    
    if download_result['status'] == 'success':
        # Get content before processing
        content_before = _scan_content_dirs()
        
        # Process the file - note we pass the URL here
        process_result = await async_process_m3u(save_path, output_path, url)
        
        # Get content after processing
        content_after = _scan_content_dirs()
        
        # Compare for changes
        changes = _detect_content_changes(content_before, content_after)
        
        # Update last check time
        await db.async_update_m3u_link_last_check(url)
            
        logger.info(f'Updated M3U file: {url}')
        
        # Send a single summary notification
        webhook_config = db.load_config()
        if webhook_config.get("notifications_enabled", False):
            webhook_url = webhook_config.get("discord_webhook_url", "")
            await notifications.notify_summary(webhook_url, url, changes)
        
        return {
            'status': 'success',
            'changes': changes,
            'process_result': process_result
        }
    else:
        logger.error(f'Error updating M3U file: {download_result["message"]}')
        
        # Send error notification
        webhook_config = db.load_config()
        if webhook_config.get("notifications_enabled", False):
            webhook_url = webhook_config.get("discord_webhook_url", "")
            await notifications.notify_error(webhook_url, download_result["message"], url)
        
        return {
            'status': 'error',
            'message': download_result["message"]
        }

def check_m3u_update(url, filename, output_path=None):
    """Synchronous wrapper for async_check_m3u_update"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(async_check_m3u_update(url, filename, output_path))
    finally:
        loop.close()

def _scan_content_dirs():
    """Scan content directories to build a list of current files"""
    config = db.load_config()
    content_path = config.get("output_path", "content")
    
    content = {
        "movies": set(),
        "tv": set()
    }
    
    # Scan movies
    movie_path = os.path.join(content_path, 'Movies')
    if os.path.exists(movie_path):
        for movie_dir in os.listdir(movie_path):
            movie_full_path = os.path.join(movie_path, movie_dir)
            if os.path.isdir(movie_full_path):
                for file in os.listdir(movie_full_path):
                    if file.endswith(".strm"):
                        content["movies"].add(os.path.join(movie_dir, file))
    
    # Scan TV shows
    tv_path = os.path.join(content_path, 'TV Shows')
    if os.path.exists(tv_path):
        for show_dir in os.listdir(tv_path):
            show_full_path = os.path.join(tv_path, show_dir)
            if os.path.isdir(show_full_path):
                for season_or_file in os.listdir(show_full_path):
                    season_full_path = os.path.join(show_full_path, season_or_file)
                    
                    if os.path.isdir(season_full_path):
                        # This is a season directory
                        for episode_file in os.listdir(season_full_path):
                            if episode_file.endswith(".strm"):
                                content["tv"].add(os.path.join(show_dir, season_or_file, episode_file))
                    elif season_or_file.endswith(".strm"):
                        # This is a direct episode file
                        content["tv"].add(os.path.join(show_dir, season_or_file))
    
    return content

def _detect_content_changes(before, after):
    """Detect content changes by comparing before and after scans"""
    # Find new content
    new_movies = after["movies"] - before["movies"]
    new_tv = after["tv"] - before["tv"]
    
    # Find removed content
    removed_movies = before["movies"] - after["movies"]
    removed_tv = before["tv"] - after["tv"]
    
    # Calculate statistics
    return {
        "added": len(new_movies) + len(new_tv),
        "removed": len(removed_movies) + len(removed_tv),
        "updated": 0  # We don't track updates here
    }

async def async_schedule_m3u_check(url, filename, output_path=None, hours=24):
    """Schedule a check for M3U updates asynchronously"""
    job = scheduler.add_job(
        check_m3u_update,
        'interval',
        hours=hours,
        args=[url, filename, output_path]
    )
    
    # Update next check time
    next_check = (datetime.now() + job.trigger.interval).strftime("%Y-%m-%d %H:%M:%S")
    await db.async_update_m3u_link_next_check(url, next_check)

def schedule_m3u_check(url, filename, output_path=None, hours=24):
    """Synchronous wrapper for async_schedule_m3u_check"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(async_schedule_m3u_check(url, filename, output_path, hours))
    finally:
        loop.close()

# Load saved M3U links and schedule checks on startup
for link in db.load_m3u_links():
    schedule_m3u_check(
        link['url'], 
        link['filename'], 
        link.get('output_path'),
        link.get('update_frequency', 24)
    )

@app.route('/')
def index():
    config = db.load_config()
    theme = config.get('ui_theme', 'dark')
    return render_template('index.html', theme=theme)

@app.route('/status')
def status():
    links = db.load_m3u_links()
    config = db.load_config()
    
    # Count movies and TV shows
    content_path = config.get("output_path", "content")
    movie_path = os.path.join(content_path, 'Movies')
    tv_shows_path = os.path.join(content_path, 'TV Shows')
    
    movie_count = sum(1 for f in os.listdir(movie_path) if os.path.isdir(os.path.join(movie_path, f))) if os.path.exists(movie_path) else 0
    tv_count = sum(1 for f in os.listdir(tv_shows_path) if os.path.isdir(os.path.join(tv_shows_path, f))) if os.path.exists(tv_shows_path) else 0
    
    # Get recent content changes
    recent_changes = db.get_recent_content_changes(10)
    
    theme = config.get('ui_theme', 'dark')
    return render_template('status.html', 
                           links=links, 
                           movie_count=movie_count, 
                           tv_count=tv_count, 
                           theme=theme, 
                           content_path=content_path,
                           recent_changes=recent_changes)

@app.route('/remove_link/<path:url>')
def remove_link(url):
    if db.remove_m3u_link(url):
        flash(f'Removed scheduled updates for: {url}')
    else:
        flash(f'Error: Could not find link {url}')
    return redirect(url_for('status'))

@app.route('/config')
def config_page():
    config = db.load_config()
    theme = config.get('ui_theme', 'dark')
    return render_template('config.html', config=config, theme=theme)

@app.route('/save_config', methods=['POST'])
def save_config_route():
    try:
        config = db.load_config()
        
        # Update configuration with form values
        config["output_path"] = request.form.get('output_path', 'content')
        config["log_level"] = request.form.get('log_level', 'NORMAL')
        config["language_filter"] = request.form.get('language_filter', 'EN')
        config["skip_non_english"] = 'skip_non_english' in request.form
        config["ui_theme"] = request.form.get('ui_theme', 'dark')
        config["discord_webhook_url"] = request.form.get('discord_webhook_url', '')
        config["notifications_enabled"] = 'notifications_enabled' in request.form
        
        # Update frequency value
        try:
            update_frequency = int(request.form.get('update_frequency', '24'))
            config["update_frequency"] = update_frequency
        except ValueError:
            config["update_frequency"] = 24
        
        # Handle keywords as comma-separated lists
        movie_keywords = request.form.get('movie_keywords', '')
        tv_keywords = request.form.get('tv_keywords', '')
        
        config["movie_keywords"] = [k.strip() for k in movie_keywords.split(',') if k.strip()]
        config["tv_keywords"] = [k.strip() for k in tv_keywords.split(',') if k.strip()]
        
        # Save configuration
        db.save_config(config)
        
        # Update scheduled tasks if update frequency has changed
        links = db.load_m3u_links()
        for link in links:
            if link.get('update_frequency', 24) != update_frequency:
                schedule_m3u_check(link['url'], link['filename'], link.get('output_path'), update_frequency)
        
        flash('Configuration saved successfully')
    except Exception as e:
        logger.error(f"Error saving configuration: {str(e)}")
        flash(f'Error saving configuration: {str(e)}')
    
    return redirect(url_for('config_page'))

@app.route('/scan_content')
def scan_content():
    try:
        config = db.load_config()
        content_path = config.get('output_path', 'content')
        
        # Create content directories if they don't exist
        movie_path = os.path.join(content_path, 'Movies')
        tv_path = os.path.join(content_path, 'TV Shows')
        
        if not os.path.exists(content_path):
            os.makedirs(content_path)
        if not os.path.exists(movie_path):
            os.makedirs(movie_path)
        if not os.path.exists(tv_path):
            os.makedirs(tv_path)
        
        # Count movies and TV shows
        movie_count = sum(1 for f in os.listdir(movie_path) if os.path.isdir(os.path.join(movie_path, f)))
        tv_count = sum(1 for f in os.listdir(tv_path) if os.path.isdir(os.path.join(tv_path, f)))
        
        flash(f'Content scanned: Found {movie_count} movies and {tv_count} TV shows in {content_path}')
    except Exception as e:
        logger.error(f"Error scanning content: {str(e)}")
        flash(f'Error scanning content: {str(e)}')
    
    return redirect(url_for('status'))

@app.route('/theme/<theme>')
def set_theme(theme):
    if theme in ['light', 'dark']:
        config = db.load_config()
        config['ui_theme'] = theme
        db.save_config(config)
    return redirect(request.referrer or url_for('index'))

@app.route('/test_webhook', methods=['POST'])
def test_webhook():
    """Test the Discord webhook configuration"""
    webhook_url = request.form.get('webhook_url', '')
    
    if not webhook_url:
        return jsonify({
            'status': 'error',
            'message': 'No webhook URL provided'
        })
    
    try:
        # Run the test in a background thread to avoid blocking the request
        def test_webhook_bg():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(notifications.notify_process_complete(
                    webhook_url, 
                    None, 
                    {"test": True, "movies_count": 1, "tv_count": 1}
                ))
                return result
            finally:
                loop.close()
                
        # Run the test
        success = test_webhook_bg()
        
        if success:
            return jsonify({
                'status': 'success',
                'message': 'Webhook test successful!'
            })
        else:
            return jsonify({
                'status': 'error',
                'message': 'Failed to send test notification. Please check your webhook URL.'
            })
    except Exception as e:
        logger.error(f"Error testing webhook: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'Error testing webhook: {str(e)}'
        })

@app.route('/content_history')
def content_history():
    """View content change history"""
    changes = db.get_recent_content_changes(100)
    stats = db.get_content_stats()
    
    config = db.load_config()
    theme = config.get('ui_theme', 'dark')
    
    return render_template(
        'history.html', 
        changes=changes, 
        stats=stats, 
        theme=theme
    )

@app.route('/check_now/<path:url>')
def check_now(url):
    """Manually trigger a check for a specific M3U URL"""
    links = db.load_m3u_links()
    
    # Find the link
    link_data = None
    for link in links:
        if link['url'] == url:
            link_data = link
            break
    
    if not link_data:
        flash(f'Error: Could not find link {url}')
        return redirect(url_for('status'))
        
    # Run the check
    try:
        result = check_m3u_update(
            link_data['url'], 
            link_data['filename'], 
            link_data.get('output_path')
        )
        
        if result['status'] == 'success':
            changes = result['changes']
            flash(f'Check completed: {changes["added"]} items added, {changes["removed"]} items removed')
        else:
            flash(f'Error checking URL: {result["message"]}')
    except Exception as e:
        logger.error(f"Error performing manual check: {str(e)}")
        flash(f'Error checking URL: {str(e)}')
    
    return redirect(url_for('status'))

@app.route('/api/status', methods=['GET'])
def api_status():
    """API endpoint for getting status information"""
    try:
        links = db.load_m3u_links()
        config = db.load_config()
        
        # Count movies and TV shows
        content_path = config.get("output_path", "content")
        movie_path = os.path.join(content_path, 'Movies')
        tv_shows_path = os.path.join(content_path, 'TV Shows')
        
        movie_count = sum(1 for f in os.listdir(movie_path) if os.path.isdir(os.path.join(movie_path, f))) if os.path.exists(movie_path) else 0
        tv_count = sum(1 for f in os.listdir(tv_shows_path) if os.path.isdir(os.path.join(tv_shows_path, f))) if os.path.exists(tv_shows_path) else 0
        
        # Get recent content changes
        recent_changes = db.get_recent_content_changes(10)
        
        return jsonify({
            'status': 'success',
            'data': {
                'content': {
                    'movies': movie_count,
                    'tv_shows': tv_count,
                    'path': content_path
                },
                'links': links,
                'recent_changes': recent_changes
            }
        })
    except Exception as e:
        logger.error(f"API error: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500
    
@app.route('/events')
def events():
    """SSE endpoint for real-time notifications"""
    return get_sse_response()

@app.route('/api/job_status/<job_id>')
def job_status(job_id):
    """Get status of a specific job"""
    job = processing_monitor.get_job(job_id)
    
    if job:
        return jsonify({
            'status': 'success',
            'data': job
        })
    else:
        return jsonify({
            'status': 'error',
            'message': f'Job {job_id} not found'
        }), 404

@app.route('/api/active_jobs')
def active_jobs():
    """Get all active processing jobs"""
    jobs = processing_monitor.get_active_jobs()
    
    return jsonify({
        'status': 'success',
        'data': jobs
    })

@app.route('/api/job_history')
def job_history():
    """Get processing job history"""
    history = processing_monitor.get_job_history()
    
    return jsonify({
        'status': 'success',
        'data': history
    })

@app.route('/processing')
def processing_page():
    """View active and recent processing jobs"""
    active = processing_monitor.get_active_jobs()
    history = processing_monitor.get_job_history()
    
    config = db.load_config()
    theme = config.get('ui_theme', 'dark')
    
    return render_template(
        'processing.html', 
        active_jobs=active,
        job_history=history,
        theme=theme
    )

@app.route('/upload', methods=['POST'])
def upload_file():
    """Handle M3U file uploads and URL processing"""
    # Create a unique job ID
    job_id = str(uuid.uuid4())
    
    # Check if the post request has the file part or URL
    if 'file' not in request.files and 'url' not in request.form:
        flash('No file or URL provided')
        return redirect(url_for('index'))
    
    # Get output path if provided
    output_path = request.form.get('output_path', '')
    if output_path and not os.path.exists(output_path):
        flash(f'Output path does not exist: {output_path}')
        return redirect(url_for('index'))
    
    # Process file upload
    if 'file' in request.files and request.files['file'].filename != '':
        try:
            file = request.files['file']
            
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)
                
                # Send initial notification
                send_notification("Processing Started", f"Started processing file: {filename}", "info")
                
                # Process the file (async)
                def process_async():
                    try:
                        result = process_m3u(file_path, output_path, None, job_id)
                        
                        # Flash message just in case the user reloads the page
                        if result['status'] == 'success':
                            flash(f'File processed successfully: {result["processed_movies"]} movies and {result["processed_tv"]} TV shows created, {result["skipped"]} entries skipped')
                        else:
                            flash(f'Error processing file: {result["message"]}')
                    except Exception as e:
                        logger.error(f"Error in async processing thread: {str(e)}")
                
                # Start processing in background thread
                processing_thread = threading.Thread(target=process_async)
                processing_thread.daemon = True
                processing_thread.start()
                
                # Redirect to the processing status page
                return redirect(url_for('processing_page'))
            else:
                flash('Invalid file format. Please upload an M3U file.')
                return redirect(url_for('index'))
        except Exception as e:
            logger.error(f"Error handling file upload: {str(e)}")
            flash(f'Error processing file: {str(e)}')
            return redirect(url_for('index'))
    
    # Process URL
    if 'url' in request.form and request.form['url'] != '':
        try:
            url = request.form['url'].strip()  # Ensure URL is stripped of whitespace
            
            if not url.startswith(('http://', 'https://')):
                flash('Invalid URL format. URL must start with http:// or https://')
                return redirect(url_for('index'))
                
            filename = f"m3u_{int(time.time())}.m3u"
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            
            # Send initial notification
            send_notification("Download Started", f"Started downloading M3U from URL", "info")
            
            # Download the M3U file
            download_result = download_m3u(url, file_path)
            
            if download_result['status'] == 'success':
                # Send notification
                send_notification("Download Complete", f"Successfully downloaded M3U from URL", "success")
                
                # Send initial processing notification
                send_notification("Processing Started", f"Started processing M3U from URL", "info")
                
                # Check for schedule_update checkbox
                schedule_updates = 'schedule_update' in request.form
                logger.info(f"Schedule updates checkbox value: {schedule_updates}")
                
                # Process the file (async)
                def process_url_async():
                    try:
                        result = process_m3u(file_path, output_path, url, job_id)
                        
                        # Save the URL for periodic updates if checkbox is checked
                        if schedule_updates:
                            logger.info(f"Scheduling updates for URL: {url}")
                            config = db.load_config()
                            update_frequency = config.get("update_frequency", 24)
                            
                            # Save to database with explicit commit
                            try:
                                db.save_m3u_link(url, filename, output_path, update_frequency)
                                logger.info(f"Saved M3U link to database: {url}")
                                
                                # Schedule the check
                                schedule_m3u_check(url, filename, output_path, update_frequency)
                                logger.info(f"Scheduled check for URL: {url}")
                                
                                flash(f'URL scheduled for updates every {update_frequency} hours')
                            except Exception as db_error:
                                logger.error(f"Error saving M3U link: {str(db_error)}")
                                flash(f'Error scheduling updates: {str(db_error)}')
                        
                        # Flash message just in case the user reloads the page
                        if result['status'] == 'success':
                            flash(f'URL processed successfully: {result["processed_movies"]} movies and {result["processed_tv"]} TV shows created, {result["skipped"]} entries skipped')
                        else:
                            flash(f'Error processing URL: {result["message"]}')
                    except Exception as e:
                        logger.error(f"Error in async URL processing thread: {str(e)}")
                
                # Start processing in background thread
                processing_thread = threading.Thread(target=process_url_async)
                processing_thread.daemon = True
                processing_thread.start()
                
                # Redirect to the processing status page
                return redirect(url_for('processing_page'))
            else:
                # Send notification
                send_notification("Download Failed", f"Failed to download M3U from URL: {download_result['message']}", "error")
                
                flash(f'Error downloading from URL: {download_result["message"]}')
                return redirect(url_for('index'))
        except Exception as e:
            logger.error(f"Error processing URL: {str(e)}")
            flash(f'Error processing URL: {str(e)}')
            return redirect(url_for('index'))
    
    flash('Invalid file or URL')
    return redirect(url_for('index'))

@app.route('/providers')
def providers_page():
    """View and manage content providers"""
    try:
        from provider_utils import get_provider_stats
        
        stats = get_provider_stats()
        providers = stats.get('providers', [])
        
        # Sort providers by content count (highest first)
        providers.sort(key=lambda p: p.get('content_count', 0), reverse=True)
        
        config = db.load_config()
        theme = config.get('ui_theme', 'dark')
        
        return render_template(
            'providers.html', 
            stats=stats,
            providers=providers,
            theme=theme
        )
    except Exception as e:
        logger.error(f"Error loading providers page: {str(e)}")
        flash(f"Error loading providers: {str(e)}")
        return redirect(url_for('index'))

@app.route('/update_provider_name', methods=['POST'])
def update_provider_name():
    """Update the name of a provider"""
    try:
        data = request.get_json()
        provider_id = data.get('provider_id')
        name = data.get('name')
        
        if not provider_id or not name:
            return jsonify({'status': 'error', 'message': 'Provider ID and name are required'})
        
        from provider_utils import ProviderManager
        
        manager = ProviderManager()
        providers = manager._load_providers()
        
        if provider_id in providers:
            # Get provider URL
            provider_url = providers[provider_id]['url']
            
            # Update the name
            manager.set_provider_name(provider_url, name)
            
            return jsonify({'status': 'success', 'message': 'Provider name updated'})
        else:
            return jsonify({'status': 'error', 'message': 'Provider not found'})
    except Exception as e:
        logger.error(f"Error updating provider name: {str(e)}")
        return jsonify({'status': 'error', 'message': f'Error: {str(e)}'})
    
@app.route('/diagnostics')
def diagnostics_page():
    """Diagnostics page for troubleshooting M3U processing"""
    config = db.load_config()
    theme = config.get('ui_theme', 'dark')
    return render_template('diagnostics.html', theme=theme)

@app.route('/test_m3u_url', methods=['POST'])
def test_m3u_url():
    """Test route for diagnosing M3U URL processing issues"""
    try:
        data = request.get_json()
        url = data.get('url')
        
        if not url:
            return jsonify({
                'status': 'error',
                'message': 'URL is required'
            })
        
        # Create a temporary filename
        filename = f"test_m3u_{int(time.time())}.m3u"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        # Step 1: Download the file
        logger.info(f"TEST: Downloading M3U from URL: {url}")
        download_result = download_m3u(url, file_path)
        
        if download_result['status'] != 'success':
            return jsonify({
                'status': 'error',
                'message': f'Download failed: {download_result["message"]}',
                'phase': 'download'
            })
        
        # Step 2: Verify the downloaded file
        if not os.path.exists(file_path):
            return jsonify({
                'status': 'error',
                'message': f'Downloaded file not found at {file_path}',
                'phase': 'verification'
            })
            
        file_size = os.path.getsize(file_path)
        if file_size == 0:
            return jsonify({
                'status': 'error',
                'message': 'Downloaded file is empty',
                'phase': 'verification'
            })
            
        # Step 3: Read file content sample
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content_sample = f.read(1000)  # Read first 1000 chars
        except Exception as e:
            return jsonify({
                'status': 'error',
                'message': f'Error reading file content: {str(e)}',
                'phase': 'file_reading'
            })
        
        # Step 4: Process the file
        try:
            logger.info(f"TEST: Processing downloaded M3U file: {file_path}")
            process_result = process_m3u(file_path)
            
            # Return the complete test results
            return jsonify({
                'status': 'success',
                'download': download_result,
                'file_info': {
                    'path': file_path,
                    'size': file_size,
                    'content_sample': content_sample[:500]  # First 500 chars
                },
                'process_result': process_result
            })
        except Exception as e:
            return jsonify({
                'status': 'error',
                'message': f'Error processing file: {str(e)}',
                'phase': 'processing',
                'download': download_result,
                'file_info': {
                    'path': file_path,
                    'size': file_size,
                    'content_sample': content_sample[:500]  # First 500 chars
                }
            })
            
    except Exception as e:
        logger.error(f"Error in test_m3u_url: {str(e)}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': f'Unexpected error: {str(e)}',
            'phase': 'test_route'
        })
    
@app.route('/direct_url_check', methods=['GET', 'POST'])
def direct_url_check():
    """Direct URL testing utility to diagnose issues with M3U URLs"""
    config = db.load_config()
    theme = config.get('ui_theme', 'dark')
    
    result = None
    url = None
    
    if request.method == 'POST':
        url = request.form.get('url', '').strip()
        import subprocess
        import sys
        import requests
        from datetime import datetime
        
        # Record start time
        start_time = datetime.now()
        
        try:
            # Try direct request with requests library
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            }
            
            # Make request with a longer timeout
            response = requests.get(url, headers=headers, timeout=60, stream=True)
            
            # Get headers and first chunk of content
            headers_info = dict(response.headers)
            
            # Stream a bit of content
            content_sample = ''
            for chunk in response.iter_content(chunk_size=1024):
                content_sample += chunk.decode('utf-8', errors='ignore')
                if len(content_sample) > 5000:
                    break
            
            # Calculate response time
            response_time = (datetime.now() - start_time).total_seconds()
            
            # Check if it's likely an M3U file
            is_m3u = '#EXTM3U' in content_sample
            
            # Try to ping the server
            if sys.platform.startswith('win'):
                ping_command = ['ping', '-n', '4', urllib.parse.urlparse(url).netloc]
            else:
                ping_command = ['ping', '-c', '4', urllib.parse.urlparse(url).netloc]
                
            ping_result = subprocess.run(ping_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
            
            result = {
                'status': 'success',
                'message': f'Successfully connected to URL (Status: {response.status_code})',
                'response_time': f'{response_time:.2f} seconds',
                'headers': headers_info,
                'content_sample': content_sample[:5000],
                'is_m3u': is_m3u,
                'ping_result': ping_result.stdout,
                'url': url
            }
            
        except requests.Timeout:
            result = {
                'status': 'error',
                'message': 'Connection timed out',
                'url': url
            }
        except requests.ConnectionError:
            result = {
                'status': 'error',
                'message': 'Connection error (server may be down or unreachable)',
                'url': url
            }
        except Exception as e:
            result = {
                'status': 'error',
                'message': f'Error: {str(e)}',
                'url': url
            }
    
    return render_template('direct_url_check.html', theme=theme, result=result, url=url)

@app.route('/filter_settings')
def filter_settings():
    """Enhanced filter settings page"""
    config = db.load_config()
    theme = config.get('ui_theme', 'dark')
    
    # Get processing statistics
    stats = {}
    try:
        # Get the last processing job to extract statistics
        job_history = processing_monitor.get_job_history()
        if job_history:
            latest_job = job_history[0]  # Most recent job
            
            # Calculate totals and percentages
            processed = latest_job.get('items_processed', 0)
            skipped = latest_job.get('skip_count', 0) 
            if not skipped and 'current_item' in latest_job:
                # Try to extract from current_item string
                current_item = latest_job.get('current_item', '')
                if 'skipped' in current_item:
                    parts = current_item.split('skipped:')
                    if len(parts) > 1:
                        try:
                            skipped = int(parts[1].strip().split(' ')[0])
                        except:
                            pass
            
            total = processed + skipped
            skip_percent = round((skipped / total) * 100, 1) if total > 0 else 0
            
            stats = {
                'processed': processed,
                'skipped': skipped,
                'total': total,
                'skip_percent': skip_percent,
                # Skip reasons would need to be tracked separately
                'skip_reasons': {
                    'Language filter': skipped if config.get('skip_non_english', True) else 0,
                }
            }
    except Exception as e:
        logger.error(f"Error getting processing statistics: {e}")
    
    return render_template('enhanced_filter_settings.html', config=config, stats=stats, theme=theme)

@app.route('/save_filter_settings', methods=['POST'])
def save_filter_settings():
    """Save enhanced filter settings"""
    try:
        config = db.load_config()
        
        # Language filter settings
        language_mode = request.form.get('language_mode', 'disabled')
        if language_mode == 'disabled':
            config["skip_non_english"] = False
        elif language_mode == 'prefix':
            config["skip_non_english"] = True
            config["language_filter"] = request.form.get('language_filter', 'EN')
        elif language_mode == 'multiple':
            config["skip_non_english"] = True
            config["included_languages"] = [lang.strip() for lang in request.form.get('included_languages', 'EN').split(',') if lang.strip()]
        
        # Content detection settings
        movie_keywords = request.form.get('movie_keywords', '')
        tv_keywords = request.form.get('tv_keywords', '')
        
        config["movie_keywords"] = [k.strip() for k in movie_keywords.split(',') if k.strip()]
        config["tv_keywords"] = [k.strip() for k in tv_keywords.split(',') if k.strip()]
        
        # Fallback settings
        if 'fallback_unidentified' in request.form:
            config["fallback_unidentified"] = request.form.get('fallback_type', 'movie')
        else:
            config["fallback_unidentified"] = 'none'
        
        # Advanced settings
        config["use_year_detection"] = 'use_year_detection' in request.form
        config["use_sxxexx_detection"] = 'use_sxxexx_detection' in request.form
        config["enhanced_logging"] = 'enhanced_logging' in request.form
        
        # Save configuration
        db.save_config(config)
        
        flash('Filter settings saved successfully')
    except Exception as e:
        logger.error(f"Error saving filter settings: {str(e)}")
        flash(f'Error saving filter settings: {str(e)}')
    
    return redirect(url_for('filter_settings'))


@app.route('/proxy')
def proxy_page():
    """Main proxy management page"""
    # Get all saved M3Us
    m3us = proxy_manager.get_all_m3us()
    
    config = db.load_config()
    theme = config.get('ui_theme', 'dark')
    
    return render_template('proxy.html', 
                           m3us=m3us, 
                           theme=theme)

@app.route('/proxy/edit/<proxy_id>')
def proxy_edit(proxy_id):
    """Automatically redirect to the channel manager"""
    return redirect(url_for('channel_manager', proxy_id=proxy_id))

@app.route('/proxy/create', methods=['GET', 'POST'])
def proxy_create():
    """Create a new proxied M3U"""
    if request.method == 'GET':
        config = db.load_config()
        theme = config.get('ui_theme', 'dark')
        return render_template('proxy_create.html', theme=theme)
    
    # Handle POST request
    m3u_url = request.form.get('url', '').strip()
    m3u_name = request.form.get('name', '').strip()
    filter_vod = 'filter_vod' in request.form
    
    if not m3u_url and 'file' not in request.files:
        flash("Please provide an M3U URL or upload a file")
        return redirect(url_for('proxy_create'))
    
    try:
        if m3u_url:
            # Download the M3U file from URL
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], f"temp_proxy_{int(time.time())}.m3u")
            download_result = download_m3u(m3u_url, file_path)
            
            if download_result['status'] == 'success':
                # Create M3U editor instance
                m3u_editor_obj = m3u_editor.M3UEditor(m3u_file=file_path, m3u_url=m3u_url)
                
                # Filter VOD content if requested
                if filter_vod:
                    original_count = len(m3u_editor_obj.channels)
                    m3u_editor_obj.filter_vod_content(keep_live_only=True)
                    filtered_count = len(m3u_editor_obj.channels)
                    logger.info(f"VOD filtering removed {original_count - filtered_count} channels")
                
                # Save it to proxy manager
                proxy_id = proxy_manager.save_m3u(m3u_editor_obj, name=m3u_name or None)
                
                # Clean up temporary file
                if os.path.exists(file_path):
                    os.remove(file_path)
                
                flash(f"Successfully created proxy for M3U: {m3u_name or m3u_url}")
                return redirect(url_for('proxy_edit', proxy_id=proxy_id))
            else:
                flash(f"Error downloading M3U: {download_result['message']}")
                return redirect(url_for('proxy_create'))
        else:
            # Handle file upload
            file = request.files['file']
            if file and file.filename.endswith('.m3u'):
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], f"temp_proxy_{int(time.time())}.m3u")
                file.save(file_path)
                
                # Create M3U editor instance
                m3u_editor_obj = m3u_editor.M3UEditor(m3u_file=file_path)
                
                # Filter VOD content if requested
                if filter_vod:
                    original_count = len(m3u_editor_obj.channels)
                    m3u_editor_obj.filter_vod_content(keep_live_only=True)
                    filtered_count = len(m3u_editor_obj.channels)
                    logger.info(f"VOD filtering removed {original_count - filtered_count} channels")
                
                # Save it to proxy manager
                proxy_id = proxy_manager.save_m3u(m3u_editor_obj, name=m3u_name or None)
                
                # Clean up temporary file
                if os.path.exists(file_path):
                    os.remove(file_path)
                
                flash(f"Successfully created proxy for M3U file: {m3u_name or file.filename}")
                return redirect(url_for('proxy_edit', proxy_id=proxy_id))
            else:
                flash("Invalid file format. Please upload an M3U file.")
                return redirect(url_for('proxy_create'))
    except Exception as e:
        logger.error(f"Error creating M3U proxy: {str(e)}")
        flash(f"Error creating M3U proxy: {str(e)}")
        return redirect(url_for('proxy_create'))

@app.route('/proxy/m3u/<proxy_id>/playlist.m3u')
def serve_proxy_m3u(proxy_id):
    """Serve the proxied M3U file"""
    m3u = proxy_manager.get_m3u(proxy_id)
    
    if not m3u:
        return "M3U not found", 404
    
    # Generate the content
    content = m3u.export_to_string()
    
    # Serve as a downloadable M3U file
    response = make_response(content)
    response.headers["Content-Type"] = "audio/x-mpegurl"
    response.headers["Content-Disposition"] = f"attachment; filename=playlist.m3u"
    
    return response

@app.route('/proxy/delete/<proxy_id>')
def proxy_delete(proxy_id):
    """Delete a proxied M3U"""
    if proxy_manager.delete_m3u(proxy_id):
        flash(f"Successfully deleted M3U proxy")
    else:
        flash(f"Error deleting M3U proxy")
    
    return redirect(url_for('proxy_page'))

@app.route('/proxy/api/optimize', methods=['POST'])
def proxy_api_optimize():
    """API endpoint to optimize channel names"""
    data = request.get_json()
    proxy_id = data.get('proxy_id')
    options = data.get('options', {})
    
    if not proxy_id:
        return jsonify({'status': 'error', 'message': 'No proxy ID provided'})
    
    m3u = proxy_manager.get_m3u(proxy_id)
    
    if not m3u:
        return jsonify({'status': 'error', 'message': 'M3U not found'})
    
    # Optimize channel names
    m3u.optimize_channel_names(options)
    
    # Save changes
    proxy_manager.save_m3u(m3u)
    
    return jsonify({
        'status': 'success', 
        'message': 'Channel names optimized',
        'channel_count': len(m3u.channels)
    })

@app.route('/proxy/api/renumber', methods=['POST'])
def proxy_api_renumber():
    """API endpoint to renumber channels"""
    data = request.get_json()
    proxy_id = data.get('proxy_id')
    start_number = int(data.get('start_number', 1))
    by_group = data.get('by_group', False)
    
    if not proxy_id:
        return jsonify({'status': 'error', 'message': 'No proxy ID provided'})
    
    m3u = proxy_manager.get_m3u(proxy_id)
    
    if not m3u:
        return jsonify({'status': 'error', 'message': 'M3U not found'})
    
    # Renumber channels
    m3u.renumber_channels(start_number=start_number, by_group=by_group)
    
    # Save changes
    proxy_manager.save_m3u(m3u)
    
    return jsonify({
        'status': 'success', 
        'message': 'Channels renumbered',
        'channel_count': len(m3u.channels)
    })

@app.route('/proxy/api/filter', methods=['POST'])
def proxy_api_filter():
    """API endpoint to filter channels"""
    data = request.get_json()
    proxy_id = data.get('proxy_id')
    group = data.get('group')
    name_contains = data.get('name_contains')
    
    if not proxy_id:
        return jsonify({'status': 'error', 'message': 'No proxy ID provided'})
    
    m3u = proxy_manager.get_m3u(proxy_id)
    
    if not m3u:
        return jsonify({'status': 'error', 'message': 'M3U not found'})
    
    # Remember original channel count
    original_count = len(m3u.channels)
    
    # Filter channels
    filtered_m3u = m3u.filter_channels(group=group, name_contains=name_contains)
    
    # Save as a new M3U
    filter_name = f"Filtered playlist"
    if group:
        filter_name += f" - Group: {group}"
    if name_contains:
        filter_name += f" - Search: {name_contains}"
    
    new_proxy_id = proxy_manager.save_m3u(filtered_m3u, name=filter_name)
    
    return jsonify({
        'status': 'success', 
        'message': 'Channels filtered',
        'original_count': original_count,
        'filtered_count': len(filtered_m3u.channels),
        'new_proxy_id': new_proxy_id
    })

@app.route('/proxy/settings')
def proxy_settings():
    """M3U proxy settings page"""
    config = db.load_config()
    theme = config.get('ui_theme', 'dark')
    
    # Get server host and port
    server_host = request.host
    
    return render_template('proxy_settings.html', 
                           server_host=server_host,
                           theme=theme)

@app.route('/proxy/api/filter_vod', methods=['POST'])
def proxy_api_filter_vod():
    """API endpoint to filter VOD content"""
    data = request.get_json()
    proxy_id = data.get('proxy_id')
    keep_live_only = data.get('keep_live_only', True)
    
    if not proxy_id:
        return jsonify({'status': 'error', 'message': 'No proxy ID provided'})
    
    m3u = proxy_manager.get_m3u(proxy_id)
    
    if not m3u:
        return jsonify({'status': 'error', 'message': 'M3U not found'})
    
    # Remember original channel count
    original_count = len(m3u.channels)
    
    # Filter VOD content
    m3u.filter_vod_content(keep_live_only=keep_live_only)
    
    # Save changes
    proxy_manager.save_m3u(m3u)
    
    filtered_count = len(m3u.channels)
    filter_type = "live channels" if keep_live_only else "VOD content"
    
    return jsonify({
        'status': 'success', 
        'message': f'Filtered playlist to keep only {filter_type}',
        'original_count': original_count,
        'filtered_count': filtered_count
    })

# Register a function to be called when the app shuts down
atexit.register(lambda: scheduler.shutdown())

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8768)
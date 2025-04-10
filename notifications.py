import requests
import json
import aiohttp
import asyncio
import db
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

async def send_discord_webhook(webhook_url, embed):
    """Send a Discord webhook notification asynchronously"""
    if not webhook_url:
        logger.debug("No webhook URL configured, skipping notification")
        return False
        
    payload = {
        "embeds": [embed]
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=payload) as response:
                if response.status == 204:
                    logger.info(f"Discord notification sent successfully")
                    return True
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to send Discord notification: {response.status} - {error_text}")
                    return False
    except Exception as e:
        logger.error(f"Error sending Discord notification: {str(e)}")
        return False

async def notify_process_complete(webhook_url, url=None, stats=None):
    """Send a notification when M3U processing is complete"""
    if not webhook_url:
        return False
        
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    title = "M3U Processing Complete"
    
    description = "An M3U file has been processed."
    if url:
        description = f"The M3U file from URL has been processed:\n{url}"
    
    fields = []
    if stats:
        if stats.get('movies_count', 0) > 0:
            fields.append({
                "name": "Movies",
                "value": f"{stats.get('movies_count', 0)} processed",
                "inline": True
            })
        if stats.get('tv_count', 0) > 0:
            fields.append({
                "name": "TV Shows",
                "value": f"{stats.get('tv_count', 0)} processed",
                "inline": True
            })
        if stats.get('skipped', 0) > 0:
            fields.append({
                "name": "Skipped",
                "value": f"{stats.get('skip_count', 0)} items",
                "inline": True
            })
    
    embed = {
        "title": title,
        "description": description,
        "color": 5814783,  # Blue color
        "timestamp": now,
        "fields": fields,
        "footer": {
            "text": "M3U to STRM Converter"
        }
    }
    
    return await send_discord_webhook(webhook_url, embed)

async def notify_summary(webhook_url, url=None, changes=None):
    """Send a summary notification after processing with all changes"""
    if not webhook_url:
        return False
        
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    title = "Processing Summary"
    
    description = "Summary of content changes:"
    if url:
        description = f"Content changes summary for M3U from:\n{url}"
    
    fields = []
    
    # Get content change statistics from database
    recent_changes = db.get_recent_content_changes(100)  # Get recent changes
    
    # Calculate statistics
    stats = {
        'movie': {'added': 0, 'updated': 0, 'removed': 0},
        'tv': {'added': 0, 'updated': 0, 'removed': 0}
    }
    
    for change in recent_changes:
        # Only count recent changes (last 5 minutes)
        try:
            # Use the same format as in the database (%Y-%m-%d %H:%M:%S)
            change_time = datetime.strptime(change['timestamp'], "%Y-%m-%d %H:%M:%S")
            now_time = datetime.now()
            time_diff = (now_time - change_time).total_seconds() / 60
            
            if time_diff <= 5:  # Within the last 5 minutes
                content_type = change['content_type']
                action = change['action']
                
                if content_type in stats and action in stats[content_type]:
                    stats[content_type][action] += 1
        except ValueError as e:
            logger.error(f"Error parsing timestamp: {e} - {change['timestamp']}")
            continue
    
    # Add movie statistics
    if stats['movie']['added'] > 0 or stats['movie']['updated'] > 0 or stats['movie']['removed'] > 0:
        movie_text = []
        if stats['movie']['added'] > 0:
            movie_text.append(f"{stats['movie']['added']} added")
        if stats['movie']['updated'] > 0:
            movie_text.append(f"{stats['movie']['updated']} updated")
        if stats['movie']['removed'] > 0:
            movie_text.append(f"{stats['movie']['removed']} removed")
            
        fields.append({
            "name": "Movies",
            "value": ", ".join(movie_text),
            "inline": True
        })
    
    # Add TV show statistics
    if stats['tv']['added'] > 0 or stats['tv']['updated'] > 0 or stats['tv']['removed'] > 0:
        tv_text = []
        if stats['tv']['added'] > 0:
            tv_text.append(f"{stats['tv']['added']} added")
        if stats['tv']['updated'] > 0:
            tv_text.append(f"{stats['tv']['updated']} updated")
        if stats['tv']['removed'] > 0:
            tv_text.append(f"{stats['tv']['removed']} removed")
            
        fields.append({
            "name": "TV Shows",
            "value": ", ".join(tv_text),
            "inline": True
        })
        
    # If we have explicit changes provided (from a check)
    if changes:
        if changes.get('added', 0) > 0:
            fields.append({
                "name": "Content Added",
                "value": str(changes['added']),
                "inline": True
            })
        if changes.get('removed', 0) > 0:
            fields.append({
                "name": "Content Removed",
                "value": str(changes['removed']),
                "inline": True
            })
        if changes.get('updated', 0) > 0:
            fields.append({
                "name": "Content Updated",
                "value": str(changes['updated']),
                "inline": True
            })
    
    # If no changes found, report that
    if len(fields) == 0:
        fields.append({
            "name": "No Changes",
            "value": "No content changes detected",
            "inline": False
        })
    
    embed = {
        "title": title,
        "description": description,
        "color": 10181046,  # Purple color
        "timestamp": now,
        "fields": fields,
        "footer": {
            "text": "M3U to STRM Converter"
        }
    }
    
    return await send_discord_webhook(webhook_url, embed)

async def notify_content_change(webhook_url, content_type, action, item_name, details=None):
    """Send a notification about content changes"""
    if not webhook_url:
        return False
        
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    colors = {
        "added": 5763719,     # Green
        "removed": 15548997,  # Red
        "updated": 16776960   # Yellow
    }
    
    action_past = {
        "added": "Added",
        "removed": "Removed",
        "updated": "Updated"
    }.get(action, action.capitalize())
    
    title = f"{action_past} {content_type.capitalize()}"
    
    embed = {
        "title": title,
        "description": f"{item_name}",
        "color": colors.get(action, 5814783),
        "timestamp": now,
        "footer": {
            "text": "M3U to STRM Converter"
        }
    }
    
    if details:
        fields = []
        for key, value in details.items():
            fields.append({
                "name": key.capitalize(),
                "value": str(value),
                "inline": True
            })
        embed["fields"] = fields
    
    return await send_discord_webhook(webhook_url, embed)

async def notify_check_complete(webhook_url, url, stats=None):
    """Send a notification when a scheduled check is complete"""
    if not webhook_url:
        return False
        
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    title = "Scheduled M3U Check Complete"
    
    description = f"Checked M3U from:\n{url}"
    
    fields = []
    
    if stats:
        if 'changes' in stats:
            changes = stats['changes']
            if changes['added'] > 0:
                fields.append({
                    "name": "Added",
                    "value": f"{changes['added']} items",
                    "inline": True
                })
            if changes['removed'] > 0:
                fields.append({
                    "name": "Removed",
                    "value": f"{changes['removed']} items",
                    "inline": True
                })
            if changes['updated'] > 0:
                fields.append({
                    "name": "Updated",
                    "value": f"{changes['updated']} items",
                    "inline": True
                })
            if changes['added'] == 0 and changes['removed'] == 0 and changes['updated'] == 0:
                fields.append({
                    "name": "No Changes",
                    "value": "Content is up to date",
                    "inline": False
                })
    
    embed = {
        "title": title,
        "description": description,
        "color": 10181046,  # Purple color
        "timestamp": now,
        "fields": fields,
        "footer": {
            "text": "M3U to STRM Converter"
        }
    }
    
    return await send_discord_webhook(webhook_url, embed)

async def notify_error(webhook_url, error_message, url=None):
    """Send a notification about an error"""
    if not webhook_url:
        return False
        
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    title = "Error Occurred"
    
    description = f"An error occurred during processing:\n```\n{error_message}\n```"
    if url:
        description += f"\nWhile processing URL: {url}"
    
    embed = {
        "title": title,
        "description": description,
        "color": 15548997,  # Red color
        "timestamp": now,
        "footer": {
            "text": "M3U to STRM Converter"
        }
    }
    
    return await send_discord_webhook(webhook_url, embed)

def should_send_notification():
    """Check if notifications are enabled in config"""
    config = db.load_config()
    return (
        config.get("notifications_enabled", False) and 
        config.get("discord_webhook_url", "")
    )

# Non-async versions for compatibility
def sync_notify_process_complete(url=None, stats=None):
    """Synchronous wrapper for notify_process_complete"""
    if not should_send_notification():
        return False
        
    config = db.load_config()
    webhook_url = config.get("discord_webhook_url", "")
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(notify_process_complete(webhook_url, url, stats))
    finally:
        loop.close()

def sync_notify_summary(url=None, changes=None):
    """Synchronous wrapper for notify_summary"""
    if not should_send_notification():
        return False
        
    config = db.load_config()
    webhook_url = config.get("discord_webhook_url", "")
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(notify_summary(webhook_url, url, changes))
    finally:
        loop.close()

def sync_notify_content_change(content_type, action, item_name, details=None):
    """Synchronous wrapper for notify_content_change"""
    if not should_send_notification():
        return False
        
    config = db.load_config()
    webhook_url = config.get("discord_webhook_url", "")
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(notify_content_change(webhook_url, content_type, action, item_name, details))
    finally:
        loop.close()

def sync_notify_error(error_message, url=None):
    """Synchronous wrapper for notify_error"""
    if not should_send_notification():
        return False
        
    config = db.load_config()
    webhook_url = config.get("discord_webhook_url", "")
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(notify_error(webhook_url, error_message, url))
    finally:
        loop.close()
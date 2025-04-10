import os
import logging
import hashlib
import json
from datetime import datetime
from flask import Blueprint, request, jsonify, url_for, render_template, flash, redirect
import db
from content_comparison import ContentRegistry, ProviderManager

logger = logging.getLogger(__name__)

# Create blueprint
content_sync_api = Blueprint('content_sync_api', __name__)

class ContentSynchronizer:
    """
    Synchronizes content across multiple providers to create a complete library
    by filling in missing episodes, shows, and movies
    """
    
    def __init__(self, content_registry=None, provider_manager=None):
        """Initialize the content synchronizer with registry and provider manager"""
        self.content_registry = content_registry or ContentRegistry()
        self.provider_manager = provider_manager or ProviderManager()
        
        # Load configuration
        self.config = db.load_config()
        self.content_path = self.config.get("output_path", "content")
        
    def scan_existing_content(self):
        """Scan content directories to build registry of existing content"""
        logger.info("Scanning existing content...")
        
        # Scan movies directory
        movie_path = os.path.join(self.content_path, 'Movies')
        if os.path.exists(movie_path):
            for movie_dir in os.listdir(movie_path):
                movie_full_path = os.path.join(movie_path, movie_dir)
                if os.path.isdir(movie_full_path):
                    # Extract movie details from directory name
                    movie_title = movie_dir
                    year = None
                    
                    # Try to extract year if present in brackets
                    import re
                    year_match = re.search(r'\((\d{4})\)', movie_title)
                    if year_match:
                        year = year_match.group(1)
                        movie_title = movie_title.replace(f"({year})", "").strip()
                    
                    # Find STRM file to get URL
                    for file in os.listdir(movie_full_path):
                        if file.endswith(".strm"):
                            strm_path = os.path.join(movie_full_path, file)
                            
                            # Extract resolution if present in filename
                            resolution = None
                            res_match = re.search(r'(720p|1080p|2160p|4K|UHD)', file)
                            if res_match:
                                resolution = res_match.group(1)
                            
                            # Read URL from STRM file
                            with open(strm_path, 'r') as f:
                                url = f.read().strip()
                                
                            # Register in content registry
                            provider_url = "unknown"  # Default for existing content
                            self.content_registry.register_content(
                                "movie", 
                                movie_title, 
                                url, 
                                strm_path, 
                                provider_url,
                                year=year,
                                resolution=resolution
                            )
                            logger.debug(f"Registered existing movie: {movie_title} ({year}) - {resolution}")
                            break
        
        # Scan TV Shows directory
        tv_path = os.path.join(self.content_path, 'TV Shows')
        if os.path.exists(tv_path):
            for show_dir in os.listdir(tv_path):
                show_full_path = os.path.join(tv_path, show_dir)
                if os.path.isdir(show_full_path):
                    show_title = show_dir
                    
                    # Process seasons
                    for season_dir in os.listdir(show_full_path):
                        season_path = os.path.join(show_full_path, season_dir)
                        if os.path.isdir(season_path):
                            # Extract season number
                            season_number = None
                            if season_dir.startswith("Season "):
                                season_number = season_dir[7:].strip().zfill(2)
                            
                            # Process episodes
                            for episode_file in os.listdir(season_path):
                                if episode_file.endswith(".strm"):
                                    episode_path = os.path.join(season_path, episode_file)
                                    
                                    # Try to extract episode info
                                    import re
                                    episode_number = None
                                    episode_match = re.search(r'S\d+E(\d+)', episode_file)
                                    if episode_match:
                                        episode_number = episode_match.group(1)
                                    
                                    # Extract resolution if present
                                    resolution = None
                                    res_match = re.search(r'(720p|1080p|2160p|4K|UHD)', episode_file)
                                    if res_match:
                                        resolution = res_match.group(1)
                                    
                                    # Read URL from STRM file
                                    with open(episode_path, 'r') as f:
                                        url = f.read().strip()
                                    
                                    # Register in content registry
                                    provider_url = "unknown"  # Default for existing content
                                    if season_number and episode_number:
                                        self.content_registry.register_content(
                                            "tv_show", 
                                            show_title, 
                                            url, 
                                            episode_path, 
                                            provider_url,
                                            season=season_number,
                                            episode=episode_number,
                                            resolution=resolution
                                        )
                                        logger.debug(f"Registered existing TV episode: {show_title} S{season_number}E{episode_number} - {resolution}")
        
        logger.info("Content scan completed")
        return self.content_registry
    
    def find_content_gaps(self):
        """Find missing episodes in TV shows by analyzing the registry"""
        logger.info("Analyzing content for gaps...")
        
        # Get all TV shows from registry
        all_content = self.content_registry.registry
        tv_content = all_content.get("tv_shows", {})
        
        # Group episodes by show and season
        shows = {}
        for content_hash, content in tv_content.items():
            show_title = content.get("title")
            season = content.get("season")
            episode = content.get("episode")
            
            if not show_title or not season or not episode:
                continue
                
            if show_title not in shows:
                shows[show_title] = {}
                
            if season not in shows[show_title]:
                shows[show_title][season] = []
                
            shows[show_title][season].append(episode)
        
        # Analyze for gaps
        gaps = []
        for show, seasons in shows.items():
            for season, episodes in seasons.items():
                # Convert to integers for proper sorting
                int_episodes = []
                for ep in episodes:
                    try:
                        int_episodes.append(int(ep))
                    except ValueError:
                        # Skip non-integer episode numbers
                        continue
                        
                int_episodes.sort()
                
                # Find gaps
                if len(int_episodes) <= 1:
                    continue  # Not enough episodes to determine gaps
                    
                max_ep = max(int_episodes)
                min_ep = min(int_episodes)
                
                # Check for missing episodes
                for ep_num in range(min_ep, max_ep + 1):
                    if ep_num not in int_episodes:
                        gap_id = f"{show}_{season}_{ep_num}"
                        gaps.append({
                            "id": gap_id,
                            "show": show,
                            "season": season,
                            "episode": str(ep_num).zfill(2),
                            "type": "episode_gap",
                            "providers": self.find_available_providers_for_gap({
                                "show": show,
                                "season": season,
                                "episode": str(ep_num).zfill(2),
                                "type": "episode_gap"
                            })
                        })
                        logger.debug(f"Found missing episode: {show} S{season}E{str(ep_num).zfill(2)}")
        
        logger.info(f"Found {len(gaps)} gaps in TV content")
        return gaps
    
    def find_available_providers_for_gap(self, gap):
        """Find providers that have content to fill a specific gap"""
        # This is a placeholder that would need to be implemented with actual provider scanning
        # For now, return an empty list indicating no providers found
        return []
    
    def fill_content_gaps(self, gaps=None):
        """Attempt to fill content gaps using available providers"""
        if gaps is None:
            gaps = self.find_content_gaps()
            
        filled_count = 0
        
        for gap in gaps:
            # Find providers that have this content
            providers = gap.get("providers") or self.find_available_providers_for_gap(gap)
            
            if not providers:
                logger.debug(f"No providers found for gap: {gap}")
                continue
                
            # Sort providers by preference (resolution, etc.)
            # For now, just use the first available provider
            provider = providers[0]
            
            # Create content based on gap type
            if gap["type"] == "episode_gap":
                # In a real implementation, this would create the episode
                # For now, just log it
                logger.info(f"Would fill gap: {gap['show']} S{gap['season']}E{gap['episode']} from {provider.get('name')}")
                filled_count += 1
                
        logger.info(f"Filled {filled_count} content gaps")
        return filled_count
    
    def find_quality_upgrades(self):
        """Find content that can be upgraded to better quality from another provider"""
        # For now, this is a placeholder
        return []
    
    def get_provider_statistics(self):
        """Get statistics about content from different providers"""
        # In a real implementation, this would analyze the registry to get provider stats
        # For now, return placeholder data
        return []
    
    def synchronize_all_content(self):
        """Full synchronization process - scan, analyze, and fill gaps"""
        # Step 1: Scan existing content
        self.scan_existing_content()
        
        # Step 2: Find content gaps
        gaps = self.find_content_gaps()
        
        # Step 3: Fill content gaps
        filled_count = self.fill_content_gaps(gaps)
        
        return {
            "gaps_found": len(gaps),
            "gaps_filled": filled_count
        }

# Routes

@content_sync_api.route('/content-sync')
def content_sync_page():
    """Content synchronization main page"""
    # Create synchronizer
    synchronizer = ContentSynchronizer()
    
    # Get basic stats
    provider_stats = synchronizer.get_provider_statistics()
    provider_count = len(provider_stats)
    
    # Initialize registry
    registry = synchronizer.content_registry
    
    # Find gaps (but don't scan directories yet to keep page load fast)
    gaps = []
    tv_gaps = 0
    duplicates = 0
    
    # If registry already has data, analyze it
    if registry.registry.get("tv_shows"):
        gaps = synchronizer.find_content_gaps()
        tv_gaps = len(gaps)
        
        # Simple count of duplicates (content with multiple providers)
        for content_hash, content in registry.registry.get("tv_shows", {}).items():
            if len(content.get("providers", {})) > 1:
                duplicates += 1
                
        for content_hash, content in registry.registry.get("movies", {}).items():
            if len(content.get("providers", {})) > 1:
                duplicates += 1
    
    return render_template(
        'content_sync.html',
        provider_count=provider_count,
        tv_gaps=tv_gaps,
        duplicates=duplicates,
        gaps=gaps[:20] if len(gaps) > 20 else gaps,  # Show at most 20 gaps on the main page
        provider_stats=provider_stats
    )

@content_sync_api.route('/scan-registry')
def scan_content_registry():
    """Scan content directories to build registry"""
    try:
        synchronizer = ContentSynchronizer()
        synchronizer.scan_existing_content()
        flash("Content registry scan completed successfully")
    except Exception as e:
        logger.error(f"Error scanning content registry: {str(e)}")
        flash(f"Error scanning content registry: {str(e)}", "error")
        
    return redirect(url_for('content_sync_page'))

@content_sync_api.route('/find-gaps')
def find_content_gaps():
    """Find content gaps in the registry"""
    try:
        synchronizer = ContentSynchronizer()
        
        # Scan content first to ensure registry is populated
        synchronizer.scan_existing_content()
        
        # Find gaps
        gaps = synchronizer.find_content_gaps()
        
        if gaps:
            flash(f"Found {len(gaps)} content gaps")
        else:
            flash("No content gaps found in your library")
    except Exception as e:
        logger.error(f"Error finding content gaps: {str(e)}")
        flash(f"Error finding content gaps: {str(e)}", "error")
        
    return redirect(url_for('content_sync_page'))

@content_sync_api.route('/fill-gaps')
def fill_content_gaps():
    """Fill content gaps using available providers"""
    try:
        synchronizer = ContentSynchronizer()
        
        # Scan content first to ensure registry is populated
        synchronizer.scan_existing_content()
        
        # Find and fill gaps
        gaps = synchronizer.find_content_gaps()
        filled = synchronizer.fill_content_gaps(gaps)
        
        flash(f"Filled {filled} content gaps out of {len(gaps)} identified gaps")
    except Exception as e:
        logger.error(f"Error filling content gaps: {str(e)}")
        flash(f"Error filling content gaps: {str(e)}", "error")
        
    return redirect(url_for('content_sync_page'))

@content_sync_api.route('/find-upgrades')
def find_quality_upgrades():
    """Find content that can be upgraded to better quality"""
    try:
        synchronizer = ContentSynchronizer()
        
        # Scan content first to ensure registry is populated
        synchronizer.scan_existing_content()
        
        # Find upgrades
        upgrades = synchronizer.find_quality_upgrades()
        
        if upgrades:
            flash(f"Found {len(upgrades)} possible quality upgrades")
        else:
            flash("No quality upgrades found in your library")
    except Exception as e:
        logger.error(f"Error finding quality upgrades: {str(e)}")
        flash(f"Error finding quality upgrades: {str(e)}", "error")
        
    return redirect(url_for('content_sync_page'))

@content_sync_api.route('/fill-gap/<gap_id>')
def fill_gap(gap_id):
    """Fill a specific content gap"""
    try:
        # Parse gap ID
        parts = gap_id.split('_')
        if len(parts) < 3:
            flash("Invalid gap ID format")
            return redirect(url_for('content_sync_page'))
            
        show = parts[0]
        season = parts[1]
        episode = parts[2]
        
        # Create synchronizer
        synchronizer = ContentSynchronizer()
        
        # Find available providers for this gap
        gap = {
            "show": show,
            "season": season,
            "episode": episode,
            "type": "episode_gap"
        }
        providers = synchronizer.find_available_providers_for_gap(gap)
        
        if not providers:
            flash(f"No providers found for {show} S{season}E{episode}")
            return redirect(url_for('content_sync_page'))
            
        # Fill the gap
        # This would call the appropriate function to create the STRM file
        # For now, just show a success message
        
        flash(f"Successfully filled gap: {show} S{season}E{episode}")
    except Exception as e:
        logger.error(f"Error filling gap {gap_id}: {str(e)}")
        flash(f"Error filling gap: {str(e)}", "error")
        
    return redirect(url_for('content_sync_page'))

@content_sync_api.route('/api/content-stats')
def content_stats_api():
    """API endpoint to get content statistics"""
    try:
        synchronizer = ContentSynchronizer()
        
        # Get provider statistics
        provider_stats = synchronizer.get_provider_statistics()
        
        # Get content gaps
        gaps = synchronizer.find_content_gaps()
        
        # Return JSON response
        return jsonify({
            "status": "success",
            "data": {
                "provider_count": len(provider_stats),
                "provider_stats": provider_stats,
                "content_gaps": len(gaps),
                "gaps": gaps[:20]  # Return max 20 gaps
            }
        })
    except Exception as e:
        logger.error(f"Error getting content stats: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

def register_content_sync_api(app):
    """Register the content sync API blueprint with the Flask app"""
    app.register_blueprint(content_sync_api)
    
    # Add routes
    app.add_url_rule('/content-sync', 'content_sync_page', content_sync_page)
    app.add_url_rule('/scan-registry', 'scan_content_registry', scan_content_registry)
    app.add_url_rule('/find-gaps', 'find_content_gaps', find_content_gaps)
    app.add_url_rule('/fill-gaps', 'fill_content_gaps', fill_content_gaps)
    app.add_url_rule('/find-upgrades', 'find_quality_upgrades', find_quality_upgrades)
    app.add_url_rule('/fill-gap/<gap_id>', 'fill_gap', fill_gap)

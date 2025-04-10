import asyncio
import concurrent.futures
from collections import defaultdict
import os
import logging
import db

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def process_m3u_optimized(filename, output_path=None, url=None, batch_size=100):
    """
    Process an M3U file with improved performance through:
    1. Parallel processing of entries
    2. Batched file operations
    3. Reduced registry updates
    """
    # Phase 1: Read and parse the entire M3U file
    logger.info(f"Reading and parsing M3U file: {filename}")
    all_entries = await parse_m3u_file(filename)
    logger.info(f"Found {len(all_entries)} entries in M3U file")
    
    # Phase 2: Pre-categorize all entries (movies vs TV shows)
    categorized_entries = categorize_entries(all_entries)
    logger.info(f"Categorized {len(categorized_entries['movies'])} movies and {len(categorized_entries['tv'])} TV shows")
    
    # Phase 3: Process entries in parallel batches
    results = {
        'movies_count': len(categorized_entries['movies']),
        'tv_count': len(categorized_entries['tv']),
        'skip_count': len(categorized_entries['skipped']),
        'error_count': 0
    }
    
    # Process movies in batches
    logger.info("Processing movies...")
    await process_in_batches(categorized_entries['movies'], 'movie', batch_size, url, output_path)
    
    # Process TV shows in batches
    logger.info("Processing TV shows...")
    await process_in_batches(categorized_entries['tv'], 'tv', batch_size, url, output_path)
    
    logger.info("M3U processing completed successfully")
    return results

async def parse_m3u_file(filename):
    """Parse M3U file in one pass and return all entries"""
    entries = []
    
    # Read the file using a single file operation
    with open(filename, 'r', encoding='utf-8', errors='ignore') as f:
        lines = [line.rstrip('\n') for line in f]
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        # Skip empty lines and headers
        if not line or (line.startswith('#') and not line.startswith('#EXTINF:')):
            i += 1
            continue
        
        # Process EXTINF line
        if line.startswith('#EXTINF:'):
            if i + 1 < len(lines):
                streaminfo = line
                streamURL = lines[i + 1].strip()
                
                # Add entry if URL seems valid
                if '://' in streamURL:
                    entries.append({
                        'streaminfo': streaminfo,
                        'streamURL': streamURL
                    })
                i += 2
            else:
                i += 1
        else:
            i += 1
    
    return entries

def categorize_entries(entries):
    """
    Pre-categorize all entries into movies, TV shows, or skipped
    This avoids doing expensive regex operations multiple times
    """
    from streamClasses import rawStreamList
    
    # Create a temporary instance just to use its methods
    temp_instance = rawStreamList.__new__(rawStreamList)
    temp_instance.log = logging.getLogger("temp")
    
    result = {
        'movies': [],
        'tv': [],
        'skipped': []
    }
    
    # Get language filter from config
    import db
    config = db.load_config()
    language_filter = config.get("language_filter", "EN")
    skip_non_english = config.get("skip_non_english", True)
    
    for entry in entries:
        streaminfo = entry['streaminfo']
        
        # Check language filter first (simple string operation, much faster than regex)
        if skip_non_english and language_filter:
            import re
            tvg_name_match = re.search(r'tvg-name="([^"]*)"', streaminfo)
            if tvg_name_match:
                tvg_name = tvg_name_match.group(1)
                if not tvg_name.startswith(f'{language_filter} - '):
                    result['skipped'].append(entry)
                    continue
        
        # Determine stream type using existing method but store result
        try:
            stream_type = temp_instance.parseStreamType(streaminfo)
            if stream_type == 'vodTV':
                result['tv'].append(entry)
            elif stream_type == 'vodMovie':
                result['movies'].append(entry)
            else:
                result['skipped'].append(entry)
        except Exception:
            # If any error in parsing, consider it skipped
            result['skipped'].append(entry)
    
    return result

async def process_in_batches(entries, entry_type, batch_size, provider_url, output_path):
    """Process entries in parallel batches to improve performance"""

    config = db.load_config()
    worker_count = config.get("worker_count", 10)
    
    batches = [entries[i:i+batch_size] for i in range(0, len(entries), batch_size)]
    
    for batch_index, batch in enumerate(batches):
        logger.info(f"Processing {entry_type} batch {batch_index+1}/{len(batches)} ({len(batch)} items)")
        
        # Process this batch in parallel
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
            loop = asyncio.get_event_loop()
            futures = []
            
            for entry in batch:
                if entry_type == 'movie':
                    future = loop.run_in_executor(
                        executor,
                        process_movie_entry,
                        entry,
                        provider_url,
                        output_path
                    )
                else:
                    future = loop.run_in_executor(
                        executor,
                        process_tv_entry,
                        entry,
                        provider_url,
                        output_path
                    )
                futures.append(future)
            
            # Wait for all futures to complete
            await asyncio.gather(*futures)
        
        # Log progress
        progress = (batch_index + 1) / len(batches) * 100
        logger.info(f"Progress: {progress:.1f}% complete")

def process_movie_entry(entry, provider_url, output_path):
    """Process a single movie entry"""
    from streamClasses import Movie
    import tools
    import re
    
    streaminfo = entry['streaminfo']
    streamURL = entry['streamURL']
    
    try:
        # Extract movie metadata
        tvg_name_match = re.search(r'tvg-name="([^"]*)"', streaminfo)
        if not tvg_name_match:
            return
            
        title = tvg_name_match.group(1)
        
        # Parse other metadata
        resolution = tools.resolutionMatch(streaminfo)
        if resolution:
            resolution = tools.parseResolution(resolution)
            
        year = tools.yearMatch(streaminfo)
        if year:
            title = tools.stripYear(title)
            year = year.group().strip()
        
        # Create and process movie
        movie = Movie(title, streamURL, year=year, resolution=resolution)
        movie.makeStream(provider_url)
        
        return True
    except Exception as e:
        logger.error(f"Error processing movie entry: {e}")
        return False

def process_tv_entry(entry, provider_url, output_path):
    """Process a single TV entry"""
    from streamClasses import TVEpisode
    import tools
    import re
    
    streaminfo = entry['streaminfo']
    streamURL = entry['streamURL']
    
    try:
        # Extract TV show metadata
        tvg_name_match = re.search(r'tvg-name="([^"]*)"', streaminfo)
        if not tvg_name_match:
            return
            
        title = tvg_name_match.group(1)
        
        # Get resolution if available
        resolution = tools.resolutionMatch(streaminfo)
        if resolution:
            resolution = tools.parseResolution(resolution)
        
        # Parse episode information
        episodeinfo = tools.parseEpisode(title)
        if not episodeinfo:
            # Try fallback method
            return create_fallback_tv_show(streaminfo, streamURL, provider_url)
            
        # Create and process episode based on extracted info
        if len(episodeinfo) == 3:  # Airdate format
            showtitle = episodeinfo[0]
            airdate = episodeinfo[2]
            episodename = episodeinfo[1] if episodeinfo[1] is not None else ""
            
            episode = TVEpisode(
                showtitle, streamURL, 
                resolution=resolution, 
                episodename=episodename, 
                airdate=airdate
            )
        else:  # Season/episode format
            showtitle = episodeinfo[0]
            episodename = episodeinfo[1] if episodeinfo[1] is not None else ""
            seasonnumber = episodeinfo[2]
            episodenumber = episodeinfo[3]
            
            episode = TVEpisode(
                showtitle, streamURL, 
                seasonnumber=seasonnumber, 
                episodenumber=episodenumber, 
                resolution=resolution, 
                episodename=episodename
            )
            
        if episode:
            episode.makeStream(provider_url)
            return True
            
    except Exception as e:
        logger.error(f"Error processing TV entry: {e}")
        return False

def create_fallback_tv_show(streaminfo, streamURL, provider_url):
    """Create a TV show entry using fallback methods"""
    from streamClasses import TVEpisode
    import tools
    import re
    
    try:
        # Extract the title
        tvg_name_match = re.search(r'tvg-name="([^"]*)"', streaminfo)
        if not tvg_name_match:
            return False
            
        original_title = tvg_name_match.group(1)
        
        # Remove language prefix if exists
        import db
        config = db.load_config()
        language_filter = config.get("language_filter", "EN")
        if language_filter and original_title.startswith(f'{language_filter} - '):
            title = original_title[len(language_filter) + 3:]
        else:
            title = original_title
        
        # Remove year pattern if exists
        title = re.sub(r'\s*\(\d{4}\)$', '', title)
        
        # Try to split into show and episode if there's a hyphen
        if " - " in title:
            parts = title.split(" - ", 1)
            show_title = parts[0].strip()
            episode_title = parts[1].strip() if len(parts) > 1 else "Episode 1"
        else:
            # If no hyphen, just use the title as show name and "Episode 1" as episode name
            show_title = title.strip()
            episode_title = "Episode 1"
        
        # Get resolution if available
        resolution = tools.resolutionMatch(streaminfo)
        if resolution:
            resolution = tools.parseResolution(resolution)
        
        # Create episode with default season 1, episode 1
        episode = TVEpisode(
            show_title, 
            streamURL,
            seasonnumber="01",
            episodenumber="01",
            resolution=resolution,
            episodename=episode_title
        )
        
        if episode:
            episode.makeStream(provider_url)
            return True
            
        return False
    except Exception as e:
        logger.error(f"Error in fallback TV processing: {e}")
        return False
import asyncio
import logging
import os
import re
import tools
import db
import notifications
import json
import time
import uuid
import threading
import signal
import concurrent.futures
from datetime import datetime
from processing_monitor import processing_monitor
from sse_notifications import send_notification, send_status_update
from logger import LogLevel


# Initialize logger
logger = logging.getLogger(__name__)

# Timeout for processing operations (in seconds)
PROCESSING_TIMEOUT = 60

class TimeoutError(Exception):
    """Custom exception for timeout errors"""
    pass

class Movie(object):
    def __init__(self, title, url, year=None, resolution=None, language=None):
        self.title = title.strip() if title else "Unknown Movie"
        self.url = url
        self.year = year
        self.resolution = resolution
        self.language = language

    def getFilename(self):
        # Use configuration for output path
        config = db.load_config()
        content_path = config.get("output_path", "content")
        
        filestring = [self.title.replace(':','-').replace('*','_').replace('/','_').replace('?','')]
        if self.resolution:
            filestring.append(self.resolution)
        # Changed path to use content/Movies structure
        movie_path = f'{content_path}/Movies/' + self.title.replace(':','-').replace('*','_').replace('/','_').replace('?','')
        return movie_path + "/" + ' - '.join(filestring) + ".strm"
    
    def makeStream(self, provider_url=None):
        """Create or update STRM file for a movie with content registry and provider tracking"""
        filename = self.getFilename()
        logger.debug(f"Creating movie stream for: {filename}")
        
        # Get content registry
        from content_comparison import ContentRegistry
        registry = ContentRegistry()
        
        # Create directories if they don't exist
        directories = filename.split('/')
        directories = directories[:-1]
        
        # Create content base directory
        config = db.load_config()
        content_path = config.get("output_path", "content")
        base_dir = content_path
        if not os.path.exists(base_dir):
            os.makedirs(base_dir)
        
        # Create Movies subfolder
        movies_dir = os.path.join(base_dir, 'Movies')
        if not os.path.exists(movies_dir):
            os.makedirs(movies_dir)
        
        # Create individual movie folder
        movie_dir = '/'.join(directories)
        if not os.path.exists(movie_dir):
            os.makedirs(movie_dir)
        
        # Check if this content has already been processed
        if registry.content_exists("movie", self.title, year=self.year):
            # Check if URL has changed or quality improved
            current_resolution = registry.get_content_resolution("movie", self.title, year=self.year)
            is_better = registry._is_better_resolution(self.resolution, current_resolution)
            
            if is_better:
                # Update with better quality version
                registry.update_content("movie", self.title, self.url, filename, provider_url, 
                                       year=self.year, resolution=self.resolution)
                tools.makeStrm(filename, self.url)
                provider_name = registry.get_provider_name(provider_url)
                db.log_content_change("movie", "updated", self.title, provider_url, 
                                     {"resolution": self.resolution, "year": self.year, "provider": provider_name})
                logger.info(f"Updated movie with better quality: {self.title} ({self.resolution})")
            else:
                # Just register the provider as a source if not already registered
                registry.add_provider_to_content("movie", self.title, self.url, provider_url, 
                                                year=self.year, resolution=self.resolution)
                logger.debug(f"Movie already exists with same or better quality: {self.title}")
            return
        
        # Create STRM file for new content
        is_new = not os.path.exists(filename)
        tools.makeStrm(filename, self.url)
        
        # Register this content in the registry
        if provider_url:
            registry.register_content("movie", self.title, self.url, filename, provider_url, 
                                     year=self.year, resolution=self.resolution)
        
        # Log the content change
        details = {
            "resolution": self.resolution,
            "year": self.year
        }
        
        if provider_url:
            # Add provider information to details
            provider_name = registry.get_provider_name(provider_url)
            details["provider"] = provider_name
        
        if is_new:
            db.log_content_change("movie", "added", self.title, provider_url, details)
        else:
            db.log_content_change("movie", "updated", self.title, provider_url, details)

class TVEpisode(object):
    def __init__(self, showtitle, url, seasonnumber=None, episodenumber=None, resolution=None, language=None, episodename=None, airdate=None):
        logger.debug(f"Creating TV Episode with title: {showtitle}")
        self.showtitle = showtitle if showtitle else "Unknown Show"
        self.episodenumber = episodenumber
        self.seasonnumber = seasonnumber
        self.url = url
        self.resolution = resolution
        self.language = language
        self.episodename = episodename if episodename else ""  # Ensure episodename is never None
        self.airdate = airdate
        if self.seasonnumber and self.episodenumber:
            self.sXXeXX = f"S{str(self.seasonnumber).zfill(2)}E{str(self.episodenumber).zfill(2)}"
            logger.debug(f"Created episode format: {self.sXXeXX}")

    def getFilename(self):
        # Use configuration for output path
        config = db.load_config()
        content_path = config.get("output_path", "content")
        
        logger.debug(f"Generating filename for: {self.showtitle}")
        filestring = [self.showtitle.replace(':','-').replace('*','_').replace('/','_').replace('?','')]
        if self.airdate:
            filestring.append(self.airdate.strip())
        elif hasattr(self, 'sXXeXX'):
            filestring.append(self.sXXeXX.strip())
        if self.episodename:
            filestring.append(self.episodename.strip())
        if self.language:
            filestring.append(self.language.strip())
        if self.resolution:
            filestring.append(self.resolution.strip())
            
        base_title = self.showtitle.strip().replace(':','-').replace('/','_').replace('*','_').replace('?','')
        if self.seasonnumber:
            season_folder = f"Season {str(self.seasonnumber).zfill(2)}"
            # Changed path to use content/TV Shows structure
            path = f'{content_path}/TV Shows/{base_title}/{season_folder}/' + ' - '.join(filestring).replace(':','-').replace('*','_') + ".strm"
        else:
            path = f'{content_path}/TV Shows/{base_title}/' + ' - '.join(filestring).replace(':','-').replace('*','_') + ".strm"
        logger.debug(f"Generated filename: {path}")
        return path
    
    def makeStream(self, provider_url=None):
        """Create or update STRM file for a TV episode with content registry integration"""
        filename = self.getFilename()
        logger.debug(f"Creating TV stream for: {filename}")
        
        # Get content registry
        from content_comparison import ContentRegistry
        registry = ContentRegistry()
        
        directories = filename.split('/')
        directories = directories[:-1]  # Remove the file name
    
        # Create content base directory
        config = db.load_config()
        content_path = config.get("output_path", "content")
        base_dir = content_path
        if not os.path.exists(base_dir):
            os.makedirs(base_dir)
        
        # Create TV Shows subfolder
        tvshows_dir = os.path.join(base_dir, 'TV Shows')
        if not os.path.exists(tvshows_dir):
            os.makedirs(tvshows_dir)
        
        # Create show directory
        showdir = '/'.join(directories[:-1] if len(directories) > 3 else directories)
        if not os.path.exists(showdir):
            os.makedirs(showdir)
        
        # Create season directory if it exists
        if len(directories) > 3:  # We have a season directory
            seasondir = '/'.join(directories)
            if not os.path.exists(seasondir):
                os.makedirs(seasondir)
    
        # Check if this content already exists
        if registry.content_exists("tv_show", self.showtitle, season=self.seasonnumber, episode=self.episodenumber):
            # Check if URL has changed or quality improved
            current_resolution = registry.get_content_resolution("tv_show", self.showtitle, 
                                                              season=self.seasonnumber, episode=self.episodenumber)
            is_better = registry._is_better_resolution(self.resolution, current_resolution)
            
            if is_better:
                # Update with better quality version
                registry.update_content("tv_show", self.showtitle, self.url, filename, provider_url,
                                      season=self.seasonnumber, episode=self.episodenumber, resolution=self.resolution)
                tools.makeStrm(filename, self.url)
                provider_name = registry.get_provider_name(provider_url)
                
                # Log the content change
                episode_info = self._get_episode_info()
                details = {
                    "show": self.showtitle,
                    "episode": episode_info,
                    "resolution": self.resolution,
                    "provider": provider_name
                }
                db.log_content_change("tv", "updated", f"{self.showtitle} - {episode_info}", provider_url, details)
                logger.info(f"Updated TV episode with better quality: {self.showtitle} - {episode_info} ({self.resolution})")
            else:
                # Just register the provider as a source
                registry.add_provider_to_content("tv_show", self.showtitle, self.url, provider_url,
                                               season=self.seasonnumber, episode=self.episodenumber, resolution=self.resolution)
                logger.debug(f"TV episode already exists with same or better quality: {self.showtitle} - {self._get_episode_info()}")
            return
    
        # Create STRM file for new content
        is_new = not os.path.exists(filename)
        tools.makeStrm(filename, self.url)
        
        # Register this content in the registry
        if provider_url:
            registry.register_content("tv_show", self.showtitle, self.url, filename, provider_url,
                                    season=self.seasonnumber, episode=self.episodenumber, resolution=self.resolution)
    
        # Log the content change
        episode_info = self._get_episode_info()
        details = {
            "show": self.showtitle,
            "episode": episode_info,
            "resolution": self.resolution
        }
        
        if provider_url:
            # Add provider information to details
            provider_name = registry.get_provider_name(provider_url)
            details["provider"] = provider_name
        
        if is_new:
            db.log_content_change("tv", "added", f"{self.showtitle} - {episode_info}", provider_url, details)
        else:
            db.log_content_change("tv", "updated", f"{self.showtitle} - {episode_info}", provider_url, details)
            
    def _get_episode_info(self):
        """Helper method to get formatted episode info for logging"""
        if hasattr(self, 'sXXeXX') and self.episodename:
            return f"{self.sXXeXX} - {self.episodename}"
        elif self.episodename:
            return self.episodename
        elif self.seasonnumber and self.episodenumber:
            return f"S{self.seasonnumber}E{self.episodenumber}"
        elif self.airdate:
            return self.airdate
        else:
            return "Unknown Episode"

def run_with_timeout(func, *args, timeout=PROCESSING_TIMEOUT, **kwargs):
    """Run a function with a timeout using ThreadPoolExecutor"""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(func, *args, **kwargs)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            # The task didn't complete in time, attempt to interrupt it
            future.cancel()
            logger.error(f"Operation timed out after {timeout} seconds: {func.__name__}")
            raise TimeoutError(f"Operation timed out after {timeout} seconds: {func.__name__}")

# Define a stream container to hold parsed data
class StreamEntry:
    def __init__(self, streaminfo, streamURL, stream_type=None):
        self.streaminfo = streaminfo
        self.streamURL = streamURL
        self.stream_type = stream_type  # Will be determined during parsing
        self.tvg_name = None
        
        # Try to extract the TVG name
        tvg_name_match = re.search(r'tvg-name="([^"]*)"', streaminfo)
        if tvg_name_match:
            self.tvg_name = tvg_name_match.group(1)

class rawStreamList(object):
    def __init__(self, filename, job_id=None, m3u_url=None):
        # Get log level from config
        config = db.load_config()
        import logger as logger_module
        log_level = getattr(logger_module.LogLevel, config.get("log_level", "NORMAL"))
        self.log = logger_module.Logger(__file__, log_level=log_level)
        
        self.streams = []  # Will hold StreamEntry objects
        self.filename = filename
        self.movies_count = 0
        self.tv_count = 0
        self.skip_count = 0
        self.error_count = 0
        self.job_id = job_id or str(uuid.uuid4())
        self.m3u_url = m3u_url  # Store the source URL for provider tracking
        
        # Initialize processing monitor
        processing_monitor.start_job(
            self.job_id, 
            f"Processing M3U file: {os.path.basename(filename)}"
        )
        
        # Track content for change detection
        self.content_before = self._scan_content_dirs()
        
        try:
            # PHASE 1: Read and parse the M3U file into memory
            send_notification(
                "Processing Started", 
                f"Phase 1: Reading M3U file {os.path.basename(filename)}", 
                "info"
            )
            
            self.readLines()
            self.parseM3UToMemory()
            
            # PHASE 2: Process the parsed entries to create STRM files
            send_notification(
                "M3U File Parsed", 
                f"Phase 2: Creating STRM files from {len(self.streams)} entries", 
                "info"
            )
            
            self.processStreamEntries()
            
            # Check for content changes
            self.content_after = self._scan_content_dirs()
            changes = self._detect_content_changes()
            
            # Complete job with status
            processing_monitor.complete_job(self.job_id, status='completed')
            
            # Send browser notification
            self._send_completion_notification()
            
        except Exception as e:
            logger.error(f"Error processing M3U file: {str(e)}")
            self.error_count += 1
            
            # Mark job as error
            processing_monitor.complete_job(
                self.job_id, 
                status='error', 
                error=str(e)
            )
            
            # Send browser notification for error
            send_notification(
                "Error Processing M3U", 
                f"Failed to process {os.path.basename(filename)}: {str(e)}", 
                "error"
            )
            
            # Re-raise the exception to be handled by the caller
            raise

    def detectStandaloneSeasonShow(title):
        """
        Detects if a title is in the format "Show Name ##" where ## is a season number.
        Returns a tuple of (show_name, season_number) if detected, otherwise (None, None).
        Example: "American Dad 19" -> ("American Dad", "19")
        """
        import re
        
        # Check for the pattern of a title followed by a number at the end
        match = re.match(r'^(.+?)[\s]+(\d{1,2})$', title)
        if match:
            show_name = match.group(1).strip()
            season_number = match.group(2)
            
            # Validate - make sure it's a reasonable season number (1-40)
            # and the show name is a reasonable length
            try:
                season_num = int(season_number)
                if 1 <= season_num <= 40 and len(show_name) > 3:
                    return (show_name, season_number.zfill(2))
            except ValueError:
                pass
        
        return (None, None)    

    def _send_completion_notification(self):
        """Send notification about completion"""
        filename = os.path.basename(self.filename)
        details = {
            "movies": self.movies_count,
            "tv_shows": self.tv_count,
            "skipped": self.skip_count,
            "errors": self.error_count
        }
        
        if self.error_count > 0:
            send_notification(
                "M3U Processing Completed with Errors",
                f"Processed {filename} with {self.error_count} errors",
                "warning",
                details
            )
        else:
            send_notification(
                "M3U Processing Completed Successfully",
                f"Processed {filename} successfully",
                "success",
                details
            )

    def _scan_content_dirs(self):
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

    def _detect_content_changes(self):
        """Detect content changes by comparing before and after scans"""
        # Find new content
        new_movies = self.content_after["movies"] - self.content_before["movies"]
        new_tv = self.content_after["tv"] - self.content_before["tv"]
        
        # Find removed content
        removed_movies = self.content_before["movies"] - self.content_after["movies"]
        removed_tv = self.content_before["tv"] - self.content_after["tv"]
        
        # Log removed content
        for movie in removed_movies:
            movie_name = os.path.splitext(os.path.basename(movie))[0]
            db.log_content_change("movie", "removed", movie_name)
            
            # Send notification
            if notifications.should_send_notification():
                notifications.sync_notify_content_change("movie", "removed", movie_name)
        
        for tv in removed_tv:
            episode_name = os.path.splitext(os.path.basename(tv))[0]
            show_path = os.path.dirname(tv)
            show_name = os.path.basename(show_path)
            
            if "/" in show_path:  # It's in a season directory
                db.log_content_change("tv", "removed", f"{show_name} - {episode_name}")
                
                # Send notification
                if notifications.should_send_notification():
                    notifications.sync_notify_content_change("tv episode", "removed", f"{show_name} - {episode_name}")
            else:
                db.log_content_change("tv", "removed", f"{show_path} - {episode_name}")
                
                # Send notification
                if notifications.should_send_notification():
                    notifications.sync_notify_content_change("tv episode", "removed", f"{show_path} - {episode_name}")
        
        # Calculate statistics
        changes = {
            "added": len(new_movies) + len(new_tv),
            "removed": len(removed_movies) + len(removed_tv),
            "updated": 0  # We don't track updates here as they're logged during makeStream
        }
        
        self.changes = changes
        return changes

    def readLines(self):
        """Read all lines from the M3U file with enhanced error handling"""
        try:
            # Check if file exists
            if not os.path.exists(self.filename):
                error_msg = f"Error: M3U file not found at {self.filename}"
                self.log.write_to_log(error_msg, log_level=LogLevel.NORMAL)
                raise FileNotFoundError(error_msg)
                
            # Check if file is empty
            if os.path.getsize(self.filename) == 0:
                error_msg = f"Error: M3U file is empty ({self.filename})"
                self.log.write_to_log(error_msg, log_level=LogLevel.NORMAL)
                raise ValueError(error_msg)
                
            # Try to open the file with different encodings if needed
            encodings = ['utf-8', 'latin-1', 'cp1252']
            
            for encoding in encodings:
                try:
                    with open(self.filename, encoding=encoding) as file:
                        self.lines = [line.rstrip('\n') for line in file]
                        
                    # Check for minimum M3U content
                    if len(self.lines) < 2:
                        self.log.write_to_log(f"Warning: M3U file has only {len(self.lines)} lines", log_level=LogLevel.NORMAL)
                    
                    # Log success
                    self.log.write_to_log(f"Successfully read {len(self.lines)} lines from M3U file using {encoding} encoding", log_level=LogLevel.NORMAL)
                    return len(self.lines)
                except UnicodeDecodeError:
                    self.log.write_to_log(f"Could not decode file using {encoding} encoding, trying next...", log_level=LogLevel.NORMAL)
                    continue
            
            # If we've tried all encodings and none worked, try one more time with errors='ignore'
            self.log.write_to_log("Falling back to ignoring encoding errors", log_level=LogLevel.NORMAL)
            with open(self.filename, encoding='utf-8', errors='ignore') as file:
                self.lines = [line.rstrip('\n') for line in file]
                
            self.log.write_to_log(f"Read {len(self.lines)} lines from M3U file with encoding errors ignored", log_level=LogLevel.NORMAL)
            return len(self.lines)
                
        except Exception as e:
            error_msg = f"Failed to read M3U file: {str(e)}"
            self.log.write_to_log(error_msg, log_level=LogLevel.NORMAL)
            self.error_count += 1
            processing_monitor.update_job(
                self.job_id,
                status='error',
                current_item=f"Error reading M3U file: {str(e)}",
                errors=self.error_count
            )
            raise
    
    def parseM3UToMemory(self):
        """PHASE 1: Parse the M3U file and collect all streams in memory without creating STRM files"""
        linenumber = 0
        total_lines = len(self.lines)
        items_processed = 0
        last_update_time = time.time()
        
        # Update status
        processing_monitor.update_job(
            self.job_id,
            current_item=f"Phase 1: Parsing M3U file",
            items_processed=0
        )
        
        send_notification(
            "Parsing M3U", 
            f"Reading {total_lines} lines", 
            "info"
        )
        
        # Get language filter from config
        config = db.load_config()
        language_filter = config.get("language_filter", "EN")
        skip_non_english = config.get("skip_non_english", True)
        
        while linenumber < total_lines:
            # Update processing status every 100 lines or 5 seconds
            if items_processed % 100 == 0 or (items_processed > 0 and time.time() - last_update_time > 5):
                processing_monitor.update_job(
                    self.job_id,
                    current_item=f"Phase 1: Parsing line {linenumber}/{total_lines}",
                    items_processed=items_processed,
                    errors=self.error_count
                )
                last_update_time = time.time()
                
                # Also send status to browser
                if items_processed % 500 == 0:  # Less frequent to reduce browser load
                    progress = {
                        "jobId": self.job_id,
                        "line": linenumber,
                        "total_lines": total_lines,
                        "processed": items_processed,
                        "currentItem": f"Phase 1: Parsing line {linenumber}/{total_lines}"
                    }
                    send_status_update(progress)
            
            try:
                thisline = self.lines[linenumber]
                
                # Skip if we're at the end of the file
                if linenumber + 1 >= total_lines:
                    break
                    
                nextline = self.lines[linenumber + 1]
                
                firstline = re.compile('EXTM3U', re.IGNORECASE).search(thisline)
                if firstline:
                    linenumber += 1
                    continue
                    
                # Process stream entries
                tvg_name_match = re.search(r'tvg-name="([^"]*)"', thisline)
                if tvg_name_match:
                    tvg_name = tvg_name_match.group(1)
                    
                    # Skip non-matching language if filter is enabled
                    if skip_non_english and language_filter and not tvg_name.startswith(f'{language_filter} - '):
                        logger.debug(f"Skipping non-{language_filter} stream: {tvg_name}")
                        self.skip_count += 1
                        if linenumber + 1 < total_lines and thisline[0] == "#" and nextline[0] == "#":
                            linenumber += 3 if linenumber + 2 < total_lines else 2
                        else:
                            linenumber += 2 if linenumber + 1 < total_lines else 1
                        continue
                    
                    # Process stream
                    if thisline[0] == "#" and nextline[0] == "#":
                        if linenumber + 2 < total_lines and tools.verifyURL(self.lines[linenumber+2]):
                            streaminfo = ' '.join([thisline, nextline])
                            streamURL = self.lines[linenumber+2]
                            
                            # Save the stream entry for later processing
                            stream_entry = StreamEntry(streaminfo, streamURL)
                            self.streams.append(stream_entry)
                            items_processed += 1
                            
                            linenumber += 3
                        else:
                            logger.warning(f"Invalid stream format at line {linenumber}")
                            linenumber += 1
                    elif tools.verifyURL(nextline):
                        streaminfo = thisline
                        streamURL = nextline
                        
                        # Save the stream entry for later processing
                        stream_entry = StreamEntry(streaminfo, streamURL)
                        self.streams.append(stream_entry)
                        items_processed += 1
                        
                        linenumber += 2
                    else:
                        linenumber += 1
                else:
                    linenumber += 1
                    
            except Exception as e:
                logger.error(f"Error parsing line {linenumber}: {str(e)}")
                self.error_count += 1
                linenumber += 1
        
        # Update status after phase 1
        processing_monitor.update_job(
            self.job_id,
            current_item=f"Phase 1 complete: Found {len(self.streams)} streams",
            items_processed=len(self.streams)
        )
        
        # Pre-determine stream types
        self._determine_stream_types()
        
        logger.info(f"Parsed {len(self.streams)} streams from M3U file")
        send_notification(
            "M3U Parsing Complete", 
            f"Found {len(self.streams)} streams in the M3U file", 
            "success"
        )
    
    def _determine_stream_types(self):
        """Determine the type of each stream beforehand"""
        movie_count = 0
        tv_count = 0
        
        for i, stream in enumerate(self.streams):
            if i % 100 == 0:
                processing_monitor.update_job(
                    self.job_id,
                    current_item=f"Determining stream types: {i}/{len(self.streams)}",
                    items_processed=i
                )
            
            try:
                stream_type = self.parseStreamType(stream.streaminfo)
                stream.stream_type = stream_type
                
                if stream_type == 'vodMovie':
                    movie_count += 1
                elif stream_type == 'vodTV':
                    tv_count += 1
            except Exception as e:
                logger.error(f"Error determining stream type: {str(e)}")
                # Default to movie
                stream.stream_type = 'vodMovie'
        
        logger.info(f"Pre-determined stream types: {movie_count} movies, {tv_count} TV shows")
    
    def processStreamEntries(self):
        """PHASE 2: Process all collected stream entries to create STRM files"""
        total_streams = len(self.streams)
        items_processed = 0
        last_update_time = time.time()
        
        # Update status
        processing_monitor.update_job(
            self.job_id,
            current_item=f"Phase 2: Creating STRM files",
            items_processed=0
        )
        
        send_notification(
            "Creating STRM Files", 
            f"Processing {total_streams} streams", 
            "info"
        )
        
        for i, stream in enumerate(self.streams):
            # Update processing status every 10 items or 5 seconds
            if i % 10 == 0 or (i > 0 and time.time() - last_update_time > 5):
                processing_monitor.update_job(
                    self.job_id,
                    current_item=f"Phase 2: Processing stream {i+1}/{total_streams}",
                    items_processed=i,
                    errors=self.error_count
                )
                last_update_time = time.time()
                
                # Also send status to browser
                if i % 50 == 0:  # Less frequent to reduce browser load
                    progress = {
                        "jobId": self.job_id,
                        "processed": i,
                        "total": total_streams,
                        "movies": self.movies_count,
                        "tv": self.tv_count,
                        "skipped": self.skip_count,
                        "errors": self.error_count,
                        "currentItem": f"Phase 2: Processing stream {i+1}/{total_streams}"
                    }
                    send_status_update(progress)
            
            try:
                # Process the stream with a timeout
                run_with_timeout(
                    self.processStreamEntry,
                    stream,
                    timeout=PROCESSING_TIMEOUT
                )
                items_processed += 1
            except Exception as e:
                logger.error(f"Error processing stream {i}: {str(e)}")
                self.error_count += 1
                self.skip_count += 1
                
                # Extract stream name for notification if possible
                stream_name = stream.tvg_name or f"Stream #{i+1}"
                
                send_notification(
                    "Stream Processing Error",
                    f"Skipped problematic stream: {stream_name}",
                    "warning"
                )
        
        # Final status update
        processing_monitor.update_job(
            self.job_id,
            current_item="Phase 2 complete: Created STRM files",
            items_processed=items_processed,
            errors=self.error_count,
            status="completed"
        )
        
        # Also send final status to browser
        progress = {
            "jobId": self.job_id,
            "processed": items_processed,
            "total": total_streams,
            "movies": self.movies_count,
            "tv": self.tv_count,
            "skipped": self.skip_count,
            "errors": self.error_count,
            "currentItem": "Completed",
            "status": "completed"
        }
        send_status_update(progress)
    
    def processStreamEntry(self, stream):
        """Process a single stream entry to create STRM file"""
        # If stream type wasn't pre-determined, determine it now
        if not stream.stream_type:
            stream.stream_type = self.parseStreamType(stream.streaminfo)
        
        # Process based on determined stream type
        if stream.stream_type == 'vodTV':
            try:
                self.parseVodTv(stream.streaminfo, stream.streamURL)
                self.tv_count += 1
            except Exception as e:
                logger.error(f"ERROR in parseVodTv: {str(e)}")
                # Try fallback method if standard fails
                try:
                    fallback_success = self.createFallbackTVShow(stream.streaminfo, stream.streamURL)
                    
                    if fallback_success:
                        self.tv_count += 1
                    else:
                        # If all TV show methods fail, process as movie
                        logger.warning("TV show parsing failed, treating as movie")
                        self.parseVodMovie(stream.streaminfo, stream.streamURL)
                        self.movies_count += 1
                except Exception as fallback_error:
                    logger.error(f"Fallback TV show processing failed: {str(fallback_error)}")
                    self.error_count += 1
                    self.skip_count += 1
                    raise  # Re-raise to be handled by the caller
        elif stream.stream_type == 'vodMovie':
            try:
                self.parseVodMovie(stream.streaminfo, stream.streamURL)
                self.movies_count += 1
            except Exception as e:
                logger.error(f"ERROR in parseVodMovie: {str(e)}")
                self.error_count += 1
                self.skip_count += 1
                raise  # Re-raise to be handled by the caller
        else:
            # Live stream or other type - just skip
            self.skip_count += 1

    def parseStreamType(self, streaminfo):
        """Determine the type of stream based on information in the stream metadata."""
        logger.debug(f"\nDetermining stream type for: {streaminfo}")
        
        # Get custom keywords from config
        config = db.load_config()
        movie_keywords = config.get("movie_keywords", ["movie", "film", "feature"])
        tv_keywords = config.get("tv_keywords", ["tv", "show", "series", "episode"])
        
        # Log the keywords we're using for detection
        logger.debug(f"Using movie keywords: {movie_keywords}")
        logger.debug(f"Using TV keywords: {tv_keywords}")
        
        try:
            # Check for explicit type in the stream info
            typematch = tools.tvgTypeMatch(streaminfo)
            if typematch:
                streamtype = tools.getResult(typematch)
                logger.debug(f"Found explicit type: {streamtype}")
                if streamtype == 'tvshows':
                    return 'vodTV'
                if streamtype == 'movies':
                    return 'vodMovie'
                if streamtype == 'live':
                    return 'live'
            
            # Check for season and episode pattern (SxxExx)
            tvshowmatch = tools.sxxExxMatch(streaminfo)
            if tvshowmatch:
                logger.debug(f"Found TV show pattern: {tvshowmatch.group()}")
                return 'vodTV'
            
            # Check for airdate pattern
            airdatematch = tools.airDateMatch(streaminfo)
            if airdatematch:
                logger.debug(f"Found airdate pattern: {airdatematch.group()}")
                return 'vodTV'
            
            # Check for keywords in the title
            tvg_name_match = tools.tvgNameMatch(streaminfo)
            if tvg_name_match:
                title = tools.getResult(tvg_name_match).lower()
                logger.debug(f"Checking title for keywords: {title}")
                
                # Check for TV show keywords
                for keyword in tv_keywords:
                    if keyword.lower() in title:
                        logger.debug(f"Found TV keyword in title: {keyword}")
                        return 'vodTV'
                
                # Check for movie keywords
                for keyword in movie_keywords:
                    if keyword.lower() in title:
                        logger.debug(f"Found movie keyword in title: {keyword}")
                        return 'vodMovie'
                
                # Check for year in parentheses (typical for movies)
                year_pattern = re.compile(r'\(\d{4}\)').search(title)
                if year_pattern:
                    logger.debug(f"Found year pattern in title: {year_pattern.group()}")
                    return 'vodMovie'
                
                # Check for common TV show indicators
                common_tv_indicators = [
                    'episode', 'season', 'series', 'show', 
                    's01', 's02', 's03', 's1', 's2', 's3',
                    'e01', 'e02', 'e1', 'e2',
                    ' tv ', ' serie', ' tv-', ' tv:'
                ]
                
                for indicator in common_tv_indicators:
                    if indicator in title.lower():
                        logger.debug(f"Found TV indicator in title: {indicator}")
                        return 'vodTV'
            
            # Check if it might be a TV show based on naming convention
            if tvg_name_match:
                title = tools.getResult(tvg_name_match)
                # Look for common TV show indicators like "S01" or "Season 1" or "Episode"
                tv_indicator = re.compile(r'S\d+|Season \d+|Episode', re.IGNORECASE).search(title)
                if tv_indicator:
                    logger.debug(f"Found TV indicator in title: {tv_indicator.group()}")
                    return 'vodTV'
            
            # Default to movie if we can't determine
            logger.debug("Defaulting to movie type")
            return 'vodMovie'
            
        except Exception as e:
            logger.error(f"Error determining stream type: {str(e)}")
            # Default to movie if there's an error
            return 'vodMovie'

    def createFallbackTVShow(self, streaminfo, streamURL):
        """Create a TV Show entry using fallback methods when standard detection fails"""
        logger.debug("\n=== FALLBACK TV SHOW PROCESSING START ===")
        logger.debug(f"Using fallback TV show detection for: {streaminfo}")
        
        # Get the title from tvg-name
        tvg_name_match = re.search(r'tvg-name="([^"]*)"', streaminfo)
        if tvg_name_match:
            original_title = tvg_name_match.group(1)
            
            # Remove language prefix if exists
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
                
                # Get resolution if available
                resolution = tools.resolutionMatch(streaminfo)
                if resolution:
                    resolution = tools.parseResolution(resolution)
                    
                # Create episode with default season 1, episode 1
                logger.debug(f"Creating fallback TV episode: Show={show_title}, Episode={episode_title}")
                episode = TVEpisode(
                    show_title, 
                    streamURL,
                    seasonnumber="01",
                    episodenumber="01",
                    resolution=resolution,
                    episodename=episode_title
                )
                
                if episode:
                    logger.debug(f"Created fallback episode: {episode.__dict__}")
                    episode.makeStream(self.m3u_url)  # Pass the M3U URL as provider URL
                    logger.debug("=== FALLBACK TV SHOW PROCESSING COMPLETE ===\n")
                    return True
            else:
                # If no hyphen, just use the title as show name and "Episode 1" as episode name
                show_title = title.strip()
                episode_title = "Episode 1"
                
                # Get resolution if available
                resolution = tools.resolutionMatch(streaminfo)
                if resolution:
                    resolution = tools.parseResolution(resolution)
                
                # Create episode with default season 1, episode 1
                logger.debug(f"Creating basic fallback TV episode: Show={show_title}")
                episode = TVEpisode(
                    show_title, 
                    streamURL,
                    seasonnumber="01",
                    episodenumber="01",
                    resolution=resolution,
                    episodename=episode_title
                )
                
                if episode:
                    logger.debug(f"Created fallback episode: {episode.__dict__}")
                    episode.makeStream(self.m3u_url)  # Pass the M3U URL as provider URL
                    logger.debug("=== FALLBACK TV SHOW PROCESSING COMPLETE ===\n")
                    return True
        
        logger.debug("Fallback TV show detection failed")
        logger.debug("=== FALLBACK TV SHOW PROCESSING FAILED ===\n")
        return False
    
    def parseVodTv(self, streaminfo, streamURL):
        logger.debug("\n=== TV SHOW PROCESSING START ===")
        logger.debug(f"Parsing TV VOD: {streaminfo}")
        
        # Get language filter from config
        config = db.load_config()
        language_filter = config.get("language_filter", "EN")
        
        # Get the title from tvg-name
        tvg_name_match = re.search(r'tvg-name="([^"]*)"', streaminfo)
        if tvg_name_match:
            original_title = tvg_name_match.group(1)
            title = original_title
            logger.debug(f"Original title: {original_title}")
            
            # Remove language prefix if it exists
            if language_filter and title.startswith(f'{language_filter} - '):
                title = original_title[len(language_filter) + 3:]  # Remove "XX - " prefix
                logger.debug(f"Title after language prefix removal: {title}")
            
            # NEW CODE: Check for standalone season number format (like "American Dad 19")
            # Inline detection of standalone season shows to avoid scope issues
            standalone_season_match = re.match(r'^(.+?)[\s]+(\d{1,2})$', title)
            if standalone_season_match:
                show_name = standalone_season_match.group(1).strip()
                season_number = standalone_season_match.group(2)
                
                # Validate - make sure it's a reasonable season number (1-40)
                # and the show name is a reasonable length
                try:
                    season_num = int(season_number)
                    if 1 <= season_num <= 40 and len(show_name) > 3:
                        # Valid standalone season detected
                        logger.debug(f"Detected standalone season format: {show_name} Season {season_number}")
                        
                        # Get resolution if available
                        resolution = tools.resolutionMatch(streaminfo)
                        if resolution:
                            resolution = tools.parseResolution(resolution)
                        
                        # Create a generic episode for this season
                        episode = TVEpisode(
                            show_name,
                            streamURL,
                            seasonnumber=season_number.zfill(2),
                            episodenumber="01",  # Use 01 as a default episode number
                            resolution=resolution,
                            episodename=f"Season {season_number} Episode 1"
                        )
                        
                        if episode:
                            logger.debug(f"Created episode from standalone season: {episode.__dict__}")
                            episode.makeStream(self.m3u_url)  # Pass the M3U URL as provider URL
                            logger.debug("=== TV SHOW PROCESSING COMPLETE ===\n")
                            return
                except ValueError:
                    # Not a valid season number, continue with normal processing
                    pass
            
            # Remove date/year pattern if it exists
            title = re.sub(r'\s*\(\d{4}\)$', '', title)
            logger.debug(f"Processing TV title: {title}")
            
            resolution = tools.resolutionMatch(streaminfo)
            if resolution:
                resolution = tools.parseResolution(resolution)
                logger.debug(f"Found resolution: {resolution}")
            
            # Parse episode information
            episodeinfo = tools.parseEpisode(title)
            episode = None
            
            if episodeinfo:
                logger.debug(f"Found episode info: {episodeinfo}")
                if len(episodeinfo) == 3:
                    showtitle = episodeinfo[0]
                    airdate = episodeinfo[2]
                    episodename = episodeinfo[1] if episodeinfo[1] is not None else ""  # Ensure episodename is not None
                    logger.debug(f"Airdate format detected: Show={showtitle}, Name={episodename}, Date={airdate}")
                    episode = TVEpisode(showtitle, streamURL, 
                                    resolution=resolution, 
                                    episodename=episodename, 
                                    airdate=airdate)
                else:
                    showtitle = episodeinfo[0]
                    episodename = episodeinfo[1] if episodeinfo[1] is not None else ""  # Ensure episodename is not None
                    seasonnumber = episodeinfo[2]
                    episodenumber = episodeinfo[3]
                    logger.debug(f"Season format detected: Show={showtitle}, Name={episodename}, S{seasonnumber}E{episodenumber}")
                    episode = TVEpisode(showtitle, streamURL, 
                                    seasonnumber=seasonnumber, 
                                    episodenumber=episodenumber, 
                                    resolution=resolution, 
                                    episodename=episodename)
                
                if episode:
                    logger.debug(f"Created episode object: {episode.__dict__}")
                    logger.debug(f"Episode filename: {episode.getFilename()}")
                    episode.makeStream(self.m3u_url)  # Pass the M3U URL as provider URL
                    logger.debug("=== TV SHOW PROCESSING COMPLETE ===\n")
                else:
                    logger.error("Failed to create episode object")
                    logger.debug("=== TV SHOW PROCESSING FAILED ===\n")
                    raise Exception("Failed to create episode object")
            else:
                logger.error("Could not parse episode information from title")
                logger.debug("=== TV SHOW PROCESSING FAILED ===\n")
                raise Exception("Could not parse episode information from title")
        else:
            logger.error("No tvg-name found in stream info")
            logger.debug("=== TV SHOW PROCESSING FAILED ===\n")
            raise Exception("No tvg-name found in stream info")
                
    def parseLiveStream(self, streaminfo, streamURL):
        # We don't process live streams for now
        pass

    def parseVodMovie(self, streaminfo, streamURL):
        logger.debug(f"Parsing Movie VOD: {streaminfo}")
        
        # Get language filter from config
        config = db.load_config()
        language_filter = config.get("language_filter", "EN")
        
        # Get the title from tvg-name
        tvg_name_match = re.search(r'tvg-name="([^"]*)"', streaminfo)
        if tvg_name_match:
            original_title = tvg_name_match.group(1)
            title = original_title
            
            # Remove language prefix if it exists
            if language_filter and title.startswith(f'{language_filter} - '):
                title = original_title[len(language_filter) + 3:]  # Remove "XX - " prefix
                
            # Remove date/year pattern if it exists
            title = re.sub(r'\s*\(\d{4}\)$', '', title)
            logger.debug(f"Processing movie title: {title}")
            
            resolution = tools.resolutionMatch(streaminfo)
            if resolution:
                resolution = tools.parseResolution(resolution)
            
            year = tools.yearMatch(streaminfo)
            if year:
                title = tools.stripYear(title)
                year = year.group().strip()
            
            moviestream = Movie(title, streamURL, year=year, resolution=resolution)
            logger.debug(f"Created movie object: {moviestream.__dict__}")
            moviestream.makeStream(self.m3u_url)  # Pass the M3U URL as provider URL
            
    def get_stats(self):
        """Return statistics about processed content"""
        stats = {
            "movies_count": self.movies_count,
            "tv_count": self.tv_count,
            "skip_count": self.skip_count,
            "error_count": self.error_count
        }
        
        if hasattr(self, 'changes'):
            stats['changes'] = self.changes
            
        return stats

async def async_process_m3u(filename, job_id=None, url=None):
    """Process an M3U file asynchronously with provider tracking"""
    loop = asyncio.get_event_loop()
    
    def process_sync():
        try:
            # Track provider if URL is provided
            if url:
                from provider_utils import ProviderManager
                manager = ProviderManager()
                provider_name = manager.get_provider_name(url)
                logger.info(f"Processing M3U from provider: {provider_name}")
            
            # Create stream list and process it
            stream_list = rawStreamList(filename, job_id, m3u_url=url)
            stats = stream_list.get_stats()
            
            # Update provider content count
            if url and stats:
                total_content = stats.get('movies_count', 0) + stats.get('tv_count', 0)
                if total_content > 0:
                    manager = ProviderManager()
                    manager.update_content_count(url, total_content)
            
            return stats
        except Exception as e:
            logger.error(f"Error in async_process_m3u: {str(e)}")
            if 'send_notification' in globals():
                send_notification(
                    "M3U Processing Failed", 
                    f"Failed to process {os.path.basename(filename)}: {str(e)}", 
                    "error"
                )
            # Re-raise with a more descriptive message
            raise Exception(f"Failed to process M3U file: {str(e)}")
    
    # Run the CPU-bound parsing in a thread pool
    return await loop.run_in_executor(None, process_sync)

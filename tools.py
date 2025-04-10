import re
import os
import logging

# Initialize logger
logger = logging.getLogger(__name__)

def verifyURL(line):
  verifyurl  = re.compile('://').search(line)
  if verifyurl:
    return True
  return

def tvgTypeMatch(line):
  typematch = re.compile('tvg-type=\"(.*?)\"', re.IGNORECASE).search(line)
  if typematch:
    return typematch
  return
  
def ufcwweMatch(line):
  ufcwwematch = re.compile('[U][f][c]|[w][w][e]|[r][i][d][i][c][u][l]', re.IGNORECASE).search(line)
  if ufcwwematch:
    return ufcwwematch
  return

def airDateMatch(line):
  datematch = re.compile('[1-2][0-9][0-9][0-9][ ][0-3][0-9][ ][0-1][0-9]|[1-2][0-9][0-9][0-9][ ][0-1][0-9][ ][0-3][0-9]').search(line)
  if datematch:
    return datematch
  return

def tvgNameMatch(line):
  namematch = re.compile('tvg-name=\"(.*?)\"', re.IGNORECASE).search(line)
  if namematch:
    return namematch
  return

def tvidmatch(line):
  tvidmatch = re.compile('tvg-ID=\"(.*?)\"', re.IGNORECASE).search(line)
  if tvidmatch:
    return tvidmatch
  return

def tvgLogoMatch(line):
  logomatch = re.compile('tvg-logo=\"(.*?)\"', re.IGNORECASE).search(line)
  if logomatch:
    return logomatch
  return

def tvgGroupMatch(line):
  groupmatch = re.compile('group-title=\"(.*?)\"', re.IGNORECASE).search(line)
  if groupmatch:
    return groupmatch
  return
      
def infoMatch(line):
  infomatch = re.compile('[,](?!.*[,])(.*?)$', re.IGNORECASE).search(line)
  if infomatch:
    return infomatch
  return

def getResult(re_match):
  if re_match and re_match.group() and '"' in re_match.group():
    return re_match.group().split('\"')[1]
  return ""
      
def sxxExxMatch(line):
  """Enhanced function to match TV show season/episode patterns"""
  # Original patterns
  tvshowmatch = re.compile('[s][0-9][0-9][e][0-9][0-9]|[0-9][0-9][x][0-9][0-9][ ][-][ ]|[s][0-9][0-9][ ][e][0-9][0-9]|[0-9][0-9][x][0-9][0-9]', re.IGNORECASE).search(line)
  if tvshowmatch:
    return tvshowmatch
  
  tvshowmatch = seasonMatch2(line)
  if tvshowmatch:
    return tvshowmatch
    
  tvshowmatch = episodeMatch2(line)
  if tvshowmatch:
    return tvshowmatch
  
  # NEW ENHANCED PATTERNS
  
  # Check for "Season X Episode Y" format
  season_episode_pattern = re.compile(r'[sS]eason\s*\d+\s*[eE]pisode\s*\d+|[sS]\d+\s*[eE]\d+|[sS]\d+\s*-\s*[eE]\d+', re.IGNORECASE).search(line)
  if season_episode_pattern:
    return season_episode_pattern
  
  # Check for standalone season numbers for shows like "American Dad 19"
  # First extract the show name without language prefix
  show_name = None
  tvg_match = tvgNameMatch(line)
  if tvg_match:
    show_title = getResult(tvg_match)
    if ' - ' in show_title:
      parts = show_title.split(' - ', 1)
      if len(parts[0]) <= 3:  # Assume language codes are 2-3 chars
        show_name = parts[1]
      else:
        show_name = parts[0]
    else:
      show_name = show_title
      
    if show_name:
      # Try to find isolated season number at the end
      isolated_season = re.compile(r'(.+?)[\s]+(\d{1,2})$', re.IGNORECASE).search(show_name)
      if isolated_season:
        # Verify it's a reasonable season number (1-40)
        potential_season = isolated_season.group(2)
        season_num = int(potential_season)
        if 1 <= season_num <= 40:
          # Create a fake SxxExx pattern for compatibility
          return re.compile(f'[s]{potential_season.zfill(2)}[e]01', re.IGNORECASE).search(f"S{potential_season.zfill(2)}E01")
  
  # Check for formats like "Name 1901" where 19 is season, 01 is episode
  if show_name:
    compact_format = re.compile(r'(.+?)[\s]+(\d{1,2})(\d{2})$', re.IGNORECASE).search(show_name)
    if compact_format:
      potential_season = compact_format.group(2)
      potential_episode = compact_format.group(3)
      # Check if it's a reasonable season number
      season_num = int(potential_season)
      if 1 <= season_num <= 40:
        # Create a fake SxxExx pattern for compatibility
        return re.compile(f'[s]{potential_season.zfill(2)}[e]{potential_episode}', re.IGNORECASE).search(f"S{potential_season.zfill(2)}E{potential_episode}")
  
  return None

def tvgChannelMatch(line):
  tvgchnomatch = re.compile('tvg-chno=\"(.*?)\"', re.IGNORECASE).search(line)
  if tvgchnomatch:
    return tvgchnomatch
  tvgchannelid = re.compile('tvg-chno=\"(.*?)\"', re.IGNORECASE).search(line)
  if tvgchannelid:
    return tvgchannelid
  return

def yearMatch(line):
  yearmatch = re.compile('[(][1-2][0-9][0-9][0-9][)]').search(line)
  if yearmatch:
    return yearmatch
  return

def resolutionMatch(line):
  resolutionmatch = re.compile('HD|SD|720p WEB x264-XLF|WEB x264-XLF|720p|1080p|2160p|4K|UHD', re.IGNORECASE).search(line)
  if resolutionmatch:
    return resolutionmatch
  return

def episodeMatch(line):
  episodematch = re.compile('[e][0-9][0-9]|[0-9][0-9][x][0-9][0-9]', re.IGNORECASE).search(line)
  if episodematch:
    if episodematch.end() - episodematch.start() > 3:
      episodenumber = episodematch.group()[3:]
      #print(episodenumber,'E#')
    else:
      episodenumber = episodematch.group()[1:]
      #print(episodenumber,'E#')
    return episodenumber
  
  # Try to match more episode patterns
  episode_patterns = [
    re.compile(r'[eE]pisode\s*(\d+)', re.IGNORECASE),
    re.compile(r'[eE]p[.]?\s*(\d+)', re.IGNORECASE),
    re.compile(r'E(\d+)', re.IGNORECASE)
  ]
  
  for pattern in episode_patterns:
    match = pattern.search(line)
    if match:
      return match.group(1).zfill(2)
      
  return

def episodeMatch2(line):
  episodematch = re.compile('[e][0-9][0-9]|[0-9][0-9][x][0-9][0-9]', re.IGNORECASE).search(line)
  if episodematch:
    return episodematch
    
  # Try more patterns
  flexible_patterns = [
    re.compile(r'[eE]pisode\s*\d+', re.IGNORECASE),
    re.compile(r'[eE]p[.]?\s*\d+', re.IGNORECASE)
  ]
  
  for pattern in flexible_patterns:
    match = pattern.search(line)
    if match:
      return match
      
  return

def seasonMatch2(line):
  """Enhanced function to find season pattern in a string"""
  # Original pattern
  seasonmatch = re.compile('[s][0-9][0-9]', re.IGNORECASE).search(line)
  if seasonmatch:   
    return seasonmatch
  
  # NEW ENHANCED PATTERNS
  
  # Check for "Season X" format
  season_word_match = re.compile(r'[sS]eason\s+\d{1,2}', re.IGNORECASE).search(line)
  if season_word_match:
    return season_word_match
  
  # Check for "S.X" format (with period)
  s_dot_match = re.compile(r'[sS]\.\d{1,2}', re.IGNORECASE).search(line)
  if s_dot_match:
    return s_dot_match
    
  # Check for standalone season number
  # Doesn't return match object but is handled in sxxExxMatch
  
  return None

def seasonMatch(line):
  seasonmatch = re.compile('[s][0-9][0-9]|[0-9][0-9][x][0-9][0-9]', re.IGNORECASE).search(line)
  if seasonmatch:
    if seasonmatch.end() - seasonmatch.start() > 3:
      seasonnumber = seasonmatch.group()[:3]
      #print(seasonnumber,'s#')
    else:
      seasonnumber = seasonmatch.group()[1:]
      #print(seasonnumber,'s#')
    return seasonnumber
  
  # Try to match more season patterns
  season_patterns = [
    re.compile(r'[sS]eason\s*(\d+)', re.IGNORECASE),
    re.compile(r'[sS]e?[.]?\s*(\d+)', re.IGNORECASE),
    re.compile(r'S(\d+)', re.IGNORECASE)
  ]
  
  for pattern in season_patterns:
    match = pattern.search(line)
    if match:
      return match.group(1).zfill(2)
      
  return

def imdbCheck(line):
  imdbmatch = re.compile('[t][t][0-9][0-9][0-9]').search(line)
  if imdbmatch:
    return imdbmatch
  return

def parseMovieInfo(info):
  if info is None:
    return ""
    
  if ',' in info:
    info = info.split(',')
  if info[0] == "":
    del info[0]
  info = info[-1]
  if '#' in info:
    info = info.split('#')[0]
  if ':' in info:
    info = info.split(':')
    if resolutionMatch(info[0]):
      info = info[1]
    else:
      info = ':'.join(info)
  return info.strip()
     
def parseResolution(match):
  if match is None:
    return None
    
  resolutionmatch = match.group().strip().lower()
  if resolutionmatch == 'hd' or resolutionmatch == '720p' or resolutionmatch == '720p web x264-xlf':
    return '720p'
  elif resolutionmatch == 'sd' or resolutionmatch == 'web x264-xlf':
    return '480p'
  elif resolutionmatch == '1080p':
    return '1080p'
  elif resolutionmatch in ['2160p', '4k', 'uhd']:
    return '2160p'
  return

def makeStrm(filename, url):
  if not os.path.exists(filename):
    streamfile = open(filename, "w+")
    streamfile.write(url)
    streamfile.close
    logger.info(f"STRM file created: {filename}")
    streamfile.close()
  else:
    # Check if URL is different
    with open(filename, "r") as f:
      current_url = f.read().strip()
    
    if current_url != url:
      # Update with new URL
      with open(filename, "w") as f:
        f.write(url)
      logger.info(f"STRM file updated: {filename}")

def makeDirectory(directory):
  if not os.path.exists(directory):
    os.makedirs(directory, exist_ok=True)
    logger.info(f"Directory created: {directory}")
  else:
    logger.debug(f"Directory already exists: {directory}")

def stripYear(title):
  if title is None:
    return ""
    
  yearmatch = re.sub('[(][1-2][0-9][0-9][0-9][)]|[1-2][0-9][0-9][0-9]', "", title)
  if yearmatch:
    return yearmatch.strip()
  return ""

def languageMatch(line):
  if line is None:
    return None
    
  languagematch = re.compile('[|][A-Z][A-Z][|]', re.IGNORECASE).search(line)
  if languagematch:
    return languagematch
  return

def stripLanguage(title):
  if title is None:
    return ""
    
  languagematch = re.sub('[|][A-Z][A-Z][|]', "", title, flags=re.IGNORECASE)
  if languagematch:
    return languagematch.strip()
  return ""

def stripResolution(title):
  if title is None:
    return ""
    
  resolutionmatch = re.sub('HD|SD|720p WEB x264-XLF|WEB x264-XLF|720p|1080p|2160p|4K|UHD', "", title, flags=re.IGNORECASE)
  if resolutionmatch:
    return resolutionmatch.strip()
  return ""

def stripSxxExx(title):
  if title is None:
    return ""
    
  sxxexxmatch = re.sub('[s][0-9][0-9][e][0-9][0-9]|[0-9][0-9][x][0-9][0-9][ ][-][ ]|[0-9][0-9][x][0-9][0-9]|[s][0-9][0-9][ ][e][0-9][0-9]', "", title, flags=re.IGNORECASE)
  if sxxexxmatch:
    return sxxexxmatch.strip()
  return ""

def parseEpisode(title):
    """Enhanced function to extract TV show episode information from the title"""
    if title is None:
        logger.debug("parseEpisode received None title")
        return None
        
    logger.debug(f"parseEpisode analyzing: {title}")
    
    # Check for air date format first (e.g., "Show Name 2023 01 23 - Episode Title")
    airdate = airDateMatch(title)
    titlelen = len(title)
    showtitle, episodetitle, language = None, None, None
    
    if airdate:
        logger.debug(f"Found airdate format: {airdate.group()}")
        showtitle = title[:airdate.start()].strip()
        if airdate.end() != titlelen:
            episodetitle = title[airdate.end():].strip()
        else:
            episodetitle = ""  # Ensure episodetitle is never None
        logger.debug(f"Parsed airdate format: Show={showtitle}, Date={airdate.group()}, Episode={episodetitle}")
        return [showtitle, episodetitle, airdate.group()]
    
    # Check for SxxExx format (e.g., "Show Name S01E01 - Episode Title")
    seasonepisode = sxxExxMatch(title)
    if seasonepisode:
        logger.debug(f"Found season/episode format: {seasonepisode.group()}")
        
        # Determine if we have a standard format or something else
        if seasonepisode.end() - seasonepisode.start() > 6 or len(seasonepisode.group()) == 5:
            logger.debug(f"Using standard SxxExx parsing")
            
            # Get the part after the SxxExx pattern as the episode title
            episodetitle = title[seasonepisode.end():].strip()
            
            # Extract season and episode numbers
            seasonnumber = seasonMatch(title)
            episodenumber = episodeMatch(title)
            
            # Default to "01" if not found
            seasonnumber = seasonnumber if seasonnumber else "01"
            episodenumber = episodenumber if episodenumber else "01"
            
            # Get the show title (everything before the SxxExx pattern)
            showtitle = title[:seasonepisode.start()].strip()
            
            # Default to "Unknown Show" if not found
            showtitle = showtitle if showtitle else "Unknown Show"
            
            # Check for language tag in the title
            languagem = languageMatch(showtitle)
            if languagem:
                language = languagem.group().strip('|')
                showtitle = showtitle[languagem.end():].strip()
                
                # Check for a second language tag
                language2 = languageMatch(showtitle)
                if language2:
                    showtitle = showtitle[:language2.start()].strip()
                    
                    # Check for season info in the show title
                    season = seasonMatch2(showtitle)
                    if season:
                        showtitle = showtitle[:season.start()].strip()
        else:
            logger.debug(f"Using alternative SxxExx parsing")
            seasonnumber = seasonMatch(title)
            episodenumber = episodeMatch(title)
            showtitle = stripSxxExx(title).strip()
            
            # Default values for safety
            seasonnumber = seasonnumber if seasonnumber else "01"
            episodenumber = episodenumber if episodenumber else "01"
            showtitle = showtitle if showtitle else "Unknown Show"
        
        logger.debug(f"Parsed season format: Show={showtitle}, Season={seasonnumber}, Episode={episodenumber}, Title={episodetitle}")
        return [showtitle, episodetitle, seasonnumber, episodenumber, language]
    
    # NEW PATTERNS FOR SHOWS WITH STANDALONE SEASON NUMBERS
    
    # Check for titles like "American Dad 19"
    standalone_season = re.match(r'^(.+?)[\s]+(\d{1,2})$', title)
    if standalone_season:
        base_show = standalone_season.group(1).strip()
        potential_season = standalone_season.group(2).zfill(2)
        
        # Make sure it's a reasonable season number
        season_num = int(potential_season)
        if 1 <= season_num <= 40:  # Allow up to season 40
            logger.debug(f"Detected standalone season format: {base_show} Season {potential_season}")
            # Return with season number but dummy episode
            return [base_show, f"Season {potential_season}", potential_season, "01", None]
    
    # Try to detect other common TV show patterns
    # Format like "Show Name - Episode Title"
    if " - " in title:
        parts = title.split(" - ", 1)
        if len(parts) == 2:
            show_candidate = parts[0].strip()
            episode_candidate = parts[1].strip()
            
            # Check if show_candidate contains season number like "American Dad 19"
            show_with_season = re.match(r'^(.+?)[\s]+(\d{1,2})$', show_candidate)
            if show_with_season:
                base_show = show_with_season.group(1).strip()
                potential_season = show_with_season.group(2).zfill(2)
                
                # Make sure it's a reasonable season number
                season_num = int(potential_season)
                if 1 <= season_num <= 40:
                    logger.debug(f"Detected show with season in title: {base_show} Season {potential_season}")
                    return [base_show, episode_candidate, potential_season, "01", None]
            
            # Basic validation - if it seems reasonable
            if len(show_candidate) > 3 and len(episode_candidate) > 3:
                logger.debug(f"Detected dash-separated format: Show={show_candidate}, Episode={episode_candidate}")
                
                # Try to find season/episode in the episode title
                ep_match = re.search(r'(Season\s*(\d+))?\s*Episode\s*(\d+)', episode_candidate, re.IGNORECASE)
                if ep_match:
                    season_num = ep_match.group(2) if ep_match.group(2) else "01"
                    episode_num = ep_match.group(3)
                    # Clean up the episode title
                    clean_title = re.sub(r'Season\s*\d+\s*Episode\s*\d+', '', episode_candidate, flags=re.IGNORECASE).strip()
                    return [show_candidate, clean_title, season_num, episode_num, None]
                else:
                    # If we can't find season/episode info, create a dummy season 1 episode 1
                    logger.debug(f"No season info found, using defaults: S01E01")
                    return [show_candidate, episode_candidate, "01", "01", None]
    
    # If we've gotten this far, check if the title has multiple parts that might be a show and episode
    words = title.split()
    if len(words) >= 4:  # Reasonable minimum for "Show Name" + "Episode Title"
        # Try splitting at different points to see if we get valid show/episode pairs
        for i in range(2, min(5, len(words) - 2)):  # Try first 2-4 words as show title
            show_candidate = " ".join(words[:i])
            episode_candidate = " ".join(words[i:])
            
            # Very basic validation - non-empty strings that seem reasonable
            if len(show_candidate) > 3 and len(episode_candidate) > 3:
                logger.debug(f"Attempting word-split detection: Show={show_candidate}, Episode={episode_candidate}")
                # Use default season 1 episode 1
                return [show_candidate, episode_candidate, "01", "01", None]
    
    # If all else fails, return None
    logger.debug("Could not parse episode information")
    return None
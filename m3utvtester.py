#!/usr/bin/env python3
"""
TV Show Season Analyzer
Analyzes M3U files to find and diagnose TV show season detection issues
"""
import re
import os
import sys
import json
import argparse
from collections import defaultdict, Counter
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger("TV-Show-Analyzer")

def tvg_name_match(line):
    """Extract tvg-name from a line"""
    namematch = re.compile('tvg-name=\"(.*?)\"', re.IGNORECASE).search(line)
    if namematch:
        return namematch.group(1)
    return None

def extract_show_info(title):
    """Extract show name, season and episode info from title"""
    # Remove language prefix if present
    if ' - ' in title:
        parts = title.split(' - ', 1)
        if len(parts[0]) <= 3:  # Language code
            title = parts[1]
    
    # Common patterns for show titles with season/episode info
    patterns = [
        # Show Name S01E01
        r'^(.*?)\s+[Ss](\d{1,2})[Ee](\d{1,2})',
        # Show Name - S01E01
        r'^(.*?)\s+-\s+[Ss](\d{1,2})[Ee](\d{1,2})',
        # Show Name 1x01
        r'^(.*?)\s+(\d{1,2})x(\d{1,2})',
        # Show Name - Season 1 Episode 1
        r'^(.*?)\s+-\s+[Ss]eason\s+(\d{1,2})\s+[Ee]pisode\s+(\d{1,2})',
        # Show Name Season 1 Episode 1
        r'^(.*?)\s+[Ss]eason\s+(\d{1,2})\s+[Ee]pisode\s+(\d{1,2})',
        # Show Name - S01 E01
        r'^(.*?)\s+-\s+[Ss](\d{1,2})\s+[Ee](\d{1,2})',
        # Show Name S01 E01
        r'^(.*?)\s+[Ss](\d{1,2})\s+[Ee](\d{1,2})',
        # Show Name - 101 (season 1 episode 01)
        r'^(.*?)\s+-\s+(\d)(\d{2})$',
        # Show Name 101 (season 1 episode 01)
        r'^(.*?)\s+(\d)(\d{2})$',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, title)
        if match:
            show_name = match.group(1).strip()
            season = int(match.group(2))
            episode = int(match.group(3))
            return {'show': show_name, 'season': season, 'episode': episode}
    
    # Try to extract from format like "Show Name - Season 1"
    season_only_match = re.search(r'^(.*?)\s+-\s+[Ss]eason\s+(\d{1,2})$', title)
    if season_only_match:
        show_name = season_only_match.group(1).strip()
        season = int(season_only_match.group(2))
        return {'show': show_name, 'season': season, 'episode': None}
    
    # Try to extract full show name for shows without season info
    if ' - ' in title:
        parts = title.split(' - ', 1)
        return {'show': parts[0].strip(), 'season': None, 'episode': None}
    
    return {'show': title, 'season': None, 'episode': None}

def analyze_tv_shows(file_path, show_filter=None):
    """Analyze M3U file to find TV show season coverage"""
    if not os.path.exists(file_path):
        logger.error(f"File not found: {file_path}")
        return
        
    logger.info(f"Analyzing TV shows in M3U file: {file_path}")
    
    # Read the file
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = [line.rstrip('\n') for line in f]
    except Exception as e:
        logger.error(f"Error reading file: {e}")
        return
        
    logger.info(f"Read {len(lines)} lines")
    
    # Track TV show seasons
    shows = defaultdict(lambda: defaultdict(list))
    undetected_seasons = []
    problematic_lines = []
    
    # Process lines
    i = 0
    total_tv_entries = 0
    
    while i < len(lines):
        if i + 1 >= len(lines):
            break
            
        line = lines[i]
        
        # Skip if not an EXTINF line
        if not line.startswith('#EXTINF'):
            i += 1
            continue
        
        # Get the URL line
        if i + 1 < len(lines):
            url_line = lines[i + 1]
        else:
            url_line = ""
        
        # Extract name
        name = tvg_name_match(line)
        if not name:
            i += 1
            continue
        
        # Try to extract show info
        info = extract_show_info(name)
        
        # Skip if not the show we're looking for
        if show_filter and show_filter.lower() not in info['show'].lower():
            i += 1
            continue
            
        total_tv_entries += 1
        
        # If we detected season and episode, track it
        if info['season'] is not None:
            shows[info['show']][info['season']].append({
                'name': name,
                'line': line,
                'url': url_line,
                'episode': info['episode']
            })
        else:
            # This might be a TV show entry but we couldn't detect season/episode
            undetected_seasons.append({
                'name': name,
                'line': line,
                'url': url_line
            })
            problematic_lines.append(line)
        
        i += 1
    
    logger.info(f"Found {len(shows)} TV shows with detected seasons")
    logger.info(f"Found {len(undetected_seasons)} TV entries with undetected seasons")
    
    # Prepare results
    results = {
        'total_tv_entries': total_tv_entries,
        'shows_with_seasons': len(shows),
        'undetected_seasons': len(undetected_seasons),
        'show_data': {},
        'problematic_entries': undetected_seasons[:20],  # First 20 problematic entries
        'problematic_lines': problematic_lines[:20]  # First 20 problematic lines
    }
    
    # Process show data
    for show_name, seasons in shows.items():
        if show_filter and show_filter.lower() not in show_name.lower():
            continue
            
        season_nums = sorted(seasons.keys())
        episode_counts = {season: len(episodes) for season, episodes in seasons.items()}
        
        # Detect gaps in seasons
        if season_nums:
            max_season = max(season_nums)
            min_season = min(season_nums)
            expected_seasons = set(range(min_season, max_season + 1))
            missing_seasons = sorted(expected_seasons - set(season_nums))
        else:
            missing_seasons = []
        
        results['show_data'][show_name] = {
            'seasons': sorted(seasons.keys()),
            'season_count': len(seasons),
            'episode_counts': episode_counts,
            'missing_seasons': missing_seasons,
            'sample_entries': {
                season: episodes[0]['name'] if episodes else None
                for season, episodes in seasons.items()
            }
        }
    
    return results

def print_results(results, show_filter=None):
    """Print analysis results in a readable format"""
    if not results:
        return
        
    print("\n=====================================================")
    print("               TV SHOW ANALYSIS REPORT              ")
    print("=====================================================\n")
    
    print(f"Total TV entries analyzed: {results['total_tv_entries']}")
    print(f"TV shows with detected seasons: {results['shows_with_seasons']}")
    print(f"TV entries with undetected seasons: {results['undetected_seasons']}")
    print("\n")
    
    # If specific show filter, show detailed info for those shows
    if show_filter:
        filtered_shows = {name: data for name, data in results['show_data'].items() 
                          if show_filter.lower() in name.lower()}
        
        if not filtered_shows:
            print(f"No shows found matching filter: {show_filter}")
            return
            
        for show_name, data in filtered_shows.items():
            print(f"SHOW: {show_name}")
            print(f"  - Found {data['season_count']} seasons: {', '.join(map(str, data['seasons']))}")
            
            if data['missing_seasons']:
                print(f"  - MISSING SEASONS: {', '.join(map(str, data['missing_seasons']))}")
                
            print("  - Episode counts by season:")
            for season in sorted(data['seasons']):
                print(f"    Season {season}: {data['episode_counts'][season]} episodes")
                
            print("  - Sample entry format by season:")
            for season in sorted(data['seasons']):
                sample = data['sample_entries'][season]
                if sample:
                    print(f"    Season {season}: {sample}")
            
            print("\n")
    else:
        # Just show top 10 shows with the most seasons
        shows_by_season_count = sorted(
            results['show_data'].items(), 
            key=lambda x: x[1]['season_count'], 
            reverse=True
        )[:10]
        
        print("TOP 10 SHOWS BY SEASON COUNT:")
        for show_name, data in shows_by_season_count:
            print(f"  - {show_name}: {data['season_count']} seasons")
            if data['missing_seasons']:
                print(f"    Missing seasons: {', '.join(map(str, data['missing_seasons']))}")
        print("\n")
    
    # Print problematic entries if any
    if results['problematic_entries']:
        print("SAMPLE PROBLEMATIC ENTRIES (undetected seasons):")
        for entry in results['problematic_entries'][:5]:  # Show first 5
            print(f"  - {entry['name']}")
        print("\n")
        
        print("SAMPLE PROBLEMATIC LINES:")
        for line in results['problematic_lines'][:5]:  # Show first 5
            print(f"  - {line}")
        print("\n")
    
    print("RECOMMENDATIONS:")
    if results['undetected_seasons'] > 0:
        print("  ⚠️ Some TV show entries have undetected seasons. Check the naming patterns.")
        print("     Consider updating the season detection patterns in streamClasses.py")
    
    if show_filter and any(data['missing_seasons'] for data in filtered_shows.values()):
        print(f"  ⚠️ Found missing seasons for '{show_filter}'.")
        print("     This might indicate issues with the season numbering in your M3U or detection logic.")

def main():
    parser = argparse.ArgumentParser(description="Analyze TV show seasons in M3U files")
    parser.add_argument("file", help="Path to the M3U file")
    parser.add_argument("--show", help="Filter results to show containing this text")
    parser.add_argument("--output", help="Output file for JSON results")
    
    args = parser.parse_args()
    
    # Analyze file
    results = analyze_tv_shows(args.file, args.show)
    
    if not results:
        return
    
    # Print results
    print_results(results, args.show)
    
    # Save to file if requested
    if args.output:
        try:
            with open(args.output, 'w') as f:
                json.dump(results, f, indent=2)
            print(f"Results saved to {args.output}")
        except Exception as e:
            logger.error(f"Error saving results: {e}")

if __name__ == "__main__":
    main()
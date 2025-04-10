#!/usr/bin/env python3
"""
M3U Filter Analyzer
Analyzes M3U files to determine what content is being skipped and why
"""
import re
import os
import sys
import json
import argparse
from collections import Counter
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger("M3U-Analyzer")

def load_config(config_path="data/config.json"):
    """Load configuration from file or use defaults"""
    try:
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config = json.load(f)
                return config
        
        # Return defaults if file doesn't exist
        return {
            "language_filter": "EN",
            "skip_non_english": True,
            "movie_keywords": ["movie", "film", "feature", "cinema"],
            "tv_keywords": [
                "tv", "show", "series", "episode", "season", "s01", "s02", "e01", "e02",
                "television", "sitcom", "drama series", "miniseries", "documentary series"
            ],
        }
    except Exception as e:
        logger.error(f"Error loading config: {e}")
        return {
            "language_filter": "EN",
            "skip_non_english": True,
            "movie_keywords": ["movie", "film", "feature", "cinema"],
            "tv_keywords": [
                "tv", "show", "series", "episode", "season", "s01", "s02", "e01", "e02",
                "television", "sitcom", "drama series", "miniseries", "documentary series"
            ],
        }

def tvg_name_match(line):
    """Extract tvg-name from a line"""
    namematch = re.compile('tvg-name=\"(.*?)\"', re.IGNORECASE).search(line)
    if namematch:
        return namematch.group(1)
    return None

def is_tv_show(title, tv_keywords):
    """Check if title contains TV show keywords"""
    title_lower = title.lower()
    
    # Check for SxxExx pattern
    if re.search(r's\d{2}e\d{2}|\d{2}x\d{2}|season\s+\d+\s+episode\s+\d+', title_lower):
        return True
    
    # Check for keywords
    for keyword in tv_keywords:
        if keyword.lower() in title_lower:
            return True
            
    return False

def is_movie(title, movie_keywords):
    """Check if title contains movie keywords"""
    title_lower = title.lower()
    
    # Check for year in parentheses (common for movies)
    if re.search(r'\(\d{4}\)', title_lower):
        return True
    
    # Check for keywords
    for keyword in movie_keywords:
        if keyword.lower() in title_lower:
            return True
            
    return False

def analyze_m3u(file_path, config):
    """Analyze M3U file to determine what content is being skipped"""
    if not os.path.exists(file_path):
        logger.error(f"File not found: {file_path}")
        return
        
    logger.info(f"Analyzing M3U file: {file_path}")
    
    # Read the file
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = [line.rstrip('\n') for line in f]
    except Exception as e:
        logger.error(f"Error reading file: {e}")
        return
        
    logger.info(f"Read {len(lines)} lines")
    
    # Counters
    total_entries = 0
    language_skipped = 0
    unidentified_content = 0
    movie_count = 0
    tv_count = 0
    
    # Language distribution
    language_prefixes = Counter()
    
    # Content samples
    language_skipped_samples = []
    unidentified_samples = []
    
    # Process lines
    i = 0
    while i < len(lines):
        if i + 1 >= len(lines):
            break
            
        line = lines[i]
        
        # Skip if not an EXTINF line
        if not line.startswith('#EXTINF'):
            i += 1
            continue
            
        total_entries += 1
        
        # Extract name
        name = tvg_name_match(line)
        if not name:
            i += 1
            continue
        
        # Check language prefix
        language_filter = config.get("language_filter", "EN")
        skip_non_english = config.get("skip_non_english", True)
        
        # Extract language prefix if any
        language_prefix = None
        if ' - ' in name:
            parts = name.split(' - ', 1)
            if len(parts[0]) <= 3:  # Assume language codes are 2-3 chars
                language_prefix = parts[0]
                language_prefixes[language_prefix] += 1
        
        # Simulate language filtering
        if skip_non_english and language_filter:
            expected_prefix = f'{language_filter} - '
            if not name.startswith(expected_prefix):
                if len(language_skipped_samples) < 5:
                    language_skipped_samples.append(name)
                language_skipped += 1
                i += 1
                continue
        
        # Check content type
        title = name
        if language_filter and title.startswith(f'{language_filter} - '):
            title = title[len(language_filter) + 3:]
        
        # Detect content type
        movie_keywords = config.get("movie_keywords", ["movie", "film"])
        tv_keywords = config.get("tv_keywords", ["tv", "show", "series"])
        
        if is_tv_show(title, tv_keywords):
            tv_count += 1
        elif is_movie(title, movie_keywords):
            movie_count += 1
        else:
            if len(unidentified_samples) < 5:
                unidentified_samples.append(title)
            unidentified_content += 1
        
        i += 1
    
    # Prepare results
    results = {
        "total_entries": total_entries,
        "language_skipped": language_skipped,
        "language_skipped_percent": round(language_skipped / total_entries * 100, 2) if total_entries > 0 else 0,
        "unidentified_content": unidentified_content,
        "unidentified_percent": round(unidentified_content / total_entries * 100, 2) if total_entries > 0 else 0,
        "movies_detected": movie_count,
        "tv_shows_detected": tv_count,
        "top_languages": language_prefixes.most_common(10),
        "language_skipped_samples": language_skipped_samples,
        "unidentified_samples": unidentified_samples,
        "config": {
            "language_filter": config.get("language_filter", "None"),
            "skip_non_english": config.get("skip_non_english", False)
        }
    }
    
    return results

def print_results(results):
    """Print analysis results in a readable format"""
    if not results:
        return
        
    print("\n=====================================================")
    print("               M3U FILE ANALYSIS REPORT              ")
    print("=====================================================\n")
    
    print(f"Total entries analyzed: {results['total_entries']}")
    print(f"Current configuration:")
    print(f"  - Language filter: {results['config']['language_filter']}")
    print(f"  - Skip non-matching language: {results['config']['skip_non_english']}")
    print("\n")
    
    print("CONTENT DETECTION:")
    print(f"  - Movies detected: {results['movies_detected']}")
    print(f"  - TV shows detected: {results['tv_shows_detected']}")
    print(f"  - Unidentified content: {results['unidentified_content']} ({results['unidentified_percent']}%)")
    print("\n")
    
    print("LANGUAGE FILTERING:")
    print(f"  - Entries skipped due to language filter: {results['language_skipped']} ({results['language_skipped_percent']}%)")
    print("\n")
    
    print("LANGUAGE DISTRIBUTION:")
    for lang, count in results['top_languages']:
        print(f"  - {lang}: {count} entries")
    print("\n")
    
    if results['language_skipped_samples']:
        print("SAMPLE ENTRIES SKIPPED DUE TO LANGUAGE FILTER:")
        for sample in results['language_skipped_samples']:
            print(f"  - {sample}")
        print("\n")
    
    if results['unidentified_samples']:
        print("SAMPLE UNIDENTIFIED CONTENT:")
        for sample in results['unidentified_samples']:
            print(f"  - {sample}")
        print("\n")
    
    print("RECOMMENDATIONS:")
    if results['language_skipped_percent'] > 50:
        print("  ⚠️ High percentage of content is being skipped due to language filtering.")
        print("     Consider disabling 'skip_non_english' in settings if you want this content.")
    
    if results['unidentified_percent'] > 10:
        print("  ⚠️ Significant amount of content could not be identified as movies or TV shows.")
        print("     Consider adjusting your movie and TV keywords in settings.")
    
    print("\n=====================================================\n")

def main():
    parser = argparse.ArgumentParser(description="Analyze M3U files to determine what content is being skipped")
    parser.add_argument("file", help="Path to the M3U file")
    parser.add_argument("--config", help="Path to config.json file", default="data/config.json")
    parser.add_argument("--output", help="Output file for JSON results")
    
    args = parser.parse_args()
    
    # Load config
    config = load_config(args.config)
    
    # Analyze file
    results = analyze_m3u(args.file, config)
    
    if not results:
        return
    
    # Print results
    print_results(results)
    
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
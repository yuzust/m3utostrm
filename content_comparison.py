import os
import json
import hashlib
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class ProviderManager:
    """Manages M3U providers and their friendly names"""
    
    def __init__(self, providers_path="data/providers.json"):
        self.providers_path = providers_path
        self.providers = self._load_providers()
        
    def _load_providers(self):
        """Load existing providers"""
        if os.path.exists(self.providers_path):
            try:
                with open(self.providers_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading providers: {str(e)}")
                return {}
        else:
            return {}
        
    def _save_providers(self):
        """Save providers to disk"""
        os.makedirs(os.path.dirname(self.providers_path), exist_ok=True)
        with open(self.providers_path, 'w') as f:
            json.dump(self.providers, f, indent=2)
    
    def get_provider_name(self, url):
        """Get friendly name for a provider URL"""
        # Create a unique ID for the URL
        url_id = hashlib.md5(url.encode()).hexdigest()[:8]
        
        # Check if we already have a name for this provider
        if url_id in self.providers:
            return self.providers[url_id]["name"]
        
        # No name yet, generate one based on the URL
        url_parts = url.split("/")
        domain = url_parts[2] if len(url_parts) > 2 else "unknown"
        # Remove www. if present and get the domain name
        if domain.startswith("www."):
            domain = domain[4:]
        # Extract just the domain without TLD
        domain_parts = domain.split('.')
        base_name = domain_parts[0] if domain_parts else "provider"
        
        # Create a new provider entry
        provider_name = f"{base_name.title()} {url_id}"
        self.providers[url_id] = {
            "url": url,
            "name": provider_name,
            "first_seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        self._save_providers()
        return provider_name
    
    def set_provider_name(self, url, name):
        """Set a custom name for a provider"""
        url_id = hashlib.md5(url.encode()).hexdigest()[:8]
        
        if url_id in self.providers:
            self.providers[url_id]["name"] = name
        else:
            self.providers[url_id] = {
                "url": url,
                "name": name,
                "first_seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        self._save_providers()
        return name
    
    def get_all_providers(self):
        """Get all registered providers"""
        return self.providers
    
    def update_content_count(self, url, count_to_add=1):
        """Update the content count for a provider"""
        url_id = hashlib.md5(url.encode()).hexdigest()[:8]
        
        if url_id in self.providers:
            current_count = self.providers[url_id].get("content_count", 0)
            self.providers[url_id]["content_count"] = current_count + count_to_add
            self.providers[url_id]["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._save_providers()
            logger.info(f"Updated content count for provider {self.providers[url_id]['name']}: {current_count} -> {current_count + count_to_add}")
        return

class ContentRegistry:
    """A registry to track and compare content across multiple M3U providers"""
    
    def __init__(self, registry_path="data/content_registry.json"):
        self.registry_path = registry_path
        self.registry = self._load_registry()
        self.provider_manager = ProviderManager()
        
    def _load_registry(self):
        """Load existing content registry"""
        if os.path.exists(self.registry_path):
            try:
                with open(self.registry_path, 'r') as f:
                    registry = json.load(f)
                    # Make sure we have the correct structure
                    if "movies" not in registry:
                        registry["movies"] = {}
                    if "tv_shows" not in registry:
                        registry["tv_shows"] = {}
                    if "providers" not in registry:
                        registry["providers"] = {}
                    return registry
            except Exception as e:
                logger.error(f"Error loading content registry: {str(e)}")
                return {"movies": {}, "tv_shows": {}, "providers": {}}
        else:
            return {"movies": {}, "tv_shows": {}, "providers": {}}
        
    def _save_registry(self):
        """Save content registry to disk"""
        os.makedirs(os.path.dirname(self.registry_path), exist_ok=True)
        with open(self.registry_path, 'w') as f:
            json.dump(self.registry, f, indent=2)
            
    def generate_content_hash(self, title, year=None, season=None, episode=None):
        """Generate a unique hash for content based on its metadata"""
        content_str = title.lower().strip()
        if year:
            content_str += f"_{year}"
        if season and episode:
            content_str += f"_s{season}e{episode}"
        return hashlib.md5(content_str.encode()).hexdigest()
        
    def content_exists(self, content_type, title, year=None, season=None, episode=None):
        """Check if content already exists in the registry"""
        content_hash = self.generate_content_hash(title, year, season, episode)
        
        if content_type == "movie":
            return content_hash in self.registry["movies"]
        elif content_type == "tv_show":
            return content_hash in self.registry["tv_shows"]
        return False
    
    def get_provider_id(self, provider_url):
        """Get or create a provider ID"""
        if not provider_url:
            return None
            
        provider_id = hashlib.md5(provider_url.encode()).hexdigest()[:8]
        
        # Register the provider if it's new
        if provider_id not in self.registry["providers"]:
            provider_name = self.provider_manager.get_provider_name(provider_url)
            self.registry["providers"][provider_id] = {
                "url": provider_url,
                "name": provider_name,
                "first_seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "content_count": 0
            }
            self._save_registry()
        
        return provider_id
    
    def get_content_resolution(self, content_type, title, year=None, season=None, episode=None):
        """Get the current resolution of content"""
        content_hash = self.generate_content_hash(title, year, season, episode)
        
        if content_type == "movie" and content_hash in self.registry["movies"]:
            return self.registry["movies"][content_hash].get("resolution", "")
        elif content_type == "tv_show" and content_hash in self.registry["tv_shows"]:
            return self.registry["tv_shows"][content_hash].get("resolution", "")
        return ""
    
    def _is_better_resolution(self, new_res, current_res):
        """Check if new resolution is better than current"""
        res_rank = {"2160p": 4, "1080p": 3, "720p": 2, "480p": 1, "": 0}
        new_rank = res_rank.get(new_res, 0)
        current_rank = res_rank.get(current_res, 0)
        return new_rank > current_rank
    
    def get_provider_name(self, provider_url):
        """Get friendly name for a provider URL"""
        if not provider_url:
            return "Unknown"
            
        provider_id = self.get_provider_id(provider_url)
        if provider_id and provider_id in self.registry["providers"]:
            return self.registry["providers"][provider_id]["name"]
        return "Unknown"
    
    def register_content(self, content_type, title, url, filepath, provider_url, year=None, season=None, episode=None, resolution=None):
        """Register new content in the registry"""
        content_hash = self.generate_content_hash(title, year, season, episode)
        provider_id = self.get_provider_id(provider_url) if provider_url else None
        provider_name = self.registry["providers"][provider_id]["name"] if provider_id and provider_id in self.registry["providers"] else "Unknown"
        
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Prepare content info
        if content_type == "movie":
            if content_hash not in self.registry["movies"]:
                # New content
                self.registry["movies"][content_hash] = {
                    "title": title,
                    "filepath": filepath,
                    "year": year,
                    "resolution": resolution,
                    "first_added": now,
                    "providers": {},
                    "preferred_provider": provider_id
                }
            
            # Add or update provider for this content
            if provider_id:
                self.registry["movies"][content_hash]["providers"][provider_id] = {
                    "url": url,
                    "added": now,
                    "last_updated": now
                }
            self.registry["movies"][content_hash]["last_updated"] = now
            
            # If this is the first provider or has better resolution, make it preferred
            current_res = self.registry["movies"][content_hash].get("resolution", "")
            if (not self.registry["movies"][content_hash]["preferred_provider"] or 
                (resolution and self._is_better_resolution(resolution, current_res))):
                self.registry["movies"][content_hash]["preferred_provider"] = provider_id
                self.registry["movies"][content_hash]["resolution"] = resolution
            
        elif content_type == "tv_show":
            if content_hash not in self.registry["tv_shows"]:
                # New content
                self.registry["tv_shows"][content_hash] = {
                    "title": title,
                    "filepath": filepath,
                    "season": season,
                    "episode": episode,
                    "resolution": resolution,
                    "first_added": now,
                    "providers": {},
                    "preferred_provider": provider_id
                }
            
            # Add or update provider for this content
            if provider_id:
                self.registry["tv_shows"][content_hash]["providers"][provider_id] = {
                    "url": url,
                    "added": now,
                    "last_updated": now
                }
            self.registry["tv_shows"][content_hash]["last_updated"] = now
            
            # If this is the first provider or has better resolution, make it preferred
            current_res = self.registry["tv_shows"][content_hash].get("resolution", "")
            if (not self.registry["tv_shows"][content_hash]["preferred_provider"] or 
                (resolution and self._is_better_resolution(resolution, current_res))):
                self.registry["tv_shows"][content_hash]["preferred_provider"] = provider_id
                self.registry["tv_shows"][content_hash]["resolution"] = resolution
        
        # Update provider content count
        if provider_id:
            self.registry["providers"][provider_id]["content_count"] = self.registry["providers"][provider_id].get("content_count", 0) + 1
            self.registry["providers"][provider_id]["last_updated"] = now
            
        self._save_registry()
        return {
            "content_hash": content_hash, 
            "provider_id": provider_id,
            "provider_name": provider_name
        }
    
    def update_content(self, content_type, title, url, filepath, provider_url, year=None, season=None, episode=None, resolution=None):
        """Update existing content with new URL and possibly better resolution"""
        content_hash = self.generate_content_hash(title, year, season, episode)
        provider_id = self.get_provider_id(provider_url) if provider_url else None
        
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        updated = False
        
        if content_type == "movie" and content_hash in self.registry["movies"]:
            # Update URL and resolution if better
            if resolution:
                current_res = self.registry["movies"][content_hash].get("resolution", "")
                if self._is_better_resolution(resolution, current_res):
                    self.registry["movies"][content_hash]["resolution"] = resolution
                    self.registry["movies"][content_hash]["preferred_provider"] = provider_id
                    updated = True
            
            # Add or update provider for this content
            if provider_id:
                self.registry["movies"][content_hash]["providers"][provider_id] = {
                    "url": url,
                    "added": now if provider_id not in self.registry["movies"][content_hash]["providers"] else self.registry["movies"][content_hash]["providers"][provider_id].get("added", now),
                    "last_updated": now
                }
            
            # Update last_updated timestamp
            self.registry["movies"][content_hash]["last_updated"] = now
                
        elif content_type == "tv_show" and content_hash in self.registry["tv_shows"]:
            # Update URL and resolution if better
            if resolution:
                current_res = self.registry["tv_shows"][content_hash].get("resolution", "")
                if self._is_better_resolution(resolution, current_res):
                    self.registry["tv_shows"][content_hash]["resolution"] = resolution
                    self.registry["tv_shows"][content_hash]["preferred_provider"] = provider_id
                    updated = True
            
            # Add or update provider for this content
            if provider_id:
                self.registry["tv_shows"][content_hash]["providers"][provider_id] = {
                    "url": url,
                    "added": now if provider_id not in self.registry["tv_shows"][content_hash]["providers"] else self.registry["tv_shows"][content_hash]["providers"][provider_id].get("added", now),
                    "last_updated": now
                }
            
            # Update last_updated timestamp
            self.registry["tv_shows"][content_hash]["last_updated"] = now
        
        # Update provider information
        if provider_id and provider_id in self.registry["providers"]:
            self.registry["providers"][provider_id]["last_updated"] = now
            # Only increment content count if this is a new relationship between content and provider
            if ((content_type == "movie" and content_hash in self.registry["movies"] and 
                 provider_id not in self.registry["movies"][content_hash]["providers"]) or
                (content_type == "tv_show" and content_hash in self.registry["tv_shows"] and 
                 provider_id not in self.registry["tv_shows"][content_hash]["providers"])):
                self.registry["providers"][provider_id]["content_count"] = self.registry["providers"][provider_id].get("content_count", 0) + 1
        
        self._save_registry()
        return updated
    
    def add_provider_to_content(self, content_type, title, url, provider_url, year=None, season=None, episode=None, resolution=None):
        """Add a provider as a source for existing content without changing preferred provider"""
        if not provider_url:
            return False
            
        content_hash = self.generate_content_hash(title, year, season, episode)
        provider_id = self.get_provider_id(provider_url)
        
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        added = False
        
        if content_type == "movie" and content_hash in self.registry["movies"]:
            # Check if this provider is already registered for this content
            if provider_id not in self.registry["movies"][content_hash]["providers"]:
                # Add new provider
                self.registry["movies"][content_hash]["providers"][provider_id] = {
                    "url": url,
                    "added": now,
                    "last_updated": now
                }
                
                # Update provider content count
                self.registry["providers"][provider_id]["content_count"] = self.registry["providers"][provider_id].get("content_count", 0) + 1
                self.registry["providers"][provider_id]["last_updated"] = now
                
                added = True
            else:
                # Update existing provider entry
                self.registry["movies"][content_hash]["providers"][provider_id]["last_updated"] = now
                if self.registry["movies"][content_hash]["providers"][provider_id]["url"] != url:
                    self.registry["movies"][content_hash]["providers"][provider_id]["url"] = url
                    added = True
                
        elif content_type == "tv_show" and content_hash in self.registry["tv_shows"]:
            # Check if this provider is already registered for this content
            if provider_id not in self.registry["tv_shows"][content_hash]["providers"]:
                # Add new provider
                self.registry["tv_shows"][content_hash]["providers"][provider_id] = {
                    "url": url,
                    "added": now,
                    "last_updated": now
                }
                
                # Update provider content count
                self.registry["providers"][provider_id]["content_count"] = self.registry["providers"][provider_id].get("content_count", 0) + 1
                self.registry["providers"][provider_id]["last_updated"] = now
                
                added = True
            else:
                # Update existing provider entry
                self.registry["tv_shows"][content_hash]["providers"][provider_id]["last_updated"] = now
                if self.registry["tv_shows"][content_hash]["providers"][provider_id]["url"] != url:
                    self.registry["tv_shows"][content_hash]["providers"][provider_id]["url"] = url
                    added = True
        
        if added:
            self._save_registry()
            
        return added
    
    def get_preferred_url(self, content_type, title, year=None, season=None, episode=None):
        """Get the preferred URL for content"""
        content_hash = self.generate_content_hash(title, year, season, episode)
        
        if content_type == "movie" and content_hash in self.registry["movies"]:
            content = self.registry["movies"][content_hash]
            preferred_id = content.get("preferred_provider", "")
            if preferred_id and preferred_id in content["providers"]:
                return content["providers"][preferred_id]["url"]
        elif content_type == "tv_show" and content_hash in self.registry["tv_shows"]:
            content = self.registry["tv_shows"][content_hash]
            preferred_id = content.get("preferred_provider", "")
            if preferred_id and preferred_id in content["providers"]:
                return content["providers"][preferred_id]["url"]
        return None
    
    def get_content_stats(self):
        """Get statistics about content and providers"""
        stats = {
            "total_movies": len(self.registry["movies"]),
            "total_tv_shows": len(self.registry["tv_shows"]),
            "total_providers": len(self.registry["providers"]),
            "providers": []
        }
        
        for provider_id, provider in self.registry["providers"].items():
            stats["providers"].append({
                "id": provider_id,
                "name": provider["name"],
                "content_count": provider.get("content_count", 0),
                "url": provider["url"]
            })
        
        return stats
    
    def get_all_content(self):
        """Get all registered content"""
        return self.registry
    
    def get_content_provider_info(self, content_type, title, year=None, season=None, episode=None):
        """Get information about providers for specific content"""
        content_hash = self.generate_content_hash(title, year, season, episode)
        
        if content_type == "movie" and content_hash in self.registry["movies"]:
            content = self.registry["movies"][content_hash]
            preferred_id = content.get("preferred_provider", "")
            return {
                "content_hash": content_hash,
                "preferred_provider": preferred_id,
                "preferred_provider_name": self.registry["providers"].get(preferred_id, {}).get("name", "Unknown") if preferred_id else "Unknown",
                "providers": len(content["providers"]),
                "resolution": content.get("resolution", "")
            }
        elif content_type == "tv_show" and content_hash in self.registry["tv_shows"]:
            content = self.registry["tv_shows"][content_hash]
            preferred_id = content.get("preferred_provider", "")
            return {
                "content_hash": content_hash,
                "preferred_provider": preferred_id,
                "preferred_provider_name": self.registry["providers"].get(preferred_id, {}).get("name", "Unknown") if preferred_id else "Unknown",
                "providers": len(content["providers"]),
                "resolution": content.get("resolution", "")
            }
        return None

def get_provider_stats():
    """Get statistics about providers"""
    registry = ContentRegistry()
    return registry.get_content_stats()

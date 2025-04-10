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
        if not url:
            return "Unknown"
            
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
        if not url:
            return name
            
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
        if not url:
            return
            
        url_id = hashlib.md5(url.encode()).hexdigest()[:8]
        
        if url_id in self.providers:
            current_count = self.providers[url_id].get("content_count", 0)
            self.providers[url_id]["content_count"] = current_count + count_to_add
            self.providers[url_id]["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._save_providers()
            logger.info(f"Updated content count for provider {self.providers[url_id]['name']}: {current_count} -> {current_count + count_to_add}")
        else:
            # Provider doesn't exist yet, create it
            provider_name = self.get_provider_name(url)
            self.providers[url_id]["content_count"] = count_to_add
            self._save_providers()
            logger.info(f"Set initial content count for provider {provider_name}: {count_to_add}")

def get_provider_stats():
    """Get statistics about providers"""
    from content_comparison import ContentRegistry
    registry = ContentRegistry()
    return registry.get_content_stats()

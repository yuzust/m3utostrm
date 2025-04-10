import time
import threading
import logging
from datetime import datetime
import json
import os

logger = logging.getLogger(__name__)

class ProcessingMonitor:
    """Monitor and track the status of processing jobs"""
    
    def __init__(self, timeout_seconds=300):
        """Initialize the monitor with a timeout value (default 5 minutes)"""
        self.active_jobs = {}
        self.timeout_seconds = timeout_seconds
        self.lock = threading.Lock()
        self.jobs_history = []
        self.max_history = 20
        
        # Ensure the status directory exists
        os.makedirs('data/status', exist_ok=True)
        self.status_file = 'data/status/processing_status.json'
        
        # Load any existing status
        self._load_status()
        
        # Start the monitoring thread
        self.monitor_thread = threading.Thread(target=self._monitor_thread, daemon=True)
        self.monitor_thread.start()
    
    def _load_status(self):
        """Load processing status from file"""
        try:
            if os.path.exists(self.status_file):
                with open(self.status_file, 'r') as f:
                    data = json.load(f)
                    self.jobs_history = data.get('history', [])
        except Exception as e:
            logger.error(f"Error loading status file: {e}")
            self.jobs_history = []
    
    def _save_status(self):
        """Save processing status to file"""
        try:
            status_data = {
                'active': list(self.active_jobs.values()),
                'history': self.jobs_history
            }
            
            with open(self.status_file, 'w') as f:
                json.dump(status_data, f)
        except Exception as e:
            logger.error(f"Error saving status file: {e}")
    
    def start_job(self, job_id, description):
        """Register the start of a new processing job"""
        with self.lock:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            job_info = {
                'id': job_id,
                'description': description,
                'status': 'running',
                'start_time': now,
                'last_update': now,
                'elapsed_seconds': 0,
                'current_item': None,
                'items_processed': 0,
                'errors': 0
            }
            
            self.active_jobs[job_id] = job_info
            self._save_status()
            return job_info
    
    def update_job(self, job_id, current_item=None, items_processed=None, errors=None, status=None):
        """Update the status of an active job"""
        with self.lock:
            if job_id not in self.active_jobs:
                return None
            
            job_info = self.active_jobs[job_id]
            job_info['last_update'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            if current_item is not None:
                job_info['current_item'] = current_item
            
            if items_processed is not None:
                job_info['items_processed'] = items_processed
            
            if errors is not None:
                job_info['errors'] = errors
            
            if status is not None:
                job_info['status'] = status
            
            # Calculate elapsed time
            start_time = datetime.strptime(job_info['start_time'], "%Y-%m-%d %H:%M:%S")
            elapsed = (datetime.now() - start_time).total_seconds()
            job_info['elapsed_seconds'] = int(elapsed)
            
            self._save_status()
            return job_info
    
    def complete_job(self, job_id, status='completed', error=None):
        """Mark a job as completed and move it to history"""
        with self.lock:
            if job_id not in self.active_jobs:
                return
            
            job_info = self.active_jobs[job_id]
            job_info['status'] = status
            job_info['end_time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            if error:
                job_info['error'] = str(error)
            
            # Calculate elapsed time
            start_time = datetime.strptime(job_info['start_time'], "%Y-%m-%d %H:%M:%S")
            elapsed = (datetime.now() - start_time).total_seconds()
            job_info['elapsed_seconds'] = int(elapsed)
            
            # Add to history and maintain max history size
            self.jobs_history.insert(0, job_info)
            self.jobs_history = self.jobs_history[:self.max_history]
            
            # Remove from active jobs
            del self.active_jobs[job_id]
            self._save_status()
    
    def get_active_jobs(self):
        """Get all active jobs"""
        with self.lock:
            return list(self.active_jobs.values())
    
    def get_job(self, job_id):
        """Get a specific job by ID"""
        with self.lock:
            if job_id in self.active_jobs:
                return self.active_jobs[job_id]
            
            # Check history
            for job in self.jobs_history:
                if job['id'] == job_id:
                    return job
            
            return None
    
    def get_job_history(self):
        """Get the job history"""
        with self.lock:
            return self.jobs_history.copy()
    
    def _monitor_thread(self):
        """Background thread to monitor for stuck jobs"""
        while True:
            try:
                now = datetime.now()
                stuck_jobs = []
                
                with self.lock:
                    for job_id, job_info in list(self.active_jobs.items()):
                        last_update = datetime.strptime(job_info['last_update'], "%Y-%m-%d %H:%M:%S")
                        elapsed = (now - last_update).total_seconds()
                        
                        # Mark as stuck if timeout exceeded
                        if elapsed > self.timeout_seconds and job_info['status'] == 'running':
                            job_info['status'] = 'stuck'
                            stuck_jobs.append(job_info)
                            logger.warning(f"Job {job_id} appears to be stuck (no updates for {elapsed:.1f} seconds)")
                
                # No need to hold the lock while logging
                for job in stuck_jobs:
                    logger.error(f"Stuck job detected: {job['id']} - {job['description']} - Last item: {job['current_item']}")
                
                # Save status if there were changes
                if stuck_jobs:
                    self._save_status()
                
                # Check every 30 seconds
                time.sleep(30)
            except Exception as e:
                logger.error(f"Error in monitor thread: {e}")
                time.sleep(30)  # Still sleep on error

# Global instance
processing_monitor = ProcessingMonitor(timeout_seconds=300)
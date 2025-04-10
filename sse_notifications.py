from flask import Response, stream_with_context
import json
import time
import threading
import queue
import logging

logger = logging.getLogger(__name__)

class SSEManager:
    """Manager for Server-Sent Events (SSE) notifications"""
    
    def __init__(self):
        self.clients = []
        self.lock = threading.Lock()
        self.keep_alive_thread = threading.Thread(target=self._keep_alive_thread, daemon=True)
        self.keep_alive_thread.start()
    
    def register_client(self, client_queue):
        """Register a new client"""
        with self.lock:
            self.clients.append(client_queue)
            logger.debug(f"Client registered, total clients: {len(self.clients)}")
    
    def remove_client(self, client_queue):
        """Remove a client"""
        with self.lock:
            if client_queue in self.clients:
                self.clients.remove(client_queue)
                logger.debug(f"Client removed, remaining clients: {len(self.clients)}")
    
    def send_message(self, event_type, data):
        """Send a message to all connected clients"""
        message = {
            "type": event_type,
            "data": data
        }
        
        with self.lock:
            dead_clients = []
            
            for client_queue in self.clients:
                try:
                    client_queue.put_nowait(message)
                except queue.Full:
                    # Queue is full, client might be dead
                    dead_clients.append(client_queue)
            
            # Remove dead clients
            for dead_client in dead_clients:
                if dead_client in self.clients:
                    self.clients.remove(dead_client)
            
            logger.debug(f"Message sent to {len(self.clients)} clients, type: {event_type}")
    
    def _keep_alive_thread(self):
        """Send keep-alive messages to prevent connection timeouts"""
        while True:
            try:
                # Send a comment every 30 seconds as a keep-alive
                with self.lock:
                    for client_queue in self.clients:
                        try:
                            client_queue.put_nowait({"type": "ping", "data": ""})
                        except queue.Full:
                            pass  # Will be handled in next send_message
                
                time.sleep(30)
            except Exception as e:
                logger.error(f"Error in keep-alive thread: {e}")
                time.sleep(30)  # Still sleep on error

# Global instance
sse_manager = SSEManager()

def get_sse_response():
    """Create a response for SSE"""
    def event_stream():
        client_queue = queue.Queue(maxsize=100)
        sse_manager.register_client(client_queue)
        
        try:
            # Send initial message
            yield 'data: {"type":"connected","data":"Connection established"}\n\n'
            
            while True:
                try:
                    message = client_queue.get(timeout=60)
                    
                    if message["type"] == "ping":
                        # Send comment as keep-alive
                        yield ': ping\n\n'
                    else:
                        # Format as SSE event
                        yield f'event: {message["type"]}\n'
                        yield f'data: {json.dumps(message["data"])}\n\n'
                except queue.Empty:
                    # Send a comment to keep the connection alive
                    yield ': keep-alive\n\n'
        except GeneratorExit:
            # Client disconnected
            sse_manager.remove_client(client_queue)
            
        # Also remove on return
        sse_manager.remove_client(client_queue)
    
    return Response(
        stream_with_context(event_stream()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no'  # For Nginx
        }
    )

def send_notification(title, message, type="info", details=None):
    """Helper to send a notification to all clients"""
    sse_manager.send_message("notification", {
        "title": title,
        "message": message,
        "type": type,  # info, success, warning, error
        "timestamp": time.time(),
        "details": details
    })

def send_status_update(status_data):
    """Helper to send a processing status update to all clients"""
    sse_manager.send_message("status_update", status_data)
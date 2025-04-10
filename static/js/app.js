// Script for M3U to STRM Converter

document.addEventListener('DOMContentLoaded', function() {
    // Flash message auto-hide
    const flashMessages = document.querySelectorAll('.alert');
    flashMessages.forEach(message => {
        setTimeout(() => {
            message.style.opacity = '0';
            message.style.transition = 'opacity 0.5s ease';
            setTimeout(() => {
                message.style.display = 'none';
            }, 500);
        }, 5000);
    });

    // File input enhancement
    const fileInputs = document.querySelectorAll('input[type="file"]');
    fileInputs.forEach(input => {
        input.addEventListener('change', function() {
            const fileName = this.files[0]?.name || 'No file chosen';
            const fileLabel = this.nextElementSibling;
            if (fileLabel && fileLabel.classList.contains('file-label')) {
                fileLabel.textContent = fileName;
            }
        });
    });

    // Form validation
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        form.addEventListener('submit', function(event) {
            const requiredInputs = form.querySelectorAll('[required]');
            let isValid = true;
            
            requiredInputs.forEach(input => {
                if (!input.value.trim()) {
                    isValid = false;
                    input.classList.add('is-invalid');
                } else {
                    input.classList.remove('is-invalid');
                }
            });
            
            if (!isValid) {
                event.preventDefault();
                // Show validation message
                const validationAlert = document.createElement('div');
                validationAlert.className = 'alert alert-danger';
                validationAlert.textContent = 'Please fill in all required fields.';
                form.insertBefore(validationAlert, form.firstChild);
                
                // Auto-remove after 3 seconds
                setTimeout(() => {
                    validationAlert.remove();
                }, 3000);
            }
        });
    });

    // Theme toggle functionality
    const themeToggle = document.getElementById('theme-toggle');
    if (themeToggle) {
        themeToggle.addEventListener('change', function() {
            window.location.href = '/theme/' + (this.checked ? 'dark' : 'light');
        });
    }
});

// Confirm delete actions
function confirmDelete(url, message) {
    if (confirm(message || 'Are you sure you want to delete this item?')) {
        window.location.href = url;
    }
    return false;
}

// Copy to clipboard function
function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(
        function() {
            // Success feedback
            const feedbackEl = document.createElement('div');
            feedbackEl.textContent = 'Copied to clipboard!';
            feedbackEl.style.position = 'fixed';
            feedbackEl.style.bottom = '20px';
            feedbackEl.style.left = '50%';
            feedbackEl.style.transform = 'translateX(-50%)';
            feedbackEl.style.backgroundColor = 'var(--success-color)';
            feedbackEl.style.color = 'white';
            feedbackEl.style.padding = '10px 20px';
            feedbackEl.style.borderRadius = '5px';
            feedbackEl.style.zIndex = '1000';
            document.body.appendChild(feedbackEl);
            
            setTimeout(() => {
                feedbackEl.style.opacity = '0';
                feedbackEl.style.transition = 'opacity 0.5s ease';
                setTimeout(() => {
                    document.body.removeChild(feedbackEl);
                }, 500);
            }, 2000);
        }
    );
}

// Add this to your existing app.js file

// SSE connection for notifications
let evtSource = null;

function connectToSSE() {
    // Close existing connection if any
    if (evtSource !== null) {
        evtSource.close();
    }
    
    // Create new connection
    evtSource = new EventSource("/events");
    
    // Listen for notifications
    evtSource.addEventListener("notification", function(e) {
        const data = JSON.parse(e.data);
        showNotification(data.title, data.message, data.type, data.details);
    });
    
    // Listen for status updates
    evtSource.addEventListener("status_update", function(e) {
        const data = JSON.parse(e.data);
        if (typeof updateJobStatus === 'function') {
            updateJobStatus(data);
        }
    });
    
    // Handle connection
    evtSource.addEventListener("connected", function(e) {
        console.log("SSE connection established");
    });
    
    // Handle errors
    evtSource.onerror = function() {
        console.error("SSE connection error");
        // Try to reconnect after 5 seconds
        setTimeout(connectToSSE, 5000);
    };
}

// Create notification container if it doesn't exist
function ensureNotificationContainer() {
    let container = document.getElementById('notifications-container');
    
    if (!container) {
        container = document.createElement('div');
        container.id = 'notifications-container';
        container.style.position = 'fixed';
        container.style.top = '20px';
        container.style.right = '20px';
        container.style.zIndex = '1000';
        container.style.maxWidth = '350px';
        container.style.display = 'flex';
        container.style.flexDirection = 'column';
        container.style.gap = '10px';
        document.body.appendChild(container);
        
        // Add styles if not already present
        if (!document.getElementById('notification-styles')) {
            const style = document.createElement('style');
            style.id = 'notification-styles';
            style.textContent = `
                #notifications-container {
                    position: fixed;
                    top: 20px;
                    right: 20px;
                    z-index: 1000;
                    max-width: 350px;
                    max-height: 80vh;
                    overflow-y: auto;
                    display: flex;
                    flex-direction: column;
                    gap: 10px;
                }
                
                .notification {
                    padding: 15px;
                    border-radius: 8px;
                    background-color: var(--card-bg, #fff);
                    box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
                    animation: slideIn 0.3s ease-out;
                    border-left: 4px solid;
                    position: relative;
                }
                
                .notification.info {
                    border-left-color: var(--info-color, #5ac8fa);
                }
                
                .notification.success {
                    border-left-color: var(--success-color, #34c759);
                }
                
                .notification.warning {
                    border-left-color: var(--warning-color, #ffcc00);
                }
                
                .notification.error {
                    border-left-color: var(--danger-color, #ff3b30);
                }
                
                .notification-title {
                    font-weight: 600;
                    margin-bottom: 5px;
                    padding-right: 20px;
                }
                
                .notification-message {
                    font-size: 0.9rem;
                    word-break: break-word;
                }
                
                .notification-close {
                    position: absolute;
                    top: 10px;
                    right: 10px;
                    background: none;
                    border: none;
                    color: var(--text-color, #000);
                    opacity: 0.5;
                    cursor: pointer;
                    padding: 0;
                    font-size: 1rem;
                }
                
                .notification-close:hover {
                    opacity: 1;
                }
                
                @keyframes slideIn {
                    from {
                        transform: translateX(100%);
                        opacity: 0;
                    }
                    to {
                        transform: translateX(0);
                        opacity: 1;
                    }
                }
                
                @keyframes fadeOut {
                    from {
                        opacity: 1;
                    }
                    to {
                        opacity: 0;
                    }
                }
            `;
            document.head.appendChild(style);
        }
    }
    
    return container;
}

function showNotification(title, message, type = "info", details = null) {
    const container = ensureNotificationContainer();
    
    // Create notification element
    const notif = document.createElement('div');
    notif.className = `notification ${type}`;
    
    // Add content
    notif.innerHTML = `
        <div class="notification-title">${title}</div>
        <div class="notification-message">${message}</div>
        <button class="notification-close">&times;</button>
    `;
    
    // Add details if provided
    if (details) {
        const detailsEl = document.createElement('div');
        detailsEl.className = 'notification-details';
        detailsEl.innerHTML = '<hr>';
        
        for (const [key, value] of Object.entries(details)) {
            detailsEl.innerHTML += `<div><strong>${key}:</strong> ${value}</div>`;
        }
        
        notif.appendChild(detailsEl);
    }
    
    // Add to container
    container.appendChild(notif);
    
    // Set up close button
    notif.querySelector('.notification-close').addEventListener('click', function() {
        closeNotification(notif);
    });
    
    // Auto-close after 10 seconds for non-error notifications
    if (type !== 'error') {
        setTimeout(function() {
            closeNotification(notif);
        }, 10000);
    }
}

function closeNotification(notif) {
    notif.style.animation = 'fadeOut 0.3s ease-out forwards';
    setTimeout(function() {
        if (notif.parentNode) {
            notif.parentNode.removeChild(notif);
        }
    }, 300);
}

// Connect to SSE when the document is loaded
document.addEventListener('DOMContentLoaded', function() {
    connectToSSE();
});